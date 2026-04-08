from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dialogue.reply_guard import ReplyGuard
from src.memory.models import MemoryReadResult
from tests.support import TemporaryWorkspace, build_test_config


class ReplyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(self.workspace.db_path, max_reply_chars=120)
        self.guard = ReplyGuard(
            self.config.runtime,
            self.config.persona,
            self.config.policy,
        )

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_blocks_ai_self_disclosure(self) -> None:
        decision = self.guard.evaluate(
            reply_text="作为AI助手，我会一直帮你。",
            raw_reply_text="作为AI助手，我会一直帮你。",
            user_input="你好",
            scene="greeting",
            memory_result=MemoryReadResult(),
            allow_retry=True,
        )

        self.assertEqual(decision.initial_action, "safe_fallback")
        self.assertIsNotNone(decision.final_text)
        self.assertNotIn("AI", decision.final_text or "")

    def test_blocks_unsupported_memory_claim(self) -> None:
        decision = self.guard.evaluate(
            reply_text="我记得你之前也总是这么拖。",
            raw_reply_text="我记得你之前也总是这么拖。",
            user_input="我不想做了。",
            scene="correction",
            memory_result=MemoryReadResult(),
            allow_retry=True,
        )

        self.assertEqual(decision.initial_action, "safe_fallback")
        self.assertIn("fake_memory_claim", decision.violation_codes)

    def test_detects_long_and_templated_reply(self) -> None:
        text = "首先你要冷静一下，其次你要相信自己。" + "你真的应该马上调整状态。" * 20
        decision = self.guard.evaluate(
            reply_text=text,
            raw_reply_text=text,
            user_input="我有点烦。",
            scene="casual_chat",
            memory_result=MemoryReadResult(),
            allow_retry=True,
        )

        self.assertEqual(decision.initial_action, "retry_once")
        self.assertIn("overlong", decision.violation_codes)

    def test_scene_conflict_triggers_conservative_handling(self) -> None:
        text = "第一，先建立分析框架。第二，拆出三层原因。你应该立刻开始执行。"
        decision = self.guard.evaluate(
            reply_text=text,
            raw_reply_text=text,
            user_input="我今天真的有点撑不住。",
            scene="comfort",
            memory_result=MemoryReadResult(),
            allow_retry=True,
        )

        self.assertEqual(decision.initial_action, "retry_once")
        self.assertIn("scene_conflict", decision.violation_codes)


if __name__ == "__main__":
    unittest.main()
