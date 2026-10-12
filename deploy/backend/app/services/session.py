"""会话管理：内存存储（可替换为 Redis），带自动过期清理。"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

MAX_HISTORY = 20          # 单会话保留的最大轮次
SESSION_TTL = 60 * 60 * 2  # 2 小时无活动即过期


@dataclass
class Session:
    id: str
    profile: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def add_turn(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > MAX_HISTORY * 2:
            self.history = self.history[-MAX_HISTORY * 2 :]
        self.touch()

    @property
    def messages(self) -> list[dict[str, str]]:
        return self.history[-MAX_HISTORY * 2 :]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str | None = None) -> Session:
        with self._lock:
            self._evict()
            if session_id and session_id in self._sessions:
                s = self._sessions[session_id]
                s.touch()
                return s
            new_id = session_id or uuid.uuid4().hex
            session = Session(id=new_id)
            self._sessions[new_id] = session
            return session

    def merge_profile(self, session: Session, profile: dict[str, Any]) -> None:
        for k, v in (profile or {}).items():
            if v not in (None, "", []):
                session.profile[k] = v
        session.touch()

    def _evict(self) -> None:
        now = time.time()
        expired = [k for k, v in self._sessions.items() if now - v.updated_at > SESSION_TTL]
        for k in expired:
            self._sessions.pop(k, None)

    def count(self) -> int:
        return len(self._sessions)


store = SessionStore()
