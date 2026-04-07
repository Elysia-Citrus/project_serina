from __future__ import annotations

from typing import Mapping, Sequence

from src.config.loader import RuntimeConfig
from src.llm.providers.deepseek import DeepSeekProvider, DeepSeekProviderError
from src.utils.logger import get_logger
from src.utils.text_utils import safe_preview


class GatewayError(RuntimeError):
    """Raised when an upstream LLM provider fails."""


class LLMGateway:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self.runtime_config = runtime_config
        self.logger = get_logger(__name__)
        self.provider = self._build_provider()

    def generate(self, messages: Sequence[Mapping[str, str]]) -> str:
        self.logger.debug(
            "Calling provider=%s with %d messages",
            self.runtime_config.provider,
            len(messages),
        )

        try:
            response = self.provider.generate(messages)
        except DeepSeekProviderError as exc:
            raise GatewayError(str(exc)) from exc
        except Exception as exc:
            raise GatewayError(f"模型调用失败：{exc}") from exc

        self.logger.debug("Provider reply preview=%s", safe_preview(response))
        return response

    def _build_provider(self) -> DeepSeekProvider:
        provider_name = self.runtime_config.provider.lower()
        if provider_name == "deepseek":
            return DeepSeekProvider(self.runtime_config)
        raise GatewayError(f"暂不支持的 provider：{self.runtime_config.provider}")
