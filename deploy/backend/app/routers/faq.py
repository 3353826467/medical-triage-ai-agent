"""常见问题（就医服务类）列表与检索。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.rag.knowledge import load_knowledge_docs
from app.schemas import FaqItem
from app.utils.text import tokenize

router = APIRouter(prefix="/api/v1/faq", tags=["faq"])

# 就医服务类知识被视作 FAQ 语料
FAQ_CATEGORIES = {"就医服务"}


def _load_faq() -> list[FaqItem]:
    docs = load_knowledge_docs()
    items: list[FaqItem] = []
    for d in docs:
        if d.category in FAQ_CATEGORIES:
            items.append(
                FaqItem(category=d.category, question=d.title, answer=d.content)
            )
    return items


@router.get("", response_model=list[FaqItem], summary="常见问题列表")
async def list_faq(
    q: str = Query(default="", description="关键词过滤"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[FaqItem]:
    items = _load_faq()
    if q:
        q_tokens = set(tokenize(q))
        scored = [
            (len(q_tokens & set(tokenize(f"{i.question} {i.answer}"))), i) for i in items
        ]
        items = [i for score, i in scored if score > 0]
        items.sort(key=lambda i: -len(q_tokens & set(tokenize(f"{i.question} {i.answer}"))))
    return items[:limit]


@router.get("/categories", summary="常见问题分类")
async def categories() -> list[str]:
    return sorted({i.category for i in _load_faq()})
