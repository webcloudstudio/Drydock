"""Stage 2 blocked-Blueprint reports: parse, check against the batch's context, and feed back.

A Stage 2 batch that cannot author a Current-batch Blueprint reports it in ``BLUEPRINT_BLOCKED.txt``
instead of prose. Drydock checks each claim deterministically before it is fed to the retry: a
claim the batch's own context refutes is answered with the refutation, so the retry differs from
the call that failed (LayersTesting ``20261022.121722``: batch 27 said the sources were absent;
they were prompt parts 14–19).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from drydock.prompt_assembly import PromptAssembly

BLOCKED_BLOCK = "BLUEPRINT_BLOCKED.txt"
ERROR_TYPES = ("missing-input", "conflict", "insufficient-specification", "other")
#: Error types that, still standing when retries run out, need a Commander's product decision.
PRODUCT_ERROR_TYPES = frozenset({"conflict", "insufficient-specification"})

_FIELD_RE = re.compile(r"^(Blueprint|Error type|Cited input):\s*(.*)$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^(Details|Required action):\s*(.*)$", re.IGNORECASE)
_FILENAME_RE = re.compile(r"[\w./\-]+\.[A-Za-z0-9]+")
_FROZEN_INPUTS = ("TOPOLOGY.md", "DECISIONS.json")
#: A Required action that names no decision: the batch resolved its own block.
_SELF_RESOLVED_RE = re.compile(
    r"^\W*(none|no (action|decision|change)s?|nothing|n/a)\b|\bcan be authored\b", re.IGNORECASE
)
#: A claim that rests on accepted Blueprints, which batches do not receive by design.
_ACCEPTED_CLAIM_RE = re.compile(
    r"\baccepted\s+(artifact|blueprint|file|spec)s?\b|\bcan(not|'t)\s+verify\b", re.IGNORECASE
)
_ACCEPTED_BY_DESIGN = (
    "Batches do not receive accepted Blueprints by design. Author against the frozen "
    "topology's `Provides` lines and record the assumption under `## Questions`."
)


@dataclass(frozen=True)
class BlockedBlueprint:
    """One Blueprint a batch reported it could not author, and Drydock's finding on the claim."""

    blueprint: str
    error_type: str
    cited: str
    details: str = ""
    required_action: str = ""
    refutation: str = ""

    @property
    def stands(self) -> bool:
        """The claim survived Drydock's check."""
        return not self.refutation

    def rendered(self) -> tuple[str, ...]:
        """The entry as the next batch reads it under ``Prior run error details``."""
        lines = [
            f"- {self.blueprint or '(no Blueprint named)'} · {self.error_type or '(no type)'} · "
            f"cited {self.cited or '(nothing)'}"
        ]
        lines.extend(f"    {line}" for line in self.details.splitlines() if line.strip())
        if self.refutation:
            lines.append(f"    Drydock check: refuted — {self.refutation}")
        return tuple(lines)

    def declaration(self) -> str:
        """The entry in the Stage 1 Error Mode shape, for the deferred product-decision record."""
        lines = [
            f"Blueprint: {self.blueprint}",
            f"Error type: {self.error_type}",
            f"Cited input: {self.cited}",
            "Reason:",
            *(self.details.splitlines() or ["-"]),
            "Required action:",
            *(self.required_action.splitlines() or ["- Resolve the cited input and replan."]),
        ]
        return "\n".join(lines)


def parse_blocked(body: str) -> tuple[BlockedBlueprint, ...]:
    """Split a ``BLUEPRINT_BLOCKED.txt`` body into entries, one per ``Blueprint:`` line."""
    entries: list[dict[str, list[str] | str]] = []
    section = ""
    for raw in body.splitlines():
        line = raw.rstrip()
        field = _FIELD_RE.match(line.strip())
        if field is not None:
            key = field.group(1).lower()
            if key == "blueprint":
                entries.append({"details": [], "required action": []})
            if entries:
                value = field.group(2).strip()
                entries[-1][key] = value if key == "cited input" else value.strip("`")
            section = ""
            continue
        heading = _SECTION_RE.match(line.strip())
        if heading is not None and entries:
            section = heading.group(1).lower()
            if heading.group(2).strip():
                _append(entries[-1], section, heading.group(2).strip())
            continue
        if section and entries and line.strip():
            _append(entries[-1], section, line.strip())
    return tuple(
        BlockedBlueprint(
            blueprint=str(entry.get("blueprint", "")),
            error_type=str(entry.get("error type", "")).lower(),
            cited=str(entry.get("cited input", "")),
            details="\n".join(entry["details"]),
            required_action="\n".join(entry["required action"]),
        )
        for entry in entries
    )


def _append(entry: dict[str, list[str] | str], section: str, line: str) -> None:
    value = entry[section]
    assert isinstance(value, list)
    value.append(line)


def context_inputs(assembly: PromptAssembly) -> frozenset[str]:
    """Every input name a batch's assembled prompt carries, by label and by path."""
    names: set[str] = set()
    for part in assembly.parts:
        if not part.included:
            continue
        label = part.label.strip()
        if _FILENAME_RE.fullmatch(label):
            names.add(label)
        if part.path is not None:
            path = PurePosixPath(str(part.path).replace("\\", "/"))
            names.add(path.name)
            if path.parent.name == "sources":
                names.add(f"sources/{path.name}")
        if part.kind == "frozen-stage":
            names.update(_FROZEN_INPUTS)
    return frozenset(names)


def _cited_file(cited: str) -> str:
    match = _FILENAME_RE.search(cited)
    return match.group(0) if match else ""


def _matches(name: str, candidates: Iterable[str]) -> str:
    """The candidate equal to ``name``, else the first by sorted order sharing its file name."""
    ordered = sorted(candidates)
    if name in ordered:
        return name
    base = PurePosixPath(name).name
    return next((item for item in ordered if PurePosixPath(item).name == base), "")


def check_blocked(
    entries: Iterable[BlockedBlueprint],
    *,
    present: Collection[str],
    accepted: Collection[str],
    tranche: Collection[str],
    unattended: bool = False,
) -> tuple[BlockedBlueprint, ...]:
    """Set ``refutation`` on each entry the batch's own context disproves; leave the rest standing.

    Only facts Drydock holds are checked: whether the Blueprint is in the Current batch, whether
    the error type and citation are well formed, whether the entry's own Required action names
    no decision, whether the claim rests on accepted Blueprints, which batches do not receive by
    design, and whether a cited "missing" input is present. Unattended, no Commander answers an
    ``insufficient-specification`` block, so the batch chooses (LayersTesting ``20261022.165023``).
    """
    checked: list[BlockedBlueprint] = []
    for entry in entries:
        refutation = _refutation(entry, present, accepted, tranche, unattended)
        checked.append(replace(entry, refutation=refutation))
    return tuple(checked)


def _refutation(
    entry: BlockedBlueprint,
    present: Collection[str],
    accepted: Collection[str],
    tranche: Collection[str],
    unattended: bool,
) -> str:
    if entry.blueprint not in tranche:
        return f"`{entry.blueprint}` is not in the Current batch; block only Current-batch files."
    if entry.error_type not in ERROR_TYPES:
        return (
            f"`{entry.error_type}` is not an error type. Use one of: "
            + ", ".join(ERROR_TYPES)
            + "."
        )
    cited = _cited_file(entry.cited)
    if not cited:
        return "the entry cites no input file. Name the file and section that block the Blueprint."
    if _SELF_RESOLVED_RE.search(entry.required_action):
        return (
            "your Required action names no decision, so nothing blocks the Blueprint. Author it "
            "with the choice you stated."
        )
    claim = f"{entry.details}\n{entry.required_action}"
    named = next((name for name in sorted(accepted) if name in claim), "")
    if named or _ACCEPTED_CLAIM_RE.search(claim):
        subject = (
            f"`{named}` is an accepted Blueprint."
            if named
            else "The claim rests on accepted Blueprints."
        )
        return f"{subject} {_ACCEPTED_BY_DESIGN}"
    if unattended and entry.error_type == "insufficient-specification":
        return (
            "no Commander answers during an unattended run. Choose the narrowest behavior "
            "consistent with the cited inputs and author the Blueprint on it."
        )
    if entry.error_type != "missing-input":
        return ""
    held = _matches(cited, accepted)
    if held:
        return f"`{held}` is an accepted Blueprint. {_ACCEPTED_BY_DESIGN}"
    supplied = _matches(cited, present)
    if supplied:
        return f"`{supplied}` is in this context. Read it and author the Blueprint."
    return ""
