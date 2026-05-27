from __future__ import annotations

from dataclasses import dataclass

from src.memory.manager import MemoryManager


@dataclass(frozen=True)
class RetrievedMemory:
    id: str
    text: str
    reason: str


class MemoryRetriever:
    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager

    def retrieve(
        self,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 3,
    ) -> list[RetrievedMemory]:
        result = self.manager.retrieve(
            user_input=query,
            scene="voice_demo",
            session_id=session_id,
        )
        memories: list[RetrievedMemory] = []
        for item in result.selected_items[:limit]:
            memories.append(
                RetrievedMemory(
                    id=item.id,
                    text=item.display_text(),
                    reason="long_term_memory",
                )
            )
        return memories
