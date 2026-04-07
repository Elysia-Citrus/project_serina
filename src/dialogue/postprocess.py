from __future__ import annotations

from src.utils.text_utils import (
    ensure_non_empty_text,
    normalize_whitespace,
    strip_ai_disclaimer,
    strip_known_role_prefixes,
)


def postprocess_response(raw_text: str, fallback_text: str = "老师，我在。") -> str:
    text = normalize_whitespace(raw_text)
    text = strip_known_role_prefixes(text)
    text = strip_ai_disclaimer(text)
    text = normalize_whitespace(text)
    return ensure_non_empty_text(text, fallback_text)
