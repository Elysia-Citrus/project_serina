from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_app_config
from src.dialogue.prompt_builder import build_prompt_package
from src.utils.time_utils import build_time_context, get_local_now


class PromptBuilderTests(unittest.TestCase):
    def test_prompt_package_contains_system_and_current_user(self) -> None:
        config = load_app_config()
        package = build_prompt_package(
            user_input="你好",
            conversation_history=[],
            persona=config.persona,
            policy=config.policy,
        )

        self.assertEqual(package.messages[0]["role"], "system")
        self.assertEqual(package.messages[-1]["role"], "user")
        self.assertEqual(package.messages[-1]["content"], "你好")
        self.assertGreaterEqual(len(package.metadata.prompt_blocks), 1)
        self.assertGreaterEqual(package.metadata.system_prompt_char_count, 1)
        self.assertGreaterEqual(package.metadata.total_message_char_count, len("你好"))

    def test_memory_block_is_injected_as_optional_context(self) -> None:
        config = load_app_config()
        package = build_prompt_package(
            user_input="聊聊项目进度",
            conversation_history=[],
            persona=config.persona,
            policy=config.policy,
            memory_snippets=("[episodic] 用户近期事项：在重构 memory 模块",),
            extra_guardrails=("这是一次保守重试，只输出自然短答。",),
        )

        system_prompt = package.messages[0]["content"]
        self.assertIn("memory context", system_prompt)
        self.assertIn("[episodic] 用户近期事项：在重构 memory 模块", system_prompt)
        self.assertIn("本轮额外修正", system_prompt)

    def test_time_context_block_is_injected(self) -> None:
        config = load_app_config()
        now = get_local_now()
        package = build_prompt_package(
            user_input="你好",
            conversation_history=[],
            persona=config.persona,
            policy=config.policy,
            time_context=build_time_context(
                now=now,
                session_started_at=now,
            ),
        )

        system_prompt = package.messages[0]["content"]
        self.assertIn("time context", system_prompt)
        self.assertTrue(
            any(block.name == "time_context" for block in package.metadata.prompt_blocks)
        )
        self.assertIsNotNone(package.metadata.time_context_summary)

    def test_continuing_context_block_is_separate_from_memory_block(self) -> None:
        config = load_app_config()
        startup_snippet = "[startup-summary] Last session focused on: schema cleanup and test backfill"
        package = build_prompt_package(
            user_input="继续",
            conversation_history=[],
            persona=config.persona,
            policy=config.policy,
            memory_snippets=(startup_snippet,),
            continuing_context_snippets=(startup_snippet,),
        )

        system_prompt = package.messages[0]["content"]
        self.assertIn("[continuing context]", system_prompt)
        self.assertIn("not full chat history", system_prompt)
        self.assertEqual(system_prompt.count(startup_snippet), 1)
        self.assertTrue(
            any(block.name == "continuing_context" for block in package.metadata.prompt_blocks)
        )
        self.assertEqual(package.metadata.continuing_context_summary, "1 items")


if __name__ == "__main__":
    unittest.main()
