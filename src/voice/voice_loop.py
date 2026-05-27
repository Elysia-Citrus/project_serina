from __future__ import annotations

from contextlib import AbstractContextManager
from threading import Event, Thread
from time import sleep
from typing import TYPE_CHECKING

from src.config.loader import VoiceConfig
from src.voice.audio_player import AudioPlayer, InterruptToken
from src.voice.vad import BargeInDetector

if TYPE_CHECKING:
    from src.avatar.event_bus import AvatarEventBus
    from src.voice.recorder import AudioRecorder


class VoiceInterruptMonitor(AbstractContextManager["VoiceInterruptMonitor"]):
    def __init__(
        self,
        *,
        config: VoiceConfig,
        playback: AudioPlayer,
        recorder: "AudioRecorder",
        interrupt_token: InterruptToken,
        event_bus: "AvatarEventBus | None" = None,
    ) -> None:
        self.config = config
        self.playback = playback
        self.recorder = recorder
        self.interrupt_token = interrupt_token
        self.event_bus = event_bus
        self._stop_event = Event()
        self._threads: list[Thread] = []

    def __enter__(self) -> "VoiceInterruptMonitor":
        if not self.config.interrupt_enabled:
            return self
        if self.config.keyboard_interrupt_enabled:
            self._start_thread("voice-keyboard-interrupt", self._watch_keyboard)
        if self.config.microphone_interrupt_enabled:
            self._start_thread("voice-microphone-interrupt", self._watch_microphone)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=0.2)
        return False

    def _start_thread(self, name: str, target) -> None:  # type: ignore[no-untyped-def]
        thread = Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _interrupt(self, reason: str) -> None:
        if self.interrupt_token.is_interrupted():
            return
        self.interrupt_token.interrupt(reason)
        self.playback.stop(reason)
        if self.event_bus is not None:
            self.event_bus.emit("tts_interrupt", {"reason": reason})

    def _watch_keyboard(self) -> None:
        try:
            import msvcrt  # type: ignore
        except ModuleNotFoundError:
            return

        while not self._stop_event.is_set() and not self.interrupt_token.is_interrupted():
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key == b"\x1b":
                    self._interrupt("keyboard_escape")
                    return
            sleep(0.03)

    def _watch_microphone(self) -> None:
        if not hasattr(self.recorder, "open_chunk_source"):
            return
        detector = BargeInDetector(self.config)
        try:
            chunk_source = self.recorder.open_chunk_source()
            for chunk in chunk_source.iter_chunks():
                if self._stop_event.is_set() or self.interrupt_token.is_interrupted():
                    return
                update = detector.consume(chunk)
                if update.interrupted:
                    self._interrupt(update.reason or "microphone_barge_in")
                    return
        except Exception:
            return
