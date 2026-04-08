from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from src.config.loader import AppConfig
from src.dialogue.engine import DialogueEngine
from src.llm.gateway import LLMGateway
from src.memory.manager import MemoryManager
from src.memory.models import MemoryTurnInput
from src.observability.trace import TurnTrace
from src.scheduler.manager import SchedulerManager
from src.utils.logger import get_logger, log_event
from src.utils.text_utils import normalize_whitespace


@dataclass
class SessionState:
    history: list[dict[str, str]] = field(default_factory=list)
    # TODO(v0.2): add session identifiers, long-term memory refs, and scheduler refs.


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
    memory_write_candidate_present: bool
    reply_guard_action: str
    reply_guard_initial_action: str
    reply_guard_initial_violations: tuple[str, ...]
    reply_guard_retry_attempted: bool
    reply_guard_violations: tuple[str, ...]
    proactive_followup_candidate_present: bool
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

        self.max_history_messages = config.runtime.max_history_turns * 2
        self.scheduler_service = SchedulerManager.from_app_config(
            config,
            self.memory_service,
        )

    def get_welcome_message(self) -> str:
        return self.config.persona.welcome_message

    def process_user_message(self, user_input: str) -> CoordinatorTurnResult:
        history_snapshot = self.get_history_snapshot()
        turn_trace = TurnTrace.create(self.config.runtime.debug_max_preview_chars)

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
                memory_write_candidate_present=False,
                reply_guard_action="accept",
                reply_guard_initial_action="accept",
                reply_guard_initial_violations=(),
                reply_guard_retry_attempted=False,
                reply_guard_violations=(),
                proactive_followup_candidate_present=False,
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
            result = self.engine.generate_reply(
                user_input=cleaned_input,
                conversation_history=history_snapshot,
                memory_snippets=None,
                turn_trace=turn_trace,
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
        self._trim_history()
        turn_trace.history_message_count = len(self.session.history)
        memory_write_result = self.memory_service.write_turn(
            MemoryTurnInput(
                user_input=cleaned_input,
                assistant_reply=result.reply_text,
                scene=result.scene,
                turn_id=turn_trace.turn_id,
            ),
            turn_trace=turn_trace,
        )
        followup_scan = self.scheduler_service.collect_followup_candidates(
            turn_trace=turn_trace,
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
            memory_selected_ids=result.memory_result.selected_ids,
            memory_write_candidate_present=memory_write_result.wrote_any,
            reply_guard_action=result.reply_guard_action,
            reply_guard_initial_action=result.reply_guard_initial_action,
            reply_guard_initial_violations=result.reply_guard_initial_violations,
            reply_guard_retry_attempted=result.reply_guard_retry_attempted,
            reply_guard_violations=result.reply_guard_violations,
            proactive_followup_candidate_present=bool(followup_scan.accepted),
            total_turn_latency_ms=turn_trace.elapsed_ms(),
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
            memory_write_candidate_present=memory_write_result.wrote_any,
            reply_guard_action=result.reply_guard_action,
            reply_guard_initial_action=result.reply_guard_initial_action,
            reply_guard_initial_violations=result.reply_guard_initial_violations,
            reply_guard_retry_attempted=result.reply_guard_retry_attempted,
            reply_guard_violations=result.reply_guard_violations,
            proactive_followup_candidate_present=bool(followup_scan.accepted),
            diagnostic_text=diagnostic_text,
        )

    def get_history_snapshot(self) -> list[Mapping[str, str]]:
        return list(self.session.history)

    def _append_message(self, role: str, content: str) -> None:
        self.session.history.append({"role": role, "content": content})

    def _trim_history(self) -> None:
        if len(self.session.history) <= self.max_history_messages:
            return
        self.session.history = self.session.history[-self.max_history_messages :]

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
