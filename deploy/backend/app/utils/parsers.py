"""报告文件解析：优先纯文本，其次 docx / pdf（可选依赖，缺失时给出明确提示）。"""
from __future__ import annotations

from pathlib import Path

MAX_FILE_BYTES = 8 * 1024 * 1024  # 8MB


class ParseError(Exception):
    pass


def parse_bytes(filename: str, data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise ParseError("文件过大，请上传 8MB 以内的报告")

    suffix = Path(filename or "").suffix.lower()

    if suffix in {".txt", ".md", ".csv", ".log", ".json"}:
        for enc in ("utf-8", "gbk", "utf-16"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    if suffix == ".docx":
        try:
            import io

            import docx  # python-docx
        except ImportError as exc:  # pragma: no cover
            raise ParseError("未安装 python-docx，无法解析 .docx，请改用文本或 PDF") from exc
        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs if p.text.strip())

    if suffix == ".pdf":
        for mod, fn in (
            ("pdfplumber", lambda m: _pdf_via_pdfplumber(m, data)),
            ("pypdf", lambda m: _pdf_via_pypdf(m, data)),
            ("PyPDF2", lambda m: _pdf_via_pypdf(m, data)),
        ):
            try:
                module = __import__(mod)
            except ImportError:
                continue
            return fn(module)
        raise ParseError("未安装 pdfplumber 或 pypdf，无法解析 PDF，请把报告文字粘贴到对话框")

    raise ParseError(f"暂不支持的文件类型：{suffix or '未知'}，支持 txt / md / docx / pdf")


def _pdf_via_pdfplumber(module, data: bytes) -> str:
    import io

    with module.open(io.BytesIO(data)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _pdf_via_pypdf(module, data: bytes) -> str:
    import io

    reader = module.PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)
