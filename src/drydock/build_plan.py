"""Parse and inspect the canonical Drydock MANIFEST.md format."""

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
_PLAN_HEADER_RE = re.compile(r"^#\s+MANIFEST:\s*(.+?)\s*$")
_LIST_FIELDS = {"depends", "implements", "context", "stack", "rules"}
# Compact single-line ac form: "## ac N: Summary (smoke|assertion: check)".
# The check is greedy to the final ')' so embedded parens (e.g. json.load(x)) survive.
_COMPACT_AC_RE = re.compile(
    r"^(?P<summary>.*?)\s*\((?P<kind>smoke|assertion):\s*(?P<check>.*)\)\s*$"
)


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
class AppliedSpecRecord:
    path: str
    sha256: str
    commit: str
    applied_by: str
    applied_at: str


@dataclass(frozen=True)
class BuildPlan:
    path: Path
    project: str
    updated: str
    plan_hash: str
    state: str
    blocks: tuple[PlanBlock, ...]
    applied_registry: dict[str, str] = field(default_factory=dict)
    applied_specs: dict[str, AppliedSpecRecord] = field(default_factory=dict)

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

    def buildable_steps(self) -> tuple[PlanBlock, ...]:
        """Story/spike blocks ready to build now: pending with verified depends.

        Running ``drydock build`` is the approval, so this is not gated by plan
        state; ``depends:`` and block state alone determine readiness.
        """
        by_id = self.by_id()

        def verified(block_id: str) -> bool:
            dependency = by_id.get(block_id)
            return dependency is not None and dependency.state == "closed/verified"

        return tuple(
            block
            for block in self.blocks
            if block.block_type in ("story", "spike")
            and block.state == "pending"
            and all(verified(dep) for dep in block.depends)
        )

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


def _parse_applied_registry(text: str) -> dict[str, str]:
    """Parse ``name=commit,name=commit`` applied registry from the manifest preamble."""
    result: dict[str, str] = {}
    for entry in text.split(","):
        entry = entry.strip()
        if "=" in entry:
            name, _, commit = entry.partition("=")
            name, commit = name.strip(), commit.strip()
            if name and commit:
                result[name] = commit
    return result


def _format_applied_registry(registry: dict[str, str]) -> str:
    """Serialize applied registry to ``name=commit,name=commit`` form."""
    return ",".join(f"{k}={v}" for k, v in sorted(registry.items()))


def _parse_kv_tokens(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in text.split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        if key and value:
            values[key] = value
    return values


def _parse_applied_specs(text: str) -> dict[str, AppliedSpecRecord]:
    """Parse the Manifest ``applied_specs`` block-scalar registry."""
    records: dict[str, AppliedSpecRecord] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        path, _, rest = line.partition(" ")
        values = _parse_kv_tokens(rest)
        digest = values.get("sha256", "")
        applied_by = values.get("applied_by", "")
        applied_at = values.get("applied_at", "")
        if not path or not digest or not applied_by or not applied_at:
            continue
        records[path] = AppliedSpecRecord(
            path=path,
            sha256=digest,
            commit=values.get("commit", "-") or "-",
            applied_by=applied_by,
            applied_at=applied_at,
        )
    return records


def _format_applied_specs(records: dict[str, AppliedSpecRecord]) -> str:
    """Serialize applied specification records in stable Manifest order."""
    lines: list[str] = []
    for path in sorted(records):
        record = records[path]
        lines.append(
            f"{record.path} sha256={record.sha256} commit={record.commit or '-'} "
            f"applied_by={record.applied_by} applied_at={record.applied_at}"
        )
    return "\n".join(lines)


def _collect_block_scalar(lines: list[str], start: int) -> tuple[str, int]:
    """Collect an indented YAML block-scalar body starting at ``start``.

    Continuation lines are blank lines or lines indented past column zero, up to
    the next field, header, or dedented line. Returns the dedented body text and
    the index of the first line that is not part of the block.
    """
    body: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if line.strip() and not line[:1].isspace():
            break
        body.append(line)
        index += 1
    while body and not body[-1].strip():
        body.pop()
    indents = [len(ln) - len(ln.lstrip()) for ln in body if ln.strip()]
    trim = min(indents) if indents else 0
    text = "\n".join(ln[trim:] if ln.strip() else "" for ln in body)
    return text, index


def _split_depends(value: str) -> tuple[str, ...]:
    """Accept comma-separated or whitespace-separated manifest dependencies."""
    if "," in value:
        return _split_list(value)
    return tuple(item for item in value.split() if item)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "ac"


def _normalize_compact_acs(raw_blocks: list[dict[str, object]]) -> None:
    """Expand compact one-line ``ac`` headers into the canonical field body.

    The planning LLM may emit ``## ac N: Summary (kind: check)`` with no field
    body. Each such block inherits its ``parent`` from the nearest preceding
    non-``ac`` block (so a run of compact ACs gates the same story), derives a
    unique ``id`` slug from the summary, and pulls ``kind``/``check`` from the
    parenthetical. Blocks that already carry an ``id`` are left untouched.
    """
    seen_ids = {
        str(raw["fields"].get("id", "")).strip()  # type: ignore[union-attr]
        for raw in raw_blocks
        if str(raw["fields"].get("id", "")).strip()  # type: ignore[union-attr]
    }
    last_parent: str | None = None
    for raw in raw_blocks:
        fields = raw["fields"]
        assert isinstance(fields, dict)
        block_type = str(raw["block_type"])
        existing_id = str(fields.get("id", "")).strip()

        if block_type != "ac":
            if existing_id:
                last_parent = existing_id
            continue

        if existing_id:
            parent = str(fields.get("parent", "")).strip()
            if parent:
                last_parent = parent
            continue

        match = _COMPACT_AC_RE.match(str(raw["name"]))
        if not match:
            continue  # leave malformed; _parse_block raises the existing error

        summary = match.group("summary").strip()
        candidate = _slugify(summary)
        unique = candidate
        suffix = 2
        while unique in seen_ids:
            unique = f"{candidate}-{suffix}"
            suffix += 1
        seen_ids.add(unique)

        fields["id"] = unique
        fields.setdefault("summary", summary)
        fields["kind"] = match.group("kind")
        check = match.group("check").strip()
        if check:
            fields["check"] = check
        fields.setdefault("state", "pending")
        if last_parent and not fields.get("parent"):
            fields["parent"] = last_parent
        raw["name"] = summary


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
    """Parse one MANIFEST.md and validate its structural execution contract."""
    if not path.is_file():
        raise SpecificationError(f"MANIFEST.md not found: {path}\n  Run: drydock plan")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SpecificationError(f"Cannot read {path}: {exc}") from exc

    project = ""
    metadata: dict[str, str] = {}
    raw_blocks: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1

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

        if value in ("|", "|-", "|+", ">", ">-", ">+"):
            block_lines, index = _collect_block_scalar(lines, index)
            value = block_lines

        if current is None:
            metadata[key] = value
        else:
            fields = current["fields"]
            assert isinstance(fields, dict)
            if key == "depends":
                fields[key] = _split_depends(value)
            elif key in _LIST_FIELDS:
                fields[key] = _split_list(value)
            else:
                fields[key] = value

    if not project:
        raise SpecificationError(f"Missing '# MANIFEST: <ProjectName>' header in {path}")

    _normalize_compact_acs(raw_blocks)
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
        applied_registry=_parse_applied_registry(metadata.get("applied", "")),
        applied_specs=_parse_applied_specs(metadata.get("applied_specs", "")),
    )


@dataclass(frozen=True)
class CompactRecommendation:
    file: str
    implements_count: int
    context_count: int


def compact_recommendations(plan: BuildPlan, *, threshold: int = 2) -> list[CompactRecommendation]:
    """Return files whose context: reference count meets the compaction threshold.

    Break-even: 1 builder + 2 context refs = 3C without compaction vs ~2C with it.
    Files meeting threshold are sorted by context_count descending.
    """
    implements_counts: Counter[str] = Counter()
    context_counts: Counter[str] = Counter()

    for block in plan.blocks:
        for f in block.fields.get("implements", ()):
            implements_counts[str(f)] += 1
        for f in block.fields.get("context", ()):
            context_counts[str(f)] += 1

    recs: list[CompactRecommendation] = []
    for f in sorted(context_counts):
        c_count = context_counts[f]
        if c_count >= threshold:
            recs.append(
                CompactRecommendation(
                    file=f,
                    implements_count=implements_counts[f],
                    context_count=c_count,
                )
            )
    recs.sort(key=lambda r: r.context_count, reverse=True)
    return recs


def load_target_plan(target: str, target_directory: Path) -> BuildPlan:
    """Load the canonical executable plan for a configured Target name."""
    return parse_build_plan(target_directory / target / "MANIFEST.md")


def set_applied_registry(path: Path, registry: dict[str, str]) -> None:
    """Write the applied stack-file registry to the MANIFEST.md preamble.

    Adds or replaces the ``applied:`` field before the first block header.
    Preserves all other preamble content verbatim.
    """
    if not path.is_file():
        raise SpecificationError(f"MANIFEST.md not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    value = _format_applied_registry(registry)
    output: list[str] = []
    replaced = False
    first_block = next((i for i, line in enumerate(lines) if _HEADER_RE.match(line)), len(lines))
    for index, line in enumerate(lines):
        if index < first_block:
            field_match = _FIELD_RE.match(line)
            if field_match and field_match.group(1).lower() == "applied":
                output.append(f"applied: {value}")
                replaced = True
                continue
        output.append(line)
    if not replaced:
        insert_at = next(
            (i for i, line in enumerate(output) if _HEADER_RE.match(line)), len(output)
        )
        output.insert(insert_at, f"applied: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write("\n".join(output).rstrip() + "\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def set_applied_specs(path: Path, records: dict[str, AppliedSpecRecord]) -> None:
    """Write Blueprint specification provenance to the MANIFEST.md preamble."""
    if not path.is_file():
        raise SpecificationError(f"MANIFEST.md not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    value = _format_applied_specs(records)
    output: list[str] = []
    replaced = False
    skip_scalar = False
    first_block = next((i for i, line in enumerate(lines) if _HEADER_RE.match(line)), len(lines))

    for index, line in enumerate(lines):
        if skip_scalar:
            if index < first_block and (not line.strip() or line[:1].isspace()):
                continue
            skip_scalar = False
        if index < first_block:
            field_match = _FIELD_RE.match(line)
            if field_match and field_match.group(1).lower() == "applied_specs":
                output.append("applied_specs: |")
                output.extend(f"  {record_line}" for record_line in value.splitlines())
                replaced = True
                if field_match.group(2).strip() in ("|", "|-", "|+", ">", ">-", ">+"):
                    skip_scalar = True
                continue
        output.append(line)

    if not replaced:
        insert_at = next(
            (i for i, line in enumerate(output) if _HEADER_RE.match(line)), len(output)
        )
        insertion = ["applied_specs: |"]
        insertion.extend(f"  {record_line}" for record_line in value.splitlines())
        output[insert_at:insert_at] = insertion

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write("\n".join(output).rstrip() + "\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def set_plan_state(path: Path, state: str, *, feedback: str = "", decision: str = "") -> BuildPlan:
    """Atomically apply a Planning Session decision to a MANIFEST.md."""
    if state not in PLAN_STATES:
        raise SpecificationError(f"Invalid plan state {state!r}")
    if not path.is_file():
        raise SpecificationError(f"MANIFEST.md not found: {path}")

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
