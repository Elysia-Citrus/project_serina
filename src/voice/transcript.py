from __future__ import annotations

from dataclasses import dataclass

from src.config.loader import VoiceConfig
from src.utils.text_utils import normalize_whitespace


@dataclass(frozen=True)
class TranscriptUpdate:
    raw_text: str
    normalized_text: str
    display_text: str | None = None


class TranscriptAggregator:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.last_partial_text: str | None = None

    def update_partial(self, text: str) -> TranscriptUpdate:
        normalized = self._normalize(text)
        display_text = None
        if self.config.partial_transcript_enabled and normalized:
            if self.config.partial_commit_strategy == "console_latest":
                display_text = normalized
            elif self.config.partial_commit_strategy == "stable_prefix":
                display_text = self._stable_prefix(normalized)
        self.last_partial_text = normalized or self.last_partial_text
        return TranscriptUpdate(
            raw_text=text,
            normalized_text=normalized,
            display_text=display_text,
        )

    def finalize(self, text: str) -> TranscriptUpdate:
        normalized = self._normalize(text)
        self.last_partial_text = None
        return TranscriptUpdate(
            raw_text=text,
            normalized_text=normalized,
            display_text=normalized or None,
        )

    def _normalize(self, text: str) -> str:
        normalized = " ".join(normalize_whitespace(text).split())
        return _dedupe_repeated_suffix(normalized)

    def _stable_prefix(self, text: str) -> str | None:
        if not self.last_partial_text:
            return text
        stable_chars: list[str] = []
        for previous, current in zip(self.last_partial_text, text):
            if previous != current:
                break
            stable_chars.append(current)
        stable_prefix = "".join(stable_chars).strip()
        return stable_prefix or text


def _dedupe_repeated_suffix(text: str) -> str:
    if len(text) < 3:
        return text
    for unit_len in range(1, min(4, len(text) // 2 + 1)):
        unit = text[-unit_len:]
        repeated = unit * 3
        if text.endswith(repeated):
            while text.endswith(unit * 2):
                text = text[:-unit_len]
            break
    return text.strip()
