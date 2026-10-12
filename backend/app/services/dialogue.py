"""对话编排：安全护栏 → 意图路由 → RAG 检索 → 能力链路 → 结果组装。"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from app.chains import faq, report, symptom, triage
from app.chains.base import ChainContext, ChainResult
from app.chains.router import route_intent
from app.config import get_settings
from app.llm.provider import ChatBackend, get_chat_backend
from app.rag.pipeline import get_rag_engine
from app.safety import guard
from app.schemas import ChatRequest, ChatResponse, Evidence, Intent, TriageResult
from app.services import session as session_store
from app.utils.text import mask_sensitive

CHITCHAT_REPLY = (
    "你好，我是康云互联网医院智能客服「小康」👩‍⚕️\n\n"
    "我可以帮你做这几件事：\n"
    "- 🩺 **症状咨询**：了解症状成因与护理要点\n"
    "- 🚦 **智能分诊**：告诉你应该挂哪个科、要不要马上去医院\n"
    "- 📄 **报告解读**：把化验单、影像报告翻译成大白话\n"
    "- 🏥 **就医服务**：挂号、医保、缴费、检查准备等问题\n\n"
    "直接描述你的不适就行，比如「最近三天咳嗽有黄痰，该挂什么科？」"
)


def _enhance_query(query: str, intent: Intent) -> str:
    """按意图给查询词加权，提升召回命中率。"""
    if intent is Intent.TRIAGE:
        return f"{query} 症状 就诊科室 就医建议"
    if intent is Intent.REPORT:
        return f"{query} 参考区间 指标 解读"
    if intent is Intent.FAQ:
        return f"{query} 就诊流程 医院服务"
    return query


async def _prepare(
    req: ChatRequest,
) -> tuple[session_store.Session, Intent, list[Evidence], ChatBackend]:
    """会话准备 + 意图识别 + 知识检索。"""
    settings = get_settings()
    sess = session_store.store.get_or_create(req.session_id or None)
    session_store.store.merge_profile(sess, req.profile)

    backend = get_chat_backend(settings)
    intent = req.intent or await route_intent(req.message, sess.messages, backend)

    evidence: list[Evidence] = []
    if req.with_evidence:
        engine = get_rag_engine()
        try:
            evidence = await engine.retrieve(_enhance_query(req.message, intent))
        except Exception:  # noqa: BLE001  检索失败不应阻断对话
            evidence = []
    return sess, intent, evidence, backend


def _emergency(guard_result: guard.GuardResult, settings) -> tuple[str, TriageResult]:
    triage_result = guard.build_emergency_result(guard_result, settings.DISCLAIMER)
    answer = guard.EMERGENCY_ANSWER_TEMPLATE.format(
        matched="、".join(sorted({h.matched for h in guard_result.hits})),
        department=triage_result.department,
        conditions="\n".join(f"- {c.name}" for c in triage_result.possible_conditions),
        advice="\n".join(f"{i}. {a}" for i, a in enumerate(triage_result.advice, 1)),
        disclaimer=settings.DISCLAIMER,
    )
    return answer, triage_result


def _scan_text(message: str, history: list[dict[str, str]], intent: Intent) -> str:
    """组装护栏扫描文本。

    两条经验规则：
    1. 只扫**患者侧**文本——助手的免责声明里本身就写着"胸痛/呼吸困难"等
       关键词，扫进去会造成连环误报。
    2. 只有当意图属于"延续性问诊"（triage/symptom）时才回溯历史。
       报告解读、就医服务咨询是新话题，不该被上一轮的症状描述持续拦截。
    """
    if intent in (Intent.TRIAGE, Intent.SYMPTOM):
        prior = [m["content"] for m in history if m.get("role") == "user"][-2:]
        return "\n".join([*prior, message])
    return message


def _finalize(answer: str, settings) -> str:
    """统一追加免责声明，避免模型漏写。"""
    disclaimer = settings.DISCLAIMER
    if disclaimer and disclaimer[:12] not in answer:
        return f"{answer.rstrip()}\n\n---\n*{disclaimer}*"
    return answer


def _chunks(text: str, size: int = 24) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


# --------------------------------------------------------------------------- #
#  非流式
# --------------------------------------------------------------------------- #
async def handle(req: ChatRequest) -> ChatResponse:
    settings = get_settings()
    started = time.perf_counter()

    sess, intent, evidence, backend = await _prepare(req)
    sess.add_turn("user", mask_sensitive(req.message))

    guard_result = guard.scan(_scan_text(req.message, sess.messages, intent))

    triage_result: TriageResult | None = None
    if guard_result.triggered:
        # ① 安全护栏优先：命中危急信号时不再交由模型自由发挥
        answer, triage_result = _emergency(guard_result, settings)
    elif intent is Intent.CHITCHAT:
        answer = CHITCHAT_REPLY
    else:
        ctx = ChainContext(
            session_id=sess.id,
            message=req.message,
            intent=intent,
            profile=sess.profile,
            history=sess.messages,
            evidence=evidence,
        )
        result: ChainResult = await _dispatch(ctx, backend)
        answer, triage_result = result.answer, result.triage

    answer = _finalize(answer, settings)
    sess.add_turn("assistant", answer)

    return ChatResponse(
        session_id=sess.id,
        intent=intent,
        answer=answer,
        triage=triage_result,
        evidence=evidence,
        followup_questions=triage_result.followup_questions if triage_result else [],
        engine=backend.name,
        latency_ms=int((time.perf_counter() - started) * 1000),
        disclaimer=settings.DISCLAIMER,
    )


async def _dispatch(ctx: ChainContext, backend: ChatBackend) -> ChainResult:
    if ctx.intent is Intent.TRIAGE:
        return await triage.arun(ctx, backend)
    if ctx.intent is Intent.SYMPTOM:
        return await symptom.arun(ctx, backend)
    if ctx.intent is Intent.REPORT:
        return await report.arun(ctx, backend)
    if ctx.intent is Intent.FAQ:
        return await faq.arun(ctx, backend)
    return ChainResult(answer=CHITCHAT_REPLY)


# --------------------------------------------------------------------------- #
#  流式（SSE）
# --------------------------------------------------------------------------- #
async def stream_events(req: ChatRequest) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    started = time.perf_counter()

    sess, intent, evidence, backend = await _prepare(req)
    sess.add_turn("user", mask_sensitive(req.message))

    yield {
        "event": "meta",
        "data": {
            "session_id": sess.id,
            "intent": intent.value,
            "engine": backend.name,
            "evidence": [e.model_dump() for e in evidence],
        },
    }

    guard_result = guard.scan(_scan_text(req.message, sess.messages, intent))

    final_triage: TriageResult | None = None
    if guard_result.triggered:
        emergency_answer, triage_result = _emergency(guard_result, settings)
        for piece in _chunks(_finalize(emergency_answer, settings)):
            yield {"event": "delta", "data": piece}
        final_triage = triage_result
    elif intent is Intent.CHITCHAT:
        for piece in _chunks(_finalize(CHITCHAT_REPLY, settings)):
            yield {"event": "delta", "data": piece}
    elif intent is Intent.TRIAGE:
        # 分诊需要结构化卡片，直接取完整结果再分块下发（仅一次模型调用）
        ctx = ChainContext(
            session_id=sess.id,
            message=req.message,
            intent=intent,
            profile=sess.profile,
            history=sess.messages,
            evidence=evidence,
        )
        result = await triage.arun(ctx, backend)
        for piece in _chunks(_finalize(result.answer, settings)):
            yield {"event": "delta", "data": piece}
        final_triage = result.triage
    else:
        ctx = ChainContext(
            session_id=sess.id,
            message=req.message,
            intent=intent,
            profile=sess.profile,
            history=sess.messages,
            evidence=evidence,
        )
        if intent is Intent.REPORT:
            gen = report.astream(ctx, backend)
        elif intent is Intent.FAQ:
            gen = faq.astream(ctx, backend)
        else:
            gen = symptom.astream(ctx, backend)

        buffer: list[str] = []
        async for piece in gen:
            buffer.append(piece)
            yield {"event": "delta", "data": piece}
        sess.add_turn("assistant", _finalize("".join(buffer), settings))

    yield {
        "event": "done",
        "data": {
            "triage": final_triage.model_dump() if final_triage else None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "disclaimer": settings.DISCLAIMER,
        },
    }


def sse_format(payload: dict[str, Any]) -> str:
    """把事件序列化为 SSE 报文。"""
    event = payload.get("event", "message")
    data = payload.get("data", "")
    body = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = [f"event: {event}"]
    lines.extend(f"data: {ln}" for ln in body.split("\n"))
    return "\n".join(lines) + "\n\n"
