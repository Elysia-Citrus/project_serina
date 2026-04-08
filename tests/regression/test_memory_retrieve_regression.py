from __future__ import annotations

import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - unittest fallback
    raise unittest.SkipTest("pytest is required for regression tests") from exc

from src.memory.manager import MemoryManager
from tests.regression.cases_memory_retrieve import MEMORY_RETRIEVE_CASES
from tests.regression.helpers import seed_memories
from tests.support import TemporaryWorkspace, build_test_config


@pytest.mark.parametrize("case", MEMORY_RETRIEVE_CASES, ids=lambda case: case.case_id)
def test_memory_retrieve_regression(case) -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path)
        manager = MemoryManager.from_app_config(config)
        seed_memories(manager, case.existing_memories)

        result = manager.retrieve(
            user_input=case.user_input,
            scene=case.scene or "casual_chat",
        )
        assert result.selected_ids == case.expected_injected_memory_ids, (
            f"{case.case_id}: unexpected injected memory ids. "
            f"expected={case.expected_injected_memory_ids} got={result.selected_ids}. "
            f"note={case.expected_behavior_notes}"
        )

        expected_skipped_reason = case.extra.get("expected_skipped_reason")
        if expected_skipped_reason is not None:
            assert result.skipped_reason == expected_skipped_reason, (
                f"{case.case_id}: unexpected skipped_reason. "
                f"expected={expected_skipped_reason} got={result.skipped_reason}. "
                f"note={case.expected_behavior_notes}"
            )
    finally:
        workspace.cleanup()
