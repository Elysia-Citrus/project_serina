from __future__ import annotations

from typing import Mapping, Sequence
import json
import socket
from urllib import error as urllib_error
from urllib import request as urllib_request

from src.config.loader import RuntimeConfig


class DeepSeekProviderError(RuntimeError):
    """Raised when DeepSeek API calls fail."""


class DeepSeekProvider:
    def __init__(self, runtime_config: RuntimeConfig) -> None:
        self.runtime_config = runtime_config

    def generate(self, messages: Sequence[Mapping[str, str]]) -> str:
        api_key = self.runtime_config.api_key
        if not api_key:
            raise DeepSeekProviderError(
                "DeepSeek API key 缺失。请设置环境变量 "
                f"`{self.runtime_config.api_key_env}` 后再运行。"
            )

        endpoint = f"{self.runtime_config.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.runtime_config.model,
            "messages": [dict(message) for message in messages],
            "temperature": self.runtime_config.temperature,
            "max_tokens": self.runtime_config.max_tokens,
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

        try:
            with urllib_request.urlopen(
                request, timeout=self.runtime_config.timeout
            ) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise DeepSeekProviderError(
                f"DeepSeek API 返回 HTTP {exc.code}：{_extract_error_message(body)}"
            ) from exc
        except urllib_error.URLError as exc:
            raise DeepSeekProviderError(f"无法连接 DeepSeek API：{exc.reason}") from exc
        except socket.timeout as exc:
            raise DeepSeekProviderError(
                f"DeepSeek API 请求超时（{self.runtime_config.timeout}s）。"
            ) from exc

        return _extract_response_text(raw_body)


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

    if isinstance(payload.get("message"), str) and payload["message"].strip():
        return payload["message"].strip()

    return raw_body.strip() or "未知错误"
