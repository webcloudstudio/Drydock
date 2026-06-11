"""User-scoped Drydock configuration with environment-variable overrides."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, set_key

from drydock.errors import ConfigurationError

_KEY_MAP = {
    "specification_directory": "SPECIFICATION_DIRECTORY",
    "target_directory": "TARGET_DIRECTORY",
    "llm_provider": "LLM_PROVIDER",
}


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


def get_specification_directory() -> Path:
    val, _source = _get("SPECIFICATION_DIRECTORY")
    if not val:
        raise ConfigurationError(
            "SPECIFICATION_DIRECTORY is not set.\n"
            "  Run: drydock config set specification_directory <path>"
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


def config_show() -> list[tuple[str, str, str]]:
    rows = []
    for display_key, key_upper, default in (
        ("specification_directory", "SPECIFICATION_DIRECTORY", None),
        ("target_directory", "TARGET_DIRECTORY", None),
        ("llm_provider", "LLM_PROVIDER", "claude"),
    ):
        value, source = _get(key_upper, default)
        rows.append((display_key, value or "(not set)", source))
    return rows


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
