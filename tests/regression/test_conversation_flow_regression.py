from __future__ import annotations

import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - unittest fallback
    raise unittest.SkipTest("pytest is required for regression tests") from exc

from tests.regression.cases_conversation_flow import FLOW_CASES
from tests.regression.helpers import run_flow_case
from tests.support import TemporaryWorkspace


@pytest.mark.parametrize("case", FLOW_CASES, ids=lambda case: case.case_id)
def test_conversation_flow_regression(case) -> None:
    workspace = TemporaryWorkspace()
    try:
        result, coordinator, gateway, memory_manager = run_flow_case(
            workspace,
            case,
            **dict(case.extra.get("config_kwargs", {})),
        )
        del coordinator, memory_manager

        assert result.memory_selected_ids == case.expected_injected_memory_ids, (
            f"{case.case_id}: unexpected memory_selected_ids. "
            f"expected={case.expected_injected_memory_ids} got={result.memory_selected_ids}. "
            f"note={case.expected_behavior_notes}"
        )
        assert result.reply_guard_action == case.expected_guard_action, (
            f"{case.case_id}: unexpected reply_guard_action. "
            f"expected={case.expected_guard_action} got={result.reply_guard_action}. "
            f"note={case.expected_behavior_notes}"
        )
        if case.expected_guard_initial_action is not None:
            assert result.reply_guard_initial_action == case.expected_guard_initial_action, (
                f"{case.case_id}: unexpected reply_guard_initial_action. "
                f"expected={case.expected_guard_initial_action} "
                f"got={result.reply_guard_initial_action}. "
                f"note={case.expected_behavior_notes}"
            )
        if case.expected_retry_attempted is not None:
            assert result.reply_guard_retry_attempted is case.expected_retry_attempted, (
                f"{case.case_id}: unexpected retry flag. "
                f"expected={case.expected_retry_attempted} got={result.reply_guard_retry_attempted}. "
                f"note={case.expected_behavior_notes}"
            )

        actual_guard_flags = tuple(
            dict.fromkeys(
                result.reply_guard_initial_violations + result.reply_guard_violations
            )
        )
        missing_flags = [
            flag for flag in case.expected_guard_flags if flag not in actual_guard_flags
        ]
        assert not missing_flags, (
            f"{case.case_id}: missing flow guard flags {missing_flags}. "
            f"actual={actual_guard_flags}. note={case.expected_behavior_notes}"
        )

        for expected in case.expected_final_contains:
            assert expected in result.reply_text, (
                f"{case.case_id}: final reply missing {expected!r}. "
                f"reply={result.reply_text!r}"
            )
        for unexpected in case.expected_final_not_contains:
            assert unexpected not in result.reply_text, (
                f"{case.case_id}: final reply should not contain {unexpected!r}. "
                f"reply={result.reply_text!r}"
            )

        expected_calls = len(case.gateway_responses)
        assert len(gateway.calls) == expected_calls, (
            f"{case.case_id}: unexpected gateway call count. "
            f"expected={expected_calls} got={len(gateway.calls)}"
        )
    finally:
        workspace.cleanup()
