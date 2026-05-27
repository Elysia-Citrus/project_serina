from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.loader import load_app_config
from src.voice.local_runtime_server import build_local_runtime_server


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the localhost-only local TTS sidecar for the selected runtime.",
    )
    parser.add_argument(
        "--runtime",
        choices=("primary", "clone"),
        required=True,
        help="Which runtime to serve.",
    )
    args = parser.parse_args()

    app_config = load_app_config()
    server = build_local_runtime_server(app_config, runtime_id=args.runtime)
    host, port = server.server_address
    print(f"local_tts_runtime={args.runtime} listening_on=http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("local_tts_runtime=stopped")
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
