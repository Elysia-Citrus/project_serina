from __future__ import annotations

from src.memory.manager import MemoryManager
from src.memory.models import MemoryTurnInput
from tests.support import TemporaryWorkspace, build_test_config


def test_repeated_recent_episodic_events_merge_into_single_record() -> None:
    workspace = TemporaryWorkspace()
    try:
        config = build_test_config(workspace.db_path, merge_time_window_hours=72)
        manager = MemoryManager.from_app_config(config)

        first_result = manager.write_turn(
            MemoryTurnInput(
                user_input="我这周在做桌面 agent 的 memory guard 模块改造。",
                assistant_reply="好，我跟着你。",
                scene="casual_chat",
                turn_id="merge-turn-1",
            )
        )
        second_result = manager.write_turn(
            MemoryTurnInput(
                user_input="今天还在做桌面 agent 的 memory guard 模块改造，主要在补回归测试。",
                assistant_reply="好，我们接着推进。",
                scene="casual_chat",
                turn_id="merge-turn-2",
            )
        )

        items = manager.list_memories(memory_type="episodic", status="active")
        assert first_result.wrote_any is True
        assert second_result.wrote_any is True
        assert len(items) == 1, f"Expected one merged episodic item, got {len(items)}"

        merged = items[0]
        assert merged.merge_count >= 2
        assert merged.summary is not None and len(merged.summary) <= 80
        assert "memory guard" in (merged.summary or merged.content)
    finally:
        workspace.cleanup()
