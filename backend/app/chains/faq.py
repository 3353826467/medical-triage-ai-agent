"""常见问题链路：挂号、医保、缴费、取药、检查准备、票据等就医服务答疑。"""
from __future__ import annotations

from typing import AsyncIterator

from app.chains.base import ChainContext, ChainResult
from app.chains.fallback import render as fallback_render
from app.chains.prompts import FAQ_SYSTEM, SYSTEM_BASE
from app.config import get_settings
from app.llm.provider import ChatBackend, Message
from app.utils.text import truncate


def _build_messages(ctx: ChainContext) -> list[Message]:
    history_text = "\n".join(
        f"{'患者' if m['role'] == 'user' else '客服'}: {m['content']}" for m in ctx.history[-6:]
    )
    user_prompt = (
        f"【对话历史】\n{history_text or '（无）'}\n"
        f"【本次问题】{ctx.message}\n\n"
        f"【知识库参考片段】\n{ctx.rag_context}"
    )
    return [
        {"role": "system", "content": SYSTEM_BASE + "\n" + FAQ_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


async def arun(ctx: ChainContext, backend: ChatBackend | None = None) -> ChainResult:
    settings = get_settings()
    if backend is not None and backend.available:
        try:
            answer = await backend.ainvoke(_build_messages(ctx), fast=True)
            if answer.strip():
                return ChainResult(answer=answer.strip())
        except Exception:  # noqa: BLE001
            pass
    intro = f"关于「{truncate(ctx.message, 30)}」，服务指南中的相关内容如下："
    return ChainResult(answer=fallback_render(ctx, intro))


async def astream(ctx: ChainContext, backend: ChatBackend | None = None) -> AsyncIterator[str]:
    if backend is not None and backend.available:
        try:
            got = False
            async for piece in backend.astream(_build_messages(ctx), fast=True):
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
