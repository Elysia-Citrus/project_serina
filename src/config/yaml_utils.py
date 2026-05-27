from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config.errors import ConfigError


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{path}") from exc

    yaml_module = _load_yaml_module()
    if yaml_module is not None:
        try:
            raw = yaml_module.safe_load(text)
        except yaml_module.YAMLError as exc:  # type: ignore[attr-defined]
            raise ConfigError(f"YAML 解析失败：{path}") from exc
    else:
        raw = _parse_minimal_yaml(text, path)

    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"配置文件内容为空或格式不正确：{path}")
    return raw


def _load_yaml_module() -> Any | None:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return None
    return yaml


def _parse_minimal_yaml(text: str, path: Path) -> dict[str, Any]:
    lines = text.splitlines()
    parsed, next_index = _parse_block(lines, 0, 0, path)

    while next_index < len(lines):
        stripped = lines[next_index].strip()
        if stripped and not stripped.startswith("#"):
            raise ConfigError(
                f"YAML 解析失败：{path} 第 {next_index + 1} 行存在未处理内容。"
            )
        next_index += 1

    if not isinstance(parsed, dict):
        raise ConfigError(f"YAML 解析失败：{path} 顶层必须是映射。")
    return parsed


def _parse_block(
    lines: list[str],
    start_index: int,
    indent: int,
    path: Path,
) -> tuple[Any, int]:
    container: dict[str, Any] | list[Any] | None = None
    index = start_index

    while index < len(lines):
        raw_line = lines[index]
        stripped_line = raw_line.strip()

        if not stripped_line or stripped_line.startswith("#"):
            index += 1
            continue

        current_indent = len(raw_line) - len(raw_line.lstrip(" "))
        if current_indent < indent:
            break
        if current_indent != indent:
            raise ConfigError(
                f"YAML 解析失败：{path} 第 {index + 1} 行缩进不符合最小解析器规则。"
            )

        if stripped_line.startswith("- "):
            if container is None:
                container = []
            if not isinstance(container, list):
                raise ConfigError(
                    f"YAML 解析失败：{path} 第 {index + 1} 行列表与映射混用。"
                )
            container.append(_parse_scalar(stripped_line[2:].strip()))
            index += 1
            continue

        if ":" not in stripped_line:
            raise ConfigError(
                f"YAML 解析失败：{path} 第 {index + 1} 行缺少键值分隔符。"
            )

        if container is None:
            container = {}
        if not isinstance(container, dict):
            raise ConfigError(
                f"YAML 解析失败：{path} 第 {index + 1} 行列表与映射混用。"
            )

        key, raw_value = stripped_line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            raise ConfigError(f"YAML 解析失败：{path} 第 {index + 1} 行存在空 key。")

        if raw_value:
            container[key] = _parse_scalar(raw_value)
            index += 1
            continue

        child, next_index = _parse_block(lines, index + 1, indent + 2, path)
        container[key] = child
        index = next_index

    if container is None:
        return {}, index
    return container, index


def _parse_scalar(raw_value: str) -> Any:
    if raw_value.startswith(("'", '"')) and raw_value.endswith(("'", '"')):
        return raw_value[1:-1]

    if raw_value.isdigit():
        return int(raw_value)

    try:
        if "." in raw_value:
            return float(raw_value)
    except ValueError:
        pass

    lowered = raw_value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None

    return raw_value

