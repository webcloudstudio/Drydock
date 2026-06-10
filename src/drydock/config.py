"""Drydock project configuration — reads/writes a .env in the working directory."""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values, set_key

from drydock.errors import ConfigurationError

_KEY_MAP = {
    "specification_directory": "SPECIFICATION_DIRECTORY",
    "target_directory": "TARGET_DIRECTORY",
}


def _config_path() -> Path:
    return Path.cwd() / ".env"


def _get(key_upper: str) -> str | None:
    return dotenv_values(_config_path()).get(key_upper)


def get_specification_directory() -> Path:
    val = _get("SPECIFICATION_DIRECTORY")
    if not val:
        raise ConfigurationError(
            "SPECIFICATION_DIRECTORY is not set.\n"
            "  Run: drydock config set specification_directory <path>"
        )
    return Path(val)


def get_target_directory() -> Path:
    val = _get("TARGET_DIRECTORY")
    if not val:
        raise ConfigurationError(
            "TARGET_DIRECTORY is not set.\n"
            "  Run: drydock config set target_directory <path>"
        )
    return Path(val)


def config_show() -> list[tuple[str, str]]:
    data = dotenv_values(_config_path())
    return [
        ("specification_directory", data.get("SPECIFICATION_DIRECTORY") or "(not set)"),
        ("target_directory", data.get("TARGET_DIRECTORY") or "(not set)"),
    ]


def config_set(key: str, value: str) -> Path:
    upper = _KEY_MAP.get(key.lower())
    if upper is None:
        raise ConfigurationError(
            f"Unknown key: {key!r}\n  Valid keys: {', '.join(_KEY_MAP)}"
        )

    resolved = Path(value).expanduser().resolve()
    if not resolved.is_dir():
        raise ConfigurationError(
            f"Directory does not exist: {resolved}\n"
            "  Create the directory first, then re-run config set."
        )

    cfg = _config_path()
    cfg.touch()
    set_key(cfg, upper, str(resolved))
    return cfg
