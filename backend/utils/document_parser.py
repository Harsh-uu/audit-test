"""Extract plain text from uploaded documents (PDF, DOCX, TXT)."""

import io
import logging

logger = logging.getLogger(__name__)

MAX_CHARS = 12000  # Enough for AI context; avoids token overflow


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Return extracted plain text, truncated to MAX_CHARS."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    try:
        if ext == "pdf":
            return _from_pdf(file_bytes)
        elif ext in ("docx",):
            return _from_docx(file_bytes)
        else:
            # txt / md / csv / any plain text
            return file_bytes.decode("utf-8", errors="replace")[:MAX_CHARS]
    except Exception as e:
        logger.warning(f"Text extraction failed for {filename}: {e}")
        return ""


def _from_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
        if sum(len(p) for p in parts) >= MAX_CHARS:
            break
    return "\n".join(parts)[:MAX_CHARS]


def _from_docx(data: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return text[:MAX_CHARS]
