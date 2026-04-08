from __future__ import annotations

from src.dialogue.reply_guard.models import (
    GuardAction,
    ReplyGuardAssessment,
    ReplyViolation,
)


SEVERITY_RANK = {"info": 0, "light": 1, "medium": 2, "severe": 3}


def classify_violations(
    violations: tuple[ReplyViolation, ...],
    *,
    scene: str,
    retry_enabled: bool,
) -> ReplyGuardAssessment:
    if not violations:
        return ReplyGuardAssessment(
            severity="none",
            suggested_action="accept",
            categories=(),
            blocking_categories=(),
            scene=scene,
            case_like_signature=f"{scene}|clean",
        )

    max_severity = max(violations, key=lambda item: SEVERITY_RANK[item.severity]).severity
    categories = tuple(dict.fromkeys(violation.category for violation in violations))
    blocking_categories = tuple(
        dict.fromkeys(
            violation.category for violation in violations if violation.should_block
        )
    )

    suggested_action = _decide_action(violations, retry_enabled=retry_enabled)
    return ReplyGuardAssessment(
        severity="none" if max_severity == "info" else max_severity,  # type: ignore[arg-type]
        suggested_action=suggested_action,
        categories=categories,
        blocking_categories=blocking_categories,
        scene=scene,
        case_like_signature=f"{scene}|{'-'.join(categories)}|{suggested_action}",
    )


def _decide_action(
    violations: tuple[ReplyViolation, ...],
    *,
    retry_enabled: bool,
) -> GuardAction:
    categories = {violation.category for violation in violations}
    if "ai_self_disclosure" in categories:
        return "safe_fallback"
    if any(violation.severity == "severe" for violation in violations):
        return "safe_fallback"
    if any(violation.severity == "medium" for violation in violations):
        if retry_enabled:
            return "retry_once"
        if all(violation.can_rewrite for violation in violations):
            return "rewrite"
        return "safe_fallback"
    if all(violation.can_rewrite for violation in violations):
        return "rewrite"
    return "accept"
