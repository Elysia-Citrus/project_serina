from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import json

from src.assist_llm import AssistLLMService
from src.config.loader import RuntimeConfig
from src.utils.logger import get_logger, get_trace_log_path


INTERESTING_TRACE_EVENTS = {
    "reply_guard_checked",
    "reply_guard_retry_completed",
    "reply_guard_assist_retry_completed",
    "dialogue_completed",
    "assist_llm_call_completed",
    "assist_llm_call_failed",
}


@dataclass(frozen=True)
class TraceAdminResult:
    success: bool
    message: str


class TraceAdminService:
    def __init__(
        self,
        *,
        assist_service: AssistLLMService,
        runtime: RuntimeConfig,
        project_root: Path,
    ) -> None:
        self.assist_service = assist_service
        self.runtime = runtime
        self.project_root = project_root
        self.logger = get_logger(__name__)

    def summarize_trace_cluster(
        self,
        *,
        trace_file: str | None = None,
        limit: int = 12,
        event_name: str | None = None,
    ) -> TraceAdminResult:
        resolved = self._resolve_trace_file(trace_file)
        if resolved is None:
            return TraceAdminResult(
                False,
                "No trace log found. Enable file logging or pass --file <trace.jsonl>.",
            )

        events = self._load_events(resolved)
        if event_name:
            events = [
                event for event in events if str(event.get("event_name", "")) == event_name
            ]
        trace_records = self._build_trace_records(events, limit=limit)
        if not trace_records:
            return TraceAdminResult(False, f"No matching trace records in {resolved}.")

        result = self.assist_service.summarize_trace_cluster(
            trace_records=trace_records,
            command_id=f"trace-summary:{resolved.name}:{limit}",
        )
        if result.success:
            parts = [
                f"trace file: {resolved}",
                f"summary: {result.structured.get('summary', '')}",
            ]
            common_patterns = result.structured.get("common_patterns") or []
            if common_patterns:
                parts.append(
                    "patterns: " + ", ".join(str(item) for item in common_patterns)
                )
            recommended_focus = str(
                result.structured.get("recommended_focus", "")
            ).strip()
            if recommended_focus:
                parts.append(f"focus: {recommended_focus}")
            self.logger.info(
                "trace_summary success source=%s records=%s",
                resolved,
                len(trace_records),
            )
            return TraceAdminResult(True, "\n".join(parts))

        fallback = self._fallback_trace_summary(trace_records)
        self.logger.warning(
            "trace_summary fell back to rules source=%s error=%s",
            resolved,
            result.record.error_type,
        )
        return TraceAdminResult(
            True,
            "\n".join(
                [
                    f"trace file: {resolved}",
                    f"summary: {fallback}",
                    f"assist fallback: {result.record.error_type}",
                ]
            ),
        )

    def draft_badcase(
        self,
        *,
        target: str = "latest",
        trace_file: str | None = None,
    ) -> TraceAdminResult:
        resolved = self._resolve_trace_file(trace_file)
        if resolved is None:
            return TraceAdminResult(
                False,
                "No trace log found. Enable file logging or pass --file <trace.jsonl>.",
            )

        events = self._load_events(resolved)
        turn_events = self._select_turn_events(events, target)
        if not turn_events:
            return TraceAdminResult(False, f"Turn not found in trace: {target}")

        trace_record = self._build_badcase_payload(turn_events, resolved)
        command_id = f"badcase-draft:{trace_record['turn_id']}"
        result = self.assist_service.draft_badcase_case(
            trace_record=trace_record,
            command_id=command_id,
        )
        payload = result.structured if result.success else self._fallback_badcase(trace_record)
        message = "\n".join(
            [
                f"trace file: {resolved}",
                f"turn_id: {trace_record['turn_id']}",
                json.dumps(payload, ensure_ascii=False, indent=2),
            ]
        )
        self.logger.info(
            "badcase_draft %s source=%s turn_id=%s",
            "success" if result.success else "fallback",
            resolved,
            trace_record["turn_id"],
        )
        return TraceAdminResult(True, message)

    def help_text(self) -> str:
        return "\n".join(
            [
                "/trace summary [--file <trace.jsonl>] [--limit 12] [--event <name>]",
                "/badcase draft [latest|<turn_id>] [--file <trace.jsonl>]",
            ]
        )

    def _resolve_trace_file(self, trace_file: str | None) -> Path | None:
        if trace_file:
            candidate = Path(trace_file)
            if not candidate.is_absolute():
                candidate = (self.project_root / candidate).resolve()
            return candidate if candidate.exists() else None

        current = get_trace_log_path()
        if current:
            candidate = Path(current)
            if candidate.exists():
                return candidate

        log_dir = Path(self.runtime.log_dir)
        if not log_dir.is_absolute():
            log_dir = (self.project_root / log_dir).resolve()
        if not log_dir.exists():
            return None
        candidates = sorted(
            log_dir.glob("serina_trace_*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _load_events(self, path: Path) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events

    def _build_trace_records(
        self,
        events: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[str]:
        selected = [
            event
            for event in events
            if str(event.get("event_name", "")) in INTERESTING_TRACE_EVENTS
            or event.get("reply_guard_initial_action") is not None
            or event.get("assist_llm_task") is not None
        ]
        if not selected:
            selected = events
        sliced = selected[-max(1, limit) :]
        return [self._format_trace_record(event) for event in sliced]

    def _format_trace_record(self, event: dict[str, Any]) -> str:
        parts = [
            f"turn={event.get('turn_id') or '-'}",
            f"event={event.get('event_name') or '-'}",
        ]
        if event.get("scene"):
            parts.append(f"scene={event['scene']}")
        if event.get("reply_guard_initial_action"):
            parts.append(f"initial={event['reply_guard_initial_action']}")
        if event.get("reply_guard_final_action"):
            parts.append(f"final={event['reply_guard_final_action']}")
        if event.get("reply_guard_violations"):
            parts.append(f"violations={event['reply_guard_violations']}")
        if event.get("assist_llm_task"):
            parts.append(f"assist={event['assist_llm_task']}")
        if event.get("assist_llm_error_type"):
            parts.append(f"assist_error={event['assist_llm_error_type']}")
        return " | ".join(parts)

    def _select_turn_events(
        self,
        events: list[dict[str, Any]],
        target: str,
    ) -> list[dict[str, Any]]:
        turn_groups: dict[str, list[dict[str, Any]]] = {}
        ordered_turn_ids: list[str] = []
        for event in events:
            turn_id = str(event.get("turn_id") or "").strip()
            if not turn_id:
                continue
            if turn_id not in turn_groups:
                turn_groups[turn_id] = []
                ordered_turn_ids.append(turn_id)
            turn_groups[turn_id].append(event)

        if not ordered_turn_ids:
            return []

        if target != "latest":
            return turn_groups.get(target, [])

        for turn_id in reversed(ordered_turn_ids):
            events_for_turn = turn_groups[turn_id]
            if any(
                event.get("reply_guard_initial_violations")
                or event.get("reply_guard_violations")
                or event.get("reply_guard_action") not in {None, "accept"}
                for event in events_for_turn
            ):
                return events_for_turn
        return turn_groups[ordered_turn_ids[-1]]

    def _build_badcase_payload(
        self,
        turn_events: list[dict[str, Any]],
        trace_path: Path,
    ) -> dict[str, Any]:
        merged = self._merge_turn_fields(turn_events)
        turn_id = str(merged.get("turn_id") or "unknown")
        scene = str(merged.get("scene") or merged.get("reply_guard_scene") or "casual_chat")
        reply_text = (
            str(merged.get("response_preview") or "").strip()
            or str(merged.get("postprocessed_response_preview") or "").strip()
        )
        observed_violations = list(
            dict.fromkeys(
                _as_str_list(merged.get("reply_guard_initial_violations"))
                + _as_str_list(merged.get("reply_guard_violations"))
            )
        )
        return {
            "turn_id": turn_id,
            "case_id": f"draft_{turn_id}",
            "scene": scene,
            "user_input": str(
                merged.get("cleaned_input_preview")
                or merged.get("user_input_preview")
                or ""
            ),
            "injected_memories": _as_str_list(merged.get("memory_selected_ids")),
            "assistant_reply": reply_text,
            "observed_violations": observed_violations,
            "suggested_expected_categories": observed_violations,
            "suggested_expected_action": str(
                merged.get("reply_guard_final_action")
                or merged.get("reply_guard_action")
                or "accept"
            ),
            "reviewer_notes": (
                f"Drafted from trace {trace_path.name}. "
                "Please verify expected action and snippets before adding to regression."
            ),
        }

    def _fallback_badcase(self, trace_record: dict[str, Any]) -> dict[str, Any]:
        return {
            "case_id": trace_record["case_id"],
            "scene": trace_record["scene"],
            "user_input": trace_record["user_input"],
            "injected_memories": trace_record["injected_memories"],
            "assistant_reply": trace_record["assistant_reply"],
            "observed_violations": trace_record["observed_violations"],
            "suggested_expected_categories": trace_record["suggested_expected_categories"],
            "suggested_expected_action": trace_record["suggested_expected_action"],
            "reviewer_notes": trace_record["reviewer_notes"],
        }

    def _fallback_trace_summary(self, trace_records: Iterable[str]) -> str:
        records = list(trace_records)
        if not records:
            return "No trace records available."
        tokens = Counter()
        for record in records:
            for chunk in record.split("|"):
                if "=" not in chunk:
                    continue
                key, value = chunk.split("=", 1)
                if key.strip() in {"violations", "assist_error", "event", "scene"}:
                    tokens.update([value.strip()])
        if not tokens:
            return f"Loaded {len(records)} trace records. No dominant violation pattern found."
        top = ", ".join(f"{label} x{count}" for label, count in tokens.most_common(3))
        return f"Loaded {len(records)} trace records. Most frequent signatures: {top}."

    def _merge_turn_fields(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for event in events:
            for key, value in event.items():
                if value in (None, "", [], ()):
                    continue
                merged[key] = value
        return merged


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    return []
