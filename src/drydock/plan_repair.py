"""``drydock plan repair`` — make unrunnable acceptance criteria runnable, once.

Paired with ``drydock plan verify``::

    drydock plan verify <Target> || drydock plan repair <Target>

Verification is free, so it runs every time; repair costs a model call, so the ``||`` idiom pays
for it only when verify's exit status says the plan is not fit to build — i.e. only when there is
a defect. Verify's warnings (advisories) never fail its exit status by design, so they never
trigger that idiom on their own.

Called directly, ``plan repair`` also makes one call per file whose only findings are advisories —
otherwise an advisory-only file, one that never fails ``plan verify``, could never be repaired at
all. What stays true from the defect case: one attempt per file, surgical splice, re-verify before
keeping the write.

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

from drydock.acceptance import (
    parse_programmatic_acceptance,
    regex_defects,
    split_fused_acceptance_boundary,
    staged_regex_defects,
    syntax_defect,
    unresolved_globals,
)
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

_REPAIRED_SPEC_RE = re.compile(
    r"^=== BEGIN REPAIRED SPECIFICATION ===[ \t]*$\n?(?P<text>.*?)"
    r"^=== END REPAIRED SPECIFICATION ===[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_AC_DELIMITER_RE = re.compile(r"^=== (?:END )?AC [^\n]*$")

#: Pulls the criterion id back out of a ``VerifyResult.warning`` string, whose format is fixed by
#: ``plan_verify.verify`` as ``f"{filename} [{check_id}]: {detail}"``.
_WARNING_ID_RE = re.compile(r"^\S+ \[(?P<id>[^\]]+)\]: ")


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


def _still_broken(code: str, *, source_root: Path) -> str | None:
    """Return why a criterion still cannot run, or ``None``. The same test verification uses."""
    if (reason := syntax_defect(code)) is not None:
        return reason
    if reasons := regex_defects(code):
        return "; ".join(reasons)
    if reasons := staged_regex_defects(code, source_root):
        return "; ".join(reasons)
    if names := unresolved_globals(code):
        return "reads undefined global name(s): " + ", ".join(f"`{n}`" for n in sorted(names))
    return None


def _blocks(text: str) -> dict[str, tuple[int, int, str]]:
    """Map criterion id to ``(start, end, whole-block-text)`` spans in a specification."""
    return {
        match.group("id").strip(): (match.start(), match.end(), match.group(0))
        for match in _BLOCK_RE.finditer(text)
    }


def _container_repair_text(text: str) -> str | None:
    """Return a wrapped full-spec repair, or ``None`` when the response is not that protocol."""
    match = _REPAIRED_SPEC_RE.search(text)
    return match.group("text").rstrip("\n") + "\n" if match is not None else None


def _only_ac_delimiters_changed(original: str, repaired: str) -> bool:
    """Require a container repair to alter only AC delimiter lines.

    A malformed container has no safe criterion span.  The model therefore repairs the whole
    file, but this deterministic guard limits the retained mutation to its delimiters.
    """

    def non_delimiters(text: str) -> list[str]:
        return [line for line in text.splitlines() if not _AC_DELIMITER_RE.fullmatch(line)]

    return non_delimiters(original) == non_delimiters(repaired)


def _assemble(
    body: str,
    *,
    rel_source: str,
    source_text: str,
    defects: list[Defect],
    improve: tuple[Defect, ...] = (),
    advisories: tuple[str, ...] = (),
    container_defect: Defect | None = None,
) -> PromptAssembly:
    """Build the repair prompt. Deterministic, so it is unit-testable without a process."""
    lines = ["## Criteria that cannot run", ""]
    for defect in defects:
        lines.append(f"- `{defect.check_id}` — {defect.detail}")
    lines.append("")
    if improve:
        # These criteria already run and judge correctly — plan verify would not gate the plan
        # over them — but this call is already paying for the file, so fix what the advisory
        # names. Never touch anything this criterion asserts, same as a defect repair.
        lines += [
            "## Criteria to improve (no defect — repair the issue named, re-emit the block)",
            "",
        ]
        for defect in improve:
            lines.append(f"- `{defect.check_id}` — {defect.detail}")
        lines.append("")
    if advisories:
        # Verification's non-fatal findings for this file that are riding along with a defect
        # repair already happening on the same criterion — informational, not a separate ask.
        lines += ["## Advisories for this file (act only while repairing it)", ""]
        lines += [f"- {advisory}" for advisory in advisories]
        lines.append("")
    if container_defect is not None:
        lines += [
            "## Bad acceptance container",
            "",
            f"- {container_defect.detail}",
            "- Repair only `=== AC ... ===` and `=== END AC ... ===` delimiter lines.",
            "",
        ]
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
    if not found.defects and not found.warnings:
        return RepairResult(target=target, nothing_to_repair=True)

    def emit(message: str) -> None:
        if on_text is not None:
            on_text(message + "\n")

    by_file: dict[str, list[Defect]] = {}
    container_by_file: dict[str, Defect] = {}
    items: list[RepairItem] = []
    for defect in found.defects:
        if not defect.check_id:
            container_by_file[defect.filename] = defect
            continue
        by_file.setdefault(defect.filename, []).append(defect)

    # Every warning, parsed back to the file and criterion it names. A warning whose criterion
    # already has a defect keeps riding along with that defect's call, unchanged; a warning whose
    # criterion has no defect becomes its own repair target, so it is never simply unreachable.
    parsed_warnings: list[tuple[str, str, str]] = []
    for warning in found.warnings:
        match = _WARNING_ID_RE.match(warning)
        if match is None:
            continue
        parsed_warnings.append((
            warning[: warning.index(" [")],
            match.group("id"),
            warning[match.end() :],
        ))

    improve_by_file: dict[str, list[Defect]] = {}
    for filename, check_id, detail in parsed_warnings:
        if any(d.check_id == check_id for d in by_file.get(filename, [])):
            continue
        improve_by_file.setdefault(filename, []).append(
            Defect(filename, check_id, "advisory", detail)
        )

    prompt = load_prompt(PROMPT_NAME)
    changed: list[str] = []
    execution_ids: list[str] = []

    for filename, defect in sorted(container_by_file.items()):
        path = blueprint_dir / filename
        original = path.read_text(encoding="utf-8")

        # A fused acceptance boundary — two criteria under one opener, closed with the second
        # criterion's id — is mechanically decidable, unlike a general malformed container. Fix
        # it deterministically before spending a model call: an LLM asked to fix this shape
        # reliably renames the wrong closer but never inserts the missing opener, so it fails on
        # every attempt regardless of retries.
        split = split_fused_acceptance_boundary(original)
        if split is not None:
            repaired_text, messages = split
            path.write_text(repaired_text, encoding="utf-8", newline="\n")
            try:
                parse_programmatic_acceptance(path)
            except ValueError:
                path.write_text(original, encoding="utf-8", newline="\n")
            else:
                item = RepairItem(
                    filename,
                    "",
                    "repaired",
                    original,
                    "acceptance container repaired deterministically: " + "; ".join(messages),
                )
                items.append(item)
                changed.append(filename)
                if on_item is not None:
                    on_item(item)
                emit(f"  ✓  {item.rendered}")
                continue

        emit(f"repair: {filename} · acceptance container · 1 of 1 attempt")
        assembly = _assemble(
            prompt.body,
            rel_source=filename,
            source_text=original,
            defects=[],
            container_defect=defect,
        )
        result = run(
            assembly.rendered_text,
            blueprint_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="plan repair",
            parameters={"target": target, "spec": filename, "repair": "acceptance-container"},
            log_dir=log_dir,
            target=target,
            prompt_assembly=assembly,
        )
        if result.execution_id:
            execution_ids.append(result.execution_id)
        repaired = _container_repair_text(result.text) if result.ok else None
        if repaired is None:
            detail = (
                "LLM execution failed" if not result.ok else "no repaired specification returned"
            )
        elif not _only_ac_delimiters_changed(original, repaired):
            detail = "repair changed content other than AC delimiters and was reverted"
        else:
            path.write_text(repaired, encoding="utf-8", newline="\n")
            try:
                parse_programmatic_acceptance(path)
            except ValueError as exc:
                path.write_text(original, encoding="utf-8", newline="\n")
                detail = f"repair left the acceptance container unparseable and was reverted: {exc}"
            else:
                item = RepairItem(
                    filename, "", "repaired", original, "acceptance container repaired"
                )
                items.append(item)
                changed.append(filename)
                if on_item is not None:
                    on_item(item)
                emit(f"  ✓  {item.rendered}")
                continue
        item = RepairItem(filename, "", "unrepaired", original, detail)
        items.append(item)
        if on_item is not None:
            on_item(item)
        emit(f"  ✗  {item.rendered}")

    for filename in sorted(set(by_file) | set(improve_by_file)):
        defects = by_file.get(filename, [])
        improve = improve_by_file.get(filename, [])
        targets = defects + improve
        path = blueprint_dir / filename
        original = path.read_text(encoding="utf-8")
        before = _blocks(original)
        emit(
            f"repair: {filename} · "
            + ", ".join(defect.check_id for defect in targets)
            + " · 1 of 1 attempt"
        )
        assembly = _assemble(
            prompt.body,
            rel_source=filename,
            source_text=original,
            defects=defects,
            improve=tuple(improve),
            advisories=tuple(
                f"{wfile} [{wid}]: {detail}"
                for wfile, wid, detail in parsed_warnings
                if wfile == filename and any(d.check_id == wid for d in defects)
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
            for defect in targets:
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
        # named — as a defect or as something to improve — are eligible: a model that returns a
        # bonus block for an untouched criterion does not get to rewrite it.
        text = original
        applied: list[str] = []
        for defect in sorted(
            targets, key=lambda d: before.get(d.check_id, (0, 0, ""))[0], reverse=True
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
            reason = _still_broken(checks[check_id].code, source_root=blueprint_dir)
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
