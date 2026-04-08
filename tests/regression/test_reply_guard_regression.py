from __future__ import annotations

import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - unittest fallback
    raise unittest.SkipTest("pytest is required for regression tests") from exc

from tests.regression.cases_reply_guard import REPLY_GUARD_CASES
from tests.regression.helpers import build_memory_read_result, build_reply_guard
from tests.support import TemporaryWorkspace


@pytest.mark.parametrize("case", REPLY_GUARD_CASES, ids=lambda case: case.case_id)
def test_reply_guard_regression(case) -> None:
    workspace = TemporaryWorkspace()
    try:
        guard = build_reply_guard(workspace, max_reply_chars=120)
        decision = guard.evaluate(
            reply_text=str(case.extra["reply_text"]),
            user_input=case.user_input,
            scene=case.scene or "casual_chat",
            memory_result=build_memory_read_result(case),
            allow_retry=True,
        )

        assert decision.action == case.expected_guard_action, (
            f"{case.case_id}: unexpected guard action. "
            f"expected={case.expected_guard_action} got={decision.action}. "
            f"note={case.expected_behavior_notes}"
        )
        missing_flags = [
            flag for flag in case.expected_guard_flags if flag not in decision.violation_codes
        ]
        assert not missing_flags, (
            f"{case.case_id}: missing guard flags {missing_flags}. "
            f"actual={decision.violation_codes}. note={case.expected_behavior_notes}"
        )

        final_text = decision.final_text or ""
        for expected in case.expected_final_contains:
            assert expected in final_text, (
                f"{case.case_id}: final_text missing expected fragment {expected!r}. "
                f"final={final_text!r}"
            )
        for unexpected in case.expected_final_not_contains:
            assert unexpected not in final_text, (
                f"{case.case_id}: final_text should not contain {unexpected!r}. "
                f"final={final_text!r}"
            )
    finally:
        workspace.cleanup()
