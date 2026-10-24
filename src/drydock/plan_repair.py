"""``drydock plan repair`` — make unrunnable acceptance criteria runnable, once.

Paired with ``drydock plan verify``::

    drydock plan verify <Target> || drydock plan repair <Target>

Verification is free, so it runs every time; repair costs one model call, so the ``||`` idiom
pays for it only when verify's exit status says the plan is not fit to build — i.e. only when
there is a defect. Verify's warnings (advisories) are never sent to repair and never trigger a
call on their own; repairing an advisory is out of this command's scope.

One call for the whole pass, not one call per file. Every defective criterion across every
Blueprint file is sent in a single request, each as its own minimal fenced block — nothing else
about its file, and nothing about any other file. What stays true: one attempt per criterion,
surgical splice, re-verify before keeping a write.

Scope. This repairs *mechanics*: a criterion that raises before it asserts anything — a missing
import, an undefined name, a syntax error. It never touches what a criterion asserts. A criterion
whose expected value is wrong is a different fault with a different remedy: it fails at build time
on the evidence of its own traceback, and the build's repair loop owns it. Trying to decide
correctness from the text is the class of analyzer Drydock has already retracted twice.

One attempt. If a criterion is still broken after one call, a second call is being asked the same
question by the same model with the same context, and the honest answer is to stop and say which
criteria remain unrunnable. The plan stays where it is; nothing is half-written.

Writes are deterministic and surgical. The model emits one composite-keyed
``=== AC <file> :: <id> === ... === END AC <file> :: <id> ===`` block per criterion in its single
combined response; this module reassembles each into its file's own plain delimiter form and
splices it over the block it replaces, by exact span. Each file is re-verified once after its
full splice; a criterion still broken or missing is reverted to its own original block, leaving
every sibling criterion that repaired correctly untouched. A file is rolled back whole only if the
full splice leaves the file itself unparseable — that failure has no addressable per-criterion
recovery.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock import technology_stack
from drydock.acceptance import (
    ProgrammaticAcceptance,
    parse_programmatic_acceptance,
    parse_programmatic_acceptance_text,
    regex_defects,
    selection_probe_reason,
    split_fused_acceptance_boundary,
    staged_regex_defects,
    syntax_defect,
    unresolved_globals,
)
from drydock.errors import SpecificationError
from drydock.harness_exits import go_cli_defect
from drydock.llm import failure_detail, run_prompt
from drydock.plan_verify import CRITERIA_MISSING, OPERATION_UNTESTED, Defect, verify
from drydock.prompt_assembly import (
    PromptAssembly,
    PromptPart,
    contextual_markdown_parts,
    fenced_body,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

PROMPT_NAME = "plan_repair"

#: The model reports this when a criterion cannot be made runnable without changing what it
#: asserts. Recorded as unrepaired rather than treated as a failure: it is a correct answer.
_IMPOSSIBLE_RE = re.compile(r"^\s*REPAIR_IMPOSSIBLE:\s*(?P<key>.+?)\s+—\s+(?P<why>.*)$", re.M)

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


def _still_broken(check: ProgrammaticAcceptance, *, source_root: Path) -> str | None:
    """Return why a criterion still cannot run, or ``None``. The same test verification uses."""
    code = check.code
    if (reason := syntax_defect(code)) is not None:
        return reason
    if defect := go_cli_defect(
        code,
        go=any(
            Path(name).name == "go.md" for name in technology_stack.stack_files(source_root.parent)
        ),
    ):
        return defect[1]
    if reasons := regex_defects(code):
        return "; ".join(reasons)
    if reasons := staged_regex_defects(code, source_root):
        return "; ".join(reasons)
    if (probe := selection_probe_reason(check, blueprint_dir=source_root)) is not None:
        return probe[1]
    if names := unresolved_globals(code):
        return "reads undefined global name(s): " + ", ".join(f"`{n}`" for n in sorted(names))
    return None


def _blocks(text: str) -> dict[str, tuple[int, int, str]]:
    """Map criterion id to ``(start, end, whole-block-text)`` spans in a specification."""
    return {
        match.group("id").strip(): (match.start(), match.end(), match.group(0))
        for match in _BLOCK_RE.finditer(text)
    }


def _block_bodies(text: str) -> dict[str, str]:
    """Map each criterion id in a file to its own AC-block body (``Intent:`` plus code)."""
    return {match.group("id").strip(): match.group("body") for match in _BLOCK_RE.finditer(text)}


def _split_composite(key: str) -> tuple[str, str]:
    """Split a response's ``<file> :: <check_id>`` id back into its two parts."""
    file, _, check_id = key.strip().partition(" :: ")
    return file.strip(), check_id.strip()


def _response_blocks(text: str) -> dict[tuple[str, str], str]:
    """Map ``(file, check_id)`` to the repaired body from the model's one combined response.

    Keyed by the composite id the model echoes back, since check_ids are only unique within a
    file once a single response can carry blocks from many files.
    """
    result: dict[tuple[str, str], str] = {}
    for match in _BLOCK_RE.finditer(text):
        key = _split_composite(match.group("id"))
        body = match.group("body")
        # Only unwrap one fence enclosing the complete proof after its declarations.
        # Embedded fences may be product input inside a Python string and stay verbatim.
        fenced = re.fullmatch(
            r"(?P<meta>(?:[ \t]*\n|(?:Intent|Suite|Requires|Sea Trials|Gate|Encoding|Probe|Probe Count|Cite):[^\n]*\n)*)"
            r"```python[ \t]*\n(?P<code>.*?)\n```[ \t]*\n?",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if fenced is not None:
            candidate = fenced["meta"] + fenced["code"] + "\n"
            # Reject ambiguous boundaries; never remove fences from a Python literal.
            try:
                checks = parse_programmatic_acceptance_text(
                    "## Programmatic Acceptance\n\n" + _plain_block(key[1], candidate),
                    source=key[0],
                )
            except ValueError:
                checks = ()
            if len(checks) == 1 and syntax_defect(checks[0].code) is None:
                body = candidate
        result[key] = body
    return result


def _plain_block(check_id: str, body: str) -> str:
    """Reassemble a response body into the on-disk file's own plain delimiter shape.

    The model's response is keyed by a composite ``<file> :: <check_id>`` id; that composite form
    must never be written to a Blueprint file.
    """
    return f"=== AC {check_id} ===\n{body.rstrip(chr(10))}\n=== END AC {check_id} ===\n"


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


def _defect_part(defect: Defect, body: str) -> PromptPart:
    """One minimal, self-contained block for one defective criterion.

    Carries only that criterion's own AC-block body (``Intent:`` plus code) and the defect that
    blocks it — never its file's other criteria, and never any other file's content. The code is
    fenced, not XML-escaped: real criteria routinely contain ``<``, ``>``, ``&``, and backslashes
    (regex literals, escaped quotes), and fencing preserves them byte for byte.
    """
    text = (
        f'<pblock file="{defect.filename}" check_id="{defect.check_id}" kind="{defect.kind}">\n'
        f"Error: {defect.detail}\n\n"
        f"{fenced_body(body, 'python')}\n"
        "</pblock>\n\n"
    )
    return part(f"{defect.filename} :: {defect.check_id}", text, kind="defect")


def _assemble(body: str, *, jobs: list[tuple[Defect, str]]) -> PromptAssembly:
    """Build one repair prompt for every defective criterion across every file, in one call.

    Deterministic, so it is unit-testable without a process. Each job carries only its own
    criterion's AC-block body — never the rest of its file, and never another file's content.
    """
    parts: list[PromptPart] = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Repair job",
            [
                "## Repair job",
                "",
                f"- DATE: {date.today().isoformat()}",
                f"- CRITERIA: {len(jobs)}",
                "",
            ],
            kind="job",
        ),
    ]
    parts.extend(_defect_part(defect, block_body) for defect, block_body in jobs)
    parts.append(section_heading_part("# Agent Task"))
    parts.append(part("Prompt body", body + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(parts))


def _assemble_container(
    body: str, *, rel_source: str, source_text: str, container_defect: Defect
) -> PromptAssembly:
    """Build the whole-file container-repair prompt.

    A malformed container has no addressable per-criterion span, so this job stays scoped to one
    file's full source — independent of the batched, minimal-context defect-repair call above.
    """
    lines = [
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
            lines_part("Container defect", lines, kind="section"),
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


def _splice_and_revert(
    filename: str,
    path: Path,
    original: str,
    defects: list[Defect],
    emitted: dict[tuple[str, str], str],
    impossible: dict[tuple[str, str], str],
    *,
    source_root: Path,
) -> tuple[list[RepairItem], bool]:
    """Splice every applicable criterion for one file out of the shared batch response.

    Reverts per criterion, not per file: a criterion still broken or missing after re-parse is
    reverted to its own original block; every sibling criterion that repaired correctly in the
    same call stays spliced in. The file is rolled back whole only when the full splice leaves
    the file itself unparseable — there is no addressable sub-file recovery from that.
    """
    before = _blocks(original)
    text = original
    applied: list[str] = []
    items: list[RepairItem] = []

    # Splice from the end so earlier spans keep their offsets.
    for defect in sorted(
        defects, key=lambda d: before.get(d.check_id, (0, 0, ""))[0], reverse=True
    ):
        span = before.get(defect.check_id)
        if span is None:
            items.append(
                RepairItem(
                    filename, defect.check_id, "unrepaired", "", "criterion not found in file"
                )
            )
            continue
        start, end, old = span
        key = (filename, defect.check_id)
        if key in impossible:
            items.append(
                RepairItem(
                    filename,
                    defect.check_id,
                    "impossible",
                    old,
                    impossible[key] or "cannot run without changing what it asserts",
                )
            )
            continue
        body = emitted.get(key)
        if body is None:
            items.append(
                RepairItem(filename, defect.check_id, "not-emitted", old, "no block returned")
            )
            continue
        text = text[:start] + _plain_block(defect.check_id, body) + text[end:]
        applied.append(defect.check_id)

    if not applied:
        return items, False

    path.write_text(text, encoding="utf-8", newline="\n")
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
        return items, False

    broken: dict[str, str] = {}
    for check_id in applied:
        check = checks.get(check_id)
        if check is None:
            broken[check_id] = "repair dropped the criterion and was reverted"
            continue
        if (reason := _still_broken(check, source_root=source_root)) is not None:
            broken[check_id] = reason

    if broken:
        # Revert only the criteria that are still bad, locating their spans in the *post-splice*
        # text — the successfully repaired siblings shifted the offsets recorded in ``before``.
        current = _blocks(text)
        for check_id in sorted(
            broken, key=lambda cid: current.get(cid, (0, 0, ""))[0], reverse=True
        ):
            span = current.get(check_id)
            if span is not None:
                start, end, _ = span
                text = text[:start] + before[check_id][2] + text[end:]
        path.write_text(text, encoding="utf-8", newline="\n")
        try:
            parse_programmatic_acceptance(path)
        except ValueError as exc:
            # Reverting byte-identical original spans should always restore parseability. If it
            # somehow doesn't, there is nothing addressable left to try.
            path.write_text(original, encoding="utf-8", newline="\n")
            for check_id in applied:
                items.append(
                    RepairItem(
                        filename,
                        check_id,
                        "unrepaired",
                        before[check_id][2],
                        f"repair left the file unparseable after reverts and was reverted: {exc}",
                    )
                )
            return items, False

    changed = bool(set(applied) - set(broken))
    for check_id in applied:
        if check_id in broken:
            items.append(
                RepairItem(filename, check_id, "unrepaired", before[check_id][2], broken[check_id])
            )
        else:
            items.append(RepairItem(filename, check_id, "repaired", before[check_id][2], ""))
    return items, changed


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
    """Repair every criterion ``plan verify`` reports as unrunnable, in one call."""
    run = runner if runner is not None else run_prompt
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    found = verify(target, target_dir)
    if not found.defects:
        return RepairResult(target=target, nothing_to_repair=True)

    def emit(message: str) -> None:
        if on_text is not None:
            on_text(message + "\n")

    container_by_file: dict[str, Defect] = {}
    by_file: dict[str, list[Defect]] = {}
    items: list[RepairItem] = []
    for defect in found.defects:
        if defect.kind.startswith("database-"):
            # The persistence declaration is not a criterion; the criterion prompt cannot repair
            # it, and handing it one would rewrite DATABASE.md as an acceptance container. It
            # stays unrepaired so the command cannot report a buildable plan it did not produce.
            items.append(
                RepairItem(
                    defect.filename,
                    "",
                    "unrepaired",
                    "",
                    f"{defect.detail} — persistence is repaired by `drydock plan {target}`",
                )
            )
            continue
        if defect.kind in (CRITERIA_MISSING, OPERATION_UNTESTED):
            # Not a criterion to rewrite: there is none. Authoring one needs the story's
            # behavior, which Plan's artifact repair holds and this prompt does not.
            items.append(
                RepairItem(
                    defect.filename,
                    "",
                    "unrepaired",
                    "",
                    f"{defect.detail} — criteria are authored by `drydock plan {target}`",
                )
            )
            continue
        if not defect.check_id:
            container_by_file[defect.filename] = defect
            continue
        by_file.setdefault(defect.filename, []).append(defect)

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
        assembly = _assemble_container(
            prompt.body,
            rel_source=filename,
            source_text=original,
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
                failure_detail(result) if not result.ok else "no repaired specification returned"
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

    if by_file:
        originals: dict[str, str] = {}
        jobs: list[tuple[Defect, str]] = []
        for filename in sorted(by_file):
            original = (blueprint_dir / filename).read_text(encoding="utf-8")
            originals[filename] = original
            bodies = _block_bodies(original)
            for defect in by_file[filename]:
                jobs.append((defect, bodies.get(defect.check_id, "")))

        emit(
            "repair: "
            + ", ".join(sorted(by_file))
            + f" · {len(jobs)} {'criterion' if len(jobs) == 1 else 'criteria'} · 1 of 1 attempt"
        )
        assembly = _assemble(prompt.body, jobs=jobs)
        result = run(
            assembly.rendered_text,
            blueprint_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="plan repair",
            parameters={"target": target, "files": len(by_file), "criteria": len(jobs)},
            log_dir=log_dir,
            target=target,
            prompt_assembly=assembly,
        )
        if result.execution_id:
            execution_ids.append(result.execution_id)

        if not result.ok or not result.text.strip():
            detail = failure_detail(result) if not result.ok else "empty output"
            for filename in sorted(by_file):
                before = _blocks(originals[filename])
                for defect in by_file[filename]:
                    item = RepairItem(
                        filename,
                        defect.check_id,
                        "unrepaired",
                        before.get(defect.check_id, (0, 0, ""))[2],
                        detail,
                    )
                    items.append(item)
                    if on_item is not None:
                        on_item(item)
                    emit(f"  ✗  {item.rendered}")
        else:
            emitted = _response_blocks(result.text)
            impossible = {
                _split_composite(match.group("key")): match.group("why").strip()
                for match in _IMPOSSIBLE_RE.finditer(result.text)
            }
            for filename in sorted(by_file):
                file_items, file_changed = _splice_and_revert(
                    filename,
                    blueprint_dir / filename,
                    originals[filename],
                    by_file[filename],
                    emitted,
                    impossible,
                    source_root=blueprint_dir,
                )
                items.extend(file_items)
                if file_changed:
                    changed.append(filename)
                for item in file_items:
                    if on_item is not None:
                        on_item(item)
                    emit(f"  {'✓' if item.status == 'repaired' else '✗'}  {item.rendered}")

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
