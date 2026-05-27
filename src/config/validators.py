from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config.errors import ConfigError


def _require_mapping(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict) or not value:
        raise ConfigError(f"{path} 中的 `{key}` 必须是非空映射。")
    return value


def _require_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} 中缺少有效字符串字段 `{key}`。")
    return value.strip()


def _require_string_list(data: dict[str, Any], key: str, path: Path) -> list[str]:
    if key not in data:
        raise ConfigError(f"{path} 中缺少字段 `{key}`。")
    result = _optional_string_list(data[key])
    if not result:
        raise ConfigError(f"{path} 中的 `{key}` 必须是非空字符串列表。")
    return result


def _optional_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError("期望字符串列表，但实际不是列表。")

    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError("字符串列表中包含空值或非字符串项。")
        cleaned.append(item.strip())
    return cleaned


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("期望字符串值，但实际不是字符串。")
    cleaned = value.strip()
    return cleaned or None


def _optional_device_selector(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ConfigError("Expected device selector to be a string or integer.")
    cleaned = value.strip()
    return cleaned or None


def _optional_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError("期望布尔值，但实际不是布尔值。")
    return value


def _optional_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int):
        raise ConfigError("期望整数值，但实际不是整数。")
    return value


def _optional_float(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, int):
        return float(value)
    if not isinstance(value, float):
        raise ConfigError("Expected a numeric value, but got a non-number.")
    return value


def _require_int(data: dict[str, Any], key: str, path: Path) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ConfigError(f"{path} 中的 `{key}` 必须是整数。")
    return value


def _require_float(data: dict[str, Any], key: str, path: Path) -> float:
    value = data.get(key)
    if isinstance(value, int):
        return float(value)
    if not isinstance(value, float):
        raise ConfigError(f"{path} 中的 `{key}` 必须是数字。")
    return value

