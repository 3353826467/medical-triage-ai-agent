"""报告解读接口：文本解读 + 文件上传（txt / md / docx / pdf）。"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.chains import report as report_chain
from app.chains.base import ChainContext
from app.config import get_settings
from app.llm.provider import get_chat_backend
from app.rag.pipeline import get_rag_engine
from app.schemas import Intent, ReportRequest, ReportResult
from app.utils.parsers import ParseError, parse_bytes

router = APIRouter(prefix="/api/v1/report", tags=["report"])


@router.post("/interpret", response_model=ReportResult, summary="检查报告解读（文本）")
async def interpret(req: ReportRequest) -> ReportResult:
    text = (req.report_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="report_text 不能为空")

    engine = get_rag_engine()
    evidence = await engine.retrieve(f"{text[:200]} 参考区间 指标 解读")
    backend = get_chat_backend()

    ctx = ChainContext(
        session_id=req.session_id or "anonymous",
        message=text,
        intent=Intent.REPORT,
        profile=req.profile,
        history=[],
        evidence=evidence,
    )
    result = await report_chain.arun(ctx, backend)
    return _to_result(result.answer, text, req.report_type)


@router.post("/upload", response_model=ReportResult, summary="检查报告解读（文件上传）")
async def upload(file: UploadFile = File(...)) -> ReportResult:
    try:
        raw = await file.read()
        text = parse_bytes(file.filename or "", raw)
    except ParseError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    engine = get_rag_engine()
    evidence = await engine.retrieve(f"{text[:200]} 参考区间 指标 解读")
    backend = get_chat_backend()

    ctx = ChainContext(
        session_id="anonymous",
        message=text,
        intent=Intent.REPORT,
        profile={},
        history=[],
        evidence=evidence,
    )
    result = await report_chain.arun(ctx, backend)
    return _to_result(result.answer, text, "auto")


def _to_result(answer: str, text: str, report_type: str) -> ReportResult:
    """报告链路返回 Markdown 文案，这里包装成带原文解析项的结构化结果。"""
    items = report_chain._parse_items(text)  # noqa: SLF001
    return ReportResult(
        report_type=report_chain.guess_report_type(text) if report_type == "auto" else report_type,
        summary=answer,
        items=items,
        abnormal_count=sum(1 for i in items if i.flag in ("high", "low")),
        advice=[],
        questions_to_ask_doctor=[],
        disclaimer=get_settings().DISCLAIMER,
    )
