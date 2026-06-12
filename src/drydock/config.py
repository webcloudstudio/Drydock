"""User-scoped Drydock configuration with environment-variable overrides."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values, set_key

from drydock.errors import ConfigurationError

_KEY_MAP = {
    "drydock_workspace": "DRYDOCK_WORKSPACE",
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


def _git_toplevel(start: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return None


def get_workspace() -> Path:
    """Resolve the Drydock workspace root.

    Precedence: ``DRYDOCK_WORKSPACE`` (environment or config file), then the Git
    top-level of the working directory, then the working directory itself.
    """
    val, _source = _get("DRYDOCK_WORKSPACE")
    if val:
        return Path(val)
    top = _git_toplevel(Path.cwd())
    return top if top is not None else Path.cwd()


def get_blueprint_directory() -> Path:
    """Root holding all Blueprints: ``$DRYDOCK_WORKSPACE/blueprints``."""
    return get_workspace() / "blueprints"


def get_target_directory() -> Path:
    """Root holding all Targets: ``$DRYDOCK_WORKSPACE/targets``."""
    return get_workspace() / "targets"


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
    ws_value, ws_source = _get("DRYDOCK_WORKSPACE")
    if not ws_value:
        ws_value, ws_source = str(get_workspace()), "default"
    rows.append(("drydock_workspace", ws_value, ws_source))
    for display_key, key_upper, default in (
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
