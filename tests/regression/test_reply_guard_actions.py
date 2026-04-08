from __future__ import annotations

import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - unittest fallback
    raise unittest.SkipTest("pytest is required for regression tests") from exc

from tests.regression.cases_reply_guard import ACTION_CASES
from tests.regression.helpers import run_reply_guard_case
from tests.support import TemporaryWorkspace


@pytest.mark.parametrize(
    "case",
    ACTION_CASES,
    ids=lambda case: str(case["case_id"]),
)
def test_reply_guard_actions(case) -> None:
    workspace = TemporaryWorkspace()
    try:
        run = run_reply_guard_case(workspace, case, max_reply_chars=120)
        initial = run["initial_decision"]
        final = run["final_decision"]
        final_reply = str(run["final_reply"])

        assert initial.initial_action == case["expected_initial_action"], (
            f"{case['case_id']}: wrong initial_action. "
            f"expected={case['expected_initial_action']} got={initial.initial_action}"
        )
        assert final.final_action == case["expected_final_action"], (
            f"{case['case_id']}: wrong final_action. "
            f"expected={case['expected_final_action']} got={final.final_action}"
        )

        missing_initial = [
            category
            for category in case["expected_categories"]
            if category not in initial.violation_codes
        ]
        assert not missing_initial, (
            f"{case['case_id']}: initial violations not preserved. "
            f"missing={missing_initial} actual={initial.violation_codes}"
        )

        expected_retry_used = case["expected_initial_action"] == "retry_once"
        assert bool(run["retry_used"]) is expected_retry_used, (
            f"{case['case_id']}: wrong retry_used flag. "
            f"expected={expected_retry_used} got={run['retry_used']}"
        )

        expected_rewrite_used = case["expected_initial_action"] == "rewrite"
        if expected_rewrite_used:
            assert initial.rewrite_used is True, (
                f"{case['case_id']}: rewrite should have been used."
            )
        if case["expected_final_action"] == "safe_fallback":
            assert final.fallback_reason, (
                f"{case['case_id']}: safe_fallback should record fallback_reason."
            )

        for bad_fragment in case["expected_final_not_contains"]:
            assert bad_fragment not in final_reply, (
                f"{case['case_id']}: final reply still contains {bad_fragment!r}. "
                f"reply={final_reply!r}"
            )
    finally:
        workspace.cleanup()
