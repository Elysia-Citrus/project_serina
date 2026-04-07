from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from src.config.loader import AppConfig
from src.dialogue.engine import DialogueEngine
from src.llm.gateway import LLMGateway
from src.utils.logger import get_logger
from src.utils.text_utils import normalize_whitespace, safe_preview


@dataclass
class SessionState:
    history: list[dict[str, str]] = field(default_factory=list)
    # TODO(v0.2): add session identifiers, long-term memory refs, and scheduler refs.


class Coordinator:
    def __init__(self, config: AppConfig, engine: DialogueEngine | None = None) -> None:
        self.config = config
        self.logger = get_logger(__name__)
        self.session = SessionState()

        if engine is None:
            gateway = LLMGateway(config.runtime)
            self.engine = DialogueEngine(config, gateway)
        else:
            self.engine = engine

        self.max_history_messages = config.runtime.max_history_turns * 2
        self.memory_service = None  # TODO(v0.2): wire real memory manager.
        self.scheduler_service = None  # TODO(v0.2): wire proactive/reminder manager.

    def get_welcome_message(self) -> str:
        return self.config.persona.welcome_message

    def process_user_message(self, user_input: str) -> str:
        cleaned_input = normalize_whitespace(user_input)
        if not cleaned_input:
            return f"{self.config.persona.user_name}，先和我说一句吧。"

        history_snapshot = self.get_history_snapshot()

        self.logger.debug("Processing input=%s", safe_preview(cleaned_input))

        result = self.engine.generate_reply(
            user_input=cleaned_input,
            conversation_history=history_snapshot,
            memory_snippets=None,
        )

        self._append_message("user", cleaned_input)
        self._append_message("assistant", result.reply_text)
        self._trim_history()

        return result.reply_text

    def get_history_snapshot(self) -> list[Mapping[str, str]]:
        return list(self.session.history)

    def _append_message(self, role: str, content: str) -> None:
        self.session.history.append({"role": role, "content": content})

    def _trim_history(self) -> None:
        if len(self.session.history) <= self.max_history_messages:
            return
        self.session.history = self.session.history[-self.max_history_messages :]
