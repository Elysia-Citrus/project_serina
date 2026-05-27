from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import argparse
import sys
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_app_config
from src.voice.asr import build_asr_provider
from src.voice.errors import VoicePipelineError
from src.voice.recorder import BlockingWavRecorder


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture short probe clips from candidate microphones and print signal stats.",
    )
    parser.add_argument(
        "--devices",
        type=str,
        default="",
        help="Comma-separated device ids to probe. Defaults to likely microphone devices.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=2.5,
        help="Recording duration per device.",
    )
    args = parser.parse_args()

    try:
        import sounddevice as sd  # type: ignore
        import numpy as np  # type: ignore
    except ModuleNotFoundError as exc:
        print(f"[probe] dependency error: {exc}")
        return 1

    config = load_app_config().voice
    device_ids = _resolve_candidate_devices(sd=sd, raw_devices=args.devices)
    if not device_ids:
        print("[probe] No input devices available.")
        return 1

    probe_dir = PROJECT_ROOT / "artifacts" / "voice" / "tmp" / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    print("[probe] Candidate devices:")
    for device_id in device_ids:
        info = sd.query_devices(device_id, "input")
        print(
            f"  - [{device_id}] {info['name']} | in={info['max_input_channels']} | "
            f"default_sr={int(float(info['default_samplerate']))}"
        )

    asr_provider = None
    try:
        asr_provider = build_asr_provider(config)
    except Exception:
        asr_provider = None

    print()
    print("[probe] Speak the same short Chinese sentence for each device.")
    print("[probe] Suggested phrase: 你好，今天帮我做个麦克风测试。")
    print()

    results: list[dict[str, object]] = []
    for device_id in device_ids:
        info = sd.query_devices(device_id, "input")
        channels = 1 if int(info["max_input_channels"]) == 1 else 2
        probe_config = replace(
            config,
            input_device=device_id,
            channels=channels,
            recording_mode="fixed_duration",
            fixed_record_seconds=max(0.5, float(args.seconds)),
            temp_audio_dir=str(probe_dir),
            debug_save_input_audio=True,
        )
        print(
            f"[probe] Ready for [{device_id}] {info['name']} "
            f"(channels={channels}, target_sr={probe_config.sample_rate}). Press Enter to record..."
        )
        input()

        recorder = BlockingWavRecorder(probe_config)
        try:
            recorded_audio = recorder.capture_to_wav()
        except VoicePipelineError as exc:
            print(f"[probe] capture failed: {exc}")
            print()
            continue

        stats = _analyze_wav(Path(recorded_audio.file_path), np=np)
        transcript = ""
        if asr_provider is not None:
            try:
                transcript = asr_provider.transcribe(
                    recorded_audio,
                    language=config.language,
                ).text
            except Exception as exc:
                transcript = f"<asr_failed: {exc}>"

        result = {
            "device_id": device_id,
            "name": str(info["name"]),
            "path": recorded_audio.file_path,
            "overall_rms": stats["overall_rms"],
            "peak": stats["peak"],
            "channels": stats["channels"],
            "channel_rms": stats["channel_rms"],
            "transcript": transcript,
        }
        results.append(result)

        print(f"[probe] saved: {recorded_audio.file_path}")
        print(f"[probe] overall_rms={stats['overall_rms']:.1f} peak={stats['peak']}")
        for index, rms_value in enumerate(stats["channel_rms"]):
            print(f"[probe] ch{index}_rms={rms_value:.1f}")
        if transcript:
            print(f"[probe] transcript={transcript}")
        print()

    if not results:
        print("[probe] No successful captures.")
        return 1

    best = _recommend_result(results)
    print("[probe] Recommendation:")
    print(
        f"  use input_device={best['device_id']} "
        f"({best['name']}); clip={best['path']}"
    )
    if best["transcript"]:
        print(f"  transcript={best['transcript']}")
    return 0


def _resolve_candidate_devices(*, sd, raw_devices: str) -> list[int]:  # type: ignore[no-untyped-def]
    if raw_devices.strip():
        return [int(part.strip()) for part in raw_devices.split(",") if part.strip()]

    device_ids: list[int] = []
    default_input = None
    if hasattr(sd, "default") and hasattr(sd.default, "device"):
        device_pair = sd.default.device
        if isinstance(device_pair, (list, tuple)) and device_pair:
            default_input = int(device_pair[0])

    for index, info in enumerate(sd.query_devices()):
        if int(info.get("max_input_channels", 0) or 0) <= 0:
            continue
        name = str(info.get("name", ""))
        if any(skip in name for skip in ("Steam Streaming", "Hands-Free", "Input ()")):
            continue
        if "麦克风" not in name and "Microphone" not in name:
            continue
        if index == default_input:
            device_ids.insert(0, index)
        else:
            device_ids.append(index)

    deduped: list[int] = []
    for device_id in device_ids:
        if device_id not in deduped:
            deduped.append(device_id)
    return deduped[:6]


def _analyze_wav(path: Path, *, np) -> dict[str, object]:  # type: ignore[no-untyped-def]
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        frames = wav_file.readframes(wav_file.getnframes())

    samples = np.frombuffer(frames, dtype=np.int16)
    if channels <= 1:
        matrix = samples.reshape(-1, 1).astype(np.float32)
    else:
        matrix = samples.reshape(-1, channels).astype(np.float32)

    channel_rms = np.sqrt(np.mean(np.square(matrix), axis=0))
    overall_rms = float(np.sqrt(np.mean(np.square(matrix))))
    peak = int(np.max(np.abs(matrix))) if matrix.size else 0
    return {
        "channels": channels,
        "channel_rms": [float(value) for value in channel_rms],
        "overall_rms": overall_rms,
        "peak": peak,
    }


def _recommend_result(results: list[dict[str, object]]) -> dict[str, object]:
    def score(result: dict[str, object]) -> tuple[int, float]:
        transcript = str(result.get("transcript") or "")
        chinese_chars = sum(1 for char in transcript if "\u4e00" <= char <= "\u9fff")
        overall_rms = float(result.get("overall_rms") or 0.0)
        return (chinese_chars, overall_rms)

    return max(results, key=score)


if __name__ == "__main__":
    raise SystemExit(main())
