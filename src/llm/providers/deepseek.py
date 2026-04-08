from __future__ import annotations

from time import monotonic
from typing import Mapping, Sequence
import json
import socket
from urllib import error as urllib_error
from urllib import request as urllib_request

from src.config.loader import RuntimeConfig
from src.observability.trace import TurnTrace
from src.utils.logger import log_event
from src.utils.text_utils import (
    redact_secrets,
    safe_preview,
    sanitize_url_for_logging,
)


class DeepSeekProviderError(RuntimeError):
    """Raised when DeepSeek API calls fail."""


class DeepSeekProvider:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self.runtime_config = runtime_config

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        turn_trace: TurnTrace | None = None,
        options: object | None = None,
    ) -> str:
        api_key = self.runtime_config.api_key
        if not api_key:
            error_message = (
                "DeepSeek API key 缺失。请设置环境变量 "
                f"`{self.runtime_config.api_key_env}` 后再运行。"
            )
            log_event(
                "provider_config_error",
                level="ERROR",
                turn_trace=turn_trace,
                provider_name="deepseek",
                model_name=self.runtime_config.model,
                error_type="MissingAPIKey",
                error_message=error_message,
            )
            raise DeepSeekProviderError(error_message)

        endpoint = f"{self.runtime_config.base_url.rstrip('/')}/chat/completions"
        safe_endpoint = sanitize_url_for_logging(endpoint)
        temperature = getattr(options, "temperature", None) or self.runtime_config.temperature
        max_tokens = getattr(options, "max_tokens", None) or self.runtime_config.max_tokens
        request_tag = getattr(options, "request_tag", "default")
        payload = {
            "model": self.runtime_config.model,
            "messages": [dict(message) for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        request = urllib_request.Request(
            url=endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        started_at = monotonic()
        log_event(
            "provider_request_started",
            level="DEBUG",
            turn_trace=turn_trace,
            provider_name="deepseek",
            model_name=self.runtime_config.model,
            provider_endpoint=safe_endpoint,
            message_count=len(messages),
            request_tag=request_tag,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            with urllib_request.urlopen(
                request,
                timeout=self.runtime_config.timeout,
            ) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            latency_ms = int((monotonic() - started_at) * 1000)
            safe_error_message = redact_secrets(_extract_error_message(body), [api_key])
            log_event(
                "provider_request_failed",
                level="ERROR",
                turn_trace=turn_trace,
                provider_name="deepseek",
                model_name=self.runtime_config.model,
                provider_endpoint=safe_endpoint,
                request_latency_ms=latency_ms,
                request_tag=request_tag,
                error_type=type(exc).__name__,
                error_message=safe_error_message,
            )
            raise DeepSeekProviderError(
                f"DeepSeek API 返回 HTTP {exc.code}：{safe_error_message}"
            ) from exc
        except urllib_error.URLError as exc:
            latency_ms = int((monotonic() - started_at) * 1000)
            safe_error_message = redact_secrets(str(exc.reason), [api_key])
            log_event(
                "provider_request_failed",
                level="ERROR",
                turn_trace=turn_trace,
                provider_name="deepseek",
                model_name=self.runtime_config.model,
                provider_endpoint=safe_endpoint,
                request_latency_ms=latency_ms,
                request_tag=request_tag,
                error_type=type(exc).__name__,
                error_message=safe_error_message,
            )
            raise DeepSeekProviderError(f"无法连接 DeepSeek API：{exc.reason}") from exc
        except socket.timeout as exc:
            latency_ms = int((monotonic() - started_at) * 1000)
            timeout_message = f"DeepSeek API 请求超时（{self.runtime_config.timeout}s）。"
            log_event(
                "provider_request_failed",
                level="ERROR",
                turn_trace=turn_trace,
                provider_name="deepseek",
                model_name=self.runtime_config.model,
                provider_endpoint=safe_endpoint,
                request_latency_ms=latency_ms,
                request_tag=request_tag,
                error_type=type(exc).__name__,
                error_message=timeout_message,
            )
            raise DeepSeekProviderError(timeout_message) from exc

        try:
            parsed_text = _extract_response_text(raw_body)
        except DeepSeekProviderError as exc:
            latency_ms = int((monotonic() - started_at) * 1000)
            safe_error_message = redact_secrets(str(exc), [api_key])
            log_event(
                "provider_response_invalid",
                level="ERROR",
                turn_trace=turn_trace,
                provider_name="deepseek",
                model_name=self.runtime_config.model,
                provider_endpoint=safe_endpoint,
                request_latency_ms=latency_ms,
                request_tag=request_tag,
                error_type=type(exc).__name__,
                error_message=safe_error_message,
            )
            raise

        latency_ms = int((monotonic() - started_at) * 1000)
        log_event(
            "provider_response_received",
            level="DEBUG",
            turn_trace=turn_trace,
            provider_name="deepseek",
            model_name=self.runtime_config.model,
            provider_endpoint=safe_endpoint,
            request_latency_ms=latency_ms,
            request_tag=request_tag,
            response_preview=safe_preview(
                parsed_text,
                turn_trace.debug_max_preview_chars if turn_trace else 120,
            ),
            raw_response_chars=len(raw_body),
            success=True,
        )
        return parsed_text


def _extract_response_text(raw_body: str) -> str:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise DeepSeekProviderError("DeepSeek API 返回了无法解析的 JSON。") from exc

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise DeepSeekProviderError("DeepSeek API 返回中缺少 choices。")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise DeepSeekProviderError("DeepSeek API 返回的 choice 结构不正确。")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise DeepSeekProviderError("DeepSeek API 返回中缺少 message。")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekProviderError("DeepSeek API 返回了空回复。")

    return content.strip()


def _extract_error_message(raw_body: str) -> str:
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body.strip() or "未知错误"

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    return raw_body.strip() or "未知错误"
