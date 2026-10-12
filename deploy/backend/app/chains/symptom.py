"""症状咨询链路：科普 + 自我照护 + 就医警示信号。"""
from __future__ import annotations

from typing import AsyncIterator

from app.chains.base import ChainContext, ChainResult
from app.chains.fallback import render as fallback_render
from app.chains.prompts import SYMPTOM_SYSTEM, SYSTEM_BASE, profile_text
from app.config import get_settings
from app.llm.provider import ChatBackend, Message
from app.safety import guard
from app.utils.text import truncate


def _build_messages(ctx: ChainContext) -> list[Message]:
    history_text = "\n".join(
        f"{'患者' if m['role'] == 'user' else '客服'}: {m['content']}" for m in ctx.history[-8:]
    )
    user_prompt = (
        f"【患者基础信息】{profile_text(ctx.profile)}\n"
        f"【对话历史】\n{history_text or '（无）'}\n"
        f"【本次问题】{ctx.message}\n\n"
        f"【知识库参考片段】\n{ctx.rag_context}"
    )
    return [
        {"role": "system", "content": SYSTEM_BASE + "\n" + SYMPTOM_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


async def arun(ctx: ChainContext, backend: ChatBackend | None = None) -> ChainResult:
    settings = get_settings()
    disclaimer = settings.DISCLAIMER

    # 症状咨询同样可能包含危急信号，命中时把急诊指引置顶
    prefix = ""
    guard_result = guard.scan(ctx.message)
    if guard_result.triggered:
        emergency_answer, _ = guard.render_answer(guard_result, disclaimer)
        prefix = emergency_answer + "\n\n---\n\n"

    if backend is not None and backend.available:
        try:
            answer = await backend.ainvoke(_build_messages(ctx))
            if answer.strip():
                return ChainResult(answer=prefix + answer.strip())
        except Exception:  # noqa: BLE001
            pass
    intro = f"关于「{truncate(ctx.message, 30)}」，知识库中相关内容整理如下："
    return ChainResult(answer=prefix + fallback_render(ctx, intro))


async def astream(ctx: ChainContext, backend: ChatBackend | None = None) -> AsyncIterator[str]:
    if backend is not None and backend.available:
        try:
            got = False
            async for piece in backend.astream(_build_messages(ctx)):
                if piece:
                    got = True
                    yield piece
            if got:
                return
        except Exception:  # noqa: BLE001
            pass
    result = await arun(ctx, None)
    text = result.answer
    for i in range(0, len(text), 24):
        yield text[i : i + 24]
