"""内置知识库加载：读取 data/knowledge/*.md，解析 YAML front-matter 元信息。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import KNOWLEDGE_DIR


@dataclass
class KnowledgeDoc:
    title: str
    content: str
    category: str
    source: str


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _parse_front_matter(md: str) -> tuple[dict[str, str], str]:
    m = _FM_RE.match(md)
    if not m:
        return {}, md
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, md[m.end() :]


def load_knowledge_docs(directory: Path = KNOWLEDGE_DIR) -> list[KnowledgeDoc]:
    """扫描目录下所有 markdown，按 `##` 小节切分成文档。"""
    docs: list[KnowledgeDoc] = []
    if not directory.exists():
        return docs

    for path in sorted(directory.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        category = meta.get("category", "通用")
        source = meta.get("source", path.name)

        # 一级标题作为文件主题，二级标题作为文档标题
        lines = body.splitlines()
        file_topic = ""
        current_title = ""
        buf: list[str] = []

        def flush() -> None:
            if current_title and buf:
                content = "\n".join(buf).strip()
                if content:
                    docs.append(
                        KnowledgeDoc(
                            title=current_title,
                            content=content,
                            category=category,
                            source=source,
                        )
                    )

        for line in lines:
            if re.match(r"^#\s+", line):
                flush()
                buf = []
                file_topic = re.sub(r"^#\s+", "", line).strip()
                current_title = ""
            elif re.match(r"^##\s+", line):
                flush()
                buf = []
                current_title = re.sub(r"^##\s+", "", line).strip()
            else:
                buf.append(line)
        flush()

        # 一级标题下的开场段落（无 ## 归属）也保留
        if file_topic:
            head = body.split("## ")[0]
            head = re.sub(r"^#\s+.*\n", "", head).strip()
            if head:
                docs.append(
                    KnowledgeDoc(title=file_topic, content=head, category=category, source=source)
                )
    return docs
