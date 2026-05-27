from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from urllib import error as urllib_error
from urllib import request as urllib_request
import json


@dataclass(frozen=True)
class GPTSoVITSv2Request:
    text: str
    text_lang: str
    ref_audio_path: str
    prompt_text: str
    prompt_lang: str
    text_split_method: str = "cut5"
    batch_size: int = 1
    media_type: str = "wav"
    streaming_mode: bool | int = False


@dataclass(frozen=True)
class GPTSoVITSv2Response:
    audio_bytes: bytes
    latency_ms: int
    media_type: str = "wav"


class GPTSoVITSv2Client:
    def __init__(self, *, tts_url: str, timeout_s: float = 120.0) -> None:
        self.tts_url = tts_url
        self.timeout_s = timeout_s

    def synthesize(self, request: GPTSoVITSv2Request) -> GPTSoVITSv2Response:
        payload = {
            "text": request.text,
            "text_lang": request.text_lang,
            "ref_audio_path": request.ref_audio_path,
            "prompt_text": request.prompt_text,
            "prompt_lang": request.prompt_lang,
            "text_split_method": request.text_split_method,
            "batch_size": request.batch_size,
            "media_type": request.media_type,
            "streaming_mode": request.streaming_mode,
        }
        http_request = urllib_request.Request(
            url=self.tts_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started_at = monotonic()
        try:
            with urllib_request.urlopen(http_request, timeout=self.timeout_s) as response:
                content_type = response.headers.get("Content-Type", "")
                response_bytes = response.read()
        except urllib_error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GPT-SoVITS v2 returned HTTP {exc.code}: {error_body}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Unable to reach GPT-SoVITS v2: {exc.reason}") from exc

        if "application/json" in content_type.lower():
            try:
                payload = json.loads(response_bytes.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError("GPT-SoVITS v2 returned invalid JSON.") from exc
            message = payload.get("message") if isinstance(payload, dict) else None
            raise RuntimeError(str(message or "GPT-SoVITS v2 did not return audio."))

        return GPTSoVITSv2Response(
            audio_bytes=response_bytes,
            latency_ms=int((monotonic() - started_at) * 1000),
            media_type=request.media_type,
        )

