from __future__ import annotations

import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - unittest fallback
    raise unittest.SkipTest("pytest is required for regression tests") from exc

from tests.regression.cases_reply_guard import FALSE_POSITIVE_CASES
from tests.regression.helpers import run_reply_guard_case
from tests.support import TemporaryWorkspace


@pytest.mark.parametrize(
    "case",
    FALSE_POSITIVE_CASES,
    ids=lambda case: str(case["case_id"]),
)
def test_reply_guard_false_positive(case) -> None:
    workspace = TemporaryWorkspace()
    try:
        run = run_reply_guard_case(workspace, case, max_reply_chars=120)
        initial = run["initial_decision"]
        final = run["final_decision"]

        assert initial.initial_action == "accept", (
            f"{case['case_id']}: expected accept but got initial_action={initial.initial_action}. "
            f"violations={initial.violation_codes}"
        )
        assert final.final_action == "accept", (
            f"{case['case_id']}: expected final accept but got {final.final_action}. "
            f"violations={final.violation_codes}"
        )

        non_info_violations = [
            violation.category
            for violation in initial.violations
            if violation.severity != "info"
        ]
        assert not non_info_violations, (
            f"{case['case_id']}: guard became too sensitive. "
            f"non_info_violations={non_info_violations}"
        )
    finally:
        workspace.cleanup()
