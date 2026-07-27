"""Subscription-authenticated Claude and Codex CLI execution."""

from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from drydock.config import get_codex_sandbox, get_llm_provider
from drydock.errors import LlmConfigurationError, LlmError
from drydock.execution import (
    ExecutionArtifacts,
    append_execution_record,
    isoformat,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from drydock.logging import close_execution_logger, create_execution_logger
from drydock.prompt_assembly import PromptAssembly

# A provider agent runs shell commands, and those grandchildren inherit the provider's
# stdout/stderr pipes.  A grandchild that outlives the provider holds the write end open,
# so pipe EOF is not a trustworthy completion signal: process exit is.  Once the provider
# has exited and the pipes have been quiet this long, Drydock stops reading and reaps the
# process group rather than waiting on a descendant it never asked for.
_DRAIN_GRACE_SECONDS = 2.0

# Builds run without a timeout and legitimately take many minutes, so a silent console is
# indistinguishable from a wedged run.  Emit a liveness notice after this much quiet.
_HEARTBEAT_SECONDS = 60.0

# Provider shell commands can be long; keep the console line readable.
_ACTIVITY_COMMAND_LIMIT = 160


@dataclass(frozen=True)
class LlmStats:
    model: str | None = None
    elapsed_ms: int | None = None
    duration_ms: int | None = None
    turns: int | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class LlmResult:
    execution_id: str
    llm: str
    command: tuple[str, ...]
    working_directory: Path
    returncode: int
    text: str
    stderr: str
    stats: LlmStats
    artifacts: ExecutionArtifacts
    record: Mapping[str, Any] = field(repr=False)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


TextCallback = Callable[[str], None]
EventCallback = Callable[[Mapping[str, Any]], None]


SUPPORTED_PROVIDERS = ("claude", "codex")

# Substrings that unambiguously identify which provider a model name belongs to.
# Used only to catch a clear cross-provider mismatch (e.g. codex + opus) up front;
# an unrecognized model name is left alone because Drydock does not enumerate every
# valid model a provider CLI accepts.
_MODEL_FAMILY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude", ("claude", "opus", "sonnet", "haiku", "fable")),
    ("codex", ("gpt-", "gpt5", "codex", "luna", "o3-", "o4-")),
)


def _model_provider_family(model: str) -> str | None:
    """Return the provider a model name clearly belongs to, or ``None`` if unknown."""
    lowered = model.lower().strip()
    for provider, markers in _MODEL_FAMILY_MARKERS:
        if any(marker in lowered for marker in markers):
            return provider
    return None


def provider_model_conflict(llm: str | None, model: str | None) -> str | None:
    """Describe an invalid provider or a provider/model mismatch, else ``None``.

    Returns a human-readable problem statement suitable for a usage error. The
    caller decides how to surface it (exit code, stream). Validation is
    conservative: only a model whose name clearly names the *other* provider is
    rejected, so custom or future model names pass through.
    """
    provider = (llm or "").lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        return f"Invalid LLM provider: {llm!r}\n  Valid providers: {', '.join(SUPPORTED_PROVIDERS)}"
    if not model:
        return None
    family = _model_provider_family(model)
    if family is not None and family != provider:
        return (
            f"Model/provider mismatch: model {model!r} is a {family} model, "
            f"but the selected provider is {provider!r}.\n"
            f"  Choose a {provider} model, or select the {family} provider "
            f"with --llm-provider {family}."
        )
    return None


# Reasoning effort, in the vocabulary the claude CLI accepts. Higher levels buy deeper
# deliberation at the cost of latency and spend, so effort is opt-in per command.
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

# codex has no --effort flag and a shorter ladder, so the top two claude levels clamp to its
# maximum. The mapping is lossy in one direction only: a codex run is never given less effort
# than was asked for.
_CODEX_EFFORT: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


def normalize_effort(effort: str | None) -> str | None:
    """Validate a requested effort level, or ``None`` when the provider default stands."""
    if effort is None:
        return None
    level = effort.strip().lower()
    if level not in EFFORT_LEVELS:
        raise LlmConfigurationError(
            f"Invalid effort level: {effort!r}\n  Valid values: {', '.join(EFFORT_LEVELS)}"
        )
    return level


def _command(
    llm: str,
    working_directory: Path,
    artifacts: ExecutionArtifacts,
    model: str | None,
    allow_tools: bool = False,
    codex_sandbox: str = "danger-full-access",
    effort: str | None = None,
) -> tuple[str, ...]:
    if llm == "claude":
        command = [
            "claude",
            "-p",
            "--verbose",
            # Suppress auto-discovery of CLAUDE.md/AGENTS.md, auto-memory, hooks,
            # plugins, and MCP servers from the caller's environment so the build
            # agent receives only Drydock's deterministically assembled prompt.
            # --safe-mode (unlike --bare) preserves subscription/OAuth auth.
            "--safe-mode",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
        ]
        if allow_tools:
            # drydock build runs an agent that writes the application into the build
            # working directory, so it needs file tools and unattended permission.
            command.append("--dangerously-skip-permissions")
        else:
            # Text-only LLM-assisted commands consume model text and write their own
            # artifacts.  Giving Claude Code tools lets it bypass that contract by
            # editing the target and returning a narrative summary instead.
            # --strict-mcp-config with no --mcp-config suppresses MCP tool descriptions
            # from the system prompt; without it, Claude emits tool-call XML as text.
            command.extend(("--tools", "", "--strict-mcp-config"))
        if model:
            command.extend(("--model", model))
        if effort:
            command.extend(("--effort", effort))
        return tuple(command)
    if llm == "codex":
        command = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--sandbox",
            codex_sandbox,
            "--cd",
            str(working_directory),
            "--json",
            "--output-last-message",
            str(artifacts.output_file),
        ]
        if model:
            command.extend(("--model", model))
        if effort:
            command.extend(("-c", f"model_reasoning_effort={_CODEX_EFFORT[effort]}"))
        command.append("-")
        return tuple(command)
    raise LlmConfigurationError(f"Unsupported LLM: {llm!r}")


def _isolate_claude_env(process_env: dict[str, str]) -> None:
    """Point the ``claude`` subprocess at a dedicated config home.

    The subprocess reads a clean ``~/.drydock/claude-home`` instead of the user's
    real ``~/.claude``, so it inherits none of the user's settings, plugins, MCP
    servers, history, or state.  The subscription OAuth token is copied in on every
    run so authentication continues to use the user's subscription.

    Mutates ``process_env`` in place.  When no plaintext credentials file exists
    (e.g. keychain or API-key auth), the overrides are skipped and behavior is
    unchanged.
    """
    source_config = Path(
        process_env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
    ).expanduser()
    source_credentials = source_config / ".credentials.json"
    if not source_credentials.is_file():
        return

    build_home = (Path.home() / ".drydock" / "claude-home").expanduser()
    try:
        build_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(source_credentials, build_home / ".credentials.json")
    except OSError:
        return

    process_env["HOME"] = str(build_home)
    process_env["CLAUDE_CONFIG_DIR"] = str(build_home)


def _preflight_codex_sandbox(sandbox: str) -> None:
    """Fail fast when a selected codex OS sandbox cannot be enforced on this host.

    ``danger-full-access`` runs commands directly in the invoking shell and needs no
    helper. On Linux, ``read-only`` / ``workspace-write`` are enforced by the separate
    ``codex-linux-sandbox`` helper (invoked via ``bwrap``); when it is absent every
    model-generated command fails mid-build with an opaque error. Detect that here and
    raise a clear, classified error instead. macOS uses the built-in Seatbelt sandbox,
    so no helper check applies there.
    """
    if sandbox == "danger-full-access":
        return
    if sys.platform == "linux" and shutil.which("codex-linux-sandbox") is None:
        raise LlmConfigurationError(
            f"execution environment unavailable: codex sandbox {sandbox!r} requires the "
            "'codex-linux-sandbox' helper, which is not installed on this host.\n"
            "  Install the helper, or set codex_sandbox to 'danger-full-access' "
            "(runs in the invoking shell).\n"
            "  Configure with: drydock config set codex_sandbox danger-full-access"
        )


def _isolate_codex_env(process_env: dict[str, str]) -> None:
    """Point the ``codex`` subprocess at a dedicated CODEX_HOME.

    The subprocess reads a clean ``~/.drydock/codex-home`` instead of the user's real
    ``$CODEX_HOME`` / ``~/.codex``, so it inherits none of the user's config, rules,
    hooks, AGENTS, memories, history, or session state. Only ``auth.json`` is copied in
    when present so subscription/API login continues to work.

    The directory is deliberately persistent rather than a temporary one. ``codex``
    refuses to install its PATH helper binaries beneath a temporary directory, and then
    retries a model refresh every few minutes, leaking a hung child process on every
    attempt. Those children consume CPU and hold the provider's stdout pipe open. A
    Drydock-owned directory outside ``/tmp`` avoids that failure mode without weakening
    isolation: ``--ignore-user-config``, ``--ignore-rules``, and ``--ephemeral`` already
    suppress ambient configuration, and nothing but Drydock writes here.

    Mutates ``process_env`` in place.
    """
    source_home = Path(process_env.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    build_home = (Path.home() / ".drydock" / "codex-home").expanduser()
    build_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    source_auth = source_home / "auth.json"
    if source_auth.is_file():
        shutil.copy2(source_auth, build_home / "auth.json")
    process_env["CODEX_HOME"] = str(build_home)


def _events(raw: str) -> list[dict[str, Any]]:
    parsed = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            parsed.append(event)
    return parsed


def _text_from_event(llm: str, event: Mapping[str, Any]) -> str | None:
    event_type = event.get("type")
    if llm == "claude":
        nested = event.get("event")
        if isinstance(nested, Mapping):
            return _text_from_event(llm, nested)
        if event_type == "text":
            return str(event.get("text") or "")
        if event_type == "content_block_delta":
            delta = event.get("delta")
            if isinstance(delta, Mapping) and delta.get("type") == "text_delta":
                return str(delta.get("text") or "")
        return None

    item = event.get("item")
    if isinstance(item, Mapping) and item.get("type") == "agent_message":
        return str(item.get("text") or "")
    if event_type in {"agent_message", "message"}:
        return str(event.get("text") or event.get("message") or "")
    return None


def _activity_from_event(llm: str, event: Mapping[str, Any]) -> str | None:
    """Render provider tool activity as a console-only progress line.

    Deliberately separate from ``_text_from_event``: that function also feeds
    ``_stream_text``, which builds ``LlmResult.text``, and ``build_run`` parses that text
    for the agent's reported result. Shell command lines must never enter it.

    Returns ``None`` for events that are not tool activity. The two-space indent matches
    the CLI's status-line prefixes so whole lines are newline-terminated on the console.
    """
    if llm != "codex":
        return None
    item = event.get("item")
    if not isinstance(item, Mapping) or item.get("type") != "command_execution":
        return None
    event_type = event.get("type")
    if event_type == "item.started":
        command = " ".join(str(item.get("command") or "").split())
        if not command:
            return None
        if len(command) > _ACTIVITY_COMMAND_LIMIT:
            command = command[: _ACTIVITY_COMMAND_LIMIT - 1] + "…"
        return f"  $ {command}"
    if event_type == "item.completed":
        exit_code = item.get("exit_code")
        return f"  -> exit {exit_code if exit_code is not None else 'unknown'}"
    return None


def _heartbeat_line(elapsed: float, idle: float) -> str:
    """Console notice proving a long, quiet provider run is still alive."""
    return f"  [running] {_duration(elapsed)} elapsed, no provider output for {_duration(idle)}"


def _duration(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    return f"{total // 60}m{total % 60:02d}s"


def _stream_text(llm: str, events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for event in events:
        text = _text_from_event(llm, event)
        if text:
            parts.append(text)
    return "".join(parts)


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _wall_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _print_run_header(*, llm: str, command_name: str, model: str | None) -> None:
    print(
        f"{_wall_time()}  Calling {llm.upper()}/{model or '-'} ({command_name})...",
        file=sys.stderr,
        flush=True,
    )


def _elapsed_ms(started_at: datetime, completed_at: datetime) -> int:
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _format_ms(milliseconds: int | None) -> str | None:
    if milliseconds is None:
        return None
    seconds = milliseconds / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {rem:.1f}s"
    hours, rem = divmod(minutes, 60)
    return f"{int(hours)}h {int(rem)}m"


def _format_cost(cost_usd: float | None) -> str | None:
    if cost_usd is None:
        return None
    return f"${cost_usd:.4f}"


def _performance_summary(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    returncode: int,
    stats: LlmStats,
    requested_model: str | None = None,
) -> str:
    model = stats.model or requested_model or "-"
    elapsed = _format_ms(stats.elapsed_ms) or "-"
    parts = [
        f"{_wall_time()}  Completed {llm.upper()}/{model} ({command_name})",
        f"rc={returncode}",
        f"elapsed={elapsed}",
    ]
    provider_duration = _format_ms(stats.duration_ms)
    if provider_duration and stats.duration_ms != stats.elapsed_ms:
        parts.append(f"provider={provider_duration}")
    if stats.turns is not None:
        parts.append(f"turns={stats.turns}")
    if stats.input_tokens is not None:
        parts.append(f"in={stats.input_tokens:,}")
    if stats.cached_input_tokens is not None:
        parts.append(f"cached={stats.cached_input_tokens:,}")
    if stats.cache_creation_input_tokens is not None:
        parts.append(f"cache_write={stats.cache_creation_input_tokens:,}")
    if stats.output_tokens is not None:
        parts.append(f"out={stats.output_tokens:,}")
        if stats.elapsed_ms and stats.elapsed_ms > 0:
            parts.append(f"tps={stats.output_tokens / (stats.elapsed_ms / 1000.0):.1f}")
    cost = _format_cost(stats.cost_usd)
    if cost is not None:
        parts.append(f"cost={cost}")
    parts.append(f"id={execution_id}")
    return "  ".join(parts)


def _prompt_breakdown_summary(command_name: str, assembly: PromptAssembly) -> list[str]:
    if command_name == "build":
        build_lines = _build_prompt_breakdown_summary(command_name, assembly)
        if build_lines is not None:
            return build_lines
    lines = [
        f"[prompt] {command_name}  parts={len(assembly.records())}  "
        f"total={assembly.total_bytes} B  est_tokens={assembly.total_tokens_estimate}"
    ]
    records = assembly.records()
    names = [Path(str(r["label"])).name for r in records]
    col_w = max((len(n) for n in names), default=0)
    toks = [f"~{r['estimated_tokens']} tok" for r in records]
    tok_w = max((len(t) for t in toks), default=0)
    for record, name, tok in zip(records, names, toks):
        lines.append(f"  [{record['order']:02d}] {name:<{col_w}}  {tok:>{tok_w}}")
    lines.append(f"[prompt] total  {assembly.total_bytes} B  ~{assembly.total_tokens_estimate} tok")
    return lines


def _pblock_body(text: str) -> str:
    start = text.find(">\n")
    end = text.rfind("</pblock>")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + 2 : end].strip()


def _build_prompt_breakdown_summary(
    command_name: str, assembly: PromptAssembly
) -> list[str] | None:
    job = next((part for part in assembly.parts if part.label == "Build block job"), None)
    stories = next((part for part in assembly.parts if part.label == "Stories in this block"), None)
    if job is None or stories is None:
        return None

    job_fields: dict[str, str] = {}
    for line in _pblock_body(job.text).splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        key, value = line[2:].split(":", 1)
        job_fields[key.strip()] = value.strip()

    story_lines = [
        line.removeprefix("- ").strip()
        for line in _pblock_body(stories.text).splitlines()
        if line.startswith("- ")
    ]
    story_count = len(story_lines)
    block = job_fields.get("BUILD_BLOCK") or job_fields.get("FEATURE_BLOCK", "(unknown)")
    lines = [
        f"PROMPT BUILD BLOCK: {block}",
        f"  stories_run={story_count}  parts={len(assembly.records())}  "
        f"total={assembly.total_bytes} B  est_tokens={assembly.total_tokens_estimate}",
        "",
        "  [STORIES RUN]",
    ]
    lines.extend(f"    {story}" for story in story_lines)

    role_labels = {
        "compass": "COMPASS - Target Orientation",
        "stack": "STACK - Technology HOW",
        "context": "CONTEXT - Read-Only Support",
        "implements": "IMPLEMENTS - Authoritative Story Specifications",
        "rules": "RULES",
    }
    records = assembly.records()
    for role in ("compass", "stack", "context", "implements", "rules"):
        role_records = [record for record in records if record.get("role") == role]
        if not role_records:
            continue
        lines.extend(["", f"  [{role_labels[role]}]"])
        name_width = max(len(Path(str(record["label"])).name) for record in role_records)
        role_width = max(len(str(record["role"])) for record in role_records)
        for record in role_records:
            name = Path(str(record["label"])).name
            lines.append(
                f"    {name:<{name_width}}  role={str(record['role']):<{role_width}}  "
                f"~{record['estimated_tokens']} tok"
            )

    instruction_records = [record for record in records if record.get("kind") == "instructions"]
    if instruction_records:
        lines.extend(["", "  [BUILD INSTRUCTIONS]"])
        for record in instruction_records:
            lines.append(f"    {record['label']}  ~{record['estimated_tokens']} tok")

    prompt_records = [record for record in records if record.get("kind") == "prompt-body"]
    if prompt_records:
        lines.extend(["", "  [AGENT TASK]"])
        for record in prompt_records:
            lines.append(f"    {record['label']}  ~{record['estimated_tokens']} tok")

    lines.extend([
        "",
        f"PROMPT TOTAL: {assembly.total_bytes} B  ~{assembly.total_tokens_estimate} tok",
    ])
    return lines


def _print_performance_summary(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    returncode: int,
    stats: LlmStats,
    requested_model: str | None = None,
) -> None:
    print(
        _performance_summary(
            llm=llm,
            command_name=command_name,
            execution_id=execution_id,
            returncode=returncode,
            stats=stats,
            requested_model=requested_model,
        ),
        file=sys.stderr,
        flush=True,
    )


def _print_prompt_breakdown(command_name: str, assembly: PromptAssembly) -> None:
    for line in _prompt_breakdown_summary(command_name, assembly):
        print(line, file=sys.stderr, flush=True)


def _parse_result(llm: str, raw: str, artifacts: ExecutionArtifacts) -> tuple[str, LlmStats]:
    events = _events(raw)
    final = next((event for event in reversed(events) if event.get("type") == "result"), {})
    usage: dict[str, Any] = {}
    model = None
    duration_ms = None
    turns = None
    cost_usd = None
    for event in events:
        model = _first(event, "model", "model_id") or model
        duration_ms = _first(event, "duration_ms") or duration_ms
        turns = _first(event, "num_turns", "turns") or turns
        cost_usd = _first(event, "total_cost_usd", "cost_usd") or cost_usd
        candidate = event.get("usage") or event.get("token_usage") or {}
        if isinstance(candidate, dict):
            usage.update(candidate)

    if llm == "claude":
        streamed_text = _stream_text(llm, events)
        text = streamed_text or str(final.get("result") or "")
    elif artifacts.output_file.exists():
        text = artifacts.output_file.read_text(encoding="utf-8", errors="replace")
    else:
        text = ""

    stats = LlmStats(
        model=model,
        duration_ms=duration_ms,
        turns=turns,
        input_tokens=_first(usage, "input_tokens", "prompt_tokens"),
        cached_input_tokens=_first(
            usage, "cache_read_input_tokens", "cached_input_tokens", "cached_tokens"
        ),
        cache_creation_input_tokens=_first(usage, "cache_creation_input_tokens", "cache_write"),
        output_tokens=_first(usage, "output_tokens", "completion_tokens"),
        cost_usd=cost_usd,
    )
    return text, stats


def _provider_error(llm: str, raw: str) -> str | None:
    """Return a concise provider error from the raw stream when one is present."""
    events = _events(raw)
    final = next((event for event in reversed(events) if event.get("type") == "result"), {})
    if final.get("is_error") or final.get("api_error_status"):
        message = str(final.get("result") or final.get("error") or "").strip()
        status = final.get("api_error_status")
        if status == 429:
            return f"provider rate limit 429: {message or 'rate limit exceeded'}"
        if status is not None:
            return f"provider error {status}: {message or 'execution failed'}"
        if message:
            return f"provider error: {message}"

    rate_limit = next(
        (event for event in reversed(events) if event.get("type") == "rate_limit_event"), None
    )
    if isinstance(rate_limit, dict):
        info = rate_limit.get("rate_limit_info")
        if isinstance(info, dict):
            limit_type = str(info.get("rateLimitType") or "rate limit")
            status = str(info.get("status") or "rejected")
            return f"provider rate limit: {limit_type} {status}"
        return "provider rate limit"
    return None


_AUTHENTICATION_ERROR_MARKERS = (
    "authentication_failed",
    "failed to authenticate",
    "oauth session expired",
    "could not be refreshed",
)


def _is_authentication_error(*texts: str | None) -> bool:
    """True when provider output indicates the CLI needs an interactive login refresh."""
    haystack = "\n".join(text for text in texts if text).lower()
    return any(marker in haystack for marker in _AUTHENTICATION_ERROR_MARKERS)


def _login_command(llm: str) -> str:
    if llm == "claude":
        return "claude"
    if llm == "codex":
        return "codex login"
    return f"{llm} login"


def _is_rate_limit_error(*texts: str | None) -> bool:
    """True when provider output indicates a quota/session/rate-limit block."""
    haystack = "\n".join(text for text in texts if text).lower()
    return "rate limit" in haystack or "session limit" in haystack


def provider_unavailable_reason(*texts: str | None) -> str | None:
    """Why a further provider call would certainly fail, or None when one is worth making.

    Callers that want to spend a second LLM call after a failure — the standoff diagnosis —
    consult this first so an exhausted or unauthenticated provider is never called twice.
    """
    if _is_authentication_error(*texts):
        return "provider authentication required"
    if _is_rate_limit_error(*texts):
        return "provider rate limit"
    return None


def render_fatal_provider_error_block(
    *,
    llm: str,
    command_name: str,
    execution_id: str | None,
    error: str,
    title: str,
    action_lines: tuple[str, ...],
) -> str:
    border = "*" * 78
    lines = [
        border,
        f"* {title}",
        "*",
        f"* Drydock could not run '{command_name}' with the {llm} provider.",
        "*",
        "* Details:",
        f"*   {error}",
        "*",
        "* Required action:",
        *(f"*   {line}" for line in action_lines),
        "*",
    ]
    if execution_id:
        lines.append(f"* execution_id: {execution_id}")
    lines.append(border)
    return "\n".join(lines)


def render_rate_limit_error_block(
    *,
    error: str,
    llm: str = "claude",
    command_name: str = "build",
    execution_id: str | None = None,
) -> str:
    return render_fatal_provider_error_block(
        llm=llm,
        command_name=command_name,
        execution_id=execution_id,
        error=error,
        title="FATAL ERROR - PROVIDER RATE LIMIT",
        action_lines=(
            "Wait for the provider quota or session limit to reset,",
            "or switch the configured LLM provider/model, then rerun the Drydock command.",
        ),
    )


def _print_fatal_provider_error(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    error: str,
    title: str,
    action_lines: tuple[str, ...],
) -> None:
    print(
        render_fatal_provider_error_block(
            llm=llm,
            command_name=command_name,
            execution_id=execution_id,
            error=error,
            title=title,
            action_lines=action_lines,
        ),
        file=sys.stderr,
        flush=True,
    )


def _print_authentication_required(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    error: str,
) -> None:
    _print_fatal_provider_error(
        llm=llm,
        command_name=command_name,
        execution_id=execution_id,
        error=error,
        title="FATAL ERROR - LLM AUTHENTICATION REQUIRED",
        action_lines=(
            "Refresh the CLI login, then rerun the Drydock command:",
            _login_command(llm),
        ),
    )


def _print_rate_limit_required(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    error: str,
) -> None:
    print(
        render_rate_limit_error_block(
            llm=llm,
            command_name=command_name,
            execution_id=execution_id,
            error=error,
        ),
        file=sys.stderr,
        flush=True,
    )


def _print_provider_failure(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    error: str,
) -> None:
    _print_fatal_provider_error(
        llm=llm,
        command_name=command_name,
        execution_id=execution_id,
        error=error,
        title="FATAL ERROR - LLM PROVIDER ERROR",
        action_lines=("Review the provider error and rerun the Drydock command.",),
    )


def _print_llm_failure_block(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    error: str,
    provider_error: str | None,
    raw_output: str,
) -> None:
    if _is_authentication_error(error, provider_error, raw_output):
        _print_authentication_required(
            llm=llm,
            command_name=command_name,
            execution_id=execution_id,
            error=error,
        )
        return
    if _is_rate_limit_error(error, provider_error, raw_output):
        _print_rate_limit_required(
            llm=llm,
            command_name=command_name,
            execution_id=execution_id,
            error=error,
        )
        return
    if provider_error:
        _print_provider_failure(
            llm=llm,
            command_name=command_name,
            execution_id=execution_id,
            error=error,
        )
        return


def _record(
    *,
    artifacts: ExecutionArtifacts,
    command_name: str,
    llm: str,
    model: str | None,
    command: tuple[str, ...],
    working_directory: Path,
    parameters: Mapping[str, Any],
    target: str,
    started_at: datetime,
    completed_at: datetime,
    returncode: int | None,
    stats: LlmStats,
    error: str | None,
    timed_out: bool,
    prompt_assembly: PromptAssembly,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "execution_id": artifacts.execution_id,
        "status": "succeeded" if returncode == 0 else "failed",
        "started_at": isoformat(started_at),
        "completed_at": isoformat(completed_at),
        "job": {
            "command_name": command_name,
            "llm": llm,
            "model": model,
            "target": target,
            "argv": list(command),
            "working_directory": str(working_directory),
            "parameters": dict(parameters),
        },
        "prompt": {
            "path": str(artifacts.prompt_file),
            "sha256": sha256_file(artifacts.prompt_file),
            "bytes": artifacts.prompt_file.stat().st_size,
            "total_tokens_estimate": prompt_assembly.total_tokens_estimate,
            "parts": prompt_assembly.records(),
        },
        "artifacts": artifacts.paths(),
        "result": {
            "returncode": returncode,
            "stats": asdict(stats),
            "raw_sha256": sha256_file(artifacts.raw_file) if artifacts.raw_file.exists() else None,
            "output_sha256": (
                sha256_file(artifacts.output_file) if artifacts.output_file.exists() else None
            ),
            "error": error,
            "timed_out": timed_out,
        },
    }


def _structured_event(
    *,
    artifacts: ExecutionArtifacts,
    level: str,
    name: str,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "drydock.event",
        "schema_version": 1,
        "timestamp": isoformat(utc_now()),
        "level": level,
        "execution_id": artifacts.execution_id,
        "event": name,
        **dict(fields or {}),
    }


def _emit_event(
    _artifacts: ExecutionArtifacts,
    event: dict[str, Any],
    on_event: EventCallback | None,
) -> None:
    if on_event is not None:
        on_event(event)


def _read_stream(
    stream,
    name: str,
    messages: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        for line in iter(stream.readline, ""):
            messages.put((name, line))
    finally:
        stream.close()
        messages.put((name, None))


def _new_session_kwargs() -> dict[str, Any]:
    """Spawn the provider as its own session/process-group leader.

    This makes every descendant addressable as one group, and makes that group disjoint
    from Drydock's own, so signalling it can never reach Drydock. It also means the
    terminal no longer delivers SIGINT to the provider on Ctrl-C; ``_interrupt_group``
    forwards it deliberately instead.
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _capture_process_group(process: subprocess.Popen[str]) -> int | None:
    """Record the provider's process-group id at spawn time.

    This must be captured while the provider is alive and held for the rest of the run:
    once ``wait()`` reaps the provider its pid is gone, so ``getpgid`` would fail and the
    surviving descendants -- the whole reason the group exists -- could never be signalled.

    Returns ``None`` when the group cannot be signalled: the test double (no ``pid``),
    platforms without process groups, or a group shared with Drydock itself, where
    signalling would kill Drydock.
    """
    if not hasattr(os, "killpg") or not hasattr(os, "getpgid"):
        return None
    try:
        pgid = os.getpgid(process.pid)
        if pgid == os.getpgid(0):
            return None
    except (AttributeError, TypeError, OSError):
        return None
    return pgid


def _signal_group(pgid: int | None, sig: int) -> bool:
    if pgid is None:
        return False
    try:
        os.killpg(pgid, sig)
    except OSError:
        return False
    return True


def _group_is_empty(pgid: int | None) -> bool:
    if pgid is None:
        return True
    try:
        os.killpg(pgid, 0)
    except OSError:
        return True
    return False


def _reap_process_group(pgid: int | None, logger=None) -> None:
    """Kill descendants that outlived the provider.

    Shell commands the provider ran inherit its stdout/stderr pipes; a survivor holds
    them open and keeps burning CPU. Escalate SIGTERM then SIGKILL across the whole
    group. Signalling the group also releases the pipes, letting the reader threads
    reach EOF and exit on their own.
    """
    if pgid is None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if _group_is_empty(pgid):
            return
        if not _signal_group(pgid, sig):
            return
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if _group_is_empty(pgid):
                return
            time.sleep(0.05)
        if logger is not None:
            logger.warning("provider process group survived %s; escalating", sig.name)


def _terminate(process: subprocess.Popen[str], pgid: int | None = None) -> None:
    """Stop the provider and every process it spawned."""
    if not _signal_group(pgid, signal.SIGTERM):
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if not _signal_group(pgid, signal.SIGKILL):
            process.kill()
        process.wait()
    _reap_process_group(pgid)


def _interrupt_group(process: subprocess.Popen[str], pgid: int | None) -> None:
    """Forward Ctrl-C to the provider, then stop it outright.

    ``_new_session_kwargs`` detaches the provider from the terminal's foreground group,
    so SIGINT no longer reaches it automatically. Send it explicitly and give the
    provider a moment to shut down cleanly before escalating.
    """
    if _signal_group(pgid, signal.SIGINT):
        try:
            process.wait(timeout=2)
            _reap_process_group(pgid)
            return
        except subprocess.TimeoutExpired:
            pass
    _terminate(process, pgid)


def _run_streaming_process(
    command: tuple[str, ...],
    *,
    prompt: str,
    working_directory: Path,
    process_env: Mapping[str, str],
    llm: str,
    artifacts: ExecutionArtifacts,
    logger,
    timeout_seconds: float | None,
    on_text: TextCallback | None,
    on_event: EventCallback | None,
) -> tuple[int, str, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=working_directory,
        env=process_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        **_new_session_kwargs(),
    )
    # Capture the group while the provider is alive; after ``wait()`` its pid is gone.
    pgid = _capture_process_group(process)
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.write(prompt)
    process.stdin.close()

    messages: queue.Queue[tuple[str, str | None]] = queue.Queue()
    threads = [
        threading.Thread(
            target=_read_stream, args=(process.stdout, "stdout", messages), daemon=True
        ),
        threading.Thread(
            target=_read_stream, args=(process.stderr, "stderr", messages), daemon=True
        ),
    ]
    for thread in threads:
        thread.start()

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    open_streams = 2
    started = time.monotonic()
    timed_out = False
    # Completion is driven by process exit, not pipe EOF.  ``quiet_since`` marks when the
    # pipes went silent after the provider exited; ``last_activity`` drives the heartbeat.
    quiet_since: float | None = None
    last_activity = started
    last_heartbeat = started
    try:
        with (
            artifacts.raw_file.open("w", encoding="utf-8", newline="\n") as raw_stream,
            artifacts.stderr_file.open("w", encoding="utf-8", newline="\n") as stderr_stream,
        ):
            while open_streams:
                if (
                    not timed_out
                    and timeout_seconds is not None
                    and time.monotonic() - started >= timeout_seconds
                ):
                    timed_out = True
                    logger.error("execution timeout after %ss", timeout_seconds)
                    _terminate(process, pgid)
                try:
                    source, line = messages.get(timeout=0.1)
                except queue.Empty:
                    now = time.monotonic()
                    if process.poll() is not None:
                        # The provider is gone.  Anything still holding the pipes open is
                        # a descendant that outlived it, so stop waiting on EOF.
                        if quiet_since is None:
                            quiet_since = now
                        elif now - quiet_since >= _DRAIN_GRACE_SECONDS:
                            logger.warning(
                                "provider exited but %s pipe(s) are still held by "
                                "surviving descendants; abandoning them",
                                open_streams,
                            )
                            break
                    elif on_text is not None and now - last_heartbeat >= _HEARTBEAT_SECONDS:
                        last_heartbeat = now
                        on_text(_heartbeat_line(now - started, now - last_activity))
                    continue
                quiet_since = None
                last_activity = time.monotonic()
                last_heartbeat = last_activity
                if line is None:
                    open_streams -= 1
                    continue
                if source == "stderr":
                    stderr_parts.append(line)
                    stderr_stream.write(line)
                    stderr_stream.flush()
                    logger.debug("provider stderr: %s", line.rstrip())
                    continue

                stdout_parts.append(line)
                raw_stream.write(line)
                raw_stream.flush()
                try:
                    provider_event = json.loads(line)
                except json.JSONDecodeError:
                    provider_event = None
                if not isinstance(provider_event, dict):
                    continue
                # Claude emits a content-block boundary for each assistant turn,
                # but its text deltas carry no terminating newline.  Preserve the
                # boundary for live console consumers so progress updates cannot
                # be concatenated into one line.
                event = provider_event.get("event")
                if (
                    llm == "claude"
                    and isinstance(event, Mapping)
                    and event.get("type") == "content_block_start"
                    and on_text is not None
                ):
                    content_block = event.get("content_block")
                    if isinstance(content_block, Mapping) and content_block.get("type") == "text":
                        on_text("\n")
                _emit_event(
                    artifacts,
                    _structured_event(
                        artifacts=artifacts,
                        level="DEBUG",
                        name="provider.event",
                        fields={
                            "llm": llm,
                            "provider_event_type": provider_event.get("type"),
                            "provider_event": provider_event,
                        },
                    ),
                    on_event,
                )
                text = _text_from_event(llm, provider_event)
                if text and on_text is not None:
                    on_text(text)
                if on_text is not None:
                    activity = _activity_from_event(llm, provider_event)
                    if activity:
                        on_text(activity)
    except KeyboardInterrupt:
        logger.warning("execution interrupted")
        _interrupt_group(process, pgid)
        raise

    # Wait for the provider itself before reaping. A provider that closed its pipes but is
    # still working must not be killed; only descendants that outlive it are fair game.
    # ``_terminate`` has already reaped on the timeout path.
    returncode = 124 if timed_out else process.wait()
    if not timed_out:
        _reap_process_group(pgid, logger)

    # Reaping releases any pipe a survivor held, so the reader threads can now finish.
    for thread in threads:
        thread.join(timeout=1)

    return returncode, "".join(stdout_parts), "".join(stderr_parts), timed_out


def run_prompt(
    prompt: str,
    working_directory: Path,
    *,
    llm: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    codex_sandbox: str | None = None,
    command_name: str = "prompt",
    parameters: Mapping[str, Any] | None = None,
    debug: bool = False,
    timeout_seconds: float | None = None,
    allow_tools: bool = False,
    log_dir: Path | None = None,
    target: str = "",
    on_text: TextCallback | None = None,
    on_event: EventCallback | None = None,
    announce: bool = True,
    prompt_assembly: PromptAssembly | None = None,
) -> LlmResult:
    """Run a fully assembled prompt and persist reproducible execution evidence.

    ``allow_tools`` lets the provider edit files in ``working_directory`` (used by
    ``drydock build``); it is off by default so text-only commands keep their
    deterministic-write contract.

    ``effort`` selects the provider's reasoning depth. It is off by default, so a command
    that does not ask for it keeps the provider's own default behavior.
    """
    selected = (llm or get_llm_provider()).lower()
    conflict = provider_model_conflict(selected, model)
    if conflict is not None:
        raise LlmConfigurationError(conflict)
    effort = normalize_effort(effort)

    working_directory = working_directory.expanduser().resolve()
    if not working_directory.is_dir():
        raise LlmConfigurationError(f"Working directory does not exist: {working_directory}")

    sandbox = get_codex_sandbox(codex_sandbox) if selected == "codex" else "danger-full-access"
    if selected == "codex":
        _preflight_codex_sandbox(sandbox)

    assembly = prompt_assembly or PromptAssembly.single_prompt(prompt)
    prompt = assembly.rendered_text

    artifacts = ExecutionArtifacts.create(
        working_directory, command_name, selected, log_dir=log_dir, target=target
    )
    prompt_bytes = prompt.encode("utf-8")
    artifacts.prompt_file.write_bytes(prompt_bytes)
    command = _command(
        selected,
        working_directory,
        artifacts,
        model,
        allow_tools,
        codex_sandbox=sandbox,
        effort=effort,
    )
    job_parameters = dict(parameters or {})
    logger = create_execution_logger(artifacts.execution_id, debug=debug)
    started_at = utc_now()
    if announce:
        _print_run_header(llm=selected, command_name=command_name, model=model)
    logger.info(
        "execution started id=%s command=%s llm=%s cwd=%s prompt_sha256=%s prompt_bytes=%d",
        artifacts.execution_id,
        command_name,
        selected,
        working_directory,
        sha256_bytes(prompt_bytes),
        len(prompt_bytes),
    )
    logger.debug("argv=%r parameters=%r artifacts=%r", command, job_parameters, artifacts.paths())
    for line in _prompt_breakdown_summary(command_name, assembly):
        logger.info("%s", line)
    if debug:
        _print_prompt_breakdown(command_name, assembly)
    _emit_event(
        artifacts,
        _structured_event(
            artifacts=artifacts,
            level="INFO",
            name="execution.started",
            fields={
                "command_name": command_name,
                "llm": selected,
                "model": model,
                "argv": list(command),
                "working_directory": str(working_directory),
                "parameters": job_parameters,
                "prompt_path": str(artifacts.prompt_file),
                "prompt_sha256": sha256_bytes(prompt_bytes),
                "prompt_bytes": len(prompt_bytes),
                "prompt_total_tokens_estimate": assembly.total_tokens_estimate,
            },
        ),
        on_event,
    )

    process_env = os.environ.copy()
    process_env.pop("ANTHROPIC_API_KEY", None)
    process_env.pop("OPENAI_API_KEY", None)
    process_env.pop("OPENAI_BASE_URL", None)
    if selected == "claude":
        _isolate_claude_env(process_env)
    elif selected == "codex":
        _isolate_codex_env(process_env)

    try:
        returncode, raw_output, stderr, timed_out = _run_streaming_process(
            command,
            prompt=prompt,
            working_directory=working_directory,
            process_env=process_env,
            llm=selected,
            artifacts=artifacts,
            logger=logger,
            timeout_seconds=timeout_seconds,
            on_text=on_text,
            on_event=on_event,
        )
        # Prune before the record is built so ``artifacts.paths()`` reflects what survives.
        artifacts.prune_empty()
        text, stats = _parse_result(selected, raw_output, artifacts)
        provider_error = _provider_error(selected, raw_output)
        if selected == "claude":
            artifacts.output_file.write_text(text, encoding="utf-8", newline="\n")
        completed_at = utc_now()
        elapsed_ms = _elapsed_ms(started_at, completed_at)
        stats = LlmStats(**{**asdict(stats), "elapsed_ms": elapsed_ms})
        error = (
            (
                stderr.strip()
                or ("execution timed out" if timed_out else None)
                or (provider_error if returncode else None)
            )
            if returncode
            else None
        )
        if returncode and error:
            _print_llm_failure_block(
                llm=selected,
                command_name=command_name,
                execution_id=artifacts.execution_id,
                error=error,
                provider_error=provider_error,
                raw_output=raw_output,
            )
        record = _record(
            artifacts=artifacts,
            command_name=command_name,
            llm=selected,
            model=model,
            command=command,
            working_directory=working_directory,
            parameters=job_parameters,
            target=target,
            started_at=started_at,
            completed_at=completed_at,
            returncode=returncode,
            stats=stats,
            error=error,
            timed_out=timed_out,
            prompt_assembly=assembly,
        )
        append_execution_record(artifacts.records_file, record)
        _emit_event(
            artifacts,
            _structured_event(
                artifacts=artifacts,
                level="INFO" if returncode == 0 else "ERROR",
                name="execution.completed",
                fields={
                    "returncode": returncode,
                    "timed_out": timed_out,
                    "elapsed_ms": elapsed_ms,
                    "stats": asdict(stats),
                    "error": error,
                },
            ),
            on_event,
        )
        log_method = logger.info if returncode == 0 else logger.error
        log_method(
            "execution completed id=%s returncode=%d duration_ms=%s turns=%s "
            "input_tokens=%s output_tokens=%s",
            artifacts.execution_id,
            returncode,
            stats.duration_ms,
            stats.turns,
            stats.input_tokens,
            stats.output_tokens,
        )
        _print_performance_summary(
            llm=selected,
            command_name=command_name,
            execution_id=artifacts.execution_id,
            returncode=returncode,
            stats=stats,
            requested_model=model,
        )
        return LlmResult(
            execution_id=artifacts.execution_id,
            llm=selected,
            command=command,
            working_directory=working_directory,
            returncode=returncode,
            text=text,
            stderr=stderr or provider_error or "",
            stats=stats,
            artifacts=artifacts,
            record=record,
        )
    except OSError as exc:
        completed_at = utc_now()
        artifacts.stderr_file.write_text(str(exc), encoding="utf-8", newline="\n")
        stats = LlmStats()
        record = _record(
            artifacts=artifacts,
            command_name=command_name,
            llm=selected,
            model=model,
            command=command,
            working_directory=working_directory,
            parameters=job_parameters,
            target=target,
            started_at=started_at,
            completed_at=completed_at,
            returncode=None,
            stats=stats,
            error=str(exc),
            timed_out=False,
            prompt_assembly=assembly,
        )
        append_execution_record(artifacts.records_file, record)
        _emit_event(
            artifacts,
            _structured_event(
                artifacts=artifacts,
                level="ERROR",
                name="execution.failed",
                fields={"error": str(exc)},
            ),
            on_event,
        )
        logger.exception("execution failed id=%s", artifacts.execution_id)
        raise LlmError(
            f"Could not run {selected}; execution_id={artifacts.execution_id}: {exc}"
        ) from exc
    except KeyboardInterrupt:
        completed_at = utc_now()
        stats = LlmStats()
        record = _record(
            artifacts=artifacts,
            command_name=command_name,
            llm=selected,
            model=model,
            command=command,
            working_directory=working_directory,
            parameters=job_parameters,
            target=target,
            started_at=started_at,
            completed_at=completed_at,
            returncode=130,
            stats=stats,
            error="execution interrupted",
            timed_out=False,
            prompt_assembly=assembly,
        )
        append_execution_record(artifacts.records_file, record)
        _emit_event(
            artifacts,
            _structured_event(
                artifacts=artifacts,
                level="WARNING",
                name="execution.interrupted",
            ),
            on_event,
        )
        raise
    finally:
        close_execution_logger(logger)
