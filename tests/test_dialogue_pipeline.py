from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.coordinator import Coordinator
from src.dialogue.engine import DialogueEngine
from src.memory.manager import MemoryManager
from tests.support import DummyGateway, TemporaryWorkspace, build_test_config


class DialoguePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_pipeline_runs_without_memory_data(self) -> None:
        config = build_test_config(self.workspace.db_path)
        memory_manager = MemoryManager.from_app_config(config)
        gateway = DummyGateway(["老师，我在。"])
        engine = DialogueEngine(config, gateway, memory_manager=memory_manager)
        coordinator = Coordinator(config, engine=engine)

        result = coordinator.process_user_message("你好")

        self.assertEqual(result.reply_text, "老师，我在。")
        self.assertFalse(result.memory_write_candidate_present)

    def test_reply_guard_can_retry_once(self) -> None:
        config = build_test_config(self.workspace.db_path)
        memory_manager = MemoryManager.from_app_config(config)
        gateway = DummyGateway(
            [
                "你应该立刻停止这种想法，并按下面三步严格执行。",
                "先别急着逼自己。我们先把最堵的那一点说出来。",
            ]
        )
        engine = DialogueEngine(config, gateway, memory_manager=memory_manager)

        result = engine.generate_reply(
            user_input="我今天真的有点撑不住。",
            conversation_history=[],
        )

        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(result.reply_text, "先别急着逼自己。我们先把最堵的那一点说出来。")
        self.assertEqual(result.reply_guard_initial_action, "retry_once")
        self.assertEqual(result.reply_guard_action, "accept")
        self.assertTrue(result.reply_guard_retry_attempted)
        self.assertIn("scene_conflict", result.reply_guard_initial_violations)

    def test_reply_guard_disabled_degrades_normally(self) -> None:
        config = build_test_config(
            self.workspace.db_path,
            reply_guard_enabled=False,
        )
        memory_manager = MemoryManager.from_app_config(config)
        gateway = DummyGateway(["我记得你之前说过这件事。"])
        engine = DialogueEngine(config, gateway, memory_manager=memory_manager)

        result = engine.generate_reply(
            user_input="继续说吧。",
            conversation_history=[],
        )

        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(result.reply_text, "我记得你之前说过这件事。")
        self.assertEqual(result.reply_guard_action, "accept")


if __name__ == "__main__":
    unittest.main()
