"""Drydock global configuration — reads/writes a user-scoped .env file."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

from drydock.errors import ConfigurationError

_KNOWN_KEYS = ("SPECIFICATION_DIRECTORY", "TARGET_DIRECTORY")
_KEY_MAP = {
    "specification_directory": "SPECIFICATION_DIRECTORY",
    "target_directory": "TARGET_DIRECTORY",
}


def _config_path() -> Path:
    """Return the path to the user-scoped Drydock .env file."""
    base = platformdirs.user_config_path("drydock", appauthor=False)
    return base / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file, preserving comments and unknown keys."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            result[k.strip()] = v.strip()
    return result


def _write_env_file(path: Path, data: dict[str, str]) -> None:
    """Write key=value pairs to a .env file, preserving existing lines."""
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    # Rewrite: update matching KEY= lines, append new ones
    written_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            k = k.strip()
            if k in data:
                new_lines.append(f"{k}={data[k]}")
                written_keys.add(k)
                continue
        new_lines.append(line)

    for k, v in data.items():
        if k not in written_keys:
            new_lines.append(f"{k}={v}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _effective_value(key_upper: str) -> tuple[str | None, str]:
    """Return (value, source) for a known config key using precedence rules."""
    # 1. Environment variable
    env_val = os.environ.get(key_upper)
    if env_val:
        return env_val, "environment variable"

    # 2. User-scoped .env
    cfg = _config_path()
    data = _read_env_file(cfg)
    file_val = data.get(key_upper)
    if file_val:
        return file_val, f"config file ({cfg})"

    return None, "not configured"


def get_specification_directory() -> Path:
    """Return the configured specification directory, raising if unset."""
    val, source = _effective_value("SPECIFICATION_DIRECTORY")
    if not val:
        raise ConfigurationError(
            "specification_directory is not configured.\n"
            "  Run: drydock config set specification_directory <path>"
        )
    return Path(val)


def get_target_directory() -> Path:
    """Return the configured target directory, raising if unset."""
    val, source = _effective_value("TARGET_DIRECTORY")
    if not val:
        raise ConfigurationError(
            "target_directory is not configured.\n  Run: drydock config set target_directory <path>"
        )
    return Path(val)


def config_show() -> list[tuple[str, str, str]]:
    """Return [(display_key, value_or_not_set, source), ...] for each config key."""
    rows = []
    for display, upper in [
        ("specification_directory", "SPECIFICATION_DIRECTORY"),
        ("target_directory", "TARGET_DIRECTORY"),
    ]:
        val, source = _effective_value(upper)
        rows.append((display, val or "(not set)", source))
    return rows


def config_set(key: str, value: str) -> Path:
    """Persist a configuration value. Returns the config file path written."""
    upper = _KEY_MAP.get(key.lower())
    if upper is None:
        raise ConfigurationError(
            f"Unknown configuration key: {key!r}\n  Valid keys: {', '.join(_KEY_MAP)}"
        )

    resolved = Path(value).expanduser().resolve()
    if not resolved.is_dir():
        raise ConfigurationError(
            f"Directory does not exist: {resolved}\n"
            "  Create the directory first, then re-run config set."
        )

    cfg = _config_path()
    existing = _read_env_file(cfg)
    existing[upper] = str(resolved)
    _write_env_file(cfg, existing)
    return cfg
