"""Parse and inspect the canonical Drydock BUILD_PLAN.md format."""

from __future__ import annotations

import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from drydock.errors import SpecificationError

BLOCK_TYPES = ("feature", "story", "spike", "ac")
STATES = ("pending", "implemented", "closed/verified", "closed/failed")
PLAN_STATES = ("draft", "approved", "closed")
SCOPES = ("blueprint", "target", "both")

_HEADER_RE = re.compile(r"^##\s+(feature|story|spike|ac)\s+(\d+):\s*(.+?)\s*$")
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
    scope: str | None = None
    fields: dict[str, str | tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class BuildPlan:
    path: Path
    project: str
    updated: str
    plan_hash: str
    state: str
    blocks: tuple[PlanBlock, ...]

    def by_id(self) -> dict[str, PlanBlock]:
        return {block.block_id: block for block in self.blocks}

    def state_counts(self) -> Counter[str]:
        return Counter(block.state for block in self.blocks)

    def runnable_frontier(self) -> tuple[PlanBlock, ...]:
        if self.state != "approved":
            return ()
        by_id = self.by_id()

        def verified(block_id: str) -> bool:
            dependency = by_id.get(block_id)
            return dependency is not None and dependency.state == "closed/verified"

        runnable = []
        for block in self.blocks:
            if block.block_type == "feature":
                continue
            if block.state != "pending" or not all(verified(dep) for dep in block.depends):
                continue
            if block.block_type == "ac":
                parent = by_id.get(block.parent or "")
                if parent is None:
                    continue
                if parent.block_type == "feature":
                    feature_work = tuple(
                        child
                        for child in self.children(parent.block_id)
                        if child.block_type != "ac"
                    )
                    if not feature_work or not all(
                        child.state == "closed/verified" for child in feature_work
                    ):
                        continue
                elif parent.state != "implemented":
                    continue
            runnable.append(block)
        return tuple(runnable)

    def children(self, parent_id: str) -> tuple[PlanBlock, ...]:
        return tuple(block for block in self.blocks if block.parent == parent_id)

    def closable_features(self) -> tuple[PlanBlock, ...]:
        closable = []
        for block in self.blocks:
            if block.block_type != "feature" or block.state not in {"pending", "implemented"}:
                continue
            children = self.children(block.block_id)
            if children and all(child.state == "closed/verified" for child in children):
                closable.append(block)
        return tuple(closable)


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
    scope = str(fields.get("scope", "")).strip() or None

    if not block_id:
        raise SpecificationError(f"Missing id for {block_type} {number} in {path}")
    if state not in STATES:
        raise SpecificationError(
            f"Invalid state {state!r} for {block_id} in {path}; expected one of: {', '.join(STATES)}"
        )
    if block_type == "ac" and not parent:
        raise SpecificationError(f"Missing parent for ac block {block_id} in {path}")
    if scope is not None and scope not in SCOPES:
        raise SpecificationError(
            f"Invalid scope {scope!r} for {block_id} in {path}; expected one of: {', '.join(SCOPES)}"
        )
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
        scope=scope,
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
    plan_state = metadata.get("state", "approved")
    if plan_state not in PLAN_STATES:
        raise SpecificationError(
            f"Invalid plan state {plan_state!r} in {path}; expected one of: {', '.join(PLAN_STATES)}"
        )
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
        state=plan_state,
        blocks=blocks,
    )


def load_target_plan(target: str, target_directory: Path) -> BuildPlan:
    """Load the canonical executable plan for a configured Target name."""
    return parse_build_plan(target_directory / target / "BUILD_PLAN.md")


def set_plan_state(path: Path, state: str, *, feedback: str = "", decision: str = "") -> BuildPlan:
    """Atomically apply a Planning Session decision to a BUILD_PLAN.md."""
    if state not in PLAN_STATES:
        raise SpecificationError(f"Invalid plan state {state!r}")
    if not path.is_file():
        raise SpecificationError(f"BUILD_PLAN.md not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    updated = datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017
    replacements = {"state": state, "updated": updated}
    if feedback:
        replacements["planning_feedback"] = feedback.replace("\n", " ").strip()
    if decision:
        replacements["planning_decision"] = decision

    output: list[str] = []
    seen: set[str] = set()
    first_block = next((i for i, line in enumerate(lines) if _HEADER_RE.match(line)), len(lines))
    for index, line in enumerate(lines):
        if index < first_block:
            field_match = _FIELD_RE.match(line)
            if field_match:
                key = field_match.group(1).lower()
                if key in replacements:
                    output.append(f"{key}: {replacements[key]}")
                    seen.add(key)
                    continue
        output.append(line)

    insert_at = next((i for i, line in enumerate(output) if _HEADER_RE.match(line)), len(output))
    missing = [f"{key}: {value}" for key, value in replacements.items() if key not in seen]
    if missing:
        output[insert_at:insert_at] = missing + [""]

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write("\n".join(output).rstrip() + "\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)
    return parse_build_plan(path)
