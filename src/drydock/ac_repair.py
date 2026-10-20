"""AC repair — rewrite criteria that cannot attribute a failure to the product, blind to it.

Two kinds of criterion reach here. A ``malformed`` one dies in its own frame and measures nothing.
A ``disputed`` one runs, but its expected value was typed by hand, so its miss cannot be charged
to the product or to itself. Both are criterion defects, and both are repaired the same way: one
model call, given each criterion's declarations, code, fault, its specification, and the imported
source material, and never the product or anything it printed.

A repair is kept only when the repaired criterion still parses under its own id, can run, is
binding, cites truthfully, is not vacuous, and records VALID on the empty-directory baseline: red
with no product present. Anything else is reverted and the original criterion records UNFIXABLE,
which is terminal until a human edits it. Selection is deterministic and runs before any call, so
a Target with nothing to repair spends nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from drydock.acceptance import (
    ProgrammaticAcceptance,
    all_programmatic_acceptance,
    citation_defect,
    parse_programmatic_acceptance_text,
    resolve_citation,
)
from drydock.acceptance_status import (
    ERROR_ENVIRONMENT,
    ERROR_MALFORMED,
    ERROR_REPAIR_IMPOSSIBLE,
    ERROR_REPAIR_REJECTED,
    ERROR_REPAIRED,
    OUTCOME_DISPUTED,
    STATUS_ERROR,
    STATUS_UNFIXABLE,
    STATUS_VALID,
    TERMINAL_STATUSES,
    acceptance_history,
    classify_baseline,
    current_status,
    observe_empty_baseline,
    read_acceptance_status,
    record_status,
)
from drydock.build_plan import parse_build_plan
from drydock.llm import failure_detail, run_prompt
from drydock.plan_repair import (
    _IMPOSSIBLE_RE,
    _blocks,
    _plain_block,
    _response_blocks,
    _still_broken,
)
from drydock.prompt_assembly import (
    PromptAssembly,
    PromptPart,
    fenced_body,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt
from drydock.proof_integrity import analyze_proof
from drydock.source_roles import declared_build_assets, parse_source_roles

PROMPT_NAME = "diagnose_ac_repair"
KIND_MALFORMED = "malformed"
KIND_DISPUTED = "disputed"

#: A source file larger than this is listed by name rather than inlined.
_SOURCE_INLINE_LIMIT = 400_000

RunnerFn = Callable[..., object]
TextCallback = Callable[[str], None]

_BODY_RE = re.compile(
    r"^=== AC (?P<id>[^=\n]+?) ===[ \t]*$\n(?P<body>.*?)^=== END AC (?P=id) ===[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class RepairCandidate:
    """One criterion selected for AC repair."""

    check: ProgrammaticAcceptance
    kind: str
    fault: str


@dataclass(frozen=True)
class AcRepairItem:
    filename: str
    check_id: str
    #: ``repaired`` | ``unfixable``
    status: str
    detail: str = ""

    @property
    def rendered(self) -> str:
        suffix = f" — {self.detail}" if self.detail else ""
        return f"{self.filename} [{self.check_id}]: {self.status}{suffix}"


@dataclass(frozen=True)
class AcRepairResult:
    items: tuple[AcRepairItem, ...] = ()
    changed_files: tuple[str, ...] = ()
    error: str | None = None

    @property
    def repaired(self) -> tuple[AcRepairItem, ...]:
        return tuple(item for item in self.items if item.status == "repaired")


def _current_checks(target_dir: Path) -> tuple[ProgrammaticAcceptance, ...]:
    manifest = target_dir / "MANIFEST.md"
    if not manifest.is_file():
        return ()
    try:
        plan = parse_build_plan(manifest)
    except Exception:  # noqa: BLE001 - an unparseable Manifest has nothing to repair
        return ()
    return all_programmatic_acceptance(plan, target_dir / "blueprint", defects=[])


def select_repairs(target_dir: Path) -> tuple[RepairCandidate, ...]:
    """Return the criteria AC repair should rewrite, in declaration order.

    ``malformed``: the recorded status for the current code is ERROR ``malformed``. ``disputed``:
    the last build pass that ran it settled DISPUTED and the current code is still non-binding.
    A terminal status (ALWAYS_PASSES, UNFIXABLE, FLAKY) is never selected.
    """
    statuses = read_acceptance_status(target_dir / "evidence")
    history = acceptance_history(target_dir)
    selected: list[RepairCandidate] = []
    for check in _current_checks(target_dir):
        entry = current_status(statuses, check)
        if entry is not None and entry.status in TERMINAL_STATUSES:
            continue
        if (
            entry is not None
            and entry.status == STATUS_ERROR
            and entry.error_code == ERROR_MALFORMED
        ):
            selected.append(
                RepairCandidate(check, KIND_MALFORMED, entry.detail or "dies in its own frame")
            )
            continue
        past = history.get(check.check_id)
        if past is not None and past.last_outcome == OUTCOME_DISPUTED and not check.binding:
            expected = ", ".join(repr(value) for value in check.retyped_expectations)
            selected.append(
                RepairCandidate(
                    check,
                    KIND_DISPUTED,
                    f"missed an expectation re-typed rather than derived: {expected}",
                )
            )
    return tuple(selected)


def disputed_criteria(target_dir: Path) -> tuple[str, ...]:
    """Return ids of criteria that are DISPUTED and still repairable — the loop's open work."""
    return tuple(
        candidate.check.check_id
        for candidate in select_repairs(target_dir)
        if candidate.kind == KIND_DISPUTED
    )


def _block_body(text: str, check_id: str) -> str:
    for match in _BODY_RE.finditer(text):
        if match.group("id").strip() == check_id:
            return match.group("body")
    return ""


def _source_parts(blueprint_dir: Path) -> list[PromptPart]:
    sources = blueprint_dir / "sources"
    if not sources.is_dir():
        return []
    parts: list[PromptPart] = []
    for path in sorted(item for item in sources.rglob("*") if item.is_file()):
        rel = path.relative_to(blueprint_dir).as_posix()
        text = None
        if path.stat().st_size <= _SOURCE_INLINE_LIMIT:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = None
        if text is None:
            parts.append(part(rel, f"### {rel}\n\n(listed only: too large or not text)\n\n"))
            continue
        numbered = "\n".join(
            f"{index:>5}| {line}" for index, line in enumerate(text.splitlines(), start=1)
        )
        parts.append(part(rel, f"### {rel}\n\n{fenced_body(numbered, 'text')}\n\n", kind="source"))
    return parts


def assemble(
    body: str, candidates: tuple[RepairCandidate, ...], blueprint_dir: Path
) -> PromptAssembly:
    """Build the one repair prompt. Deterministic: specification and sources, never the product."""
    parts: list[PromptPart] = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Repair job",
            [
                "## Repair job",
                "",
                f"- DATE: {date.today().isoformat()}",
                f"- CRITERIA: {len(candidates)}",
                "",
            ],
            kind="job",
        ),
    ]
    from drydock.paths import get_language_dir
    from drydock.technology_stack import declared_language

    language = declared_language(blueprint_dir.parent)
    if language:
        source = get_language_dir(language) / f"{language}_compact.md"
        parts.append(part(source.name, source.read_text(encoding="utf-8")))
    texts: dict[str, str] = {}
    for candidate in candidates:
        source = candidate.check.source
        text = texts.setdefault(source, (blueprint_dir / source).read_text(encoding="utf-8"))
        block = _block_body(text, candidate.check.check_id)
        parts.append(
            part(
                f"{source} :: {candidate.check.check_id}",
                f'<acblock file="{source}" check_id="{candidate.check.check_id}" '
                f'kind="{candidate.kind}">\n'
                f"Fault: {candidate.fault}\n\n"
                f"{fenced_body(block.strip(chr(10)), 'python')}\n"
                "</acblock>\n\n",
                kind="defect",
            )
        )
    parts.append(section_heading_part("# Specifications"))
    for source, text in texts.items():
        parts.append(part(source, f"### {source}\n\n{fenced_body(text, 'markdown')}\n\n"))
    sources = _source_parts(blueprint_dir)
    if sources:
        parts.append(section_heading_part("# Imported Sources"))
        parts.extend(sources)
    parts.append(section_heading_part("# Agent Task"))
    parts.append(part("Prompt body", body + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(parts))


def _staged_assets(target_dir: Path, blueprint_dir: Path):
    analysis = target_dir / "ANALYSIS.md"
    if not analysis.is_file():
        return ()
    return declared_build_assets(
        blueprint_dir, parse_source_roles(analysis.read_text(encoding="utf-8"))
    )


def verify_repaired(
    check: ProgrammaticAcceptance, *, target_dir: Path, blueprint_dir: Path, staged=()
) -> str | None:
    """Return why a repaired criterion is not kept, or ``None`` when it records VALID.

    The static gates run first because they are free. Execution is the empty-directory baseline:
    a criterion that passes with no product measures nothing. An environment error is retried
    once, since it says nothing about the criterion.
    """
    if (reason := _still_broken(check, source_root=blueprint_dir)) is not None:
        return f"still cannot run: {reason}"
    if (reason := citation_defect(check, blueprint_dir)) is not None:
        return reason
    if not check.binding:
        expected = ", ".join(repr(value) for value in check.retyped_expectations)
        return f"still re-types its expectation: {expected}"
    if not (integrity := analyze_proof(check.code)).ok:
        return "cannot fail: " + "; ".join(integrity.reasons)
    for _ in range(2):
        (observation,) = observe_empty_baseline(
            (check,), target_dir=target_dir, blueprint_dir=blueprint_dir, staged=staged
        ) or (None,)
        if observation is None:
            return "the empty-directory baseline produced no observation"
        status = classify_baseline(observation, check, empty=observation)
        if status is None:
            return "the empty-directory baseline could not run"
        if status.status == STATUS_VALID:
            return None
        if status.error_code != ERROR_ENVIRONMENT:
            break
    return f"records {status.status} {status.error_code} on the empty-directory baseline".strip()


def repair(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    candidates: tuple[RepairCandidate, ...] | None = None,
    accept: Callable[[str], bool] | None = None,
) -> AcRepairResult:
    """Repair every selected criterion in one call; keep only repairs that record VALID.

    ``accept`` is asked about each verified repair before it is kept. A declined repair leaves the
    criterion as it was and records nothing, so it stays selected for the next pass.
    """
    blueprint_dir = target_dir / "blueprint"
    selected = select_repairs(target_dir) if candidates is None else candidates
    if not selected:
        return AcRepairResult()

    def emit(message: str) -> None:
        if on_text is not None:
            on_text(message)

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    assembly = assemble(prompt.body, selected, blueprint_dir)
    emit(
        f"ac repair: {len(selected)} "
        f"{'criterion' if len(selected) == 1 else 'criteria'} · 1 of 1 attempt"
    )
    result = run(
        assembly.rendered_text,
        blueprint_dir,
        llm=llm_provider,
        model=model or prompt.model,
        command_name="diagnose ac-repair",
        parameters={"target": target, "criteria": len(selected)},
        target=target,
        prompt_assembly=assembly,
    )
    if not getattr(result, "ok", False):
        return AcRepairResult(error=failure_detail(result))
    text = str(getattr(result, "text", ""))
    responses = _response_blocks(text)
    impossible = {
        tuple(part.strip() for part in match.group("key").split(" :: ", 1)): match.group("why")
        for match in _IMPOSSIBLE_RE.finditer(text)
    }
    staged = _staged_assets(target_dir, blueprint_dir)
    evidence_dir = target_dir / "evidence"
    items: list[AcRepairItem] = []
    changed: list[str] = []

    by_file: dict[str, list[RepairCandidate]] = {}
    for candidate in selected:
        by_file.setdefault(candidate.check.source, []).append(candidate)

    for filename, file_candidates in by_file.items():
        path = blueprint_dir / filename
        original = path.read_text(encoding="utf-8")
        kept_text = original
        for candidate in file_candidates:
            check = candidate.check
            key = (filename, check.check_id)

            def unfixable(code: str, detail: str, check=check) -> None:
                record_status(evidence_dir, check, STATUS_UNFIXABLE, code, detail)
                items.append(AcRepairItem(filename, check.check_id, "unfixable", detail))
                emit(f"  ✗  {filename} [{check.check_id}]: unfixable — {detail}")

            if key in impossible:
                unfixable(ERROR_REPAIR_IMPOSSIBLE, impossible[key].strip())
                continue
            body = responses.get(key)
            if body is None:
                unfixable(ERROR_REPAIR_REJECTED, "no repaired block returned")
                continue
            spans = _blocks(kept_text)
            if check.check_id not in spans:
                unfixable(ERROR_REPAIR_REJECTED, "original block not found in the specification")
                continue
            start, end, _ = spans[check.check_id]
            trial = kept_text[:start] + _plain_block(check.check_id, body) + kept_text[end:]
            # Validated in memory: the file parse is cached by mtime and size, so reading a file
            # rewritten within one timestamp tick could return the criterion it replaced.
            try:
                repaired = next(
                    (
                        item
                        for item in parse_programmatic_acceptance_text(trial, source=filename)
                        if item.check_id == check.check_id
                    ),
                    None,
                )
            except ValueError as exc:
                repaired, reason = None, f"left the specification unparseable: {exc}"
            else:
                if repaired is not None and repaired.cite:
                    repaired = replace(
                        repaired, cited_text=resolve_citation(repaired.cite, blueprint_dir)
                    )
                reason = (
                    "the repaired block lost its id"
                    if repaired is None
                    else verify_repaired(
                        repaired, target_dir=target_dir, blueprint_dir=blueprint_dir, staged=staged
                    )
                )
            if reason is not None or repaired is None:
                unfixable(ERROR_REPAIR_REJECTED, reason or "rejected")
                continue
            if accept is not None and not accept(
                f"AC repair: {filename} [{check.check_id}] ({candidate.kind})\n"
                f"{_plain_block(check.check_id, body).rstrip()}\n"
                "Apply this repair? [y/N] "
            ):
                items.append(AcRepairItem(filename, check.check_id, "declined", candidate.kind))
                emit(f"  ·  {filename} [{check.check_id}]: declined")
                continue
            kept_text = trial
            record_status(evidence_dir, repaired, STATUS_VALID, ERROR_REPAIRED, candidate.kind)
            items.append(AcRepairItem(filename, check.check_id, "repaired", candidate.kind))
            emit(f"  ✓  {filename} [{check.check_id}]: repaired ({candidate.kind})")
        if kept_text != original:
            path.write_text(kept_text, encoding="utf-8", newline="\n")
            changed.append(filename)
    return AcRepairResult(items=tuple(items), changed_files=tuple(changed))
