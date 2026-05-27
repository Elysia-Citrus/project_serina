from __future__ import annotations

from src.utils.text_utils import normalize_whitespace


_SENTENCE_ENDINGS = {"。", "！", "？", "!", "?"}
_SOFT_BREAKS = {"，", ",", "；", ";", "：", ":", "、"}


class SpeechChunker:
    def __init__(
        self,
        *,
        max_sentences_per_chunk: int = 2,
        max_chars_per_chunk: int = 80,
    ) -> None:
        self.max_sentences_per_chunk = max(1, max_sentences_per_chunk)
        self.max_chars_per_chunk = max(16, max_chars_per_chunk)

    def chunk(self, text: str) -> tuple[str, ...]:
        normalized = normalize_whitespace(text)
        if not normalized:
            return ()

        sentence_units = self._split_sentences(normalized)
        chunks: list[str] = []
        pending: list[str] = []

        for sentence in sentence_units:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > self.max_chars_per_chunk:
                for overflow_unit in self._split_long_sentence(sentence):
                    if pending and len("".join(pending)) + len(overflow_unit) > self.max_chars_per_chunk:
                        chunks.append("".join(pending).strip())
                        pending.clear()
                    pending.append(overflow_unit)
                    if (
                        len(pending) >= self.max_sentences_per_chunk
                        or len("".join(pending)) >= self.max_chars_per_chunk
                    ):
                        chunks.append("".join(pending).strip())
                        pending.clear()
                continue

            if pending and (
                len(pending) >= self.max_sentences_per_chunk
                or len("".join(pending)) + len(sentence) > self.max_chars_per_chunk
            ):
                chunks.append("".join(pending).strip())
                pending.clear()
            pending.append(sentence)

        if pending:
            chunks.append("".join(pending).strip())
        return tuple(chunk for chunk in chunks if chunk)

    def _split_sentences(self, text: str) -> list[str]:
        sentences: list[str] = []
        current: list[str] = []
        for character in text:
            current.append(character)
            if character in _SENTENCE_ENDINGS:
                sentences.append("".join(current).strip())
                current.clear()
        if current:
            sentences.append("".join(current).strip())
        return sentences or [text]

    def _split_long_sentence(self, sentence: str) -> tuple[str, ...]:
        pieces: list[str] = []
        current: list[str] = []

        for character in sentence:
            current.append(character)
            current_text = "".join(current)
            if len(current_text) >= self.max_chars_per_chunk and character in _SOFT_BREAKS:
                pieces.append(current_text.strip())
                current.clear()

        if current:
            remainder = "".join(current).strip()
            if remainder:
                if len(remainder) <= self.max_chars_per_chunk:
                    pieces.append(remainder)
                else:
                    pieces.extend(self._hard_split(remainder))
        return tuple(piece for piece in pieces if piece)

    def _hard_split(self, text: str) -> tuple[str, ...]:
        pieces: list[str] = []
        for start in range(0, len(text), self.max_chars_per_chunk):
            piece = text[start : start + self.max_chars_per_chunk].strip()
            if piece:
                pieces.append(piece)
        return tuple(pieces)
