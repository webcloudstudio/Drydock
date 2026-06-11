"""Parse and inspect the canonical Drydock BUILD_PLAN.md format."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import SpecificationError

BLOCK_TYPES = ("story", "spike", "ac")
STATES = ("pending", "implemented", "closed/verified", "closed/failed")

_HEADER_RE = re.compile(r"^##\s+(story|spike|ac)\s+(\d+):\s*(.+?)\s*$")
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")
_PLAN_HEADER_RE = re.compile(r"^#\s+BUILD_PLAN:\s*(.+?)\s*$")
_LIST_FIELDS = {"depends", "implements", "context", "stack", "rules"}


@dataclass(frozen=True)
class PlanBlock:
    block_type: str
    number: int
    name: str
    block_id: str
    state: str
    parent: str | None = None
    depends: tuple[str, ...] = ()
    fields: dict[str, str | tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class BuildPlan:
    path: Path
    project: str
    updated: str
    plan_hash: str
    blocks: tuple[PlanBlock, ...]

    def by_id(self) -> dict[str, PlanBlock]:
        return {block.block_id: block for block in self.blocks}

    def state_counts(self) -> Counter[str]:
        return Counter(block.state for block in self.blocks)

    def runnable_frontier(self) -> tuple[PlanBlock, ...]:
        by_id = self.by_id()

        def verified(block_id: str) -> bool:
            dependency = by_id.get(block_id)
            return dependency is not None and dependency.state == "closed/verified"

        runnable = []
        for block in self.blocks:
            if block.state != "pending" or not all(verified(dep) for dep in block.depends):
                continue
            if block.block_type == "ac":
                parent = by_id.get(block.parent or "")
                if parent is None or parent.state != "implemented":
                    continue
            runnable.append(block)
        return tuple(runnable)


def _split_list(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_block(raw: dict[str, object], path: Path) -> PlanBlock:
    fields = raw["fields"]
    assert isinstance(fields, dict)

    block_type = str(raw["block_type"])
    number = int(raw["number"])
    name = str(raw["name"])
    block_id = str(fields.get("id", "")).strip()
    state = str(fields.get("state", "pending")).strip()
    parent = str(fields.get("parent", "")).strip() or None
    depends = fields.get("depends", ())

    if not block_id:
        raise SpecificationError(f"Missing id for {block_type} {number} in {path}")
    if state not in STATES:
        raise SpecificationError(
            f"Invalid state {state!r} for {block_id} in {path}; expected one of: {', '.join(STATES)}"
        )
    if block_type == "ac" and not parent:
        raise SpecificationError(f"Missing parent for ac block {block_id} in {path}")
    if not isinstance(depends, tuple):
        depends = ()

    return PlanBlock(
        block_type=block_type,
        number=number,
        name=name,
        block_id=block_id,
        state=state,
        parent=parent,
        depends=depends,
        fields=dict(fields),
    )


def parse_build_plan(path: Path) -> BuildPlan:
    """Parse one BUILD_PLAN.md and validate its structural execution contract."""
    if not path.is_file():
        raise SpecificationError(f"BUILD_PLAN.md not found: {path}\n  Run: drydock plan create")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SpecificationError(f"Cannot read {path}: {exc}") from exc

    project = ""
    metadata: dict[str, str] = {}
    raw_blocks: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in lines:
        header = _PLAN_HEADER_RE.match(line)
        if header and not project:
            project = header.group(1)
            continue

        block_header = _HEADER_RE.match(line)
        if block_header:
            current = {
                "block_type": block_header.group(1),
                "number": int(block_header.group(2)),
                "name": block_header.group(3),
                "fields": {},
            }
            raw_blocks.append(current)
            continue

        field_match = _FIELD_RE.match(line)
        if not field_match:
            continue
        key, value = field_match.group(1).lower(), field_match.group(2).strip()
        if current is None:
            metadata[key] = value
        else:
            fields = current["fields"]
            assert isinstance(fields, dict)
            fields[key] = _split_list(value) if key in _LIST_FIELDS else value

    if not project:
        raise SpecificationError(f"Missing '# BUILD_PLAN: <ProjectName>' header in {path}")

    blocks = tuple(_parse_block(raw, path) for raw in raw_blocks)
    seen: set[str] = set()
    for block in blocks:
        if block.block_id in seen:
            raise SpecificationError(f"Duplicate block id {block.block_id!r} in {path}")
        seen.add(block.block_id)

    return BuildPlan(
        path=path,
        project=project,
        updated=metadata.get("updated", ""),
        plan_hash=metadata.get("plan_hash", ""),
        blocks=blocks,
    )


def load_blueprint_plan(blueprint: str, blueprint_directory: Path) -> BuildPlan:
    """Load the canonical plan for a configured Blueprint name."""
    return parse_build_plan(blueprint_directory / blueprint / "BUILD_PLAN.md")
