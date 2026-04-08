from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_app_config
from src.dialogue.prompt_builder import build_prompt_package


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
        self.assertIn("可用记忆片段", system_prompt)
        self.assertIn("[episodic] 用户近期事项：在重构 memory 模块", system_prompt)
        self.assertIn("本轮额外修正", system_prompt)


if __name__ == "__main__":
    unittest.main()
