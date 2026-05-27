from __future__ import annotations

from datetime import timedelta
import unittest

from src.utils.time_utils import build_time_context, format_time_context_block, get_local_now


class TimeContextTests(unittest.TestCase):
    def test_build_time_context_contains_session_fields(self) -> None:
        now = get_local_now()
        context = build_time_context(
            now=now,
            session_started_at=now - timedelta(minutes=15),
            last_user_turn_at=now - timedelta(minutes=3),
            memory_time_summary="最近一次相关内容出现在 2 小时前",
        )

        self.assertEqual(context.current_date, now.date().isoformat())
        self.assertEqual(context.session_age_minutes, 15)
        self.assertEqual(context.minutes_since_last_turn, 3)
        self.assertEqual(context.memory_time_summary, "最近一次相关内容出现在 2 小时前")

    def test_format_time_context_block_is_stable(self) -> None:
        now = get_local_now()
        context = build_time_context(now=now, session_started_at=now)
        block = format_time_context_block(context)

        self.assertIn("current_local_datetime", block)
        self.assertIn("time_of_day", block)
        self.assertIn("session_started_at", block)


if __name__ == "__main__":
    unittest.main()
