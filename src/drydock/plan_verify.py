"""``drydock plan verify`` — decide whether the planned Blueprint is fit to build.

The failure this exists for. A criterion that reads an unimported name is not a failing test; it
is a test that cannot run. It raises ``NameError`` in its own frame, settles UNVERIFIED, and the
build spends its whole repair budget on a story whose code was already correct — then stops on a
score that never moved. Every part of that is detectable before the first build call, from the
text of the Blueprint alone, and Drydock already detects it: ``drydock status`` printed both
defects forty minutes before the run that motivated this module died on one of them. Nothing
consumed the detection.

So this command consumes it. It is read-only and deterministic — no model, no build directory, no
network — and its exit status is the whole verdict: zero when the Blueprint is fit to build,
non-zero when a defect will cost build calls to discover. The intended use is a two-line workflow
in which the repair call is only paid for when it is needed::

    drydock plan verify <Target> || drydock plan repair <Target>

What it refuses to judge. Whether a criterion is *correct* — whether its expected value matches
what the product should do — is not decidable from the text, and the analyzers that tried to
decide it were retracted after failing specifications that had validated for weeks. A wrong-but-
runnable criterion fails at build time on the evidence of its own traceback, which is a sounder
authority than a prediction. This command judges only facts about the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from drydock.acceptance import (
    blueprint_read_defects,
    captures_without_reporting,
    citation_defect,
    dynamic_selector_advisory,
    imported_modules,
    parse_programmatic_acceptance,
    regex_defects,
    selection_probe_reason,
    staged_regex_defects,
    syntax_defect,
    unresolved_globals,
)
from drydock.database_contract import (
    database_contract_defects,
    declared_owners,
    legal_owner,
    sqlite_schema_tables,
    table_coverage_defects,
)
from drydock.errors import SpecificationError
from drydock.rigging_contract import import_defects
from drydock.story_guidance import load_guidance

#: Advisories of one kind printed in full before they are rolled up into a count.
_WARNING_DETAIL_LIMIT = 5

#: Files under ``blueprint/`` that no Blueprint author wrote and no repair may touch.
_GENERATED_FILES = frozenset({"MANIFEST.md", "TOPOLOGY.md", "SCORECARD.md"})


@dataclass(frozen=True)
class Defect:
    """One repairable fault, addressed to the exact criterion that carries it."""

    #: Blueprint file name, relative to ``blueprint/``.
    filename: str
    #: Acceptance criterion id, or empty when the fault is the file's own parse.
    check_id: str
    #: Machine-stable class, used to route the repair and to assert on in tests.
    kind: str
    #: One sentence naming the fault and what would fix it.
    detail: str

    @property
    def rendered(self) -> str:
        where = f"{self.filename} [{self.check_id}]" if self.check_id else self.filename
        return f"{where}: {self.detail}"


@dataclass(frozen=True)
class VerifyResult:
    """What verification found. ``ok`` is the exit status and nothing else decides it."""

    target: str
    blueprint_dir: Path
    defects: tuple[Defect, ...] = ()
    warnings: tuple[str, ...] = ()
    checked_files: int = 0
    checked_criteria: int = 0
    guidance_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.defects

    def exit_code(self) -> int:
        return 0 if self.ok else 1

    @property
    def summary(self) -> str:
        if self.ok:
            return (
                f"{self.checked_criteria} acceptance "
                f"{'criterion' if self.checked_criteria == 1 else 'criteria'} in "
                f"{self.checked_files} {'file' if self.checked_files == 1 else 'files'}: "
                "every one can run"
            )
        criteria = sum(1 for defect in self.defects if not defect.kind.startswith("database-"))
        persistence = len(self.defects) - criteria
        parts = []
        if criteria:
            parts.append(
                f"{criteria} {'criterion' if criteria == 1 else 'criteria'} cannot run as written"
            )
        if persistence:
            parts.append(
                f"{persistence} persistence "
                f"{'defect' if persistence == 1 else 'defects'}: Build cannot read DATABASE.md"
            )
        return "; ".join(parts)


def _blueprint_files(blueprint_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(blueprint_dir.glob("*.md"))
        if path.name not in _GENERATED_FILES and "_compact." not in path.name
    ]


def persistence_defects(blueprint_dir: Path) -> list[Defect]:
    """Return every reason Build cannot generate the persistence layer from ``DATABASE.md``.

    Build generates the persistence package from this declaration, so a declaration it cannot
    parse is a plan that cannot be built — the same verdict as a criterion that cannot run, and
    decidable from the file alone.
    """
    path = blueprint_dir / "DATABASE.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        declares_storage = bool(sqlite_schema_tables(text))
    except SpecificationError:
        declares_storage = True  # a schema that does not parse is itself a declaration defect
    if not declares_storage:
        # The rule Build applies: a declaration with no tables generates no persistence package,
        # so there is no contract for Build to read.
        return []
    defects = [
        Defect("DATABASE.md", "", "database-contract", reason.removeprefix("DATABASE.md: "))
        for reason in database_contract_defects(text)
    ]
    blueprints = {candidate.name for candidate in _blueprint_files(blueprint_dir)}
    defects.extend(
        Defect(
            "DATABASE.md",
            "",
            "database-owner-unknown",
            f"`| Owner |` names {owner!r}, which is not a Feature in this plan; a pattern no "
            "single Feature owns names `DATABASE.md`",
        )
        for owner in sorted(
            owner for owner in set(declared_owners(text)) if not legal_owner(owner, blueprints)
        )
    )
    try:
        uncited, undeclared = table_coverage_defects(text)
    except SpecificationError:
        return defects  # the unreadable contract is already reported above
    defects.extend(
        Defect(
            "DATABASE.md",
            "",
            "database-table-uncited",
            f"table `{table}` is declared in `## Schema` but no access pattern reaches it",
        )
        for table in uncited
    )
    defects.extend(
        Defect(
            "DATABASE.md",
            "",
            "database-table-undeclared",
            f"{identifier}: `{operation}` names a table `## Schema` does not declare",
        )
        for identifier, operation in undeclared
    )
    return defects


def _foundation_defects(target_dir: Path) -> list[Defect]:
    """Refuse a plan whose Technology Stack cannot yield one foundation per kind.

    Checked at plan, not at analyze. Analyze proposes ``TECHNOLOGY_STACK.md`` — the questionnaire —
    and the Commander answers it; an unanswered row is a normal intermediate state there. By plan
    it is not: the foundation's package name, entry point, and fixture come from the selected
    Rigging file, and without one every criterion invents its own. Drydock does not pick a web
    server on the operator's behalf.
    """
    from drydock import technology_stack

    if not technology_stack.path_for(target_dir).is_file():
        # No stack file is a different, earlier problem, reported by the commands that need one.
        return []
    return [
        Defect(technology_stack.FILENAME, "", "foundation", reason)
        for reason in technology_stack.foundation_defects(technology_stack.load(target_dir))
    ]


def _selected_rigging(target_dir: Path) -> list[str]:
    """The Rigging files the Target's Technology Stack names, or ``[]`` when it has no stack."""
    from drydock import technology_stack

    if not technology_stack.path_for(target_dir).is_file():
        return []
    return technology_stack.stack_files(target_dir)


def verify(target: str, target_dir: Path) -> VerifyResult:
    """Judge every acceptance criterion in the Target's Blueprint. Never writes."""
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    selected = _selected_rigging(target_dir)
    defects: list[Defect] = []
    warnings: list[str] = []
    checked_criteria = 0
    files = _blueprint_files(blueprint_dir)

    for path in files:
        try:
            checks = parse_programmatic_acceptance(path)
        except ValueError as exc:
            # The container is malformed, so no criterion in this file is readable. Reported
            # against the file rather than a criterion, because there is no criterion to name.
            defects.append(Defect(path.name, "", "bad-container", str(exc)))
            continue
        for check in checks:
            checked_criteria += 1
            if captures_without_reporting(check.code):
                # Advisory for the same reason as a re-typed expectation: the criterion runs and
                # judges correctly, so refusing the Blueprint over it would be wrong. What it
                # costs is measurement — a suite of hundreds of cases reporting its progress as
                # one bit, which the build's repair loop reads as a stall. Raised before the
                # defect checks short-circuit, because a criterion can carry both faults and a
                # repair pass should be told about both in the one call it is paid for.
                warnings.append(
                    f"{path.name} [{check.check_id}]: captures a program's output and prints "
                    "none of it; print its pass/fail counts before asserting so repair can see "
                    "progress"
                )
            # Order matters: a snippet that does not compile has no meaningful name analysis, so
            # reporting both would name the same fault twice and give repair two things to fix.
            if (reason := syntax_defect(check.code)) is not None:
                defects.append(Defect(path.name, check.check_id, "syntax", reason))
                continue
            if reasons := blueprint_read_defects(check.code, blueprint_dir):
                # Raised before the content checks: a criterion reading its own specification
                # cannot run at all, so its regexes and expectations are not yet worth judging.
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "blueprint-read",
                        "; ".join(reasons),
                    )
                )
                continue
            if selected and (reasons := import_defects(imported_modules(check.code), selected)):
                # Raised alongside the Blueprint read for the same reason: a criterion importing
                # a package no selected foundation publishes raises ModuleNotFoundError in its
                # own frame on every run, so no implementation turns it green. Judged only when
                # a Technology Stack exists — without one there is nothing to judge against.
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "unknown-package",
                        "; ".join(reasons),
                    )
                )
                continue
            if reasons := regex_defects(check.code):
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "invalid-regex",
                        "; ".join(reasons),
                    )
                )
                continue
            if reasons := staged_regex_defects(check.code, blueprint_dir):
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "invalid-staged-regex",
                        "; ".join(reasons),
                    )
                )
                continue
            if (probe := selection_probe_reason(check, blueprint_dir=blueprint_dir)) is not None:
                kind, reason = probe
                defects.append(Defect(path.name, check.check_id, kind, reason))
                continue
            if (reason := citation_defect(check, blueprint_dir)) is not None:
                # A citation exists to make a literal derived. One that names nothing, or names
                # lines that do not state the expectation, would launder a re-typed value.
                defects.append(Defect(path.name, check.check_id, "bad-citation", reason))
                continue
            if names := unresolved_globals(check.code):
                rendered = ", ".join(f"`{name}`" for name in sorted(names))
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "unresolved-global",
                        f"reads undefined global name(s): {rendered}; import or assign each "
                        "name inside this acceptance criterion",
                    )
                )
                continue
            if (
                advisory := dynamic_selector_advisory(check, blueprint_dir=blueprint_dir)
            ) is not None:
                # Advisory, not gating: the selector is real but not statically recoverable, so
                # no probe can be constructed. build_run's zero-case handling still guards it.
                warnings.append(f"{path.name} [{check.check_id}]: {advisory}")
            for literal in check.retyped_expectations:
                # Advisory, deliberately not a defect. A re-typed expectation is an authoring
                # smell with a real false-positive rate, and gating on it would refuse correct
                # specifications. Repair is told about it and may act; verification does not
                # fail on it.
                warnings.append(
                    f"{path.name} [{check.check_id}]: expects {literal!r}, a value re-typed "
                    "rather than derived from the input or read back from the system"
                )

    defects.extend(persistence_defects(blueprint_dir))
    defects.extend(_foundation_defects(target_dir))
    guidance = load_guidance(target_dir)
    return VerifyResult(
        target=target,
        blueprint_dir=blueprint_dir,
        defects=tuple(defects),
        warnings=tuple(warnings),
        checked_files=len(files),
        checked_criteria=checked_criteria,
        guidance_ids=guidance.ids,
    )


def render(result: VerifyResult) -> str:
    """Render the verdict for a terminal. One line per defect, path first so it is clickable."""
    lines = [f"plan verify: {result.target}", f"  {result.summary}"]
    for defect in result.defects:
        lines.append(f"  ✗  {defect.rendered}")
    # An advisory that holds for most of a plan is one finding about the plan, not sixty
    # findings. Printed one per line it buries the defects, which are the part that gates.
    grouped: dict[str, list[str]] = {}
    for warning in result.warnings:
        where, _, detail = warning.partition(": ")
        grouped.setdefault(detail or warning, []).append(where)
    for detail, where in grouped.items():
        if len(where) <= _WARNING_DETAIL_LIMIT:
            lines += [f"  ⚠  {place}: {detail}" for place in where]
            continue
        lines.append(f"  ⚠  {len(where)} criteria: {detail}")
        lines.append(
            f"       {', '.join(where[:_WARNING_DETAIL_LIMIT])}, and {len(where) - _WARNING_DETAIL_LIMIT} more"
        )
    if any(not defect.kind.startswith("database-") for defect in result.defects):
        lines.append(f"  Run: drydock plan repair {result.target}")
    if any(defect.kind.startswith("database-") for defect in result.defects):
        # ``plan repair`` rewrites acceptance criteria only; the declaration is Plan's to repair.
        lines.append(f"  Run: drydock plan {result.target}")
    return "\n".join(lines)
