from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from time import monotonic
from typing import Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4
import json
import mimetypes
import wave

from src.config.loader import VoiceConfig
from src.integrations.myneuro_asr_client import MyNeuroASRClient
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.models import ASRResult, RecordedAudio


class ASRProvider(Protocol):
    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        ...


class DefaultChineseASRProvider:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config

    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        if not self.config.asr_api_key:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                f"Missing ASR API key. Set {self.config.asr_api_key_env} before using voice mode.",
            )

        try:
            import dashscope  # type: ignore
            from dashscope.audio.asr import Recognition  # type: ignore
        except ModuleNotFoundError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "dashscope is required for the default ASR provider. Install it before using voice mode.",
            ) from exc

        dashscope.api_key = self.config.asr_api_key
        if hasattr(dashscope, "base_http_api_url"):
            dashscope.base_http_api_url = self.config.asr_base_url

        started_at = monotonic()
        recognizer = Recognition(
            model=self.config.asr_model,
            format=recorded_audio.container_format,
            sample_rate=recorded_audio.sample_rate,
            language_hints=["zh", "en"] if language.lower().startswith("zh") else [language],
        )
        result = recognizer.call(recorded_audio.file_path)
        latency_ms = int((monotonic() - started_at) * 1000)

        status_code = getattr(result, "status_code", None)
        if status_code not in {HTTPStatus.OK, 200}:
            message = getattr(result, "message", None) or "ASR request failed."
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                str(message),
            )

        transcript = self._extract_text(result)
        return ASRResult(
            text=transcript,
            provider_name=self.config.asr_provider,
            model_name=self.config.asr_model,
            latency_ms=latency_ms,
            raw_result=result,
        )

    def _extract_text(self, result: object) -> str:
        transcript = ""

        if hasattr(result, "get_sentence"):
            sentence = result.get_sentence()  # type: ignore[attr-defined]
            if isinstance(sentence, list):
                transcript = "".join(
                    str(item.get("text", "")).strip()
                    for item in sentence
                    if isinstance(item, dict)
                ).strip()

        if not transcript and hasattr(result, "output"):
            output = getattr(result, "output")
            if isinstance(output, dict):
                sentence = output.get("sentence")
                if isinstance(sentence, list):
                    transcript = "".join(
                        str(item.get("text", "")).strip()
                        for item in sentence
                        if isinstance(item, dict)
                    ).strip()

        if not transcript:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "ASR returned an empty transcript.",
            )
        return transcript


class SiliconFlowSenseVoiceASRProvider:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config

    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        if not self.config.asr_api_key:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                f"Missing ASR API key. Set {self.config.asr_api_key_env} before using voice mode.",
            )

        started_at = monotonic()
        payload = self._post_transcription_request(recorded_audio.path)
        latency_ms = int((monotonic() - started_at) * 1000)
        transcript = self._extract_text(payload)
        if not transcript:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "SiliconFlow returned an empty transcript.",
            )
        return ASRResult(
            text=transcript,
            provider_name=self.config.asr_provider,
            model_name=self.config.asr_model,
            latency_ms=latency_ms,
            raw_result=payload,
        )

    def _post_transcription_request(self, audio_path: Path) -> dict[str, object]:
        endpoint = self.config.asr_base_url.rstrip("/") + "/audio/transcriptions"
        boundary = f"----SerinaBoundary{uuid4().hex}"
        mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        audio_bytes = audio_path.read_bytes()
        request_body = _build_multipart_body(
            boundary=boundary,
            model_name=self.config.asr_model,
            filename=audio_path.name,
            mime_type=mime_type,
            file_bytes=audio_bytes,
        )
        request = urllib_request.Request(
            url=endpoint,
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.config.asr_api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )

        try:
            with urllib_request.urlopen(request, timeout=120) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                f"SiliconFlow ASR returned HTTP {exc.code}: {error_body}",
            ) from exc
        except urllib_error.URLError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                f"Unable to reach SiliconFlow ASR: {exc.reason}",
            ) from exc

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "SiliconFlow ASR returned invalid JSON.",
            ) from exc

        if not isinstance(payload, dict):
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "SiliconFlow ASR returned an invalid response payload.",
            )
        return payload

    def _extract_text(self, payload: dict[str, object]) -> str:
        return _extract_siliconflow_transcript(payload)


class LocalSherpaSenseVoiceASRProvider:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._recognizer: object | None = None

    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        if language.lower() != "zh-cn":
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "The local sherpa-onnx SenseVoice adapter currently only supports zh-CN.",
            )

        started_at = monotonic()
        recognizer, np = self._get_runtime()
        samples, sample_rate = _load_wav_as_float32(recorded_audio.path, np=np)
        try:
            stream = recognizer.create_stream()
            stream.accept_waveform(sample_rate, samples)
            recognizer.decode_stream(stream)
            raw_result = getattr(stream, "result", None)
        except Exception as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                f"Local sherpa-onnx decoding failed: {exc}",
            ) from exc

        transcript = _extract_sherpa_text(raw_result)
        if not transcript:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "Local sherpa-onnx ASR returned an empty transcript.",
            )

        return ASRResult(
            text=transcript,
            provider_name=self.config.asr_provider,
            model_name=self.config.asr_model,
            latency_ms=int((monotonic() - started_at) * 1000),
            raw_result=raw_result,
        )

    def _get_runtime(self) -> tuple[object, object]:
        if self.config.asr_compute_device not in {"cpu", "auto"}:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                (
                    "The current local sherpa-onnx adapter only supports "
                    "`asr_compute_device: cpu` or `auto`."
                ),
            )

        try:
            import numpy as np  # type: ignore
        except ModuleNotFoundError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "numpy is required for the local sherpa-onnx ASR adapter.",
            ) from exc

        try:
            import sherpa_onnx  # type: ignore
        except ModuleNotFoundError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                "sherpa-onnx is required for `asr_provider: sherpa_onnx_sensevoice`.",
            ) from exc

        if self._recognizer is None:
            model_path, tokens_path = _resolve_sense_voice_model_paths(self.config.asr_model)
            offline_recognizer = getattr(sherpa_onnx, "OfflineRecognizer", None)
            if offline_recognizer is None or not hasattr(offline_recognizer, "from_sense_voice"):
                raise VoicePipelineError(
                    VoiceErrorStage.TRANSCRIBING,
                    "The installed sherpa-onnx package does not expose OfflineRecognizer.from_sense_voice.",
                )
            try:
                self._recognizer = offline_recognizer.from_sense_voice(
                    model=str(model_path),
                    tokens=str(tokens_path),
                    use_itn=True,
                    debug=False,
                )
            except Exception as exc:
                raise VoicePipelineError(
                    VoiceErrorStage.TRANSCRIBING,
                    f"Failed to initialize local sherpa-onnx SenseVoice: {exc}",
                ) from exc
        return self._recognizer, np


class MyNeuroASRProvider:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.client = MyNeuroASRClient(
            upload_url=config.myneuro_asr_url,
            timeout_s=config.myneuro_asr_timeout_s,
        )

    def transcribe(self, recorded_audio: RecordedAudio, *, language: str) -> ASRResult:
        started_at = monotonic()
        try:
            response = self.client.transcribe_file(recorded_audio.path)
        except VoicePipelineError:
            raise
        except RuntimeError as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                (
                    f"my-neuro ASR request failed "
                    f"({self.config.myneuro_asr_url}): {exc}"
                ),
            ) from exc
        except Exception as exc:
            raise VoicePipelineError(
                VoiceErrorStage.TRANSCRIBING,
                (
                    f"my-neuro ASR request failed "
                    f"({self.config.myneuro_asr_url}, {type(exc).__name__}): {exc}"
                ),
            ) from exc
        latency_ms = response.latency_ms or int((monotonic() - started_at) * 1000)
        return ASRResult(
            text=response.text,
            provider_name=self.config.asr_provider,
            model_name=self.config.asr_model,
            latency_ms=latency_ms,
            raw_result=response.raw_payload,
        )


def build_asr_provider(config: VoiceConfig) -> ASRProvider:
    provider_name = config.asr_provider.lower()
    if provider_name in {"myneuro_asr", "my-neuro-asr", "myneuro"}:
        return MyNeuroASRProvider(config)
    if provider_name == "dashscope":
        return DefaultChineseASRProvider(config)
    if provider_name in {"siliconflow", "siliconflow_sensevoice"}:
        return SiliconFlowSenseVoiceASRProvider(config)
    if provider_name in {
        "sherpa_onnx_sensevoice",
        "local_sherpa_sensevoice",
        "sherpa_sensevoice",
    }:
        return LocalSherpaSenseVoiceASRProvider(config)
    raise VoicePipelineError(
        VoiceErrorStage.TRANSCRIBING,
        f"Unsupported ASR provider: {config.asr_provider}",
    )


def _extract_siliconflow_transcript(payload: dict[str, object]) -> str:
    for key in ("text", "transcript"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("text", "transcript"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("text", "transcript"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def _build_multipart_body(
    *,
    boundary: str,
    model_name: str,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
) -> bytes:
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
    body.extend(model_name.encode("utf-8"))
    body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body)


def _resolve_sense_voice_model_paths(raw_model: str) -> tuple[Path, Path]:
    candidate = Path(raw_model).expanduser()
    if not candidate.exists():
        bundled = Path("artifacts") / "voice" / "models" / raw_model
        if bundled.exists():
            candidate = bundled

    if candidate.is_dir():
        model_path = _first_existing_path(
            candidate / "model.int8.onnx",
            candidate / "model.onnx",
            candidate / "sense-voice.onnx",
        )
        tokens_path = candidate / "tokens.txt"
    else:
        model_path = candidate
        tokens_path = candidate.with_name("tokens.txt")

    if model_path is None or not model_path.exists():
        raise VoicePipelineError(
            VoiceErrorStage.TRANSCRIBING,
            (
                "Unable to locate the local SenseVoice model. Set `asr_model` to an ONNX file "
                "or to a directory containing `model.int8.onnx` and `tokens.txt`."
            ),
        )
    if not tokens_path.exists():
        raise VoicePipelineError(
            VoiceErrorStage.TRANSCRIBING,
            f"Unable to locate tokens.txt for the local SenseVoice model: {tokens_path}",
        )
    return model_path, tokens_path


def _first_existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _load_wav_as_float32(audio_path: Path, *, np) -> tuple[object, int]:  # type: ignore[no-untyped-def]
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            if wav_file.getsampwidth() != 2:
                raise VoicePipelineError(
                    VoiceErrorStage.TRANSCRIBING,
                    "Local sherpa-onnx decoding currently expects 16-bit PCM WAV input.",
                )
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except wave.Error as exc:
        raise VoicePipelineError(
            VoiceErrorStage.TRANSCRIBING,
            f"Unable to read WAV input for local ASR: {exc}",
        ) from exc

    samples = np.frombuffer(frames, dtype=np.int16)
    if channels > 1:
        samples = _select_best_mono_channel(samples, channels=channels, np=np)
    return samples.astype(np.float32) / 32768.0, sample_rate


def _select_best_mono_channel(samples, *, channels: int, np):  # type: ignore[no-untyped-def]
    matrix = samples.reshape(-1, channels).astype(np.float32)
    if channels <= 1:
        return matrix[:, 0]

    channel_rms = np.sqrt(np.mean(np.square(matrix), axis=0))
    best_channel_index = int(np.argmax(channel_rms))
    best_channel_rms = float(channel_rms[best_channel_index])
    mean_channel_rms = float(np.mean(channel_rms))

    if mean_channel_rms <= 0:
        return matrix[:, best_channel_index]

    # Prefer the hottest channel when one side clearly carries the voice signal.
    if best_channel_rms >= mean_channel_rms * 1.35:
        return matrix[:, best_channel_index]

    return np.mean(matrix, axis=1)


def _extract_sherpa_text(result: object | None) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if hasattr(result, "text"):
        value = getattr(result, "text")
        if isinstance(value, str):
            return value.strip()
    if isinstance(result, dict):
        for key in ("text", "result", "transcript"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""
