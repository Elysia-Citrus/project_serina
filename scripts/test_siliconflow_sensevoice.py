from __future__ import annotations

from pathlib import Path
import argparse
import json
import mimetypes
import sys
import wave

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.voice.recorder import describe_audio_devices

SILICONFLOW_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"
DEFAULT_API_KEY = "sk-jacpianjalqtwfejsdgnpnvwdbtkowonhqjryolhhoqbdzvb"
DEFAULT_OUTPUT_PATH = Path("artifacts/voice/siliconflow_test_input.wav")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone SiliconFlow SenseVoiceSmall ASR test.",
    )
    parser.add_argument(
        "--file",
        help="Existing audio file to upload. If omitted, the script records one fixed-duration WAV first.",
    )
    parser.add_argument(
        "--record-seconds",
        type=float,
        default=5.0,
        help="Recording duration when --file is not provided.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Sample rate for microphone recording.",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Channel count for microphone recording.",
    )
    parser.add_argument(
        "--input-device",
        help="Microphone device name or numeric index.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List input-capable audio devices and exit.",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="SiliconFlow API key. Defaults to the inline local test key.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="ASR model name.",
    )
    parser.add_argument(
        "--save-audio",
        help=(
            "Where to save the recorded WAV. Defaults to "
            f"{DEFAULT_OUTPUT_PATH.as_posix()} when recording."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_devices:
        print(describe_audio_devices())
        return 0

    if args.file:
        audio_path = Path(args.file).expanduser().resolve()
        if not audio_path.exists():
            print(f"Audio file not found: {audio_path}")
            return 1
    else:
        audio_path = Path(args.save_audio or DEFAULT_OUTPUT_PATH).expanduser().resolve()
        record_wav(
            output_path=audio_path,
            duration_s=max(0.5, args.record_seconds),
            sample_rate=max(8000, args.sample_rate),
            channels=max(1, args.channels),
            input_device=_coerce_device_selector(args.input_device),
        )

    print(f"Uploading audio file: {audio_path}")
    response_payload = transcribe_audio_file(
        audio_path=audio_path,
        api_key=args.api_key,
        model=args.model,
    )
    transcript = extract_transcript(response_payload)

    print("\n=== Response JSON ===")
    print(json.dumps(response_payload, ensure_ascii=False, indent=2))
    print("\n=== Transcript ===")
    print(transcript or "<empty transcript>")
    return 0


def record_wav(
    *,
    output_path: Path,
    duration_s: float,
    sample_rate: int,
    channels: int,
    input_device: str | int | None,
) -> None:
    try:
        import sounddevice as sd  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "sounddevice is required for microphone recording in this test script."
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(duration_s * sample_rate))
    print(
        f"Recording {duration_s:.1f}s from microphone "
        f"(sample_rate={sample_rate}, channels={channels}, device={input_device!r})..."
    )
    recording = sd.rec(
        frame_count,
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        device=input_device,
    )
    sd.wait()

    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(recording.tobytes())

    print(f"Saved recording to: {output_path}")


def transcribe_audio_file(
    *,
    audio_path: Path,
    api_key: str,
    model: str,
) -> dict[str, object]:
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise RuntimeError("requests is required for the SiliconFlow test script.") from exc

    mime_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    with audio_path.open("rb") as audio_file:
        files = {
            "file": (audio_path.name, audio_file, mime_type),
            "model": (None, model),
        }
        response = requests.post(
            SILICONFLOW_URL,
            headers=headers,
            files=files,
            timeout=120,
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text}

    if response.status_code >= 400:
        raise RuntimeError(
            "SiliconFlow request failed with "
            f"HTTP {response.status_code}: "
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    if not isinstance(payload, dict):
        raise RuntimeError("SiliconFlow returned a non-object response.")
    return payload


def extract_transcript(payload: dict[str, object]) -> str:
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


def _coerce_device_selector(raw_value: str | None) -> str | int | None:
    if raw_value is None:
        return None
    stripped = raw_value.strip()
    if not stripped:
        return None
    if stripped.isdigit():
        return int(stripped)
    return stripped


if __name__ == "__main__":
    raise SystemExit(main())
