from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping
from uuid import uuid4
import json

from src.config.loader import AppConfig
from src.dialogue.engine import DialogueEngine
from src.llm.gateway import LLMGateway
from src.memory.manager import MemoryManager
from src.memory.models import MemoryItem, MemoryTurnInput, SessionMemoryItem, WorkingMemoryState
from src.observability.trace import TurnTrace
from src.scheduler.manager import SchedulerManager
from src.utils.logger import get_logger, log_event
from src.utils.text_utils import normalize_whitespace
from src.utils.time_utils import build_time_context, get_local_now


@dataclass
class SessionState:
    session_id: str = field(default_factory=lambda: uuid4().hex)
    history: list[dict[str, str]] = field(default_factory=list)
    started_at: datetime = field(default_factory=get_local_now)
    last_user_turn_at: datetime | None = None
    turn_count: int = 0
    working: WorkingMemoryState = field(init=False)

    def __post_init__(self) -> None:
        self.working = WorkingMemoryState(session_id=self.session_id)


@dataclass(frozen=True)
class CoordinatorTurnResult:
    reply_text: str
    raw_response: str
    turn_id: str
    scene: str
    latency_ms: int
    provider_name: str | None
    model_name: str | None
    postprocess_applied_rules: tuple[str, ...]
    used_fallback: bool
    prompt_block_count: int
    prompt_message_count: int
    memory_selected_ids: tuple[str, ...]
    memory_used_count: int
    startup_memory_pack_present: bool
    startup_memory_pack_count: int
    startup_memory_memory_ids: tuple[str, ...]
    startup_memory_categories: tuple[str, ...]
    continuation_cue_detected: bool
    last_session_summary_used: bool
    retrieval_mode: str
    memory_write_candidate_present: bool
    memory_write_result: tuple[str, ...]
    reply_guard_action: str
    reply_guard_initial_action: str
    reply_guard_final_action: str
    reply_guard_initial_violations: tuple[str, ...]
    reply_guard_retry_attempted: bool
    reply_guard_retry_used: bool
    reply_guard_rewrite_used: bool
    reply_guard_fallback_reason: str | None
    reply_guard_scene: str
    reply_guard_memory_refs_checked: tuple[str, ...]
    reply_guard_case_like_signature: str | None
    reply_guard_violations: tuple[str, ...]
    proactive_followup_candidate_present: bool
    time_context_summary: str | None
    diagnostic_text: str | None = None


class Coordinator:
    def __init__(self, config: AppConfig, engine: DialogueEngine | None = None) -> None:
        self.config = config
        self.logger = get_logger(__name__)
        self.session = SessionState()

        if engine is None:
            gateway = LLMGateway(config.runtime)
            self.memory_service = MemoryManager.from_app_config(config)
            self.engine = DialogueEngine(
                config,
                gateway,
                memory_manager=self.memory_service,
            )
        else:
            self.engine = engine
            self.memory_service = getattr(
                self.engine,
                "memory_manager",
                MemoryManager.from_app_config(config),
            )

        self.memory_service.register_session(
            session_id=self.session.session_id,
            started_at=self.session.started_at,
        )
        self.max_history_messages = config.runtime.max_history_turns * 2
        self.scheduler_service = SchedulerManager.from_app_config(
            config,
            self.memory_service,
        )

    def get_welcome_message(self) -> str:
        return self.config.persona.welcome_message

    def process_user_message(
        self,
        user_input: str,
        *,
        source_channel: str = "text",
        raw_asr_text: str | None = None,
        asr_provider: str | None = None,
        tts_provider: str | None = None,
    ) -> CoordinatorTurnResult:
        history_snapshot = self.get_history_snapshot()
        turn_trace = TurnTrace.create(self.config.runtime.debug_max_preview_chars)
        turn_started_at = get_local_now()

        cleaned_input = normalize_whitespace(user_input)
        turn_trace.set_user_input(
            raw_input=user_input,
            cleaned_input=cleaned_input,
            history_message_count=len(history_snapshot),
        )
        log_event(
            "turn_received",
            level="INFO",
            turn_trace=turn_trace,
            raw_input_length=len(user_input),
        )

        if not cleaned_input:
            fallback_reply = f"{self.config.persona.user_name}，先和我说一句吧。"
            turn_trace.set_postprocessed_response_preview(fallback_reply)
            log_event(
                "turn_rejected_empty_input",
                level="DEBUG",
                turn_trace=turn_trace,
            )
            latency_ms = turn_trace.elapsed_ms()
            return CoordinatorTurnResult(
                reply_text=fallback_reply,
                raw_response="",
                turn_id=turn_trace.turn_id,
                scene="empty_input",
                latency_ms=latency_ms,
                provider_name=None,
                model_name=None,
                postprocess_applied_rules=("empty_input",),
                used_fallback=True,
                prompt_block_count=0,
                prompt_message_count=0,
                memory_selected_ids=(),
                memory_used_count=0,
                startup_memory_pack_present=False,
                startup_memory_pack_count=0,
                startup_memory_memory_ids=(),
                startup_memory_categories=(),
                continuation_cue_detected=False,
                last_session_summary_used=False,
                retrieval_mode="query",
                memory_write_candidate_present=False,
                memory_write_result=(),
                reply_guard_action="accept",
                reply_guard_initial_action="accept",
                reply_guard_final_action="accept",
                reply_guard_initial_violations=(),
                reply_guard_retry_attempted=False,
                reply_guard_retry_used=False,
                reply_guard_rewrite_used=False,
                reply_guard_fallback_reason=None,
                reply_guard_scene="empty_input",
                reply_guard_memory_refs_checked=(),
                reply_guard_case_like_signature="empty_input|clean",
                reply_guard_violations=(),
                proactive_followup_candidate_present=False,
                time_context_summary=None,
                diagnostic_text=self._build_diagnostic_text(
                    turn_trace=turn_trace,
                    scene="empty_input",
                    latency_ms=latency_ms,
                    history_count=len(history_snapshot),
                ),
            )

        if cleaned_input != user_input.strip():
            log_event(
                "input_cleaned",
                level="DEBUG",
                turn_trace=turn_trace,
            )

        try:
            session_turn_index = self.session.turn_count + 1
            time_context = build_time_context(
                session_started_at=self.session.started_at,
                last_user_turn_at=self.session.last_user_turn_at,
            )
            result = self.engine.generate_reply(
                user_input=cleaned_input,
                conversation_history=history_snapshot,
                session_id=self.session.session_id,
                session_turn_index=session_turn_index,
                memory_snippets=None,
                turn_trace=turn_trace,
                time_context=time_context,
            )
        except Exception as exc:
            log_event(
                "turn_failed",
                level="ERROR",
                turn_trace=turn_trace,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise

        self._append_message("user", cleaned_input)
        self._append_message("assistant", result.reply_text)
        self.session.last_user_turn_at = get_local_now()
        self.session.turn_count += 1
        self._trim_history()
        turn_trace.history_message_count = len(self.session.history)
        memory_turn = MemoryTurnInput(
            user_input=cleaned_input,
            assistant_reply=result.reply_text,
            scene=result.scene,
            turn_id=turn_trace.turn_id,
            session_id=self.session.session_id,
            turn_index=session_turn_index,
            source_channel=source_channel,
            raw_asr_text=raw_asr_text,
            llm_provider=result.provider_name,
            llm_model=result.model_name,
            asr_provider=asr_provider,
            tts_provider=tts_provider or self.config.voice.tts_provider,
            latency_json=json.dumps(
                {
                    "llm_ms": result.request_latency_ms,
                    "total_ms": turn_trace.elapsed_ms(),
                },
                ensure_ascii=False,
            ),
            metadata_json=json.dumps(
                {
                    "history_message_count": len(history_snapshot),
                    "retrieval_mode": result.memory_result.retrieval_mode,
                },
                ensure_ascii=False,
            ),
        )
        memory_write_result = self.memory_service.write_turn(
            memory_turn,
            turn_trace=turn_trace,
        )
        session_items = self.memory_service.record_session_turn(
            session_id=self.session.session_id,
            turn=memory_turn,
            stored_items=memory_write_result.stored_items,
        )
        self.memory_service.record_session_continuity(
            session_id=self.session.session_id,
            session_started_at=self.session.started_at,
            turn=memory_turn,
            session_items=session_items,
            stored_items=memory_write_result.stored_items,
            turn_trace=turn_trace,
        )
        self.memory_service.record_conversation_turn(
            memory_turn,
            session_id=self.session.session_id,
            turn_index=session_turn_index,
            started_at=turn_started_at,
            completed_at=get_local_now(),
            turn_trace=turn_trace,
        )
        self._update_working_state(
            memory_write_result.stored_items,
            session_items=session_items,
        )
        followup_scan = self.scheduler_service.collect_followup_candidates(
            turn_trace=turn_trace,
        )
        try:
            self.scheduler_service.run_session_maintenance(
                session_id=self.session.session_id,
                limit=1,
            )
        except Exception as exc:
            log_event(
                "session_maintenance_failed",
                level="DEBUG",
                turn_trace=turn_trace,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

        log_event(
            "coordinator_history_updated",
            level="DEBUG",
            turn_trace=turn_trace,
            history_message_count=len(self.session.history),
        )
        log_event(
            "turn_completed",
            level="INFO",
            turn_trace=turn_trace,
            scene=result.scene,
            request_latency_ms=result.request_latency_ms,
            is_new_session=session_turn_index == 1,
            retrieval_mode=result.memory_result.retrieval_mode,
            memory_selected_ids=result.memory_result.selected_ids,
            memory_read_count=len(result.memory_result.selected_ids),
            startup_memory_pack_present=bool(result.memory_result.startup_prompt_items),
            startup_memory_pack_count=len(result.memory_result.startup_prompt_items),
            startup_memory_memory_ids=result.memory_result.startup_selected_ids,
            startup_memory_categories=result.memory_result.startup_categories,
            continuation_cue_detected=result.memory_result.continuation_cue_detected,
            last_session_summary_used=result.memory_result.last_session_summary_used,
            memory_write_candidate_present=memory_write_result.wrote_any,
            memory_write_result=tuple(
                f"{decision.action}:{decision.reason}"
                for decision in memory_write_result.decisions
            ),
            time_context_present=result.time_context_summary is not None,
            time_context_summary=result.time_context_summary,
            prompt_blocks_summary=tuple(
                block.name for block in result.prompt_metadata.prompt_blocks
            ),
            reply_guard_action=result.reply_guard_action,
            reply_guard_initial_action=result.reply_guard_initial_action,
            reply_guard_final_action=result.reply_guard_final_action,
            reply_guard_initial_violations=result.reply_guard_initial_violations,
            reply_guard_retry_attempted=result.reply_guard_retry_attempted,
            reply_guard_retry_used=result.reply_guard_retry_used,
            reply_guard_rewrite_used=result.reply_guard_rewrite_used,
            reply_guard_fallback_reason=result.reply_guard_fallback_reason,
            reply_guard_scene=result.reply_guard_scene,
            reply_guard_memory_refs_checked=result.reply_guard_memory_refs_checked,
            reply_guard_case_like_signature=result.reply_guard_case_like_signature,
            reply_guard_violations=result.reply_guard_violations,
            reply_guard_memory_reference_verdict=result.reply_guard_memory_reference_verdict,
            proactive_followup_candidate_present=bool(followup_scan.accepted),
            total_turn_latency_ms=turn_trace.elapsed_ms(),
            **(
                result.assist_llm_record.as_log_fields()
                if result.assist_llm_record is not None
                else {}
            ),
        )

        diagnostic_text = self._build_diagnostic_text(
            turn_trace=turn_trace,
            scene=result.scene,
            latency_ms=result.request_latency_ms,
            history_count=len(history_snapshot),
        )
        return CoordinatorTurnResult(
            reply_text=result.reply_text,
            raw_response=result.raw_response,
            turn_id=turn_trace.turn_id,
            scene=result.scene,
            latency_ms=result.request_latency_ms,
            provider_name=result.provider_name,
            model_name=result.model_name,
            postprocess_applied_rules=tuple(result.postprocess.applied_rules),
            used_fallback=result.postprocess.used_fallback,
            prompt_block_count=len(result.prompt_metadata.prompt_blocks),
            prompt_message_count=len(result.prompt_metadata.message_summaries),
            memory_selected_ids=result.memory_result.selected_ids,
            memory_used_count=len(result.memory_result.selected_ids),
            startup_memory_pack_present=bool(result.memory_result.startup_prompt_items),
            startup_memory_pack_count=len(result.memory_result.startup_prompt_items),
            startup_memory_memory_ids=result.memory_result.startup_selected_ids,
            startup_memory_categories=result.memory_result.startup_categories,
            continuation_cue_detected=result.memory_result.continuation_cue_detected,
            last_session_summary_used=result.memory_result.last_session_summary_used,
            retrieval_mode=result.memory_result.retrieval_mode,
            memory_write_candidate_present=memory_write_result.wrote_any,
            memory_write_result=tuple(
                f"{decision.action}:{decision.reason}"
                for decision in memory_write_result.decisions
            ),
            reply_guard_action=result.reply_guard_action,
            reply_guard_initial_action=result.reply_guard_initial_action,
            reply_guard_final_action=result.reply_guard_final_action,
            reply_guard_initial_violations=result.reply_guard_initial_violations,
            reply_guard_retry_attempted=result.reply_guard_retry_attempted,
            reply_guard_retry_used=result.reply_guard_retry_used,
            reply_guard_rewrite_used=result.reply_guard_rewrite_used,
            reply_guard_fallback_reason=result.reply_guard_fallback_reason,
            reply_guard_scene=result.reply_guard_scene,
            reply_guard_memory_refs_checked=result.reply_guard_memory_refs_checked,
            reply_guard_case_like_signature=result.reply_guard_case_like_signature,
            reply_guard_violations=result.reply_guard_violations,
            proactive_followup_candidate_present=bool(followup_scan.accepted),
            time_context_summary=result.time_context_summary,
            diagnostic_text=diagnostic_text,
        )

    def finalize_session(self) -> None:
        if self.session.turn_count <= 0:
            return
        try:
            self.memory_service.finalize_session(
                session_id=self.session.session_id,
            )
        except Exception as exc:
            log_event(
                "session_finalize_failed",
                level="DEBUG",
                session_id=self.session.session_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise

    def get_history_snapshot(self) -> list[Mapping[str, str]]:
        return list(self.session.history)

    def _append_message(self, role: str, content: str) -> None:
        self.session.history.append({"role": role, "content": content})

    def _trim_history(self) -> None:
        if len(self.session.history) <= self.max_history_messages:
            return
        self.session.history = self.session.history[-self.max_history_messages :]

    def _update_working_state(
        self,
        stored_items: tuple[MemoryItem, ...],
        *,
        session_items: tuple[SessionMemoryItem, ...] = (),
    ) -> None:
        if not stored_items and not session_items:
            return
        topics = tuple(
            dict.fromkeys(
                topic
                for topic in self.session.working.active_topic_keys
                + tuple(
                    item.topic_key
                    for item in stored_items
                    if item.topic_key
                )
                + tuple(
                    item.topic_key
                    for item in session_items
                    if item.topic_key
                )
                if topic
            )
        )[:4]
        unresolved = tuple(
            dict.fromkeys(
                self.session.working.unresolved_items
                + tuple(
                    item.display_text()
                    for item in stored_items
                    if item.memory_class == "task"
                )
                + tuple(
                    item.display_text()
                    for item in session_items
                    if item.carryover_kind == "task"
                )
            )
        )[:4]
        memory_refs = tuple(
            dict.fromkeys(
                self.session.working.recent_memory_refs
                + tuple(item.id for item in stored_items)
                + tuple(f"session:{item.id}" for item in session_items)
            )
        )[:6]
        current_task_hint = next(
            (item.display_text() for item in stored_items if item.memory_class == "task"),
            next(
                (item.display_text() for item in session_items if item.carryover_kind == "task"),
                self.session.working.current_task_hint,
            ),
        )
        self.session.working = WorkingMemoryState(
            session_id=self.session.session_id,
            active_topic_keys=topics,
            unresolved_items=unresolved,
            recent_memory_refs=memory_refs,
            current_task_hint=current_task_hint,
        )

    def _build_diagnostic_text(
        self,
        *,
        turn_trace: TurnTrace,
        scene: str,
        latency_ms: int,
        history_count: int,
    ) -> str | None:
        if not self.config.runtime.debug_cli_diagnostics_enabled:
            return None

        parts = [f"[turn={turn_trace.turn_id}]"]
        if self.config.runtime.debug_show_scene:
            parts.append(f"[scene={scene}]")
        parts.append(f"[history={history_count}]")
        parts.append(f"[latency={latency_ms}ms]")
        return " ".join(parts)
