from __future__ import annotations

from datetime import datetime


WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def get_local_now() -> datetime:
    return datetime.now().astimezone()


def get_day_period(now: datetime | None = None) -> str:
    current = now or get_local_now()
    hour = current.hour

    if 5 <= hour < 11:
        return "早上"
    if 11 <= hour < 13:
        return "中午"
    if 13 <= hour < 18:
        return "下午"
    if 18 <= hour < 23:
        return "晚上"
    return "深夜"


def format_time_context(now: datetime | None = None) -> str:
    current = now or get_local_now()
    weekday = WEEKDAY_NAMES[current.weekday()]
    period = get_day_period(current)
    return f"{current:%Y-%m-%d %H:%M}，{weekday}，{period}"
