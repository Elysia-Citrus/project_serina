from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_app_config
from src.voice.synthesis import build_speech_synthesis_service


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect local voice runtime health and registered profile state.",
    )
    parser.add_argument(
        "--profile-id",
        help="Profile id to inspect. Defaults to the configured default voice profile.",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Ping all configured local TTS runtimes before checking the profile state.",
    )
    args = parser.parse_args()

    app_config = load_app_config()
    speech_service = build_speech_synthesis_service(app_config)

    if args.warmup:
        warmup_status = speech_service.warmup_local_runtimes()
        for provider_name, status in warmup_status.items():
            print(f"warmup {provider_name}={status}")

    profile_id = args.profile_id or app_config.voice.default_voice_profile_id
    if not profile_id:
        print("No default voice profile is configured.")
        return 1

    profile_state = speech_service.describe_profile_state(profile_id)
    for key, value in profile_state.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
