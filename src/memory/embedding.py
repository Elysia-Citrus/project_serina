from __future__ import annotations

from typing import Protocol


class EmbeddingService(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class NullEmbeddingService:
    def embed(self, text: str) -> list[float]:
        return []
