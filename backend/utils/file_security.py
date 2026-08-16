"""
File upload security helpers.
Validates actual file content via magic bytes — not just the filename extension.
This prevents extension-spoofing attacks where a malicious file is renamed to
an allowed extension (e.g. a script saved as 'exploit.pdf').
"""

# Server-side canonical MIME types — never trust the client Content-Type header.
CANONICAL_MIME = {
    "png":  "image/png",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif":  "image/gif",
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt":  "text/plain",
    "md":   "text/plain",
    "csv":  "text/csv",
    "webm": "audio/webm",
    "mp4":  "audio/mp4",
    "m4a":  "audio/mp4",
}


def _magic_ok(data: bytes, ext: str) -> bool:
    """Return True if the file's leading bytes match the expected magic for its extension."""
    e = ext.lower()
    if e == "png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if e in ("jpg", "jpeg"):
        return data[:3] == b"\xff\xd8\xff"
    if e == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if e == "gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    if e == "pdf":
        return data[:4] == b"%PDF"
    if e in ("docx", "xlsx", "pptx"):
        # All Office Open XML formats are ZIP archives
        return data[:4] == b"PK\x03\x04"
    # txt / md / csv — no reliable magic bytes, skip check
    return True


def validate_upload(data: bytes, ext: str) -> str:
    """
    Validate file content against its declared extension.

    - Checks magic bytes to detect extension spoofing.
    - Returns the canonical server-side MIME type (never the client-supplied value).
    - Raises ValueError with a user-facing message if validation fails.
    """
    if not _magic_ok(data, ext):
        raise ValueError(
            f"File content does not match a valid {ext.upper()} file. "
            "Executable files and scripts are not permitted."
        )
    return CANONICAL_MIME.get(ext.lower(), "application/octet-stream")
