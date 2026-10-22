"""Claude, Codex, and Gemini CLI execution behind one adapter."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from drydock import model_config
from drydock.artifact_blocks import pair_artifact_delimiters
from drydock.config import (
    LLM_PROVIDERS,
    get_codex_sandbox,
    get_effort,
    get_haiku_thinking_tokens,
    get_llm_provider,
    get_max_output_tokens,
)
from drydock.config import normalize_effort as config_normalize_effort
from drydock.errors import ConfigurationError, LlmConfigurationError, LlmError
from drydock.execution import (
    ExecutionArtifacts,
    append_execution_record,
    format_ms,
    isoformat,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from drydock.llm_usage import normalize_tokens
from drydock.logging import close_execution_logger, create_execution_logger
from drydock.output_format import OutputFormat, clean_output
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
    # Set when the provider exited cleanly but Drydock judged the response unusable.
    failure: str | None = None
    # The provider's own account of why it failed, extracted from its structured output.
    # Kept apart from ``stderr`` so callers can report the cause without the console noise
    # and stack frames that surround it.
    provider_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.failure is None


@dataclass
class ClaudePromptSession:
    """Choose Claude Code session arguments for one logical, in-process prompt sequence.

    A session resumes only when the next complete prompt byte-prefixes the previous one.  A
    different prompt or model deliberately starts a new session, preventing unrelated work from
    inheriting stale conversation context.  ``context_reused`` covers a deliberate delta prompt:
    the caller has retained the prior context in Claude and sends only its appended instruction.
    """

    session_id: str | None = None
    _prompt: str | None = field(default=None, init=False, repr=False)
    _model: str | None = field(default=None, init=False, repr=False)

    def invocation(
        self, prompt: str, model: str | None, *, context_reused: bool = False
    ) -> dict[str, str]:
        same_model = self._model == model
        extends_prior = self._prompt is not None and prompt.startswith(self._prompt)
        if self.session_id and same_model and (context_reused or extends_prior):
            self._prompt = prompt
            return {"claude_resume_session_id": self.session_id}
        self.session_id = str(uuid.uuid4())
        self._prompt = prompt
        self._model = model
        return {"claude_session_id": self.session_id}


TextCallback = Callable[[str], None]
EventCallback = Callable[[Mapping[str, Any]], None]


SUPPORTED_PROVIDERS = LLM_PROVIDERS

# Substrings that unambiguously identify which provider a model name belongs to.
# Used only to catch a clear cross-provider mismatch (e.g. codex + opus) up front;
# an unrecognized model name is left alone because Drydock does not enumerate every
# valid model a provider CLI accepts.
_MODEL_FAMILY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude", ("claude", "opus", "sonnet", "haiku", "fable")),
    ("codex", ("gpt-", "gpt5", "codex", "luna", "o3-", "o4-")),
    ("gemini", ("gemini", "gemma")),
)


def _model_provider_family(model: str) -> str | None:
    """Return the provider a model name clearly belongs to, or ``None`` if unknown."""
    lowered = model.lower().strip()
    for provider, markers in _MODEL_FAMILY_MARKERS:
        if any(marker in lowered for marker in markers):
            return provider
    return None


def resolve_provider(cli_provider: str | None, model: str | None) -> str:
    """Return the provider to run, given an optional explicit choice and the model.

    A model name states which provider serves it, so naming the provider as well is
    redundant: ``--model gemini-3.5-flash`` can only run on gemini. The model therefore
    selects the provider whenever its family is recognized, and ``--llm-provider`` is needed
    only for a model name Drydock does not recognize.

    An explicit ``--llm-provider`` still wins, and is still checked against the model by
    :func:`provider_model_conflict`, so a contradiction is reported rather than silently
    resolved one way or the other.
    """
    if cli_provider:
        return get_llm_provider(cli_provider)
    family = _model_provider_family(model or "")
    if family is not None:
        return family
    return get_llm_provider()


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


# The effort ladder is Drydock's, defined once in config; each provider maps onto it below.
# Higher levels buy deeper deliberation at the cost of latency and spend, so effort is opt-in.

# codex takes no --effort flag: the level rides in as a config override. Its ladder tops out
# at xhigh, and xhigh is served only by the codex-max model family; every other model clamps
# to high. The mapping is lossy in one direction only — a codex run is never given less
# effort than the next level down from what was asked for.
_CODEX_EFFORT: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}
_CODEX_XHIGH_MODELS = ("-codex-max",)


def normalize_effort(effort: str | None) -> str | None:
    """Validate a requested effort level, or ``None`` when the provider default stands."""
    try:
        return config_normalize_effort(effort)
    except ConfigurationError as exc:
        raise LlmConfigurationError(str(exc)) from None


def codex_effort(effort: str, model: str | None) -> str:
    """Map a Drydock effort level onto what this codex model actually serves."""
    level = _CODEX_EFFORT[effort]
    if level == "xhigh" and not any(
        family in (model or "").lower() for family in _CODEX_XHIGH_MODELS
    ):
        return "high"
    return level


def _command(
    llm: str,
    working_directory: Path,
    artifacts: ExecutionArtifacts,
    model: str | None,
    allow_tools: bool = False,
    codex_sandbox: str = "danger-full-access",
    effort: str | None = None,
    claude_session_id: str | None = None,
    claude_resume_session_id: str | None = None,
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
        # The tool surface is model_config.jsonl's provider row. Text-only commands consume
        # model text and write their own artifacts, so they get no tools; a build gets only
        # what a code builder uses. Every enabled tool's schema is sent with every request.
        # --strict-mcp-config with no --mcp-config suppresses MCP tool descriptions; without
        # it, a tool-less Claude emits tool-call XML as text.
        command.extend(_provider_args("claude", allow_tools))
        if claude_session_id:
            command.extend(("--session-id", claude_session_id))
        if claude_resume_session_id:
            command.extend(("--resume", claude_resume_session_id))
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
            # Build directories are created from the Target workspace and need not
            # be Git repositories.  Drydock supplies the working root explicitly
            # and runs Codex with an isolated, ephemeral configuration.
            "--skip-git-repo-check",
            "--sandbox",
            codex_sandbox,
            "--cd",
            str(working_directory),
            "--json",
            "--output-last-message",
            str(artifacts.output_file),
        ]
        command.extend(_provider_args("codex", allow_tools))
        if model:
            command.extend(("--model", model))
        if effort:
            command.extend(("-c", f"model_reasoning_effort={codex_effort(effort, model)}"))
        command.append("-")
        return tuple(command)
    if llm == "gemini":
        command = [
            "gemini",
            # Headless gemini refuses an untrusted workspace. Drydock supplies the working
            # root itself, so the refusal only blocks a run Drydock already authorized.
            "--skip-trust",
            "--output-format",
            "json",
        ]
        # ``plan`` is read-only: the model may inspect the working directory but cannot
        # write it. That is the gemini equivalent of claude's empty tool list — text-only
        # commands write their own artifacts and a writable agent would bypass them.
        command.extend(("--approval-mode", "yolo" if allow_tools else "plan"))
        command.extend(_provider_args("gemini", allow_tools))
        if model:
            command.extend(("--model", model))
        # ``-p`` is what selects headless mode; the prompt itself arrives on stdin, which
        # gemini prepends to the (empty) flag value. Passing a megabyte prompt as an argv
        # entry would risk the argument-length limit.
        command.extend(("--prompt", ""))
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


def _isolate_gemini_env(process_env: dict[str, str]) -> None:
    """Point the ``gemini`` subprocess at a dedicated config home.

    ``gemini`` reads ``~/.gemini`` for settings, extensions, skills, hooks, MCP servers, and
    ``GEMINI.md`` context. None of it belongs in a Drydock run, whose prompt is assembled
    deterministically. Overriding ``HOME`` leaves the CLI a clean tree it populates itself.

    Authentication is unaffected: gemini reads ``GEMINI_API_KEY`` from the environment, which
    is inherited rather than stored under the isolated home.

    Mutates ``process_env`` in place.
    """
    build_home = (Path.home() / ".drydock" / "gemini-home").expanduser()
    try:
        build_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return
    process_env["HOME"] = str(build_home)


def _provider_args(provider: str, allow_tools: bool) -> tuple[str, ...]:
    """The provider's tool-surface arguments for this run mode, from ``model_config.jsonl``."""
    try:
        return model_config.load().provider(provider).args(allow_tools)
    except ConfigurationError as exc:
        raise LlmConfigurationError(str(exc)) from None


#: Claude sessions started or resumed in this process: session id -> (model, context tokens at
#: exit). A resumed request resends that context ahead of its new prompt, so the price-limit
#: check counts it.
_CLAUDE_SESSIONS: dict[str, tuple[str | None, int]] = {}


def _prompt_limit_escalation(
    model: str | None,
    prompt_size: int,
    *,
    allow_tools: bool,
    resume_session_id: str | None,
) -> model_config.Escalation | None:
    prior = _CLAUDE_SESSIONS.get(resume_session_id or "")
    try:
        return model_config.escalation(
            model,
            prompt_size,
            allow_tools=allow_tools,
            prior_context_tokens=prior[1] if prior else 0,
        )
    except ConfigurationError as exc:
        raise LlmConfigurationError(str(exc)) from None


def _record_calibration(
    artifacts: ExecutionArtifacts,
    raw_output: str,
    *,
    model: str | None,
    allow_tools: bool,
    prompt_size: int,
    command_name: str,
    session_id: str | None,
    resumed: bool,
) -> None:
    """Append this run's measured first request to ``model_calibration.jsonl``.

    Evidence only: the live ``model_config.jsonl`` changes solely through
    ``drydock config calibrate --apply``. A failure to record never fails the run.
    """
    usage = model_config.claude_request_usage(_events(raw_output))
    if session_id and usage.last_request_tokens:
        _CLAUDE_SESSIONS[session_id] = (model, usage.last_request_tokens)
    if not usage.first_request_tokens or not model:
        return
    observation = model_config.Observation(
        at=isoformat(utc_now()),
        model=model,
        resolved_model=usage.resolved_model,
        provider="claude",
        mode="build" if allow_tools else "text",
        cli_version=usage.cli_version,
        prompt_bytes=prompt_size,
        first_request_tokens=usage.first_request_tokens,
        resumed=resumed,
        probe=command_name == CALIBRATION_PROBE_COMMAND,
    )
    try:
        model_config.record_observation(artifacts.records_file.parent, observation)
    except OSError:
        pass


#: ``command_name`` of the trivial-prompt runs ``drydock config calibrate --probe`` makes.
CALIBRATION_PROBE_COMMAND = "calibrate_probe"


def _takes_thinking_budget(model: str | None) -> bool:
    """True for a model family whose ``model_config.jsonl`` row says ``thinking: budget``.

    Haiku 4.x takes a fixed thinking budget; later models size thinking from effort and reject
    a budget. The bare ``haiku`` alias selects the current Haiku and therefore gets no budget.
    """
    if not model:
        return False
    try:
        return model_config.load().model(model).thinking == "budget"
    except ConfigurationError:
        return False


def _apply_claude_token_limits(process_env: dict[str, str], model: str | None) -> None:
    """Set the Claude CLI's output ceiling and, for Haiku 4.x only, its thinking budget.

    Drydock owns both, so a value inherited from the caller's shell is replaced. The CLI caps
    ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` at the model's maximum. A fixed thinking budget never
    reaches any other model: they size thinking from effort, and later models reject a budget.

    Mutates ``process_env`` in place.
    """
    process_env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(get_max_output_tokens())
    if _takes_thinking_budget(model):
        process_env["MAX_THINKING_TOKENS"] = str(get_haiku_thinking_tokens())
    else:
        process_env.pop("MAX_THINKING_TOKENS", None)


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


@dataclass(frozen=True)
class OutputTruncation:
    """A Claude response cut off at its output-token ceiling.

    ``output_tokens`` is the ceiling as the provider reports it, which is the effective limit
    after the CLI capped the requested one at the model's maximum. ``open_artifact`` names the
    artifact block the cut landed inside, when the response was emitting one.
    """

    output_tokens: int | None
    thinking_tokens: int | None
    open_artifact: str | None


def _token_count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _claude_truncation(raw: str) -> OutputTruncation | None:
    """The first response in a Claude stream that stopped on ``max_tokens``, or ``None``.

    The CLI answers a cut-off response by asking the model to resume in a new message, so the
    joined text can look complete. Only the provider's stop reason shows that it is not.
    """
    parts: list[str] = []
    for event in _events(raw):
        text = _text_from_event("claude", event)
        if text:
            parts.append(text)
            continue
        nested = event.get("event")
        if not isinstance(nested, Mapping) or nested.get("type") != "message_delta":
            continue
        delta = nested.get("delta")
        if not isinstance(delta, Mapping) or delta.get("stop_reason") != "max_tokens":
            continue
        usage = nested.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        details = usage.get("output_tokens_details")
        details = details if isinstance(details, Mapping) else {}
        unclosed = pair_artifact_delimiters("".join(parts)).unclosed
        return OutputTruncation(
            output_tokens=_token_count(usage.get("output_tokens")),
            thinking_tokens=_token_count(details.get("thinking_tokens")),
            open_artifact=unclosed[-1] if unclosed else None,
        )
    return None


def _truncation_detail(truncation: OutputTruncation) -> str:
    size = f" of {truncation.output_tokens} tokens" if truncation.output_tokens else ""
    thinking = (
        f" ({truncation.thinking_tokens} spent on thinking)" if truncation.thinking_tokens else ""
    )
    where = f" inside {truncation.open_artifact}" if truncation.open_artifact else ""
    return (
        f"The model reached its output-token limit{size}{thinking} and its response was cut "
        f"off{where}. The response is incomplete, so nothing it produced was used."
    )


def _truncation_actions(truncation: OutputTruncation, model: str | None) -> tuple[str, ...]:
    lines: list[str] = []
    if _takes_thinking_budget(model):
        budget = get_haiku_thinking_tokens()
        if budget > 0:
            lines.append(f"Lower the Haiku thinking budget (now {budget}), then rerun:")
            lines.append(f"  drydock config set haiku_thinking_tokens {budget // 2}")
    else:
        lines.append("Reduce thinking: rerun with --effort low (or --effort medium).")
    requested = get_max_output_tokens()
    reached = truncation.output_tokens
    if reached is not None and reached < requested:
        lines.append(
            f"{reached} tokens is this model's output maximum; a larger model allows more."
        )
    else:
        lines.append(f"Or raise the output limit (now {requested}); the CLI caps it at the")
        lines.append("model's maximum:  drydock config set max_output_tokens <tokens>")
    return tuple(lines)


def _print_truncation_block(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    truncation: OutputTruncation,
    model: str | None,
) -> None:
    _print_fatal_provider_error(
        llm=llm,
        command_name=command_name,
        execution_id=execution_id,
        error=_truncation_detail(truncation),
        title="FATAL ERROR - LLM OUTPUT TRUNCATED",
        action_lines=_truncation_actions(truncation, model),
    )


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _wall_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _announce(artifacts: ExecutionArtifacts, line: str, *, console: bool = True) -> None:
    """Record one line of run telemetry, and show it on the console when it is progress.

    Every line reaches ``<stem>.llm.log``, so a ``.stderr.log`` alongside an execution still
    means something went wrong. Only progress reaches stdout: a call starting and finishing is
    what an operator watches a long command for. Token and cost accounting is not progress —
    it is billing evidence, read from the LLM log after the fact, so ``console=False`` keeps it
    out of the command's own output.
    """
    if console:
        print(line, flush=True)
    artifacts.record_activity(line)


def _print_run_header(
    artifacts: ExecutionArtifacts, *, llm: str, command_name: str, model: str | None
) -> None:
    _announce(
        artifacts,
        f"{_wall_time()}  Calling {llm.upper()}/{model or '-'} ({command_name})...",
    )


def _claude_session_metadata(
    *, claude_session_id: str | None, claude_resume_session_id: str | None
) -> dict[str, str] | None:
    """Describe an explicit Claude Code session without deriving it from argv."""
    if claude_session_id:
        return {"mode": "start", "id": claude_session_id}
    if claude_resume_session_id:
        return {"mode": "resume", "id": claude_resume_session_id}
    return None


def _elapsed_ms(started_at: datetime, completed_at: datetime) -> int:
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _format_cost(cost_usd: float | None) -> str | None:
    if cost_usd is None:
        return None
    return f"${cost_usd:.4f}"


def format_token_summary(stats: LlmStats | None, *, llm: str | None) -> str | None:
    """Render one call's token accounting, or ``None`` when the provider reported none.

    Provider token conventions differ (codex counts cache reads inside ``input_tokens``,
    claude does not); normalization is delegated to :func:`llm_usage.normalize_tokens`. Every
    surface reports the billed split rather than the raw one: ``cached`` is the cache-read
    share of the input, ``uncached`` is the remainder charged at full rate, and ``out`` is the
    generated tokens. The two input figures sum to everything sent to the model.
    """
    if stats is None:
        return None
    fields = asdict(stats)
    if all(
        fields.get(name) is None
        for name in (
            "input_tokens",
            "cached_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
        )
    ):
        return None
    total_input, cached, output = normalize_tokens(llm or "", fields)
    parts: list[str] = []
    if total_input:
        hit = f" ({cached / total_input:.0%} hit)" if cached else ""
        parts.append(f"cached={cached:,}{hit}")
        parts.append(f"uncached={max(total_input - cached, 0):,}")
    if stats.cache_creation_input_tokens:
        parts.append(f"write {stats.cache_creation_input_tokens:,}")
    if output:
        parts.append(f"out={output:,}")
    cost = _format_cost(stats.cost_usd)
    if cost is not None:
        parts.append(f"cost={cost}")
    parts = [part for part in parts if part]
    return " · ".join(parts) if parts else None


def _performance_summary(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    returncode: int,
    stats: LlmStats,
    requested_model: str | None = None,
) -> str:
    _ = execution_id  # Retained for the internal execution-evidence call contract.
    model = stats.model or requested_model or "-"
    elapsed = format_ms(stats.elapsed_ms) or "-"
    detail_parts = [f"elapsed={elapsed}"]
    provider_duration = format_ms(stats.duration_ms)
    if provider_duration and stats.duration_ms != stats.elapsed_ms:
        detail_parts.append(f"provider={provider_duration}")
    if stats.turns is not None:
        detail_parts.append(f"turns={stats.turns}")
    tokens = format_token_summary(stats, llm=llm)
    if tokens:
        detail_parts.extend(tokens.split(" · "))
    if stats.output_tokens and stats.elapsed_ms and stats.elapsed_ms > 0:
        detail_parts.append(f"tps={stats.output_tokens / (stats.elapsed_ms / 1000.0):.1f}")
    return (
        f"  Completed {llm.upper()}/{model} ({command_name})  rc={returncode}\n"
        f"    {'   '.join(detail_parts)}"
    )


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
    artifacts: ExecutionArtifacts,
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    returncode: int,
    stats: LlmStats,
    requested_model: str | None = None,
    console: bool = True,
) -> None:
    summary = _performance_summary(
        llm=llm,
        command_name=command_name,
        execution_id=execution_id,
        returncode=returncode,
        stats=stats,
        requested_model=requested_model,
    )
    # The headline states that the call finished and with what exit code — progress. The
    # detail line below it is token and cost accounting, which is written to the LLM log only.
    headline, _, accounting = summary.partition("\n")
    _announce(artifacts, headline, console=console)
    if accounting:
        _announce(artifacts, accounting, console=False)


def _print_prompt_breakdown(
    artifacts: ExecutionArtifacts, command_name: str, assembly: PromptAssembly
) -> None:
    for line in _prompt_breakdown_summary(command_name, assembly):
        _announce(artifacts, line)


def _gemini_payload(raw: str) -> dict[str, Any]:
    """Return the single JSON object ``gemini --output-format json`` writes, or ``{}``.

    Unlike claude and codex, gemini emits one pretty-printed object at the end of the run
    rather than a stream of records, so the whole transcript is parsed at once. The CLI may
    precede it with unstructured console notices and, on a failure, a stack trace whose final
    frame ends in a brace-delimited fragment that is not JSON. Every brace is therefore tried
    in turn and the object carrying ``response`` or ``error`` wins, so a leading fragment
    cannot mask the payload behind it.
    """
    text = raw.strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    fallback: dict[str, Any] = {}
    start = text.find("{")
    while start >= 0:
        try:
            payload, _end = decoder.raw_decode(text[start:])
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            if "response" in payload or "error" in payload:
                return payload
            fallback = fallback or payload
        start = text.find("{", start + 1)
    return fallback


def _gemini_model_stats(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce gemini's per-model accounting to one call's totals.

    A single invocation bills more than one model: a small router model classifies the
    request before the main model answers it. Every model's tokens are charged, so the
    totals sum across all of them, while the reported model name is the one that served
    the ``main`` role — naming the router would misreport what produced the response.
    """
    stats = payload.get("stats")
    models = stats.get("models") if isinstance(stats, Mapping) else None
    if not isinstance(models, Mapping):
        return {}

    total_input = cached = output = requests = latency = 0
    main_model: str | None = None
    busiest: tuple[int, str | None] = (-1, None)
    for name, entry in models.items():
        if not isinstance(entry, Mapping):
            continue
        tokens = entry.get("tokens") if isinstance(entry.get("tokens"), Mapping) else {}
        api = entry.get("api") if isinstance(entry.get("api"), Mapping) else {}
        # ``input`` already contains the cached prefix; ``candidates`` and ``thoughts`` are
        # both generated and both billed as output.
        model_input = _int_or_zero(tokens.get("input"))
        total_input += model_input
        cached += _int_or_zero(tokens.get("cached"))
        output += _int_or_zero(tokens.get("candidates")) + _int_or_zero(tokens.get("thoughts"))
        requests += _int_or_zero(api.get("totalRequests"))
        latency += _int_or_zero(api.get("totalLatencyMs"))
        roles = entry.get("roles")
        if isinstance(roles, Mapping) and "main" in roles:
            main_model = str(name)
        if model_input > busiest[0]:
            busiest = (model_input, str(name))

    return {
        "model": main_model or busiest[1],
        "input_tokens": total_input,
        "cached_input_tokens": cached,
        "output_tokens": output,
        "turns": requests or None,
        "duration_ms": latency or None,
    }


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_gemini_result(raw: str) -> tuple[str, LlmStats]:
    payload = _gemini_payload(raw)
    totals = _gemini_model_stats(payload)
    return str(payload.get("response") or ""), LlmStats(
        model=totals.get("model"),
        duration_ms=totals.get("duration_ms"),
        turns=totals.get("turns"),
        input_tokens=totals.get("input_tokens"),
        cached_input_tokens=totals.get("cached_input_tokens"),
        output_tokens=totals.get("output_tokens"),
        # gemini reports no per-call cost and no separate cache-write category.
        cost_usd=None,
    )


def _parse_result(llm: str, raw: str, artifacts: ExecutionArtifacts) -> tuple[str, LlmStats]:
    if llm == "gemini":
        return _parse_gemini_result(raw)
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


def _gemini_error(raw: str, stderr: str = "") -> str | None:
    """Return the failure gemini reported in its JSON payload, when it reported one.

    A failed gemini run replaces ``response`` with an ``error`` object carrying the message
    and the CLI's exit code. When the run fails before any response is produced the CLI writes
    that payload to stderr and leaves stdout empty, so both streams are searched: a model that
    no longer exists is reported only on stderr, and losing it there leaves the operator with a
    bare exit code.
    """
    error = _gemini_payload(raw).get("error")
    if not error and stderr:
        error = _gemini_payload(stderr).get("error")
    if isinstance(error, Mapping):
        message = str(error.get("message") or error.get("type") or "").strip()
    else:
        message = str(error or "").strip()
    if not message:
        return None
    if _is_rate_limit_error(message):
        return f"provider rate limit: {message}"
    return f"provider error: {message}"


# Console notices every run emits, carrying no information about a failure. Dropping them is
# what lets the real cause be the first thing an operator reads.
_STDERR_NOISE: tuple[str, ...] = (
    "warning: true color",
    "ripgrep is not available",
)


def _stderr_reason(stderr: str) -> str | None:
    """Return the first stderr line that explains a failure, ignoring routine notices.

    Stack frames are dropped: the message above them is the cause, and the frames below it are
    the provider CLI's internals, which no Drydock operator can act on.
    """
    for line in stderr.splitlines():
        line = line.strip()
        if not line or line.startswith("at ") or line in "{}":
            continue
        if any(marker in line.lower() for marker in _STDERR_NOISE):
            continue
        return line
    return None


def failure_reason(result: LlmResult) -> str | None:
    """Return the most specific available explanation for a failed run, or ``None``.

    Prefers Drydock's own judgement, then the provider's structured error, then the first
    informative stderr line. Long messages are truncated: the first sentence of a provider
    error names the problem, and the evidence files hold the rest.

    Fields are read defensively. LLM-assisted commands are tested through injected fake
    runners, which return result-like stand-ins rather than a full ``LlmResult``; a shared
    reporting helper must not oblige every fake in the suite to grow a field it never sets.
    """
    reason = (
        getattr(result, "failure", None)
        or getattr(result, "provider_error", None)
        or _stderr_reason(getattr(result, "stderr", "") or "")
    )
    if not reason:
        return None
    reason = " ".join(reason.split())
    return reason if len(reason) <= 400 else reason[:397] + "..."


def failure_detail(result: LlmResult, summary: str = "LLM execution failed") -> str:
    """Return ``summary`` with the cause appended, for reporting a failed run to an operator.

    A bare summary tells an operator only that something went wrong, leaving the cause in an
    evidence file they have no reason to suspect exists. A retired model, an expired key, and a
    rate limit are all actionable, and all indistinguishable without this.
    """
    reason = failure_reason(result)
    return f"{summary}: {reason}" if reason else summary


def _provider_error(llm: str, raw: str, stderr: str = "") -> str | None:
    """Return a concise provider error from the raw stream when one is present."""
    if llm == "gemini":
        return _gemini_error(raw, stderr)
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
            if _is_rate_limit_error(message):
                return f"provider rate limit: {message}"
            return f"provider error: {message}"

    rate_limit = next(
        (event for event in reversed(events) if event.get("type") == "rate_limit_event"), None
    )
    if isinstance(rate_limit, dict):
        info = rate_limit.get("rate_limit_info")
        if isinstance(info, dict):
            limit_type = str(info.get("rateLimitType") or "rate limit")
            status = str(info.get("status") or "rejected")
            # Claude reports quota state on every healthy call too. Only a refusal is an error;
            # naming an ``allowed`` window the cause would misclassify an unrelated failure as a
            # rate limit and send the operator away to wait for a reset that changes nothing.
            if not status.startswith("allowed"):
                return f"provider rate limit: {limit_type} {status}"
        else:
            return "provider rate limit"

    message = _stream_error_message(events)
    if message:
        if _is_rate_limit_error(message):
            return f"provider rate limit: {message}"
        return f"provider error: {message}"
    return None


#: Codex reports a refused turn as its own stream event rather than a terminal ``result`` record.
#: Both carry the operator-facing explanation (quota exhausted, provider outage), so the message is
#: read from whichever event the provider emitted.
_STREAM_ERROR_EVENT_TYPES = ("turn.failed", "error", "stream_error")


def _stream_error_message(events: list[dict[str, Any]]) -> str | None:
    """Return the message from a stream-level provider error event, when one is present."""
    for event in reversed(events):
        if event.get("type") not in _STREAM_ERROR_EVENT_TYPES:
            continue
        error = event.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
        else:
            message = str(error or "").strip()
        message = message or str(event.get("message") or "").strip()
        if message:
            return message
    return None


_AUTHENTICATION_ERROR_MARKERS = (
    "authentication_failed",
    # gemini, which has no login subcommand and fails this way when its key is unset.
    "please set an auth method",
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
    if llm == "gemini":
        # gemini has no login subcommand: headless authentication is an environment variable.
        return "export GEMINI_API_KEY=..."
    return f"{llm} login"


#: Providers name the same exhausted-quota condition differently: Claude blocks on a "rate limit",
#: "session limit", or "spend limit", Codex on a "usage limit". All are the same operator action —
#: wait for the reset, raise the limit, or switch provider — so all must classify as a rate limit.
_RATE_LIMIT_MARKERS = (
    "rate limit",
    "session limit",
    "usage limit",
    "spend limit",
    "limit reached",
    "quota",
    # gemini's wording for an exhausted per-minute or per-day allowance.
    "resource has been exhausted",
)


def _is_rate_limit_error(*texts: str | None) -> bool:
    """True when provider output indicates a quota/session/rate-limit block."""
    haystack = "\n".join(text for text in texts if text).lower()
    return any(marker in haystack for marker in _RATE_LIMIT_MARKERS)


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


#: A provider that answered 5xx, or could not be reached, is down; another call fails the same way.
_OUTAGE_STATUS = re.compile(r"provider error 5\d\d\b")
_OUTAGE_MARKERS = (
    "overloaded",
    "service unavailable",
    "temporarily unavailable",
    "internal server error",
    "bad gateway",
    "gateway timeout",
    "connection refused",
    "connection reset",
    "could not connect",
    "stream disconnected",
)


@dataclass(frozen=True)
class FatalStop:
    """The provider failure that ended this process's LLM work."""

    kind: str
    message: str
    llm: str
    command_name: str
    execution_id: str

    def recovery(self) -> str:
        """The operator's way back, one instruction per line."""
        if self.kind == "provider rate limit":
            return (
                "Wait for the provider limit to reset (the reason above names when), or switch\n"
                "provider or model with --llm-provider / --model."
            )
        if self.kind == "provider authentication required":
            return f"Log in again: {_login_command(self.llm)}"
        if self.kind == "provider timeout":
            return (
                "Check the provider's status and the network. A timed-out call may already have\n"
                "spent tokens, so Drydock does not retry it on its own."
            )
        if self.kind == "provider outage":
            return "Check the provider's status page; rerun once it recovers, or switch provider."
        return f"Install or repair the {self.llm} CLI so it runs from this shell."


_fatal: FatalStop | None = None


def fatal_stop_reason(
    error: str | None, provider_error: str | None, raw_output: str = "", *, timed_out: bool = False
) -> str | None:
    """Why no further call to this provider can succeed in this run, or None when one can.

    Rate limits, expired logins, timeouts, and outages are fatal. A malformed or truncated
    response is not: its shape is observed and the calling command repairs or retries it.
    """
    if (reason := provider_unavailable_reason(error, provider_error, raw_output)) is not None:
        return reason
    if timed_out:
        return "provider timeout"
    haystack = "\n".join(text for text in (error, provider_error) if text).lower()
    if _OUTAGE_STATUS.search(haystack) or any(marker in haystack for marker in _OUTAGE_MARKERS):
        return "provider outage"
    return None


def fatal_stop() -> FatalStop | None:
    """The fatal provider failure this process recorded, if any."""
    return _fatal


def reset_fatal_stop() -> None:
    global _fatal
    _fatal = None


def _record_fatal_stop(stop: FatalStop) -> None:
    """Keep the first fatal failure; later ones are its consequences."""
    global _fatal
    if _fatal is None:
        _fatal = stop


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
    full_cli: str | None = None,
    sub_command: str | None = None,
    truncation: Mapping[str, Any] | None = None,
    failed: bool = False,
    claude_session_id: str | None = None,
    claude_resume_session_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "execution_id": artifacts.execution_id,
        "status": "succeeded" if returncode == 0 and not failed else "failed",
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
            "full_cli": full_cli,
            "sub_command": sub_command,
            "claude_session": _claude_session_metadata(
                claude_session_id=claude_session_id,
                claude_resume_session_id=claude_resume_session_id,
            ),
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
            "timing": {
                "client_elapsed_ms": _elapsed_ms(started_at, completed_at),
                "llm_server_duration_ms": stats.duration_ms,
            },
            "raw_sha256": sha256_file(artifacts.raw_file) if artifacts.raw_file.exists() else None,
            "output_sha256": (
                sha256_file(artifacts.output_file) if artifacts.output_file.exists() else None
            ),
            "error": error,
            "timed_out": timed_out,
            "truncation": dict(truncation) if truncation is not None else None,
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
        encoding="utf-8",
        errors="replace",
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
    announce_completion: bool = True,
    prompt_assembly: PromptAssembly | None = None,
    full_cli: str | None = None,
    sub_command: str | None = None,
    claude_session_id: str | None = None,
    claude_resume_session_id: str | None = None,
    output_format: OutputFormat | None = None,
) -> LlmResult:
    """Run a fully assembled prompt and persist reproducible execution evidence.

    ``allow_tools`` lets the provider edit files in ``working_directory`` (used by
    ``drydock build``); it is off by default so text-only commands keep their
    deterministic-write contract.

    ``effort`` selects the provider's reasoning depth. An explicit level wins; otherwise the
    configured ``drydock_effort`` applies, and with neither set the provider's own default
    stands. The level is mapped to what the selected provider and model actually serve.

    ``output_format`` opts into narrow wrapper cleanup. Original output remains evidence;
    cleanup is recorded separately. Callers still validate bodies and own retry budgets.
    """
    if output_format not in (None, "artifacts", "json"):
        raise LlmConfigurationError(f"Unsupported output format: {output_format}")
    debug = debug or os.environ.get("DRYDOCK_DEBUG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    selected = (llm or get_llm_provider()).lower()
    if claude_session_id and claude_resume_session_id:
        raise LlmConfigurationError("Claude session start and resume cannot be used together.")
    if (claude_session_id or claude_resume_session_id) and selected != "claude":
        raise LlmConfigurationError("Claude session options require the claude provider.")
    conflict = provider_model_conflict(selected, model)
    if conflict is not None:
        raise LlmConfigurationError(conflict)
    effort = normalize_effort(effort) if effort else get_effort()

    working_directory = working_directory.expanduser().resolve()
    if not working_directory.is_dir():
        raise LlmConfigurationError(f"Working directory does not exist: {working_directory}")

    sandbox = get_codex_sandbox(codex_sandbox) if selected == "codex" else "danger-full-access"
    if selected == "codex":
        if not allow_tools:
            # codex exec always carries a shell tool; there is no --tools "" equivalent,
            # so the sandbox is the only lever. Text-only commands consume model text and
            # write their own artifacts — a writable codex edits the target and returns a
            # narrative summary, which the caller then writes over the file it just wrote.
            # read-only is Drydock's floor for these commands and overrides any configured
            # sandbox; codex enforces it natively, so the helper preflight does not apply.
            sandbox = "read-only"
        else:
            _preflight_codex_sandbox(sandbox)

    assembly = prompt_assembly or PromptAssembly.single_prompt(prompt)
    prompt = assembly.rendered_text
    prompt_bytes = prompt.encode("utf-8")

    # A model with a price-tier limit runs a prompt that would cross it on its escalation
    # model instead. Decided here, the single adapter, so every command gets the same rule.
    escalated = _prompt_limit_escalation(
        model,
        len(prompt_bytes),
        allow_tools=allow_tools,
        resume_session_id=claude_resume_session_id,
    )
    if escalated is not None:
        model = escalated.to_model
        conflict = provider_model_conflict(selected, model)
        if conflict is not None:
            raise LlmConfigurationError(f"escalate_model: {conflict}")

    if _fatal is not None:
        # One fatal failure ends this process's provider work. A retry loop above this call
        # would otherwise resubmit into the same limit, outage, or timeout, and a timed-out
        # call may already have spent its tokens.
        raise LlmError(
            f"{_fatal.kind}: {command_name} was not sent; execution {_fatal.execution_id} "
            f"already failed fatally: {_fatal.message}"
        )
    artifacts = ExecutionArtifacts.create(
        working_directory, command_name, selected, log_dir=log_dir, target=target
    )
    artifacts.prompt_file.write_bytes(prompt_bytes)
    command = _command(
        selected,
        working_directory,
        artifacts,
        model,
        allow_tools,
        codex_sandbox=sandbox,
        effort=effort,
        claude_session_id=claude_session_id,
        claude_resume_session_id=claude_resume_session_id,
    )
    job_parameters = dict(parameters or {})
    if escalated is not None:
        job_parameters["escalation"] = escalated.describe()
    claude_session = _claude_session_metadata(
        claude_session_id=claude_session_id,
        claude_resume_session_id=claude_resume_session_id,
    )
    logger = create_execution_logger(artifacts.execution_id, debug=debug)
    started_at = utc_now()
    # The console names the stage; evidence keeps the bare command so usage classification holds.
    display_name = f"{command_name} · {sub_command}" if sub_command else command_name
    if announce:
        _print_run_header(artifacts, llm=selected, command_name=display_name, model=model)
    if escalated is not None:
        _announce(artifacts, f"  {escalated.describe()}", console=announce)
    if claude_session is not None:
        _announce(
            artifacts,
            f"  Claude session: {claude_session['mode']} id={claude_session['id']}",
            console=announce,
        )
    logger.info(
        "execution started id=%s command=%s llm=%s cwd=%s prompt_sha256=%s prompt_bytes=%d "
        "claude_session=%s",
        artifacts.execution_id,
        command_name,
        selected,
        working_directory,
        sha256_bytes(prompt_bytes),
        len(prompt_bytes),
        claude_session,
    )
    logger.debug("argv=%r parameters=%r artifacts=%r", command, job_parameters, artifacts.paths())
    for line in _prompt_breakdown_summary(command_name, assembly):
        logger.info("%s", line)
    if debug:
        _print_prompt_breakdown(artifacts, command_name, assembly)
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
                "claude_session": claude_session,
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
        _apply_claude_token_limits(process_env, model)
    elif selected == "codex":
        _isolate_codex_env(process_env)
    elif selected == "gemini":
        _isolate_gemini_env(process_env)

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
        if selected == "claude" and returncode == 0:
            _record_calibration(
                artifacts,
                raw_output,
                model=model,
                allow_tools=allow_tools,
                prompt_size=len(prompt_bytes),
                command_name=command_name,
                session_id=claude_session_id or claude_resume_session_id,
                resumed=bool(claude_resume_session_id),
            )
        provider_error = _provider_error(selected, raw_output, stderr)
        if selected == "claude":
            artifacts.output_file.write_text(text, encoding="utf-8", newline="\n")
        truncation = _claude_truncation(raw_output) if selected == "claude" else None
        # A text-only command consumes the response as its artifact, so a cut-off response is
        # unusable even when the CLI continued it: the continuation is the model's guess at
        # where it stopped. A tool-using run keeps its work in files, where the CLI's
        # continuation is ordinary, so there the truncation is recorded and not fatal.
        failure = (
            _truncation_detail(truncation)
            if truncation is not None and not allow_tools and returncode == 0
            else None
        )
        cleanup = None
        if output_format is not None and returncode == 0 and failure is None:
            cleanup = clean_output(text, output_format)
            # Keep provider/output evidence unchanged; only the returned payload is normalized.
            text = cleanup.text
            if on_text is not None:
                for removed in cleanup.removed:
                    on_text(f"[output] {output_format} wrapper discarded: {removed.strip()!r}\n")
                if cleanup.defect:
                    on_text(
                        f"[output] {output_format}: {cleanup.defect}; retained for validation\n"
                    )
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
            else failure
        )
        if returncode and (
            kind := fatal_stop_reason(error, provider_error, raw_output, timed_out=timed_out)
        ):
            _record_fatal_stop(
                FatalStop(
                    kind,
                    " ".join((error or provider_error or kind).split())[:600],
                    selected,
                    command_name,
                    artifacts.execution_id,
                )
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
        if truncation is not None:
            logger.warning(
                "output truncated output_tokens=%s thinking_tokens=%s open_artifact=%s fatal=%s",
                truncation.output_tokens,
                truncation.thinking_tokens,
                truncation.open_artifact,
                failure is not None,
            )
        if failure is not None and truncation is not None:
            _print_truncation_block(
                llm=selected,
                command_name=command_name,
                execution_id=artifacts.execution_id,
                truncation=truncation,
                model=model or stats.model,
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
            full_cli=full_cli,
            sub_command=sub_command,
            truncation=asdict(truncation) if truncation is not None else None,
            failed=failure is not None,
            claude_session_id=claude_session_id,
            claude_resume_session_id=claude_resume_session_id,
        )
        if output_format is not None:
            record["output_contract"] = {
                "format": output_format,
                "removed": list(cleanup.removed) if cleanup else [],
                "defect": cleanup.defect if cleanup else None,
                "normalized_sha256": sha256_bytes(text.encode("utf-8")),
            }
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
            artifacts,
            llm=selected,
            command_name=display_name,
            execution_id=artifacts.execution_id,
            returncode=returncode,
            stats=stats,
            requested_model=model,
            console=announce_completion,
        )
        return LlmResult(
            execution_id=artifacts.execution_id,
            llm=selected,
            command=command,
            working_directory=working_directory,
            returncode=returncode,
            text=text,
            stderr=failure or stderr or provider_error or "",
            stats=stats,
            artifacts=artifacts,
            record=record,
            failure=failure,
            provider_error=provider_error,
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
            full_cli=full_cli,
            sub_command=sub_command,
            claude_session_id=claude_session_id,
            claude_resume_session_id=claude_resume_session_id,
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
        _record_fatal_stop(
            FatalStop(
                "provider unavailable",
                f"Could not run {selected}: {exc}",
                selected,
                command_name,
                artifacts.execution_id,
            )
        )
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
            full_cli=full_cli,
            sub_command=sub_command,
            claude_session_id=claude_session_id,
            claude_resume_session_id=claude_resume_session_id,
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
