"""报告解读链路：检验 / 影像 / 病理报告 → 通俗解读 + 异常项 + 就诊建议。"""
from __future__ import annotations

import re
from typing import AsyncIterator

from app.chains.base import ChainContext, ChainResult
from app.chains.prompts import REPORT_SYSTEM, SYSTEM_BASE, profile_text
from app.config import get_settings
from app.llm.provider import ChatBackend, Message
from app.safety import guard
from app.schemas import ReportItem, ReportResult
from app.utils.text import truncate

# 常见检验行，如：白细胞 12.3 ×10^9/L ↑（参考 3.5-9.5）
_LAB_LINE = re.compile(
    r"(?P<name>[\u4e00-\u9fff A-Za-zαβ\-]{2,20}?)"
    r"[\s:：]*"
    r"(?P<value>[<>≤≥]*\s*\d+(?:\.\d+)?)"
    r"\s*(?P<unit>[\w/%×^µμ\.\-]*)?"
    r"\s*(?P<flag>[↑↓⬆⬇高低+*\s]*)"
)


def guess_report_type(text: str) -> str:
    if re.search(r"(病理|活检|镜下|免疫组化)", text):
        return "pathology"
    if re.search(r"(CT|MRI|核磁|超声|B超|DR|胸片|影像|结节|密度影|回声)", text):
        return "imaging"
    if re.search(r"(血常规|尿常规|生化|肝功能|肾功能|血脂|血糖|甲功|肿瘤标志物|参考)", text):
        return "lab"
    return "other"


def _parse_items(text: str) -> list[ReportItem]:
    """轻量预解析：先抓出可能的指标行，交给模型补全解释，模型不可用时也能展示。"""
    items: list[ReportItem] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 400:
            continue
        # 一行里可能包含多个指标（如 "白细胞 12.3 ↑，血红蛋白 105 ↓"），需全部遍历
        for m in _LAB_LINE.finditer(line):
            item = _to_item(m)
            if item is not None:
                items.append(item)
    # 去重保序
    seen: set[str] = set()
    uniq: list[ReportItem] = []
    for it in items:
        if it.name in seen:
            continue
        seen.add(it.name)
        uniq.append(it)
    return uniq[:40]


def _to_item(m: "re.Match[str]") -> ReportItem | None:
    flag_raw = (m.group("flag") or "").strip()
    value = (m.group("value") or "").strip()
    unit = (m.group("unit") or "").strip()

    if "↑" in flag_raw or "⬆" in flag_raw or "高" in flag_raw:
        flag = "high"
    elif "↓" in flag_raw or "⬇" in flag_raw or "低" in flag_raw:
        flag = "low"
    elif not unit:
        # 既无升降标记也无单位，多半不是指标行（如"帮我看看这个血常规"）
        return None
    else:
        flag = "unknown"

    name = (m.group("name") or "").strip(" ：:，,。")
    if not name:
        return None

    return ReportItem(name=name, value=value, unit=unit, flag=flag)


def _build_messages(ctx: ChainContext) -> list[Message]:
    pre = _parse_items(ctx.message)
    pre_text = ""
    if pre:
        pre_text = "【预解析出的指标行】\n" + "\n".join(
            f"- {i.name}：{i.value} {i.unit}".strip() for i in pre
        )
    user_prompt = (
        f"【患者基础信息】{profile_text(ctx.profile)}\n"
        f"【报告类型（可自动判定）】{ctx.message[:40]}\n\n"
        f"【报告原文】\n{ctx.message[:6000]}\n\n"
        f"{pre_text}\n\n"
        f"【知识库参考片段】\n{ctx.rag_context}\n\n"
        "请严格按 Schema 输出 JSON，只解读报告中出现的项目。"
    )
    return [
        {"role": "system", "content": SYSTEM_BASE + "\n" + REPORT_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


def _normalize(data: dict, disclaimer: str) -> ReportResult:
    items: list[ReportItem] = []
    for raw in (data.get("items") or [])[:40]:
        if not isinstance(raw, dict):
            continue
        flag = str(raw.get("flag", "unknown")).lower()
        if flag not in ("high", "low", "normal", "unknown"):
            flag = "unknown"
        items.append(
            ReportItem(
                name=truncate(str(raw.get("name", "")), 40),
                value=str(raw.get("value", "")),
                unit=str(raw.get("unit", "")),
                reference=str(raw.get("reference", "")),
                flag=flag,
                plain_explanation=truncate(str(raw.get("plain_explanation", "")), 200),
                possible_causes=[truncate(str(x), 60) for x in (raw.get("possible_causes") or [])][:3],
                suggestion=truncate(str(raw.get("suggestion", "")), 200),
            )
        )
    abnormal = sum(1 for i in items if i.flag in ("high", "low"))

    def _list(key: str, limit: int) -> list[str]:
        vals = data.get(key) or []
        return [truncate(str(v), 160) for v in vals if str(v).strip()][:limit]

    return ReportResult(
        report_type=str(data.get("report_type") or "lab"),
        summary=truncate(str(data.get("summary", "")), 400),
        items=items,
        abnormal_count=int(data.get("abnormal_count") or abnormal),
        advice=_list("advice", 5),
        questions_to_ask_doctor=_list("questions_to_ask_doctor", 3),
        disclaimer=disclaimer,
    )


_FLAG_CN = {"high": "偏高", "low": "偏低", "normal": "正常", "unknown": "待判定"}
_FLAG_ICON = {"high": "🔺", "low": "🔻", "normal": "✅", "unknown": "❔"}


def _render(result: ReportResult) -> str:
    lines: list[str] = []
    if result.summary:
        lines.append(result.summary)
        lines.append("")

    if result.items:
        lines.append(f"**逐项解读**（共 {len(result.items)} 项，异常 {result.abnormal_count} 项）")
        lines.append("")
        for it in result.items:
            head = f"{_FLAG_ICON.get(it.flag, '❔')} **{it.name}** {it.value}{it.unit}"
            if it.reference:
                head += f"（参考 {it.reference}）"
            head += f" —— {_FLAG_CN.get(it.flag, '待判定')}"
            lines.append(head)
            if it.plain_explanation:
                lines.append(f"   {it.plain_explanation}")
            if it.possible_causes:
                lines.append(f"   常见原因：{'、'.join(it.possible_causes)}")
            if it.suggestion:
                lines.append(f"   建议：{it.suggestion}")
            lines.append("")
    else:
        lines.append("未从报告中解析出具体项目，建议上传更清晰的报告图片或粘贴检验数值。")
        lines.append("")

    if result.advice:
        lines.append("**总体建议**")
        lines.extend(f"- {a}" for a in result.advice)
        lines.append("")

    if result.questions_to_ask_doctor:
        lines.append("**就诊时可以问医生**")
        lines.extend(f"- {q}" for q in result.questions_to_ask_doctor)
        lines.append("")

    lines.append("- 请携带报告原件就诊，单项轻度异常通常不足以诊断，需由医生结合症状判断。")
    return "\n".join(lines).strip()


async def arun(ctx: ChainContext, backend: ChatBackend | None = None) -> ChainResult:
    settings = get_settings()
    disclaimer = settings.DISCLAIMER

    # 用户可能在贴报告的同时描述危急症状（"胸痛，帮我看看这份心电图"）
    prefix = ""
    guard_result = guard.scan(ctx.message)
    if guard_result.triggered:
        emergency_answer, _ = guard.render_answer(guard_result, disclaimer)
        prefix = emergency_answer + "\n\n---\n\n"

    if backend is not None and backend.available:
        try:
            data = await backend.ajson(_build_messages(ctx), fast=False)
            if data:
                result = _normalize(data, disclaimer)
                return ChainResult(answer=prefix + _render(result))
        except Exception:  # noqa: BLE001
            pass

    # 降级：用预解析 + 知识库片段拼装
    pre = _parse_items(ctx.message)
    fake = ReportResult(
        report_type=guess_report_type(ctx.message),
        summary="当前为离线模式（未配置大模型），以下仅列出从报告中识别到的数值与知识库相关片段，不做结论性判断。",
        items=pre,
        abnormal_count=sum(1 for i in pre if i.flag in ("high", "low")),
        advice=[
            "请把异常项与参考区间一起交给接诊医生判断",
            "单项轻度异常通常不具诊断意义，常需复查确认",
        ],
        questions_to_ask_doctor=[
            "这项异常需要复查吗？间隔多久？",
            "是否需要进一步检查或转专科？",
        ],
        disclaimer=disclaimer,
    )
    answer = prefix + _render(fake)
    if ctx.evidence:
        answer += "\n\n**知识库相关片段**\n\n"
        answer += "\n\n".join(f"- 《{e.title}》：{e.snippet}" for e in ctx.evidence)
    return ChainResult(answer=answer)


async def astream(ctx: ChainContext, backend: ChatBackend | None = None) -> AsyncIterator[str]:
    result = await arun(ctx, backend)
    for i in range(0, len(result.answer), 24):
        yield result.answer[i : i + 24]


def clean_report_text(raw: str) -> str:
    """清理 OCR/复制粘贴带来的噪声。"""
    text = raw or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)
