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
"""

from __future__ import annotations

import re
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

#: Fields every contract states. A foundation that cannot name its package, its entry point and
#: the fixture criteria call is not a contract, and publishing it half-written would put the guess
#: back where this module removes it.
REQUIRED_FIELDS = ("package", "entry", "fixture")

#: Only the header block is scanned for the kind, matching ``technology_stack._category``.
_HEADER_LINES = 20


@dataclass(frozen=True)
class FoundationContract:
    """The shape one foundation Rigging file publishes."""

    #: Rigging filename, e.g. ``fastapi.md``.
    filename: str
    #: Exclusive kind, e.g. ``web-server``. One selected file per kind per Target.
    kind: str
    #: Python package the foundation story creates, e.g. ``app_server``.
    package: str
    #: Entry contract, e.g. ``create_app() -> FastAPI``.
    entry: str
    #: Fixture name criteria call rather than constructing a client themselves.
    fixture: str
    #: Where the fixture lives in the build tree. Defaults to pytest's conventional home.
    fixture_source: str = "conftest.py"
    #: The verbatim section text, including its heading, for splicing through compaction.
    section: str = ""

    @property
    def entry_callable(self) -> str:
        """The bare callable name in ``entry``, e.g. ``create_app``."""
        return self.entry.split("(", 1)[0].strip()


def declared_kind(text: str) -> str | None:
    """Return the foundation kind a Rigging file's header declares, or ``None``."""
    head = "\n".join(text.splitlines()[:_HEADER_LINES])
    match = FOUNDATION_HEADER.search(head)
    return match.group("kind").strip() if match else None


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
    fields = {m.group("key"): m.group("value") for m in _FIELD_RE.finditer(section)}
    if missing := [name for name in REQUIRED_FIELDS if not fields.get(name)]:
        raise ValueError(f"{filename} foundation contract is missing: {', '.join(missing)}")
    return FoundationContract(
        filename=filename,
        kind=kind,
        package=fields["package"],
        entry=fields["entry"],
        fixture=fields["fixture"],
        fixture_source=fields.get("fixture_source", "conftest.py"),
        section=section,
    )


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
