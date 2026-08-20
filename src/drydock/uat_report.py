"""Portable proof-kit rendering for completed UAT runs.

A UAT run leaves behind command logs, LLM transcripts, a Blueprint, and delivered code.
This module turns that raw output into a self-contained, checkable receipt:

* every file under the run is inventoried with byte count and SHA-256;
* ``SHA256SUMS`` makes the whole kit verifiable with ``sha256sum -c``;
* ``index.html`` links each lifecycle command to its own stdout and stderr, states the
  verdict for the run, and never reports success that the recorded exit codes do not
  support.

Rendering is deterministic and reads only what is already on disk, so a kit can be rebuilt
for an old run without re-executing it.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from drydock.report_render import (
    _CHECK_TAGS,
    _IGNORE_NAME,
    _INDEX_NAME,
    _KIT_OUTPUTS,
    _MARKDOWN_SUFFIXES,
    _RUN_NOTES,
    _SUMS_NAME,
    ArtifactGroup,
    Check,
    FileRecord,
    _anchor,
    _cell,
    _command_by_suffix,
    _command_text,
    _evidence_link,
    _exit_state,
    _hash_file,
    _is_status_command,
    _iter_files,
    _letterhead,
    _link,
    _llm_calls,
    _llm_log_cell,
    _make_portable,
    _md_link,
    _meta,
    _page,
    _portable,
    _read_json,
    _relative,
    _render_receipt,
    _status_cell,
    _stream_link,
    _table,
    _tabs,
    _tail,
    _tokens,
    _verdict,
    _viewers,
    _write_sums,
    _write_viewers,
    inventory_panels,
    local_run_window,
    prune_generated,
    recorded_status_headline,
    run_notes,
)

__all__ = [
    "ArtifactGroup",
    "FileRecord",
    "build_case_kit",
    "build_kit_index",
    "prune_generated",
    "write_kit_index",
]

_MANIFEST_PATH = "evidence/manifest.json"
_LLM_CALL_RE = re.compile(r"\bCalling\s+[^\s/]+/\S+\s+\(([^)]+)\)\.\.\.")


def _command_llm_logs(
    case_root: Path,
    commands: Sequence[Mapping[str, object]],
    calls: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, ...], ...]:
    """Join LLM activity logs to the lifecycle command that produced them.

    A run records the execution identifiers each command created while it ran, which is an exact
    association. Banner matching against captured stdout is the fallback for runs recorded before
    that field existed; it is lossy, because a command that makes calls without printing a banner
    — ``drydock build`` does — leaves nothing to match.
    """
    by_execution = {str(call.get("execution_id") or ""): call for call in calls}
    if any(command.get("llm_executions") for command in commands):
        linked: list[tuple[str, ...]] = []
        for command in commands:
            recorded: list[str] = []
            for execution_id in command.get("llm_executions") or ():
                call = by_execution.get(str(execution_id))
                path = str(call.get("llm_log") or "") if call else ""
                if path and (case_root / path).is_file():
                    recorded.append(path)
            linked.append(tuple(recorded))
        return tuple(linked)

    pending: dict[str, list[Mapping[str, object]]] = {}
    for call in calls:
        pending.setdefault(str(call.get("command") or ""), []).append(call)

    joined: list[tuple[str, ...]] = []
    for command in commands:
        relative = _relative(command.get("stdout_path"), case_root)
        try:
            text = (case_root / relative).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            text = ""
        logs: list[str] = []
        for name in _LLM_CALL_RE.findall(text):
            queue = pending.get(name, [])
            if not queue:
                continue
            call = queue.pop(0)
            path = str(call.get("llm_log") or "")
            if path and (case_root / path).is_file():
                logs.append(path)
        joined.append(tuple(logs))
    return tuple(joined)


def _receipt_llm_logs(
    case_root: Path,
    commands: Sequence[Mapping[str, object]],
    calls: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, ...], ...]:
    """Per-step logs to link: the step's combined log when the kit wrote one, else each call."""
    per_command = _command_llm_logs(case_root, commands, calls)
    linked: list[tuple[str, ...]] = []
    for index, (command, logs) in enumerate(zip(commands, per_command, strict=True), start=1):
        combined = _step_llm_log(case_root, str(command.get("label") or f"step-{index:02d}"))
        if logs and combined.is_file():
            linked.append((combined.relative_to(case_root).as_posix(),))
        else:
            linked.append(logs)
    return tuple(linked)


def _step_llm_log(case_root: Path, label: str) -> Path:
    """Path of the one activity log a step publishes, beside its stdout and stderr."""
    return case_root / "evidence" / "commands" / f"{label}.llm.log"


def _write_step_llm_logs(
    case_root: Path,
    commands: Sequence[Mapping[str, object]],
    calls: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, ...], ...]:
    """Concatenate every model call a step made into one activity log for that step.

    A step drives as many calls as its command needs — planning drives fifteen — and linking each
    three-line log separately turns one table cell into a row of numbered links that says nothing
    about which call is which. The calls are joined in execution order under a banner naming the
    call, its command, and its execution identifier, so the step's model activity reads as one
    document alongside its stdout.

    Returns the per-command log paths the receipt should link: the combined log where one was
    written, and the individual logs for a step whose calls could not be joined.
    """
    per_command = _command_llm_logs(case_root, commands, calls)
    by_path = {str(call.get("llm_log") or ""): call for call in calls}
    linked: list[tuple[str, ...]] = []
    written: set[Path] = set()
    for index, (command, logs) in enumerate(zip(commands, per_command, strict=True), start=1):
        label = str(command.get("label") or f"step-{index:02d}")
        combined = _step_llm_log(case_root, label)
        if not logs:
            linked.append(())
            continue
        sections: list[str] = []
        for position, relative in enumerate(logs, start=1):
            call = by_path.get(relative) or {}
            banner = " · ".join(
                part
                for part in (
                    f"llm {position}/{len(logs)}",
                    str(call.get("command") or ""),
                    " ".join(
                        part for part in (call.get("provider"), call.get("model")) if part
                    ).strip(),
                    str(call.get("execution_id") or ""),
                )
                if part
            )
            try:
                body = (case_root / relative).read_text(encoding="utf-8", errors="replace")
            except OSError:
                body = ""
            sections.append(f"--- {banner} ---\n{body.rstrip()}\n")
        combined.parent.mkdir(parents=True, exist_ok=True)
        combined.write_text("\n".join(sections), encoding="utf-8")
        written.add(combined)
        linked.append((combined.relative_to(case_root).as_posix(),))
    # A rebuild after a resume renumbered or dropped steps leaves logs for steps this run no
    # longer has. They are generated, so they are replaced rather than accumulated.
    commands_root = case_root / "evidence" / "commands"
    if commands_root.is_dir():
        for stale in commands_root.glob("*.llm.log"):
            if stale not in written:
                stale.unlink()
    return tuple(linked)


# A run drives a Drydock workspace, and that workspace keeps its own copy of every prompt,
# provider transcript, and model output the run produced. Inventorying both trees whole
# publishes each transcript twice and renders an HTML viewer for both copies, which is where
# the bulk of a kit's size comes from. ``evidence/`` is the canonical home: it is the sectioned,
# reviewable record, and it holds the same bytes.
_CANONICAL_ROOT = "evidence"

_MIRRORED_ROOT = "workspace"


# Agent skill scaffolding copied in so the case could run. It is Drydock's own tooling rather
# than a record of the build, and it says nothing about what the run produced.
_UNPUBLISHED_PREFIXES = (
    f"{_MIRRORED_ROOT}/.claude/",
    f"{_MIRRORED_ROOT}/.agents/",
)


def _unpublished(canonical: Sequence[FileRecord], mirrored: Sequence[FileRecord]) -> dict[str, str]:
    """Map each withheld mirrored path to the canonical path that replaces it.

    A withheld path maps to its canonical twin, or to ``""`` when nothing replaces it because
    it was never part of the build record. One mapping drives all three consumers — the
    inventory, the ignore file, and the link remapping — so they cannot disagree about what
    the kit contains.

    Duplication is decided on the digest rather than on a list of suffixes, so a transcript
    the run names differently in the two trees is still recognised, and a mirrored file that
    is genuinely unique is never dropped. Empty files are exempt: every empty file shares one
    digest, and "this command wrote no stderr" is a fact the receipt should keep.
    """
    # Skipping empty files here is the whole exemption: nothing can match a digest the
    # canonical index never learned, so no empty mirrored file is ever withheld.
    published: dict[str, str] = {}
    for record in canonical:
        if record.bytes:
            published.setdefault(record.sha256, record.path)
    withheld: dict[str, str] = {}
    for record in mirrored:
        if record.path.startswith(_UNPUBLISHED_PREFIXES):
            withheld[record.path] = ""
        elif record.sha256 in published:
            withheld[record.path] = published[record.sha256]
    return withheld


def _case_groups(case_root: Path, target: str) -> tuple[tuple[ArtifactGroup, ...], dict[str, str]]:
    """Inventory a completed case as the four directories a run writes, plus its record.

    Returns the groups and the withheld-path mapping described by :func:`_unpublished`, which
    the caller writes out as the run's ignore file and uses to redirect recorded links onto
    the copies the kit publishes.

    ``target`` is unused: every directory is inventoried whole, so a Target rename cannot
    silently drop files from the receipt.
    """
    del target
    canonical = tuple(_iter_files(case_root / _CANONICAL_ROOT, case_root))
    mirrored = tuple(_iter_files(case_root / _MIRRORED_ROOT, case_root))
    unpublished = _unpublished(canonical, mirrored)
    groups = [
        ArtifactGroup(
            "Build",
            "Working tree produced by drydock build, exactly as the build left it.",
            tuple(_iter_files(case_root / "build", case_root)),
        ),
        ArtifactGroup(
            "Evidence",
            "Captured command streams, assembled prompts, model output, and provider transcripts.",
            canonical,
        ),
        ArtifactGroup(
            "Inputs",
            "Optional lifecycle decisions seeded into the Target before analysis.",
            tuple(_iter_files(case_root / "inputs", case_root)),
        ),
        ArtifactGroup(
            "Sources",
            "Input bundle staged for drydock import before the lifecycle started.",
            tuple(_iter_files(case_root / "sources", case_root)),
        ),
        ArtifactGroup(
            "Workspace",
            "Drydock workspace the run drove: Blueprint, Manifest, Target artifacts, and the "
            "logs Evidence does not already carry.",
            tuple(record for record in mirrored if record.path not in unpublished),
        ),
        ArtifactGroup(
            "Run record",
            "Machine-readable outcome for this project.",
            tuple(
                _hash_file(path, case_root)
                for path in sorted(case_root.glob("*"))
                if path.is_file() and not path.is_symlink() and path.name not in _KIT_OUTPUTS
            ),
        ),
    ]
    return tuple(group for group in groups if group.files), unpublished


def _rehash(
    base: Path, groups: Sequence[ArtifactGroup], relative: str
) -> tuple[ArtifactGroup, ...]:
    """Re-inventory one file that was rewritten after the inventory was taken."""
    path = base / relative
    if not path.is_file():
        return tuple(groups)
    fresh = _hash_file(path, base)
    return tuple(
        ArtifactGroup(
            group.name,
            group.description,
            tuple(fresh if record.path == relative else record for record in group.files),
        )
        for group in groups
    )


def _write_ignore(base: Path, unpublished: Iterable[str]) -> None:
    """Ignore exactly what the receipt withheld, so a clone carries everything it links.

    The receipt and this file are generated from one set. Deriving them separately lets them
    drift, and the failure that produces is the worst one available here: ``index.html`` is
    the only way anyone reads a committed kit, so a path it links but git never took is a
    dead link in the sole interface.
    """
    lines = [
        "# Generated by drydock uat with the receipt; edits are lost on the next rebuild.",
        f"# Each path below is published from {_CANONICAL_ROOT}/ instead, or is tooling that",
        "# is not part of the build record. Nothing index.html links is listed here.",
    ]
    lines.extend(f"/{path}" for path in sorted(unpublished))
    (base / _IGNORE_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


# The four directories a run writes, each rendered as its own tree. The run record is not a
# tab: the footer already links it, and one file is not a tree.
_INVENTORY_TABS = {
    "Build": ("build", "Build"),
    "Evidence": ("evidence", "Evidence"),
    "Sources": ("sources", "Sources"),
    "Workspace": ("workspace", "Workspace"),
}


def _delivered_root(groups: Sequence[ArtifactGroup], run_prefix: str) -> str:
    """Name the directory the build delivered its code into, stated relative to the kit."""
    files = next((group.files for group in groups if group.name == "Build"), ())
    if not files:
        return ""
    common = files[0].path.rpartition("/")[0]
    for record in files[1:]:
        directory = record.path.rpartition("/")[0]
        while common and not (directory == common or directory.startswith(f"{common}/")):
            common = common.rpartition("/")[0]
    return f"{run_prefix}{common or 'build'}/"


def _render_case_markdown(
    case_root: Path, result: dict, redirect: Mapping[str, str] | None = None
) -> str:
    """Render the run report a forge shows when a reader opens the run directory.

    Markdown, not HTML: a published kit is read on GitHub, which renders the README of whatever
    directory the reader lands in and shows HTML as source. ``index.html`` carries the same run
    for local ``file://`` reading, where nothing renders Markdown.
    """
    fixture = str(result.get("fixture") or "")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    scores = (
        result.get("score_exit_codes") if isinstance(result.get("score_exit_codes"), dict) else {}
    )
    environment = result.get("environment") if isinstance(result.get("environment"), dict) else {}
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    checks = _receipt_checks(case_root, result)
    proven = sum(check.state == "pass" for check in checks)
    test = _command_by_suffix(commands, "-test")
    source, _ = _primary_source(case_root, "")
    target = str(result.get("target") or case_root.name)
    lines = [
        f"# {fixture}: {str(result.get('status') or '').upper()}",
        "",
        f"{proven} of {len(checks)} receipt claims proven. Open `index.html` for the linked "
        "proof kit; verify it with `sha256sum -c SHA256SUMS`.",
        "",
        "## Receipt",
        "",
        "| Claim | Verdict | Recorded outcome | Proof |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {check.name} | {_CHECK_TAGS[check.state]} | {check.detail} "
        f"| {f'[{check.evidence}]({check.evidence})' if check.evidence else '—'} |"
        for check in checks
    ]
    lines += [
        "",
        "## Run facts",
        "",
        f"- Drydock: `{environment.get('drydock_version') or 'not recorded'}` "
        f"(commit `{environment.get('git_commit') or 'not recorded'}`)",
        f"- Provider and model: `{environment.get('provider', '')}` / "
        f"`{environment.get('model', '')}`",
        f"- Platform: `{environment.get('platform') or 'not recorded'}` on Python "
        f"`{environment.get('python_version') or 'not recorded'}`",
        f"- Target: `{result.get('target') or ''}`",
        f"- Run: `{result.get('run_id') or ''}`",
        f"- Ran: {local_run_window(environment)}",
        f"- Elapsed: {int(result.get('elapsed_ms') or 0) / 1000:.1f}s",
        f"- LLM calls: {usage.get('calls', 0)}",
        f"- Tokens: cached {usage.get('cached_input_tokens', 0):,}; "
        f"uncached {usage.get('fresh_input_tokens', 0):,}; "
        f"output {usage.get('output_tokens', 0):,}",
        f"- LLM elapsed: {int(usage.get('llm_elapsed_ms') or 0) / 1000:.1f}s",
        f"- Build passes: {result.get('build_passes', 0)}; repairs: {_repair_budget(commands)}",
        f"- Conformance: {_conformance_result(commands)}",
        f"- Verdict: expected {result.get('expected_verdict') or ''}, "
        f"observed {result.get('observed_verdict') or ''}",
        "- Advisory scores: "
        + (", ".join(f"{name}=exit {code}" for name, code in scores.items()) or "none recorded"),
        "",
        "## RUN SUMMARY",
        "",
        f"- Input specification: {_md_link(case_root, source)}",
        f"- Delivered Code: {_md_link(case_root, _delivered_directory(case_root, target))}",
        "- Test Results: "
        + _md_link(case_root, _relative(test.get("stdout_path"), case_root) if test else ""),
        "",
        "## RUN NOTES:",
        "",
    ]
    lines += [f"- {item}" for item in _RUN_NOTES]
    if result.get("degraded"):
        # A degraded run completed its lifecycle with a named shortfall. Labelling it a failure
        # would misreport a measurement that was taken.
        lines += [
            "",
            "## Shortfall",
            "",
            "- Degraded: " + "; ".join(str(item) for item in result["degraded"] or ()),
        ]
    elif result.get("error"):
        lines += ["", "## Shortfall", "", f"- Failure: {result['error']}"]
    attestations = _attestations(result)
    if attestations:
        # The run passed. These are prohibitions the release gate could not settle either way,
        # so they are surfaced as work a human owes — not as a shortfall of the run.
        lines += [
            "",
            "## Manual verification required",
            "",
            "The release gate completed. It could not settle the following project guardrails "
            "from evidence, so each needs a manual check before release.",
            "",
        ]
        lines += [f"- {item}" for item in attestations]
    lines += [
        "",
        "## Commands",
        "",
        "| # | Command | Exit | Elapsed | Output |",
        "|---|---|---|---|---|",
    ]
    calls = _llm_calls(case_root / "evidence" / "llm.jsonl", case_root, redirect)
    command_logs = _receipt_llm_logs(case_root, commands, calls)
    for item, logs in zip(commands, command_logs, strict=True):
        argv = " ".join(str(part) for part in item.get("argv") or [])
        stdout = str(item.get("stdout_path") or "")
        links = [f"[stdout]({stdout})", f"[stderr]({item.get('stderr_path') or ''})"]
        links.extend(f"[llm]({path})" for path in logs)
        lines.append(
            f"| {item.get('label', '')} | `{argv}` | {item.get('returncode', '')} "
            f"| {int(item.get('elapsed_ms') or 0) / 1000:.1f}s "
            f"| {' · '.join(links)} |"
        )
    lines += [
        "",
        "## Evidence",
        "",
        "- [`evidence/commands/`](evidence/commands) — stdout and stderr of every command",
        "- [`evidence/prompts/`](evidence/prompts) — the assembled prompt for every LLM call",
        "- [`evidence/provider_raw/`](evidence/provider_raw) — unmodified provider transcripts",
    ]
    # Runs recorded before activity logs were collected have no such directory, and a receipt
    # never links a path the run did not write.
    if (case_root / "evidence" / "llm_logs").is_dir():
        lines.append(
            "- [`evidence/llm_logs/`](evidence/llm_logs) — call banners and token accounting"
        )
    lines += [
        "- [`result.json`](result.json) — the machine-readable record of this run",
        "",
    ]
    return "\n".join(lines)


#: Report tag class per run status. A degraded run completed its lifecycle with a named
#: shortfall, so it is neither a pass nor an abort and must not be rendered as either.
_STATUS_TAGS = {"passed": "pass", "degraded": "degraded"}


def _attestations(result: dict) -> tuple[str, ...]:
    """Unproven project guardrails this run handed back for manual verification."""
    items = result.get("attestations")
    return tuple(str(item) for item in items) if isinstance(items, list) else ()


def _sums_detail(case_root: Path) -> tuple[str, str]:
    """Report what ``SHA256SUMS`` covers, as the count of digests actually written."""
    path = case_root / _SUMS_NAME
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return "unknown", "No SHA256SUMS is present in this run directory."
    if not lines:
        return "fail", "SHA256SUMS is empty."
    return "pass", f"{len(lines):,} files digested; verify with sha256sum -c SHA256SUMS."


def _receipt_checks(case_root: Path, result: dict) -> tuple[Check, ...]:
    """Derive the six receipt claims from the recorded run, in fixed order."""
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    scores = (
        result.get("score_exit_codes") if isinstance(result.get("score_exit_codes"), dict) else {}
    )
    status = str(result.get("status") or "")

    lifecycle_state = {"passed": "pass", "degraded": "pass"}.get(status, "fail")
    last = str(commands[-1].get("label") or "") if commands else ""
    lifecycle_detail = (
        f"{len(commands)} lifecycle commands executed; the run ended at {last}."
        if commands
        else "No lifecycle commands were recorded."
    )
    if status == "degraded":
        lifecycle_detail += " Completed with a named shortfall; see the verdict above."

    checks = [Check("Lifecycle completed", lifecycle_state, lifecycle_detail, "result.json")]
    for name, suffix, absent in (
        (
            "External conformance suite passed",
            "-test",
            "No external test command is defined for this project.",
        ),
        (
            "Target completion check passed",
            "-complete",
            "No completion check was recorded for this run.",
        ),
    ):
        command = _command_by_suffix(commands, suffix)
        if command is None:
            checks.append(Check(name, "unknown", absent))
            continue
        argv = _command_text(command.get("argv") or []) or str(command.get("label") or "")
        state = _exit_state(command.get("returncode"))
        if suffix == "-complete" and state == "fail":
            # ``drydock status --check`` reports Manifest state through its exit code. An
            # incomplete Target has not made the receipt claim, but the status command itself
            # did not fail.
            state = "unknown"
        checks.append(
            Check(
                name,
                state,
                f"{argv} exited {command.get('returncode')}.",
                _relative(command.get("stdout_path"), case_root),
            )
        )
    for name, score in (
        ("Acceptance score passed", "acceptance"),
        ("Release score passed", "release"),
    ):
        command = _command_by_suffix(commands, f"-score-{score}")
        code = scores.get(score, command.get("returncode") if command else None)
        evidence = _relative(command.get("stdout_path"), case_root) if command else ""
        detail = (
            f"drydock score {score} exited {code}."
            if code is not None
            else f"No {score} score was recorded for this run."
        )
        checks.append(Check(name, _exit_state(code), detail, evidence))
    integrity_state, integrity_detail = _sums_detail(case_root)
    checks.append(
        Check("Integrity verification passed", integrity_state, integrity_detail, _SUMS_NAME)
    )
    return tuple(checks)


def _repair_budget(commands: Sequence[dict]) -> str:
    """Report the repair allowance the build ran under, as recorded on its own command line."""
    build = _command_by_suffix(commands, "-build-1") or _command_by_suffix(commands, "build")
    argv = [str(part) for part in (build or {}).get("argv") or []]
    if "--repair-attempts" in argv:
        index = argv.index("--repair-attempts")
        if index + 1 < len(argv):
            return f"{argv[index + 1]} attempts allowed"
    return "not recorded"


def _conformance_result(commands: Sequence[dict]) -> str:
    test = _command_by_suffix(commands, "-test")
    if test is None:
        return "no external suite defined"
    code = test.get("returncode")
    return "passed" if code == 0 else f"failed (exit {code})"


def _run_facts(
    case_root: Path,
    result: dict,
    environment: Mapping[str, object],
    usage: Mapping[str, object],
    delivered: str = "",
) -> list[tuple[str, str]]:
    """The provenance a reader needs before reading anything else the run wrote."""
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    status = str(result.get("status") or "").upper()
    observed = str(result.get("observed_verdict") or "")
    verdict = f"{status} · verdict {observed}" if observed and observed != status else status
    tokens = _tokens(dict(usage))
    _, _, tokens = tokens.partition(" · ")  # the call count is already its own field

    def recorded(key: str) -> str:
        return html.escape(str(environment.get(key) or "not recorded"))

    return [
        ("Verdict", html.escape(verdict)),
        ("Target", f"<code>{html.escape(str(result.get('target') or case_root.name))}</code>"),
        ("Run", f"<code>{html.escape(str(result.get('run_id') or ''))}</code>"),
        ("Ran", html.escape(local_run_window(environment))),
        ("Drydock", recorded("drydock_version")),
        ("Commit", f"<code>{recorded('git_commit')}</code>"),
        ("Provider", recorded("provider")),
        ("Model", recorded("model")),
        ("Platform", recorded("platform")),
        ("Python", recorded("python_version")),
        ("Elapsed", f"{int(result.get('elapsed_ms') or 0) / 1000:.1f}s"),
        ("LLM calls", html.escape(str(usage.get("calls", "not recorded")))),
        ("Tokens", html.escape(tokens)),
        ("Build passes", html.escape(str(result.get("build_passes", "not recorded")))),
        ("Repairs", html.escape(_repair_budget(commands))),
        ("Conformance", html.escape(_conformance_result(commands))),
        ("Code", f"<code>{html.escape(delivered)}</code>" if delivered else ""),
    ]


def _receipt(case_root: Path, result: dict, prefix: str = "") -> str:
    """Render the UAT receipt: the six claims a run either earned or did not."""
    return _render_receipt(case_root, _receipt_checks(case_root, result), prefix)


# ── guided verification path ─────────────────────────────────────────────────────────


def _primary_source(case_root: Path, prefix: str) -> tuple[str, str]:
    """Name the specification the run was built from: the largest prose file in ``sources/``."""
    directory = case_root / "sources"
    if not directory.is_dir():
        return "", ""
    documents = [
        path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in _MARKDOWN_SUFFIXES
    ]
    named = [path for path in documents if path.name != "INSTRUCTIONS.md"] or documents
    if not named:
        return "", ""
    chosen = max(named, key=lambda path: path.stat().st_size)
    return f"sources/{chosen.name}", f"{prefix}sources/{chosen.name}"


def _delivered_directory(case_root: Path, target: str) -> str:
    """Name the delivered-code directory from the run tree, without needing its inventory."""
    root = case_root / "build"
    if (root / target).is_dir():
        return f"build/{target}/"
    return "build/" if root.is_dir() else ""


def _run_summary(case_root: Path, result: dict, prefix: str = "") -> str:
    """Render the three artifacts that summarize the run."""
    target = str(result.get("target") or case_root.name)
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    test = _command_by_suffix(commands, "-test")
    test_log = _relative(test.get("stdout_path"), case_root) if test else ""
    source, _ = _primary_source(case_root, prefix)
    delivered = _delivered_directory(case_root, target)
    facts = (
        ("Input specification", _evidence_link(case_root, source, prefix)),
        ("Delivered Code", _evidence_link(case_root, delivered, prefix)),
        ("Test Results", _evidence_link(case_root, test_log, prefix)),
    )
    return "<h2>RUN SUMMARY</h2>" + _meta([
        (label, value or "not recorded for this run.") for label, value in facts
    ])


def _decision_records(case_root: Path) -> tuple[list[dict], str]:
    """Return this run's decision records and the path they were read from.

    A UAT run has no operator at the keyboard, so every question Drydock raised was either
    answered from the fixture or decided by Drydock itself. That makes ``DECISIONS.json`` the
    review surface for an unattended run — the same role ``decisions`` plays interactively — and
    it must be reachable from the run page rather than buried in the workspace mirror.
    """
    targets = case_root / "workspace" / "targets"
    if not targets.is_dir():
        return [], ""
    for target_dir in sorted(path for path in targets.iterdir() if path.is_dir()):
        path = target_dir / "DECISIONS.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], ""
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)], str(
                path.relative_to(case_root).as_posix()
            )
    return [], ""


def _decisions_block(case_root: Path) -> str:
    """Tier-one panel listing every decision recorded during the run."""
    records, relative = _decision_records(case_root)
    if not records:
        return ""
    open_count = sum(1 for item in records if str(item.get("status")) != "answered")
    rows = [
        [
            _cell(str(item.get("id") or "")),
            _cell(str(item.get("origin") or "")),
            _cell(str(item.get("severity") or "")),
            _cell(str(item.get("status") or "")),
            _cell(str(item.get("title") or "")),
            _cell(str(item.get("system_choice") or "—")),
            _cell(str(item.get("commander_direction") or "—")),
        ]
        for item in records
    ]
    note = (
        f"{len(records)} recorded · {open_count} still recommended. A recommended decision is "
        "one Drydock made on the author's behalf and no human has confirmed. Decisions carry "
        "forward: an answered one is re-entered on this project's next run."
    )
    link = f" Full record: {_link(f'view/{relative}.html')}." if relative else ""
    return f'<h2>Decisions</h2><p class="note">{html.escape(note)}{link}</p>' + _table(
        (
            "ID",
            "Origin",
            "Severity",
            "Status",
            "Title",
            "System choice",
            "Commander direction",
        ),
        rows,
    )


def _render_case(
    case_root: Path,
    result: dict,
    groups: Sequence[ArtifactGroup],
    redirect: Mapping[str, str] | None = None,
) -> str:
    target = str(result.get("target") or case_root.name)
    fixture = str(result.get("fixture") or case_root.name)
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    failed = [
        item
        for item in commands
        if item.get("returncode") not in (0, None)
        and not _is_status_command(item.get("argv") or ())
    ]
    status = str(result.get("status") or ("passed" if not failed else "failed"))
    passed = status == "passed"

    resumed = str(result.get("resumed_from") or "")
    # Unproven guardrails do not gate the run: nothing demonstrated a violation. They are named
    # because a prohibition the evidence could not settle still needs a human to settle it.
    attestations = _attestations(result)
    detail = ""
    if status == "degraded":
        # Not a failure: the lifecycle ran end to end and the scores below describe the
        # application the build actually produced. Name what fell short and leave it at that.
        detail = (
            "Degraded: <code>"
            + html.escape("; ".join(str(item) for item in result.get("degraded") or ()))
            + "</code>. Every later stage ran against the work the build produced."
        )
    elif result.get("error"):
        detail = f"Failure: <code>{html.escape(str(result['error']))}</code>"
    elif passed and resumed:
        # A resumed run reuses state an earlier attempt produced, and its command table still
        # carries that attempt's failures. Saying "every command exited 0" would be false.
        detail = (
            f"Resumed at <code>{html.escape(resumed)}</code>; every required command from that "
            "stage onward exited 0. Earlier rows are the prior attempt, retained as evidence."
        )
    elif passed:
        detail = (
            f"{len(commands)} lifecycle commands ran; every required command exited 0. "
            "Each row below links to its own captured output."
        )
    # A run status of PASSED is decided by the required commands. It does not settle the
    # advisory claims the receipt reports, so the page never lets the verdict imply them.
    unproven = [check for check in _receipt_checks(case_root, result) if check.state != "pass"]
    if unproven:
        names = ", ".join(check.name.lower() for check in unproven)
        detail += (
            f" {len(unproven)} receipt "
            f"{'claim is' if len(unproven) == 1 else 'claims are'} not proven ({names}); "
            "see the receipt below."
        )
    if passed and attestations:
        count = len(attestations)
        noun = "guardrail" if count == 1 else "guardrails"
        detail += (
            f" {count} project {noun} could not be settled from evidence and "
            f"{'needs' if count == 1 else 'need'} manual verification before release; "
            "see Manual verification required."
        )
    verdict = f"{fixture}: {status.upper()}"

    inventory = inventory_panels(
        groups, f"runs/{result.get('run_id') or case_root.name}/", _INVENTORY_TABS
    )
    calls = _llm_calls(case_root / "evidence" / "llm.jsonl", case_root, redirect)
    command_logs = _receipt_llm_logs(case_root, commands, calls)

    command_rows: list[list[str]] = []
    for index, (command, logs) in enumerate(zip(commands, command_logs, strict=True), start=1):
        argv = command.get("argv") or []
        label = command.get("label") or f"step-{index:02d}"
        stdout = _relative(command.get("stdout_path"), case_root)
        stderr = _relative(command.get("stderr_path"), case_root)
        elapsed = command.get("elapsed_ms") or 0
        command_rows.append([
            _cell(index, css="num"),
            _cell(label),
            f"<td><code>{html.escape(_command_text(argv))}</code></td>",
            _status_cell(
                command.get("returncode"),
                argv,
                recorded_status_headline(case_root, stdout, argv),
            ),
            _cell(f"{elapsed / 1000:.1f}s", css="num"),
            _stream_link(case_root, stdout, "stdout"),
            _stream_link(case_root, stderr, "stderr"),
            _llm_log_cell(case_root, logs),
        ])
    commands_table = _table(
        ("#", "Stage", "Command", "Result", "Elapsed", "stdout", "stderr", "llm"),
        command_rows,
    )

    excerpt = ""
    if failed:
        # Every stage that exited nonzero, in the order it ran. The first is where the run
        # diverged and the rest are usually its consequence, but a reader chasing a defect needs
        # all of them: quoting two ends of the list hides whatever failed between them. stderr
        # leads each block, because a command that exits nonzero states its cause there.
        blocks: list[str] = []
        for position, command in enumerate(failed):
            sections = []
            for stream, name in (("stderr_path", "stderr"), ("stdout_path", "stdout")):
                relative = _relative(command.get(stream), case_root)
                text = _tail(case_root / relative) if relative else ""
                if text:
                    sections.append(
                        f'<p class="note">Tail of <code>{html.escape(relative)}</code>.</p>'
                        f"<pre>{html.escape(text[-4000:])}</pre>"
                    )
                elif name == "stderr":
                    # A nonzero exit with an empty error stream is itself a defect: the command
                    # failed without naming a cause. Say so rather than render nothing.
                    sections.append(
                        '<p class="note">This stage exited nonzero and wrote nothing to '
                        "<code>stderr</code>. The failure is reported below from "
                        "<code>stdout</code> only.</p>"
                    )
            if not sections:
                continue
            role = (
                "is the first stage that exited nonzero, so it is where the run diverged"
                if position == 0
                else "exited nonzero"
            )
            label = html.escape(str(command.get("label") or ""))
            code = html.escape(str(command.get("returncode")))
            blocks.append(
                f'<p class="note">Stage <code>{label}</code> {role} (exit {code}).</p>'
                + "".join(sections)
            )
        if blocks:
            excerpt = (
                "<h2>Recorded failure output</h2>"
                '<p class="note">Every stage that exited nonzero, quoted verbatim from the '
                "captured streams, error stream first.</p>" + "".join(blocks)
            )

    call_rows = [
        [
            _cell(call["command"]),
            _cell(f"{call['provider']}/{call['model']}"),
            _status_cell(call["returncode"]),
            _cell(f"{int(call['elapsed_ms'] or 0) / 1000:.1f}s", css="num"),
            _cell(f"{int(call['cached_input_tokens']):,}", css="num"),
            _cell(
                f"{max(int(call['input_tokens']) - int(call['cached_input_tokens']), 0):,}",
                css="num",
            ),
            _cell(f"{int(call['output_tokens']):,}", css="num"),
            _link(str(call["prompt"]), "prompt"),
            _link(str(call["output"]), "output"),
            _link(str(call["raw"]), "transcript"),
            _stream_link(case_root, str(call["llm_log"]), "llm"),
        ]
        for call in calls
    ]
    calls_table = _table(
        (
            "Command",
            "Model",
            "Result",
            "Elapsed",
            "Cached",
            "Uncached",
            "Output",
            "prompt",
            "output",
            "transcript",
            "llm",
        ),
        call_rows,
    )

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    recorded = result.get("environment")
    environment = dict(recorded) if isinstance(recorded, dict) else {}
    # Runs recorded before provenance capture still name their provider in every LLM record.
    for key, field in (("provider", "provider"), ("model", "model")):
        if not environment.get(key) and calls:
            environment[key] = str(calls[0][field] or "")
    run_prefix = f"runs/{result.get('run_id') or case_root.name}/"
    meta = _meta(
        _run_facts(case_root, result, environment, usage, _delivered_root(groups, run_prefix))
    )

    scores = (
        result.get("score_exit_codes") if isinstance(result.get("score_exit_codes"), dict) else {}
    )
    score_rows = [[_cell(name), _status_cell(code)] for name, code in sorted(scores.items())]
    scores_block = (
        "<h2>Advisory scores</h2>"
        '<p class="note">Scoring is advisory and does not gate the run.</p>'
        + _table(("Score", "Result"), score_rows)
        if score_rows
        else ""
    )

    attestations_block = (
        "<h2>Manual verification required</h2>"
        '<p class="note">The release gate completed. It could not settle the following project '
        "guardrails from evidence, so each needs a manual check before release.</p><ul>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in attestations)
        + "</ul>"
        if attestations
        else ""
    )

    steps_panel = "".join([
        "<h2>Lifecycle commands</h2>",
        '<p class="note">Each Drydock command executed in order, with its recorded exit code '
        "and its own captured streams. A stream is linked only when it captured output; "
        "run progress and token accounting are reported on stdout, so a linked stderr "
        "means the stage wrote diagnostics.</p>",
        commands_table,
        scores_block,
        attestations_block,
    ])
    llm_panel = (
        "".join([
            "<h2>LLM executions</h2>",
            '<p class="note">One row per model invocation, with the exact prompt sent, the '
            "output returned, and the raw provider transcript.</p>",
            calls_table,
        ])
        if call_rows
        else ""
    )

    provider = str(environment.get("provider") or "")
    model = str(environment.get("model") or "")
    docline = " · ".join(
        part
        for part in (
            f"Run {result.get('run_id') or ''}",
            f"Target {target}",
            f"{provider}/{model}" if provider or model else "",
        )
        if part
    )
    return _page(
        f"Drydock UAT report — {fixture}",
        "\n".join([
            _letterhead(
                "User Acceptance Test — Run Report",
                fixture,
                docline,
                passed,
                "Approved" if passed else "Rejected",
            ),
            _verdict(passed, verdict, detail),
            _receipt(case_root, result),
            meta,
            _run_summary(case_root, result),
            run_notes(),
            _decisions_block(case_root),
            "<h2>Run detail</h2>",
            '<p class="note">Everything below is the underlying record: the commands Drydock '
            "executed, the model calls they made, and every file this run wrote.</p>",
            _tabs([
                ("steps", "Steps", steps_panel),
                ("error", "Error", excerpt),
                ("llm", "LLM", llm_panel),
                *inventory,
            ]),
            "<footer>Generated by <code>drydock uat --report</code>. Byte counts and digests are "
            "computed from the files in this directory at generation time. Verify the kit with "
            f"<code>cd {html.escape(case_root.name)} &amp;&amp; sha256sum -c SHA256SUMS</code>. "
            f"Record: {_anchor('result.json')} · {_anchor('SHA256SUMS')}</footer>",
        ]),
    )


# A kit is published as its own repository, so its landing page is the project page: the
# governed documents at the kit root, the input bundles, and every recorded run. Purposes are
# stated here so the page explains the layout to a reader who has never seen a kit before.
_KIT_DOCUMENTS: tuple[tuple[str, str], ...] = (
    ("README.md", "What this project builds, how to run it, and how to read its evidence"),
    ("uat.json", "Kit definition: source bundle, updates, and test command"),
    ("USER_NOTES.md", "Operator notes carried into the build"),
    ("LICENSE", "Licence for the published kit"),
)

_KIT_BUNDLES: tuple[tuple[str, str], ...] = (
    ("inputs", "Optional lifecycle decisions seeded after init and before analysis"),
    ("sources", "Specification and artifact bundle imported before the initial lifecycle"),
    ("updates", "Replacement sources that drive each incremental rebuild"),
)


def _kit_documents(kit_root: Path) -> list[list[str]]:
    """Row per governed document present at the kit root, catalogued first, then the rest."""
    known = {name for name, _ in _KIT_DOCUMENTS}
    rows = [
        [_link(name), _cell(purpose)]
        for name, purpose in _KIT_DOCUMENTS
        if (kit_root / name).is_file()
    ]
    # Dotfiles are publishing and tooling markers, not project documents.
    rows.extend(
        [_link(path.name), _cell("Kit file")]
        for path in sorted(kit_root.iterdir())
        if path.is_file()
        and not path.name.startswith(".")
        and path.name not in known
        and path.name not in _KIT_OUTPUTS
    )
    return rows


def _kit_artifacts(kit_root: Path) -> list[str]:
    """Every kit-level file the landing page can link: root documents and both bundles."""
    paths = [
        path.name
        for path in sorted(kit_root.iterdir())
        if path.is_file() and not path.name.startswith(".") and path.name not in _KIT_OUTPUTS
    ]
    for name, _ in _KIT_BUNDLES:
        directory = kit_root / name
        if directory.is_dir():
            paths.extend(
                f"{name}/{path.name}" for path in sorted(directory.iterdir()) if path.is_file()
            )
    return paths


def _kit_bundle_panels(kit_root: Path) -> str:
    """List each input bundle's files, so the page shows what the runs were built from."""
    sections: list[str] = []
    for name, purpose in _KIT_BUNDLES:
        directory = kit_root / name
        if not directory.is_dir():
            continue
        rows = [
            [_link(f"{name}/{path.name}"), _cell(f"{path.stat().st_size:,} bytes", css="num")]
            for path in sorted(directory.iterdir())
            if path.is_file()
        ]
        sections.extend([
            f"<h3>{html.escape(name)}/</h3>",
            f'<p class="note">{html.escape(purpose)}</p>',
            _table(("File", "Size"), rows),
        ])
    return "\n".join(sections)


def _kit_decisions_rows(kit_root: Path) -> list[list[str]]:
    """One row per run, counting the decisions it recorded and how many remain recommended."""
    runs_root = kit_root / "runs"
    if not runs_root.is_dir():
        return []
    rows: list[list[str]] = []
    for run_dir in sorted((path for path in runs_root.iterdir() if path.is_dir()), reverse=True):
        records, _ = _decision_records(run_dir)
        if not records:
            continue
        open_count = sum(1 for item in records if str(item.get("status")) != "answered")
        material = sum(
            1
            for item in records
            if str(item.get("severity")) == "material" and str(item.get("status")) != "answered"
        )
        rows.append([
            _link(f"runs/{run_dir.name}/index.html", run_dir.name),
            _cell(str(len(records)), css="num"),
            _cell(str(open_count), css="num"),
            _cell(str(material) if material else "—", css="num"),
        ])
    return rows


def _render_kit(kit_root: Path, results: Sequence[tuple[str, dict]]) -> str:
    """Render the kit landing page: one row per run, newest first."""
    latest = results[0][1] if results else {}
    passed = str(latest.get("status")) == "passed"
    verdict = f"latest run {str(latest.get('status') or 'unknown').upper()}"
    detail = (
        str(latest.get("error") or "") or "Open a run below for its command-by-command evidence."
    )

    rows = []
    for run_id, item in results:
        case_status = str(item.get("status") or "")
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        commands = [entry for entry in item.get("commands") or [] if isinstance(entry, dict)]
        environment = item.get("environment") if isinstance(item.get("environment"), dict) else {}
        state = _STATUS_TAGS.get(case_status, "fail")
        rows.append([
            f"<td>{_anchor(f'runs/{run_id}/index.html', run_id)}</td>",
            f'<td><span class="tag {state}">{html.escape(case_status.upper())}</span></td>',
            _cell(str(environment.get("model") or "not recorded"), css="nowrap"),
            _cell(len(commands), css="num"),
            _cell(item.get("build_passes", ""), css="num"),
            _cell(f"{int(item.get('elapsed_ms') or 0) / 1000:.1f}s", css="num"),
            _cell(_tokens(usage)),
        ])

    # The newest run is what a reader almost always wants, so it is reachable above the table,
    # and the summary below reports that run specifically rather than the project in general.
    latest_link = (
        f'<p class="note">This page summarizes the newest recorded run, '
        f"{_anchor(f'runs/{results[0][0]}/index.html', results[0][0])}. Its own receipt carries "
        "the full command-by-command record.</p>"
        if results
        else '<p class="note">No runs have been recorded for this project yet.</p>'
    )
    if results:
        run_id = results[0][0]
        latest_root = kit_root / "runs" / run_id
        prefix = f"runs/{run_id}/"
        environment = (
            latest.get("environment") if isinstance(latest.get("environment"), dict) else {}
        )
        usage = latest.get("usage") if isinstance(latest.get("usage"), dict) else {}
        summary = "\n".join([
            _receipt(latest_root, latest, prefix),
            _meta(
                _run_facts(
                    latest_root,
                    latest,
                    environment,
                    usage,
                    prefix + _delivered_directory(latest_root, str(latest.get("target") or "")),
                )
            ),
            _run_summary(latest_root, latest, prefix),
            run_notes(),
        ])
    else:
        summary = ""

    return _page(
        f"Drydock UAT kit {kit_root.name}",
        "\n".join([
            _letterhead(
                "User Acceptance Test — Project Register",
                kit_root.name,
                f"{len(results)} recorded runs · newest first",
                passed,
                "Approved" if passed else "Rejected",
            ),
            _verdict(passed, verdict, html.escape(detail)),
            latest_link,
            summary,
            "<h2>Runs</h2>",
            '<p class="note">Every unattended build of this project, each a complete, '
            "self-verifying record of the commands Drydock executed. Open a run to reach its "
            "commands, prompts, evidence, and delivered application.</p>",
            _table(
                ("Run", "Status", "Model", "Commands", "Build passes", "Elapsed", "LLM usage"),
                rows,
            ),
            "<h2>Decisions</h2>",
            '<p class="note">Questions Drydock raised while building this project, and how each '
            "was settled. A run has no operator at the keyboard, so a decision still marked "
            "recommended was made by Drydock and no human has confirmed it. Answered decisions "
            "carry forward into the next run of this project.</p>",
            _table(
                ("Run", "Recorded", "Recommended", "Material open"),
                _kit_decisions_rows(kit_root),
            ),
            "<h2>Inputs</h2>",
            '<p class="note">Everything supplied to these runs before Drydock authored '
            "anything: the imported specification bundle, the declared technology stack, the "
            "frozen Sea Trials, the replacement sources that drive each rebuild, and the "
            "decisions carried in from earlier runs.</p>",
            _kit_bundle_panels(kit_root),
            "<h2>Project</h2>",
            '<p class="note">The governed documents that define this project.</p>',
            _table(("File", "Purpose"), _kit_documents(kit_root)),
            "<footer>Generated by <code>drydock uat --report</code>.</footer>",
        ]),
    )


# ── entry points ─────────────────────────────────────────────────────────────────────


def build_case_kit(case_root: Path) -> Path:
    """Inventory one project case and write its receipt; returns the index path."""
    _make_portable(case_root / "result.json", case_root)
    result = _read_json(case_root / "result.json")
    if not isinstance(result, dict):
        raise ValueError(f"UAT case has no readable result.json: {case_root}")
    prune_generated(case_root)
    target = str(result.get("target") or case_root.name)

    manifest_path = case_root / "evidence" / "manifest.json"
    # Written before the inventory: the combined step logs are published evidence, so they are
    # hashed into SHA256SUMS and the manifest like the streams they sit beside.
    _write_step_llm_logs(
        case_root,
        [item for item in result.get("commands") or [] if isinstance(item, dict)],
        _llm_calls(case_root / "evidence" / "llm.jsonl", case_root),
    )
    groups, unpublished = _case_groups(case_root, target)
    _write_ignore(case_root, unpublished)

    # The manifest is rewritten here, so it is inventoried afterwards: a checksum taken before
    # the rewrite describes a file that no longer exists, and `sha256sum -c` reports it FAILED.
    # It cannot index its own digest either, so it lists every artifact except itself.
    manifest = _read_json(manifest_path)
    if isinstance(manifest, dict):
        manifest = _portable(manifest, case_root)
        manifest["environment"] = result.get("environment") or {}
        manifest["artifacts"] = {
            group.name: [
                record.to_dict() for record in group.files if record.path != _MANIFEST_PATH
            ]
            for group in groups
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        groups = _rehash(case_root, groups, _MANIFEST_PATH)
    _write_sums(case_root, groups)

    (case_root / "README.md").write_text(
        _render_case_markdown(case_root, result, unpublished), encoding="utf-8"
    )
    # Viewers are written before the receipt so every link it emits can point at one. They are
    # generated output: excluded from the inventory above, and replaced on every rebuild.
    viewers = _write_viewers(
        case_root,
        [record.path for group in groups for record in group.files],
        "Run artifact",
        _INDEX_NAME,
    )
    index = case_root / _INDEX_NAME
    with _viewers(viewers):
        index.write_text(_render_case(case_root, result, groups, unpublished), encoding="utf-8")
    return index


def _kit_cases(kit_root: Path) -> list[Path]:
    """Run directories holding a readable record, newest first."""
    from drydock.uat import run_sort_key

    runs_root = kit_root / "runs"
    if not runs_root.is_dir():
        return []
    return sorted(
        (
            path
            for path in runs_root.iterdir()
            if path.is_dir() and (path / "result.json").is_file()
        ),
        key=lambda path: run_sort_key(path.name),
        reverse=True,
    )


def write_kit_index(kit_root: Path) -> Path:
    """Write the kit landing page from the run records already on disk.

    Rebuilds no run receipt, so a completed run can refresh its project page cheaply.
    """
    results: list[tuple[str, dict]] = []
    for case_root in _kit_cases(kit_root):
        result = _read_json(case_root / "result.json")
        if isinstance(result, dict):
            results.append((case_root.name, result))
    index = kit_root / _INDEX_NAME
    viewers = _write_viewers(kit_root, _kit_artifacts(kit_root), "Project document", _INDEX_NAME)
    with _viewers(viewers):
        index.write_text(_render_kit(kit_root, results), encoding="utf-8")
    return index


def build_kit_index(kit_root: Path) -> Path:
    """Rebuild every run receipt under one kit and write the kit landing page."""
    for case_root in _kit_cases(kit_root):
        build_case_kit(case_root)
    return write_kit_index(kit_root)
