from __future__ import annotations

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.myneuro_asr_client import MyNeuroASRClient
from src.integrations.myneuro_gpt_sovits_v2_client import GPTSoVITSv2Client, GPTSoVITSv2Request
from src.voice.models import TTSRequest
from src.voice.tts import GPTSoVITSv2TTSProvider
from tests.support import TemporaryWorkspace, build_test_config


class _ServerHarness:
    def __init__(self, handler_class: type[BaseHTTPRequestHandler]) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


class MyNeuroASRHandler(BaseHTTPRequestHandler):
    request_path = ""
    request_body = b""

    def do_POST(self) -> None:  # noqa: N802
        type(self).request_path = self.path
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_body = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "success", "text": "hello"}).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return None


class GPTSoVITSHandler(BaseHTTPRequestHandler):
    request_path = ""
    payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802
        type(self).request_path = self.path
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        type(self).payload = json.loads(raw_body.decode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.end_headers()
        self.wfile.write(b"RIFFfakewav")

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return None


class MyNeuroIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_myneuro_asr_uploads_audio_to_expected_endpoint(self) -> None:
        server = _ServerHarness(MyNeuroASRHandler)
        try:
            audio_path = self.workspace.root / "input.wav"
            audio_path.write_bytes(b"RIFFfakewav")
            client = MyNeuroASRClient(
                upload_url=server.base_url + "/v1/upload_audio",
                timeout_s=5,
            )

            result = client.transcribe_file(audio_path)

            self.assertEqual(result.text, "hello")
            self.assertEqual(MyNeuroASRHandler.request_path, "/v1/upload_audio")
            self.assertIn(b'name="file"; filename="input.wav"', MyNeuroASRHandler.request_body)
            self.assertIn(b"RIFFfakewav", MyNeuroASRHandler.request_body)
        finally:
            server.close()

    def test_gpt_sovits_v2_posts_expected_payload(self) -> None:
        server = _ServerHarness(GPTSoVITSHandler)
        try:
            client = GPTSoVITSv2Client(tts_url=server.base_url + "/tts", timeout_s=5)

            result = client.synthesize(
                GPTSoVITSv2Request(
                    text="你好",
                    text_lang="zh",
                    ref_audio_path="role_voice_api/neuro/01.wav",
                    prompt_text="reference text",
                    prompt_lang="en",
                    streaming_mode=True,
                )
            )

            self.assertEqual(result.audio_bytes, b"RIFFfakewav")
            self.assertEqual(GPTSoVITSHandler.request_path, "/tts")
            self.assertEqual(GPTSoVITSHandler.payload["text"], "你好")
            self.assertEqual(GPTSoVITSHandler.payload["text_lang"], "zh")
            self.assertEqual(
                GPTSoVITSHandler.payload["ref_audio_path"],
                "role_voice_api/neuro/01.wav",
            )
            self.assertEqual(GPTSoVITSHandler.payload["prompt_text"], "reference text")
            self.assertEqual(GPTSoVITSHandler.payload["prompt_lang"], "en")
            self.assertTrue(GPTSoVITSHandler.payload["streaming_mode"])
        finally:
            server.close()

    def test_tts_provider_uses_configured_v2_defaults(self) -> None:
        server = _ServerHarness(GPTSoVITSHandler)
        try:
            config = replace(
                build_test_config(self.workspace.db_path).voice,
                tts_provider="gpt_sovits_v2",
                gpt_sovits_v2_url=server.base_url + "/tts",
                gpt_sovits_v2_ref_audio_path="role_voice_api/neuro/01.wav",
                gpt_sovits_v2_prompt_text="reference text",
                gpt_sovits_v2_text_lang="zh",
                gpt_sovits_v2_prompt_lang="en",
            )
            provider = GPTSoVITSv2TTSProvider(config)

            result = provider.synthesize(TTSRequest(text="你好", language="zh-CN"))

            self.assertEqual(result.audio_bytes, b"RIFFfakewav")
            self.assertEqual(result.provider_name, "gpt_sovits_v2")
            self.assertEqual(GPTSoVITSHandler.payload["text"], "你好")
            self.assertEqual(
                GPTSoVITSHandler.payload["ref_audio_path"],
                "role_voice_api/neuro/01.wav",
            )
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
