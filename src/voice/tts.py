from __future__ import annotations

import base64
from dataclasses import replace
import json
from time import monotonic
from typing import Iterable, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from src.config.loader import VoiceConfig
from src.integrations.myneuro_gpt_sovits_v2_client import (
    GPTSoVITSv2Client,
    GPTSoVITSv2Request,
)
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.models import AudioChunkLike, SynthesizedAudio, TTSRequest


class TTSProvider(Protocol):
    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        ...


class LocalSpeechProvider(TTSProvider, Protocol):
    def synthesize_full(self, request: TTSRequest) -> SynthesizedAudio:
        ...

    def synthesize_stream(self, request: TTSRequest) -> Iterable[AudioChunkLike]:
        ...

    def healthcheck(self) -> dict[str, object]:
        ...

    def get_profile_state(self, profile_id: str) -> dict[str, object]:
        ...


class NullTTSProvider:
    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        return SynthesizedAudio(
            audio_bytes=b"",
            provider_name="none",
            model_name="none",
            latency_ms=0,
        )


class DefaultChineseTTSProvider:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        if not self.config.tts_api_key:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Missing TTS API key. Set {self.config.tts_api_key_env} before using voice mode.",
            )

        model_name = request.model_name or self.config.tts_model
        voice_name = request.voice_preset or self.config.tts_voice_preset
        started_at = monotonic()
        response_json = self._request_synthesis(
            text=request.text,
            model_name=model_name,
            voice_name=voice_name,
        )
        audio_url = self._extract_audio_url(response_json)
        audio_bytes = self._download_audio(audio_url)
        latency_ms = int((monotonic() - started_at) * 1000)
        return SynthesizedAudio(
            audio_bytes=audio_bytes,
            provider_name=self.config.tts_provider,
            model_name=model_name,
            latency_ms=latency_ms,
            container_format="wav",
            voice_preset=voice_name,
            audio_url=audio_url,
        )

    def _request_synthesis(
        self,
        *,
        text: str,
        model_name: str,
        voice_name: str,
    ) -> dict[str, object]:
        endpoint = self.config.tts_base_url.rstrip("/") + "/services/audio/tts/SpeechSynthesizer"
        payload = {
            "model": model_name,
            "input": {
                "text": text,
                "voice": voice_name,
                "format": "wav",
            },
        }
        request = urllib_request.Request(
            url=endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.tts_api_key}",
                "X-DashScope-Async": "false",
            },
            method="POST",
        )

        try:
            with urllib_request.urlopen(request, timeout=60) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"TTS provider returned HTTP {exc.code}.",
            ) from exc
        except urllib_error.URLError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Unable to reach the TTS provider: {exc.reason}",
            ) from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                "TTS provider returned invalid JSON.",
            ) from exc
        if not isinstance(parsed, dict):
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                "TTS provider returned an invalid response payload.",
            )
        return parsed

    def _extract_audio_url(self, payload: dict[str, object]) -> str:
        output = payload.get("output")
        if isinstance(output, dict):
            audio = output.get("audio")
            if isinstance(audio, dict):
                url = audio.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
        raise VoicePipelineError(
            VoiceErrorStage.SPEAKING,
            "TTS provider response did not include an audio URL.",
        )

    def _download_audio(self, audio_url: str) -> bytes:
        try:
            with urllib_request.urlopen(audio_url, timeout=60) as response:
                return response.read()
        except urllib_error.URLError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Unable to download synthesized audio: {exc.reason}",
            ) from exc


class _StreamEndpointUnsupported(RuntimeError):
    pass


class LocalRuntimeTTSProvider:
    def __init__(
        self,
        config: VoiceConfig,
        *,
        provider_name: str,
        runtime_url: str,
    ) -> None:
        self.config = config
        self.provider_name = provider_name.lower()
        self.runtime_url = runtime_url.rstrip("/")

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        return self.synthesize_full(request)

    def synthesize_full(self, request: TTSRequest) -> SynthesizedAudio:
        started_at = monotonic()
        payload = self._request_json(
            "/synthesize",
            payload=self._build_payload(request, request.text),
            method="POST",
        )
        latency_ms = int((monotonic() - started_at) * 1000)
        audio_bytes = self._extract_audio_bytes(payload)
        return SynthesizedAudio(
            audio_bytes=audio_bytes,
            provider_name=self.provider_name,
            model_name=self._extract_string(payload, "model_name") or request.model_name or "local-model",
            latency_ms=latency_ms,
            container_format=self._extract_string(payload, "container_format") or "wav",
            sample_rate=self._extract_int(payload, "sample_rate"),
            channels=self._extract_int(payload, "channels"),
            sample_width=self._extract_int(payload, "sample_width"),
            voice_preset=request.voice_preset,
        )

    def synthesize_stream(self, request: TTSRequest) -> Iterable[AudioChunkLike]:
        try:
            yield from self._stream_from_endpoint(request)
            return
        except _StreamEndpointUnsupported:
            pass

        text_chunks = request.text_chunks or (request.text,)
        for index, chunk_text in enumerate(text_chunks):
            chunk_request = replace(request, text=chunk_text, text_chunks=())
            audio = self.synthesize_full(chunk_request)
            yield AudioChunkLike(
                audio_bytes=audio.audio_bytes,
                provider_name=audio.provider_name,
                model_name=audio.model_name,
                container_format=audio.container_format,
                sample_rate=audio.sample_rate,
                channels=audio.channels,
                sample_width=audio.sample_width,
                sequence_index=index,
                is_final=index == len(text_chunks) - 1,
            )

    def healthcheck(self) -> dict[str, object]:
        return self._request_json("/healthz", method="GET")

    def get_profile_state(self, profile_id: str) -> dict[str, object]:
        encoded_profile_id = urllib_parse.quote(profile_id, safe="")
        return self._request_json(f"/profiles/{encoded_profile_id}", method="GET")

    def _stream_from_endpoint(self, request: TTSRequest) -> Iterable[AudioChunkLike]:
        endpoint = self.runtime_url + "/synthesize-stream"
        payload = self._build_payload(
            request,
            request.text,
            text_chunks=request.text_chunks or None,
        )
        http_request = urllib_request.Request(
            url=endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(http_request, timeout=60) as response:
                sequence_index = 0
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    decoded_line = raw_line.decode("utf-8").strip()
                    if not decoded_line:
                        continue
                    payload = self._decode_json(decoded_line)
                    event_name = str(payload.get("event", "audio_chunk")).strip().lower()
                    if event_name == "done":
                        break
                    if event_name == "error":
                        raise VoicePipelineError(
                            VoiceErrorStage.SPEAKING,
                            str(payload.get("message") or "Local TTS runtime reported an error."),
                        )
                    yield AudioChunkLike(
                        audio_bytes=self._extract_audio_bytes(payload),
                        provider_name=self.provider_name,
                        model_name=self._extract_string(payload, "model_name")
                        or request.model_name
                        or "local-model",
                        container_format=self._extract_string(payload, "container_format") or "wav",
                        sample_rate=self._extract_int(payload, "sample_rate"),
                        channels=self._extract_int(payload, "channels"),
                        sample_width=self._extract_int(payload, "sample_width"),
                        sequence_index=self._extract_int(payload, "sequence_index") or sequence_index,
                        is_final=bool(payload.get("is_final", False)),
                    )
                    sequence_index += 1
        except urllib_error.HTTPError as exc:
            if exc.code in {404, 405}:
                raise _StreamEndpointUnsupported() from exc
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Local TTS runtime `{self.provider_name}` returned HTTP {exc.code}.",
            ) from exc
        except urllib_error.URLError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Unable to reach local TTS runtime `{self.provider_name}`: {exc.reason}",
            ) from exc

    def _request_json(
        self,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        method: str,
    ) -> dict[str, object]:
        endpoint = self.runtime_url + path
        request_data = None
        headers: dict[str, str] = {}
        if payload is not None:
            request_data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        http_request = urllib_request.Request(
            url=endpoint,
            data=request_data,
            headers=headers,
            method=method,
        )
        try:
            with urllib_request.urlopen(http_request, timeout=60) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Local TTS runtime `{self.provider_name}` returned HTTP {exc.code}.",
            ) from exc
        except urllib_error.URLError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Unable to reach local TTS runtime `{self.provider_name}`: {exc.reason}",
            ) from exc
        return self._decode_json(raw_body)

    def _build_payload(
        self,
        request: TTSRequest,
        text: str,
        *,
        text_chunks: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "text": text,
            "language": request.language,
            "model": request.model_name,
            "voice_preset": request.voice_preset,
            "speaker_id": request.speaker_id,
            "voice_profile_id": request.voice_profile_id,
            "reference_audio_path": request.reference_audio_path,
            "style_hint": request.style_hint,
            "profile_id": request.profile_id,
            "runtime_id": request.runtime_id,
            "profile_kind": request.profile_kind,
            "asset_dir": request.asset_dir,
            "reference_text": request.reference_text,
        }
        if text_chunks:
            payload["text_chunks"] = list(text_chunks)
        return {key: value for key, value in payload.items() if value is not None}

    def _decode_json(self, raw_body: str) -> dict[str, object]:
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Local TTS runtime `{self.provider_name}` returned invalid JSON.",
            ) from exc
        if not isinstance(parsed, dict):
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Local TTS runtime `{self.provider_name}` returned an invalid payload.",
            )
        return parsed

    def _extract_audio_bytes(self, payload: dict[str, object]) -> bytes:
        audio_base64 = self._extract_string(payload, "audio_base64")
        if audio_base64 is None:
            output = payload.get("output")
            if isinstance(output, dict):
                audio_base64 = self._extract_string(output, "audio_base64")
        if audio_base64 is None:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Local TTS runtime `{self.provider_name}` did not include `audio_base64`.",
            )
        try:
            return base64.b64decode(audio_base64)
        except ValueError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Local TTS runtime `{self.provider_name}` returned invalid base64 audio.",
            ) from exc

    def _extract_string(self, payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_int(self, payload: dict[str, object], key: str) -> int | None:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        return None


class GPTSoVITSv2TTSProvider:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.provider_name = "gpt_sovits_v2"
        self.client = GPTSoVITSv2Client(
            tts_url=config.gpt_sovits_v2_url,
            timeout_s=config.gpt_sovits_v2_timeout_s,
        )

    def synthesize(self, request: TTSRequest) -> SynthesizedAudio:
        started_at = monotonic()
        try:
            response = self.client.synthesize(self._build_request(request))
        except RuntimeError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                str(exc),
            ) from exc
        latency_ms = response.latency_ms or int((monotonic() - started_at) * 1000)
        return SynthesizedAudio(
            audio_bytes=response.audio_bytes,
            provider_name=self.provider_name,
            model_name=request.model_name or self.config.tts_model,
            latency_ms=latency_ms,
            container_format=response.media_type,
            voice_preset=request.voice_preset,
        )

    def synthesize_full(self, request: TTSRequest) -> SynthesizedAudio:
        return self.synthesize(request)

    def synthesize_stream(self, request: TTSRequest) -> Iterable[AudioChunkLike]:
        text_chunks = request.text_chunks or (request.text,)
        for index, chunk_text in enumerate(text_chunks):
            chunk_request = replace(request, text=chunk_text, text_chunks=())
            audio = self.synthesize(chunk_request)
            yield AudioChunkLike(
                audio_bytes=audio.audio_bytes,
                provider_name=audio.provider_name,
                model_name=audio.model_name,
                container_format=audio.container_format,
                sample_rate=audio.sample_rate,
                channels=audio.channels,
                sample_width=audio.sample_width,
                sequence_index=index,
                is_final=index == len(text_chunks) - 1,
            )

    def healthcheck(self) -> dict[str, object]:
        return {"status": "external", "url": self.config.gpt_sovits_v2_url}

    def get_profile_state(self, profile_id: str) -> dict[str, object]:
        return {
            "profile_id": profile_id,
            "provider": self.provider_name,
            "status": "external",
        }

    def _build_request(self, request: TTSRequest) -> GPTSoVITSv2Request:
        return GPTSoVITSv2Request(
            text=request.text,
            text_lang=_to_gpt_sovits_lang(self.config.gpt_sovits_v2_text_lang),
            ref_audio_path=(
                request.reference_audio_path
                or self.config.gpt_sovits_v2_ref_audio_path
            ),
            prompt_text=request.reference_text or self.config.gpt_sovits_v2_prompt_text,
            prompt_lang=_to_gpt_sovits_lang(self.config.gpt_sovits_v2_prompt_lang),
            text_split_method=self.config.gpt_sovits_v2_text_split_method,
            batch_size=self.config.gpt_sovits_v2_batch_size,
            media_type=self.config.gpt_sovits_v2_media_type,
            streaming_mode=self.config.gpt_sovits_v2_streaming_mode,
        )


def build_tts_provider(
    config: VoiceConfig,
    *,
    provider_name: str | None = None,
) -> TTSProvider:
    provider_name = (provider_name or config.tts_provider).lower()
    if provider_name == "none":
        return NullTTSProvider()
    if provider_name == "dashscope_tts":
        return DefaultChineseTTSProvider(config)
    if provider_name == "cosyvoice_local":
        return LocalRuntimeTTSProvider(
            config,
            provider_name=provider_name,
            runtime_url=config.primary_tts_runtime_url,
        )
    if provider_name == "gpt_sovits_local":
        return LocalRuntimeTTSProvider(
            config,
            provider_name=provider_name,
            runtime_url=config.clone_tts_runtime_url,
        )
    if provider_name == "gpt_sovits_v2":
        return GPTSoVITSv2TTSProvider(config)
    raise VoicePipelineError(
        VoiceErrorStage.SPEAKING,
        f"Unsupported TTS provider: {provider_name}",
    )


def _to_gpt_sovits_lang(language: str) -> str:
    normalized = language.strip().lower().replace("_", "-")
    if normalized in {"zh-cn", "zh-hans", "zh"}:
        return "zh"
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("ja"):
        return "ja"
    return normalized
