"""Foundation contracts published by Rigging files.

A Blueprint criterion must name the application it tests without inventing it. Marina_Luna shows
what happens when it cannot: 47 Blueprints split 98 imports of ``app`` against 77 of
``marina_app``, and wrote the Flask ``create_app().test_client()`` 134 times against a FastAPI
stack whose Rigging states the correct idiom in prose. Both are one defect — the criterion author
had no published contract to write against, so it guessed, and guessed differently each time.

So the Rigging file publishes the contract. A file that defines a foundation declares its kind in
the header block::

    **Foundation:** web-server

and the shape it builds in a ``## Foundation Contract`` section::

    ## Foundation Contract

    - package: app_server
    - entry: create_app() -> FastAPI
    - fixture: web_client
    - fixture_source: conftest.py

Two facts follow from the declaration. A foundation kind is exclusive — one web server, one
database, one CLI — so selecting FastAPI and Flask is a refusal rather than a merge. And the
contract is the API the rest of the Target writes against, so ``drydock rigging compact`` carries
the section verbatim instead of asking a model to shorten it.

Kinds are open. A new exclusive foundation is a new Rigging file with a new ``**Foundation:**``
value; nothing here enumerates them.

A foundation also declares which tier it is built in::

    **Tier:** language

The tiers are the chain ``MANIFEST_CONTRACT.md`` already names — foundational, database, service,
ui — repeating inside each phase rather than running once across the project. A tier is therefore
a rank within a phase, never a phase, and never a block. The ranks are ordered because the work
is: a language foundation lays the directory tree, the environment, and the test runner that a
web server or a database foundation is then built into, so ``fastapi.md`` cannot build before
``python.md`` has. The palette and the voice are settled before the shell that shows them, and
the shell before any screen — so a screen is never built against a look nobody has chosen.
Services declare no tier at all, which is how they stay free to land either side of the shell.

Two contract shapes exist, because two kinds of foundation publish two different things. A
platform foundation publishes an importable API: the package a criterion imports, the entry that
constructs it, the fixture that hands it over. A language foundation publishes no API — it
publishes the tree and the environment everything else is built into. Requiring the API trio of a
language is why ``language`` sat outside the foundation set while being the most exclusive choice
a Target makes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from drydock.paths import get_rigging_root

#: The header field naming the exclusive foundation kind a Rigging file defines. Absent means the
#: file is additive guidance: ``sqlalchemy.md`` and ``alembic.md`` are Persistence files that a
#: Target selects alongside its one database, not instead of it.
FOUNDATION_HEADER = re.compile(r"^\*\*Foundation:\*\*[ \t]*(?P<kind>.+?)[ \t]*$", re.MULTILINE)

#: The section carrying the published shape. Read by tooling and spliced through compaction; never
#: summarized by a model.
CONTRACT_HEADING = "## Foundation Contract"

_CONTRACT_RE = re.compile(
    r"^## Foundation Contract[ \t]*$\n(?P<body>.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)

_FIELD_RE = re.compile(r"^-[ \t]+(?P<key>[a-z_]+):[ \t]*(?P<value>.+?)[ \t]*$", re.MULTILINE)

#: The header field naming the tier a Rigging file's work belongs to. Absent means the file
#: carries no ordering claim: ``uv_ruff.md`` is read wherever Python is, and a service story is
#: unordered against the interface tier by design.
TIER_HEADER = re.compile(r"^\*\*Tier:\*\*[ \t]*(?P<tier>.+?)[ \t]*$", re.MULTILINE)

#: The tiers in build order, numbered from 1. A tier is a position inside a phase, never a phase
#: and never a block: the chain repeats in every phase.
#:
#: 1. ``language``  — the tree, the environment, the test runner everything else is built into
#: 2. ``platform``  — the one web server, the one database, the one CLI, built into that tree
#: 3. ``branding``  — the palette, the typography, the voice
#: 4. ``interface`` — the shared UI shell, built with that palette
#: 5. ``screen``    — screens, built on that shell
#:
#: Services appear nowhere. They are deliberately unordered against ``interface``, which is the
#: one ordering claim the chain does not make.
TIER_ORDER = ("language", "platform", "branding", "interface", "screen")

#: What a platform foundation publishes: the name a criterion imports, the callable that builds
#: it, and the fixture that hands it over. A foundation that cannot name all three is not a
#: contract, and publishing it half-written puts the guess back where this module removes it.
API_FIELDS = ("package", "entry", "fixture")

#: What a language foundation publishes instead. There is no package to import and no client to
#: construct; what every later story needs is where code goes and how the suite is run.
ENVIRONMENT_FIELDS = ("source_root", "test_command")

#: Only the header block is scanned for the kind, matching ``technology_stack._category``.
_HEADER_LINES = 20


@dataclass(frozen=True)
class FoundationContract:
    """The shape one foundation Rigging file publishes."""

    #: Rigging filename, e.g. ``fastapi.md``.
    filename: str
    #: Exclusive kind, e.g. ``web-server``. One selected file per kind per Target.
    kind: str
    #: Tier the foundation is built in, e.g. ``platform``. Ranked by :data:`TIER_ORDER`.
    tier: str = ""
    #: Package the foundation story creates, e.g. ``app_server``. Empty for a language.
    package: str = ""
    #: Entry contract, e.g. ``create_app() -> FastAPI``. Empty for a language.
    entry: str = ""
    #: Fixture name criteria call rather than constructing a client themselves.
    fixture: str = ""
    #: Where the fixture lives in the build tree. Defaults to pytest's conventional home.
    fixture_source: str = "conftest.py"
    #: Directory the language foundation puts application code in, e.g. ``src/``.
    source_root: str = ""
    #: Command the language foundation makes the suite runnable by, e.g. ``pytest -q``.
    test_command: str = ""
    #: The verbatim section text, including its heading, for splicing through compaction.
    section: str = ""

    @property
    def entry_callable(self) -> str:
        """The bare callable name in ``entry``, e.g. ``create_app``. Empty when there is none."""
        return self.entry.split("(", 1)[0].strip()

    @property
    def shape(self) -> str:
        """``api`` when the foundation publishes an importable package, else ``environment``."""
        return "api" if self.package else "environment"

    @property
    def rank(self) -> int:
        """Build-order rank within a phase. An unranked tier sorts after every ranked one."""
        return tier_rank(self.tier)

    @property
    def tier_number(self) -> int:
        """The tier's 1-based number, or ``0`` when it makes no ordering claim."""
        return tier_number(self.tier)


def tier_rank(tier: str) -> int:
    """Rank a tier in the chain. An unnamed or unknown tier sorts after every ranked tier.

    Sorting an unranked tier last rather than first is the safe default: a file making no
    ordering claim must never be read as claiming to come before one that does.
    """
    name = (tier or "").strip().lower()
    return TIER_ORDER.index(name) if name in TIER_ORDER else len(TIER_ORDER)


def tier_number(tier: str) -> int:
    """Return the tier's 1-based number for display, or ``0`` when it is unranked."""
    name = (tier or "").strip().lower()
    return TIER_ORDER.index(name) + 1 if name in TIER_ORDER else 0


def declared_kind(text: str) -> str | None:
    """Return the foundation kind a Rigging file's header declares, or ``None``."""
    head = "\n".join(text.splitlines()[:_HEADER_LINES])
    match = FOUNDATION_HEADER.search(head)
    return match.group("kind").strip() if match else None


def declared_tier(text: str) -> str | None:
    """Return the tier a Rigging file's header declares, or ``None``."""
    head = "\n".join(text.splitlines()[:_HEADER_LINES])
    match = TIER_HEADER.search(head)
    return match.group("tier").strip() if match else None


def contract_section(text: str) -> str | None:
    """Return the verbatim ``## Foundation Contract`` section, heading included, or ``None``."""
    match = _CONTRACT_RE.search(text)
    if match is None:
        return None
    return text[match.start() : match.end()].rstrip() + "\n"


def parse_contract(text: str, *, filename: str) -> FoundationContract | None:
    """Return the contract a Rigging file publishes, or ``None`` when it declares no foundation.

    Raises ``ValueError`` when a file declares a kind but publishes no usable contract. That
    combination is an authoring error in Drydock's own Rigging, not a Target's problem, so it fails
    loudly rather than degrading to a guess.
    """
    kind = declared_kind(text)
    if kind is None:
        return None
    section = contract_section(text)
    if section is None:
        raise ValueError(
            f"{filename} declares **Foundation:** {kind} but has no '{CONTRACT_HEADING}' section"
        )
    tier = declared_tier(text)
    if tier is None:
        raise ValueError(
            f"{filename} declares **Foundation:** {kind} but no **Tier:**; a foundation with no "
            f"rank in the chain cannot be ordered against the foundations it is built on"
        )
    fields = {m.group("key"): m.group("value") for m in _FIELD_RE.finditer(section)}
    _require_one_shape(fields, filename=filename)
    return FoundationContract(
        filename=filename,
        kind=kind,
        tier=tier,
        package=fields.get("package", ""),
        entry=fields.get("entry", ""),
        fixture=fields.get("fixture", ""),
        fixture_source=fields.get("fixture_source", "conftest.py"),
        source_root=fields.get("source_root", ""),
        test_command=fields.get("test_command", ""),
        section=section,
    )


def _require_one_shape(fields: dict[str, str], *, filename: str) -> None:
    """Refuse a contract that completes neither published shape.

    Completing one shape is the whole requirement. A half-written contract is worse than none:
    the reader is told a name exists and then given nothing to write against.
    """
    for required in (API_FIELDS, ENVIRONMENT_FIELDS):
        if all(fields.get(name) for name in required):
            return
    missing = [name for name in API_FIELDS if not fields.get(name)]
    if all(not fields.get(name) for name in API_FIELDS):
        missing = [name for name in ENVIRONMENT_FIELDS if not fields.get(name)]
    raise ValueError(f"{filename} foundation contract is missing: {', '.join(missing)}")


def load_contract(path: Path) -> FoundationContract | None:
    """Return the contract published by one Rigging file on disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_contract(text, filename=path.name)


def contract_for(name: str, stack_dir: Path | None = None) -> FoundationContract | None:
    """Return the contract published by the Rigging file called ``name``, if it publishes one."""
    root = stack_dir if stack_dir is not None else get_rigging_root() / "stack"
    return load_contract(root / name)


def foundation_contracts(stack_dir: Path | None = None) -> dict[str, FoundationContract]:
    """Return every published foundation contract, keyed by Rigging filename."""
    root = stack_dir if stack_dir is not None else get_rigging_root() / "stack"
    contracts: dict[str, FoundationContract] = {}
    for path in sorted(root.glob("*.md")):
        if "_compact" in path.name or path.name == "README.md":
            continue
        if (contract := load_contract(path)) is not None:
            contracts[path.name] = contract
    return contracts


def exclusivity_conflicts(selected: list[str]) -> dict[str, list[str]]:
    """Return the foundation kinds ``selected`` names more than once.

    One web server, one database, one CLI. Two is not a richer stack; it is two application shapes
    in one build tree and every criterion coin-flipping between them.
    """
    published = foundation_contracts()
    by_kind: dict[str, list[str]] = {}
    for name in selected:
        if (contract := published.get(name)) is not None:
            by_kind.setdefault(contract.kind, []).append(name)
    return {kind: sorted(names) for kind, names in by_kind.items() if len(names) > 1}


# ── Tier ordering ───────────────────────────────────────────────────────────────


def tier_for(name: str, stack_dir: Path | None = None) -> str:
    """Return the tier the Rigging file ``name`` declares, or ``""`` when it declares none.

    Branding files sit at ``Rigging/`` rather than ``Rigging/stack/``, so both are searched.
    """
    roots = (
        [stack_dir] if stack_dir is not None else [get_rigging_root() / "stack", get_rigging_root()]
    )
    for root in roots:
        try:
            text = (root / name).read_text(encoding="utf-8")
        except OSError:
            continue
        return declared_tier(text) or ""
    return ""


def order_rigging(names: Iterable[str], stack_dir: Path | None = None) -> list[str]:
    """Return ``names`` in build order: by tier rank, then alphabetically.

    ``bootstrap5.md`` declares the ``interface`` tier, so it sorts after the platform and the
    branding files and before every screen file, and carries no claim at all against a service —
    the chain deliberately ranks no service tier.
    """
    ordered = list(names)
    return sorted(ordered, key=lambda name: (tier_rank(tier_for(name, stack_dir)), name))


def foundation_kinds() -> list[tuple[str, str, list[str]]]:
    """Return ``(tier, kind, candidate filenames)`` for every foundation kind, in build order.

    The order is the one the Commander chooses in and the one Drydock builds in: a language
    before the platform built into it. QuarterDeck renders this directly.
    """
    by_kind: dict[str, list[str]] = {}
    tiers: dict[str, str] = {}
    for name, contract in foundation_contracts().items():
        by_kind.setdefault(contract.kind, []).append(name)
        tiers[contract.kind] = contract.tier
    return [
        (tiers[kind], kind, sorted(names))
        for kind, names in sorted(
            by_kind.items(), key=lambda item: (tier_rank(tiers[item[0]]), item[0])
        )
    ]


# ── Published package names ─────────────────────────────────────────────────────


def published_packages() -> dict[str, list[FoundationContract]]:
    """Return ``{package: contracts publishing it}`` across every foundation Rigging file.

    These names are reserved. ``app_server`` means the selected web server whichever one was
    selected, so a criterion importing it when no web server is selected is importing nothing.
    """
    packages: dict[str, list[FoundationContract]] = {}
    for contract in foundation_contracts().values():
        if contract.package:
            packages.setdefault(contract.package, []).append(contract)
    return packages


def import_defects(
    imports: Iterable[tuple[int, str, tuple[str, ...]]],
    selected: Iterable[str],
) -> list[str]:
    """Judge a criterion's imports against the foundations this Target actually selected.

    ``imports`` is ``(line, module, imported names)`` per import statement, as
    ``acceptance.imported_modules`` yields it. ``selected`` is the Rigging filenames the
    Technology Stack names.

    Two facts are decidable from the text alone, and only two are judged here. A criterion that
    imports a reserved foundation package no selected foundation publishes names a package that
    will not exist — ``ModuleNotFoundError`` in its own frame on every run, for the whole repair
    budget. And a criterion that imports a published entry callable from some other package has
    found the right symbol under the wrong name, which is exactly the ``app`` / ``marina_app``
    split: 98 against 77, all of them importing ``create_app``.

    Nothing else is judged. Whether an arbitrary third-party import resolves is a fact about the
    build environment, not about the Blueprint, and guessing at it would refuse working plans.
    """
    published = published_packages()
    chosen = {name for name in selected}
    live = {
        contract.package: contract
        for contract in foundation_contracts().values()
        if contract.filename in chosen and contract.package
    }
    entry_owner = {
        contract.entry_callable: contract for contract in live.values() if contract.entry_callable
    }

    defects: list[str] = []
    for line, module, names in imports:
        root = module.split(".", 1)[0] if module else ""
        if root and root in published and root not in live:
            kind = published[root][0].kind
            defects.append(
                f"line {line}: imports `{root}`, the package a {kind} foundation publishes; "
                f"this Target's Technology Stack selects no {kind}"
            )
            continue
        for imported in names:
            owner = entry_owner.get(imported)
            if owner is not None and root and root != owner.package:
                defects.append(
                    f"line {line}: imports `{imported}` from `{root}`; the {owner.kind} "
                    f"foundation publishes it in `{owner.package}` "
                    f"({owner.filename}) — import it from there"
                )
    return defects
