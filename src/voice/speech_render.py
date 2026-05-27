from __future__ import annotations

import re

from src.utils.text_utils import normalize_whitespace
from src.voice.models import SpeechRenderResult


_SCENE_STYLE_MAP = {
    "greeting": "default",
    "casual_chat": "default",
    "comfort": "comfort",
    "deep_discussion": "discussion",
    "correction": "correction",
}

_STAGE_DIRECTION_PATTERNS = (
    re.compile(r"（[^（）]{0,120}）"),
    re.compile(r"\([^()]{0,120}\)"),
    re.compile(r"【[^【】]{0,120}】"),
    re.compile(r"\[[^\[\]]{0,120}\]"),
)
_COMMAND_LINE_PATTERN = re.compile(r"(?m)^\s*/[A-Za-z][^\n]*$")
_ASCII_ELLIPSIS_PATTERN = re.compile(r"\.{3,}")
_ELLIPSIS_PATTERN = re.compile(r"…{2,}")
_REPEATED_PUNCT_PATTERN = re.compile(r"([。！？!?~～])\1+")
_EDGE_PUNCT_PATTERN = re.compile(r"(^|[\n ])([，,。！？!?~～]+)")


class SpeechScriptRenderer:
    def render(self, reply_text: str, *, scene: str) -> SpeechRenderResult:
        style_id = _SCENE_STYLE_MAP.get(scene, "default")
        applied_rules: list[str] = []

        speech_text = normalize_whitespace(reply_text)
        if speech_text != reply_text.strip():
            applied_rules.append("normalize_whitespace")

        stripped_stage_text = self._strip_stage_directions(speech_text)
        if stripped_stage_text != speech_text:
            speech_text = stripped_stage_text
            applied_rules.append("strip_stage_directions")

        stripped_command_text = self._strip_command_lines(speech_text)
        if stripped_command_text != speech_text:
            speech_text = stripped_command_text
            applied_rules.append("strip_command_lines")

        compressed_text = self._compress_punctuation(speech_text)
        if compressed_text != speech_text:
            speech_text = compressed_text
            applied_rules.append("compress_punctuation")

        cleaned_text = normalize_whitespace(speech_text)
        if cleaned_text != speech_text and "normalize_whitespace" not in applied_rules:
            applied_rules.append("normalize_whitespace")
        speech_text = cleaned_text or normalize_whitespace(reply_text)

        return SpeechRenderResult(
            speech_text=speech_text,
            style_id=style_id,
            applied_rules=tuple(applied_rules),
        )

    def _strip_stage_directions(self, text: str) -> str:
        stripped = text
        for pattern in _STAGE_DIRECTION_PATTERNS:
            while True:
                updated = pattern.sub("", stripped)
                if updated == stripped:
                    break
                stripped = updated
        return self._trim_edge_punctuation(stripped)

    def _strip_command_lines(self, text: str) -> str:
        stripped = _COMMAND_LINE_PATTERN.sub("", text)
        return self._trim_edge_punctuation(stripped)

    def _compress_punctuation(self, text: str) -> str:
        compressed = _ASCII_ELLIPSIS_PATTERN.sub("…", text)
        compressed = _ELLIPSIS_PATTERN.sub("…", compressed)
        compressed = _REPEATED_PUNCT_PATTERN.sub(r"\1", compressed)
        return self._trim_edge_punctuation(compressed)

    def _trim_edge_punctuation(self, text: str) -> str:
        trimmed = _EDGE_PUNCT_PATTERN.sub(r"\1", text)
        return trimmed.strip()
