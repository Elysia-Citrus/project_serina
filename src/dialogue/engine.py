from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.config.loader import AppConfig
from src.dialogue.postprocess import postprocess_response
from src.dialogue.prompt_builder import PromptPackage, build_prompt_package
from src.llm.gateway import LLMGateway
from src.utils.logger import get_logger
from src.utils.text_utils import safe_preview


@dataclass(frozen=True)
class DialogueResult:
    reply_text: str
    scene: str
    raw_response: str
    memory_write_candidate: None = None
    proactive_followup_candidate: None = None


class DialogueEngine:
    def __init__(self, config: AppConfig, gateway: LLMGateway) -> None:
        self.config = config
        self.gateway = gateway
        self.logger = get_logger(__name__)

    def generate_reply(
        self,
        user_input: str,
        conversation_history: Sequence[Mapping[str, str]],
        memory_snippets: Sequence[str] | None = None,
    ) -> DialogueResult:
        prompt_package = build_prompt_package(
            user_input=user_input,
            conversation_history=conversation_history,
            persona=self.config.persona,
            policy=self.config.policy,
            memory_snippets=memory_snippets,
        )

        self._log_prompt(prompt_package, user_input)

        raw_response = self.gateway.generate(prompt_package.messages)
        fallback = f"{self.config.persona.user_name}，我在。"
        final_response = postprocess_response(raw_response, fallback_text=fallback)

        self.logger.debug(
            "Scene=%s | reply=%s",
            prompt_package.scene,
            safe_preview(final_response),
        )

        return DialogueResult(
            reply_text=final_response,
            scene=prompt_package.scene,
            raw_response=raw_response,
        )

    def _log_prompt(self, prompt_package: PromptPackage, user_input: str) -> None:
        self.logger.debug(
            "Preparing reply | scene=%s | user_input=%s",
            prompt_package.scene,
            safe_preview(user_input),
        )
