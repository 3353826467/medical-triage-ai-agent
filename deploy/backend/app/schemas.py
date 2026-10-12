"""API 数据模型（Pydantic v2）。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Intent(str, Enum):
    """用户意图分类。"""

    SYMPTOM = "symptom"          # 症状咨询
    TRIAGE = "triage"            # 智能分诊
    REPORT = "report"            # 报告解读
    FAQ = "faq"                  # 常见问题（挂号/医保/就诊流程等）
    CHITCHAT = "chitchat"        # 寒暄 / 无关内容


class Urgency(str, Enum):
    """紧急程度 —— 决定前端卡片配色与提示强度。"""

    EMERGENCY = "emergency"      # 立即急诊 / 拨打 120
    URGENT = "urgent"            # 24 小时内就诊
    ROUTINE = "routine"          # 门诊择期就诊
    SELF_CARE = "self_care"      # 居家观察 / 自我护理


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    role: Role
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class ChatRequest(BaseModel):
    """统一对话入口请求体。"""

    session_id: str = Field(default="", description="会话 ID，留空自动创建")
    message: str = Field(..., description="用户输入")
    # 结构化上下文（年龄/性别/病程/既往史等），由前端表单采集
    profile: dict[str, Any] = Field(default_factory=dict)
    intent: Intent | None = Field(default=None, description="手动指定意图，缺省自动路由")
    stream: bool = Field(default=False, description="是否使用 SSE 流式返回")
    with_evidence: bool = Field(default=True, description="是否返回引用来源")


class PossibleCondition(BaseModel):
    name: str
    probability: str = Field(default="low", description="high / medium / low")
    reason: str = ""


class TriageResult(BaseModel):
    """智能分诊结构化结果。"""

    department: str = Field(default="全科 / 普通内科", description="推荐首诊科室")
    department_aliases: list[str] = Field(default_factory=list)
    urgency: Urgency = Urgency.ROUTINE
    urgency_reason: str = ""
    possible_conditions: list[PossibleCondition] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    followup_questions: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    need_more_info: bool = False
    disclaimer: str = ""


class Evidence(BaseModel):
    """RAG 引用来源，用于前端展示"依据来自哪里"。"""

    source: str
    title: str
    score: float
    snippet: str


class ChatResponse(BaseModel):
    session_id: str
    intent: Intent
    answer: str
    triage: TriageResult | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    followup_questions: list[str] = Field(default_factory=list)
    engine: str = Field(default="", description="实际使用的引擎：langchain-openai / rule-engine")
    latency_ms: int = 0
    disclaimer: str = ""


class ReportRequest(BaseModel):
    """报告解读：支持直接贴文本，也支持上传文件后传入 OCR/解析结果。"""

    session_id: str = ""
    report_text: str = Field(default="", description="报告正文文本")
    report_type: str = Field(default="auto", description="lab / imaging / pathology / auto")
    profile: dict[str, Any] = Field(default_factory=dict)


class ReportItem(BaseModel):
    """单项检验指标解读。"""

    name: str
    value: str = ""
    unit: str = ""
    reference: str = ""
    flag: str = Field(default="unknown", description="high / low / normal / unknown")
    plain_explanation: str = ""
    possible_causes: list[str] = Field(default_factory=list)
    suggestion: str = ""


class ReportResult(BaseModel):
    report_type: str
    summary: str
    items: list[ReportItem] = Field(default_factory=list)
    abnormal_count: int = 0
    advice: list[str] = Field(default_factory=list)
    questions_to_ask_doctor: list[str] = Field(default_factory=list)
    disclaimer: str = ""


class FaqItem(BaseModel):
    category: str
    question: str
    answer: str


class IngestRequest(BaseModel):
    """知识库入库请求。"""

    docs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{title, content, category, source}]，留空则从 data/knowledge 重新全量导入",
    )
    rebuild: bool = Field(default=False, description="是否清空重建 collection")


class IngestResponse(BaseModel):
    backend: str
    inserted: int
    collection: str = ""
    message: str = ""


class HealthResponse(BaseModel):
    status: str
    version: str
    llm_engine: str
    vector_backend: str
    vector_ready: bool
    knowledge_docs: int
    uptime_seconds: float
