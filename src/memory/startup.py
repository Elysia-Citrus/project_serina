from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.memory.models import MemoryItem, MemorySelection, SessionContinuityRecord, parse_timestamp
from src.memory.rules import extract_retrieval_tokens
from src.memory.store import SQLiteMemoryStore
from src.utils.text_utils import normalize_whitespace, safe_preview


CONTINUATION_CUES = (
    "继续",
    "我们继续",
    "接着",
    "接上次",
    "上次",
    "上回",
    "刚刚那个",
    "刚才那个",
    "那然后呢",
    "然后呢",
    "还有个问题",
    "继续聊",
    "继续看",
    "继续说",
    "continue",
)

GREETING_CUES = (
    "你好",
    "hi",
    "hello",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "晚安",
)


@dataclass(frozen=True)
class StartupMemoryConfig:
    enabled: bool
    turn_window: int
    max_total_items: int
    profile_limit: int
    episodic_limit: int
    open_loop_limit: int
    summary_limit: int


@dataclass(frozen=True)
class StartupMemoryEntry:
    entry_type: str
    category: str
    summary: str
    score: float
    memory_id: str | None = None
    session_id: str | None = None

    @property
    def prompt_text(self) -> str:
        return f"[startup-{self.entry_type}] {self.summary}"


@dataclass(frozen=True)
class StartupMemoryPack:
    entries: tuple[StartupMemoryEntry, ...] = ()
    selected_memories: tuple[MemoryItem, ...] = ()
    last_session_summary: SessionContinuityRecord | None = None
    continuation_cue_detected: bool = False
    retrieval_mode: str = "query"

    @property
    def prompt_items(self) -> tuple[str, ...]:
        return tuple(entry.prompt_text for entry in self.entries)

    @property
    def memory_ids(self) -> tuple[str, ...]:
        ids = [entry.memory_id for entry in self.entries if entry.memory_id]
        if self.last_session_summary is not None:
            ids.append(f"continuity:{self.last_session_summary.session_id}")
        return tuple(ids)

    @property
    def categories(self) -> tuple[str, ...]:
        values = [entry.category for entry in self.entries if entry.category]
        if self.last_session_summary is not None:
            values.append("last_session_summary")
        return tuple(values)

    @property
    def last_session_summary_used(self) -> bool:
        return self.last_session_summary is not None

    @property
    def has_items(self) -> bool:
        return bool(self.entries)


def detect_continuation_cue(user_input: str) -> bool:
    text = normalize_whitespace(user_input).casefold()
    if not text:
        return False
    return any(cue.casefold() in text for cue in CONTINUATION_CUES)


class StartupMemoryBuilder:
    def __init__(
        self,
        store: SQLiteMemoryStore,
        config: StartupMemoryConfig,
    ) -> None:
        self.store = store
        self.config = config

    def build(
        self,
        *,
        user_input: str,
        scene: str,
        now: datetime,
        session_id: str | None,
        session_turn_index: int,
    ) -> StartupMemoryPack:
        if (
            not self.config.enabled
            or session_turn_index <= 0
            or session_turn_index > self.config.turn_window
        ):
            return StartupMemoryPack()

        continuation_cue_detected = detect_continuation_cue(user_input)
        query_tokens = extract_retrieval_tokens(user_input)
        greeting_like = self._looks_like_greeting(user_input=user_input, scene=scene)

        visible_memories = [
            memory
            for memory in self.store.list_active_items()
            if memory.cross_session_visible and not memory.is_expired(now)
        ]

        profile_ranked = self._rank_memories(
            [item for item in visible_memories if item.memory_class == "profile"],
            now=now,
            query_tokens=query_tokens,
            category="profile",
            continuation_cue_detected=continuation_cue_detected,
        )
        episodic_ranked = self._rank_memories(
            [item for item in visible_memories if item.memory_class == "episodic"],
            now=now,
            query_tokens=query_tokens,
            category="episodic",
            continuation_cue_detected=continuation_cue_detected,
        )
        open_loop_ranked = self._rank_memories(
            [
                item
                for item in visible_memories
                if item.memory_class == "task" or item.followup_enabled
            ],
            now=now,
            query_tokens=query_tokens,
            category="open_loop",
            continuation_cue_detected=continuation_cue_detected,
        )
        summary_record = self._select_last_session_summary(
            user_input=user_input,
            now=now,
            session_id=session_id,
            continuation_cue_detected=continuation_cue_detected,
            query_tokens=query_tokens,
        )

        entries: list[StartupMemoryEntry] = []
        selected_memories: list[MemoryItem] = []
        used_memory_ids: set[str] = set()
        remaining = self.config.max_total_items

        if (
            continuation_cue_detected
            and summary_record is not None
            and self.config.summary_limit > 0
            and remaining > 0
        ):
            summary_text = self._format_last_session_summary(summary_record, now=now)
            entries.append(
                StartupMemoryEntry(
                    entry_type="summary",
                    category="last_session_summary",
                    summary=summary_text,
                    score=2.0,
                    session_id=summary_record.session_id,
                )
            )
            remaining -= 1

        if greeting_like and not continuation_cue_detected:
            self._extend_entries(
                entries,
                selected_memories,
                used_memory_ids,
                profile_ranked[: self.config.profile_limit],
                category="profile",
                entry_type="profile",
                limit=min(2, self.config.profile_limit, remaining),
            )
            return StartupMemoryPack(
                entries=tuple(entries),
                selected_memories=tuple(selected_memories),
                last_session_summary=None,
                continuation_cue_detected=continuation_cue_detected,
                retrieval_mode="startup" if entries else "query",
            )

        if continuation_cue_detected:
            remaining = self._extend_entries(
                entries,
                selected_memories,
                used_memory_ids,
                open_loop_ranked,
                category="open_loop",
                entry_type="open-loop",
                limit=min(self.config.open_loop_limit, remaining),
                remaining=remaining,
            )
            remaining = self._extend_entries(
                entries,
                selected_memories,
                used_memory_ids,
                episodic_ranked,
                category="recent_episodic",
                entry_type="episodic",
                limit=min(self.config.episodic_limit, remaining),
                remaining=remaining,
            )

        remaining = self._extend_entries(
            entries,
            selected_memories,
            used_memory_ids,
            profile_ranked,
            category="profile",
            entry_type="profile",
            limit=min(self.config.profile_limit, remaining),
            remaining=remaining,
        )

        if not continuation_cue_detected:
            if query_tokens:
                remaining = self._extend_entries(
                    entries,
                    selected_memories,
                    used_memory_ids,
                    open_loop_ranked,
                    category="open_loop",
                    entry_type="open-loop",
                    limit=min(1, self.config.open_loop_limit, remaining),
                    remaining=remaining,
                )
                remaining = self._extend_entries(
                    entries,
                    selected_memories,
                    used_memory_ids,
                    episodic_ranked,
                    category="recent_episodic",
                    entry_type="episodic",
                    limit=min(1, self.config.episodic_limit, remaining),
                    remaining=remaining,
                )
                if (
                    summary_record is not None
                    and self.config.summary_limit > 0
                    and remaining > 0
                ):
                    entries.append(
                        StartupMemoryEntry(
                            entry_type="summary",
                            category="last_session_summary",
                            summary=self._format_last_session_summary(summary_record, now=now),
                            score=1.1,
                            session_id=summary_record.session_id,
                        )
                    )

        if not entries:
            return StartupMemoryPack(
                continuation_cue_detected=continuation_cue_detected,
                retrieval_mode="query",
            )

        return StartupMemoryPack(
            entries=tuple(entries[: self.config.max_total_items]),
            selected_memories=tuple(selected_memories[: self.config.max_total_items]),
            last_session_summary=summary_record if any(
                entry.entry_type == "summary" for entry in entries
            ) else None,
            continuation_cue_detected=continuation_cue_detected,
            retrieval_mode="startup",
        )

    def _looks_like_greeting(self, *, user_input: str, scene: str) -> bool:
        text = normalize_whitespace(user_input).casefold()
        if scene == "greeting":
            return True
        return len(text) <= 12 and any(cue.casefold() in text for cue in GREETING_CUES)

    def _rank_memories(
        self,
        memories: list[MemoryItem],
        *,
        now: datetime,
        query_tokens: set[str],
        category: str,
        continuation_cue_detected: bool,
    ) -> list[MemorySelection]:
        ranked: list[MemorySelection] = []
        for memory in memories:
            memory_tokens = extract_retrieval_tokens(
                " ".join(
                    filter(
                        None,
                        (
                            memory.display_text(),
                            memory.source_message_excerpt,
                            memory.topic_key or "",
                            memory.preference_target or "",
                            memory.preference_value or "",
                        ),
                    )
                )
            )
            overlap = query_tokens & memory_tokens
            if query_tokens and not continuation_cue_detected and category != "profile" and not overlap:
                continue

            age_days = max(0, int((now - parse_timestamp(memory.updated_at)).days))
            score = memory.confidence + min(1.0, memory.useful_score)
            score += min(0.8, max(0, 7 - age_days) * 0.1)
            score += min(0.5, len(overlap) * 0.3)
            if memory.last_used_at is not None:
                used_days = max(0, int((now - parse_timestamp(memory.last_used_at)).days))
                score += max(0.0, 0.3 - used_days * 0.05)
            if memory.pinned:
                score += 0.4
            if category == "profile":
                score += 0.7 if memory.representation == "preference" else 0.35
            elif category == "open_loop":
                score += 0.9 if memory.followup_enabled else 0.5
                if continuation_cue_detected:
                    score += 0.7
            elif category == "episodic":
                score += 0.5
                if continuation_cue_detected:
                    score += 0.4

            ranked.append(
                MemorySelection(
                    item=memory,
                    score=score,
                    reason=f"startup_{category}:overlap={len(overlap)}",
                )
            )

        ranked.sort(
            key=lambda selection: (
                -selection.score,
                -parse_timestamp(selection.item.updated_at).timestamp(),
            )
        )
        return ranked

    def _select_last_session_summary(
        self,
        *,
        user_input: str,
        now: datetime,
        session_id: str | None,
        continuation_cue_detected: bool,
        query_tokens: set[str],
    ) -> SessionContinuityRecord | None:
        recent = self.store.list_session_continuity(
            exclude_session_id=session_id,
            min_turn_count=1,
            limit=3,
        )
        if not recent:
            return None
        if continuation_cue_detected:
            return recent[0]

        ranked: list[tuple[float, SessionContinuityRecord]] = []
        for item in recent:
            summary = normalize_whitespace(
                item.summary_text or item.last_user_message or item.first_user_message or ""
            )
            if not summary:
                continue
            summary_tokens = extract_retrieval_tokens(summary)
            overlap = query_tokens & summary_tokens
            if query_tokens and not overlap:
                continue
            age_days = max(0, int((now - parse_timestamp(item.last_active_at)).days))
            score = float(len(overlap)) + max(0.0, 1.0 - age_days * 0.15)
            ranked.append((score, item))
        if not ranked:
            return None
        ranked.sort(key=lambda pair: (-pair[0], -parse_timestamp(pair[1].last_active_at).timestamp()))
        return ranked[0][1]

    def _format_last_session_summary(
        self,
        item: SessionContinuityRecord,
        *,
        now: datetime,
    ) -> str:
        last_active = parse_timestamp(item.last_active_at)
        age_hours = max(0, int((now - last_active).total_seconds() // 3600))
        age_label = (
            f"{age_hours}h ago"
            if age_hours < 48
            else last_active.strftime("%Y-%m-%d %H:%M")
        )
        summary = normalize_whitespace(
            item.summary_text or item.last_user_message or item.first_user_message or ""
        ).strip()
        clipped = safe_preview(summary, 120).rstrip("。.!? ")
        return f"Last session ({age_label}) focused on: {clipped}"

    def _extend_entries(
        self,
        entries: list[StartupMemoryEntry],
        selected_memories: list[MemoryItem],
        used_memory_ids: set[str],
        ranked: list[MemorySelection],
        *,
        category: str,
        entry_type: str,
        limit: int,
        remaining: int | None = None,
    ) -> int:
        available = limit if remaining is None else min(limit, remaining)
        count = 0
        for selection in ranked:
            if count >= available:
                break
            if selection.item.id in used_memory_ids:
                continue
            summary = self._format_memory_summary(selection.item, category=category)
            entries.append(
                StartupMemoryEntry(
                    entry_type=entry_type,
                    category=category,
                    summary=summary,
                    score=selection.score,
                    memory_id=selection.item.id,
                )
            )
            selected_memories.append(selection.item)
            used_memory_ids.add(selection.item.id)
            count += 1
        if remaining is None:
            return 0
        return max(0, remaining - count)

    def _format_memory_summary(self, memory: MemoryItem, *, category: str) -> str:
        text = safe_preview(normalize_whitespace(memory.display_text()), 120).rstrip("。.!? ")
        if category == "profile":
            return f"Known preference or profile: {text}"
        if category == "open_loop":
            return f"Open loop worth continuing: {text}"
        return f"Recent track that may still matter: {text}"
