"""意图路由：关键词快判 + 大模型兜底，保证零 Key 也能正确分流。"""
from __future__ import annotations

import re

from app.chains.prompts import ROUTER_SYSTEM
from app.llm.provider import ChatBackend, Message
from app.schemas import Intent
from app.utils.text import extract_json_object, normalize

# 顺序敏感：越具体的规则放前面
_KEYWORD_RULES: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (
        Intent.REPORT,
        (
            r"报告", r"化验", r"检验单", r"血常规", r"尿常规", r"生化", r"指标",
            r"参考区间", r"箭头", r"偏高", r"偏低", r"ct\b", r"超声", r"b超",
            r"核磁", r"mr[i]?", r"病理", r"胸片", r"帮我看看.*单", r"解读",
        ),
    ),
    (
        Intent.FAQ,
        (
            r"挂号", r"怎么预约", r"预约", r"医保", r"报销", r"缴费",
            r"取药", r"住院", r"转诊", r"发票", r"门诊时间", r"出诊", r"病历复印",
            r"停车", r"院区", r"核酸", r"疫苗.*预约",
        ),
    ),
    (
        Intent.TRIAGE,
        (
            r"挂什么科", r"看什么科", r"去哪个科", r"哪个科室", r"分诊",
            r"要不要去?医院", r"需要去医院吗", r"严重吗", r"严不严重",
            r"要不要紧", r"急诊", r"要不要看医生", r"该怎?么办",
        ),
    ),
    (
        Intent.SYMPTOM,
        (
            r"怎么办", r"是什么原因", r"怎么回事", r"正常吗", r"注意什么",
            r"该怎么.*护理", r"吃什么药", r"要不要紧", r"多长?时间能好",
            r"会传染吗",
        ),
    ),
    (Intent.CHITCHAT, (r"^(你好|您好|hi|hello|嗨|在吗|谢谢|感谢|再见|拜拜)",)),
)

_SYMPTOM_HINT = re.compile(
    r"(疼|痛|酸|麻|胀|痒|晕|咳|喘|热|烧|吐|泻|血|肿|疹|包|疲|累|眠|咳|鼻|咽|喉|腹|胃|胸|心|头|腰|腿|关节|尿|经|带"
    r"|无力|没力|使不上劲|不省人事|昏迷|抽搐|麻木)"
)


def _keyword_route(text: str, history: list[dict[str, str]]) -> Intent | None:
    content = normalize(text)
    for intent, patterns in _KEYWORD_RULES:
        for pattern in patterns:
            if re.search(pattern, content, re.I):
                return intent
    return None


async def route_intent(
    message: str,
    history: list[dict[str, str]] | None = None,
    backend: ChatBackend | None = None,
) -> Intent:
    history = history or []
    hit = _keyword_route(message, history)
    if hit is not None:
        # 问候 + 症状描述 组合时，优先按症状处理
        if hit is Intent.CHITCHAT and _SYMPTOM_HINT.search(normalize(message)):
            return Intent.TRIAGE
        return hit

    backend = backend or None
    if backend is None or not backend.available:
        # 无模型时：含症状字眼 → 分诊，否则闲聊
        return Intent.TRIAGE if _SYMPTOM_HINT.search(normalize(message)) else Intent.CHITCHAT

    recent = history[-6:]
    context = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    messages: list[Message] = [
        {"role": "system", "content": ROUTER_SYSTEM},
        {"role": "user", "content": f"对话历史：\n{context}\n\n最新一句话：{message}"},
    ]
    try:
        raw = await backend.ainvoke(messages, fast=True)
        data = extract_json_object(raw) or {}
        value = str(data.get("intent", "")).lower()
        for intent in Intent:
            if intent.value == value:
                return intent
    except Exception:  # noqa: BLE001
        pass
    return Intent.TRIAGE if _SYMPTOM_HINT.search(normalize(message)) else Intent.CHITCHAT
