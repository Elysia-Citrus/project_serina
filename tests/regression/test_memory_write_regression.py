from __future__ import annotations

import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - unittest fallback
    raise unittest.SkipTest("pytest is required for regression tests") from exc

from src.memory.manager import MemoryManager
from tests.regression.cases_memory_write import MEMORY_WRITE_CASES
from tests.regression.helpers import build_turn_input
from tests.support import TemporaryWorkspace, build_test_config


@pytest.mark.parametrize("case", MEMORY_WRITE_CASES, ids=lambda case: case.case_id)
def test_memory_write_regression(case) -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path)
        manager = MemoryManager.from_app_config(config)
        turn = build_turn_input(case)

        preview_candidates = manager.preview_write_candidates(turn)
        preview_reasons = tuple(candidate.candidate_reason for candidate in preview_candidates)
        assert preview_reasons == case.expected_write_candidates, (
            f"{case.case_id}: unexpected write candidates. "
            f"expected={case.expected_write_candidates} got={preview_reasons}. "
            f"note={case.expected_behavior_notes}"
        )

        result = manager.write_turn(turn)
        stored_types = tuple(item.memory_type for item in result.stored_items)
        assert stored_types == case.expected_written_memory_types, (
            f"{case.case_id}: unexpected stored memory types. "
            f"expected={case.expected_written_memory_types} got={stored_types}. "
            f"note={case.expected_behavior_notes}"
        )

        if not case.expected_write_candidates:
            assert result.skipped_reason == "no_high_signal_candidate", (
                f"{case.case_id}: expected no write, got skipped_reason={result.skipped_reason}. "
                f"note={case.expected_behavior_notes}"
            )
        else:
            assert result.wrote_any, (
                f"{case.case_id}: expected memory write but wrote_any was False. "
                f"note={case.expected_behavior_notes}"
            )
    finally:
        workspace.cleanup()
