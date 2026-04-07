from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os


class ConfigError(RuntimeError):
    """Raised when configuration files are missing or invalid."""


@dataclass(frozen=True)
class RelationshipStyleConfig:
    positioning: str
    default_address: str
    intimacy_boundary: str


@dataclass(frozen=True)
class CorrectionStyleConfig:
    stance: str
    principles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaConfig:
    name: str
    user_name: str
    language: str
    self_concept: str
    welcome_message: str
    core_traits: list[str] = field(default_factory=list)
    relationship_style: RelationshipStyleConfig | None = None
    tone_rules: list[str] = field(default_factory=list)
    forbidden_styles: list[str] = field(default_factory=list)
    correction_style: CorrectionStyleConfig | None = None


@dataclass(frozen=True)
class PolicyConfig:
    default_reply_style: str
    short_reply_scenarios: list[str] = field(default_factory=list)
    long_reply_scenarios: list[str] = field(default_factory=list)
    comfort_rules: list[str] = field(default_factory=list)
    correction_rules: list[str] = field(default_factory=list)
    memory_usage_rules: list[str] = field(default_factory=list)
    output_guardrails: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str
    model: str
    reasoner_model: str | None
    api_key_env: str
    api_key: str | None
    base_url: str
    temperature: float
    max_tokens: int
    timeout: int
    max_history_turns: int
    log_level: str
    exit_commands: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    persona: PersonaConfig
    policy: PolicyConfig
    runtime: RuntimeConfig
    config_dir: Path


def load_app_config(config_dir: str | Path | None = None) -> AppConfig:
    resolved_dir = Path(config_dir) if config_dir else Path(__file__).resolve().parent

    persona = load_persona_config(resolved_dir / "persona_config.yaml")
    policy = load_policy_config(resolved_dir / "policy_config.yaml")
    runtime = load_runtime_config(resolved_dir / "runtime_config.yaml")

    return AppConfig(
        persona=persona,
        policy=policy,
        runtime=runtime,
        config_dir=resolved_dir,
    )


def load_persona_config(path: str | Path) -> PersonaConfig:
    resolved_path = Path(path)
    raw = _read_yaml_file(resolved_path)

    relationship_raw = _require_mapping(raw, "relationship_style", resolved_path)
    correction_raw = _require_mapping(raw, "correction_style", resolved_path)
    user_name = _require_string(raw, "user_name", resolved_path)

    return PersonaConfig(
        name=_require_string(raw, "name", resolved_path),
        user_name=user_name,
        language=str(raw.get("language", "zh-CN")).strip(),
        self_concept=str(raw.get("self_concept", "")).strip()
        or "你是 Serina，是老师长期相处的私人数字伴侣。",
        welcome_message=str(raw.get("welcome_message", f"{user_name}，我在。")).strip(),
        core_traits=_require_string_list(raw, "core_traits", resolved_path),
        relationship_style=RelationshipStyleConfig(
            positioning=_require_string(relationship_raw, "positioning", resolved_path),
            default_address=_require_string(
                relationship_raw, "default_address", resolved_path
            ),
            intimacy_boundary=_require_string(
                relationship_raw, "intimacy_boundary", resolved_path
            ),
        ),
        tone_rules=_require_string_list(raw, "tone_rules", resolved_path),
        forbidden_styles=_require_string_list(raw, "forbidden_styles", resolved_path),
        correction_style=CorrectionStyleConfig(
            stance=_require_string(correction_raw, "stance", resolved_path),
            principles=_require_string_list(correction_raw, "principles", resolved_path),
        ),
    )


def load_policy_config(path: str | Path) -> PolicyConfig:
    resolved_path = Path(path)
    raw = _read_yaml_file(resolved_path)

    return PolicyConfig(
        default_reply_style=_require_string(raw, "default_reply_style", resolved_path),
        short_reply_scenarios=_require_string_list(
            raw, "short_reply_scenarios", resolved_path
        ),
        long_reply_scenarios=_require_string_list(
            raw, "long_reply_scenarios", resolved_path
        ),
        comfort_rules=_require_string_list(raw, "comfort_rules", resolved_path),
        correction_rules=_require_string_list(raw, "correction_rules", resolved_path),
        memory_usage_rules=_require_string_list(
            raw, "memory_usage_rules", resolved_path
        ),
        output_guardrails=_optional_string_list(raw.get("output_guardrails")),
    )


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    resolved_path = Path(path)
    raw = _read_yaml_file(resolved_path)

    api_key_env = _require_string(raw, "api_key_env", resolved_path)
    inline_api_key = str(raw.get("api_key", "")).strip()
    env_api_key = os.getenv(api_key_env, "").strip()

    exit_commands_raw = raw.get("exit_commands", ["exit", "quit"])
    exit_commands = tuple(
        command.strip().lower()
        for command in _optional_string_list(exit_commands_raw)
        if command.strip()
    )

    return RuntimeConfig(
        provider=_require_string(raw, "provider", resolved_path).lower(),
        model=_require_string(raw, "model", resolved_path),
        reasoner_model=_optional_string(raw.get("reasoner_model")),
        api_key_env=api_key_env,
        api_key=env_api_key or inline_api_key or None,
        base_url=_require_string(raw, "base_url", resolved_path),
        temperature=_require_float(raw, "temperature", resolved_path),
        max_tokens=_require_int(raw, "max_tokens", resolved_path),
        timeout=_require_int(raw, "timeout", resolved_path),
        max_history_turns=max(1, _require_int(raw, "max_history_turns", resolved_path)),
        log_level=str(raw.get("log_level", "INFO")).strip().upper() or "INFO",
        exit_commands=exit_commands or ("exit", "quit"),
    )


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{path}") from exc

    yaml = _load_yaml_module()
    if yaml is not None:
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML 解析失败：{path}") from exc
    else:
        raw = _parse_minimal_yaml(text, path)

    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"配置文件内容为空或格式不正确：{path}")

    return raw


def _load_yaml_module() -> Any | None:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        return None
    return yaml


def _parse_minimal_yaml(text: str, path: Path) -> dict[str, Any]:
    lines = text.splitlines()
    parsed, next_index = _parse_block(lines, 0, 0, path)

    while next_index < len(lines):
        if lines[next_index].strip():
            raise ConfigError(f"YAML 解析失败：{path} 第 {next_index + 1} 行存在未处理内容。")
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

        if not stripped_line:
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
            raise ConfigError(f"YAML 解析失败：{path} 第 {index + 1} 行缺少键值分隔符。")

        if container is None:
            container = {}
        if not isinstance(container, dict):
            raise ConfigError(f"YAML 解析失败：{path} 第 {index + 1} 行列表与映射混用。")

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
    value = data[key]
    result = _optional_string_list(value)
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
