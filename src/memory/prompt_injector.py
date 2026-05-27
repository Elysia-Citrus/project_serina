from __future__ import annotations

from src.memory.models import MemoryReadResult


class MemoryPromptInjector:
    def build_prompt_items(self, result: MemoryReadResult) -> tuple[str, ...]:
        return result.prompt_items
