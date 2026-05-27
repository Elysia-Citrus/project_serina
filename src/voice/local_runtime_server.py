from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
from typing import Iterable
from urllib.parse import unquote, urlsplit
import wave

from src.config.loader import AppConfig, ConfigError, VoiceConfig, _read_yaml_file
from src.voice.models import AudioChunkLike, SynthesizedAudio, TTSRequest, VoiceProfile
from src.voice.profiles import VoiceProfileRegistry, load_voice_profile_registry

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WINDOWS_SAPI_SCRIPT = _PROJECT_ROOT / "scripts" / "windows_sapi_tts.ps1"


@dataclass(frozen=True)
class LocalRuntimeConfig:
    runtime_id: str
    bind_host: str
    bind_port: int
    provider_name: str
    adapter: str
    model_name: str
    voice_name: str | None = None
    rate: int = 0
    volume: int = 100
    unavailable_message: str | None = None


class LocalRuntimeAdapter:
    def healthz(self) -> dict[str, object]:
        raise NotImplementedError

    def describe_profile(
        self,
        profile: VoiceProfile | None,
        *,
        runtime_id: str,
    ) -> dict[str, object]:
        raise NotImplementedError

    def synthesize(
        self,
        request: TTSRequest,
        *,
        runtime_config: LocalRuntimeConfig,
        profile: VoiceProfile | None,
    ) -> SynthesizedAudio:
        raise NotImplementedError

    def synthesize_stream(
        self,
        request: TTSRequest,
        *,
        runtime_config: LocalRuntimeConfig,
        profile: VoiceProfile | None,
    ) -> Iterable[AudioChunkLike]:
        audio = self.synthesize(
            request,
            runtime_config=runtime_config,
            profile=profile,
        )
        chunks = request.text_chunks or (request.text,)
        for index, _chunk_text in enumerate(chunks):
            yield AudioChunkLike(
                audio_bytes=audio.audio_bytes,
                provider_name=audio.provider_name,
                model_name=audio.model_name,
                container_format=audio.container_format,
                sample_rate=audio.sample_rate,
                channels=audio.channels,
                sample_width=audio.sample_width,
                sequence_index=index,
                is_final=index == len(chunks) - 1,
            )


class DebugWaveAdapter(LocalRuntimeAdapter):
    sample_rate = 24000
    channels = 1
    sample_width = 2

    def healthz(self) -> dict[str, object]:
        return {"status": "ok", "adapter": "debug_wave"}

    def describe_profile(
        self,
        profile: VoiceProfile | None,
        *,
        runtime_id: str,
    ) -> dict[str, object]:
        return {
            "status": "ready",
            "runtime_id": runtime_id,
            "profile_id": profile.id if profile else None,
            "profile_kind": profile.profile_kind if profile else None,
            "adapter": "debug_wave",
            "note": "Debug wave adapter is active. This is a local smoke backend, not the final CosyVoice/GPT-SoVITS engine.",
        }

    def synthesize(
        self,
        request: TTSRequest,
        *,
        runtime_config: LocalRuntimeConfig,
        profile: VoiceProfile | None,
    ) -> SynthesizedAudio:
        text = request.text.strip()
        if not text:
            raise ValueError("synthesis text must not be empty")
        duration_ms = max(240, min(2400, 160 + len(text) * 28))
        waveform = self._build_waveform(
            text=text,
            duration_ms=duration_ms,
            runtime_id=runtime_config.runtime_id,
            style_hint=request.style_hint,
        )
        return SynthesizedAudio(
            audio_bytes=waveform,
            provider_name=runtime_config.provider_name,
            model_name=request.model_name or runtime_config.model_name,
            latency_ms=0,
            container_format="wav",
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            voice_preset=request.voice_preset,
        )

    def synthesize_stream(
        self,
        request: TTSRequest,
        *,
        runtime_config: LocalRuntimeConfig,
        profile: VoiceProfile | None,
    ) -> Iterable[AudioChunkLike]:
        chunks = request.text_chunks or (request.text,)
        for index, chunk_text in enumerate(chunks):
            audio = self.synthesize(
                TTSRequest(
                    text=chunk_text,
                    language=request.language,
                    model_name=request.model_name,
                    voice_preset=request.voice_preset,
                    speaker_id=request.speaker_id,
                    voice_profile_id=request.voice_profile_id,
                    reference_audio_path=request.reference_audio_path,
                    style_hint=request.style_hint,
                    profile_id=request.profile_id,
                    runtime_id=request.runtime_id,
                    profile_kind=request.profile_kind,
                    asset_dir=request.asset_dir,
                    reference_text=request.reference_text,
                ),
                runtime_config=runtime_config,
                profile=profile,
            )
            yield AudioChunkLike(
                audio_bytes=audio.audio_bytes,
                provider_name=audio.provider_name,
                model_name=audio.model_name,
                container_format=audio.container_format,
                sample_rate=audio.sample_rate,
                channels=audio.channels,
                sample_width=audio.sample_width,
                sequence_index=index,
                is_final=index == len(chunks) - 1,
            )

    def _build_waveform(
        self,
        *,
        text: str,
        duration_ms: int,
        runtime_id: str,
        style_hint: str | None,
    ) -> bytes:
        total_frames = max(1, int(self.sample_rate * duration_ms / 1000))
        base_frequency = 180 if runtime_id == "primary" else 130
        style_offset = 0 if not style_hint else sum(ord(char) for char in style_hint) % 40
        text_offset = sum(ord(char) for char in text[:24]) % 80
        frequency = base_frequency + style_offset + text_offset
        amplitude = 0.22
        fade_frames = min(total_frames // 10, 400)
        frame_data = bytearray()
        from io import BytesIO

        for frame_index in range(total_frames):
            position = frame_index / self.sample_rate
            envelope = 1.0
            if fade_frames:
                if frame_index < fade_frames:
                    envelope = frame_index / fade_frames
                elif frame_index > total_frames - fade_frames:
                    envelope = max(0.0, (total_frames - frame_index) / fade_frames)
            sample = math.sin(2.0 * math.pi * frequency * position)
            pcm_value = int(sample * envelope * amplitude * 32767)
            frame_data.extend(struct.pack("<h", pcm_value))

        output = BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(bytes(frame_data))
        return output.getvalue()


class UnavailableRuntimeAdapter(LocalRuntimeAdapter):
    def __init__(self, message: str) -> None:
        self.message = message

    def healthz(self) -> dict[str, object]:
        return {
            "status": "degraded",
            "adapter": "unavailable",
            "message": self.message,
        }

    def describe_profile(
        self,
        profile: VoiceProfile | None,
        *,
        runtime_id: str,
    ) -> dict[str, object]:
        return {
            "status": "unavailable",
            "runtime_id": runtime_id,
            "profile_id": profile.id if profile else None,
            "profile_kind": profile.profile_kind if profile else None,
            "adapter": "unavailable",
            "message": self.message,
        }

    def synthesize(
        self,
        request: TTSRequest,
        *,
        runtime_config: LocalRuntimeConfig,
        profile: VoiceProfile | None,
    ) -> SynthesizedAudio:
        raise RuntimeError(self.message)


class WindowsSapiAdapter(LocalRuntimeAdapter):
    def healthz(self) -> dict[str, object]:
        voices = self._list_voices()
        selected_voice = self._select_voice_name(voices)
        return {
            "status": "ok",
            "adapter": "windows_sapi",
            "voice_count": len(voices),
            "selected_voice": selected_voice,
        }

    def describe_profile(
        self,
        profile: VoiceProfile | None,
        *,
        runtime_id: str,
    ) -> dict[str, object]:
        voices = self._list_voices()
        return {
            "status": "ready",
            "runtime_id": runtime_id,
            "profile_id": profile.id if profile else None,
            "profile_kind": profile.profile_kind if profile else None,
            "adapter": "windows_sapi",
            "voice_count": len(voices),
            "selected_voice": self._select_voice_name(voices),
        }

    def synthesize(
        self,
        request: TTSRequest,
        *,
        runtime_config: LocalRuntimeConfig,
        profile: VoiceProfile | None,
    ) -> SynthesizedAudio:
        text = request.text.strip()
        if not text:
            raise ValueError("synthesis text must not be empty")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)

        try:
            self._run_sapi(
                action="synthesize",
                output_path=output_path,
                text=text,
                runtime_config=runtime_config,
            )
            audio_bytes = output_path.read_bytes()
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass

        return SynthesizedAudio(
            audio_bytes=audio_bytes,
            provider_name=runtime_config.provider_name,
            model_name=request.model_name or runtime_config.model_name,
            latency_ms=0,
            container_format="wav",
            sample_rate=None,
            channels=None,
            sample_width=None,
            voice_preset=request.voice_preset,
        )

    def synthesize_stream(
        self,
        request: TTSRequest,
        *,
        runtime_config: LocalRuntimeConfig,
        profile: VoiceProfile | None,
    ) -> Iterable[AudioChunkLike]:
        chunks = request.text_chunks or (request.text,)
        for index, chunk_text in enumerate(chunks):
            audio = self.synthesize(
                TTSRequest(
                    text=chunk_text,
                    language=request.language,
                    model_name=request.model_name,
                    voice_preset=request.voice_preset,
                    speaker_id=request.speaker_id,
                    voice_profile_id=request.voice_profile_id,
                    reference_audio_path=request.reference_audio_path,
                    style_hint=request.style_hint,
                    profile_id=request.profile_id,
                    runtime_id=request.runtime_id,
                    profile_kind=request.profile_kind,
                    asset_dir=request.asset_dir,
                    reference_text=request.reference_text,
                ),
                runtime_config=runtime_config,
                profile=profile,
            )
            yield AudioChunkLike(
                audio_bytes=audio.audio_bytes,
                provider_name=audio.provider_name,
                model_name=audio.model_name,
                container_format=audio.container_format,
                sample_rate=audio.sample_rate,
                channels=audio.channels,
                sample_width=audio.sample_width,
                sequence_index=index,
                is_final=index == len(chunks) - 1,
            )

    def _list_voices(self) -> list[str]:
        payload = self._run_sapi(action="list-voices", output_path=None, text=None, runtime_config=None)
        voices = payload.get("voices")
        if not isinstance(voices, list):
            raise RuntimeError("windows_sapi did not return a voice list.")
        cleaned: list[str] = []
        for voice in voices:
            if isinstance(voice, str) and voice.strip():
                cleaned.append(voice.strip())
        if not cleaned:
            raise RuntimeError("No Windows SAPI voices are installed.")
        return cleaned

    def _select_voice_name(self, voices: list[str]) -> str | None:
        for voice in voices:
            if "Huihui" in voice or "Chinese" in voice or "中文" in voice:
                return voice
        return voices[0] if voices else None

    def _run_sapi(
        self,
        *,
        action: str,
        output_path: Path | None,
        text: str | None,
        runtime_config: LocalRuntimeConfig | None,
    ) -> dict[str, object]:
        if not _WINDOWS_SAPI_SCRIPT.exists():
            raise RuntimeError(f"Missing Windows SAPI helper script: {_WINDOWS_SAPI_SCRIPT}")

        command = [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_WINDOWS_SAPI_SCRIPT),
            "-Action",
            action,
        ]
        if output_path is not None:
            command.extend(["-OutputPath", str(output_path)])
        if text is not None:
            import base64

            command.extend(
                [
                    "-TextBase64",
                    base64.b64encode(text.encode("utf-8")).decode("ascii"),
                ]
            )
        if runtime_config is not None:
            if runtime_config.voice_name:
                command.extend(["-VoiceName", runtime_config.voice_name])
            command.extend(["-Rate", str(runtime_config.rate)])
            command.extend(["-Volume", str(runtime_config.volume)])

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip() or "unknown error"
            raise RuntimeError(f"Windows SAPI backend failed: {message}")
        stdout = (completed.stdout or "").strip()
        if not stdout:
            return {}
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Windows SAPI backend returned invalid JSON: {stdout}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Windows SAPI backend returned an invalid payload.")
        return parsed


class LocalRuntimeApp:
    def __init__(
        self,
        *,
        runtime_config: LocalRuntimeConfig,
        voice_config: VoiceConfig,
        profile_registry: VoiceProfileRegistry,
        adapter: LocalRuntimeAdapter,
    ) -> None:
        self.runtime_config = runtime_config
        self.voice_config = voice_config
        self.profile_registry = profile_registry
        self.adapter = adapter

    def healthz(self) -> dict[str, object]:
        payload = dict(self.adapter.healthz())
        payload.update(
            {
                "runtime_id": self.runtime_config.runtime_id,
                "provider_name": self.runtime_config.provider_name,
                "model_name": self.runtime_config.model_name,
            }
        )
        return payload

    def describe_profile(self, profile_id: str) -> dict[str, object]:
        profile = self.profile_registry.get(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        payload = dict(
            self.adapter.describe_profile(
                profile,
                runtime_id=self.runtime_config.runtime_id,
            )
        )
        payload.update(
            {
                "profile_id": profile.id,
                "provider": profile.provider,
                "runtime_id": profile.runtime_id,
                "profile_kind": profile.profile_kind,
                "enabled": profile.enabled,
                "asset_dir": profile.asset_dir,
                "reference_audio_path": profile.reference_audio_path,
            }
        )
        if profile.runtime_id and profile.runtime_id != self.runtime_config.runtime_id:
            payload["status"] = "mismatch"
            payload["message"] = (
                f"profile runtime_id={profile.runtime_id} does not match server runtime_id={self.runtime_config.runtime_id}"
            )
        return payload

    def synthesize(self, payload: dict[str, object]) -> dict[str, object]:
        request, profile = self._build_request(payload)
        synthesized_audio = self.adapter.synthesize(
            request,
            runtime_config=self.runtime_config,
            profile=profile,
        )
        return self._encode_audio(synthesized_audio)

    def synthesize_stream(self, payload: dict[str, object]) -> Iterable[dict[str, object]]:
        request, profile = self._build_request(payload)
        for audio_chunk in self.adapter.synthesize_stream(
            request,
            runtime_config=self.runtime_config,
            profile=profile,
        ):
            yield {
                "event": "audio_chunk",
                "sequence_index": audio_chunk.sequence_index,
                "is_final": audio_chunk.is_final,
                "provider_name": audio_chunk.provider_name,
                "model_name": audio_chunk.model_name,
                "container_format": audio_chunk.container_format,
                "sample_rate": audio_chunk.sample_rate,
                "channels": audio_chunk.channels,
                "sample_width": audio_chunk.sample_width,
                "audio_base64": b64encode(audio_chunk.audio_bytes).decode("ascii"),
            }
        yield {"event": "done"}

    def _build_request(self, payload: dict[str, object]) -> tuple[TTSRequest, VoiceProfile | None]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("request body must include non-empty `text`")

        profile_id = _clean_optional_string(payload.get("profile_id"))
        runtime_id = _clean_optional_string(payload.get("runtime_id"))
        if runtime_id and runtime_id != self.runtime_config.runtime_id:
            raise ValueError(
                f"request runtime_id={runtime_id} does not match server runtime_id={self.runtime_config.runtime_id}"
            )

        profile = self.profile_registry.get(profile_id) if profile_id else None
        text_chunks = _coerce_text_chunks(payload.get("text_chunks"))
        model_name = _clean_optional_string(payload.get("model")) or _clean_optional_string(payload.get("model_name"))
        request = TTSRequest(
            text=text,
            language=_clean_optional_string(payload.get("language")) or self.voice_config.language,
            model_name=model_name or self.runtime_config.model_name,
            voice_preset=_clean_optional_string(payload.get("voice_preset")),
            speaker_id=_clean_optional_string(payload.get("speaker_id")),
            voice_profile_id=_clean_optional_string(payload.get("voice_profile_id")),
            reference_audio_path=_clean_optional_string(payload.get("reference_audio_path")),
            style_hint=_clean_optional_string(payload.get("style_hint")),
            profile_id=profile_id,
            runtime_id=self.runtime_config.runtime_id,
            profile_kind=_clean_optional_string(payload.get("profile_kind")),
            asset_dir=_clean_optional_string(payload.get("asset_dir")),
            reference_text=_clean_optional_string(payload.get("reference_text")),
            text_chunks=text_chunks,
        )
        return request, profile

    def _encode_audio(self, synthesized_audio: SynthesizedAudio) -> dict[str, object]:
        return {
            "provider_name": synthesized_audio.provider_name,
            "model_name": synthesized_audio.model_name,
            "container_format": synthesized_audio.container_format,
            "sample_rate": synthesized_audio.sample_rate,
            "channels": synthesized_audio.channels,
            "sample_width": synthesized_audio.sample_width,
            "audio_base64": b64encode(synthesized_audio.audio_bytes).decode("ascii"),
        }


class LocalRuntimeServer:
    def __init__(self, app: LocalRuntimeApp) -> None:
        self.app = app
        handler = self._build_handler()
        self.httpd = ThreadingHTTPServer(
            (app.runtime_config.bind_host, app.runtime_config.bind_port),
            handler,
        )
        self.httpd.daemon_threads = True

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self.httpd.server_address
        return str(host), int(port)

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _build_handler(self):
        app = self.app

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                try:
                    if self.path == "/healthz":
                        self._write_json(HTTPStatus.OK, app.healthz())
                        return
                    if self.path.startswith("/profiles/"):
                        profile_id = unquote(self.path.removeprefix("/profiles/"))
                        self._write_json(HTTPStatus.OK, app.describe_profile(profile_id))
                        return
                    self._write_json(
                        HTTPStatus.NOT_FOUND,
                        {"error": "not_found", "message": "unsupported path"},
                    )
                except KeyError as exc:
                    self._write_json(
                        HTTPStatus.NOT_FOUND,
                        {"error": "profile_not_found", "message": str(exc)},
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self._write_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": "server_error", "message": str(exc)},
                    )

            def do_POST(self) -> None:  # noqa: N802
                try:
                    payload = self._read_json()
                    if self.path == "/synthesize":
                        self._write_json(HTTPStatus.OK, app.synthesize(payload))
                        return
                    if self.path == "/synthesize-stream":
                        event_iterator = iter(app.synthesize_stream(payload))
                        first_event = next(event_iterator)
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                        self.end_headers()
                        self.wfile.write((json.dumps(first_event, ensure_ascii=False) + "\n").encode("utf-8"))
                        self.wfile.flush()
                        for event in event_iterator:
                            self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                            self.wfile.flush()
                        return
                    self._write_json(
                        HTTPStatus.NOT_FOUND,
                        {"error": "not_found", "message": "unsupported path"},
                    )
                except ValueError as exc:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "bad_request", "message": str(exc)},
                    )
                except RuntimeError as exc:
                    self._write_json(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        {"error": "runtime_unavailable", "message": str(exc)},
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self._write_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": "server_error", "message": str(exc)},
                    )

            def log_message(self, format, *args) -> None:  # noqa: A003
                return

            def _read_json(self) -> dict[str, object]:
                raw_length = self.headers.get("Content-Length", "0").strip()
                try:
                    content_length = int(raw_length)
                except ValueError as exc:
                    raise ValueError("invalid content length") from exc
                body = self.rfile.read(max(0, content_length))
                try:
                    payload = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError("request body must be valid JSON") from exc
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
                return payload

            def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        return Handler


def build_local_runtime_server(
    app_config: AppConfig,
    *,
    runtime_id: str,
    runtime_settings_path: str | Path | None = None,
) -> LocalRuntimeServer:
    runtime_config = load_local_runtime_config(
        app_config,
        runtime_id=runtime_id,
        runtime_settings_path=runtime_settings_path,
    )
    registry_path = _resolve_registry_path(
        config_dir=app_config.config_dir,
        configured_path=app_config.voice.voice_profiles_path,
    )
    profile_registry = load_voice_profile_registry(registry_path, allow_missing=True)
    adapter = _build_runtime_adapter(runtime_config)
    app = LocalRuntimeApp(
        runtime_config=runtime_config,
        voice_config=app_config.voice,
        profile_registry=profile_registry,
        adapter=adapter,
    )
    return LocalRuntimeServer(app)


def load_local_runtime_config(
    app_config: AppConfig,
    *,
    runtime_id: str,
    runtime_settings_path: str | Path | None = None,
) -> LocalRuntimeConfig:
    settings_path = (
        Path(runtime_settings_path)
        if runtime_settings_path is not None
        else app_config.config_dir / "local_tts_runtime.yaml"
    )
    raw = _read_yaml_file(settings_path)
    runtimes = raw.get("runtimes")
    if not isinstance(runtimes, dict):
        raise ConfigError(f"{settings_path} must contain a `runtimes` mapping.")
    runtime_raw = runtimes.get(runtime_id)
    if not isinstance(runtime_raw, dict):
        raise ConfigError(f"{settings_path} is missing runtime `{runtime_id}`.")

    bind_host, bind_port = _resolve_bind_address(app_config.voice, runtime_id)
    provider_name = "cosyvoice_local" if runtime_id == "primary" else "gpt_sovits_local"
    adapter = _clean_optional_string(runtime_raw.get("adapter")) or "unavailable"
    model_name = _clean_optional_string(runtime_raw.get("model_name")) or provider_name
    return LocalRuntimeConfig(
        runtime_id=runtime_id,
        bind_host=_clean_optional_string(runtime_raw.get("host")) or bind_host,
        bind_port=_coerce_int(runtime_raw.get("port")) or bind_port,
        provider_name=provider_name,
        adapter=adapter,
        model_name=model_name,
        voice_name=_clean_optional_string(runtime_raw.get("voice_name")),
        rate=_coerce_int(runtime_raw.get("rate")) or 0,
        volume=_coerce_int(runtime_raw.get("volume")) or 100,
        unavailable_message=_clean_optional_string(runtime_raw.get("unavailable_message")),
    )


def _build_runtime_adapter(runtime_config: LocalRuntimeConfig) -> LocalRuntimeAdapter:
    if runtime_config.adapter == "debug_wave":
        return DebugWaveAdapter()
    if runtime_config.adapter == "windows_sapi":
        return WindowsSapiAdapter()
    if runtime_config.adapter == "unavailable":
        return UnavailableRuntimeAdapter(
            runtime_config.unavailable_message
            or f"{runtime_config.runtime_id} runtime backend is not configured yet."
        )
    raise ConfigError(
        f"Unsupported local runtime adapter `{runtime_config.adapter}` for runtime `{runtime_config.runtime_id}`."
    )


def _resolve_registry_path(*, config_dir: Path, configured_path: str) -> Path:
    raw_path = Path(configured_path)
    if raw_path.is_absolute():
        return raw_path
    return (config_dir / raw_path).resolve()


def _resolve_bind_address(
    voice_config: VoiceConfig,
    runtime_id: str,
) -> tuple[str, int]:
    raw_url = (
        voice_config.primary_tts_runtime_url
        if runtime_id == "primary"
        else voice_config.clone_tts_runtime_url
    )
    parsed = urlsplit(raw_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _clean_optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("Expected an optional string value, but got a non-string.")
    cleaned = value.strip()
    return cleaned or None


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ConfigError("Expected an integer value in local runtime config.")
    return value


def _coerce_text_chunks(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("`text_chunks` must be a list of strings")
    chunks: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("`text_chunks` must contain only strings")
        cleaned = item.strip()
        if cleaned:
            chunks.append(cleaned)
    return tuple(chunks)
