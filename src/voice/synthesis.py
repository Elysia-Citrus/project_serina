from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config.loader import AppConfig, VoiceConfig
from src.voice.chunking import SpeechChunker
from src.voice.errors import VoiceErrorStage, VoicePipelineError
from src.voice.models import (
    SpeechRenderResult,
    SpeechSynthesisResult,
    SpeechSynthesisStreamResult,
    TTSRequest,
    VoiceProfile,
)
from src.voice.profiles import (
    LEGACY_VOICE_PROFILE_ID,
    VoiceProfileRegistry,
    load_voice_profile_registry,
)
from src.voice.speech_render import SpeechScriptRenderer
from src.voice.tts import LocalSpeechProvider, NullTTSProvider, TTSProvider, build_tts_provider


@dataclass(frozen=True)
class _PreparedSpeechRequest:
    profile: VoiceProfile
    provider: TTSProvider
    render_result: SpeechRenderResult
    request: TTSRequest


class SpeechSynthesisService:
    def __init__(
        self,
        *,
        config: VoiceConfig,
        profile_registry: VoiceProfileRegistry,
        renderer: SpeechScriptRenderer,
        chunker: SpeechChunker,
        providers: dict[str, TTSProvider],
    ) -> None:
        self.config = config
        self.profile_registry = profile_registry
        self.renderer = renderer
        self.chunker = chunker
        self.providers = {name.lower(): provider for name, provider in providers.items()}

    @property
    def is_enabled(self) -> bool:
        return self.config.tts_provider.lower() != "none"

    def get_requested_profile_id(self, profile_id: str | None = None) -> str | None:
        if not self.is_enabled:
            return None
        return profile_id or self.config.default_voice_profile_id or LEGACY_VOICE_PROFILE_ID

    def synthesize_reply(
        self,
        reply_text: str,
        scene: str,
        profile_id: str | None = None,
    ) -> SpeechSynthesisResult:
        if not self.is_enabled:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                "Speech synthesis is disabled because tts_provider is set to `none`.",
            )

        prepared = self._prepare_request(reply_text, scene=scene, profile_id=profile_id)
        synthesized_audio = prepared.provider.synthesize(prepared.request)
        return SpeechSynthesisResult(
            synthesized_audio=synthesized_audio,
            speech_text=prepared.render_result.speech_text,
            style_id=prepared.render_result.style_id,
            applied_rules=prepared.render_result.applied_rules,
            voice_profile_id=prepared.profile.id,
        )

    def synthesize_reply_stream(
        self,
        reply_text: str,
        scene: str,
        profile_id: str | None = None,
    ) -> SpeechSynthesisStreamResult | None:
        if not self.is_enabled or not self.config.stream_playback_enabled:
            return None

        prepared = self._prepare_request(reply_text, scene=scene, profile_id=profile_id)
        stream_provider = self._as_local_provider(prepared.provider)
        if stream_provider is None:
            return None

        return SpeechSynthesisStreamResult(
            audio_chunks=stream_provider.synthesize_stream(prepared.request),
            provider_name=prepared.profile.provider,
            model_name=prepared.request.model_name or prepared.profile.model,
            speech_text=prepared.render_result.speech_text,
            style_id=prepared.render_result.style_id,
            applied_rules=prepared.render_result.applied_rules,
            voice_profile_id=prepared.profile.id,
        )

    def warmup_local_runtimes(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for provider_name, provider in self.providers.items():
            local_provider = self._as_local_provider(provider)
            if local_provider is None:
                continue
            try:
                payload = local_provider.healthcheck()
            except VoicePipelineError as exc:
                statuses[provider_name] = f"error: {exc}"
                continue
            statuses[provider_name] = str(payload.get("status") or "ok")
        return statuses

    def describe_profile_state(self, profile_id: str | None = None) -> dict[str, object]:
        profile = self._resolve_profile(profile_id)
        provider = self._resolve_provider(profile.provider)
        local_provider = self._as_local_provider(provider)
        if local_provider is None:
            return {
                "profile_id": profile.id,
                "provider": profile.provider,
                "profile_kind": profile.profile_kind,
                "status": "not_applicable",
            }
        return local_provider.get_profile_state(profile.id)

    def _resolve_profile(self, profile_id: str | None) -> VoiceProfile:
        requested_profile_id = self.get_requested_profile_id(profile_id)
        if requested_profile_id is None:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                "No voice profile is available because speech synthesis is disabled.",
            )

        if requested_profile_id == LEGACY_VOICE_PROFILE_ID:
            return VoiceProfile(
                id=LEGACY_VOICE_PROFILE_ID,
                provider=self.config.tts_provider.lower(),
                model=self.config.tts_model,
                runtime_id=None,
                profile_kind="preset",
                voice_preset=self.config.tts_voice_preset,
                enabled=True,
            )

        profile = self.profile_registry.get(requested_profile_id)
        if profile is None:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Voice profile `{requested_profile_id}` was not found.",
            )
        if not profile.enabled:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"Voice profile `{requested_profile_id}` is disabled.",
            )
        return profile

    def _prepare_request(
        self,
        reply_text: str,
        *,
        scene: str,
        profile_id: str | None,
    ) -> _PreparedSpeechRequest:
        selected_profile = self._resolve_profile(profile_id)
        self._validate_profile(selected_profile)
        render_result = self.renderer.render(reply_text, scene=scene)
        provider = self._resolve_provider(selected_profile.provider)
        runtime_id = selected_profile.runtime_id
        if runtime_id is None:
            if selected_profile.provider == "cosyvoice_local":
                runtime_id = "primary"
            elif selected_profile.provider == "gpt_sovits_local":
                runtime_id = "clone"
        request = TTSRequest(
            text=render_result.speech_text,
            language=self.config.language,
            model_name=selected_profile.model,
            voice_preset=selected_profile.voice_preset,
            speaker_id=selected_profile.speaker_id,
            voice_profile_id=selected_profile.voice_profile_id,
            reference_audio_path=selected_profile.reference_audio_path,
            style_hint=self._resolve_style_hint(selected_profile, render_result.style_id),
            profile_id=selected_profile.id,
            runtime_id=runtime_id,
            profile_kind=selected_profile.profile_kind,
            asset_dir=selected_profile.asset_dir,
            reference_text=selected_profile.reference_text,
            text_chunks=self.chunker.chunk(render_result.speech_text),
        )
        return _PreparedSpeechRequest(
            profile=selected_profile,
            provider=provider,
            render_result=render_result,
            request=request,
        )

    def _resolve_provider(self, provider_name: str) -> TTSProvider:
        normalized_name = provider_name.lower()
        if normalized_name == "none":
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                "Voice profiles cannot target provider `none` while speech synthesis is enabled.",
            )

        provider = self.providers.get(normalized_name)
        if provider is None:
            raise VoicePipelineError(
                VoiceErrorStage.SPEAKING,
                f"No TTS provider is configured for `{provider_name}`.",
            )
        return provider

    def _resolve_style_hint(self, profile: VoiceProfile, style_id: str) -> str | None:
        return (
            profile.scene_style_hints.get(style_id)
            or profile.scene_style_hints.get("default")
        )

    def _validate_profile(self, profile: VoiceProfile) -> None:
        if profile.profile_kind == "clone":
            if profile.provider not in {"gpt_sovits_local", "gpt_sovits_v2"}:
                raise VoicePipelineError(
                    VoiceErrorStage.SPEAKING,
                    f"Clone profile `{profile.id}` must target a GPT-SoVITS provider.",
                )
            if not profile.asset_dir:
                raise VoicePipelineError(
                    VoiceErrorStage.SPEAKING,
                    f"Clone profile `{profile.id}` is missing `asset_dir`.",
                )
            if not Path(profile.asset_dir).exists():
                raise VoicePipelineError(
                    VoiceErrorStage.SPEAKING,
                    f"Clone profile `{profile.id}` asset_dir does not exist: {profile.asset_dir}",
                )
            if not profile.reference_text:
                raise VoicePipelineError(
                    VoiceErrorStage.SPEAKING,
                    f"Clone profile `{profile.id}` is missing `reference_text`.",
                )

    def _as_local_provider(self, provider: TTSProvider) -> LocalSpeechProvider | None:
        if hasattr(provider, "synthesize_stream") and hasattr(provider, "healthcheck"):
            return provider  # type: ignore[return-value]
        return None


def build_speech_synthesis_service(
    app_config: AppConfig,
    *,
    renderer: SpeechScriptRenderer | None = None,
    chunker: SpeechChunker | None = None,
) -> SpeechSynthesisService:
    registry_path = _resolve_registry_path(
        config_dir=app_config.config_dir,
        configured_path=app_config.voice.voice_profiles_path,
    )
    profile_registry = load_voice_profile_registry(registry_path, allow_missing=True)
    providers: dict[str, TTSProvider] = {"none": NullTTSProvider()}
    configured_provider_name = app_config.voice.tts_provider.lower()
    providers[configured_provider_name] = build_tts_provider(
        app_config.voice,
        provider_name=configured_provider_name,
    )
    if app_config.voice.local_tts_enabled:
        for provider_name in ("cosyvoice_local", "gpt_sovits_local", "gpt_sovits_v2"):
            if provider_name not in providers:
                providers[provider_name] = build_tts_provider(
                    app_config.voice,
                    provider_name=provider_name,
                )
    return SpeechSynthesisService(
        config=app_config.voice,
        profile_registry=profile_registry,
        renderer=renderer or SpeechScriptRenderer(),
        chunker=chunker or SpeechChunker(),
        providers=providers,
    )


def _resolve_registry_path(*, config_dir: Path, configured_path: str) -> Path:
    raw_path = Path(configured_path)
    if raw_path.is_absolute():
        return raw_path
    return (config_dir / raw_path).resolve()
