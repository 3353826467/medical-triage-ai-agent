"""会话管理接口。"""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas import Role
from app.services import session as session_store

router = APIRouter(prefix="/api/v1/sessions", tags=["session"])


@router.get("/{session_id}", summary="获取会话历史")
async def get_session(session_id: str) -> dict[str, object]:
    sess = session_store.store.get_or_create(session_id)
    return {
        "session_id": sess.id,
        "profile": sess.profile,
        "history": [
            {"role": m["role"], "content": m["content"]} for m in sess.messages
        ],
    }


@router.delete("/{session_id}", summary="清空会话历史")
async def delete_session(session_id: str) -> dict[str, str]:
    session_store.store._sessions.pop(session_id, None)  # noqa: SLF001
    return {"status": "deleted", "session_id": session_id}
