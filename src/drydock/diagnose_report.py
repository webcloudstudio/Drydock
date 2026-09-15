"""Assemble the diagnosis prompt, run it once, verify the answer, and write the diagnosis.

The model writes section prose. This module writes the file. That split is what lets the report
carry a deterministic header, a deterministic ladder, and a deterministic table of local evidence
paths regardless of what the model returned — and it is why a malformed answer still produces a
readable document rather than nothing.

Verification is not a formality. An amendment whose diff does not apply is worse than no
amendment: the operator approves a change that then fails to land, and trust in the whole report
goes with it. Every diff is applied to an in-memory copy of the current file before the operator
is shown anything, and one that will not apply is reported as unapplicable instead.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from drydock.build_plan import compact_source
from drydock.diagnose_evidence import AMENDABLE, BLUEPRINT_PREFIX, Bundle, Excerpt
from drydock.diagnose_ladder import render_ladder
from drydock.patch import Amendment, parse_amendments
from drydock.prompt_assembly import (
    PromptAssembly,
    fenced_block_part,
    fenced_markdown_part,
    fenced_text_part,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

PROMPT_NAME = "diagnose_report"
DIAGNOSE_TIMEOUT_SECONDS = 900.0
REPORT_PREFIX = "DIAGNOSE"

#: The report's fixed section order. The model must return all four; a missing one is a
#: malformed answer, because a reader cannot tell an omitted section from an empty finding.
REQUIRED_SECTIONS = (
    "Root Cause",
    "Details",
    "Commander Feedback Requested",
    "Repair Proposal",
)

_SECTION_RE = re.compile(r"(?m)^###\s+(?P<title>.+?)\s*$")
_RULE = "\n\n---\n\n"


@dataclass(frozen=True)
class Diagnosis:
    """A verified diagnosis, or a malformed one that is still written down.

    ``ok`` false means the model's answer did not satisfy the output contract. The report is
    written either way: an operator who paid for a call is owed the raw answer and a clear
    statement that Drydock could not use it.
    """

    ok: bool
    sections: dict[str, str]
    amendments: tuple[Amendment, ...]
    unapplicable: tuple[Amendment, ...]
    raw: str
    problems: tuple[str, ...] = ()


def assemble(bundle: Bundle, body: str) -> PromptAssembly:
    """Build the diagnosis prompt deterministically, so it can be tested without a provider."""
    parts = [system_preamble_part(), part("Task", body, kind="prompt")]

    parts.append(section_heading_part("Established Facts"))
    state, reason = bundle.execution
    parts.append(
        lines_part(
            "Current execution state",
            [
                f"{state}: {reason}",
                "Milestone successes are historical; they do not resolve current impediments.",
            ],
            role="deterministic",
        )
    )
    parts.append(
        lines_part(
            "Run",
            [
                f"Target: {bundle.target}",
                f"Run stamp: {bundle.run_stamp or 'not recorded'}",
                f"Stop: {bundle.stop.headline if bundle.stop else 'no live failure recorded'}",
                f"Classification: {bundle.stop.classification if bundle.stop else ''}"
                or "Classification: none recorded",
                f"Stopping detail: {bundle.stop.detail if bundle.stop else ''}",
                f"Retries at the stop: {bundle.stop.attempts if bundle.stop else 0}",
            ],
            role="deterministic",
        )
    )
    parts.append(
        fenced_text_part("Stage ladder", render_ladder(bundle.ladder), role="deterministic")
    )
    if bundle.superseded:
        parts.append(
            lines_part(
                "Superseded failures",
                [
                    "These states failed and a later state in the same milestone answered "
                    "them. They are not defects.",
                    *(
                        f"- {entry.label}: {entry.detail or 'no detail recorded'}"
                        for entry in bundle.superseded
                    ),
                ],
                role="deterministic",
            )
        )
    if bundle.missing:
        parts.append(
            lines_part(
                "Missing evidence",
                [
                    "Absent from this run. Do not assume their contents.",
                    *(f"- {name}" for name in bundle.missing),
                ],
                role="deterministic",
            )
        )

    parts.append(section_heading_part("Command History"))
    parts.append(
        lines_part(
            "Commands",
            [_command_line(command) for command in bundle.commands] or ["No commands recorded."],
            role="evidence",
        )
    )

    if bundle.transcripts:
        parts.append(section_heading_part("Transcripts"))
        for excerpt in bundle.transcripts:
            parts.append(_excerpt_part(excerpt, "text", "evidence"))

    parts.append(section_heading_part("Recorded State"))
    if bundle.scorecard is not None:
        parts.append(_excerpt_part(bundle.scorecard, "markdown", "evidence"))
    if bundle.blockers is not None:
        parts.append(_excerpt_part(bundle.blockers, "markdown", "evidence"))
    parts.append(
        fenced_text_part(
            "DECISIONS.json",
            json.dumps(list(bundle.decisions), indent=2),
            role="evidence",
        )
    )

    parts.append(section_heading_part("Amendable Files"))
    parts.append(
        lines_part(
            "Amendment rules",
            [
                "Diffs must apply to these exact contents. Line numbers and context must match.",
                "Amendable files: "
                + ", ".join((*AMENDABLE, *(excerpt.name for excerpt in bundle.blueprints))),
            ],
            role="contract",
        )
    )
    for excerpt in (*bundle.blueprints, *bundle.governed):
        parts.append(_numbered_part(excerpt))

    return PromptAssembly(parts=tuple(parts))


def diagnose_run(
    bundle: Bundle,
    *,
    llm: str | None = None,
    model: str | None = None,
    log_dir: Path | None = None,
    on_text: Callable[[str], None] | None = None,
    runner: Callable[..., object] | None = None,
) -> Diagnosis:
    """Make the single diagnostic call and verify what comes back.

    One call. There is no retry and no second pass: a diagnosis that needs to be asked twice is
    a prompt defect, and spending the operator's budget hiding it helps nobody.
    """
    from drydock.llm import run_prompt

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    assembly = assemble(bundle, prompt.body)
    working_directory = bundle.target_dir if bundle.target_dir.is_dir() else Path.cwd()
    result = run(
        assembly.rendered_text,
        working_directory,
        llm=llm,
        model=model or prompt.model,
        command_name="diagnose",
        parameters={"target": bundle.target, "run": bundle.run_stamp},
        timeout_seconds=DIAGNOSE_TIMEOUT_SECONDS,
        log_dir=log_dir,
        target=bundle.target,
        on_text=on_text,
        prompt_assembly=assembly,
    )
    text = getattr(result, "text", "") or ""
    if not getattr(result, "ok", False) or not text.strip():
        return Diagnosis(
            ok=False,
            sections={},
            amendments=(),
            unapplicable=(),
            raw=text,
            problems=("The provider returned no usable diagnosis.",),
        )
    return verify(text, bundle)


def verify(text: str, bundle: Bundle) -> Diagnosis:
    """Check the model's answer against the output contract and the files on disk."""
    sections = split_sections(text)
    problems = [f"Missing section: {name}" for name in REQUIRED_SECTIONS if name not in sections]

    amendments = parse_amendments(sections.get("Repair Proposal", ""))
    proposal = sections.get("Repair Proposal", "").strip()
    if proposal and not amendments and not proposal.lower().startswith("none"):
        problems.append("Repair Proposal contains no parseable repair diffs.")
    current = {excerpt.name: excerpt for excerpt in (*bundle.governed, *bundle.blueprints)}
    applicable: list[Amendment] = []
    unapplicable: list[Amendment] = []
    for amendment in amendments:
        if amendment.file not in current and BLUEPRINT_PREFIX + amendment.file in current:
            amendment = replace(amendment, file=BLUEPRINT_PREFIX + amendment.file)
        if not amendable(amendment.file):
            unapplicable.append(amendment.rejected(f"{amendment.file} is not an amendable file"))
            continue
        excerpt = current.get(amendment.file)
        if excerpt is None or excerpt.truncated:
            unapplicable.append(
                amendment.rejected(
                    f"{amendment.file} was not read in full, so a diff cannot be verified"
                )
            )
            continue
        applied = amendment.apply_to(excerpt.text)
        if applied is None:
            unapplicable.append(amendment.rejected("the diff does not apply to the current file"))
            continue
        if applied == excerpt.text:
            unapplicable.append(amendment.rejected("the proposed repair makes no change"))
            continue
        if amendment.file.startswith(BLUEPRINT_PREFIX):
            from drydock.diagnose_repair import validate_acceptance_repair

            error = validate_acceptance_repair(excerpt.text, applied, Path(amendment.file).name)
            if error:
                unapplicable.append(amendment.rejected(error))
                continue
        applicable.append(amendment)

    return Diagnosis(
        ok=not problems,
        sections=sections,
        amendments=tuple(applicable),
        unapplicable=tuple(unapplicable),
        raw=text,
        problems=tuple(problems),
    )


def amendable(file: str) -> bool:
    """Whether a repair may target ``file``: a governed input or a top-level source Blueprint.

    Imported sources, change tickets, and compact derivatives are never repair targets.
    """
    if file in AMENDABLE:
        return True
    name = file.removeprefix(BLUEPRINT_PREFIX)
    return (
        file.startswith(BLUEPRINT_PREFIX)
        and "/" not in name
        and name.endswith(".md")
        and compact_source(name) == name
    )


def split_sections(text: str) -> dict[str, str]:
    """Split the model's answer on its ``###`` headings, keeping only the contracted ones."""
    found: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        title = match.group("title").strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if title in REQUIRED_SECTIONS:
            found[title] = text[match.end() : end].strip()
    return found


@dataclass(frozen=True)
class Written:
    """Both surfaces of one diagnosis."""

    markdown: Path
    html: Path
    stamp: str


def write_report(bundle: Bundle, diagnosis: Diagnosis, *, stamp: str = "") -> Written:
    """Write both surfaces of the diagnosis and return their paths.

    The Markdown is what an operator pastes into a ticket or hands to another agent; the page
    is what they read. Both render from the same verified diagnosis, so neither can say
    something the other does not.

    The header, ladder, and log table are written from the deterministic bundle, so they are
    correct even when the model's answer was not.
    """
    from drydock.diagnose_html import write_page

    stamp = stamp or datetime.now(UTC).strftime("%Y%m%d.%H%M%S.%f")[:-3] + "Z"
    directory = bundle.target_dir
    directory.mkdir(parents=True, exist_ok=True)
    markdown = directory / f"{REPORT_PREFIX}_{stamp}.md"
    markdown.write_text(
        render_report(bundle, diagnosis, stamp=stamp), encoding="utf-8", newline="\n"
    )
    page = write_page(bundle, diagnosis, stamp=stamp, directory=directory)
    return Written(markdown=markdown, html=page, stamp=stamp)


def render_report(bundle: Bundle, diagnosis: Diagnosis, *, stamp: str) -> str:
    """The diagnosis as text, rule-separated, in a fixed section order.

    It reads as an incident report — masthead facts, ladder, findings, cited evidence — because
    that is the shape a reader can act on. It is not titled one: this is what ``drydock
    diagnose`` produced, and naming it after the command is how an operator finds it again.
    """
    from drydock import __version__

    blocks: list[str] = []
    title = f"# Drydock Diagnosis: {bundle.target}"
    if not diagnosis.ok:
        title += "\n\n> **MALFORMED** — the diagnosis did not satisfy the output contract. "
        title += (
            "The recorded facts below stand; the model's answer is reproduced verbatim at the end."
        )
    blocks.append(title)

    blocks.append(
        "\n".join([
            "| Field | Value |",
            "|-------|-------|",
            f"| Target | `{bundle.target}` |",
            f"| Run stamp | `{bundle.run_stamp or 'not recorded'}` |",
            f"| Drydock version | {__version__} |",
            f"| Classification | {bundle.stop.classification if bundle.stop and bundle.stop.classification else 'none recorded'} |",
            f"| Milestone | {bundle.stop.milestone if bundle.stop else 'none failed'} |",
            f"| Recorded state | {bundle.stop.label if bundle.stop else '—'} |",
            f"| Stop | {bundle.stop.headline if bundle.stop else 'no live failure recorded'} |",
            f"| Report written | {stamp} |",
        ])
    )

    blocks.append("## Stage Ladder\n\n```text\n" + render_ladder(bundle.ladder) + "\n```")

    for name in REQUIRED_SECTIONS[:-1]:
        body = diagnosis.sections.get(name, "").strip()
        blocks.append(f"## {name}\n\n{body or '_Not returned by the diagnosis._'}")

    blocks.append(_log_table(bundle))
    blocks.append(_amendment_block(diagnosis))

    if bundle.missing:
        blocks.append(
            "## Missing Evidence\n\n"
            + "\n".join(f"- `{name}`" for name in bundle.missing)
            + "\n\nConclusions above were reached without these."
        )
    if not diagnosis.ok:
        problems = "\n".join(f"- {problem}" for problem in diagnosis.problems)
        blocks.append(f"## Contract Violations\n\n{problems}")
        blocks.append("## Raw Model Answer\n\n```text\n" + diagnosis.raw.strip() + "\n```")

    return _RULE.join(blocks) + "\n"


def _log_table(bundle: Bundle) -> str:
    """Local evidence paths, cited from the run's own records rather than reconstructed."""
    if not bundle.logs:
        return "## Log Files\n\nNo model-execution artifacts were recorded for this run."
    rows = [
        "| Role | Path | Bytes | SHA-256 |",
        "|------|------|-------|---------|",
    ]
    for log in bundle.logs:
        marker = "" if log.exists else " *(missing)*"
        rows.append(f"| {log.role} | `{log.path}`{marker} | {log.size} | `{log.sha256[:16]}` |")
    return (
        "## Log Files\n\nThese are local. Open them directly to verify anything above.\n\n"
        + "\n".join(rows)
    )


def _amendment_block(diagnosis: Diagnosis) -> str:
    """The amendments section, with unapplicable proposals reported rather than hidden."""
    blocks = ["## Repair Proposal"]
    if not diagnosis.amendments:
        blocks.append("None applicable.")
    for index, amendment in enumerate(diagnosis.amendments, start=1):
        blocks.append(
            f"### {index}. {amendment.summary}\n\n"
            f"**File:** `{amendment.file}`  \n"
            f"**Why:** {amendment.why}\n\n"
            f"```diff\n{amendment.diff.strip()}\n```"
        )
    if diagnosis.unapplicable:
        rejected = "\n".join(
            f"- **{item.summary}** (`{item.file}`) — {item.rejection}"
            for item in diagnosis.unapplicable
        )
        blocks.append(
            "### Not Offered\n\nThese were proposed but could not be verified against the "
            f"current files, so they were not offered for approval.\n\n{rejected}"
        )
    return "\n\n".join(blocks)


def _command_line(command) -> str:
    code = command.get("return_code")
    marker = "ok  " if int(code or 0) == 0 else "FAIL"
    return f"[{marker}] {command.get('time', '')}  {command.get('command', '')}"


def _excerpt_part(excerpt: Excerpt, fence: str, role: str):
    label = excerpt.name
    if excerpt.truncated:
        label = f"{excerpt.name} (last lines of {excerpt.total_lines})"
    if fence == "markdown":
        return fenced_markdown_part(label, excerpt.text, role=role, path=Path(excerpt.path))
    return fenced_block_part(label, excerpt.text, fence=fence, role=role, path=Path(excerpt.path))


def _numbered_part(excerpt: Excerpt):
    """A governed file with line numbers, so the model can author a diff that applies."""
    numbered = "\n".join(
        f"{index:>5}\t{line}" for index, line in enumerate(excerpt.text.splitlines(), start=1)
    )
    label = excerpt.name
    if excerpt.truncated:
        label = f"{excerpt.name} (first {len(excerpt.text.splitlines())} of {excerpt.total_lines} lines — NOT AMENDABLE)"
    return fenced_block_part(
        label, numbered, fence="text", role="amendable", path=Path(excerpt.path)
    )


def _sections_present(text: str) -> Sequence[str]:
    return [match.group("title").strip() for match in _SECTION_RE.finditer(text)]
