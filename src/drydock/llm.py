"""Subscription-authenticated Claude and Codex CLI execution."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from drydock.config import get_llm_provider
from drydock.errors import LlmConfigurationError, LlmError
from drydock.execution import (
    ExecutionArtifacts,
    append_event,
    append_execution_record,
    isoformat,
    sha256_bytes,
    sha256_file,
    utc_now,
)
from drydock.logging import close_execution_logger, create_execution_logger
from drydock.prompt_assembly import PromptAssembly


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


def _command(
    llm: str,
    working_directory: Path,
    artifacts: ExecutionArtifacts,
    model: str | None,
    allow_tools: bool = False,
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
        return tuple(command)
    if llm == "codex":
        command = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(working_directory),
            "--json",
            "--output-last-message",
            str(artifacts.output_file),
        ]
        if model:
            command.extend(("--model", model))
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


def _isolate_codex_env(process_env: dict[str, str]) -> Path:
    """Point the ``codex`` subprocess at a dedicated temporary CODEX_HOME.

    The subprocess reads a clean runtime directory instead of the user's real
    ``$CODEX_HOME`` / ``~/.codex``, so it inherits none of the user's config,
    rules, hooks, AGENTS, memories, history, or session state. Only ``auth.json``
    is copied in when present so subscription/API login continues to work.

    Mutates ``process_env`` in place and returns the temporary directory so the
    caller can remove it after the subprocess exits.
    """
    source_home = Path(
        process_env.get("CODEX_HOME") or Path.home() / ".codex"
    ).expanduser()
    build_home = Path(tempfile.mkdtemp(prefix="drydock-codex-home-"))
    build_home.chmod(0o700)
    source_auth = source_home / "auth.json"
    if source_auth.is_file():
        shutil.copy2(source_auth, build_home / "auth.json")
    process_env["CODEX_HOME"] = str(build_home)
    return build_home


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


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


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
) -> str:
    model = stats.model or "-"
    elapsed = _format_ms(stats.elapsed_ms) or "-"
    parts = [
        f"[llm] {command_name} {llm}/{model}",
        f"rc={returncode}",
        f"elapsed={elapsed}",
    ]
    provider_duration = _format_ms(stats.duration_ms)
    if provider_duration and stats.duration_ms != stats.elapsed_ms:
        parts.append(f"provider={provider_duration}")
    if stats.turns is not None:
        parts.append(f"turns={stats.turns}")
    if stats.input_tokens is not None:
        parts.append(f"in={stats.input_tokens}")
    if stats.cached_input_tokens is not None:
        parts.append(f"cached={stats.cached_input_tokens}")
    if stats.cache_creation_input_tokens is not None:
        parts.append(f"cache_write={stats.cache_creation_input_tokens}")
    if stats.output_tokens is not None:
        parts.append(f"out={stats.output_tokens}")
        if stats.elapsed_ms and stats.elapsed_ms > 0:
            parts.append(f"out_tps={stats.output_tokens / (stats.elapsed_ms / 1000.0):.1f}")
    cost = _format_cost(stats.cost_usd)
    if cost is not None:
        parts.append(f"cost={cost}")
    parts.append(f"id={execution_id}")
    return "  ".join(parts)


def _prompt_breakdown_summary(command_name: str, assembly: PromptAssembly) -> list[str]:
    lines = [
        f"[prompt] {command_name}  parts={len(assembly.records())}  "
        f"total={assembly.total_bytes} B  est_tokens={assembly.total_tokens_estimate}"
    ]
    for record in assembly.records():
        role = f"  {record['role']}" if record.get("role") else ""
        lines.append(
            f"  [{record['order']:02d}] {record['label']}  "
            f"~{record['estimated_tokens']} tok{role}"
        )
    lines.append(
        f"[prompt] total  {assembly.total_bytes} B  ~{assembly.total_tokens_estimate} tok"
    )
    return lines


def _print_performance_summary(
    *,
    llm: str,
    command_name: str,
    execution_id: str,
    returncode: int,
    stats: LlmStats,
) -> None:
    print(
        _performance_summary(
            llm=llm,
            command_name=command_name,
            execution_id=execution_id,
            returncode=returncode,
            stats=stats,
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
        text = str(final.get("result") or "")
    elif artifacts.output_file.exists():
        text = artifacts.output_file.read_text(encoding="utf-8", errors="replace")
    else:
        text = ""

    stats = LlmStats(
        model=model,
        duration_ms=duration_ms,
        turns=turns,
        input_tokens=_first(usage, "input_tokens", "prompt_tokens"),
        cached_input_tokens=_first(usage, "cache_read_input_tokens", "cached_tokens"),
        cache_creation_input_tokens=_first(usage, "cache_creation_input_tokens", "cache_write"),
        output_tokens=_first(usage, "output_tokens", "completion_tokens"),
        cost_usd=cost_usd,
    )
    return text, stats


def _record(
    *,
    artifacts: ExecutionArtifacts,
    command_name: str,
    llm: str,
    model: str | None,
    command: tuple[str, ...],
    working_directory: Path,
    parameters: Mapping[str, Any],
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
    artifacts: ExecutionArtifacts,
    event: dict[str, Any],
    on_event: EventCallback | None,
) -> None:
    append_event(artifacts.events_file, event)
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


def _terminate(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


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
    )
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
                    _terminate(process)
                try:
                    source, line = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
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
    except KeyboardInterrupt:
        logger.warning("execution interrupted")
        _terminate(process)
        raise

    if timed_out:
        for thread in threads:
            thread.join(timeout=1)
        return 124, "".join(stdout_parts), "".join(stderr_parts), True
    return process.wait(), "".join(stdout_parts), "".join(stderr_parts), False


def run_prompt(
    prompt: str,
    working_directory: Path,
    *,
    llm: str | None = None,
    model: str | None = None,
    command_name: str = "prompt",
    parameters: Mapping[str, Any] | None = None,
    debug: bool = False,
    timeout_seconds: float | None = None,
    allow_tools: bool = False,
    log_dir: Path | None = None,
    target: str = "",
    on_text: TextCallback | None = None,
    on_event: EventCallback | None = None,
    prompt_assembly: PromptAssembly | None = None,
) -> LlmResult:
    """Run a fully assembled prompt and persist reproducible execution evidence.

    ``allow_tools`` lets the provider edit files in ``working_directory`` (used by
    ``drydock build``); it is off by default so text-only commands keep their
    deterministic-write contract.
    """
    selected = (llm or get_llm_provider()).lower()
    if selected not in {"claude", "codex"}:
        raise LlmConfigurationError(f"Unsupported LLM: {selected!r}")

    working_directory = working_directory.expanduser().resolve()
    if not working_directory.is_dir():
        raise LlmConfigurationError(f"Working directory does not exist: {working_directory}")

    assembly = prompt_assembly or PromptAssembly.single_prompt(prompt)
    prompt = assembly.rendered_text

    artifacts = ExecutionArtifacts.create(
        working_directory, command_name, selected, log_dir=log_dir, target=target
    )
    prompt_bytes = prompt.encode("utf-8")
    artifacts.prompt_file.write_bytes(prompt_bytes)
    command = _command(selected, working_directory, artifacts, model, allow_tools)
    job_parameters = dict(parameters or {})
    logger = create_execution_logger(artifacts.execution_id, artifacts.log_file, debug=debug)
    started_at = utc_now()
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
    cleanup_dir: Path | None = None
    if selected == "claude":
        _isolate_claude_env(process_env)
    elif selected == "codex":
        cleanup_dir = _isolate_codex_env(process_env)

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
        text, stats = _parse_result(selected, raw_output, artifacts)
        if selected == "claude":
            artifacts.output_file.write_text(text, encoding="utf-8", newline="\n")
        completed_at = utc_now()
        elapsed_ms = _elapsed_ms(started_at, completed_at)
        stats = LlmStats(**{**asdict(stats), "elapsed_ms": elapsed_ms})
        error = (
            (stderr.strip() or ("execution timed out" if timed_out else None))
            if returncode
            else None
        )
        record = _record(
            artifacts=artifacts,
            command_name=command_name,
            llm=selected,
            model=model,
            command=command,
            working_directory=working_directory,
            parameters=job_parameters,
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
        )
        return LlmResult(
            execution_id=artifacts.execution_id,
            llm=selected,
            command=command,
            working_directory=working_directory,
            returncode=returncode,
            text=text,
            stderr=stderr,
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
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        close_execution_logger(logger)
