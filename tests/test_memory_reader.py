from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.memory.manager import MemoryManager
from src.memory.models import MemoryItem, format_timestamp, now_timestamp
from tests.support import TemporaryWorkspace, build_test_config


class MemoryReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()
        self.config = build_test_config(
            self.workspace.db_path,
            max_memory_injection_items=3,
        )
        self.manager = MemoryManager.from_app_config(self.config)

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_injection_is_limited_to_configured_cap(self) -> None:
        now = now_timestamp()
        items = []
        for index in range(6):
            items.append(
                MemoryItem(
                    id=f"mem-{index}",
                    memory_type="episodic",
                    content=f"用户近期事项：项目 {index} 的发布排期。",
                    source_turn=f"turn-{index}",
                    source_message_excerpt="项目发布",
                    created_at=format_timestamp(now - timedelta(days=1)),
                    updated_at=format_timestamp(now - timedelta(hours=index)),
                    confidence=0.82,
                    ttl_days=7,
                    expires_at=format_timestamp(now + timedelta(days=5)),
                    decay_policy="ttl_expiry",
                    status="active",
                    dedupe_key=f"task-{index}",
                )
            )
        self.manager.store.seed_items(items)  # type: ignore[union-attr]

        result = self.manager.retrieve(user_input="项目发布进度怎么样了？", scene="casual_chat")

        self.assertLessEqual(len(result.selected_items), 3)
        self.assertGreaterEqual(len(result.selected_items), 1)

    def test_expired_episodic_memory_is_not_injected(self) -> None:
        now = now_timestamp()
        expired = MemoryItem(
            id="expired-1",
            memory_type="episodic",
            content="用户近期事项：下周答辩。",
            source_turn="turn-old",
            source_message_excerpt="下周答辩",
            created_at=format_timestamp(now - timedelta(days=10)),
            updated_at=format_timestamp(now - timedelta(days=10)),
            confidence=0.82,
            ttl_days=7,
            expires_at=format_timestamp(now - timedelta(days=1)),
            decay_policy="ttl_expiry",
            status="active",
            dedupe_key="episodic:task:答辩",
        )
        self.manager.store.seed_items([expired])  # type: ignore[union-attr]

        result = self.manager.retrieve(user_input="答辩结果出来了吗？", scene="casual_chat")

        self.assertFalse(result.hit)
        stats = self.manager.get_store_stats()
        self.assertEqual(stats.expired_count, 1)

    def test_irrelevant_memory_is_not_forced_into_prompt(self) -> None:
        now = now_timestamp()
        profile = MemoryItem(
            id="profile-1",
            memory_type="profile",
            content="用户喜欢爵士乐。",
            source_turn="turn-pref",
            source_message_excerpt="喜欢爵士乐",
            created_at=format_timestamp(now - timedelta(days=3)),
            updated_at=format_timestamp(now - timedelta(days=1)),
            confidence=0.9,
            ttl_days=None,
            expires_at=None,
            decay_policy="manual_override",
            status="active",
            dedupe_key="profile:preference:爵士乐",
        )
        self.manager.store.seed_items([profile])  # type: ignore[union-attr]

        result = self.manager.retrieve(user_input="我刚吃完面，准备睡了。", scene="casual_chat")

        self.assertFalse(result.hit)
        self.assertEqual(result.skipped_reason, "no_relevant_memory")


if __name__ == "__main__":
    unittest.main()
