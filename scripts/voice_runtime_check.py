from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_app_config
from src.voice.asr import LocalSherpaSenseVoiceASRProvider
from src.voice.models import RecordedAudio
from src.voice.recorder import describe_audio_devices


def main() -> int:
    print(f"python={sys.version.split()[0]}")
    try:
        import sherpa_onnx  # type: ignore
        import sounddevice  # type: ignore
        import numpy  # type: ignore
    except Exception as exc:
        print(f"dependency_check=failed error={exc}")
        return 1

    print(f"sherpa_onnx={sherpa_onnx.__version__}")
    print(f"numpy={numpy.__version__}")
    print("sounddevice=ok")

    config = load_app_config().voice
    print(f"voice_recording_mode={config.recording_mode}")
    print(f"voice_input_device={config.input_device!r}")
    print(f"voice_asr_provider={config.asr_provider}")
    print(f"voice_asr_model={config.asr_model}")

    try:
        print(describe_audio_devices())
    except Exception as exc:
        print(f"device_list=failed error={exc}")

    if config.asr_provider == "sherpa_onnx_sensevoice":
        audio_path = (
            PROJECT_ROOT
            / "artifacts"
            / "voice"
            / "models"
            / "sensevoice-small-int8"
            / "test_wavs"
            / "zh.wav"
        )
        if not audio_path.exists():
            print(f"model_smoke=skipped missing={audio_path}")
            return 0

        provider = LocalSherpaSenseVoiceASRProvider(
            replace(
                config,
                asr_provider="sherpa_onnx_sensevoice",
                asr_model=config.asr_model,
                asr_compute_device="cpu",
            )
        )
        result = provider.transcribe(
            RecordedAudio(
                file_path=str(audio_path),
                sample_rate=16000,
                channels=1,
                duration_ms=0,
                frame_count=0,
            ),
            language="zh-CN",
        )
        print(f"model_smoke=ok transcript={result.text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
