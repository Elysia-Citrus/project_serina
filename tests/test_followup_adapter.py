from __future__ import annotations

from src.memory.manager import MemoryManager
from src.scheduler.followup_adapter import FollowUpSchedulerAdapter
from tests.regression.helpers import build_memory_item
from tests.regression.models import MemorySeed
from tests.support import TemporaryWorkspace, build_test_config


def test_followup_adapter_accepts_due_explicit_followup_memory() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(
            workspace.db_path,
            followup_scheduler_enabled=True,
            followup_cooldown_hours=24,
        )
        manager = MemoryManager.from_app_config(config)
        manager.store.seed_items(  # type: ignore[union-attr]
            [
                build_memory_item(
                    MemorySeed(
                        id="followup-1",
                        memory_type="episodic",
                        content="用户约定后续可跟进：过两天再问我这个项目的进展。",
                        summary="用户最近提到这个项目，并约定后续跟进。",
                        ttl_days=7,
                        tags=("followup", "project"),
                        followup_enabled=True,
                        followup_due_in_hours=-2,
                        expires_in_hours=48,
                    )
                )
            ]
        )
        adapter = FollowUpSchedulerAdapter(
            manager,
            enabled=True,
            cooldown_hours=24,
        )

        result = adapter.collect_candidates()

        assert tuple(candidate.memory_id for candidate in result.accepted) == ("followup-1",)
        assert not result.skipped_reason
    finally:
        workspace.cleanup()


def test_followup_adapter_rejects_not_due_or_cooldown_items() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(
            workspace.db_path,
            followup_scheduler_enabled=True,
            followup_cooldown_hours=24,
        )
        manager = MemoryManager.from_app_config(config)
        manager.store.seed_items(  # type: ignore[union-attr]
            [
                build_memory_item(
                    MemorySeed(
                        id="followup-2",
                        memory_type="episodic",
                        content="用户约定后续可跟进：明天继续问我。",
                        summary="用户最近提到这个任务，并约定后续跟进。",
                        ttl_days=7,
                        tags=("followup",),
                        followup_enabled=True,
                        followup_due_in_hours=8,
                        expires_in_hours=48,
                    )
                ),
                build_memory_item(
                    MemorySeed(
                        id="followup-3",
                        memory_type="episodic",
                        content="用户约定后续可跟进：之后提醒我。",
                        summary="用户最近提到这个任务，并约定后续跟进。",
                        ttl_days=7,
                        tags=("followup",),
                        followup_enabled=True,
                        followup_due_in_hours=-1,
                        last_followup_hours_ago=2,
                        expires_in_hours=48,
                    )
                ),
            ]
        )
        adapter = FollowUpSchedulerAdapter(
            manager,
            enabled=True,
            cooldown_hours=24,
        )

        result = adapter.collect_candidates()
        rejected = {item["id"]: item["reason"] for item in result.rejected}

        assert result.accepted == ()
        assert rejected["followup-2"] == "followup_not_due"
        assert rejected["followup-3"] == "followup_cooldown"
    finally:
        workspace.cleanup()
