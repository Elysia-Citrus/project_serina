from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.memory.manager import MemoryManager
from src.memory.models import MemoryTurnInput
from tests.support import TemporaryWorkspace, build_test_config


class MemoryWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(self.workspace.db_path)
        self.manager = MemoryManager.from_app_config(self.config)

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_explicit_preference_enters_profile_memory(self) -> None:
        result = self.manager.write_turn(
            MemoryTurnInput(
                user_input="以后叫我阿泽吧，我更喜欢你直接一点。",
                assistant_reply="好。",
                scene="casual_chat",
                turn_id="turn-1",
            )
        )

        self.assertTrue(result.wrote_any)
        stored_items = self.manager.store.list_active_items()  # type: ignore[union-attr]
        self.assertTrue(any(item.memory_type == "profile" for item in stored_items))
        self.assertTrue(any("阿泽" in item.content for item in stored_items))

    def test_small_talk_does_not_write_memory(self) -> None:
        result = self.manager.write_turn(
            MemoryTurnInput(
                user_input="我刚吃完饭，准备去洗澡。",
                assistant_reply="嗯。",
                scene="casual_chat",
                turn_id="turn-2",
            )
        )

        self.assertFalse(result.wrote_any)
        self.assertEqual(result.skipped_reason, "no_high_signal_candidate")

    def test_follow_up_task_enters_episodic_memory(self) -> None:
        result = self.manager.write_turn(
            MemoryTurnInput(
                user_input="我这周在重构桌面 agent 的 memory 模块，下周记得问我进度。",
                assistant_reply="我记住了。",
                scene="casual_chat",
                turn_id="turn-3",
            )
        )

        self.assertTrue(result.wrote_any)
        stored_items = self.manager.store.list_active_items()  # type: ignore[union-attr]
        episodic_items = [item for item in stored_items if item.memory_type == "episodic"]
        self.assertGreaterEqual(len(episodic_items), 1)
        self.assertTrue(any("重构" in item.content or "跟进" in item.content for item in episodic_items))


if __name__ == "__main__":
    unittest.main()
