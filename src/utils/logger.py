from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any

from src.config.loader import RuntimeConfig
from src.observability.trace import TurnTrace

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
TRACE_LOGGER_NAME = "serina.trace"

_TRACE_FILE_PATH: str | None = None


class JsonEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "event_payload", None)
        if payload is None:
            return super().format(record)

        event = {
            "timestamp": datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            **payload,
        }
        return json.dumps(event, ensure_ascii=False)


def configure_logging(config_or_level: RuntimeConfig | str = "INFO") -> None:
    global _TRACE_FILE_PATH

    runtime_config = config_or_level if isinstance(config_or_level, RuntimeConfig) else None
    level = runtime_config.log_level if runtime_config else str(config_or_level)
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()

    _reset_handlers(root_logger)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    console_handler.setLevel(resolved_level)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(resolved_level)

    if runtime_config is not None:
        _configure_trace_logger(runtime_config)
    else:
        trace_logger = logging.getLogger(TRACE_LOGGER_NAME)
        _reset_handlers(trace_logger)
        trace_logger.propagate = False
        _TRACE_FILE_PATH = None


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    event_name: str,
    *,
    level: str = "INFO",
    turn_trace: TurnTrace | None = None,
    **fields: Any,
) -> None:
    trace_logger = logging.getLogger(TRACE_LOGGER_NAME)
    if not trace_logger.handlers:
        return

    payload: dict[str, Any] = {
        "event_name": event_name,
        "turn_id": None,
        "scene": None,
        "user_input_preview": None,
        "cleaned_input_preview": None,
        "history_message_count": None,
        "model_name": None,
        "request_latency_ms": None,
        "response_preview": None,
        "postprocessed_response_preview": None,
        "memory_selected_ids": None,
        "memory_written_ids": None,
        "reply_guard_action": None,
        "reply_guard_initial_action": None,
        "reply_guard_final_action": None,
        "reply_guard_initial_violations": None,
        "reply_guard_retry_attempted": None,
        "reply_guard_retry_used": None,
        "reply_guard_rewrite_used": None,
        "reply_guard_fallback_reason": None,
        "reply_guard_scene": None,
        "reply_guard_memory_refs_checked": None,
        "reply_guard_case_like_signature": None,
        "reply_guard_violations": None,
        "assist_llm_task": None,
        "assist_llm_enabled": None,
        "assist_llm_model": None,
        "assist_llm_timeout_ms": None,
        "assist_llm_runtime_call_used": None,
        "assist_llm_input_excerpt": None,
        "assist_llm_output_excerpt": None,
        "assist_llm_duration_ms": None,
        "assist_llm_success": None,
        "assist_llm_fallback_to_rules": None,
        "assist_llm_error_type": None,
        "assist_llm_trace_linked_turn_id": None,
        "assist_llm_pre_guard_action": None,
        "assist_llm_post_guard_action": None,
        "error_type": None,
        "error_message": None,
    }
    if turn_trace is not None:
        payload.update(turn_trace.as_log_fields())
    payload.update(fields)

    trace_logger.log(
        getattr(logging, level.upper(), logging.INFO),
        event_name,
        extra={"event_payload": payload},
    )


def get_trace_log_path() -> str | None:
    return _TRACE_FILE_PATH


def _configure_trace_logger(runtime_config: RuntimeConfig) -> None:
    global _TRACE_FILE_PATH

    trace_logger = logging.getLogger(TRACE_LOGGER_NAME)
    _reset_handlers(trace_logger)
    trace_logger.setLevel(logging.DEBUG)
    trace_logger.propagate = False

    formatter = JsonEventFormatter()

    if runtime_config.debug_trace_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        trace_logger.addHandler(console_handler)

    _TRACE_FILE_PATH = None
    if runtime_config.enable_file_logging:
        log_dir = Path(runtime_config.log_dir).resolve()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"serina_trace_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        trace_logger.addHandler(file_handler)
        _TRACE_FILE_PATH = str(log_path)


def _reset_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
