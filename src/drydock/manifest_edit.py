"""Constrained reorder/regroup editing of MANIFEST.md.

The QuarterDeck build compass lets the product owner reorder build steps and move
them between features. Edits are constrained: a move that would break the work
graph's topology — a step placed before one of its ``depends:``, or an acceptance
check before its parent — is rejected, so the displayed order is always a legal
build order. ``depends:`` still governs actual execution; this editing only sets
the preferred order and grouping the compass shows and the build walks.

The writer preserves each block's source lines verbatim (including ``|`` block
scalars); it only reorders blocks and rewrites a moved step's ``parent:`` line.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

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


def validate_order(blocks: list[RawBlock]) -> list[str]:
    """Return topology violations for a flattened block order; empty means valid.

    A block's ``depends:`` ids and an ac's parent must all appear before it.
    """
    errors: list[str] = []
    seen: set[str] = set()
    ids = {b.block_id for b in blocks}
    for block in blocks:
        for dep in block.depends:
            if dep in ids and dep not in seen:
                errors.append(f"{block.block_id} is ordered before its dependency {dep}")
        if block.block_type == "ac" and block.parent and block.parent in ids:
            if block.parent not in seen:
                errors.append(f"acceptance {block.block_id} is ordered before its parent {block.parent}")
        seen.add(block.block_id)
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
    siblings = _steps_by_feature(doc)[block.parent if _is_feature(doc, block.parent) else None]
    other = _neighbor(siblings, step_id, direction)
    _swap_block_positions(doc, step_id, other)
    _reject_if_invalid(doc)


def move_feature(doc: ManifestDoc, feature_id: str, direction: str) -> None:
    """Move a feature group earlier/later among the features."""
    block = doc.by_id().get(feature_id)
    if block is None or block.block_type != "feature":
        raise SpecificationError(f"{feature_id} is not a feature")
    if direction not in ("up", "down"):
        raise SpecificationError(f"Invalid direction {direction!r}")
    order = _feature_order(doc)
    other = _neighbor(order, feature_id, direction)
    _swap_block_positions(doc, feature_id, other)
    _reject_if_invalid(doc)


def regroup_step(doc: ManifestDoc, step_id: str, feature_id: str | None) -> None:
    """Move a step into another feature (or out of all features)."""
    block = doc.by_id().get(step_id)
    if block is None or block.block_type not in _STEP_TYPES:
        raise SpecificationError(f"{step_id} is not a movable step")
    if feature_id and not _is_feature(doc, feature_id):
        raise SpecificationError(f"{feature_id} is not a feature")
    _set_parent_line(block, feature_id)
    doc.blocks[:] = _flatten(doc)
    _reject_if_invalid(doc)


def _is_feature(doc: ManifestDoc, block_id: str | None) -> bool:
    if not block_id:
        return False
    block = doc.by_id().get(block_id)
    return block is not None and block.block_type == "feature"


def _reject_if_invalid(doc: ManifestDoc) -> None:
    errors = validate_order(doc.blocks)
    if errors:
        raise SpecificationError(
            "Move rejected; it would break the build topology:\n  - " + "\n  - ".join(errors)
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


def apply_move(path: Path, kind: str, block_id: str, *, direction: str = "", feature: str = "") -> None:
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
