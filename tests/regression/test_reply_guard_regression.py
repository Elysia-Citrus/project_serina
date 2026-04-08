from __future__ import annotations

import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - unittest fallback
    raise unittest.SkipTest("pytest is required for regression tests") from exc

from tests.regression.cases_reply_guard import REPLY_GUARD_CASES
from tests.regression.helpers import run_reply_guard_case
from tests.support import TemporaryWorkspace


@pytest.mark.parametrize(
    "case",
    REPLY_GUARD_CASES,
    ids=lambda case: str(case["case_id"]),
)
def test_reply_guard_regression(case) -> None:
    workspace = TemporaryWorkspace()
    try:
        run = run_reply_guard_case(workspace, case, max_reply_chars=120)
        initial = run["initial_decision"]
        final = run["final_decision"]

        missing_categories = [
            category
            for category in case["expected_categories"]
            if category not in initial.violation_codes
        ]
        assert not missing_categories, (
            f"{case['case_id']}: missing categories {missing_categories}. "
            f"actual={initial.violation_codes}. note={case['expected_behavior_notes']}"
        )
        assert initial.assessment is not None, f"{case['case_id']}: missing assessment"
        assert initial.assessment.severity == case["expected_severity"], (
            f"{case['case_id']}: unexpected severity. "
            f"expected={case['expected_severity']} got={initial.assessment.severity}. "
            f"note={case['expected_behavior_notes']}"
        )
        assert initial.initial_action == case["expected_initial_action"], (
            f"{case['case_id']}: unexpected initial_action. "
            f"expected={case['expected_initial_action']} got={initial.initial_action}. "
            f"note={case['expected_behavior_notes']}"
        )
        assert final.final_action == case["expected_final_action"], (
            f"{case['case_id']}: unexpected final_action. "
            f"expected={case['expected_final_action']} got={final.final_action}. "
            f"note={case['expected_behavior_notes']}"
        )
    finally:
        workspace.cleanup()
