"""User-scoped Drydock configuration with environment-variable overrides."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values, set_key

from drydock.errors import ConfigurationError

_KEY_MAP = {
    "blueprint_directory": "BLUEPRINT_DIRECTORY",
    "specification_directory": "BLUEPRINT_DIRECTORY",
    "target_directory": "TARGET_DIRECTORY",
    "llm_provider": "LLM_PROVIDER",
    "prompt_warn_kb": "PROMPT_WARN_KB",
    "quarterdeck_port": "QUARTERDECK_PORT",
}

DEFAULT_PROMPT_WARN_KB = 50
DEFAULT_QUARTERDECK_PORT = 8080


def _config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "drydock" / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def _get(key_upper: str, default: str | None = None) -> tuple[str | None, str]:
    if key_upper in os.environ:
        return os.environ[key_upper], "environment"
    value = _read_env_file(_config_path()).get(key_upper)
    if value is not None:
        return value, "config file"
    return default, "default"


def get_blueprint_directory() -> Path:
    val, _source = _get("BLUEPRINT_DIRECTORY")
    if not val:
        val, _source = _get("SPECIFICATION_DIRECTORY")
    if not val:
        raise ConfigurationError(
            "BLUEPRINT_DIRECTORY is not set.\n  Run: drydock config set blueprint_directory <path>"
        )
    return Path(val)


def get_target_directory() -> Path:
    val, _source = _get("TARGET_DIRECTORY")
    if not val:
        raise ConfigurationError(
            "TARGET_DIRECTORY is not set.\n  Run: drydock config set target_directory <path>"
        )
    return Path(val)


def get_llm_provider() -> str:
    value, _source = _get("LLM_PROVIDER", "claude")
    provider = (value or "").lower()
    if provider not in {"claude", "codex"}:
        raise ConfigurationError(f"Invalid LLM_PROVIDER: {value!r}\n  Valid values: claude, codex")
    return provider


def get_prompt_warn_kb() -> int:
    value, _source = _get("PROMPT_WARN_KB", str(DEFAULT_PROMPT_WARN_KB))
    try:
        kb = int(value or DEFAULT_PROMPT_WARN_KB)
    except ValueError:
        kb = 0
    if kb <= 0:
        raise ConfigurationError(
            f"Invalid PROMPT_WARN_KB: {value!r}\n  Expected a positive integer (kilobytes)."
        )
    return kb


def get_quarterdeck_port() -> int:
    value, _source = _get("QUARTERDECK_PORT", str(DEFAULT_QUARTERDECK_PORT))
    try:
        port = int(value or DEFAULT_QUARTERDECK_PORT)
    except ValueError:
        port = 0
    if not (1 <= port <= 65535):
        raise ConfigurationError(
            f"Invalid QUARTERDECK_PORT: {value!r}\n  Expected an integer between 1 and 65535."
        )
    return port


def config_show() -> list[tuple[str, str, str]]:
    rows = []
    blueprint_value, blueprint_source = _get("BLUEPRINT_DIRECTORY")
    if not blueprint_value:
        blueprint_value, blueprint_source = _get("SPECIFICATION_DIRECTORY")
    rows.append(("blueprint_directory", blueprint_value or "(not set)", blueprint_source))
    for display_key, key_upper, default in (
        ("target_directory", "TARGET_DIRECTORY", None),
        ("llm_provider", "LLM_PROVIDER", "claude"),
        ("prompt_warn_kb", "PROMPT_WARN_KB", str(DEFAULT_PROMPT_WARN_KB)),
        ("quarterdeck_port", "QUARTERDECK_PORT", str(DEFAULT_QUARTERDECK_PORT)),
    ):
        value, source = _get(key_upper, default)
        rows.append((display_key, value or "(not set)", source))
    return rows


def record_activity(
    command: str,
    blueprint: str | None = None,
    target: str | None = None,
) -> None:
    cfg = _config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.touch()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    set_key(cfg, "LAST_COMMAND", command)
    set_key(cfg, "LAST_BLUEPRINT", blueprint or "")
    set_key(cfg, "LAST_TARGET", target or "")
    set_key(cfg, "LAST_COMMAND_TIME", now)


def get_last_activity() -> dict[str, str]:
    stored = _read_env_file(_config_path())
    return {
        "command": stored.get("LAST_COMMAND", ""),
        "blueprint": stored.get("LAST_BLUEPRINT", ""),
        "target": stored.get("LAST_TARGET", ""),
        "time": stored.get("LAST_COMMAND_TIME", ""),
    }


def config_set(key: str, value: str) -> Path:
    upper = _KEY_MAP.get(key.lower())
    if upper is None:
        raise ConfigurationError(f"Unknown key: {key!r}\n  Valid keys: {', '.join(_KEY_MAP)}")

    if upper == "LLM_PROVIDER":
        stored_value = value.lower()
        if stored_value not in {"claude", "codex"}:
            raise ConfigurationError(
                f"Invalid llm_provider: {value!r}\n  Valid values: claude, codex"
            )
    elif upper == "PROMPT_WARN_KB":
        if not value.isdigit() or int(value) <= 0:
            raise ConfigurationError(
                f"Invalid prompt_warn_kb: {value!r}\n  Expected a positive integer (kilobytes)."
            )
        stored_value = value
    elif upper == "QUARTERDECK_PORT":
        try:
            port = int(value)
        except ValueError:
            port = 0
        if not (1 <= port <= 65535):
            raise ConfigurationError(
                f"Invalid quarterdeck_port: {value!r}\n  Expected an integer between 1 and 65535."
            )
        stored_value = value
    else:
        resolved = Path(value).expanduser().resolve()
        if not resolved.is_dir():
            raise ConfigurationError(
                f"Directory does not exist: {resolved}\n"
                "  Create the directory first, then re-run config set."
            )
        stored_value = str(resolved)

    cfg = _config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.touch()
    set_key(cfg, upper, stored_value)
    return cfg
