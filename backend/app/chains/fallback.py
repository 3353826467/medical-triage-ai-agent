"""无大模型时的兜底回答生成：把检索到的知识片段组织成可读答案。"""
from __future__ import annotations

from app.chains.base import ChainContext

_URGENT_HINT = [
    "出现胸痛持续不缓解、呼吸困难、意识不清、偏瘫失语、大出血等情况，请立即拨打 120。",
    "症状在 24 小时内持续加重，或高热不退，建议尽快线下就诊。",
]


def render(ctx: ChainContext, intro: str) -> str:
    lines = [intro, ""]

    if ctx.evidence:
        lines.append("**知识库中与你的问题相关的内容**")
        lines.append("")
        for e in ctx.evidence:
            lines.append(f"**《{e.title}》**（来源：{e.source}，相关度 {e.score:.2f}）")
            lines.append(e.snippet)
            lines.append("")
    else:
        lines.append("当前知识库未覆盖该问题，以下为通用就医建议。")
        lines.append("")

    lines.append("**建议**")
    lines.extend(f"- {h}" for h in _URGENT_HINT)
    lines.append("- 线下就诊时请携带既往检查报告与正在服用的药物清单。")
    lines.append("")

    profile_missing = [k for k in ("age", "duration") if not ctx.profile.get(k)]
    if profile_missing:
        lines.append("补充年龄、症状持续时间与伴随症状，可以让分诊结果更准确。")

    return "\n".join(lines).strip()
