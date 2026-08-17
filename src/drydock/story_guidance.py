"""Story guidance: named stories supplied to planning, and the commands that decide them.

What this is. A story is a Blueprint — an atomic specification Drydock authors. *Story guidance*
is not a story; it is the instruction that a story by this name must exist, and, where the source
material supplies one, the command that decides whether it is done. The Blueprint remains the
story. This file only names it and, optionally, grades it.

Two producers, distinguished by ``provenance``, and the distinction carries authority:

* ``commander`` — supplied before ``analyze`` as a kit input. Binding. ``analyze`` preserves each
  id verbatim and ``plan`` shapes a story around the scope its gate exercises. Its gates are
  oracles: data the model did not author, which is the only kind of evidence that can close a
  story ``closed/verified``.
* ``plan`` — derived by ``analyze`` when the imported material states its own build breakdown (a
  conformance corpus grouped by chapter, a suite partitioned by feature). Recorded as evidence,
  not authority. Its gates are ordinary model-authored criteria and ``drydock plan repair`` may
  correct them.

Without the split, letting Drydock write this file would quietly destroy the reason the governed
contract exists: an oracle the model wrote proves nothing about the code the same model wrote.

``ACCEPTANCE.json`` keeps only ``full``, the whole-project release gate, which is genuinely not a
story. Everything story-shaped lives here, beside ``ANALYSIS.md``, and is rendered into that
document's ``## Story Guidance`` section so a reader sees it without opening JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import SpecificationError

#: Target-root artifact, beside ``ANALYSIS.md``.
FILENAME = "STORY_GUIDANCE.json"

#: Supplied by the Commander before analyze. Binding; its gates are governed oracles.
PROVENANCE_COMMANDER = "commander"

#: Derived by Drydock from the imported material. Evidence; its gates are repairable criteria.
PROVENANCE_PLAN = "plan"

PROVENANCES = (PROVENANCE_COMMANDER, PROVENANCE_PLAN)

#: Heading rendered into ``ANALYSIS.md``. The table refers to this file rather than carrying the
#: argv, because ANALYSIS.md is LLM-regenerated and a Commander-supplied command must not be
#: rewritable by the model that reads it.
SECTION_HEADING = "## Story Guidance"


@dataclass(frozen=True)
class StoryGuidanceEntry:
    """One named story, its provenance, and the command that decides it if there is one."""

    story_id: str
    provenance: str = PROVENANCE_PLAN
    gate: tuple[str, ...] = ()
    note: str = ""

    @property
    def binding(self) -> bool:
        """Commander guidance constrains the plan; derived guidance only records it."""
        return self.provenance == PROVENANCE_COMMANDER

    @property
    def governed(self) -> bool:
        """A gate is an oracle only when its author is not the model being graded."""
        return self.binding and bool(self.gate)

    def to_dict(self) -> dict:
        payload: dict[str, object] = {"id": self.story_id, "provenance": self.provenance}
        if self.gate:
            payload["gate"] = list(self.gate)
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass(frozen=True)
class StoryGuidance:
    """Every named story for one Target. An absent file is an empty set, never an error."""

    entries: tuple[StoryGuidanceEntry, ...] = ()
    source: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.entries)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(entry.story_id for entry in self.entries)

    @property
    def commander_ids(self) -> tuple[str, ...]:
        return tuple(entry.story_id for entry in self.entries if entry.binding)

    @property
    def gates(self) -> dict[str, tuple[str, ...]]:
        """Story id to argv, for every entry that carries a command."""
        return {entry.story_id: entry.gate for entry in self.entries if entry.gate}

    @property
    def governed_gates(self) -> dict[str, tuple[str, ...]]:
        """Only the gates whose authority the model did not author."""
        return {entry.story_id: entry.gate for entry in self.entries if entry.governed}

    def entry_for(self, *story_ids: str) -> StoryGuidanceEntry | None:
        """First entry matching any selector, in caller order.

        A block exposes its generated story id plus the stable analyzed ids from ``covers:``.
        Callers put stable selectors first so a Commander-supplied identity wins over a
        generated implementation id.
        """
        by_id = {entry.story_id: entry for entry in self.entries}
        for story_id in story_ids:
            entry = by_id.get(story_id)
            if entry is not None:
                return entry
        return None

    def merged_with(self, other: StoryGuidance) -> StoryGuidance:
        """Fold ``other`` in behind this set. Existing ids keep their entry.

        Used by ``analyze`` to add derived stories without ever displacing, renaming, or
        regrading a Commander-supplied one.
        """
        known = {entry.story_id for entry in self.entries}
        added = tuple(entry for entry in other.entries if entry.story_id not in known)
        if not added:
            return self
        return StoryGuidance(entries=self.entries + added, source=self.source or other.source)


def _argv(value: object, *, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise SpecificationError(f"{FILENAME}: {where} must be a non-empty argv list")
    if not all(isinstance(item, str) and item for item in value):
        raise SpecificationError(f"{FILENAME}: {where} argv entries must be non-empty strings")
    return tuple(value)


def _provenance(value: object, *, where: str, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text not in PROVENANCES:
        raise SpecificationError(
            f"{FILENAME}: {where} provenance must be one of {', '.join(PROVENANCES)}"
        )
    return text


def _entries_from(payload: object, *, where: str, default_provenance: str) -> tuple:
    """Parse either the record list or the id-to-argv shorthand.

    The shorthand exists because a kit declaring nothing but gates should not have to write a
    provenance on every line; a kit input is Commander-supplied by definition.
    """
    if payload is None:
        return ()
    entries: list[StoryGuidanceEntry] = []
    if isinstance(payload, dict):
        for story_id, argv in payload.items():
            entries.append(
                StoryGuidanceEntry(
                    story_id=str(story_id),
                    provenance=default_provenance,
                    gate=_argv(argv, where=f"{where}.{story_id}"),
                )
            )
        return tuple(entries)
    if not isinstance(payload, list):
        raise SpecificationError(f"{FILENAME}: {where} must be a list of stories or an object")
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise SpecificationError(f"{FILENAME}: {where}[{index}] must be an object")
        story_id = str(item.get("id") or "").strip()
        if not story_id:
            raise SpecificationError(f"{FILENAME}: {where}[{index}] requires a non-empty id")
        gate = item.get("gate")
        entries.append(
            StoryGuidanceEntry(
                story_id=story_id,
                provenance=_provenance(
                    item.get("provenance"), where=f"{where}[{index}]", default=default_provenance
                ),
                gate=_argv(gate, where=f"{where}[{index}].gate") if gate is not None else (),
                note=str(item.get("note") or "").strip(),
            )
        )
    seen: set[str] = set()
    for entry in entries:
        if entry.story_id in seen:
            raise SpecificationError(f"{FILENAME}: duplicate story id {entry.story_id}")
        seen.add(entry.story_id)
    return tuple(entries)


def load_guidance(target_dir: Path) -> StoryGuidance:
    """Read the Target's story guidance, or an empty set when absent.

    Falls back to the retired ``ACCEPTANCE.json`` ``stages`` key so a Target planned before this
    split keeps its gates. Entries recovered that way are Commander-supplied, because that file
    was never writable by an LLM-assisted command.
    """
    path = target_dir / FILENAME
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SpecificationError(f"{FILENAME} is not readable JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise SpecificationError(f"{FILENAME} must contain a JSON object")
        entries = _entries_from(
            payload.get("stories"), where="stories", default_provenance=PROVENANCE_PLAN
        )
        return StoryGuidance(entries=entries, source=str(path))
    return _legacy_guidance(target_dir)


def _legacy_guidance(target_dir: Path) -> StoryGuidance:
    """Recover guidance from the retired ``ACCEPTANCE.json`` ``stages`` key."""
    legacy = target_dir / "ACCEPTANCE.json"
    if not legacy.is_file():
        return StoryGuidance()
    try:
        payload = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return StoryGuidance()
    if not isinstance(payload, dict) or not payload.get("stages"):
        return StoryGuidance()
    entries = _entries_from(
        payload.get("stages"), where="stages", default_provenance=PROVENANCE_COMMANDER
    )
    return StoryGuidance(entries=entries, source=str(legacy))


def write_guidance(target_dir: Path, guidance: StoryGuidance) -> Path:
    """Persist story guidance into the Target root."""
    path = target_dir / FILENAME
    payload = {"stories": [entry.to_dict() for entry in guidance.entries]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def guidance_from_config(payload: object, *, where: str) -> StoryGuidance:
    """Build guidance from a fixture's ``acceptance`` block.

    Accepts ``story_guidance`` and, for one release, the retired ``stages`` key. Both declare
    Commander-supplied stories, because a kit input precedes every Drydock command.
    """
    if payload is None:
        return StoryGuidance()
    if not isinstance(payload, dict):
        raise SpecificationError(f"{where}: acceptance must be an object")
    declared = payload.get("story_guidance")
    key = "story_guidance"
    if declared is None:
        declared = payload.get("stages")
        key = "stages"
    if declared is None:
        return StoryGuidance()
    entries = _entries_from(
        declared, where=f"{where}.{key}", default_provenance=PROVENANCE_COMMANDER
    )
    return StoryGuidance(entries=entries, source=where)


def render_section(guidance: StoryGuidance) -> str:
    """Render the ``## Story Guidance`` section for ``ANALYSIS.md``.

    The command is shown, not stored here: this section is regenerated with the document, and the
    authoritative argv stays in ``STORY_GUIDANCE.json`` where no LLM-assisted command writes it.
    """
    lines = [
        SECTION_HEADING,
        "",
        f"Named stories planning must produce. Authoritative record: `{FILENAME}`.",
        "",
    ]
    if not guidance.declared:
        lines.append("None.")
        lines.append("")
        return "\n".join(lines)
    lines.append("| Story ID | Provenance | Gate | Note |")
    lines.append("|---|---|---|---|")
    for entry in guidance.entries:
        gate = f"`{' '.join(entry.gate)}`" if entry.gate else "—"
        lines.append(f"| {entry.story_id} | {entry.provenance} | {gate} | {entry.note or '—'} |")
    lines.append("")
    return "\n".join(lines)


def replace_section(analysis_text: str, guidance: StoryGuidance) -> str:
    """Insert or replace ``## Story Guidance`` in an analysis document.

    Placed after ``## Story List`` when that section exists, because guidance names the stories
    the list enumerates and reads as a footnote to it anywhere else.
    """
    section = render_section(guidance).rstrip() + "\n"
    lines = analysis_text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == SECTION_HEADING),
        None,
    )
    if start is not None:
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        return "".join(lines[:start]) + section + "\n" + "".join(lines[end:])
    anchor = next(
        (i for i, line in enumerate(lines) if line.strip() == "## Story List"),
        None,
    )
    if anchor is None:
        body = analysis_text.rstrip("\n")
        return f"{body}\n\n{section}" if body else section
    insert = next(
        (i for i in range(anchor + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "".join(lines[:insert]) + section + "\n" + "".join(lines[insert:])
