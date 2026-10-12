"""统一对话入口：支持一次性返回与 SSE 流式两种模式。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest, ChatResponse
from app.services import dialogue

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="智能问诊对话（一次性返回）")
async def chat(req: ChatRequest) -> ChatResponse:
    if not (req.message or "").strip():
        raise HTTPException(status_code=400, detail="message 不能为空")
    return await dialogue.handle(req)


@router.post("/chat/stream", summary="智能问诊对话（SSE 流式）")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    if not (req.message or "").strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    async def event_gen():
        async for payload in dialogue.stream_events(req):
            yield dialogue.sse_format(payload)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
