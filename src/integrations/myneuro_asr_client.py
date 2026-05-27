from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4
import json
import mimetypes


@dataclass(frozen=True)
class MyNeuroASRResponse:
    text: str
    latency_ms: int
    raw_payload: dict[str, object]


class MyNeuroASRClient:
    def __init__(self, *, upload_url: str, timeout_s: float = 120.0) -> None:
        self.upload_url = upload_url
        self.timeout_s = timeout_s

    def transcribe_file(self, audio_path: str | Path) -> MyNeuroASRResponse:
        resolved_audio_path = Path(audio_path)
        boundary = f"----SerinaMyNeuroASR{uuid4().hex}"
        mime_type = mimetypes.guess_type(resolved_audio_path.name)[0] or "audio/wav"
        body = _build_upload_body(
            boundary=boundary,
            field_name="file",
            filename=resolved_audio_path.name,
            mime_type=mime_type,
            file_bytes=resolved_audio_path.read_bytes(),
        )
        request = urllib_request.Request(
            url=self.upload_url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        started_at = monotonic()
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_s) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"my-neuro ASR returned HTTP {exc.code}: {error_body}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Unable to reach my-neuro ASR: {exc.reason}") from exc

        latency_ms = int((monotonic() - started_at) * 1000)
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("my-neuro ASR returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("my-neuro ASR returned an invalid response payload.")

        status = str(payload.get("status", "")).strip().lower()
        text = _extract_text(payload)
        if status and status != "success":
            message = str(payload.get("message") or "my-neuro ASR request failed.")
            raise RuntimeError(message)
        if not text:
            raise RuntimeError("my-neuro ASR returned an empty transcript.")
        return MyNeuroASRResponse(text=text, latency_ms=latency_ms, raw_payload=payload)


def _extract_text(payload: dict[str, object]) -> str:
    for key in ("text", "transcript", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("text", "transcript", "result"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _build_upload_body(
    *,
    boundary: str,
    field_name: str,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
) -> bytes:
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body)

