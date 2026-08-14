import re

TITLE_PREFIXES = ('Mr', 'Mrs', 'Ms', 'Miss', 'Dr', 'Prof', 'Rev', 'Sir', 'Dame')


def _build_redaction_pattern(original: str) -> str:
    """
    Build a regex pattern for the original phrase.
    Makes title abbreviations like 'Mr'/'Mr.' interchangeable,
    so 'Mr Hutchinson' matches 'Mr. Hutchinson' and vice versa.
    """
    for title in TITLE_PREFIXES:
        # Check if original starts with the title (with or without period)
        for sep in (' ', '. ', '.'):
            prefix = title + sep
            if original.lower().startswith(prefix.lower()):
                rest = original[len(prefix):]
                # title with optional period, then one or more whitespace chars
                return re.escape(title) + r'\.?\s+' + re.escape(rest)
    return re.escape(original)


def apply_redactions_to_text(text: str, redactions: list) -> str:
    """Apply saved redaction pairs to a text string (case-insensitive).
    Handles title abbreviation variations e.g. Mr / Mr."""
    if not text or not redactions:
        return text
    result = text
    for r in redactions:
        original = r.get("original", "")
        replacement = r.get("replacement", "[Redacted]")
        if original:
            pattern = _build_redaction_pattern(original)
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
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
