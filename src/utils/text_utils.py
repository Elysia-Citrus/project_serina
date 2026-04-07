from __future__ import annotations

import re


ROLE_PREFIXES = (
    "Serina：",
    "Serina:",
    "芹奈：",
    "芹奈:",
    "助手：",
    "助手:",
    "AI：",
    "AI:",
)

AI_DISCLAIMER_PATTERNS = (
    re.compile(r"^(作为(?:一个|一名)?(?:AI|人工智能)[^，。]*[，。]\s*)", re.IGNORECASE),
    re.compile(r"^(作为(?:数字|智能)?助手[^，。]*[，。]\s*)", re.IGNORECASE),
)


def normalize_whitespace(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized.split("\n")]

    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank

    return "\n".join(collapsed).strip()


def strip_known_role_prefixes(text: str) -> str:
    stripped = text.lstrip()
    for prefix in ROLE_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].lstrip()
            break
    return stripped


def strip_ai_disclaimer(text: str) -> str:
    cleaned = text.lstrip()
    for pattern in AI_DISCLAIMER_PATTERNS:
        cleaned = pattern.sub("", cleaned, count=1)
    return cleaned.lstrip("，。:： ")


def ensure_non_empty_text(text: str, fallback_text: str) -> str:
    cleaned = normalize_whitespace(text)
    return cleaned or fallback_text


def contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = text.casefold()
    return any(keyword.casefold() in normalized for keyword in keywords)


def safe_preview(text: str, limit: int = 80) -> str:
    normalized = normalize_whitespace(text)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."
