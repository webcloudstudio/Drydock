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

One exception is a fact about two files: a criterion that asserts an exit status for the exact
command a staged harness line expects a different status for. The harness is the user's own test,
so the criterion cannot pass it. Only calls that pass a staged file are compared
(``harness_exits``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
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
    uncalled_function_defect,
    unresolved_globals,
)
from drydock.acceptance_oracle import decimal_expectation_defects
from drydock.acceptance_store import store_setup_defects
from drydock.database_contract import (
    database_contract_defects,
    declared_owners,
    legal_owner,
    parse_database_contract,
    sqlite_schema_tables,
    table_coverage_defects,
)
from drydock.errors import SpecificationError
from drydock.harness_exits import (
    contradictions,
    go_cli_defect,
    load_harness,
    unchecked_calls,
    unloaded_staged_values,
)
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
        uncovered = sum(1 for defect in self.defects if defect.kind == CRITERIA_MISSING)
        persistence = sum(1 for defect in self.defects if defect.kind.startswith("database-"))
        untested = sum(1 for defect in self.defects if defect.kind == OPERATION_UNTESTED)
        criteria = len(self.defects) - persistence - uncovered - untested
        parts = []
        if criteria:
            parts.append(
                f"{criteria} {'criterion' if criteria == 1 else 'criteria'} cannot run as written"
            )
        if uncovered:
            parts.append(
                f"{uncovered} story {'Blueprint has' if uncovered == 1 else 'Blueprints have'} "
                "no acceptance criteria"
            )
        if untested:
            parts.append(
                f"{untested} repository {'operation' if untested == 1 else 'operations'} "
                "no DATABASE.md criterion calls"
            )
        if persistence:
            parts.append(
                f"{persistence} persistence "
                f"{'defect' if persistence == 1 else 'defects'}: Build cannot read DATABASE.md"
            )
        return "; ".join(parts)


#: Defect kind for a story whose implemented Blueprints carry no Programmatic Acceptance.
CRITERIA_MISSING = "criteria-missing"


#: Defect kind for a declared repository operation no ``DATABASE.md`` criterion calls.
OPERATION_UNTESTED = "operation-untested"


#: Defect kind for a criterion calling a repository operation ``DATABASE.md`` does not declare.
OPERATION_UNDECLARED = "operation-undeclared"


#: Defect kind for a criterion importing ``persistence`` on a story built before DATABASE.
PERSISTENCE_ORDER = "persistence-order"

#: Defect kind for a criterion whose assertions sit in a function nothing calls.
UNCALLED_FUNCTION = "uncalled-function"


def untested_operations(database_text: str, codes: Iterable[str]) -> tuple[str, ...]:
    """Each declared ``<table>.<verb>`` that no ``DATABASE.md`` criterion calls, in order.

    The generated package is the product ``DATABASE.md``'s criteria measure, so an operation none
    of them calls ships untested. Python calls it ``db.<table>.<verb>(...)`` and Go
    ``db.<Table>.<Verb>(ctx, ...)``; either spelling counts. A contract that does not parse is
    reported by :func:`persistence_defects`.
    """
    from drydock.database_emit_go import _export

    try:
        contract = parse_database_contract(database_text)
    except SpecificationError:
        return ()
    text = "\n".join(codes)
    untested: list[str] = []
    for pattern in contract.patterns:
        for operation in pattern.operations:
            table, verb = operation.split(".", 1)
            calls = (rf"\.{table}\.{verb}\s*\(", rf"\.{_export(table)}\.{_export(verb)}\s*\(")
            if operation not in untested and not any(re.search(call, text) for call in calls):
                untested.append(operation)
    return tuple(untested)


def untested_operation_reason(operation: str) -> str:
    """One sentence naming an operation no criterion calls and the criterion it needs."""
    table, verb = operation.split(".", 1)
    return (
        f"repository operation `{operation}` is declared and no criterion calls it; give it a "
        f"criterion that calls `db.{table}.{verb}(...)` inside `with db_session() as db:` and "
        "asserts the declared Output"
    )


#: ``.<table>.<verb>(`` — a repository call in either spelling, matched against declared tables.
_REPOSITORY_CALL_RE = re.compile(r"\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(")


def undeclared_operation_calls(database_text: str, code: str) -> tuple[str, ...]:
    """Each reason a criterion calls a ``<table>.<verb>`` that ``DATABASE.md`` does not declare.

    The generated package grants exactly the declared operations and raises
    ``UnknownOperation`` for any other name, so such a call fails on every run whatever the
    implementation does (FxRates ``20261024.145257``: ``db.rates.get`` with no ``get`` declared).
    Only receivers naming a declared table are judged, in the Python or Go spelling. A contract
    that does not parse is reported by :func:`persistence_defects`.
    """
    from drydock.database_emit_go import _export

    try:
        contract = parse_database_contract(database_text)
    except SpecificationError:
        return ()
    granted: dict[str, set[str]] = {}
    spelled: dict[tuple[str, str], str] = {}
    for pattern in contract.patterns:
        for operation in pattern.operations:
            table, verb = operation.split(".", 1)
            granted.setdefault(table, set()).add(verb)
            spelled[(table, verb)] = spelled[(_export(table), _export(verb))] = operation
    tables = {name: table for table in granted for name in (table, _export(table))}
    reasons: list[str] = []
    for receiver, verb in _REPOSITORY_CALL_RE.findall(code):
        table = tables.get(receiver)
        if table is None or (receiver, verb) in spelled:
            continue
        reason = (
            f"calls `{receiver}.{verb}(...)`, which DATABASE.md does not declare; {table} "
            f"declares {', '.join(sorted(granted[table]))} — call a declared operation or "
            "declare the access pattern in DATABASE.md"
        )
        if reason not in reasons:
            reasons.append(reason)
    return tuple(reasons)


def stories_without_criteria(
    stories: Iterable[tuple[str, tuple[str, ...]]], criteria: Mapping[str, int | None]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return each ``(story id, implements)`` whose implemented Blueprints declare no criterion.

    Every story closes on its own evidence, so a story with nothing to run can only close on the
    builder's word. ``criteria`` maps a Blueprint name to its criterion count, or ``None`` when
    the file does not parse; that is reported by its own check, so a story citing one is not
    reported here as well. A name ``criteria`` omits is not a file in ``blueprint/`` (a Rigging
    file, a typo) and carries none, and a story naming no Blueprint carries none.
    """
    found = []
    for story_id, implements in stories:
        names = tuple(name for name in implements if name)
        if all(criteria.get(name, 0) == 0 for name in names):
            found.append((story_id, names))
    return tuple(found)


def criteria_missing_reason(story_id: str, filename: str, *, absent: bool = False) -> str:
    """One sentence naming a story with no criteria and what its Blueprint must carry."""
    if not filename:
        return (
            f"story `{story_id}` implements no Blueprint, so it has no criterion to close on; "
            "every story implements a Blueprint carrying at least one"
        )
    if absent:
        return (
            f"story `{story_id}` implements {filename}, which is not a file in blueprint/, so it "
            "has no criterion to close on; every story implements a Blueprint carrying at least one"
        )
    reason = (
        f"story `{story_id}` implements {filename}, which declares no Programmatic Acceptance "
        "criterion; every story carries at least one"
    )
    if filename == "DATABASE.md":
        reason += (
            ", and DATABASE.md's criteria exercise each declared repository operation through "
            "`with db_session() as db:` from `persistence.testing`"
        )
    return reason


def criteria_missing(
    stories: Iterable[tuple[str, tuple[str, ...]]], criteria: Mapping[str, int | None]
) -> tuple[tuple[str, str, str], ...]:
    """Each ``(story id, file, reason)`` for a story with no criterion.

    A story naming no Blueprint cites the Manifest.
    """
    return tuple(
        (
            story_id,
            name or "MANIFEST.md",
            criteria_missing_reason(story_id, name, absent=name not in criteria),
        )
        for story_id, implements in stories_without_criteria(stories, criteria)
        for name in implements or ("",)
    )


def _story_criteria_defects(target_dir: Path, criteria: Mapping[str, int | None]) -> list[Defect]:
    """Refuse a Manifest story whose implemented Blueprints carry no Programmatic Acceptance."""
    from drydock.build_plan import parse_build_plan

    manifest = target_dir / "MANIFEST.md"
    if not manifest.is_file():
        return []
    try:
        plan = parse_build_plan(manifest)
    except SpecificationError:
        # An unreadable Manifest is reported by every command that executes it.
        return []
    stories = tuple(
        (block.block_id, implements_of(block))
        for block in plan.blocks
        if block.block_type == "story"
    )
    # ``criteria`` counts the top-level Blueprints; a story may implement one beneath them, such
    # as a Refit ticket under ``changes/``.
    criteria = dict(criteria)
    blueprint_dir = target_dir / "blueprint"
    for _, implements in stories:
        for name in implements:
            path = blueprint_dir / name
            if name and name not in criteria and path.is_file():
                try:
                    criteria[name] = len(parse_programmatic_acceptance(path))
                except ValueError:
                    criteria[name] = None
    return [
        Defect(filename, "", CRITERIA_MISSING, reason)
        for _, filename, reason in criteria_missing(stories, criteria)
    ]


def _persistence_order_defects(target_dir: Path) -> list[Defect]:
    """Refuse a criterion that imports ``persistence`` on a story built before DATABASE.

    Drydock generates ``persistence/`` at the step of the story implementing ``DATABASE.md``, so a
    criterion an earlier story owns can pass only if that story's builder writes the package
    Rigging forbids it to write. A story in the DATABASE step itself is not earlier: the package
    is generated before that step runs.
    """
    from drydock.build_plan import parse_build_plan

    manifest = target_dir / "MANIFEST.md"
    if not manifest.is_file():
        return []
    try:
        plan = parse_build_plan(manifest)
    except SpecificationError:
        return []
    stories = [block for block in plan.blocks if block.block_type == "story"]
    database = min(
        (
            story
            for story in stories
            if "DATABASE.md" in implements_of(story) and story.computed_block is not None
        ),
        key=lambda story: story.computed_block or 0,
        default=None,
    )
    if database is None or database.computed_block is None:
        return []
    blueprint_dir = target_dir / "blueprint"
    defects: list[Defect] = []
    for story in stories:
        block = story.computed_block
        if block is None or block >= database.computed_block:
            continue
        for name in implements_of(story):
            path = blueprint_dir / name
            if name == "DATABASE.md" or not path.is_file():
                continue
            try:
                checks = parse_programmatic_acceptance(path)
            except ValueError:
                continue  # reported as bad-container
            defects.extend(
                Defect(
                    name,
                    check.check_id,
                    PERSISTENCE_ORDER,
                    f"imports `persistence`, which Drydock generates from DATABASE.md at block "
                    f"{database.computed_block} (story `{database.block_id}`), after story "
                    f"`{story.block_id}` builds at block {block}; assert only what that story "
                    "delivers and leave persistence to DATABASE.md's criteria",
                )
                for check in checks
                if any(
                    module.split(".")[0] == "persistence"
                    for _, module, _ in imported_modules(check.code)
                )
            )
    return defects


def implements_of(block: object) -> tuple[str, ...]:
    """The Blueprint names a Manifest node implements, whether stored as a string or a tuple."""
    value = getattr(block, "fields", {}).get("implements", ())
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(name) for name in value or () if name)


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
    harness = load_harness(blueprint_dir / "sources")
    database = blueprint_dir / "DATABASE.md"
    database_text = database.read_text(encoding="utf-8") if database.is_file() else ""

    criteria: dict[str, int | None] = {}
    for path in files:
        try:
            checks = parse_programmatic_acceptance(path)
        except ValueError as exc:
            # The container is malformed, so no criterion in this file is readable. Reported
            # against the file rather than a criterion, because there is no criterion to name.
            defects.append(Defect(path.name, "", "bad-container", str(exc)))
            criteria[path.name] = None
            continue
        criteria[path.name] = len(checks)
        for check in checks:
            checked_criteria += 1
            for reason in decimal_expectation_defects(check):
                defects.append(Defect(path.name, check.check_id, "decimal-oracle", reason))
            for reason in store_setup_defects(check.code):
                defects.append(Defect(path.name, check.check_id, "acceptance-store", reason))
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
            if (reason := uncalled_function_defect(check.code)) is not None:
                defects.append(Defect(path.name, check.check_id, UNCALLED_FUNCTION, reason))
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
            if database_text and (reasons := undeclared_operation_calls(database_text, check.code)):
                defects.append(
                    Defect(path.name, check.check_id, OPERATION_UNDECLARED, "; ".join(reasons))
                )
                continue
            if defect := go_cli_defect(
                check.code, go=any(Path(name).name == "go.md" for name in selected)
            ):
                kind, reason = defect
                defects.append(Defect(path.name, check.check_id, kind, reason))
                continue
            if found := contradictions(check.code, harness):
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "harness-exit",
                        "; ".join(
                            f"asserts `{' '.join(call.argv)}` exits {call.exit_code}, but the "
                            f"staged harness sources/{line.source}:{line.line} expects "
                            f"{line.exit_code}; assert {line.exit_code} and correct any later "
                            "assertion that followed from the wrong exit"
                            for call, line in found
                        ),
                    )
                )
                continue
            if lines := unchecked_calls(check.code):
                # A setup call that fails silently leaves the criterion testing state that does
                # not exist, and the product is charged for it (LayersTesting 20261021.195808).
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "unchecked-call",
                        "calls `cli_runner` at line(s) "
                        + ", ".join(str(line) for line in lines)
                        + " without asserting its exit status; bind it as "
                        "`code, out, err = cli_runner(...)` and assert `code` before the next call",
                    )
                )
                continue
            if found_values := unloaded_staged_values(check.code, harness):
                defects.append(
                    Defect(
                        path.name,
                        check.check_id,
                        "staged-value",
                        "; ".join(
                            f"uses `{value}` from staged sources/{source} without loading that "
                            "file; create the state in this criterion under an identifier no "
                            "staged file holds, or load the file first"
                            for value, source in found_values
                        ),
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

    defects.extend(_story_criteria_defects(target_dir, criteria))
    defects.extend(_persistence_order_defects(target_dir))
    defects.extend(persistence_defects(blueprint_dir))
    if criteria.get("DATABASE.md"):
        # A DATABASE.md with no criterion is reported once, as criteria-missing.
        codes = [check.code for check in parse_programmatic_acceptance(database)]
        defects.extend(
            Defect("DATABASE.md", "", OPERATION_UNTESTED, untested_operation_reason(operation))
            for operation in untested_operations(database.read_text(encoding="utf-8"), codes)
        )
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
