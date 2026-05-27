from __future__ import annotations

import re
from typing import Sequence

from src.evals.models import EvalCase, ResponseCheck
from src.utils.text_utils import normalize_whitespace


SHORT_MAX_CHARS = 36
MEDIUM_MAX_CHARS = 100

AI_DISCLOSURE_PATTERNS = (
    r"作为(?:一个)?(?:ai|人工智能|语言模型)",
    r"我是(?:一个)?(?:ai|人工智能|语言模型)",
    r"作为(?:数字|智能)?助手",
)

PSEUDO_MEMORY_PATTERNS = (
    r"我记得你(?:之前|上次|前面)",
    r"你之前说过",
    r"上次你提到",
    r"我还记得你",
)

TEMPLATE_STYLE_PATTERNS = (
    r"首先.{0,40}其次",
    r"1\.\s.*2\.\s",
    r"第一.{0,40}第二",
)

ADVICEY_PATTERNS = (
    r"你应该",
    r"建议你",
    r"最好",
    r"立刻",
    r"马上",
    r"先去",
)

FOLLOW_UP_PATTERNS = (
    r"[?？]$",
    r"要不要",
    r"想不想",
    r"愿不愿意",
    r"要不",
    r"还想继续",
)

RECENT_CONTEXT_PATTERNS = (
    r"前几天",
    r"之前",
    r"刚才",
    r"后来",
    r"上次",
)

WARMTH_PATTERNS = (
    r"老师",
    r"我在",
    r"先别",
    r"辛苦了",
    r"慢一点",
    r"没事",
    r"我陪你",
)


def classify_length_band(text: str) -> str:
    normalized = normalize_whitespace(text)
    length = len(normalized)
    if length <= SHORT_MAX_CHARS:
        return "short"
    if length <= MEDIUM_MAX_CHARS:
        return "medium"
    return "long"


def run_response_checks(case: EvalCase, response_text: str) -> ResponseCheck:
    normalized = normalize_whitespace(response_text)
    response_length = len(normalized)
    actual_length_band = classify_length_band(normalized)
    length_band_match = actual_length_band == case.expected_length_band

    forbidden_hits = tuple(find_pattern_hits(normalized, case.forbidden_patterns))
    preferred_hits = tuple(find_pattern_hits(normalized, case.preferred_patterns))
    ai_disclaimer_detected = bool(find_pattern_hits(normalized, AI_DISCLOSURE_PATTERNS))
    pseudo_memory_detected = bool(find_pattern_hits(normalized, PSEUDO_MEMORY_PATTERNS))
    template_style_detected = bool(find_pattern_hits(normalized, TEMPLATE_STYLE_PATTERNS))
    advicey_detected = bool(find_pattern_hits(normalized, ADVICEY_PATTERNS))
    follow_up_detected = bool(find_pattern_hits(normalized, FOLLOW_UP_PATTERNS))
    warmth_signal_detected = bool(find_pattern_hits(normalized, WARMTH_PATTERNS))
    empty_response = not normalized

    failure_reasons: list[str] = []
    manual_review_needed = False

    if empty_response:
        failure_reasons.append("empty_response")
    if not length_band_match:
        failure_reasons.append("length_band_mismatch")
    if forbidden_hits:
        failure_reasons.append("forbidden_pattern_hit")
    if ai_disclaimer_detected:
        failure_reasons.append("ai_disclaimer_detected")
    if pseudo_memory_detected:
        failure_reasons.append("pseudo_memory_detected")
    if case.should_avoid_advice and advicey_detected:
        failure_reasons.append("advice_should_be_avoided")
    if case.should_follow_up and not follow_up_detected:
        failure_reasons.append("missing_follow_up_signal")
    if case.should_reference_recent_context and not find_pattern_hits(
        normalized,
        RECENT_CONTEXT_PATTERNS,
    ):
        manual_review_needed = True
    if template_style_detected:
        manual_review_needed = True
    if case.should_feel_warm and not warmth_signal_detected:
        manual_review_needed = True

    return ResponseCheck(
        response_length=response_length,
        actual_length_band=actual_length_band,
        length_band_match=length_band_match,
        forbidden_hits=forbidden_hits,
        preferred_hits=preferred_hits,
        ai_disclaimer_detected=ai_disclaimer_detected,
        pseudo_memory_detected=pseudo_memory_detected,
        template_style_detected=template_style_detected,
        advicey_detected=advicey_detected,
        follow_up_detected=follow_up_detected,
        warmth_signal_detected=warmth_signal_detected,
        empty_response=empty_response,
        manual_review_needed=manual_review_needed,
        failure_reasons=tuple(failure_reasons),
    )


def find_pattern_hits(text: str, patterns: Sequence[str]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            hits.append(pattern)
    return hits
