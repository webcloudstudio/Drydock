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
    "drydock_effort": "DRYDOCK_EFFORT",
    "drydock_build_escalate_model": "DRYDOCK_BUILD_ESCALATE_MODEL",
    "llm_provider": "LLM_PROVIDER",
    "codex_sandbox": "DRYDOCK_CODEX_SANDBOX",
    "prompt_warn_tokens": "PROMPT_WARN_TOKENS",
    "prompt_error_tokens": "PROMPT_ERROR_TOKENS",
    "quarterdeck_port": "QUARTERDECK_PORT",
    "diagnose": "DRYDOCK_DIAGNOSE",
    "sandbox_mem_limit": "DRYDOCK_SANDBOX_MEM_LIMIT",
}

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

DEFAULT_MODEL = "sonnet"

# Reasoning effort, lowest to highest, in Drydock's own vocabulary. Providers map onto this
# ladder; a level a provider cannot serve clamps down to the nearest one it can, never up.
# Unset is the shipped default: each provider keeps its own effort default until a prompt,
# the configuration, or ``--effort`` asks for something else.
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

DEFAULT_PROMPT_WARN_TOKENS = 50_000
# The red light to ``PROMPT_WARN_TOKENS``' yellow. The warn threshold is advisory and a
# legitimate specification trips it routinely, so only this one is a genuine ceiling.
DEFAULT_PROMPT_ERROR_TOKENS = 120_000
DEFAULT_QUARTERDECK_PORT = 8080
# Address-space ceiling, in MB, for a build's acceptance run and everything it spawns. A JVM,
# a Go toolchain, or a sanitizer build reserves far more virtual address space than it uses;
# raise this or set it to 0 to lift the bound entirely.
DEFAULT_SANDBOX_MEM_LIMIT_MB = 4096


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
    top-level of the working directory. Raises ``ConfigurationError`` when neither
    is available so commands never silently operate on an unintended directory.
    """
    val, _source = _get("DRYDOCK_WORKSPACE")
    if val:
        return Path(val)
    top = _git_toplevel(Path.cwd())
    if top is not None:
        return top
    raise ConfigurationError(
        "DRYDOCK_WORKSPACE is not set and the current directory is not a Git "
        "repository.\n"
        "  Set a workspace:  drydock config set drydock_workspace <path>\n"
        "  or export DRYDOCK_WORKSPACE=<path>\n"
        "  then initialize a Target:  drydock init <Target>"
    )


def _default_build_directory() -> Path:
    """Default build root lives inside the workspace: ``$DRYDOCK_WORKSPACE/build``."""
    return get_workspace() / "build"


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


def require_target_dir(target: str) -> Path:
    """Resolve an initialized Target directory or raise a run-init error.

    Gates Target-consuming commands so an unset workspace or an uninitialized
    Target produces an actionable message instead of an opaque downstream failure.
    """
    targets_root = get_target_directory()
    target_dir = targets_root / target
    if not target_dir.is_dir():
        raise ConfigurationError(
            f"Target '{target}' is not initialized under {targets_root}.\n"
            f"  Run: drydock init {target}"
        )
    return target_dir


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


def invalid_effort_message(label: str, value: str) -> str:
    """The one message every effort rejection uses, so the vocabulary is always shown."""
    return (
        f"Invalid {label}: {value!r}\n"
        f"  Valid values: {', '.join(EFFORT_LEVELS)} (lowest to highest)\n"
        "  Omit it to keep the provider's own default."
    )


def normalize_effort(value: str | None, label: str = "effort") -> str | None:
    """Validate one effort level, or ``None`` when the provider default stands.

    ``label`` names the setting in the error message so the same check serves the
    ``--effort`` flag, ``drydock_effort``, and prompt frontmatter alike.
    """
    if value is None:
        return None
    level = value.strip().lower()
    if not level:
        return None
    if level not in EFFORT_LEVELS:
        raise ConfigurationError(invalid_effort_message(label, value))
    return level


def get_effort(cli_override: str | None = None) -> str | None:
    """Resolve the reasoning effort for this invocation.

    Resolution order: cli_override → DRYDOCK_EFFORT (env or config file) → unset. Unset
    returns ``None``: no effort is requested and the provider's default stands. A prompt's
    frontmatter ``effort:`` is more specific than this configured floor and is applied by
    the command that loads the prompt.
    """
    if cli_override is not None:
        return normalize_effort(cli_override)
    value, _source = _get("DRYDOCK_EFFORT")
    return normalize_effort(value, "drydock_effort")


def get_escalate_model(cli_override: str | None = None) -> str | None:
    """Resolve the fallback model used on a build's final repair attempt.

    Resolution order: cli_override → DRYDOCK_BUILD_ESCALATE_MODEL (env or config
    file) → unset. An empty or unset value returns ``None``: no escalation, the
    repair loop stays on the base model for every attempt.
    """
    if cli_override is not None:
        return cli_override.strip() or None
    value, _source = _get("DRYDOCK_BUILD_ESCALATE_MODEL")
    return (value or "").strip() or None


def get_llm_provider(cli_override: str | None = None) -> str:
    """Resolve the LLM provider for this invocation.

    Resolution order: cli_override → LLM_PROVIDER (env or config file) → ``claude``.
    """
    value: str | None
    if cli_override is not None:
        value = cli_override
    else:
        value, _source = _get("LLM_PROVIDER", "claude")
    provider = (value or "").lower().strip()
    if provider not in {"claude", "codex"}:
        raise ConfigurationError(f"Invalid LLM_PROVIDER: {value!r}\n  Valid values: claude, codex")
    return provider


CODEX_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
DEFAULT_CODEX_SANDBOX = "danger-full-access"


def get_codex_sandbox(cli_override: str | None = None) -> str:
    """Resolve the sandbox policy for the ``codex`` provider.

    Resolution order: cli_override → DRYDOCK_CODEX_SANDBOX (env or config file) →
    ``danger-full-access``. The default runs model-generated commands directly in the
    invoking shell, so Drydock never depends on an external encapsulation layer
    (``codex-linux-sandbox`` / ``bwrap``). Hardened deployments may opt into
    ``workspace-write``; confinement is otherwise a deployment-layer concern.
    """
    value: str | None
    if cli_override is not None:
        value = cli_override
    else:
        value, _source = _get("DRYDOCK_CODEX_SANDBOX", DEFAULT_CODEX_SANDBOX)
    sandbox = (value or "").lower().strip()
    if sandbox not in CODEX_SANDBOX_MODES:
        raise ConfigurationError(
            f"Invalid DRYDOCK_CODEX_SANDBOX: {value!r}\n"
            f"  Valid values: {', '.join(CODEX_SANDBOX_MODES)}"
        )
    return sandbox


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


def get_prompt_error_tokens() -> int:
    value, _source = _get("PROMPT_ERROR_TOKENS", str(DEFAULT_PROMPT_ERROR_TOKENS))
    try:
        tokens = int(value or DEFAULT_PROMPT_ERROR_TOKENS)
    except ValueError:
        tokens = 0
    if tokens <= 0:
        raise ConfigurationError(
            f"Invalid PROMPT_ERROR_TOKENS: {value!r}\n  Expected a positive integer (tokens)."
        )
    return tokens


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


def get_diagnose_enabled() -> bool:
    """Whether an opaque failure triggers a standoff diagnosis by the selected LLM.

    Resolution order: DRYDOCK_DIAGNOSE (env or config file) → enabled. The ``--no-diagnose``
    flag suppresses the diagnosis for a single invocation and is handled by the CLI.
    """
    value, _source = _get("DRYDOCK_DIAGNOSE", "true")
    return (value or "").strip().lower() not in _FALSE_VALUES


def settable_config_keys() -> tuple[str, ...]:
    """Every key ``config set`` accepts, in declaration order."""
    return tuple(_KEY_MAP)


def get_sandbox_mem_limit_mb() -> int:
    """Address-space ceiling in MB for an acceptance run; ``0`` lifts the bound.

    The limit is inherited by every process the acceptance check spawns, so it bounds the
    built code under test, not just the check. ``RLIMIT_AS`` caps *virtual* address space:
    a JVM or Go runtime reserves far more than it uses, so those stacks may need it raised.
    """
    value, _source = _get("DRYDOCK_SANDBOX_MEM_LIMIT", str(DEFAULT_SANDBOX_MEM_LIMIT_MB))
    try:
        limit = int(value or DEFAULT_SANDBOX_MEM_LIMIT_MB)
    except ValueError:
        raise ConfigurationError(
            f"Invalid sandbox_mem_limit: {value!r}\n"
            "  Expected megabytes as a non-negative integer (0 disables the bound)."
        ) from None
    if limit < 0:
        raise ConfigurationError(
            f"Invalid sandbox_mem_limit: {value!r}\n"
            "  Expected megabytes as a non-negative integer (0 disables the bound)."
        )
    return limit


def config_show() -> list[tuple[str, str, str]]:
    rows = []
    ws_value, ws_source = _get("DRYDOCK_WORKSPACE")
    if not ws_value:
        try:
            ws_value, ws_source = str(get_workspace()), "default"
        except ConfigurationError:
            ws_value, ws_source = "(not set)", "default"
    build_value, build_source = _get("DRYDOCK_BUILD_DIRECTORY")
    if not build_value:
        try:
            build_value, build_source = str(get_build_directory()), "default"
        except ConfigurationError:
            build_value, build_source = "(not set)", "default"
    rows.append(("drydock_build_directory", build_value or "(not set)", build_source))
    rows.append(("drydock_workspace", ws_value, ws_source))
    for display_key, key_upper, default in (
        ("drydock_model", "DRYDOCK_MODEL", DEFAULT_MODEL),
        ("drydock_effort", "DRYDOCK_EFFORT", "(provider default)"),
        ("drydock_build_escalate_model", "DRYDOCK_BUILD_ESCALATE_MODEL", "(not set)"),
        ("llm_provider", "LLM_PROVIDER", "claude"),
        ("codex_sandbox", "DRYDOCK_CODEX_SANDBOX", DEFAULT_CODEX_SANDBOX),
        ("prompt_warn_tokens", "PROMPT_WARN_TOKENS", str(DEFAULT_PROMPT_WARN_TOKENS)),
        ("prompt_error_tokens", "PROMPT_ERROR_TOKENS", str(DEFAULT_PROMPT_ERROR_TOKENS)),
        ("quarterdeck_port", "QUARTERDECK_PORT", str(DEFAULT_QUARTERDECK_PORT)),
        ("diagnose", "DRYDOCK_DIAGNOSE", "true"),
        (
            "sandbox_mem_limit",
            "DRYDOCK_SANDBOX_MEM_LIMIT",
            str(DEFAULT_SANDBOX_MEM_LIMIT_MB),
        ),
    ):
        value, source = _get(key_upper, default)
        # A cleared key holds an empty value; report what actually governs, not "(not set)".
        empty_label = "(provider default)" if key_upper == "DRYDOCK_EFFORT" else "(not set)"
        rows.append((display_key, value or empty_label, source))
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
    elif upper == "DRYDOCK_EFFORT":
        # Empty clears the setting: no effort is requested and the provider default stands.
        stored_value = normalize_effort(value, "drydock_effort") or ""
    elif upper == "DRYDOCK_BUILD_ESCALATE_MODEL":
        # Empty clears the setting: no escalation. A non-empty value is a model name.
        stored_value = value.strip()
    elif upper == "LLM_PROVIDER":
        stored_value = value.lower()
        if stored_value not in {"claude", "codex"}:
            raise ConfigurationError(
                f"Invalid llm_provider: {value!r}\n  Valid values: claude, codex"
            )
    elif upper == "DRYDOCK_CODEX_SANDBOX":
        stored_value = value.lower()
        if stored_value not in CODEX_SANDBOX_MODES:
            raise ConfigurationError(
                f"Invalid codex_sandbox: {value!r}\n"
                f"  Valid values: {', '.join(CODEX_SANDBOX_MODES)}"
            )
    elif upper in {"PROMPT_WARN_TOKENS", "PROMPT_ERROR_TOKENS"}:
        if not value.isdigit() or int(value) <= 0:
            raise ConfigurationError(
                f"Invalid {upper.lower()}: {value!r}\n  Expected a positive integer (tokens)."
            )
        stored_value = value
    elif upper == "DRYDOCK_DIAGNOSE":
        stored_value = value.strip().lower()
        if stored_value not in _TRUE_VALUES | _FALSE_VALUES:
            raise ConfigurationError(
                f"Invalid diagnose: {value!r}\n"
                f"  Valid values: {', '.join(sorted(_TRUE_VALUES | _FALSE_VALUES))}"
            )
    elif upper == "DRYDOCK_SANDBOX_MEM_LIMIT":
        stripped = value.strip()
        if not stripped.isdigit():
            raise ConfigurationError(
                f"Invalid sandbox_mem_limit: {value!r}\n"
                "  Expected megabytes as a non-negative integer (0 disables the bound)."
            )
        stored_value = stripped
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
