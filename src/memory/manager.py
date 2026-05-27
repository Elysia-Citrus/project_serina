from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json

from src.config.loader import AppConfig
from src.memory.decay import SessionDecayService
from src.memory.consolidator import build_session_consolidation_snapshot
from src.memory.models import (
    ConversationTurn,
    MemoryCandidate,
    MemoryItem,
    MemoryReadResult,
    SessionConsolidationResult,
    SessionContinuityRecord,
    SessionFinalizeResult,
    SessionMaintenanceResult,
    MemoryStoreStats,
    MemoryRepresentation,
    MemoryReviewState,
    SessionMemoryCandidate,
    SessionMemoryItem,
    MemoryTurnInput,
    MemoryWriteResult,
    now_timestamp,
)
from src.memory.reader import MemoryReader
from src.memory.rules import build_topic_key
from src.memory.startup import StartupMemoryBuilder, StartupMemoryConfig
from src.memory.store import SQLiteMemoryStore
from src.memory.summarizer import SessionSummarizer
from src.memory.writer import MemoryWriter
from src.observability.trace import TurnTrace
from src.utils.logger import log_event
from src.utils.text_utils import normalize_whitespace, safe_preview

_UNSET = object()


@dataclass(frozen=True)
class MemoryManagerConfig:
    enabled: bool
    write_enabled: bool
    store_type: str
    store_path: Path
    max_injection_items: int
    startup_memory_enabled: bool
    startup_memory_turn_window: int
    startup_memory_profile_limit: int
    startup_memory_episodic_limit: int
    startup_memory_open_loop_limit: int
    startup_memory_summary_limit: int
    startup_memory_total_limit: int
    episodic_ttl_days: int
    merge_time_window_hours: int
    session_ttl_days: int = 3


class MemoryManager:
    def __init__(self, config: MemoryManagerConfig) -> None:
        self.config = config
        self.store = (
            self._build_store(config.store_type, config.store_path)
            if config.enabled or config.write_enabled
            else None
        )
        self.reader = (
            MemoryReader(
                self.store,
                config.max_injection_items,
                StartupMemoryBuilder(
                    self.store,
                    StartupMemoryConfig(
                        enabled=config.startup_memory_enabled,
                        turn_window=config.startup_memory_turn_window,
                        max_total_items=config.startup_memory_total_limit,
                        profile_limit=config.startup_memory_profile_limit,
                        episodic_limit=config.startup_memory_episodic_limit,
                        open_loop_limit=config.startup_memory_open_loop_limit,
                        summary_limit=config.startup_memory_summary_limit,
                    ),
                ),
            )
            if self.store is not None
            else None
        )
        self.writer = (
            MemoryWriter(
                self.store,
                config.episodic_ttl_days,
                config.merge_time_window_hours,
            )
            if self.store is not None
            else None
        )
        self.session_summarizer = (
            SessionSummarizer(config.episodic_ttl_days)
            if self.store is not None
            else None
        )
        self.session_decay = (
            SessionDecayService(self.store)
            if self.store is not None
            else None
        )

    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> "MemoryManager":
        project_root = app_config.config_dir.parent.parent
        runtime = app_config.runtime
        return cls(
            MemoryManagerConfig(
                enabled=runtime.memory_enabled,
                write_enabled=runtime.memory_write_enabled,
                store_type=runtime.memory_store_type,
                store_path=_resolve_store_path(project_root, runtime.memory_store_path),
                max_injection_items=runtime.max_memory_injection_items,
                startup_memory_enabled=runtime.startup_memory_enabled,
                startup_memory_turn_window=runtime.startup_memory_turn_window,
                startup_memory_profile_limit=runtime.startup_memory_profile_limit,
                startup_memory_episodic_limit=runtime.startup_memory_episodic_limit,
                startup_memory_open_loop_limit=runtime.startup_memory_open_loop_limit,
                startup_memory_summary_limit=runtime.startup_memory_summary_limit,
                startup_memory_total_limit=runtime.startup_memory_total_limit,
                episodic_ttl_days=runtime.episodic_memory_ttl_days,
                merge_time_window_hours=runtime.merge_time_window_hours,
                session_ttl_days=3,
            )
        )

    def preview_write_candidates(
        self,
        turn: MemoryTurnInput,
        *,
        now: datetime | None = None,
    ) -> tuple[MemoryCandidate, ...]:
        if self.store is None or self.writer is None:
            return ()
        current_time = now or now_timestamp()
        return tuple(self.writer.extract_turn_candidates(turn, now=current_time))

    def retrieve(
        self,
        *,
        user_input: str,
        scene: str,
        session_id: str | None = None,
        session_turn_index: int | None = None,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryReadResult:
        if not self.config.enabled or self.store is None or self.reader is None:
            result = MemoryReadResult(skipped_reason="memory_disabled")
            log_event(
                "memory_retrieval_skipped",
                level="DEBUG",
                turn_trace=turn_trace,
                skipped_reason=result.skipped_reason,
            )
            return result

        current_time = now or now_timestamp()
        expired_count = self.store.expire_episodic_entries(
            current_time.isoformat(timespec="seconds")
        )
        session_expired_count = self.store.expire_session_entries(
            current_time.isoformat(timespec="seconds")
        )
        result = self.reader.retrieve(
            user_input=user_input,
            scene=scene,
            now=current_time,
            session_id=session_id,
            session_turn_index=session_turn_index,
        )
        log_event(
            "memory_retrieval_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            expired_count=expired_count,
            session_expired_count=session_expired_count,
            retrieval_mode=result.retrieval_mode,
            memory_selected_ids=result.selected_ids,
            memory_selected_count=len(result.selected_ids),
            startup_memory_pack_present=bool(result.startup_prompt_items),
            startup_memory_pack_count=len(result.startup_prompt_items),
            startup_memory_memory_ids=result.startup_selected_ids,
            startup_memory_categories=result.startup_categories,
            continuation_cue_detected=result.continuation_cue_detected,
            last_session_summary_used=result.last_session_summary_used,
            memory_selection_reasons=[
                {
                    "id": selection.item.id,
                    "score": round(selection.score, 2),
                    "reason": selection.reason,
                }
                for selection in result.debug_selections
            ],
            skipped_reason=result.skipped_reason,
        )
        return result

    def summarize_memory_time_context(
        self,
        items: tuple[object, ...],
        *,
        now: datetime | None = None,
    ) -> str | None:
        current_time = now or now_timestamp()
        if not items:
            return None

        timestamps: list[datetime] = []
        for item in items:
            for field_name in ("last_touched_at", "last_confirmed_at", "updated_at", "created_at"):
                raw_value = getattr(item, field_name, None)
                if raw_value:
                    timestamps.append(datetime.fromisoformat(str(raw_value)))
                    break

        if not timestamps:
            return None

        latest = max(timestamps)
        age_minutes = max(0, int((current_time - latest).total_seconds() // 60))
        if age_minutes < 60:
            return f"最近一次相关内容出现在 {age_minutes} 分钟前"
        age_hours = age_minutes // 60
        if age_hours < 24:
            return f"最近一次相关内容出现在 {age_hours} 小时前"
        return f"最近一次相关内容出现在 {age_hours // 24} 天前"

    def register_session(
        self,
        *,
        session_id: str,
        started_at: datetime,
        turn_trace: TurnTrace | None = None,
    ) -> SessionContinuityRecord | None:
        if self.store is None:
            return None
        record = self.store.register_session(
            session_id=session_id,
            started_at=started_at.isoformat(timespec="seconds"),
        )
        log_event(
            "session_continuity_registered",
            level="DEBUG",
            turn_trace=turn_trace,
            session_id=session_id,
            started_at=record.started_at,
        )
        return record

    def record_session_continuity(
        self,
        *,
        session_id: str,
        session_started_at: datetime,
        turn: MemoryTurnInput,
        session_items: tuple[SessionMemoryItem, ...] = (),
        stored_items: tuple[MemoryItem, ...] = (),
        now: datetime | None = None,
        turn_trace: TurnTrace | None = None,
    ) -> SessionContinuityRecord | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        summary_text = self._build_session_continuity_summary(
            turn=turn,
            session_items=session_items,
            stored_items=stored_items,
        )
        metadata = {
            "turn_id": turn.turn_id,
            "scene": turn.scene,
            "session_item_ids": [item.id for item in session_items[:2]],
            "stored_memory_ids": [item.id for item in stored_items[:2]],
        }
        record = self.store.update_session_continuity(
            session_id=session_id,
            started_at=session_started_at.isoformat(timespec="seconds"),
            last_active_at=current_time.isoformat(timespec="seconds"),
            user_message=safe_preview(normalize_whitespace(turn.user_input), 120),
            assistant_message=safe_preview(normalize_whitespace(turn.assistant_reply), 120),
            scene=turn.scene,
            summary_text=summary_text,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )
        log_event(
            "session_continuity_updated",
            level="DEBUG",
            turn_trace=turn_trace,
            session_id=session_id,
            continuity_turn_count=record.turn_count,
            continuity_summary=safe_preview(record.summary_text or "", 80),
        )
        return record

    def write_turn(
        self,
        turn: MemoryTurnInput,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryWriteResult:
        if not self.config.write_enabled or self.store is None or self.writer is None:
            result = MemoryWriteResult(skipped_reason="memory_write_disabled")
            log_event(
                "memory_write_skipped",
                level="DEBUG",
                turn_trace=turn_trace,
                skipped_reason=result.skipped_reason,
            )
            return result

        current_time = now or now_timestamp()
        self.store.expire_episodic_entries(current_time.isoformat(timespec="seconds"))
        extracted_candidates = self.writer.extract_turn_candidates(turn, now=current_time)
        log_event(
            "memory_candidates_extracted",
            level="DEBUG",
            turn_trace=turn_trace,
            candidate_count=len(extracted_candidates),
            candidate_previews=[
                {
                    "reason": candidate.candidate_reason,
                    "type": candidate.memory_type,
                    "preview": safe_preview(candidate.content, 60),
                    "topic_key": candidate.topic_key,
                    "followup_enabled": candidate.followup_enabled,
                }
                for candidate in extracted_candidates
            ],
        )
        result = self.writer.write_turn(turn, now=current_time)
        log_event(
            "memory_write_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            memory_written_ids=result.stored_ids,
            memory_written_count=len(result.stored_ids),
            candidate_decisions=[
                {
                    "preview": decision.candidate_preview,
                    "accepted": decision.accepted,
                    "action": decision.action,
                    "reason": decision.reason,
                    "memory_id": decision.memory_id,
                    "candidate_reason": decision.candidate_reason,
                }
                for decision in result.decisions
            ],
            skipped_reason=result.skipped_reason,
        )
        if not extracted_candidates:
            log_event(
                "memory_candidate_rejected",
                level="DEBUG",
                turn_trace=turn_trace,
                reason="no_high_signal_candidate",
            )
        return result

    def record_conversation_turn(
        self,
        turn: MemoryTurnInput,
        *,
        session_id: str,
        turn_index: int,
        started_at: datetime,
        completed_at: datetime,
        turn_trace: TurnTrace | None = None,
    ) -> str | None:
        if self.store is None:
            return None
        record = ConversationTurn(
            id=turn.turn_id,
            session_id=session_id,
            turn_index=turn_index,
            source_channel=turn.source_channel,
            user_text=turn.user_input,
            assistant_text=turn.assistant_reply,
            raw_asr_text=turn.raw_asr_text,
            scene=turn.scene,
            started_at=started_at.isoformat(timespec="seconds"),
            completed_at=completed_at.isoformat(timespec="seconds"),
            llm_provider=turn.llm_provider,
            llm_model=turn.llm_model,
            asr_provider=turn.asr_provider,
            tts_provider=turn.tts_provider,
            latency_json=turn.latency_json,
            metadata_json=turn.metadata_json,
        )
        saved_id = self.store.save_conversation_turn(record)
        log_event(
            "conversation_turn_saved",
            level="DEBUG",
            turn_trace=turn_trace,
            session_id=session_id,
            turn_index=turn_index,
            source_channel=turn.source_channel,
        )
        return saved_id

    def list_memories(
        self,
        *,
        memory_type: str | None = None,
        status: str | None = "active",
        memory_class: str | None = None,
        representation: str | None = None,
        namespace: str | None = None,
        owner_kind: str | None = None,
        review_states: tuple[MemoryReviewState, ...] | None = None,
        limit: int | None = None,
    ) -> tuple[MemoryItem, ...]:
        if self.store is None:
            return ()
        return tuple(
            self.store.list_items(
                memory_type=memory_type,
                status=status,
                memory_class=memory_class,
                representation=representation,
                namespace=namespace,
                owner_kind=owner_kind,
                review_states=review_states,
                limit=limit,
            )
        )

    def list_session_memories(
        self,
        *,
        session_id: str | None = None,
        status: str | None = "active",
        consolidation_states: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> tuple[SessionMemoryItem, ...]:
        if self.store is None:
            return ()
        return tuple(
            self.store.list_session_items(
                session_id=session_id,
                status=status,
                consolidation_states=consolidation_states,
                limit=limit,
            )
        )

    def get_memory(self, memory_id: str) -> MemoryItem | None:
        if self.store is None:
            return None
        return self.store.get_item(memory_id)

    def delete_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
    ) -> bool:
        if self.store is None:
            return False
        deleted = self.store.delete_item(memory_id)
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action="delete",
            memory_id=memory_id,
            success=deleted,
        )
        return deleted

    def archive_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        return self._status_action(
            action="archive",
            memory_id=memory_id,
            turn_trace=turn_trace,
            now=now,
        )

    def expire_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        return self._status_action(
            action="expire",
            memory_id=memory_id,
            turn_trace=turn_trace,
            now=now,
        )

    def activate_memory(
        self,
        memory_id: str,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        return self._status_action(
            action="activate",
            memory_id=memory_id,
            turn_trace=turn_trace,
            now=now,
        )

    def set_pinned(
        self,
        memory_id: str,
        pinned: bool,
        *,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        item = self.store.set_pinned(
            memory_id,
            pinned=pinned,
            now_iso=current_time.isoformat(timespec="seconds"),
        )
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action="pin" if pinned else "unpin",
            memory_id=memory_id,
            success=item is not None,
        )
        return item

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | object = _UNSET,
        canonical_text: str | None | object = _UNSET,
        confidence: float | object = _UNSET,
        expires_at: str | None | object = _UNSET,
        summary: str | None | object = _UNSET,
        status: str | object = _UNSET,
        review_state: str | object = _UNSET,
        stale_reason: str | None | object = _UNSET,
        last_confirmed_at: str | None | object = _UNSET,
        supersedes_id: str | None | object = _UNSET,
        contradicts_id: str | None | object = _UNSET,
        turn_trace: TurnTrace | None = None,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        update_kwargs: dict[str, object] = {
            "now_iso": current_time.isoformat(timespec="seconds")
        }
        if content is not _UNSET:
            update_kwargs["content"] = content
        if canonical_text is not _UNSET:
            update_kwargs["canonical_text"] = canonical_text
        if confidence is not _UNSET:
            update_kwargs["confidence"] = confidence
        if expires_at is not _UNSET:
            update_kwargs["expires_at"] = expires_at
        if summary is not _UNSET:
            update_kwargs["summary"] = summary
        if status is not _UNSET:
            update_kwargs["status"] = status
        if review_state is not _UNSET:
            update_kwargs["review_state"] = review_state
        if stale_reason is not _UNSET:
            update_kwargs["stale_reason"] = stale_reason
        if last_confirmed_at is not _UNSET:
            update_kwargs["last_confirmed_at"] = last_confirmed_at
        if supersedes_id is not _UNSET:
            update_kwargs["supersedes_id"] = supersedes_id
        if contradicts_id is not _UNSET:
            update_kwargs["contradicts_id"] = contradicts_id
        item = self.store.update_item(
            memory_id,
            **update_kwargs,
        )
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action="update",
            memory_id=memory_id,
            success=item is not None,
        )
        return item

    def mark_followup_sent(
        self,
        memory_id: str,
        *,
        now: datetime | None = None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        return self.store.mark_followup_sent(
            memory_id,
            current_time.isoformat(timespec="seconds"),
        )

    def record_session_turn(
        self,
        *,
        session_id: str,
        turn: MemoryTurnInput,
        stored_items: tuple[MemoryItem, ...],
        now: datetime | None = None,
    ) -> tuple[SessionMemoryItem, ...]:
        if self.store is None:
            return ()
        current_time = now or now_timestamp()
        now_iso = current_time.isoformat(timespec="seconds")
        self.store.expire_session_entries(now_iso)
        candidates = self._build_session_candidates(
            session_id=session_id,
            turn=turn,
            stored_items=stored_items,
            now=current_time,
        )
        if not candidates:
            return ()
        return tuple(
            self.store.upsert_session_candidate(candidate, now_iso) for candidate in candidates
        )

    def run_session_maintenance(
        self,
        *,
        session_id: str | None = None,
        limit: int = 1,
        now: datetime | None = None,
    ) -> SessionMaintenanceResult:
        if (
            self.store is None
            or self.writer is None
            or self.session_summarizer is None
            or self.session_decay is None
            or limit <= 0
        ):
            return SessionMaintenanceResult()

        current_time = now or now_timestamp()
        now_iso = current_time.isoformat(timespec="seconds")
        decay_sweep = self.session_decay.sweep(
            now=current_time,
            session_id=session_id,
            final_attempt_limit=limit,
        )
        processed: list[SessionConsolidationResult] = []
        processed_ids = {item.id for item in decay_sweep.final_attempt_items}

        for item in decay_sweep.final_attempt_items:
            result = self._consolidate_session_item(
                item,
                now=current_time,
                final_attempt=True,
            )
            processed.append(result)

        remaining_limit = max(0, limit - len(processed))
        if remaining_limit > 0:
            pending_items = self.store.list_session_items(
                session_id=session_id,
                status="active",
                consolidation_states=("pending",),
                limit=max(remaining_limit * 4, remaining_limit),
            )
            for item in pending_items:
                if item.id in processed_ids or item.origin_kind != "session_only":
                    continue
                result = self._consolidate_session_item(
                    item,
                    now=current_time,
                    final_attempt=False,
                )
                processed.append(result)
                if len(processed) >= limit:
                    break

        return SessionMaintenanceResult(
            processed=tuple(processed),
            archived_session_ids=decay_sweep.archived_ids,
            expired_count=decay_sweep.expired_count,
        )

    def get_store_stats(self) -> MemoryStoreStats:
        if self.store is None:
            return MemoryStoreStats()
        return self.store.get_stats()

    def list_session_continuity(
        self,
        *,
        exclude_session_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[SessionContinuityRecord, ...]:
        if self.store is None:
            return ()
        return tuple(
            self.store.list_session_continuity(
                exclude_session_id=exclude_session_id,
                min_turn_count=1,
                limit=limit,
            )
        )

    def finalize_session(
        self,
        *,
        session_id: str,
        now: datetime | None = None,
        turn_trace: TurnTrace | None = None,
    ) -> SessionFinalizeResult:
        if self.store is None:
            return SessionFinalizeResult(
                session_id=session_id,
                skipped_reason="memory_store_unavailable",
            )

        current_time = now or now_timestamp()
        session_items = self.store.list_session_items(
            session_id=session_id,
            status="active",
        )
        if not session_items:
            return SessionFinalizeResult(
                session_id=session_id,
                skipped_reason="empty_session",
            )

        maintenance = self.run_session_maintenance(
            session_id=session_id,
            limit=max(1, self.config.startup_memory_total_limit),
            now=current_time,
        )
        promoted_memory_ids = tuple(
            dict.fromkeys(
                memory_id
                for result in maintenance.processed
                for memory_id in result.produced_memory_refs
                if memory_id
            )
        )
        promoted_memories = tuple(
            memory
            for memory in (
                self.store.get_item(memory_id) for memory_id in promoted_memory_ids
            )
            if memory is not None
        )
        refreshed_session_items = self.store.list_session_items(
            session_id=session_id,
            status="active",
        )
        snapshot = build_session_consolidation_snapshot(
            session_items=refreshed_session_items,
            promoted_memories=promoted_memories,
            now=current_time,
        )
        metadata_json = json.dumps(
            {
                "consolidated_at": current_time.isoformat(timespec="seconds"),
                "promoted_memory_ids": list(promoted_memory_ids),
                "open_loop_memory_ids": list(snapshot.open_loop_memory_ids),
                "processed_session_item_ids": [
                    result.session_item_id for result in maintenance.processed
                ],
            },
            ensure_ascii=False,
        )
        continuity_record = self.store.update_session_continuity_snapshot(
            session_id=session_id,
            last_active_at=current_time.isoformat(timespec="seconds"),
            summary_text=snapshot.summary_text,
            metadata_json=metadata_json,
            minimum_turn_count=1,
        )
        log_event(
            "session_consolidated",
            level="DEBUG",
            turn_trace=turn_trace,
            session_id=session_id,
            consolidation_triggered=bool(maintenance.processed),
            promoted_memory_count=len(promoted_memory_ids),
            promoted_memory_ids=promoted_memory_ids,
            open_loop_memory_ids=snapshot.open_loop_memory_ids,
            last_session_summary_present=snapshot.summary_text is not None,
        )
        return SessionFinalizeResult(
            session_id=session_id,
            summary_text=snapshot.summary_text,
            promoted_memory_ids=promoted_memory_ids,
            open_loop_memory_ids=snapshot.open_loop_memory_ids,
            consolidation_triggered=bool(maintenance.processed),
            continuity_updated=continuity_record is not None,
        )

    def _build_store(self, store_type: str, store_path: Path) -> SQLiteMemoryStore:
        if store_type.lower() != "sqlite":
            raise ValueError(f"Unsupported memory store type: {store_type}")
        return SQLiteMemoryStore(store_path)

    def _build_session_continuity_summary(
        self,
        *,
        turn: MemoryTurnInput,
        session_items: tuple[SessionMemoryItem, ...],
        stored_items: tuple[MemoryItem, ...],
    ) -> str | None:
        ranked_session_items = sorted(
            session_items,
            key=lambda item: (
                0 if item.carryover_kind == "task" else 1,
                0 if item.carryover_kind in {"session", "episodic"} else 1,
                -item.importance,
                -item.confidence,
            ),
        )
        for item in ranked_session_items:
            text = normalize_whitespace(
                item.summary_text or item.content_summary or item.display_text()
            ).strip()
            if text:
                return text

        ranked_memories = sorted(
            stored_items,
            key=lambda item: (
                0 if item.memory_class == "task" else 1,
                0 if item.memory_class == "episodic" else 1,
                -item.confidence,
            ),
        )
        for item in ranked_memories:
            text = normalize_whitespace(item.summary or item.display_text()).strip()
            if text:
                return text

        conclusion_text = _extract_session_conclusion(turn.user_input)
        if conclusion_text:
            return f"这轮主要聊到：{conclusion_text}"

        topic_summary = _extract_session_topic_summary(turn.user_input)
        if topic_summary:
            return f"这轮主要聊到：{topic_summary}"

        preview = safe_preview(normalize_whitespace(turn.user_input), 60)
        if len(preview) >= 12:
            return f"这轮提到：{preview}"
        return None

    def _status_action(
        self,
        *,
        action: str,
        memory_id: str,
        turn_trace: TurnTrace | None,
        now: datetime | None,
    ) -> MemoryItem | None:
        if self.store is None:
            return None
        current_time = now or now_timestamp()
        now_iso = current_time.isoformat(timespec="seconds")
        if action == "archive":
            item = self.store.archive_item(memory_id, now_iso)
        elif action == "expire":
            item = self.store.expire_item(memory_id, now_iso)
        else:
            item = self.store.activate_item(memory_id, now_iso)
        log_event(
            "memory_manual_override",
            level="INFO",
            turn_trace=turn_trace,
            override_action=action,
            memory_id=memory_id,
            success=item is not None,
        )
        return item

    def _build_session_candidates(
        self,
        *,
        session_id: str,
        turn: MemoryTurnInput,
        stored_items: tuple[MemoryItem, ...],
        now: datetime,
    ) -> tuple[SessionMemoryCandidate, ...]:
        bridge_candidates = self._build_session_bridge_candidates(
            session_id=session_id,
            turn=turn,
            stored_items=stored_items,
        )
        session_only_candidates = self._build_session_only_candidates(
            session_id=session_id,
            turn=turn,
            now=now,
            stored_items=stored_items,
        )
        seen_keys: set[tuple[str, str | None, str]] = set()
        ordered_candidates = [*bridge_candidates, *session_only_candidates]
        candidates: list[SessionMemoryCandidate] = []
        for candidate in ordered_candidates:
            key = (
                candidate.origin_kind,
                candidate.topic_key,
                candidate.canonical_text,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            candidates.append(candidate)
            if len(candidates) >= 4:
                break
        return tuple(candidates)

    def _build_session_bridge_candidates(
        self,
        *,
        session_id: str,
        turn: MemoryTurnInput,
        stored_items: tuple[MemoryItem, ...],
    ) -> tuple[SessionMemoryCandidate, ...]:
        prioritized = sorted(
            stored_items,
            key=lambda item: (
                0 if item.memory_class == "task" else 1,
                0 if item.memory_class == "episodic" else 1,
                0 if item.representation == "preference" else 1,
                -item.confidence,
            ),
        )
        candidates: list[SessionMemoryCandidate] = []
        for item in prioritized:
            if item.memory_class not in {"task", "episodic", "profile"} and item.representation != "preference":
                continue
            candidates.append(
                SessionMemoryCandidate(
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    source_role="derived",
                    category=_session_category_for_item(item),
                    content=item.display_text(),
                    canonical_text=item.display_text(),
                    source_turn=turn.turn_id,
                    representation=(
                        "preference"
                        if item.representation == "preference"
                        else "abstract"
                    ),
                    consolidation_state="promoted",
                    origin_kind="long_term_bridge",
                    topic_key=item.topic_key,
                    carryover_kind=item.memory_class,
                    importance=max(0.6, min(1.0, item.confidence)),
                    confidence=item.confidence,
                    content_summary=item.summary,
                    summary_text=item.summary,
                    structured_payload_json=item.structured_payload_json,
                    metadata_json=_merge_session_metadata(
                        item.metadata_json,
                        {
                            "session_signal_kind": "long_term_bridge",
                            "source_memory_id": item.id,
                        },
                    ),
                    ttl_days=self.config.session_ttl_days,
                    last_confirmed_at=item.last_confirmed_at,
                    promotion_fingerprint=f"bridge:{item.id}",
                    produced_memory_refs=(item.id,),
                )
            )
            if len(candidates) >= 2:
                break
        return tuple(candidates)

    def _build_session_only_candidates(
        self,
        *,
        session_id: str,
        turn: MemoryTurnInput,
        now: datetime,
        stored_items: tuple[MemoryItem, ...],
    ) -> tuple[SessionMemoryCandidate, ...]:
        if self.writer is None:
            return ()
        stored_topics = {item.topic_key for item in stored_items if item.topic_key}
        extracted = self.writer.extract_turn_candidates(turn, now=now)
        candidates: list[SessionMemoryCandidate] = []

        for candidate in extracted:
            if candidate.memory_class != "task":
                continue
            if not (
                candidate.followup_enabled
                or "followup" in candidate.tags
                or "commitment" in candidate.tags
                or candidate.followup_due_at is not None
            ):
                continue
            if candidate.topic_key and candidate.topic_key in stored_topics:
                continue
            candidates.append(
                SessionMemoryCandidate(
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    source_role="user",
                    category="task_commitment",
                    content=candidate.canonical_text or candidate.content,
                    canonical_text=candidate.summary or candidate.canonical_text or candidate.content,
                    source_turn=turn.turn_id,
                    representation="abstract",
                    topic_key=candidate.topic_key,
                    carryover_kind="task",
                    importance=max(0.65, min(1.0, candidate.confidence)),
                    confidence=candidate.confidence,
                    content_summary=candidate.summary,
                    summary_text=candidate.summary,
                    structured_payload_json=candidate.structured_payload_json,
                    metadata_json=json.dumps(
                        {
                            "session_signal_kind": "task_carryover",
                            "candidate_reason": candidate.candidate_reason,
                        },
                        ensure_ascii=False,
                    ),
                    ttl_days=self.config.session_ttl_days,
                )
            )

        conclusion_text = _extract_session_conclusion(turn.user_input)
        if conclusion_text:
            candidates.append(
                SessionMemoryCandidate(
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    source_role="derived",
                    category="unresolved_topic",
                    content=conclusion_text,
                    canonical_text=conclusion_text,
                    source_turn=turn.turn_id,
                    representation="abstract",
                    topic_key=_build_session_topic_key(conclusion_text),
                    carryover_kind="session",
                    importance=0.55,
                    confidence=0.7,
                    content_summary=f"本次会话中间结论：{conclusion_text}",
                    summary_text=f"本次会话中间结论：{conclusion_text}",
                    metadata_json=json.dumps(
                        {"session_signal_kind": "session_conclusion"},
                        ensure_ascii=False,
                    ),
                    ttl_days=self.config.session_ttl_days,
                )
            )

        if not candidates:
            topic_summary = _extract_session_topic_summary(turn.user_input)
            if topic_summary:
                candidates.append(
                    SessionMemoryCandidate(
                        session_id=session_id,
                        turn_id=turn.turn_id,
                        source_role="derived",
                        category="recent_event",
                        content=topic_summary,
                        canonical_text=topic_summary,
                        source_turn=turn.turn_id,
                        representation="abstract",
                        topic_key=_build_session_topic_key(topic_summary),
                        carryover_kind="session",
                        importance=0.45,
                        confidence=0.55,
                        content_summary=f"本次会话主题摘要：{topic_summary}",
                        summary_text=f"本次会话主题摘要：{topic_summary}",
                        metadata_json=json.dumps(
                            {"session_signal_kind": "topic_summary"},
                            ensure_ascii=False,
                        ),
                        ttl_days=self.config.session_ttl_days,
                    )
                )
        return tuple(candidates[:2])

    def _consolidate_session_item(
        self,
        item: SessionMemoryItem,
        *,
        now: datetime,
        final_attempt: bool,
    ) -> SessionConsolidationResult:
        if self.store is None or self.writer is None or self.session_summarizer is None:
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="skipped",
                skipped_reason="memory_components_unavailable",
                final_attempt=final_attempt,
            )
        if item.origin_kind != "session_only":
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state=item.consolidation_state,
                summary_text=item.summary_text,
                skipped_reason="non_promotable_origin_kind",
                final_attempt=final_attempt,
            )

        sibling_items = self.store.list_session_items(
            session_id=item.session_id,
            status="active",
        )
        result = self.session_summarizer.summarize(
            item,
            now=now,
            sibling_items=sibling_items,
            strong_only=final_attempt,
        )
        now_iso = now.isoformat(timespec="seconds")

        if result.promoted:
            promotion_candidate = result.promotion_candidates[0]
            if (
                item.promotion_fingerprint == promotion_candidate.fingerprint
                and item.last_consolidated_at
                and item.last_consolidated_at >= item.updated_at
            ):
                updated_item = self.store.update_session_item(
                    item.id,
                    now_iso=now_iso,
                    summary_text=result.summary_text,
                    consolidation_state="promoted",
                    last_consolidated_at=now_iso,
                    promotion_fingerprint=promotion_candidate.fingerprint,
                )
                return SessionConsolidationResult(
                    session_item_id=item.id,
                    session_id=item.session_id,
                    target_state="promoted",
                    summary_text=result.summary_text,
                    skipped_reason="idempotent_promotion_skip",
                    final_attempt=final_attempt,
                    produced_memory_refs=updated_item.produced_memory_refs if updated_item else item.produced_memory_refs,
                )
            write_result = self.writer.persist_candidates(
                [promotion_candidate.memory_candidate],
                now=now,
            )
            stored_ids = write_result.stored_ids
            self.store.update_session_item(
                item.id,
                now_iso=now_iso,
                summary_text=result.summary_text,
                consolidation_state="promoted",
                last_consolidated_at=now_iso,
                promotion_fingerprint=promotion_candidate.fingerprint,
                produced_memory_refs=stored_ids,
            )
            return SessionConsolidationResult(
                session_item_id=item.id,
                session_id=item.session_id,
                target_state="promoted",
                summary_text=result.summary_text,
                promotion_candidates=result.promotion_candidates,
                final_attempt=final_attempt,
                produced_memory_refs=stored_ids,
            )

        self.store.update_session_item(
            item.id,
            now_iso=now_iso,
            summary_text=result.summary_text,
            consolidation_state=result.target_state,
            last_consolidated_at=now_iso,
        )
        return result


def _resolve_store_path(project_root: Path, store_path: str) -> Path:
    candidate = Path(store_path)
    return candidate if candidate.is_absolute() else project_root / candidate


def _merge_session_metadata(existing_json: str | None, extra: dict[str, object]) -> str:
    payload: dict[str, object] = {}
    if existing_json:
        try:
            loaded = json.loads(existing_json)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            payload.update(loaded)
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _extract_session_conclusion(user_input: str) -> str | None:
    text = normalize_whitespace(user_input)
    if not text:
        return None
    strong_markers = ("先", "再", "然后", "结论", "定下来", "就按", "收口", "先做")
    if not any(marker in text for marker in strong_markers):
        return None
    return safe_preview(text, 72).rstrip("。！？")


def _extract_session_topic_summary(user_input: str) -> str | None:
    text = normalize_whitespace(user_input)
    if not text or len(text) < 10:
        return None
    if not any(marker in text for marker in ("schema", "memory", "测试", "迁移", "重构", "任务", "项目")):
        return None
    return safe_preview(text, 64).rstrip("。！？")


def _build_session_topic_key(text: str) -> str | None:
    return build_topic_key(normalize_whitespace(text))


def _session_category_for_item(item: MemoryItem) -> str:
    if item.representation == "preference":
        return "user_preference"
    if item.memory_class == "task":
        return "task_commitment"
    if item.memory_class == "profile":
        return "user_background"
    return "recent_event"
