"""健康检查与运行状态。"""
from __future__ import annotations

import time

from fastapi import APIRouter

from app.config import APP_START_TIME, get_settings
from app.llm.provider import get_chat_backend
from app.rag.pipeline import get_rag_engine
from app.schemas import HealthResponse
from app.services.session import store

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="服务健康检查")
async def health() -> HealthResponse:
    settings = get_settings()
    backend = get_chat_backend(settings)
    engine = get_rag_engine()
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        llm_engine=backend.name,
        vector_backend=engine.store.name,
        vector_ready=True,
        knowledge_docs=len(engine._docs),  # noqa: SLF001
        uptime_seconds=round(time.time() - APP_START_TIME, 2),
    )


@router.get("/runtime", summary="运行后端自省（排障用）")
async def runtime() -> dict[str, object]:
    """返回当前实际生效的引擎组合，便于确认是否走了降级路径。"""
    settings = get_settings()
    engine = get_rag_engine()
    backend = get_chat_backend(settings)
    info = engine.describe()
    info.update(
        {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "llm_engine": backend.name,
            "llm_ready": backend.available,
            "llm_model": settings.LLM_MODEL,
            "base_url": settings.OPENAI_BASE_URL if settings.llm_ready else "(未启用)",
            "milvus_enabled": settings.MILVUS_ENABLED,
            "sessions": store.count(),
        }
    )
    return info
