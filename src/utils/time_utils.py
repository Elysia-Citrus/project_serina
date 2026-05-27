from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
TIME_OF_DAY_LABELS = {
    "morning": "早上",
    "afternoon": "下午",
    "evening": "晚上",
    "late_night": "深夜",
}


@dataclass(frozen=True)
class TimeContext:
    current_local_datetime: str
    current_date: str
    current_time: str
    weekday: str
    time_of_day: str
    session_started_at: str | None
    session_age_seconds: int
    session_age_minutes: int
    last_user_turn_at: str | None
    seconds_since_last_turn: int | None
    minutes_since_last_turn: int | None
    memory_time_summary: str | None = None

    @property
    def summary(self) -> str:
        parts = [
            self.current_local_datetime,
            self.weekday,
            TIME_OF_DAY_LABELS.get(self.time_of_day, self.time_of_day),
        ]
        if self.session_started_at is not None:
            parts.append(f"session_started_at={self.session_started_at}")
            parts.append(f"session_age_minutes={self.session_age_minutes}")
        if self.last_user_turn_at is not None and self.minutes_since_last_turn is not None:
            parts.append(f"minutes_since_last_turn={self.minutes_since_last_turn}")
        if self.memory_time_summary:
            parts.append(self.memory_time_summary)
        return " | ".join(parts)


def get_local_now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def get_time_of_day(now: datetime | None = None) -> str:
    current = now or get_local_now()
    hour = current.hour

    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "late_night"


def get_day_period(now: datetime | None = None) -> str:
    return TIME_OF_DAY_LABELS[get_time_of_day(now)]


def build_time_context(
    *,
    now: datetime | None = None,
    session_started_at: datetime | None = None,
    last_user_turn_at: datetime | None = None,
    memory_time_summary: str | None = None,
) -> TimeContext:
    current = now or get_local_now()
    session_age_seconds = 0
    if session_started_at is not None:
        session_age_seconds = max(
            0,
            int((current - session_started_at).total_seconds()),
        )

    seconds_since_last_turn: int | None = None
    if last_user_turn_at is not None:
        seconds_since_last_turn = max(
            0,
            int((current - last_user_turn_at).total_seconds()),
        )

    return TimeContext(
        current_local_datetime=current.isoformat(timespec="minutes"),
        current_date=current.date().isoformat(),
        current_time=current.strftime("%H:%M"),
        weekday=WEEKDAY_NAMES[current.weekday()],
        time_of_day=get_time_of_day(current),
        session_started_at=(
            session_started_at.isoformat(timespec="seconds")
            if session_started_at is not None
            else None
        ),
        session_age_seconds=session_age_seconds,
        session_age_minutes=session_age_seconds // 60,
        last_user_turn_at=(
            last_user_turn_at.isoformat(timespec="seconds")
            if last_user_turn_at is not None
            else None
        ),
        seconds_since_last_turn=seconds_since_last_turn,
        minutes_since_last_turn=(
            None if seconds_since_last_turn is None else seconds_since_last_turn // 60
        ),
        memory_time_summary=memory_time_summary,
    )


def format_time_context(now: datetime | None = None) -> str:
    context = build_time_context(now=now)
    return (
        f"{context.current_date} {context.current_time}"
        f"（{context.weekday}，{TIME_OF_DAY_LABELS.get(context.time_of_day, context.time_of_day)}）"
    )


def format_time_context_block(context: TimeContext) -> str:
    lines = [
        "【time context】",
        f"- current_local_datetime: {context.current_local_datetime}",
        f"- current_date: {context.current_date}",
        f"- current_time: {context.current_time}",
        f"- weekday: {context.weekday}",
        f"- time_of_day: {context.time_of_day}",
    ]
    if context.session_started_at is not None:
        lines.append(f"- session_started_at: {context.session_started_at}")
        lines.append(f"- session_age_minutes: {context.session_age_minutes}")
    if context.last_user_turn_at is not None:
        lines.append(f"- last_user_turn_at: {context.last_user_turn_at}")
    if context.minutes_since_last_turn is not None:
        lines.append(f"- minutes_since_last_turn: {context.minutes_since_last_turn}")
    if context.memory_time_summary:
        lines.append(f"- related_memory_time_hint: {context.memory_time_summary}")
    return "\n".join(lines)
