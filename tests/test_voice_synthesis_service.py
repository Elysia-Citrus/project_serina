from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.voice.chunking import SpeechChunker
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.models import AudioChunkLike, SynthesizedAudio
from src.voice.profiles import (
    LEGACY_VOICE_PROFILE_ID,
    VoiceProfileRegistry,
    load_voice_profile_registry,
)
from src.voice.speech_render import SpeechScriptRenderer
from src.voice.synthesis import SpeechSynthesisService
from tests.support import TemporaryWorkspace, build_test_config


class _Provider:
    def __init__(self) -> None:
        self.requests = []

    def synthesize(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return SynthesizedAudio(
            audio_bytes=b"RIFF",
            provider_name="mock-tts",
            model_name=request.model_name or "mock-model",
            latency_ms=42,
            voice_preset=request.voice_preset,
        )


class _LocalProvider(_Provider):
    def __init__(self) -> None:
        super().__init__()
        self.stream_requests = []

    def synthesize_stream(self, request):  # type: ignore[no-untyped-def]
        self.stream_requests.append(request)
        chunks = request.text_chunks or (request.text,)
        for index, _chunk_text in enumerate(chunks):
            yield AudioChunkLike(
                audio_bytes=b"RIFF",
                provider_name="cosyvoice_local",
                model_name=request.model_name or "mock-model",
                sequence_index=index,
                is_final=index == len(chunks) - 1,
            )

    def healthcheck(self):  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    def get_profile_state(self, profile_id: str):  # type: ignore[no-untyped-def]
        return {"profile_id": profile_id, "status": "ready"}


class VoiceSynthesisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = TemporaryWorkspace()

    def tearDown(self) -> None:
        self.workspace.cleanup()

    def test_renderer_strips_stage_directions_and_command_lines(self) -> None:
        renderer = SpeechScriptRenderer()

        result = renderer.render(
            "（lowering voice）\n/memory list\nTeacher......slow down！！",
            scene="comfort",
        )

        self.assertEqual(result.style_id, "comfort")
        self.assertEqual(result.speech_text, "Teacher…slow down！")
        self.assertIn("strip_stage_directions", result.applied_rules)
        self.assertIn("strip_command_lines", result.applied_rules)
        self.assertIn("compress_punctuation", result.applied_rules)

    def test_voice_profile_registry_loads_nested_mapping(self) -> None:
        registry_path = self._write_registry(
            [
                "profiles:",
                "  serina_main:",
                "    id: serina_main",
                "    provider: cosyvoice_local",
                "    runtime_id: primary",
                "    profile_kind: preset",
                "    model: cosyvoice-local-primary",
                "    voice_preset: serina_main",
                "    speaker_id: speaker-a",
                "    voice_profile_id: clone-a",
                "    reference_audio_path: refs/serina.wav",
                "    enabled: true",
                "    scene_style_hints:",
                "      default: gentle",
                "      comfort: warm",
            ]
        )

        registry = load_voice_profile_registry(registry_path)
        profile = registry.get("serina_main")

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.provider, "cosyvoice_local")
        self.assertEqual(profile.runtime_id, "primary")
        self.assertEqual(profile.profile_kind, "preset")
        self.assertEqual(profile.scene_style_hints["comfort"], "warm")
        self.assertTrue(profile.reference_audio_path.endswith("refs\\serina.wav"))

    def test_synthesis_service_uses_default_profile_and_style_hint(self) -> None:
        provider = _Provider()
        registry = load_voice_profile_registry(
            self._write_registry(
                [
                    "profiles:",
                    "  serina_main:",
                    "    id: serina_main",
                    "    provider: dashscope_tts",
                    "    model: cosyvoice-v3-flash",
                    "    voice_preset: longanyang",
                    "    speaker_id: speaker-a",
                    "    voice_profile_id: clone-a",
                    "    reference_audio_path: refs/serina.wav",
                    "    enabled: true",
                    "    scene_style_hints:",
                    "      default: gentle",
                    "      comfort: warm",
                    "      discussion: thoughtful",
                    "      correction: steady",
                ]
            )
        )

        app_config = build_test_config(self.workspace.db_path)
        voice_config = replace(
            app_config.voice,
            default_voice_profile_id="serina_main",
            tts_provider="dashscope_tts",
        )
        service = SpeechSynthesisService(
            config=voice_config,
            profile_registry=registry,
            renderer=SpeechScriptRenderer(),
            chunker=SpeechChunker(),
            providers={"dashscope_tts": provider},
        )

        result = service.synthesize_reply(
            "（softly）Teacher......we can take this slowly.",
            scene="comfort",
        )

        self.assertEqual(result.voice_profile_id, "serina_main")
        self.assertEqual(result.style_id, "comfort")
        self.assertEqual(result.speech_text, "Teacher…we can take this slowly.")
        request = provider.requests[0]
        self.assertEqual(request.model_name, "cosyvoice-v3-flash")
        self.assertEqual(request.voice_preset, "longanyang")
        self.assertEqual(request.speaker_id, "speaker-a")
        self.assertEqual(request.voice_profile_id, "clone-a")
        self.assertEqual(request.style_hint, "warm")
        self.assertTrue(request.reference_audio_path.endswith("refs\\serina.wav"))

    def test_synthesis_service_falls_back_to_legacy_config_without_profile(self) -> None:
        provider = _Provider()
        app_config = build_test_config(self.workspace.db_path)
        voice_config = replace(
            app_config.voice,
            default_voice_profile_id=None,
            tts_provider="dashscope_tts",
            tts_model="legacy-model",
            tts_voice_preset="legacy-voice",
        )
        service = SpeechSynthesisService(
            config=voice_config,
            profile_registry=VoiceProfileRegistry.empty(),
            renderer=SpeechScriptRenderer(),
            chunker=SpeechChunker(),
            providers={"dashscope_tts": provider},
        )

        result = service.synthesize_reply("We stay with the legacy voice.", scene="greeting")

        self.assertEqual(result.voice_profile_id, LEGACY_VOICE_PROFILE_ID)
        request = provider.requests[0]
        self.assertEqual(request.model_name, "legacy-model")
        self.assertEqual(request.voice_preset, "legacy-voice")
        self.assertIsNone(request.style_hint)

    def test_synthesis_service_raises_for_missing_default_profile(self) -> None:
        provider = _Provider()
        app_config = build_test_config(self.workspace.db_path)
        voice_config = replace(
            app_config.voice,
            default_voice_profile_id="missing_profile",
            tts_provider="dashscope_tts",
        )
        service = SpeechSynthesisService(
            config=voice_config,
            profile_registry=VoiceProfileRegistry.empty(),
            renderer=SpeechScriptRenderer(),
            chunker=SpeechChunker(),
            providers={"dashscope_tts": provider},
        )

        with self.assertRaises(VoicePipelineError) as ctx:
            service.synthesize_reply("This should fail.", scene="casual_chat")

        self.assertEqual(ctx.exception.stage, VoiceErrorStage.SPEAKING)
        self.assertIn("missing_profile", str(ctx.exception))

    def test_stream_synthesis_routes_local_profile_and_chunks_text(self) -> None:
        provider = _LocalProvider()
        registry = load_voice_profile_registry(
            self._write_registry(
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
            )
        )
        app_config = build_test_config(self.workspace.db_path)
        voice_config = replace(
            app_config.voice,
            default_voice_profile_id="serina_main",
            tts_provider="cosyvoice_local",
            stream_playback_enabled=True,
        )
        service = SpeechSynthesisService(
            config=voice_config,
            profile_registry=registry,
            renderer=SpeechScriptRenderer(),
            chunker=SpeechChunker(max_sentences_per_chunk=2, max_chars_per_chunk=20),
            providers={"cosyvoice_local": provider},
        )

        stream_result = service.synthesize_reply_stream(
            "第一句。第二句！第三句？",
            scene="casual_chat",
        )

        self.assertIsNotNone(stream_result)
        assert stream_result is not None
        self.assertEqual(stream_result.voice_profile_id, "serina_main")
        materialized = list(stream_result.audio_chunks)
        self.assertEqual(len(materialized), 2)
        request = provider.stream_requests[0]
        self.assertEqual(request.profile_id, "serina_main")
        self.assertEqual(request.runtime_id, "primary")
        self.assertEqual(request.text_chunks, ("第一句。第二句！", "第三句？"))

    def test_clone_profile_requires_assets_and_clone_provider(self) -> None:
        provider = _LocalProvider()
        registry = load_voice_profile_registry(
            self._write_registry(
                [
                    "profiles:",
                    "  serina_clone:",
                    "    id: serina_clone",
                    "    provider: gpt_sovits_local",
                    "    runtime_id: clone",
                    "    profile_kind: clone",
                    "    model: gpt-sovits-runtime",
                    "    asset_dir: missing-assets",
                    "    reference_text: hello there",
                    "    enabled: true",
                    "    scene_style_hints:",
                    "      default: clone",
                ]
            )
        )
        app_config = build_test_config(self.workspace.db_path)
        voice_config = replace(
            app_config.voice,
            default_voice_profile_id="serina_clone",
            tts_provider="cosyvoice_local",
        )
        service = SpeechSynthesisService(
            config=voice_config,
            profile_registry=registry,
            renderer=SpeechScriptRenderer(),
            chunker=SpeechChunker(),
            providers={"gpt_sovits_local": provider, "cosyvoice_local": provider},
        )

        with self.assertRaises(VoicePipelineError) as ctx:
            service.synthesize_reply("This should fail before synth.", scene="greeting")

        self.assertEqual(ctx.exception.stage, VoiceErrorStage.SPEAKING)
        self.assertIn("asset_dir", str(ctx.exception))

    def _write_registry(self, lines: list[str]) -> Path:
        registry_path = self.workspace.root / "voice_profiles.yaml"
        registry_path.write_text("\n".join(lines), encoding="utf-8")
        return registry_path


if __name__ == "__main__":
    unittest.main()
