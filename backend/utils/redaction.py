import re


def apply_redactions_to_text(text: str, redactions: list) -> str:
    """Apply saved redaction pairs to a text string (case-insensitive)."""
    if not text or not redactions:
        return text
    result = text
    for r in redactions:
        original = r.get("original", "")
        replacement = r.get("replacement", "[Redacted]")
        if original:
            result = re.sub(re.escape(original), replacement, result, flags=re.IGNORECASE)
    return result


def apply_redactions_deep(obj, redactions: list):
    """Recursively apply redactions to every string value in a dict/list structure."""
    if not redactions:
        return obj
    if isinstance(obj, str):
        return apply_redactions_to_text(obj, redactions)
    if isinstance(obj, dict):
        return {k: apply_redactions_deep(v, redactions) for k, v in obj.items()}
    if isinstance(obj, list):
        return [apply_redactions_deep(item, redactions) for item in obj]
    return obj
