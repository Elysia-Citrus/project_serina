from __future__ import annotations

from datetime import datetime

from src.memory.models import (
    MemoryReadResult,
    MemorySelection,
    SessionContinuityRecord,
    SessionMemoryItem,
    parse_timestamp,
)
from src.memory.rules import (
    extract_retrieval_tokens,
    format_memory_for_prompt,
    score_memory_for_query,
    sort_memory_selections,
)
from src.memory.startup import StartupMemoryBuilder
from src.memory.store import SQLiteMemoryStore


FIRST_SESSION_KEYWORDS = (
    "第一次",
    "最开始",
    "最初",
    "第一次会话",
    "第一次聊天",
    "第一次找你",
)
PREVIOUS_SESSION_KEYWORDS = (
    "上次",
    "上一次",
    "之前",
    "前一次",
    "前面那次",
)
CONTINUITY_TOPIC_KEYWORDS = (
    "会话",
    "聊天",
    "聊到哪",
    "聊过",
    "开始聊",
    "什么时候",
    "记不记得",
)


class MemoryReader:
    def __init__(
        self,
        store: SQLiteMemoryStore,
        max_injection_items: int,
        startup_builder: StartupMemoryBuilder,
    ) -> None:
        self.store = store
        self.max_injection_items = max(2, min(4, max_injection_items))
        self.startup_builder = startup_builder

    def retrieve(
        self,
        *,
        user_input: str,
        scene: str,
        now: datetime,
        session_id: str | None = None,
        session_turn_index: int | None = None,
    ) -> MemoryReadResult:
        startup_pack = None
        if session_turn_index is not None:
            startup_pack = self.startup_builder.build(
                user_input=user_input,
                scene=scene,
                now=now,
                session_id=session_id,
                session_turn_index=session_turn_index,
            )
            if startup_pack.has_items:
                self.store.touch_items(
                    [memory.id for memory in startup_pack.selected_memories],
                    now_iso=now.isoformat(timespec="seconds"),
                )
                debug_selections = tuple(
                    MemorySelection(
                        item=memory,
                        score=1.0,
                        reason="startup_memory_pack",
                    )
                    for memory in startup_pack.selected_memories
                )
                continuity_items = (
                    (startup_pack.last_session_summary,)
                    if startup_pack.last_session_summary is not None
                    else ()
                )
                continuity_prompt_items = tuple(
                    entry.prompt_text
                    for entry in startup_pack.entries
                    if entry.entry_type == "summary"
                )
                return MemoryReadResult(
                    selected_items=tuple(startup_pack.selected_memories),
                    continuity_selected_items=continuity_items,
                    startup_selected_items=tuple(startup_pack.selected_memories),
                    continuity_prompt_items=continuity_prompt_items,
                    startup_prompt_items=startup_pack.prompt_items,
                    prompt_items=startup_pack.prompt_items,
                    debug_selections=debug_selections,
                    continuation_cue_detected=startup_pack.continuation_cue_detected,
                    retrieval_mode=startup_pack.retrieval_mode,
                    startup_categories=startup_pack.categories,
                    last_session_summary_used=startup_pack.last_session_summary_used,
                )

        result = self._retrieve_query_mode(
            user_input=user_input,
            scene=scene,
            now=now,
            session_id=session_id,
        )
        if startup_pack is not None and startup_pack.continuation_cue_detected:
            return MemoryReadResult(
                selected_items=result.selected_items,
                session_selected_items=result.session_selected_items,
                continuity_selected_items=result.continuity_selected_items,
                startup_selected_items=result.startup_selected_items,
                working_prompt_items=result.working_prompt_items,
                session_prompt_items=result.session_prompt_items,
                continuity_prompt_items=result.continuity_prompt_items,
                startup_prompt_items=result.startup_prompt_items,
                prompt_items=result.prompt_items,
                debug_selections=result.debug_selections,
                continuation_cue_detected=True,
                retrieval_mode=result.retrieval_mode,
                startup_categories=result.startup_categories,
                last_session_summary_used=result.last_session_summary_used,
                skipped_reason=result.skipped_reason,
            )
        return result

    def _retrieve_query_mode(
        self,
        *,
        user_input: str,
        scene: str,
        now: datetime,
        session_id: str | None,
    ) -> MemoryReadResult:
        session_ranked = self._select_session_items(
            user_input=user_input,
            now=now,
            session_id=session_id,
        )
        continuity_ranked = self._select_cross_session_items(
            user_input=user_input,
            now=now,
            session_id=session_id,
        )
        memories = self.store.list_active_items()
        selections = []
        for memory in memories:
            selection = score_memory_for_query(
                memory,
                user_input=user_input,
                scene=scene,
                now=now,
            )
            if selection is not None:
                selections.append(selection)

        if not session_ranked and not continuity_ranked and not selections:
            skipped_reason = "empty_store" if not memories else "no_relevant_memory"
            return MemoryReadResult(skipped_reason=skipped_reason)

        prompt_items: list[str] = []
        session_prompt_items: list[str] = []
        continuity_prompt_items: list[str] = []
        continuity_items: list[SessionContinuityRecord] = []
        long_term_items = []
        seen_topics: set[str] = set()

        for item in session_ranked:
            session_prompt_items.append(
                f"[session] {item.display_text().strip().rstrip('。！？')}"
            )
            prompt_items.append(session_prompt_items[-1])
            if len(prompt_items) >= self.max_injection_items:
                break

        if session_prompt_items:
            self.store.touch_session_items(
                [item.id for item in session_ranked[: len(session_prompt_items)]],
                now_iso=now.isoformat(timespec="seconds"),
            )

        remaining_budget = self.max_injection_items - len(prompt_items)
        if remaining_budget > 0:
            for item, snippet in continuity_ranked[:1]:
                continuity_items.append(item)
                continuity_prompt_items.append(snippet)
                prompt_items.append(snippet)
                if len(prompt_items) >= self.max_injection_items:
                    break

        for selection in sort_memory_selections(selections):
            if len(prompt_items) >= self.max_injection_items:
                break
            topic_key = selection.item.topic_key or selection.item.id
            if topic_key in seen_topics:
                continue
            seen_topics.add(topic_key)
            long_term_items.append(selection.item)
            prompt_items.append(format_memory_for_prompt(selection.item))

        if long_term_items:
            self.store.touch_items(
                [item.id for item in long_term_items],
                now_iso=now.isoformat(timespec="seconds"),
            )

        if not prompt_items:
            return MemoryReadResult(skipped_reason="no_relevant_memory")

        return MemoryReadResult(
            selected_items=tuple(long_term_items),
            session_selected_items=tuple(session_ranked[: len(session_prompt_items)]),
            continuity_selected_items=tuple(continuity_items),
            session_prompt_items=tuple(session_prompt_items),
            continuity_prompt_items=tuple(continuity_prompt_items),
            prompt_items=tuple(prompt_items),
            debug_selections=tuple(sort_memory_selections(selections)),
            retrieval_mode="query",
        )

    def _select_session_items(
        self,
        *,
        user_input: str,
        now: datetime,
        session_id: str | None,
    ) -> list[SessionMemoryItem]:
        if not session_id:
            return []
        query_tokens = extract_retrieval_tokens(user_input)
        if not query_tokens:
            return []

        ranked: list[tuple[float, SessionMemoryItem]] = []
        for item in self.store.list_session_items(session_id=session_id, status="active"):
            if item.is_expired(now):
                continue
            text_tokens = extract_retrieval_tokens(
                f"{item.display_text()} {item.topic_key or ''}"
            )
            overlap = query_tokens & text_tokens
            if not overlap:
                continue
            score = float(len(overlap))
            freshness_anchor = item.last_touched_at or item.updated_at
            age_days = max(0, int((now - parse_timestamp(freshness_anchor)).days))
            if age_days <= 1:
                score += 0.6
            elif age_days <= 3:
                score += 0.3
            ranked.append((score, item))

        ranked.sort(
            key=lambda pair: (
                -pair[0],
                -parse_timestamp(pair[1].last_touched_at or pair[1].updated_at).timestamp(),
            )
        )
        limit = max(1, self.max_injection_items - 1)
        return [item for _, item in ranked[:limit]]

    def _select_cross_session_items(
        self,
        *,
        user_input: str,
        now: datetime,
        session_id: str | None,
    ) -> list[tuple[SessionContinuityRecord, str]]:
        if not self._looks_like_continuity_query(user_input):
            return self._select_topic_matched_session_summaries(
                user_input=user_input,
                now=now,
                session_id=session_id,
            )

        if any(keyword in user_input for keyword in FIRST_SESSION_KEYWORDS):
            first = self.store.get_first_session_continuity(
                exclude_session_id=session_id,
                min_turn_count=1,
            )
            if first is None:
                first = self.store.get_first_session_continuity(min_turn_count=1)
            if first is None:
                return []
            return [(first, self._format_first_session_snippet(first))]

        if any(keyword in user_input for keyword in PREVIOUS_SESSION_KEYWORDS):
            recent = self.store.list_session_continuity(
                exclude_session_id=session_id,
                min_turn_count=1,
                limit=1,
            )
            if not recent:
                return []
            return [(recent[0], self._format_recent_session_snippet(recent[0], now=now))]

        return self._select_topic_matched_session_summaries(
            user_input=user_input,
            now=now,
            session_id=session_id,
        )

    def _select_topic_matched_session_summaries(
        self,
        *,
        user_input: str,
        now: datetime,
        session_id: str | None,
    ) -> list[tuple[SessionContinuityRecord, str]]:
        query_tokens = extract_retrieval_tokens(user_input)
        if not query_tokens:
            return []

        ranked: list[tuple[float, SessionContinuityRecord]] = []
        for item in self.store.list_session_continuity(
            exclude_session_id=session_id,
            min_turn_count=1,
            limit=4,
        ):
            text_tokens = extract_retrieval_tokens(
                f"{item.display_text} {item.last_user_message or ''}"
            )
            overlap = query_tokens & text_tokens
            if not overlap:
                continue
            age_days = max(0, int((now - parse_timestamp(item.last_active_at)).days))
            score = float(len(overlap))
            if age_days <= 1:
                score += 0.4
            ranked.append((score, item))

        ranked.sort(
            key=lambda pair: (
                -pair[0],
                -parse_timestamp(pair[1].last_active_at).timestamp(),
            )
        )
        if not ranked:
            return []
        item = ranked[0][1]
        return [(item, self._format_topic_session_snippet(item, now=now))]

    def _looks_like_continuity_query(self, user_input: str) -> bool:
        return any(keyword in user_input for keyword in CONTINUITY_TOPIC_KEYWORDS)

    def _format_first_session_snippet(self, item: SessionContinuityRecord) -> str:
        started_at = parse_timestamp(item.started_at).strftime("%Y-%m-%d %H:%M")
        if item.summary_text:
            return (
                "[continuity] "
                f"已记录的第一次会话开始于 {started_at}，当时大致聊到："
                f"{item.summary_text.strip().rstrip('。')}"
            )
        return f"[continuity] 已记录的第一次会话开始于 {started_at}。"

    def _format_recent_session_snippet(
        self,
        item: SessionContinuityRecord,
        *,
        now: datetime,
    ) -> str:
        last_active = parse_timestamp(item.last_active_at)
        hours_ago = max(0, int((now - last_active).total_seconds() // 3600))
        when_text = f"{hours_ago} 小时前" if hours_ago < 48 else last_active.strftime("%Y-%m-%d %H:%M")
        summary = item.summary_text or item.last_user_message or ""
        if summary:
            return (
                "[continuity] "
                f"上一次已记录会话在 {when_text}，大致聊到："
                f"{summary.strip().rstrip('。')}"
            )
        return f"[continuity] 上一次已记录会话在 {when_text}。"

    def _format_topic_session_snippet(
        self,
        item: SessionContinuityRecord,
        *,
        now: datetime,
    ) -> str:
        last_active = parse_timestamp(item.last_active_at)
        days_ago = max(0, int((now - last_active).days))
        prefix = "最近一轮相关会话里提到过"
        if days_ago >= 2:
            prefix = f"{days_ago} 天前的一轮相关会话里提到过"
        summary = item.summary_text or item.last_user_message or item.first_user_message or ""
        return f"[continuity] {prefix}：{summary.strip().rstrip('。')}"
