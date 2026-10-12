"""智能分诊专用接口：只返回结构化分诊卡片。"""
from __future__ import annotations

from fastapi import APIRouter

from app.chains.triage import arun
from app.config import get_settings
from app.llm.provider import get_chat_backend
from app.rag.pipeline import get_rag_engine
from app.schemas import ChatRequest, Intent, TriageResult

router = APIRouter(prefix="/api/v1", tags=["triage"])


@router.post("/triage", response_model=TriageResult, summary="智能分诊（结构化结果）")
async def triage_only(req: ChatRequest) -> TriageResult:
    from app.chains.base import ChainContext

    settings = get_settings()
    engine = get_rag_engine()
    evidence = await engine.retrieve(f"{req.message} 症状 就诊科室")
    backend = get_chat_backend()

    ctx = ChainContext(
        session_id=req.session_id or "anonymous",
        message=req.message,
        intent=req.intent or Intent.TRIAGE,
        profile=req.profile,
        history=[],
        evidence=evidence,
    )
    result = await arun(ctx, backend)
    triage = result.triage or TriageResult()
    triage.disclaimer = triage.disclaimer or settings.DISCLAIMER
    return triage
