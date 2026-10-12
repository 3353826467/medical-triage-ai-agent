"""文本处理工具：分块、清洗、轻量分词（不依赖第三方分词库）。"""
from __future__ import annotations

import re
import unicodedata

_STOPWORD_HINT = ("的", "了", "和", "是", "我", "有", "在", "就", "不", "也", "很", "吗", "呢", "请")

_CJK = r"\u4e00-\u9fff"
_TOKEN_RE = re.compile(rf"[{_CJK}]|[A-Za-z]+|\d+(?:\.\d+)?")


def normalize(text: str) -> str:
    """全角转半角、统一空白、去除控制字符。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    """极简分词：中文按字 + 相邻二字组，英文数字按词。

    对医疗短文本检索足够用，且零依赖。
    """
    text = normalize(text).lower()
    singles = _TOKEN_RE.findall(text)
    tokens: list[str] = []
    for i, tk in enumerate(singles):
        tokens.append(tk)
        if re.match(rf"[{_CJK}]", tk) and i + 1 < len(singles) and re.match(rf"[{_CJK}]", singles[i + 1]):
            tokens.append(tk + singles[i + 1])
    return [t for t in tokens if t not in _STOPWORD_HINT]


def split_markdown_sections(md: str) -> list[tuple[str, str]]:
    """按 markdown 标题切分，返回 [(标题, 正文)]。"""
    sections: list[tuple[str, str]] = []
    current_title = ""
    buf: list[str] = []
    for line in md.splitlines():
        if re.match(r"^#{1,4}\s+", line):
            if buf:
                body = "\n".join(buf).strip()
                if body:
                    sections.append((current_title, body))
                buf = []
            current_title = re.sub(r"^#{1,4}\s+", "", line).strip()
        else:
            buf.append(line)
    if buf:
        body = "\n".join(buf).strip()
        if body:
            sections.append((current_title, body))
    return sections


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """按字符窗口分块，优先在中文标点/换行处断开。"""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    breakers = "\n。！？；;!?，,、"
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            cut = -1
            for i in range(end, start + size // 2, -1):
                if text[i - 1] in breakers:
                    cut = i
                    break
            if cut > start:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def truncate(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def extract_json_object(text: str) -> dict | None:
    """从 LLM 输出中稳健地提取第一个 JSON 对象。"""
    import json

    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        # 兜底：尝试去掉尾随逗号
        candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
        try:
            return json.loads(candidate)
        except Exception:
            return None


def mask_sensitive(text: str) -> str:
    """日志/存储前的敏感信息脱敏（身份证、手机号）。"""
    text = re.sub(r"\d{17}[\dXx]", "[ID]", text)
    text = re.sub(r"1[3-9]\d{9}", "[PHONE]", text)
    return text
