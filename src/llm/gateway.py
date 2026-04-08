from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Mapping, Sequence

from src.config.loader import RuntimeConfig
from src.llm.providers.deepseek import DeepSeekProvider, DeepSeekProviderError
from src.observability.trace import TurnTrace
from src.utils.logger import get_logger, log_event
from src.utils.text_utils import redact_secrets, safe_preview


class GatewayError(RuntimeError):
    """Raised when an upstream LLM provider fails."""


@dataclass(frozen=True)
class GatewayResponse:
    text: str
    provider_name: str
    model_name: str
    latency_ms: int


@dataclass(frozen=True)
class GenerationOptions:
    temperature: float | None = None
    max_tokens: int | None = None
    request_tag: str = "default"


class LLMGateway:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self.runtime_config = runtime_config
        self.logger = get_logger(__name__)
        self.provider = self._build_provider()

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        turn_trace: TurnTrace | None = None,
        options: GenerationOptions | None = None,
    ) -> GatewayResponse:
        generation_options = options or GenerationOptions()
        log_event(
            "llm_gateway_call_started",
            level="DEBUG",
            turn_trace=turn_trace,
            provider_name=self.runtime_config.provider,
            model_name=self.runtime_config.model,
            message_count=len(messages),
            request_tag=generation_options.request_tag,
            temperature_override=generation_options.temperature,
            max_tokens_override=generation_options.max_tokens,
        )
        started_at = monotonic()

        try:
            response_text = self.provider.generate(
                messages,
                turn_trace=turn_trace,
                options=generation_options,
            )
        except DeepSeekProviderError as exc:
            latency_ms = int((monotonic() - started_at) * 1000)
            safe_error_message = redact_secrets(
                str(exc),
                [self.runtime_config.api_key or ""],
            )
            log_event(
                "llm_gateway_call_failed",
                level="ERROR",
                turn_trace=turn_trace,
                provider_name=self.runtime_config.provider,
                model_name=self.runtime_config.model,
                request_latency_ms=latency_ms,
                request_tag=generation_options.request_tag,
                error_type=type(exc).__name__,
                error_message=safe_error_message,
            )
            raise GatewayError(str(exc)) from exc
        except Exception as exc:
            latency_ms = int((monotonic() - started_at) * 1000)
            safe_error_message = redact_secrets(
                str(exc),
                [self.runtime_config.api_key or ""],
            )
            log_event(
                "llm_gateway_call_failed",
                level="ERROR",
                turn_trace=turn_trace,
                provider_name=self.runtime_config.provider,
                model_name=self.runtime_config.model,
                request_latency_ms=latency_ms,
                request_tag=generation_options.request_tag,
                error_type=type(exc).__name__,
                error_message=safe_error_message,
            )
            raise GatewayError(f"模型调用失败：{exc}") from exc

        latency_ms = int((monotonic() - started_at) * 1000)
        log_event(
            "llm_gateway_call_completed",
            level="DEBUG",
            turn_trace=turn_trace,
            provider_name=self.runtime_config.provider,
            model_name=self.runtime_config.model,
            request_latency_ms=latency_ms,
            request_tag=generation_options.request_tag,
            response_preview=safe_preview(
                response_text,
                turn_trace.debug_max_preview_chars if turn_trace else 120,
            ),
            success=True,
        )
        return GatewayResponse(
            text=response_text,
            provider_name=self.runtime_config.provider,
            model_name=self.runtime_config.model,
            latency_ms=latency_ms,
        )

    def _build_provider(self) -> DeepSeekProvider:
        provider_name = self.runtime_config.provider.lower()
        if provider_name == "deepseek":
            return DeepSeekProvider(self.runtime_config)
        raise GatewayError(f"暂不支持的 provider：{self.runtime_config.provider}")
