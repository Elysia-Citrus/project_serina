from __future__ import annotations

from dataclasses import dataclass

from src.utils.text_utils import (
    ensure_non_empty_text,
    normalize_whitespace,
    safe_preview,
    strip_ai_disclaimer,
    strip_known_role_prefixes,
)


@dataclass(frozen=True)
class PostprocessResult:
    final_text: str
    raw_preview: str
    cleaned_preview: str
    applied_rules: list[str]
    used_fallback: bool


def postprocess_response(
    raw_text: str,
    fallback_text: str = "老师，我在。",
    preview_chars: int = 120,
) -> PostprocessResult:
    applied_rules: list[str] = []

    normalized_once = normalize_whitespace(raw_text)
    if normalized_once != raw_text.strip():
        applied_rules.append("normalize_whitespace")

    without_role_prefix = strip_known_role_prefixes(normalized_once)
    if without_role_prefix != normalized_once:
        applied_rules.append("strip_role_prefix")

    without_disclaimer = strip_ai_disclaimer(without_role_prefix)
    if without_disclaimer != without_role_prefix:
        applied_rules.append("strip_ai_disclaimer")

    cleaned_text = normalize_whitespace(without_disclaimer)
    if cleaned_text != without_disclaimer and "normalize_whitespace" not in applied_rules:
        applied_rules.append("normalize_whitespace")

    final_text = ensure_non_empty_text(cleaned_text, fallback_text)
    used_fallback = final_text == fallback_text and not cleaned_text
    if used_fallback:
        applied_rules.append("fallback_empty_response")

    return PostprocessResult(
        final_text=final_text,
        raw_preview=safe_preview(raw_text, preview_chars),
        cleaned_preview=safe_preview(final_text, preview_chars),
        applied_rules=applied_rules,
        used_fallback=used_fallback,
    )
