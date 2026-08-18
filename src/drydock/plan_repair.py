"""``drydock plan repair`` — make unrunnable acceptance criteria runnable, once.

Paired with ``drydock plan verify`` and meaningless without it::

    drydock plan verify <Target> || drydock plan repair <Target>

Verification is free, so it runs every time; repair costs a model call, so it runs only when
there is something to repair. That asymmetry is the whole reason the two are separate commands.

Scope. This repairs *mechanics*: a criterion that raises before it asserts anything — a missing
import, an undefined name, a syntax error. It never touches what a criterion asserts. A criterion
whose expected value is wrong is a different fault with a different remedy: it fails at build time
on the evidence of its own traceback, and the build's repair loop owns it. Trying to decide
correctness from the text is the class of analyzer Drydock has already retracted twice.

One attempt. If a criterion is still broken after one call, a second call is being asked the same
question by the same model with the same context, and the honest answer is to stop and say which
criteria remain unrunnable. The plan stays where it is; nothing is half-written.

Writes are deterministic and surgical. The model emits whole ``=== AC id ===`` blocks; this module
splices each one over the block it replaces, by exact delimiter match, and re-verifies the file
before keeping it. A file that fails to re-verify is rolled back to its original bytes, so a
repair can never leave a Blueprint worse than it found it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock.acceptance import parse_programmatic_acceptance, syntax_defect, unresolved_globals
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.plan_verify import Defect, verify
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

PROMPT_NAME = "plan_repair"

#: The model reports this when a criterion cannot be made runnable without changing what it
#: asserts. Recorded as unrepaired rather than treated as a failure: it is a correct answer.
_IMPOSSIBLE_RE = re.compile(r"^\s*REPAIR_IMPOSSIBLE:\s*(?P<id>\S+)\s*[-—:]?\s*(?P<why>.*)$", re.M)

_BLOCK_RE = re.compile(
    r"^=== AC (?P<id>[^=\n]+?) ===[ \t]*$\n(?P<body>.*?)^=== END AC (?P=id) ===[ \t]*$\n?",
    re.MULTILINE | re.DOTALL,
)


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class RepairItem:
    """One criterion Drydock tried to make runnable, and what became of it."""

    filename: str
    check_id: str
    #: ``repaired`` | ``unrepaired`` | ``impossible`` | ``not-emitted``
    status: str
    before: str
    detail: str = ""

    @property
    def rendered(self) -> str:
        suffix = f" — {self.detail}" if self.detail else ""
        return f"{self.filename} [{self.check_id}]: {self.status}{suffix}"


@dataclass(frozen=True)
class RepairResult:
    """The outcome of one repair pass. ``ok`` means every defect found is now runnable."""

    target: str
    items: tuple[RepairItem, ...] = ()
    files_changed: tuple[str, ...] = ()
    execution_ids: tuple[str, ...] = ()
    error: str | None = None
    #: True when verification found nothing to do, so no model call was made.
    nothing_to_repair: bool = False

    @property
    def repaired(self) -> tuple[RepairItem, ...]:
        return tuple(item for item in self.items if item.status == "repaired")

    @property
    def outstanding(self) -> tuple[RepairItem, ...]:
        return tuple(item for item in self.items if item.status != "repaired")

    @property
    def ok(self) -> bool:
        return self.error is None and not self.outstanding

    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _still_broken(code: str) -> str | None:
    """Return why a criterion still cannot run, or ``None``. The same test verification uses."""
    if (reason := syntax_defect(code)) is not None:
        return reason
    if names := unresolved_globals(code):
        return "reads undefined global name(s): " + ", ".join(f"`{n}`" for n in sorted(names))
    return None


def _blocks(text: str) -> dict[str, tuple[int, int, str]]:
    """Map criterion id to ``(start, end, whole-block-text)`` spans in a specification."""
    return {
        match.group("id").strip(): (match.start(), match.end(), match.group(0))
        for match in _BLOCK_RE.finditer(text)
    }


def _assemble(
    body: str,
    *,
    rel_source: str,
    source_text: str,
    defects: list[Defect],
    advisories: tuple[str, ...] = (),
) -> PromptAssembly:
    """Build the repair prompt. Deterministic, so it is unit-testable without a process."""
    lines = ["## Criteria that cannot run", ""]
    for defect in defects:
        lines.append(f"- `{defect.check_id}` — {defect.detail}")
    lines.append("")
    if advisories:
        # Verification's non-fatal findings for this file. They never justify a call of their
        # own — a criterion that runs is not worth a model call — but a call already being paid
        # for can carry them.
        lines += ["## Advisories for this file (act only while repairing it)", ""]
        lines += [f"- {advisory}" for advisory in advisories]
        lines.append("")
    return PromptAssembly(
        parts=(
            system_preamble_part(),
            section_heading_part("# Input Context"),
            lines_part(
                "Repair job",
                [
                    "## Repair job",
                    "",
                    f"- SPEC_FILE: {rel_source}",
                    f"- DATE: {date.today().isoformat()}",
                    "",
                ],
                kind="job",
            ),
            lines_part("Defects", lines, kind="section"),
            *contextual_markdown_parts(
                rel_source,
                source_text,
                filename=Path(rel_source).name,
                role="specification under repair",
            ),
            section_heading_part("# Agent Task"),
            part("Prompt body", body + "\n\n", kind="prompt-body"),
        )
    )


def repair(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    on_item: Callable[[RepairItem], None] | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
) -> RepairResult:
    """Repair every criterion ``plan verify`` reports as unrunnable. One call per file."""
    run = runner if runner is not None else run_prompt
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    found = verify(target, target_dir)
    if found.ok:
        return RepairResult(target=target, nothing_to_repair=True)

    def emit(message: str) -> None:
        if on_text is not None:
            on_text(message + "\n")

    by_file: dict[str, list[Defect]] = {}
    items: list[RepairItem] = []
    for defect in found.defects:
        if not defect.check_id:
            # An unparseable file has no criterion to replace and no safe splice point. Repair
            # declines it rather than guessing at the container's structure.
            items.append(
                RepairItem(
                    defect.filename, "", "impossible", "", "file does not parse: " + defect.detail
                )
            )
            continue
        by_file.setdefault(defect.filename, []).append(defect)

    prompt = load_prompt(PROMPT_NAME)
    changed: list[str] = []
    execution_ids: list[str] = []

    for filename, defects in sorted(by_file.items()):
        path = blueprint_dir / filename
        original = path.read_text(encoding="utf-8")
        before = _blocks(original)
        emit(
            f"repair: {filename} · "
            + ", ".join(defect.check_id for defect in defects)
            + " · 1 of 1 attempt"
        )
        assembly = _assemble(
            prompt.body,
            rel_source=filename,
            source_text=original,
            defects=defects,
            advisories=tuple(
                warning for warning in found.warnings if warning.startswith(f"{filename} [")
            ),
        )
        result = run(
            assembly.rendered_text,
            blueprint_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="plan repair",
            parameters={"target": target, "spec": filename},
            log_dir=log_dir,
            target=target,
            prompt_assembly=assembly,
        )
        if result.execution_id:
            execution_ids.append(result.execution_id)
        if not result.ok or not result.text.strip():
            for defect in defects:
                items.append(
                    RepairItem(
                        filename,
                        defect.check_id,
                        "unrepaired",
                        before.get(defect.check_id, (0, 0, ""))[2],
                        "LLM execution failed" if not result.ok else "empty output",
                    )
                )
            continue

        impossible = {
            match.group("id").strip(): match.group("why").strip()
            for match in _IMPOSSIBLE_RE.finditer(result.text)
        }
        emitted = _blocks(result.text)

        # Splice from the end so earlier spans keep their offsets. Only the criteria that were
        # reported defective are eligible: a model that returns a bonus block for an untouched
        # criterion does not get to rewrite it.
        text = original
        applied: list[str] = []
        for defect in sorted(
            defects, key=lambda d: before.get(d.check_id, (0, 0, ""))[0], reverse=True
        ):
            span = before.get(defect.check_id)
            replacement = emitted.get(defect.check_id)
            if span is None:
                items.append(
                    RepairItem(
                        filename, defect.check_id, "unrepaired", "", "criterion not found in file"
                    )
                )
                continue
            start, end, old = span
            if defect.check_id in impossible:
                items.append(
                    RepairItem(
                        filename,
                        defect.check_id,
                        "impossible",
                        old,
                        impossible[defect.check_id]
                        or "cannot run without changing what it asserts",
                    )
                )
                continue
            if replacement is None:
                items.append(
                    RepairItem(filename, defect.check_id, "not-emitted", old, "no block returned")
                )
                continue
            # The emitted block may arrive without its final newline; the span it replaces always
            # ends with one. Normalise so the delimiter can never be glued to the following line.
            text = text[:start] + replacement[2].rstrip("\n") + "\n" + text[end:]
            applied.append(defect.check_id)

        if not applied:
            continue

        path.write_text(text, encoding="utf-8", newline="\n")
        # Re-verify from disk, through the same parser the build uses. A splice that produced a
        # file the parser cannot read is worse than the defect it fixed, so it is reverted whole.
        try:
            checks = {check.check_id: check for check in parse_programmatic_acceptance(path)}
        except ValueError as exc:
            path.write_text(original, encoding="utf-8", newline="\n")
            for check_id in applied:
                items.append(
                    RepairItem(
                        filename,
                        check_id,
                        "unrepaired",
                        before[check_id][2],
                        f"repair left the file unparseable and was reverted: {exc}",
                    )
                )
            continue

        reverted = False
        for check_id in applied:
            check = checks.get(check_id)
            if check is None:
                reverted = True
                break
        if reverted:
            path.write_text(original, encoding="utf-8", newline="\n")
            for check_id in applied:
                items.append(
                    RepairItem(
                        filename,
                        check_id,
                        "unrepaired",
                        before[check_id][2],
                        "repair dropped the criterion and was reverted",
                    )
                )
            continue

        changed.append(filename)
        for check_id in applied:
            reason = _still_broken(checks[check_id].code)
            item = RepairItem(
                filename,
                check_id,
                "unrepaired" if reason else "repaired",
                before[check_id][2],
                reason or "",
            )
            items.append(item)
            if on_item is not None:
                on_item(item)
            emit(f"  {'✗' if reason else '✓'}  {item.rendered}")

    return RepairResult(
        target=target,
        items=tuple(items),
        files_changed=tuple(sorted(set(changed))),
        execution_ids=tuple(execution_ids),
    )


def render(result: RepairResult) -> str:
    """Render the outcome for a terminal."""
    if result.nothing_to_repair:
        return f"plan repair: {result.target}\n  nothing to repair"
    lines = [f"plan repair: {result.target}"]
    if result.error:
        lines.append(f"  error: {result.error}")
    lines.append(
        f"  {len(result.repaired)} repaired, {len(result.outstanding)} outstanding, "
        f"{len(result.files_changed)} "
        f"{'file' if len(result.files_changed) == 1 else 'files'} changed"
    )
    for item in result.outstanding:
        lines.append(f"  ✗  {item.rendered}")
    return "\n".join(lines)
