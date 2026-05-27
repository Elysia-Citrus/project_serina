from __future__ import annotations

from base64 import b64decode
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib import request as urllib_request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.local_runtime_server import build_local_runtime_server
from src.voice.models import TTSRequest
from src.voice.tts import build_tts_provider
from tests.support import TemporaryWorkspace, build_test_config


class LocalRuntimeServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_primary_runtime_serves_health_profile_and_synthesis(self) -> None:
        (self.workspace.root / "voice_profiles.yaml").write_text(
            "\n".join(
                [
                    "profiles:",
                    "  serina_main:",
                    "    id: serina_main",
                    "    provider: cosyvoice_local",
                    "    runtime_id: primary",
                    "    profile_kind: preset",
                    "    model: cosyvoice-local-primary",
                    "    voice_preset: serina_main",
                    "    enabled: true",
                    "    scene_style_hints:",
                    "      default: gentle",
                ]
            ),
            encoding="utf-8",
        )
        (self.workspace.root / "local_tts_runtime.yaml").write_text(
            "\n".join(
                [
                    "runtimes:",
                    "  primary:",
                    "    adapter: debug_wave",
                    "    model_name: cosyvoice-local-primary",
                    "  clone:",
                    "    adapter: unavailable",
                    "    model_name: gpt-sovits-runtime",
                ]
            ),
            encoding="utf-8",
        )

        app_config = build_test_config(self.workspace.db_path)
        voice_config = replace(
            app_config.voice,
            tts_provider="cosyvoice_local",
            default_voice_profile_id="serina_main",
            voice_profiles_path="voice_profiles.yaml",
            primary_tts_runtime_url="http://127.0.0.1:0",
            clone_tts_runtime_url="http://127.0.0.1:51772",
        )
        app_config = replace(
            app_config,
            voice=voice_config,
            config_dir=self.workspace.root,
        )

        server = build_local_runtime_server(app_config, runtime_id="primary")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        try:
            health = self._read_json(f"{base_url}/healthz")
            self.assertEqual(health["status"], "ok")
            self.assertEqual(health["runtime_id"], "primary")

            profile = self._read_json(f"{base_url}/profiles/serina_main")
            self.assertEqual(profile["status"], "ready")
            self.assertEqual(profile["profile_id"], "serina_main")

            full = self._post_json(
                f"{base_url}/synthesize",
                {
                    "text": "Bring the local sidecar online first.",
                    "profile_id": "serina_main",
                    "runtime_id": "primary",
                    "model": "cosyvoice-local-primary",
                },
            )
            self.assertEqual(full["container_format"], "wav")
            self.assertGreater(len(b64decode(full["audio_base64"])), 100)

            provider = build_tts_provider(
                replace(
                    voice_config,
                    primary_tts_runtime_url=base_url,
                ),
                provider_name="cosyvoice_local",
            )
            self.assertEqual(provider.healthcheck()["status"], "ok")  # type: ignore[attr-defined]
            synthesized_audio = provider.synthesize(  # type: ignore[attr-defined]
                TTSRequest(
                    text="Client compatibility check.",
                    model_name="cosyvoice-local-primary",
                    profile_id="serina_main",
                    runtime_id="primary",
                )
            )
            self.assertEqual(synthesized_audio.container_format, "wav")
            self.assertGreater(len(synthesized_audio.audio_bytes), 100)

            stream_events = self._post_ndjson(
                f"{base_url}/synthesize-stream",
                {
                    "text": "First sentence. Second sentence.",
                    "text_chunks": ["First sentence.", "Second sentence."],
                    "profile_id": "serina_main",
                    "runtime_id": "primary",
                },
            )
            self.assertEqual(stream_events[-1]["event"], "done")
            self.assertEqual(stream_events[0]["event"], "audio_chunk")
            self.assertEqual(stream_events[1]["sequence_index"], 1)
        finally:
            server.shutdown()
            thread.join(timeout=2)

    def _read_json(self, url: str) -> dict[str, object]:
        with urllib_request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib_request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_ndjson(self, url: str, payload: dict[str, object]) -> list[dict[str, object]]:
        request = urllib_request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(request, timeout=10) as response:
            return [
                json.loads(line.decode("utf-8"))
                for line in response.readlines()
                if line.strip()
            ]


if __name__ == "__main__":
    unittest.main()
