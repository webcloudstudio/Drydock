"""User-scoped Drydock configuration with environment-variable overrides."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values, set_key

from drydock.errors import ConfigurationError

_KEY_MAP = {
    "drydock_build_directory": "DRYDOCK_BUILD_DIRECTORY",
    "drydock_workspace": "DRYDOCK_WORKSPACE",
    "drydock_model": "DRYDOCK_MODEL",
    "llm_provider": "LLM_PROVIDER",
    "prompt_warn_tokens": "PROMPT_WARN_TOKENS",
    "quarterdeck_port": "QUARTERDECK_PORT",
    "shipslog_dir": "DRYDOCK_SHIPSLOG_DIR",
}

DEFAULT_MODEL = "sonnet"
DEFAULT_PROMPT_WARN_TOKENS = 50_000
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


def _default_build_directory() -> Path:
    """Default builds beside the Drydock source/install directory."""
    try:
        from drydock.paths import get_repo_root

        return get_repo_root().parent
    except FileNotFoundError:
        # Installed package fallback: one level above the package directory.
        return Path(__file__).resolve().parent.parent


def get_build_directory() -> Path:
    """Resolve the root where ``drydock build`` writes built projects."""
    val, _source = _get("DRYDOCK_BUILD_DIRECTORY")
    resolved = Path(val).expanduser().resolve() if val else _default_build_directory()
    if not resolved.is_dir():
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigurationError(
                f"Could not create build directory: {resolved}\n  {exc}"
            ) from exc
    return resolved


def build_dir_for(target: str) -> Path:
    """The built application directory for a Target: ``$DRYDOCK_BUILD_DIRECTORY/<Target>``."""
    return get_build_directory() / target


def get_target_directory() -> Path:
    """Root holding all Targets: ``$DRYDOCK_WORKSPACE/targets``."""
    return get_workspace() / "targets"


def blueprint_dir_for(target_dir: Path) -> Path:
    """The Blueprint subtree of a Target: ``targets/<Target>/blueprint``."""
    return target_dir / "blueprint"


def get_model(cli_override: str | None = None) -> str:
    """Resolve the LLM model for this invocation.

    Resolution order: cli_override → DRYDOCK_MODEL (env or config file) → ``sonnet``.
    Prompt frontmatter ``model:`` values are hints only and are ignored here.
    """
    if cli_override:
        return cli_override.strip()
    value, _source = _get("DRYDOCK_MODEL", DEFAULT_MODEL)
    return (value or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def get_llm_provider(cli_override: str | None = None) -> str:
    """Resolve the LLM provider for this invocation.

    Resolution order: cli_override → LLM_PROVIDER (env or config file) → ``claude``.
    """
    if cli_override is not None:
        value = cli_override
    else:
        value, _source = _get("LLM_PROVIDER", "claude")
    provider = (value or "").lower().strip()
    if provider not in {"claude", "codex"}:
        raise ConfigurationError(f"Invalid LLM_PROVIDER: {value!r}\n  Valid values: claude, codex")
    return provider


def get_prompt_warn_tokens() -> int:
    value, _source = _get("PROMPT_WARN_TOKENS", str(DEFAULT_PROMPT_WARN_TOKENS))
    try:
        tokens = int(value or DEFAULT_PROMPT_WARN_TOKENS)
    except ValueError:
        tokens = 0
    if tokens <= 0:
        raise ConfigurationError(
            f"Invalid PROMPT_WARN_TOKENS: {value!r}\n  Expected a positive integer (tokens)."
        )
    return tokens


def get_shipslog_dir() -> Path | None:
    """Resolve the configured Ship's Log posts package directory, if any."""
    value, _source = _get("DRYDOCK_SHIPSLOG_DIR")
    return Path(value).expanduser() if value else None


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
    build_value, build_source = _get("DRYDOCK_BUILD_DIRECTORY")
    if not build_value:
        build_value, build_source = str(get_build_directory()), "default"
    rows.append(("drydock_build_directory", build_value or "(not set)", build_source))
    ws_value, ws_source = _get("DRYDOCK_WORKSPACE")
    if not ws_value:
        ws_value, ws_source = str(get_workspace()), "default"
    rows.append(("drydock_workspace", ws_value, ws_source))
    for display_key, key_upper, default in (
        ("drydock_model", "DRYDOCK_MODEL", DEFAULT_MODEL),
        ("llm_provider", "LLM_PROVIDER", "claude"),
        ("prompt_warn_tokens", "PROMPT_WARN_TOKENS", str(DEFAULT_PROMPT_WARN_TOKENS)),
        ("quarterdeck_port", "QUARTERDECK_PORT", str(DEFAULT_QUARTERDECK_PORT)),
        ("shipslog_dir", "DRYDOCK_SHIPSLOG_DIR", ""),
    ):
        value, source = _get(key_upper, default)
        rows.append((display_key, value or "(not set)", source))
    return rows


def record_activity(
    command: str,
    blueprint: str | None = None,
    target: str | None = None,
) -> None:
    """Persist last-command metadata when the user config path is writable.

    Activity logging is best-effort only and must never change command behavior.
    """
    try:
        cfg = _config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.touch()
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        set_key(cfg, "LAST_COMMAND", command)
        set_key(cfg, "LAST_BLUEPRINT", blueprint or "")
        set_key(cfg, "LAST_TARGET", target or "")
        set_key(cfg, "LAST_COMMAND_TIME", now)
    except OSError:
        return


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

    if upper == "DRYDOCK_MODEL":
        stored_value = value.strip()
        if not stored_value:
            raise ConfigurationError("drydock_model must not be empty.")
    elif upper == "LLM_PROVIDER":
        stored_value = value.lower()
        if stored_value not in {"claude", "codex"}:
            raise ConfigurationError(
                f"Invalid llm_provider: {value!r}\n  Valid values: claude, codex"
            )
    elif upper == "PROMPT_WARN_TOKENS":
        if not value.isdigit() or int(value) <= 0:
            raise ConfigurationError(
                f"Invalid prompt_warn_tokens: {value!r}\n  Expected a positive integer (tokens)."
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


_HISTORY_FILENAME = "history.jsonl"


def append_command_history(
    workspace: Path,
    command: str,
    target: str = "",
    return_code: int | None = None,
) -> None:
    """Append one timestamped command record to the workspace command-execution log.

    All drydock CLI invocations that touch a named target pass ``target``; workspace-only
    commands (e.g. ``drydock config show``) omit it.
    """
    history_path = workspace / "logs" / _HISTORY_FILENAME
    history_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    record: dict = {"command": command, "time": now}
    if target:
        record["target"] = target
    if return_code is not None:
        record["return_code"] = return_code
    with history_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record) + "\n")


def read_command_history(workspace: Path, target: str = "", limit: int = 10) -> list[dict]:
    """Return up to *limit* most-recent records from the workspace command-execution log.

    Pass ``target`` to filter to records for a specific target only.
    """
    history_path = workspace / "logs" / _HISTORY_FILENAME
    if not history_path.exists():
        return []
    records: list[dict] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if not target or rec.get("target", "") == target:
                records.append(rec)
        except Exception:
            pass
    return records[-limit:]
