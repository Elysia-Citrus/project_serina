from __future__ import annotations

from typing import Iterable, Protocol

from src.voice.audio_player import InterruptToken
from src.voice.models import AudioChunkLike, TTSRequest


class TTSService(Protocol):
    def synthesize_stream(
        self,
        request: TTSRequest,
        *,
        interrupt_token: InterruptToken | None = None,
    ) -> Iterable[AudioChunkLike]:
        ...
