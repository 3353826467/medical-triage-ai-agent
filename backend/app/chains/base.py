"""链路公共定义。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas import Evidence, Intent, TriageResult


@dataclass
class ChainContext:
    """一次调用在链路之间传递的上下文。"""

    session_id: str
    message: str
    intent: Intent
    profile: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    with_evidence: bool = True

    @property
    def rag_context(self) -> str:
        if not self.evidence:
            return "（本次未检索到知识库片段，请基于通用医学常识谨慎回答，并明确提示线下就诊）"
        lines = []
        for i, e in enumerate(self.evidence, 1):
            lines.append(f"[{i}] 《{e.title}》（来源：{e.source}）：{e.snippet}")
        return "\n".join(lines)


@dataclass
class ChainResult:
    answer: str
    triage: TriageResult | None = None
    followup_questions: list[str] = field(default_factory=list)
