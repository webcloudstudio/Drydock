"""Standoff diagnosis — LLM triage for failures the author cannot interpret.

A Drydock failure is worth an LLM call only when it is non-deterministic and has no single known
cause: a post-LLM :class:`~drydock.errors.RecordedError` or an unclassified exception. Everything
else — usage errors, validation findings, gate blocks, and any failure whose classification already
carries its own remediation — is answered deterministically and never reaches this module.

The diagnosis is advisory. It is printed and persisted; Drydock never acts on it and the failing
command's exit code is unaffected.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from drydock.errors import DrydockError, ErrorRecord
from drydock.llm import provider_unavailable_reason
from drydock.prompt_assembly import (
    PromptAssembly,
    fenced_block_part,
    fenced_text_part,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

DIAGNOSE_TIMEOUT_SECONDS = 90.0
PROMPT_NAME = "diagnose"
MAX_SOURCE_LINES = 200
MAX_EVIDENCE_LINES = 120
MAX_DIAGNOSIS_LINES = 6

#: Classification prefixes produced by ``build_run._classify_failure`` that already carry their own
#: structured remediation. Diagnosing them spends a call to repeat what Drydock already printed.
BLOCKED_PREFIXES = (
    "dependency legitimacy gate failed",
    "programmatic acceptance failed",
    "provider rate limit",
    "provider error",
    "execution timed out",
    "execution environment unavailable",
    "context/token limit",
)


class CompletedRun(Protocol):
    """The subset of an ``LlmResult`` this module consumes."""

    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]

_diagnosed = False


def reset_diagnosis_guard() -> None:
    """Clear the once-per-invocation guard. For tests and long-lived hosts."""
    global _diagnosed
    _diagnosed = False


def should_diagnose(
    *,
    record: ErrorRecord | None = None,
    exc: BaseException | None = None,
) -> bool:
    """Whether this failure earns a standoff diagnosis.

    Allowlisted: a post-LLM error record, and an exception that is not a ``DrydockError``.
    Blocked: deterministic Drydock errors, classifications with their own remediation, states in
    which the provider is known to be unavailable, and any second diagnosis in one invocation.
    """
    if _diagnosed:
        return False
    if isinstance(exc, KeyboardInterrupt):
        return False
    if record is not None:
        classification = (record.classification or "").strip().lower()
        if any(classification.startswith(prefix) for prefix in BLOCKED_PREFIXES):
            return False
        if provider_unavailable_reason(record.classification, record.detail) is not None:
            return False
        return True
    if exc is None:
        return False
    if isinstance(exc, DrydockError):
        return False
    if provider_unavailable_reason(str(exc)) is not None:
        return False
    return True


def render_standoff_banner(*, llm: str, model: str, command: str) -> str:
    """The block printed before the diagnostic call so the author knows why the terminal paused."""
    width = 72
    border = "=" * width
    return "\n".join([
        border,
        f"A MAJOR ERROR HAS OCCURRED — {command} has stopped.",
        f"{llm}/{model} is diagnosing. Standing off; this takes up to a minute.",
        border,
    ])


def _tail(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.strip()
    return "\n".join(["…"] + lines[-max_lines:]).strip()


def _traceback_text(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _source_region(exc: BaseException | None) -> tuple[str, Path | None]:
    """Source around the innermost frame in the drydock package, capped at MAX_SOURCE_LINES."""
    if exc is None or exc.__traceback__ is None:
        return "", None
    frames = [
        frame
        for frame in traceback.extract_tb(exc.__traceback__)
        if "drydock" in Path(frame.filename).parts
    ]
    if not frames:
        return "", None
    frame = frames[-1]
    path = Path(frame.filename)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", path
    center = (frame.lineno or 1) - 1
    half = MAX_SOURCE_LINES // 2
    start = max(0, center - half)
    end = min(len(lines), center + half)
    numbered = [f"{number + 1:5d}  {lines[number]}" for number in range(start, end)]
    return "\n".join(numbered), path


def _evidence_text(target_dir: Path, record: ErrorRecord | None) -> tuple[str, Path | None]:
    if record is None or not record.evidence:
        return "", None
    path = Path(record.evidence)
    if not path.is_absolute():
        path = target_dir / path
    if not path.is_file():
        return "", path
    try:
        return _tail(path.read_text(encoding="utf-8"), MAX_EVIDENCE_LINES), path
    except OSError:
        return "", path


def _target_state(target_dir: Path) -> list[str]:
    from drydock.metadata import parse_metadata

    metadata_path = target_dir / "METADATA.md"
    if not metadata_path.is_file():
        return []
    try:
        fields = parse_metadata(metadata_path)
    except (OSError, ValueError):
        return []
    keys = ("name", "stack", "build_state", "build_sub_state", "build_dir")
    return [f"- {key.upper()}: {fields.get(key, '') or '-'}" for key in keys]


def assemble_prompt(
    body: str,
    *,
    command: str,
    target: str,
    record: ErrorRecord | None,
    exc: BaseException | None,
    target_dir: Path,
) -> PromptAssembly:
    """Build the diagnostic prompt. Tools are off, so all evidence is injected here."""
    job = [
        "## Diagnosis job",
        "",
        f"- COMMAND: {command}",
        f"- TARGET: {target or '-'}",
    ]
    if record is not None:
        job += [
            f"- PHASE: {record.phase or '-'}",
            f"- CLASSIFICATION: {record.classification or '-'}",
            f"- STATE: {record.state or '-'}",
            f"- EXECUTION_ID: {record.execution_id or '-'}",
        ]
    elif exc is not None:
        job.append(f"- EXCEPTION: {type(exc).__name__}: {exc}")
    job += _target_state(target_dir)
    job.append("")

    parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part("Diagnosis job", job, kind="job"),
    ]

    if record is not None and record.detail.strip():
        parts.append(fenced_text_part("Error detail", record.detail, role="failure detail"))
    if record is not None and record.recovery.strip():
        parts.append(
            fenced_text_part("Recorded recovery", record.recovery, role="recorded recovery")
        )

    tb = _traceback_text(exc)
    if tb:
        parts.append(fenced_text_part("Traceback", _tail(tb, MAX_EVIDENCE_LINES), role="traceback"))

    source, source_path = _source_region(exc)
    if source:
        parts.append(
            fenced_block_part(
                str(source_path),
                source,
                fence="python",
                role="failing source",
                path=source_path,
            )
        )

    evidence, evidence_path = _evidence_text(target_dir, record)
    if evidence:
        parts.append(
            fenced_text_part(
                str(evidence_path), evidence, role="execution evidence", path=evidence_path
            )
        )

    parts += [
        section_heading_part("# Agent Task"),
        part("Prompt body", body + "\n\n", kind="prompt-body"),
    ]
    return PromptAssembly(parts=tuple(parts))


def clamp_diagnosis(text: str) -> str:
    """Keep only the contracted CAUSE/DO lines, capped at MAX_DIAGNOSIS_LINES."""
    kept: list[str] = []
    for line in text.strip().splitlines():
        stripped = line.strip().strip("`")
        if not stripped.upper().startswith(("CAUSE:", "DO:")):
            continue  # drop preamble, fences, and any commentary around the contract
        kept.append(stripped)
        if len(kept) >= MAX_DIAGNOSIS_LINES:
            break
    if kept:
        return "\n".join(kept)
    return _tail(text.strip(), MAX_DIAGNOSIS_LINES)


def diagnose(
    target_dir: Path,
    *,
    command: str,
    target: str = "",
    record: ErrorRecord | None = None,
    exc: BaseException | None = None,
    llm: str | None = None,
    model: str | None = None,
    log_dir: Path | None = None,
    runner: RunnerFn | None = None,
) -> str | None:
    """Run one diagnostic call and return the clamped diagnosis, or None.

    Never raises: a failure to diagnose must not replace or mask the failure being diagnosed.
    """
    global _diagnosed
    if _diagnosed:
        return None
    _diagnosed = True

    from drydock.llm import run_prompt

    run = runner if runner is not None else run_prompt
    try:
        prompt = load_prompt(PROMPT_NAME)
        assembly = assemble_prompt(
            prompt.body,
            command=command,
            target=target,
            record=record,
            exc=exc,
            target_dir=target_dir,
        )
        working_directory = target_dir if target_dir.is_dir() else Path.cwd()
        result = run(
            assembly.rendered_text,
            working_directory,
            llm=llm,
            model=model or prompt.model,
            command_name="diagnose",
            parameters={"diagnosed_command": command, "target": target},
            timeout_seconds=DIAGNOSE_TIMEOUT_SECONDS,
            log_dir=log_dir,
            target=target,
            on_text=None,
            prompt_assembly=assembly,
        )
    except Exception:  # noqa: BLE001 - diagnosis is advisory and must never mask the real failure
        return None

    if not result.ok or not result.text.strip():
        return None
    return clamp_diagnosis(result.text) or None
