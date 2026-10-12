"""知识库管理：导入、检索调试。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.rag.knowledge import KnowledgeDoc
from app.rag.pipeline import get_rag_engine
from app.schemas import Evidence, IngestRequest, IngestResponse

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.post("/ingest", response_model=IngestResponse, summary="知识库导入 / 重建索引")
async def ingest(req: IngestRequest) -> IngestResponse:
    engine = get_rag_engine()
    docs = None
    if req.docs:
        docs = [
            KnowledgeDoc(
                title=d.get("title", "未命名"),
                content=d.get("content", ""),
                category=d.get("category", "自定义"),
                source=d.get("source", "api"),
            )
            for d in req.docs
            if d.get("content")
        ]
    count = await engine.index(docs=docs, rebuild=req.rebuild)
    return IngestResponse(
        backend=engine.store.name,
        inserted=count,
        collection=engine.settings.MILVUS_COLLECTION,
        message=f"已写入 {count} 个切片到 {engine.store.name}",
    )


@router.get("/search", response_model=list[Evidence], summary="知识库检索（调试）")
async def search(
    q: str = Query(..., description="检索词"),
    top_k: int = Query(default=4, ge=1, le=20),
) -> list[Evidence]:
    engine = get_rag_engine()
    return await engine.retrieve(q, top_k=top_k)
