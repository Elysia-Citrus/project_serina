from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from src.config.loader import ConfigError, _read_yaml_file
from src.voice.models import VoiceProfile


LEGACY_VOICE_PROFILE_ID = "legacy_default"


@dataclass(frozen=True)
class VoiceProfileRegistry:
    profiles: dict[str, VoiceProfile]
    source_path: Path | None = None

    @classmethod
    def empty(cls, *, source_path: Path | None = None) -> "VoiceProfileRegistry":
        return cls(profiles={}, source_path=source_path)

    def get(self, profile_id: str) -> VoiceProfile | None:
        return self.profiles.get(profile_id)


def load_voice_profile_registry(
    path: str | Path,
    *,
    allow_missing: bool = False,
) -> VoiceProfileRegistry:
    resolved_path = Path(path)
    if not resolved_path.is_absolute():
        resolved_path = resolved_path.resolve()

    if not resolved_path.exists():
        if allow_missing:
            return VoiceProfileRegistry.empty(source_path=resolved_path)
        raise ConfigError(f"Voice profile registry does not exist: {resolved_path}")

    raw = _read_yaml_file(resolved_path)
    profiles_raw = raw.get("profiles", raw)
    if not isinstance(profiles_raw, dict) or not profiles_raw:
        raise ConfigError(
            f"{resolved_path} must contain a non-empty `profiles` mapping."
        )

    profiles: dict[str, VoiceProfile] = {}
    for entry_key, entry_value in profiles_raw.items():
        if not isinstance(entry_key, str) or not entry_key.strip():
            raise ConfigError(
                f"{resolved_path} contains a voice profile with an empty id key."
            )
        if not isinstance(entry_value, dict):
            raise ConfigError(
                f"{resolved_path} profile `{entry_key}` must be a mapping."
            )

        profile = _parse_voice_profile(
            profile_key=entry_key.strip(),
            raw=entry_value,
            source_path=resolved_path,
        )
        if profile.id in profiles:
            raise ConfigError(
                f"{resolved_path} contains duplicate voice profile id `{profile.id}`."
            )
        profiles[profile.id] = profile

    return VoiceProfileRegistry(profiles=profiles, source_path=resolved_path)


def _parse_voice_profile(
    *,
    profile_key: str,
    raw: Mapping[str, object],
    source_path: Path,
) -> VoiceProfile:
    profile_id = _clean_optional_string(raw.get("id")) or profile_key
    provider = _require_string(raw, "provider", source_path, profile_id).lower()
    model = _require_string(raw, "model", source_path, profile_id)
    enabled = _parse_bool(
        raw.get("enabled"),
        default=True,
        source_path=source_path,
        profile_id=profile_id,
    )
    profile_kind = _parse_profile_kind(
        raw.get("profile_kind"),
        source_path=source_path,
        profile_id=profile_id,
    )
    scene_style_hints = _parse_scene_style_hints(
        raw.get("scene_style_hints"),
        source_path=source_path,
        profile_id=profile_id,
    )
    reference_audio_path = _clean_optional_string(raw.get("reference_audio_path"))
    if reference_audio_path is not None:
        reference_path = Path(reference_audio_path)
        if not reference_path.is_absolute():
            reference_audio_path = str((source_path.parent / reference_path).resolve())
    asset_dir = _clean_optional_string(raw.get("asset_dir"))
    if asset_dir is not None:
        asset_path = Path(asset_dir)
        if not asset_path.is_absolute():
            asset_dir = str((source_path.parent / asset_path).resolve())

    return VoiceProfile(
        id=profile_id,
        provider=provider,
        model=model,
        runtime_id=_clean_optional_string(raw.get("runtime_id")),
        profile_kind=profile_kind,
        voice_preset=_clean_optional_string(raw.get("voice_preset")),
        speaker_id=_clean_optional_string(raw.get("speaker_id")),
        voice_profile_id=_clean_optional_string(raw.get("voice_profile_id")),
        reference_audio_path=reference_audio_path,
        asset_dir=asset_dir,
        reference_text=_clean_optional_string(raw.get("reference_text")),
        scene_style_hints=scene_style_hints,
        enabled=enabled,
    )


def _parse_scene_style_hints(
    value: object,
    *,
    source_path: Path,
    profile_id: str,
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            f"{source_path} profile `{profile_id}` field `scene_style_hints` must be a mapping."
        )

    parsed: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ConfigError(
                f"{source_path} profile `{profile_id}` contains an empty style hint key."
            )
        cleaned_value = _clean_optional_string(raw_value)
        if cleaned_value is None:
            continue
        parsed[raw_key.strip()] = cleaned_value
    return parsed


def _require_string(
    raw: Mapping[str, object],
    key: str,
    source_path: Path,
    profile_id: str,
) -> str:
    value = _clean_optional_string(raw.get(key))
    if value is None:
        raise ConfigError(
            f"{source_path} profile `{profile_id}` is missing required field `{key}`."
        )
    return value


def _parse_bool(
    value: object,
    *,
    default: bool,
    source_path: Path,
    profile_id: str,
) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(
            f"{source_path} profile `{profile_id}` field `enabled` must be a boolean."
        )
    return value


def _parse_profile_kind(
    value: object,
    *,
    source_path: Path,
    profile_id: str,
) -> str:
    cleaned = _clean_optional_string(value) or "preset"
    if cleaned not in {"preset", "clone"}:
        raise ConfigError(
            f"{source_path} profile `{profile_id}` field `profile_kind` must be `preset` or `clone`."
        )
    return cleaned


def _clean_optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("Expected an optional string value, but got a non-string.")
    cleaned = value.strip()
    return cleaned or None
