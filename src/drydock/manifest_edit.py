"""Constrained reorder/regroup editing of MANIFEST.md.

The QuarterDeck build compass lets the product owner reorder build steps and move
them between features. Edits are constrained only by coarse layer bands: steps must
stay in non-decreasing band order (Foundation, then Data/Persistence, then the
Features/Screens band), and a move that would newly break that order is rejected.
Movement within a band is free. ``depends:`` does not constrain order — the build
engine selects work at run time by walking ``depends:`` — so manifest order is
display and priority only. Acceptance (``ac``) blocks are out of the ordered stream
entirely. ``normalize_order`` restores canonical band order on demand.

The writer preserves each block's source lines verbatim (including ``|`` block
scalars); it only reorders blocks and rewrites a moved step's ``parent:`` line.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from drydock.build import BAND_FOUNDATION, BAND_NAMES, band_for, work_kind_for
from drydock.build_plan import _HEADER_RE, _split_depends
from drydock.errors import SpecificationError

_FIELD_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")
_STEP_TYPES = ("story", "spike")


@dataclass
class RawBlock:
    """One MANIFEST.md block with its exact source lines and routing fields."""

    block_id: str
    block_type: str
    parent: str | None
    depends: tuple[str, ...]
    lines: list[str] = field(default_factory=list)


@dataclass
class ManifestDoc:
    """A parsed-for-editing manifest: header preamble plus ordered raw blocks."""

    path: Path
    preamble: list[str]
    blocks: list[RawBlock]

    def by_id(self) -> dict[str, RawBlock]:
        return {b.block_id: b for b in self.blocks}


def _scan_field(lines: list[str], key: str) -> str | None:
    for line in lines:
        match = _FIELD_LINE_RE.match(line)
        if match and match.group(1).lower() == key:
            return match.group(2).strip()
    return None


def split_manifest(path: Path) -> ManifestDoc:
    """Split a MANIFEST.md into its header preamble and ordered raw blocks."""
    if not path.is_file():
        raise SpecificationError(f"MANIFEST.md not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()

    first = next((i for i, line in enumerate(lines) if _HEADER_RE.match(line)), len(lines))
    preamble = lines[:first]

    blocks: list[RawBlock] = []
    index = first
    while index < len(lines):
        header = _HEADER_RE.match(lines[index])
        if not header:
            index += 1
            continue
        start = index
        index += 1
        while index < len(lines) and not _HEADER_RE.match(lines[index]):
            index += 1
        body = lines[start:index]
        while body and not body[-1].strip():
            body.pop()
        block_id = (_scan_field(body, "id") or "").strip()
        if not block_id:
            raise SpecificationError(f"Block missing id near: {body[0]!r}")
        parent = (_scan_field(body, "parent") or "").strip() or None
        depends_raw = _scan_field(body, "depends") or ""
        blocks.append(
            RawBlock(
                block_id=block_id,
                block_type=header.group(1),
                parent=parent,
                depends=_split_depends(depends_raw),
                lines=body,
            )
        )
    return blocks_doc(path, preamble, blocks)


def blocks_doc(path: Path, preamble: list[str], blocks: list[RawBlock]) -> ManifestDoc:
    doc = ManifestDoc(path=path, preamble=preamble, blocks=blocks)
    _require_unique_ids(doc)
    return doc


def _require_unique_ids(doc: ManifestDoc) -> None:
    seen: set[str] = set()
    for block in doc.blocks:
        if block.block_id in seen:
            raise SpecificationError(f"Duplicate block id {block.block_id!r} in {doc.path}")
        seen.add(block.block_id)


# ── Tree view (features → steps → acs) ───────────────────────────────────────


def _feature_order(doc: ManifestDoc) -> list[str]:
    return [b.block_id for b in doc.blocks if b.block_type == "feature"]


def _steps_by_feature(doc: ManifestDoc) -> dict[str | None, list[str]]:
    features = set(_feature_order(doc))
    out: dict[str | None, list[str]] = {}
    for block in doc.blocks:
        if block.block_type not in _STEP_TYPES:
            continue
        key = block.parent if block.parent in features else None
        out.setdefault(key, []).append(block.block_id)
    return out


def _acs_by_parent(doc: ManifestDoc) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for block in doc.blocks:
        if block.block_type == "ac" and block.parent:
            out.setdefault(block.parent, []).append(block.block_id)
    return out


def _flatten(doc: ManifestDoc) -> list[RawBlock]:
    """Re-serialize blocks canonically: features group their steps contiguously.

    Order within each group follows current block order. Each step is followed by
    its acceptance checks; feature-level acceptance checks trail the feature's
    steps; ungrouped steps follow all features; any orphan blocks trail last.
    """
    by_id = doc.by_id()
    features = _feature_order(doc)
    steps_by_feature = _steps_by_feature(doc)
    acs_by_parent = _acs_by_parent(doc)
    emitted: set[str] = set()
    out: list[RawBlock] = []

    def emit(block_id: str) -> None:
        if block_id in emitted or block_id not in by_id:
            return
        emitted.add(block_id)
        out.append(by_id[block_id])

    def emit_step(step_id: str) -> None:
        emit(step_id)
        for ac_id in acs_by_parent.get(step_id, []):
            emit(ac_id)

    for feature_id in features:
        emit(feature_id)
        for step_id in steps_by_feature.get(feature_id, []):
            emit_step(step_id)
        for ac_id in acs_by_parent.get(feature_id, []):
            emit(ac_id)
    for step_id in steps_by_feature.get(None, []):
        emit_step(step_id)
    for block in doc.blocks:  # orphans (e.g. acs whose parent is missing)
        emit(block.block_id)
    return out


# ── Validation ───────────────────────────────────────────────────────────────


def _raw_band(block: RawBlock) -> int:
    """Layer band for one raw step block, derived from its ``implements:`` line."""
    implements = _scan_field(block.lines, "implements") or ""
    names = [name.strip() for name in implements.split(",") if name.strip()]
    return band_for(block.block_type, names)


def _raw_work_kind(block: RawBlock) -> str:
    """Stack-local work kind for one raw step block."""
    implements = _scan_field(block.lines, "implements") or ""
    names = [name.strip() for name in implements.split(",") if name.strip()]
    return work_kind_for(block.block_type, names)


def validate_order(blocks: list[RawBlock]) -> list[str]:
    """Return layer-band ordering violations for a flattened order; empty means valid.

    Manifest order constrains only the coarse layer band: ``story``/``spike`` steps
    must appear in non-decreasing band order (Foundation, then Data/Persistence,
    then the Features/Screens band). Movement within a band is free, and
    ``depends:`` does not constrain order — the build engine selects work at run
    time by walking ``depends:``. Acceptance (``ac``) blocks are out of the ordered
    stream entirely and are never positioned or checked.
    """
    errors: list[str] = []
    highest = BAND_FOUNDATION
    highest_label = BAND_NAMES[BAND_FOUNDATION]
    for block in blocks:
        if block.block_type not in _STEP_TYPES:
            continue
        band = _raw_band(block)
        if band < highest:
            errors.append(
                f"{block.block_id} ({BAND_NAMES[band]}) is ordered after {highest_label} work"
            )
        else:
            highest, highest_label = band, BAND_NAMES[band]
    return errors


# ── Edit primitives ──────────────────────────────────────────────────────────


def _set_parent_line(block: RawBlock, feature_id: str | None) -> None:
    """Rewrite (or remove/insert) the block's ``parent:`` line in place."""
    block.parent = feature_id or None
    kept: list[str] = []
    replaced = False
    for line in block.lines:
        match = _FIELD_LINE_RE.match(line)
        if match and match.group(1).lower() == "parent":
            if feature_id:
                kept.append(f"parent:       {feature_id}")
            replaced = True
            continue
        kept.append(line)
    if feature_id and not replaced:
        insert_at = 1
        for i, line in enumerate(kept):
            match = _FIELD_LINE_RE.match(line)
            if match and match.group(1).lower() == "id":
                insert_at = i + 1
                break
        kept.insert(insert_at, f"parent:       {feature_id}")
    block.lines = kept


def _neighbor(seq: list[str], target: str, direction: str) -> str:
    if target not in seq:
        raise SpecificationError(f"{target} is not in its group")
    pos = seq.index(target)
    swap = pos - 1 if direction == "up" else pos + 1
    if swap < 0 or swap >= len(seq):
        raise SpecificationError(f"Cannot move {target} {direction}; already at the edge")
    return seq[swap]


def _swap_block_positions(doc: ManifestDoc, id_a: str, id_b: str) -> None:
    ids = [b.block_id for b in doc.blocks]
    ia, ib = ids.index(id_a), ids.index(id_b)
    doc.blocks[ia], doc.blocks[ib] = doc.blocks[ib], doc.blocks[ia]
    doc.blocks[:] = _flatten(doc)


def move_step(doc: ManifestDoc, step_id: str, direction: str) -> None:
    """Move a step earlier/later among the steps of its own feature group."""
    block = doc.by_id().get(step_id)
    if block is None or block.block_type not in _STEP_TYPES:
        raise SpecificationError(f"{step_id} is not a movable step")
    if direction not in ("up", "down"):
        raise SpecificationError(f"Invalid direction {direction!r}")
    before = validate_order(doc.blocks)
    siblings = _steps_by_feature(doc)[block.parent if _is_feature(doc, block.parent) else None]
    other = _neighbor(siblings, step_id, direction)
    _swap_block_positions(doc, step_id, other)
    _reject_if_worsened(doc, before)


def move_feature(doc: ManifestDoc, feature_id: str, direction: str) -> None:
    """Move a feature group earlier/later among the features."""
    block = doc.by_id().get(feature_id)
    if block is None or block.block_type != "feature":
        raise SpecificationError(f"{feature_id} is not a feature")
    if direction not in ("up", "down"):
        raise SpecificationError(f"Invalid direction {direction!r}")
    before = validate_order(doc.blocks)
    order = _feature_order(doc)
    other = _neighbor(order, feature_id, direction)
    _swap_block_positions(doc, feature_id, other)
    _reject_if_worsened(doc, before)


def regroup_step(doc: ManifestDoc, step_id: str, feature_id: str | None) -> None:
    """Move a step into another feature (or out of all features)."""
    block = doc.by_id().get(step_id)
    if block is None or block.block_type not in _STEP_TYPES:
        raise SpecificationError(f"{step_id} is not a movable step")
    if feature_id and not _is_feature(doc, feature_id):
        raise SpecificationError(f"{feature_id} is not a feature")
    before = validate_order(doc.blocks)
    _set_parent_line(block, feature_id)
    doc.blocks[:] = _flatten(doc)
    _reject_if_worsened(doc, before)


def _is_feature(doc: ManifestDoc, block_id: str | None) -> bool:
    if not block_id:
        return False
    block = doc.by_id().get(block_id)
    return block is not None and block.block_type == "feature"


def _reject_if_worsened(doc: ManifestDoc, before: list[str]) -> None:
    """Reject only the band-order violations a move newly introduces.

    Pre-existing violations in the manifest are not the caller's doing, so the
    message lists only the violations this edit actually causes — never the full
    set — matching what the Commander can see on the compass.
    """
    new = [error for error in validate_order(doc.blocks) if error not in set(before)]
    if new:
        raise SpecificationError(
            "Move rejected; it would break the build order:\n  - " + "\n  - ".join(new)
        )


# ── Structure edits (rename, add group, split) ───────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "feature"


def _unique_id(base: str, existing: set[str]) -> str:
    candidate, n = base, 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _next_ordinal(doc: ManifestDoc) -> int:
    highest = 0
    for block in doc.blocks:
        match = _HEADER_RE.match(block.lines[0]) if block.lines else None
        if match:
            highest = max(highest, int(match.group(2)))
    return highest + 1


def _set_header_name(block: RawBlock, new_name: str) -> None:
    """Rewrite a block's ``## <type> <ordinal>: <name>`` header, keeping type/ordinal."""
    match = _HEADER_RE.match(block.lines[0]) if block.lines else None
    if not match:
        raise SpecificationError(f"{block.block_id} has no parsable header line")
    block.lines[0] = f"## {match.group(1)} {match.group(2)}: {new_name}"


def rename_block(doc: ManifestDoc, block_id: str, new_name: str) -> None:
    """Rename a feature or step: rewrite only its header label.

    The block ``id:`` is untouched, so every ``parent:``/``depends:`` reference
    and the work graph remain intact; the name is a display label only.
    """
    name = (new_name or "").strip()
    if not name or "\n" in name:
        raise SpecificationError("New name must be a non-empty single line")
    block = doc.by_id().get(block_id)
    if block is None:
        raise SpecificationError(f"{block_id} not found")
    if block.block_type not in ("feature", *_STEP_TYPES):
        raise SpecificationError(f"{block_id} is not a renamable feature or step")
    _set_header_name(block, name)


def add_feature(doc: ManifestDoc, name: str) -> str:
    """Append a new, empty feature group. Returns its generated id.

    The group carries no steps; the product owner moves stories into it with the
    regroup control. It appears in the compass and the regroup dropdown at once.
    """
    label = (name or "").strip()
    if not label or "\n" in label:
        raise SpecificationError("Feature name must be a non-empty single line")
    existing = {b.block_id for b in doc.blocks}
    feature_id = _unique_id(f"feat-{_slug(label)}", existing)
    doc.blocks.append(
        RawBlock(
            block_id=feature_id,
            block_type="feature",
            parent=None,
            depends=(),
            lines=[
                f"## feature {_next_ordinal(doc)}: {label}",
                f"id: {feature_id}",
                f"summary: {label}",
                "state: pending",
            ],
        )
    )
    doc.blocks[:] = _flatten(doc)
    _require_unique_ids(doc)
    return feature_id


def split_group(doc: ManifestDoc, feature_id: str) -> list[str]:
    """Split a feature into one feature per story. Returns the resulting feature ids.

    The original feature is reused for its first story (renamed to that story);
    each remaining story gets a new feature named after it, and is reparented.
    """
    if not _is_feature(doc, feature_id):
        raise SpecificationError(f"{feature_id} is not a feature")
    steps = _steps_by_feature(doc).get(feature_id, [])
    if len(steps) < 2:
        raise SpecificationError(f"{feature_id} needs at least two stories to split")
    before = validate_order(doc.blocks)
    by_id = doc.by_id()
    existing = {b.block_id for b in doc.blocks}
    result: list[str] = []
    # New features are inserted immediately after the original so the split
    # stories keep their build position; a story that a later group depends on
    # must not be pushed behind that group.
    insert_at = next(i for i, b in enumerate(doc.blocks) if b.block_id == feature_id) + 1
    for position, step_id in enumerate(steps):
        step = by_id[step_id]
        header = _HEADER_RE.match(step.lines[0]) if step.lines else None
        story_name = header.group(3) if header else step_id
        if position == 0:
            _set_header_name(by_id[feature_id], story_name)
            result.append(feature_id)
            continue
        new_id = _unique_id(f"feat-{_slug(story_name)}", existing)
        existing.add(new_id)
        doc.blocks.insert(
            insert_at,
            RawBlock(
                block_id=new_id,
                block_type="feature",
                parent=None,
                depends=(),
                lines=[
                    f"## feature {_next_ordinal(doc)}: {story_name}",
                    f"id: {new_id}",
                    f"summary: {story_name}",
                    "state: pending",
                ],
            ),
        )
        insert_at += 1
        _set_parent_line(step, new_id)
        result.append(new_id)
    doc.blocks[:] = _flatten(doc)
    _require_unique_ids(doc)
    _reject_if_worsened(doc, before)
    return result


def split_step(doc: ManifestDoc, step_id: str) -> str:
    """Move one story out of its group into a new feature named after the story.

    The new feature is inserted immediately above the story's current feature, or
    immediately below it when above would break build order. Returns the new
    feature's id.
    """
    by_id = doc.by_id()
    step = by_id.get(step_id)
    if step is None or step.block_type not in _STEP_TYPES:
        raise SpecificationError(f"{step_id} is not a movable step")
    old_feature_id = step.parent if _is_feature(doc, step.parent) else None
    before = validate_order(doc.blocks)
    header = _HEADER_RE.match(step.lines[0]) if step.lines else None
    story_name = header.group(3) if header else step_id
    existing = {b.block_id for b in doc.blocks}
    new_id = _unique_id(f"feat-{_slug(story_name)}", existing)
    ordinal = _next_ordinal(doc)

    saved_blocks = list(doc.blocks)
    saved_lines = list(step.lines)
    anchor = (
        next(i for i, b in enumerate(saved_blocks) if b.block_id == old_feature_id)
        if old_feature_id
        else len(saved_blocks)
    )

    def attempt(position: int) -> bool:
        doc.blocks[:] = list(saved_blocks)
        step.lines = list(saved_lines)
        doc.blocks.insert(
            position,
            RawBlock(
                block_id=new_id,
                block_type="feature",
                parent=None,
                depends=(),
                lines=[
                    f"## feature {ordinal}: {story_name}",
                    f"id: {new_id}",
                    f"summary: {story_name}",
                    "state: pending",
                ],
            ),
        )
        _set_parent_line(step, new_id)
        doc.blocks[:] = _flatten(doc)
        try:
            _reject_if_worsened(doc, before)
            return True
        except SpecificationError:
            return False

    if attempt(anchor) or attempt(anchor + 1):
        return new_id

    doc.blocks[:] = saved_blocks
    step.lines = saved_lines
    raise SpecificationError(
        f"Splitting {step_id} into its own group would break the build order "
        "whether placed above or below its current group."
    )


def normalize_order(doc: ManifestDoc) -> None:
    """Reorder feature groups and split mixed stack-kind groups.

    A stable normalization offered when a manifest is out of band order: groups
    keep their relative order within a band and are sorted so Foundation precedes
    Data/Persistence precedes the implementation band. A feature group that mixes
    feature/service, screen, foundation, data, or other work is split into
    contiguous single-kind groups first, preserving the existing story order.
    """
    _isolate_failed_steps(doc)
    _split_mixed_work_kind_groups(doc)
    _roll_up_feature_states(doc)
    by_id = doc.by_id()
    steps_by_feature = _steps_by_feature(doc)
    feature_order = _feature_order(doc)
    index_of = {fid: i for i, fid in enumerate(feature_order)}

    def feature_band(fid: str) -> int:
        bands = [_raw_band(by_id[sid]) for sid in steps_by_feature.get(fid, [])]
        return min(bands) if bands else BAND_FOUNDATION + 2

    ordered = sorted(feature_order, key=lambda fid: (feature_band(fid), index_of[fid]))
    features = [by_id[fid] for fid in ordered]
    others = [block for block in doc.blocks if block.block_type != "feature"]
    doc.blocks[:] = features + others
    doc.blocks[:] = _flatten(doc)


_WORK_KIND_LABELS = {
    "foundation": "Foundation",
    "data": "Data",
    "feature": "Features",
    "screen": "Screens",
    "other": "Work",
}


def _block_header_name(block: RawBlock) -> str:
    match = _HEADER_RE.match(block.lines[0]) if block.lines else None
    return match.group(3).strip() if match else block.block_id


def _split_mixed_work_kind_groups(doc: ManifestDoc) -> None:
    """Split any feature group containing multiple contiguous work-kind runs."""
    by_id = doc.by_id()
    existing = {block.block_id for block in doc.blocks}

    for feature_id in list(_feature_order(doc)):
        steps = _steps_by_feature(doc).get(feature_id, [])
        if len(steps) < 2:
            continue
        runs: list[tuple[str, list[str]]] = []
        for step_id in steps:
            kind = _raw_work_kind(by_id[step_id])
            if runs and runs[-1][0] == kind:
                runs[-1][1].append(step_id)
            else:
                runs.append((kind, [step_id]))
        if len(runs) < 2:
            continue

        feature = by_id[feature_id]
        base_name = _block_header_name(feature)
        insert_at = next(i for i, b in enumerate(doc.blocks) if b.block_id == feature_id) + 1
        for kind, run_steps in runs[1:]:
            label = _WORK_KIND_LABELS.get(kind, "Work")
            new_name = f"{base_name} {label}"
            new_id = _unique_id(f"{feature_id}-{kind}", existing)
            existing.add(new_id)
            doc.blocks.insert(
                insert_at,
                RawBlock(
                    block_id=new_id,
                    block_type="feature",
                    parent=None,
                    depends=(),
                    lines=[
                        f"## feature {_next_ordinal(doc)}: {new_name}",
                        f"id: {new_id}",
                        f"summary: {new_name}",
                        "state: pending",
                    ],
                ),
            )
            insert_at += 1
            for step_id in run_steps:
                _set_parent_line(by_id[step_id], new_id)

    _require_unique_ids(doc)
    doc.blocks[:] = _flatten(doc)


def _isolate_failed_steps(doc: ManifestDoc) -> None:
    """Move failed executable steps into their own retry feature blocks."""
    by_id = doc.by_id()
    existing = {block.block_id for block in doc.blocks}

    for feature_id in list(_feature_order(doc)):
        steps = _steps_by_feature(doc).get(feature_id, [])
        if len(steps) < 2:
            continue
        runs: list[list[str]] = []
        for step_id in steps:
            state = _scan_field(by_id[step_id].lines, "state") or "pending"
            if state == "closed/failed":
                runs.append([step_id])
            elif runs and all(
                (_scan_field(by_id[existing_step].lines, "state") or "pending") != "closed/failed"
                for existing_step in runs[-1]
            ):
                runs[-1].append(step_id)
            else:
                runs.append([step_id])
        if len(runs) < 2:
            continue

        feature = by_id[feature_id]
        insert_at = next(i for i, b in enumerate(doc.blocks) if b.block_id == feature_id) + 1
        for run in runs[1:]:
            first_step = by_id[run[0]]
            first_state = _scan_field(first_step.lines, "state") or "pending"
            if len(run) == 1 and first_state == "closed/failed":
                new_name = f"{_block_header_name(first_step)} Retry"
                new_id = _unique_id(f"retry-{first_step.block_id}", existing)
            else:
                new_name = f"{_block_header_name(feature)} Continued"
                new_id = _unique_id(f"{feature_id}-continued", existing)
            existing.add(new_id)
            doc.blocks.insert(
                insert_at,
                RawBlock(
                    block_id=new_id,
                    block_type="feature",
                    parent=None,
                    depends=(),
                    lines=[
                        f"## feature {_next_ordinal(doc)}: {new_name}",
                        f"id: {new_id}",
                        f"summary: {new_name}",
                        "state: pending",
                    ],
                ),
            )
            insert_at += 1
            for step_id in run:
                _set_parent_line(by_id[step_id], new_id)

    _require_unique_ids(doc)
    doc.blocks[:] = _flatten(doc)


def _roll_up_feature_states(doc: ManifestDoc) -> None:
    """Keep feature block state coherent with its executable child stories."""
    by_id = doc.by_id()
    for feature_id, step_ids in _steps_by_feature(doc).items():
        if feature_id is None or feature_id not in by_id or not step_ids:
            continue
        feature = by_id[feature_id]
        child_states = [
            _scan_field(by_id[step_id].lines, "state") or "pending" for step_id in step_ids
        ]
        if any(state == "closed/failed" for state in child_states):
            failed_id = next(
                step_id
                for step_id, state in zip(step_ids, child_states)
                if state == "closed/failed"
            )
            failed = by_id[failed_id]
            _set_field_line(feature, "state", "closed/failed")
            _set_field_line(
                feature,
                "finding",
                _scan_field(failed.lines, "finding") or _scan_field(feature.lines, "finding"),
            )
            _set_field_line(
                feature,
                "evidence",
                _scan_field(failed.lines, "evidence") or _scan_field(feature.lines, "evidence"),
            )
        elif all(state == "closed/verified" for state in child_states):
            first = by_id[step_ids[0]]
            _set_field_line(feature, "state", "closed/verified")
            _set_field_line(
                feature,
                "evidence",
                _scan_field(first.lines, "evidence") or _scan_field(feature.lines, "evidence"),
            )


# ── Serialization ────────────────────────────────────────────────────────────


def render_manifest(doc: ManifestDoc) -> str:
    """Render the document back to MANIFEST.md text with one blank between blocks."""
    parts: list[str] = []
    preamble = list(doc.preamble)
    while preamble and not preamble[-1].strip():
        preamble.pop()
    if preamble:
        parts.append("\n".join(preamble))
    for block in doc.blocks:
        body = list(block.lines)
        while body and not body[-1].strip():
            body.pop()
        parts.append("\n".join(body))
    return "\n\n".join(parts) + "\n"


def write_manifest(doc: ManifestDoc) -> None:
    """Atomically write the document back to its path."""
    text = render_manifest(doc)
    doc.path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=doc.path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(doc.path)


def _set_field_line(block: RawBlock, key: str, value: str | None) -> None:
    """Rewrite, insert, or delete a scalar field line on a block."""
    kept: list[str] = []
    replaced = False
    for line in block.lines:
        match = _FIELD_LINE_RE.match(line)
        if match and match.group(1).lower() == key:
            if value is not None:
                kept.append(f"{key}: {value}")
            replaced = True
            continue
        kept.append(line)
    if value is not None and not replaced:
        insert_at = 1
        for i, line in enumerate(kept):
            match = _FIELD_LINE_RE.match(line)
            if match and match.group(1).lower() == "id":
                insert_at = i + 1
                break
        kept.insert(insert_at, f"{key}: {value}")
    block.lines = kept


def set_block_fields(path: Path, block_id: str, **fields: str | None) -> None:
    """Decision writer: set scalar fields on one block and rewrite MANIFEST.md.

    The single mutator for per-block state transitions (``state``, ``evidence``,
    ``finding``). Block ordering and all other content are preserved verbatim.
    """
    doc = split_manifest(path)
    block = doc.by_id().get(block_id)
    if block is None:
        raise SpecificationError(f"Block {block_id!r} not found in {path}")
    for key, value in fields.items():
        _set_field_line(block, key.lower(), value)
    write_manifest(doc)


def batch_set_block_fields(path: Path, updates: dict[str, dict[str, str | None]]) -> None:
    """Set scalar fields on multiple blocks in a single parse-and-write cycle.

    ``updates`` maps block_id → {field_name → value}. Blocks not present in the
    manifest are silently skipped. Preserves block ordering and all other content.
    """
    if not updates:
        return
    doc = split_manifest(path)
    by_id = doc.by_id()
    for block_id, fields in updates.items():
        block = by_id.get(block_id)
        if block is None:
            continue
        for key, value in fields.items():
            _set_field_line(block, key.lower(), value)
    write_manifest(doc)


def apply_move(
    path: Path, kind: str, block_id: str, *, direction: str = "", feature: str = ""
) -> None:
    """Load, apply one constrained move, validate, and write MANIFEST.md.

    ``kind`` is ``move_step``, ``move_feature``, or ``regroup_step``. Raises
    SpecificationError (without writing) if the move is illegal or breaks topology.
    """
    doc = split_manifest(path)
    if kind == "move_step":
        move_step(doc, block_id, direction)
    elif kind == "move_feature":
        move_feature(doc, block_id, direction)
    elif kind == "regroup_step":
        regroup_step(doc, block_id, feature or None)
    else:
        raise SpecificationError(f"Unknown move kind {kind!r}")
    write_manifest(doc)


def apply_edit(path: Path, kind: str, *, block_id: str = "", name: str = "") -> dict[str, object]:
    """Load, apply one structure edit, validate, and write MANIFEST.md.

    ``kind`` is ``rename`` (a feature or step, by ``block_id`` and ``name``),
    ``add_feature`` (a new empty group named ``name``), ``split_group`` (the
    feature ``block_id`` into one group per story), ``split_step`` (the story
    ``block_id`` into its own new group), or ``normalize`` (reorder all groups
    into canonical layer-band order). Raises SpecificationError (without writing)
    if the edit is illegal.
    """
    doc = split_manifest(path)
    result: dict[str, object] = {}
    if kind == "rename":
        rename_block(doc, block_id, name)
    elif kind == "add_feature":
        result["feature_id"] = add_feature(doc, name)
    elif kind == "split_group":
        result["features"] = split_group(doc, block_id)
    elif kind == "split_step":
        result["feature_id"] = split_step(doc, block_id)
    elif kind == "normalize":
        normalize_order(doc)
    else:
        raise SpecificationError(f"Unknown edit kind {kind!r}")
    write_manifest(doc)
    return result
