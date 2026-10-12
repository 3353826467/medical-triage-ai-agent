"""智能分诊链路：症状 → 科室 + 紧急度 + 可能情况。"""
from __future__ import annotations

from typing import AsyncIterator

from app.chains.base import ChainContext, ChainResult
from app.chains.prompts import SYSTEM_BASE, TRIAGE_SYSTEM, profile_text
from app.chains.rules import match_rules
from app.config import get_settings
from app.llm.provider import ChatBackend, Message
from app.safety import guard
from app.schemas import PossibleCondition, TriageResult, Urgency
from app.utils.text import truncate

_VALID_URGENCY = {u.value for u in Urgency}


def _normalize_result(data: dict, disclaimer: str) -> TriageResult:
    urgency_raw = str(data.get("urgency", "routine")).lower().strip()
    urgency = Urgency(urgency_raw) if urgency_raw in _VALID_URGENCY else Urgency.ROUTINE

    conditions: list[PossibleCondition] = []
    for item in (data.get("possible_conditions") or [])[:5]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        prob = str(item.get("probability", "low")).lower().strip()
        if prob not in ("high", "medium", "low"):
            prob = "low"
        conditions.append(
            PossibleCondition(name=truncate(name, 40), probability=prob,
                              reason=truncate(str(item.get("reason", "")), 80))
        )

    def _list(key: str, limit: int, size: int = 120) -> list[str]:
        items = data.get(key) or []
        if not isinstance(items, list):
            return []
        return [truncate(str(x), size) for x in items if str(x).strip()][:limit]

    return TriageResult(
        department=str(data.get("department") or "全科医学科"),
        department_aliases=_list("department_aliases", 3, 20),
        urgency=urgency,
        urgency_reason=truncate(str(data.get("urgency_reason", "")), 120),
        possible_conditions=conditions,
        advice=_list("advice", 5),
        followup_questions=_list("followup_questions", 3),
        red_flags=_list("red_flags", 5, 60),
        need_more_info=bool(data.get("need_more_info", False)),
        disclaimer=disclaimer,
    )


def _rule_result(ctx: ChainContext, disclaimer: str) -> TriageResult:
    hits = match_rules(ctx.message)
    if not hits:
        return TriageResult(
            department="全科医学科",
            department_aliases=("全科", "普通内科"),
            urgency=Urgency.ROUTINE,
            urgency_reason="主诉较泛化，未见明确急症指征，建议全科初筛。",
            advice=[
                "补充症状部位、持续时间与伴随表现，有助于准确分诊",
                "如出现胸痛、呼吸困难、意识改变等，请立即拨打 120",
                "症状持续或加重时请及时线下就诊",
            ],
            followup_questions=[
                "最主要的症状是什么？持续多久了？",
                "有没有发热、疼痛或其他伴随症状？",
            ],
            need_more_info=True,
            disclaimer=disclaimer,
        )

    top = hits[0]
    conditions = list(top.conditions)
    for extra in hits[1:3]:
        for cond in extra.conditions[:1]:
            if cond.name not in {c.name for c in conditions}:
                conditions.append(cond)

    return TriageResult(
        department=top.department,
        department_aliases=list(top.aliases),
        urgency=top.urgency,
        urgency_reason="依据主诉关键词与常规分诊规则匹配。",
        possible_conditions=conditions[:5],
        advice=list(top.advice),
        followup_questions=list(top.questions),
        red_flags=[],
        need_more_info=True,
        disclaimer=disclaimer,
    )


def _build_messages(ctx: ChainContext) -> list[Message]:
    history_text = "\n".join(
        f"{'患者' if m['role'] == 'user' else '客服'}: {m['content']}" for m in ctx.history[-8:]
    )
    user_prompt = (
        f"【患者基础信息】{profile_text(ctx.profile)}\n"
        f"【对话历史】\n{history_text or '（无）'}\n"
        f"【本次主诉】{ctx.message}\n\n"
        f"【知识库参考片段】\n{ctx.rag_context}\n\n"
        "请按 Schema 输出 JSON。"
    )
    return [
        {"role": "system", "content": SYSTEM_BASE + "\n" + TRIAGE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


def _render_answer(result: TriageResult) -> str:
    urgency_label = {
        Urgency.EMERGENCY: "🔴 紧急（立即就医 / 120）",
        Urgency.URGENT: "🟠 尽快就诊（24 小时内）",
        Urgency.ROUTINE: "🟢 门诊择期就诊",
        Urgency.SELF_CARE: "🔵 居家观察护理",
    }[result.urgency]

    lines = []
    if result.urgency is Urgency.EMERGENCY:
        lines.append("⚠️ **请立即拨打 120 或前往急诊**，不要自行判断、不要自行驾车。")
        lines.append("")
    lines.append(f"**建议首诊科室**：{result.department}")
    lines.append(f"**紧急程度**：{urgency_label}")
    if result.urgency_reason:
        lines.append(f"**判定依据**：{result.urgency_reason}")

    if result.possible_conditions:
        lines.append("")
        lines.append("**可能的情况**")
        prob_cn = {"high": "可能性高", "medium": "可能性中", "low": "可能性低"}
        for c in result.possible_conditions:
            tail = f"——{c.reason}" if c.reason else ""
            lines.append(f"- {c.name}（{prob_cn.get(c.probability, '可能性低')}）{tail}")

    if result.advice:
        lines.append("")
        lines.append("**建议**")
        lines.extend(f"- {a}" for a in result.advice)

    return "\n".join(lines)


async def arun(ctx: ChainContext, backend: ChatBackend | None = None) -> ChainResult:
    settings = get_settings()
    disclaimer = settings.DISCLAIMER
    backend = backend or None

    # 护栏放在链路最内层，而不是只在编排层——否则直接调用本链路的入口
    # （如 /api/v1/triage）会绕过安全检查。
    guard_result = guard.scan(ctx.message)
    if guard_result.triggered:
        answer, result = guard.render_answer(guard_result, disclaimer)
        return ChainResult(answer=answer, triage=result, followup_questions=[])

    if backend is not None and backend.available:
        try:
            data = await backend.ajson(_build_messages(ctx), fast=False)
            if data:
                result = _normalize_result(data, disclaimer)
                return ChainResult(
                    answer=_render_answer(result),
                    triage=result,
                    followup_questions=result.followup_questions,
                )
        except Exception:  # noqa: BLE001
            pass

    result = _rule_result(ctx, disclaimer)
    answer = _render_answer(result)
    if ctx.evidence:
        answer += "\n\n**相关知识库内容**\n\n"
        answer += "\n\n".join(f"- 《{e.title}》：{e.snippet}" for e in ctx.evidence)
    return ChainResult(
        answer=answer,
        triage=result,
        followup_questions=result.followup_questions,
    )


async def astream(ctx: ChainContext, backend: ChatBackend | None = None) -> AsyncIterator[str]:
    """分诊需要先拿到完整结构化结果，因此以分块方式回吐最终文本。"""
    result = await arun(ctx, backend)
    text = result.answer
    step = 24
    for i in range(0, len(text), step):
        yield text[i : i + step]
