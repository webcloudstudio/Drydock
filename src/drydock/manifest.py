"""Typed, lossless graph model for ``MANIFEST.md``.

The public model deliberately combines the execution view formerly exposed by
``build_plan`` with the source-preserving view formerly exposed by
``manifest_edit``.  A Manifest is parsed and validated once, changed in memory,
and atomically saved once.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import SpecificationError

logger = logging.getLogger(__name__)

BLOCK_TYPES = ("feature", "story", "spike", "ac")
STATES = ("pending", "blocked/questions", "implemented", "closed/verified", "closed/failed")
PLAN_STATES = ("draft", "approved", "closed")
SCOPES = ("blueprint", "target", "both")
AC_KINDS = ("smoke", "assertion")

_HEADER_RE = re.compile(r"^##\s+(feature|story|spike|ac)\s+(\d+):\s*(.*?)\s*$")
_LOOSE_HEADER_RE = re.compile(r"^##\s+(\S+)(?:\s+(\S+))?(?::\s*(.*))?$")
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")
_PLAN_HEADER_RE = re.compile(r"^#\s+MANIFEST:\s*(.+?)\s*$")
_COMPACT_AC_RE = re.compile(
    r"^(?P<summary>.*?)\s*\((?P<kind>smoke|assertion):\s*(?P<check>.*)\)\s*$"
)
_LIST_FIELDS = frozenset({
    "depends",
    "implements",
    "context",
    "stack",
    "rules",
    "accepts",
    "covers",
})
#: Interface lists are comma-separated only: a route such as ``GET /health`` contains a space, so
#: the whitespace fallback used for filename lists would split one entry into two.
_INTERFACE_FIELDS = frozenset({"provides", "consumes"})

#: Story types. The Manifest is a list of stories; ``type`` is the only variation. See
#: :mod:`drydock.plan_graph` for the authoritative definitions. ``spike`` is retired as a node
#: type: research questions are handled by questionnaires before Plan and by the owning story's
#: ``## Questions`` section after. ``ac`` is not a node type — Programmatic Acceptance is
#: verification the build runs to prove a story is complete, so it is a field the story owns and
#: passing is part of the story's own state transition.
STORY_TYPES = ("foundational", "service", "feature")

#: Story fields computed by Zone C. They describe the *schedule*, not the artifact, so they live
#: only in the Manifest and are regenerated wholly by every plan run.
_SCHEDULE_FIELDS = (
    "type",
    "kind",
    "phase",
    "block",
    "stack_mode",
    "size",
    "budget",
    "acceptance",
)
_SCALAR_MARKERS = frozenset({"|", "|-", "|+", ">", ">-", ">+"})
_CANONICAL_FIELDS = {
    "feature": ("id", "summary", "state"),
    "story": (
        "id",
        "parent",
        "summary",
        "type",
        "kind",
        "phase",
        "block",
        "implements",
        "covers",
        "accepts",
        "context",
        "stack",
        "stack_mode",
        "size",
        "budget",
        "provides",
        "consumes",
        "rules",
        "copy",
        "instructions",
        "acceptance",
        "depends",
        "questions",
        "questions_approved",
        "feedback",
        "state",
        "evidence",
        "scope",
    ),
    "spike": (
        "id",
        "parent",
        "summary",
        "context",
        "question",
        "finding",
        "depends",
        "state",
        "evidence",
    ),
    "ac": ("id", "parent", "summary", "kind", "check", "state", "evidence"),
}


def _split_list(value: str) -> tuple[str, ...]:
    if "," in value:
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return tuple(part for part in value.split() if part)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "ac"


@dataclass(frozen=True)
class AppliedSpecRecord:
    path: str
    sha256: str
    commit: str
    applied_by: str
    applied_at: str


@dataclass(frozen=True)
class ManifestDefect:
    """One actionable syntax or graph defect."""

    source: str
    message: str
    line: int | None = None
    block_header: str = ""
    node_id: str = ""
    field: str = ""
    received: str = ""
    expected: str = ""
    hint: str = ""
    stage: str = "parse"
    source_line: str = ""

    def concise(self) -> str:
        location: list[str] = []
        if self.line is not None:
            location.append(f"line {self.line}")
        if self.node_id:
            location.append(self.node_id)
        elif self.block_header:
            location.append(self.block_header)
        prefix = f"  {', '.join(location)}: " if location else "  "
        lines = [prefix + self.message]
        if self.expected:
            lines.append(f"  Expected {self.expected}.")
        if self.hint:
            lines.append(f"  {self.hint}")
        return "\n".join(lines)

    def detailed(self) -> str:
        lines = [self.concise(), f"  stage: {self.stage}"]
        if self.field:
            lines.append(f"  field: {self.field}")
        if self.received:
            lines.append(f"  received: {self.received!r}")
        if self.source_line:
            lines.append(f"  source: {self.source_line}")
        return "\n".join(lines)


class ManifestError(SpecificationError):
    """A collected set of deterministic Manifest defects."""

    def __init__(
        self,
        source: str | Path,
        defects: Iterable[ManifestDefect],
        *,
        debug: bool = False,
    ):
        self.source = str(source)
        self.defects = tuple(defects)
        self.debug = debug
        body = "\n".join(
            defect.detailed() if debug else defect.concise() for defect in self.defects
        )
        suffix = (
            "  No files were changed."
            if debug
            else "  No files were changed. Run with --debug for parser details."
        )
        super().__init__(f"Invalid MANIFEST.md: {self.source}\n{body}\n{suffix}")


@dataclass
class ManifestMetadata:
    project: str
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def updated(self) -> str:
        return self.fields.get("updated", "")

    @property
    def plan_hash(self) -> str:
        return self.fields.get("plan_hash", "")

    @property
    def state(self) -> str:
        return self.fields.get("state", "approved")


@dataclass
class ManifestNode:
    """Typed graph node retaining its exact source block."""

    block_type: str
    number: int
    name: str
    block_id: str
    state: str
    parent: str | None = None
    depends: tuple[str, ...] = ()
    scope: str | None = None
    fields: dict[str, str | tuple[str, ...]] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    line: int = 0
    legacy_compact: bool = False
    dirty: bool = False

    @property
    def node_type(self) -> str:
        return self.block_type

    def _scalar(self, name: str) -> str:
        value = self.fields.get(name, "")
        if isinstance(value, tuple):
            return ", ".join(value)
        return str(value).strip()

    @property
    def story_type(self) -> str:
        """``foundational`` | ``service`` | ``feature``, or '' on a legacy-taxonomy block."""
        return self._scalar("type").lower()

    @property
    def delivery_kind(self) -> str:
        return self._scalar("kind").lower()

    @property
    def stack_mode(self) -> str:
        """``builder`` | ``consumer``. Computed from first use in the build-order-global sort."""
        return self._scalar("stack_mode").lower()

    @property
    def phase(self) -> int:
        """Commander build sequencing. Describes when the file is built, not the file."""
        try:
            return int(self._scalar("phase"))
        except ValueError:
            return 0

    @property
    def block(self) -> int:
        """Ephemeral context-optimization group; regenerated every plan run."""
        try:
            return int(self._scalar("block"))
        except ValueError:
            return 0

    @property
    def size_tokens(self) -> int:
        """Measured single-build-pass cost in tokens; 0 when unmeasured."""
        try:
            return int(self._scalar("size"))
        except ValueError:
            return 0

    @property
    def over_target(self) -> bool:
        """Whether this story exceeds the single-build-pass target.

        A marker, never a gate. Some specifications are irreducible — a language definition that
        is normative text rather than instructions makes every story implementing against it
        over target by construction, and those stories build.
        """
        return self._scalar("budget").lower() == "over-target"

    @property
    def has_acceptance_contract(self) -> bool:
        """Whether the story carries real acceptance to honor.

        Acceptance is a field the story owns, not an independent node with independent state: a
        story is not "built and failed", it is built or it is not.
        """
        return self._scalar("acceptance").lower() in {"yes", "true", "1"}


class FeatureNode(ManifestNode):
    pass


class StoryNode(ManifestNode):
    pass


class SpikeNode(ManifestNode):
    pass


class AcceptanceNode(ManifestNode):
    pass


_NODE_TYPES = {
    "feature": FeatureNode,
    "story": StoryNode,
    "spike": SpikeNode,
    "ac": AcceptanceNode,
}

# Compatibility name used throughout the existing build modules.
PlanBlock = ManifestNode


def _parse_applied_registry(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in text.split(","):
        name, separator, commit = entry.strip().partition("=")
        if separator and name.strip() and commit.strip():
            result[name.strip()] = commit.strip()
    return result


def _parse_applied_specs(text: str) -> dict[str, AppliedSpecRecord]:
    result: dict[str, AppliedSpecRecord] = {}
    for raw in text.splitlines():
        path, _, rest = raw.strip().partition(" ")
        values = dict(token.split("=", 1) for token in rest.split() if "=" in token)
        if not path or not all(values.get(key) for key in ("sha256", "applied_by", "applied_at")):
            continue
        result[path] = AppliedSpecRecord(
            path=path,
            sha256=values["sha256"],
            commit=values.get("commit", "-") or "-",
            applied_by=values["applied_by"],
            applied_at=values["applied_at"],
        )
    return result


def _field_value(lines: list[str], key: str) -> str | None:
    for line in lines[1:]:
        match = _FIELD_RE.match(line)
        if match and match.group(1).lower() == key:
            return match.group(2).strip()
    return None


@dataclass
class DrydockManifest:
    """The sole typed read/write graph interface for ``MANIFEST.md``."""

    path: Path
    metadata: ManifestMetadata
    blocks: list[ManifestNode]
    preamble: list[str]
    applied_registry: dict[str, str] = field(default_factory=dict)
    applied_specs: dict[str, AppliedSpecRecord] = field(default_factory=dict)
    _trailing_newline: bool = True
    _compatibility: bool = False

    @classmethod
    def load(
        cls,
        path: Path | str,
        *,
        debug: bool = False,
        compatibility: bool = False,
    ) -> DrydockManifest:
        debug = debug or os.environ.get("DRYDOCK_DEBUG", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        manifest_path = Path(path)
        if not manifest_path.is_file():
            raise ManifestError(
                manifest_path,
                [
                    ManifestDefect(
                        source=str(manifest_path),
                        message=f"MANIFEST.md not found: {manifest_path}",
                        expected="an existing MANIFEST.md file",
                        hint="Run: drydock plan",
                        stage="read",
                    )
                ],
                debug=debug,
            )
        try:
            text = manifest_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ManifestError(
                manifest_path,
                [
                    ManifestDefect(
                        source=str(manifest_path),
                        message=f"cannot read Manifest: {exc}",
                        expected="UTF-8 text",
                        stage="read",
                    )
                ],
                debug=debug,
            ) from exc
        return cls.parse(text, source=manifest_path, debug=debug, compatibility=compatibility)

    @classmethod
    def parse(
        cls,
        text: str,
        *,
        source: Path | str = "<memory>",
        debug: bool = False,
        defect_cap: int = 50,
        compatibility: bool = False,
    ) -> DrydockManifest:
        source_path = Path(source)
        lines = text.splitlines()
        defects: list[ManifestDefect] = []

        def defect(**values: object) -> None:
            if len(defects) >= defect_cap:
                return
            defects.append(ManifestDefect(source=str(source), **values))  # type: ignore[arg-type]

        first_block = len(lines)
        for index, line in enumerate(lines):
            if line.startswith("## "):
                first_block = index
                break

        project = ""
        metadata_fields: dict[str, str] = {}
        index = 0
        while index < first_block:
            line = lines[index]
            header = _PLAN_HEADER_RE.match(line)
            if header:
                if not project:
                    project = header.group(1)
                index += 1
                continue
            match = _FIELD_RE.match(line)
            if match:
                key, value = match.group(1).lower(), match.group(2).strip()
                if value in _SCALAR_MARKERS:
                    body, next_index = cls._collect_scalar(lines, index + 1, first_block)
                    metadata_fields[key] = body
                    index = next_index
                    continue
                metadata_fields[key] = value
            index += 1

        if not project:
            defect(
                message="missing Manifest header",
                line=1 if lines else None,
                field="header",
                received=lines[0] if lines else "",
                expected="'# MANIFEST: <ProjectName>'",
                hint="Add the Manifest header as the first content line.",
                source_line=lines[0] if lines else "",
            )

        blocks: list[ManifestNode] = []
        cursor = first_block
        last_owner: str | None = None
        used_ids: set[str] = set()
        while cursor < len(lines):
            raw_header = lines[cursor]
            match = _HEADER_RE.match(raw_header)
            if not match:
                defect(
                    message="malformed block header",
                    line=cursor + 1,
                    block_header=raw_header.removeprefix("## ").strip(),
                    received=raw_header,
                    expected="'## feature|story|spike|ac N: <Name>'",
                    hint="Correct the block type, numeric ordinal, and colon.",
                    source_line=raw_header,
                )
                cursor += 1
                while cursor < len(lines) and not lines[cursor].startswith("## "):
                    cursor += 1
                continue

            start = cursor
            cursor += 1
            while cursor < len(lines) and not lines[cursor].startswith("## "):
                cursor += 1
            raw_lines = lines[start:cursor]
            while raw_lines and not raw_lines[-1].strip():
                raw_lines.pop()

            block_type, number_text, name = match.groups()
            parsed_fields: dict[str, str | tuple[str, ...]] = {}
            field_lines: dict[str, int] = {}
            body_index = 1
            while body_index < len(raw_lines):
                field_match = _FIELD_RE.match(raw_lines[body_index])
                if not field_match:
                    body_index += 1
                    continue
                key = field_match.group(1).lower()
                value = field_match.group(2).strip()
                absolute_line = start + body_index + 1
                if key in field_lines:
                    defect(
                        message=f"duplicate field `{key}`",
                        line=absolute_line,
                        block_header=f"{block_type} {number_text}",
                        field=key,
                        received=value,
                        expected=f"one `{key}:` field",
                        hint="Remove the duplicate field.",
                        source_line=raw_lines[body_index],
                    )
                field_lines.setdefault(key, absolute_line)
                if value in _SCALAR_MARKERS:
                    scalar, next_body = cls._collect_scalar(
                        raw_lines, body_index + 1, len(raw_lines)
                    )
                    parsed_fields[key] = scalar
                    body_index = next_body
                    continue
                if key in _LIST_FIELDS:
                    parsed_fields[key] = _split_list(value)
                elif key in _INTERFACE_FIELDS:
                    parsed_fields[key] = tuple(
                        part.strip() for part in value.split(",") if part.strip()
                    )
                else:
                    parsed_fields[key] = value
                body_index += 1

            legacy = False
            if block_type == "ac" and not str(parsed_fields.get("id", "")).strip():
                compact = _COMPACT_AC_RE.match(name)
                if compact:
                    legacy = True
                    summary = compact.group("summary").strip()
                    candidate = _slugify(summary)
                    unique = candidate
                    suffix = 2
                    while unique in used_ids:
                        unique = f"{candidate}-{suffix}"
                        suffix += 1
                    parsed_fields["id"] = unique
                    parsed_fields.setdefault("parent", last_owner or "")
                    parsed_fields.setdefault("summary", summary)
                    parsed_fields.setdefault("kind", compact.group("kind"))
                    parsed_fields.setdefault("check", compact.group("check").strip())
                    parsed_fields.setdefault("state", "pending")
                    name = summary

            block_id = str(parsed_fields.get("id", "")).strip()
            state = str(parsed_fields.get("state", "pending")).strip()
            parent = str(parsed_fields.get("parent", "")).strip() or None
            depends_value = parsed_fields.get("depends", ())
            depends = (
                depends_value
                if isinstance(depends_value, tuple)
                else _split_list(str(depends_value))
            )
            scope = str(parsed_fields.get("scope", "")).strip() or None
            node_cls = _NODE_TYPES[block_type]
            node = node_cls(
                block_type=block_type,
                number=int(number_text),
                name=name,
                block_id=block_id,
                state=state,
                parent=parent,
                depends=depends,
                scope=scope,
                fields=parsed_fields,
                lines=raw_lines,
                line=start + 1,
                legacy_compact=legacy,
            )
            blocks.append(node)
            if block_id:
                used_ids.add(block_id)
                if block_type != "ac":
                    last_owner = block_id

        manifest = cls(
            path=source_path,
            metadata=ManifestMetadata(project=project, fields=metadata_fields),
            blocks=blocks,
            preamble=lines[:first_block],
            applied_registry=_parse_applied_registry(metadata_fields.get("applied", "")),
            applied_specs=_parse_applied_specs(metadata_fields.get("applied_specs", "")),
            _trailing_newline=text.endswith("\n"),
            _compatibility=compatibility,
        )
        if compatibility:
            manifest._normalize_legacy_edges()
        defects.extend(
            manifest.validate(
                raise_on_error=False,
                cap=defect_cap - len(defects),
                compatibility=compatibility,
            )
        )
        if defects:
            logger.debug(
                "Manifest validation failed: source=%s defects=%d stages=%s",
                source,
                len(defects),
                sorted({item.stage for item in defects}),
            )
            raise ManifestError(source, defects, debug=debug)
        logger.debug(
            "Manifest parsed: source=%s project=%s nodes=%d edges=%d",
            source,
            project,
            len(blocks),
            sum(len(node.depends) + bool(node.parent) for node in blocks),
        )
        return manifest

    def _normalize_legacy_edges(self) -> None:
        """Apply the temporary BuildPlan edge compatibility policy."""
        by_id = self.by_id()
        for node in self.blocks:
            dependencies: list[str] = []
            for dependency in node.depends:
                target = by_id.get(dependency)
                if (
                    node.block_type in {"story", "spike"}
                    and target is not None
                    and target.block_type == "ac"
                    and target.parent
                ):
                    dependency = target.parent
                if node.block_type == "ac" and dependency != node.parent:
                    continue
                if dependency != node.block_id and dependency not in dependencies:
                    dependencies.append(dependency)
            node.depends = tuple(dependencies)
            node.fields["depends"] = node.depends

    @staticmethod
    def _collect_scalar(lines: list[str], start: int, stop: int) -> tuple[str, int]:
        body: list[str] = []
        index = start
        while index < stop:
            line = lines[index]
            if line.strip() and not line[:1].isspace():
                break
            body.append(line)
            index += 1
        while body and not body[-1].strip():
            body.pop()
        indents = [len(line) - len(line.lstrip()) for line in body if line.strip()]
        trim = min(indents) if indents else 0
        return "\n".join(line[trim:] if line.strip() else "" for line in body), index

    @property
    def project(self) -> str:
        return self.metadata.project

    @property
    def updated(self) -> str:
        return self.metadata.updated

    @property
    def plan_hash(self) -> str:
        return self.metadata.plan_hash

    @property
    def state(self) -> str:
        return self.metadata.state

    def by_id(self) -> dict[str, ManifestNode]:
        return {node.block_id: node for node in self.blocks}

    def ids(self) -> tuple[str, ...]:
        return tuple(node.block_id for node in self.blocks)

    def node(self, node_id: str) -> ManifestNode:
        try:
            return self.by_id()[node_id]
        except KeyError as exc:
            raise SpecificationError(f"Unknown Manifest node {node_id!r}") from exc

    def parent_of(self, node_id: str) -> ManifestNode | None:
        parent_id = self.node(node_id).parent
        return self.by_id().get(parent_id or "")

    def children(self, parent_id: str) -> tuple[ManifestNode, ...]:
        return tuple(node for node in self.blocks if node.parent == parent_id)

    def dependencies(self, node_id: str, *, transitive: bool = False) -> tuple[ManifestNode, ...]:
        by_id = self.by_id()
        direct = [by_id[item] for item in self.node(node_id).depends if item in by_id]
        if not transitive:
            return tuple(direct)
        seen: set[str] = set()
        ordered: list[ManifestNode] = []

        def visit(node: ManifestNode) -> None:
            for dependency in node.depends:
                if dependency in seen or dependency not in by_id:
                    continue
                seen.add(dependency)
                visit(by_id[dependency])
                ordered.append(by_id[dependency])

        visit(self.node(node_id))
        return tuple(ordered)

    def dependents(self, node_id: str, *, transitive: bool = False) -> tuple[ManifestNode, ...]:
        direct = tuple(node for node in self.blocks if node_id in node.depends)
        if not transitive:
            return direct
        seen: set[str] = set()
        queue = list(direct)
        while queue:
            current = queue.pop(0)
            if current.block_id in seen:
                continue
            seen.add(current.block_id)
            queue.extend(node for node in self.blocks if current.block_id in node.depends)
        return tuple(node for node in self.blocks if node.block_id in seen)

    def state_counts(self) -> Counter[str]:
        return Counter(node.state for node in self.blocks)

    def runnable_frontier(self) -> tuple[ManifestNode, ...]:
        by_id = self.by_id()

        def verified(node_id: str) -> bool:
            node = by_id.get(node_id)
            return node is not None and node.state == "closed/verified"

        result: list[ManifestNode] = []
        for node in self.blocks:
            if node.block_type == "feature" or node.state != "pending":
                continue
            if not all(verified(item) for item in node.depends):
                continue
            if node.block_type == "ac":
                owner = by_id.get(node.parent or "")
                if owner is None:
                    continue
                if owner.block_type == "feature":
                    work = [
                        child
                        for child in self.children(owner.block_id)
                        if child.block_type in {"story", "spike"}
                    ]
                    if not work or not all(child.state == "closed/verified" for child in work):
                        continue
                elif owner.state != "implemented":
                    continue
            result.append(node)
        return tuple(result)

    def buildable_steps(self) -> tuple[ManifestNode, ...]:
        by_id = self.by_id()

        def verified(node_id: str) -> bool:
            target = by_id.get(node_id)
            return target is not None and target.state == "closed/verified"

        grouped: set[str] = set()
        result: list[ManifestNode] = []
        for feature in (node for node in self.blocks if node.block_type == "feature"):
            work = tuple(
                child
                for child in self.children(feature.block_id)
                if child.block_type in {"story", "spike"}
            )
            # A feature is normally one grouped build unit. Question-blocked
            # children split that group temporarily so unrelated siblings stay
            # available on the frontier.
            question_blocked = any(node.state == "blocked/questions" for node in work)
            if not question_blocked:
                grouped.update(node.block_id for node in work)
            pending = tuple(node for node in work if node.state == "pending")
            internal = {node.block_id for node in work}
            dependencies = [
                dependency
                for node in (feature, *pending)
                for dependency in node.depends
                if dependency not in internal and not verified(dependency)
            ]
            if pending and not dependencies and not question_blocked:
                result.append(feature)
        result.extend(
            node
            for node in self.blocks
            if node.block_type in {"story", "spike"}
            and node.block_id not in grouped
            and node.state == "pending"
            and all(verified(item) for item in node.depends)
        )
        return tuple(result)

    def closable_features(self) -> tuple[ManifestNode, ...]:
        return tuple(
            node
            for node in self.blocks
            if node.block_type == "feature"
            and node.state in {"pending", "implemented"}
            and self.children(node.block_id)
            and all(child.state == "closed/verified" for child in self.children(node.block_id))
        )

    def reset_cascade(self, seed_ids: Iterable[str]) -> tuple[str, ...]:
        reset = set(seed_ids)
        changed = True
        while changed:
            changed = False
            for node in self.blocks:
                if node.block_id in reset:
                    continue
                if node.parent in reset or any(item in reset for item in node.depends):
                    reset.add(node.block_id)
                    changed = True
        reset.update(
            node.block_id
            for node in self.blocks
            if node.block_type == "feature"
            and any(child.block_id in reset for child in self.children(node.block_id))
        )
        return tuple(node.block_id for node in self.blocks if node.block_id in reset)

    def validate(
        self,
        *,
        raise_on_error: bool = True,
        cap: int = 50,
        compatibility: bool = False,
    ) -> tuple[ManifestDefect, ...]:
        defects: list[ManifestDefect] = []
        by_id: dict[str, ManifestNode] = {}

        def add(node: ManifestNode | None, message: str, **values: object) -> None:
            if len(defects) >= cap:
                return
            defects.append(
                ManifestDefect(
                    source=str(self.path),
                    message=message,
                    line=node.line if node else None,
                    block_header=(f"{node.block_type} {node.number}" if node is not None else ""),
                    node_id=node.block_id if node else "",
                    source_line=node.lines[0] if node and node.lines else "",
                    stage="graph-validation",
                    **values,  # type: ignore[arg-type]
                )
            )

        if self.state not in PLAN_STATES:
            add(
                None,
                "invalid Manifest state",
                field="state",
                received=self.state,
                expected=f"one of: {', '.join(PLAN_STATES)}",
                hint="Set the preamble state to a legal value.",
            )

        for node in self.blocks:
            if not node.block_id:
                add(
                    node,
                    "Missing id: missing required `id`",
                    field="id",
                    expected="an explicit `id:` field or valid legacy compact AC syntax",
                    hint="Add a stable, unique id.",
                )
            elif node.block_id in by_id:
                add(
                    node,
                    f"Duplicate block id `{node.block_id}`",
                    field="id",
                    received=node.block_id,
                    expected="a unique id",
                    hint="Rename one node and update its parent/dependency references.",
                )
            else:
                by_id[node.block_id] = node
            if node.state not in STATES:
                add(
                    node,
                    f"Invalid state `{node.state}`",
                    field="state",
                    received=node.state,
                    expected=f"one of: {', '.join(STATES)}",
                    hint="Set the node to a legal lifecycle state.",
                )
            if node.scope is not None and node.scope not in SCOPES:
                add(
                    node,
                    f"invalid scope `{node.scope}`",
                    field="scope",
                    received=node.scope,
                    expected=f"one of: {', '.join(SCOPES)}",
                    hint="Correct or remove the scope field.",
                )

        for node in self.blocks:
            if node.parent:
                parent = by_id.get(node.parent)
                legal = (
                    ("feature",)
                    if node.block_type in {"story", "spike"}
                    else (("feature", "story", "spike") if node.block_type == "ac" else ())
                )
                if parent is None and not compatibility:
                    add(
                        node,
                        f"parent names unknown id '{node.parent}'",
                        field="parent",
                        received=node.parent,
                        expected="the id of an existing legal owner",
                        hint="Correct the parent id or add the missing owner.",
                    )
                elif parent is not None and parent.block_type not in legal and not compatibility:
                    add(
                        node,
                        (
                            f"{node.block_type} must be parented to a "
                            f"{'feature' if node.block_type in {'story', 'spike'} else 'legal owner'}; "
                            f"received `{parent.block_type}`"
                        ),
                        field="parent",
                        received=node.parent,
                        expected=f"parent type: {', '.join(legal) or 'none'}",
                        hint="Move the node under a legal owner.",
                    )
            elif node.block_type == "ac":
                add(
                    node,
                    "Missing parent: missing required `parent`",
                    field="parent",
                    expected="a story, spike, or feature id",
                    hint="Add the owner this acceptance gate controls.",
                )
            for dependency in node.depends:
                if dependency == node.block_id:
                    add(
                        node,
                        "self dependency",
                        field="depends",
                        received=dependency,
                        expected="another story or spike id",
                        hint="Remove the self edge.",
                    )
                elif dependency not in by_id and not compatibility:
                    add(
                        node,
                        f"unknown dependency: depends on unknown id `{dependency}`",
                        field="depends",
                        received=dependency,
                        expected="an existing story or spike id",
                        hint="Correct or remove the dependency edge.",
                    )
                elif (
                    dependency in by_id
                    and by_id[dependency].block_type not in {"story", "spike"}
                    and not compatibility
                ):
                    add(
                        node,
                        f"illegal dependency target `{dependency}`",
                        field="depends",
                        received=by_id[dependency].block_type,
                        expected="a story or spike id",
                        hint="Depend on executable work, not a feature or acceptance node.",
                    )

            if node.block_type == "ac":
                kind = str(node.fields.get("kind", "")).strip()
                if kind and kind not in AC_KINDS:
                    add(
                        node,
                        f"invalid acceptance kind `{kind}`",
                        field="kind",
                        received=kind,
                        expected="'smoke' or 'assertion'",
                        hint="Correct the kind.",
                    )
                if kind == "smoke" and not str(node.fields.get("check", "")).strip():
                    add(
                        node,
                        "missing required `check`",
                        field="check",
                        expected="a non-empty command for a smoke gate",
                        hint="Add the smoke command.",
                    )
                for dependency in node.depends:
                    if dependency != node.parent and not compatibility:
                        add(
                            node,
                            f"acceptance dependency `{dependency}` does not match its owner",
                            field="depends",
                            received=dependency,
                            expected="no dependency edge; parent ownership provides gating",
                            hint="Remove the acceptance dependency.",
                        )

        ownership: dict[str, str] = {}
        for node in self.blocks:
            if node.block_type != "story":
                continue
            implementations = node.fields.get("implements", ())
            items = implementations if isinstance(implementations, tuple) else (implementations,)
            for item in (str(value) for value in items if value):
                previous = ownership.get(item)
                if previous and previous != node.block_id and not compatibility:
                    add(
                        node,
                        f"Blueprint implementation `{item}` has multiple owners",
                        field="implements",
                        received=f"{previous}, {node.block_id}",
                        expected="exactly one story owner",
                        hint="Remove the duplicate implementation ownership.",
                    )
                ownership[item] = node.block_id

        colors: dict[str, int] = {}
        stack: list[str] = []

        def visit(node_id: str) -> None:
            colors[node_id] = 1
            stack.append(node_id)
            for dependency in by_id[node_id].depends:
                if dependency not in by_id:
                    continue
                if colors.get(dependency) == 1:
                    cycle = stack[stack.index(dependency) :] + [dependency]
                    add(
                        by_id[node_id],
                        "dependency cycle: " + " -> ".join(cycle),
                        field="depends",
                        received=dependency,
                        expected="an acyclic dependency graph",
                        hint="Remove or reverse one edge in the cycle.",
                    )
                elif colors.get(dependency, 0) == 0:
                    visit(dependency)
            stack.pop()
            colors[node_id] = 2

        if not compatibility:
            for node_id in by_id:
                if colors.get(node_id, 0) == 0:
                    visit(node_id)

        result = tuple(defects)
        if result and raise_on_error:
            raise ManifestError(self.path, result)
        return result

    def _sync_node(self, node: ManifestNode) -> None:
        """Canonicalize a changed node while retaining unknown extension fields."""
        if node.legacy_compact and not node.dirty:
            return
        known = list(_CANONICAL_FIELDS[node.block_type])
        extension = [key for key in node.fields if key not in known]
        lines = [f"## {node.block_type} {node.number}: {node.name}"]
        comments = [line for line in node.lines[1:] if line.lstrip().startswith(("#", "<!--"))]
        for key in (*known, *extension):
            if key not in node.fields:
                continue
            value = node.fields[key]
            if isinstance(value, tuple):
                rendered = ", ".join(value)
                if not rendered:
                    continue
                lines.append(f"{key}: {rendered}")
            elif "\n" in str(value):
                lines.append(f"{key}: |")
                lines.extend(f"  {part}" for part in str(value).splitlines())
            elif str(value) or key in {"parent", "depends", "check"}:
                lines.append(f"{key}: {value}")
        lines.extend(comments)
        node.lines = lines
        node.legacy_compact = False
        node.dirty = False

    def set_fields(self, node_id: str, **fields: str | tuple[str, ...] | None) -> None:
        node = self.node(node_id)
        for key, value in fields.items():
            if value is None:
                node.fields.pop(key, None)
            else:
                node.fields[key] = value
        node.block_id = str(node.fields.get("id", node.block_id)).strip()
        node.parent = str(node.fields.get("parent", "")).strip() or None
        node.state = str(node.fields.get("state", "pending")).strip()
        node.scope = str(node.fields.get("scope", "")).strip() or None
        depends = node.fields.get("depends", ())
        node.depends = depends if isinstance(depends, tuple) else _split_list(str(depends))
        node.dirty = True

    def transition(self, node_id: str, state: str) -> None:
        if state not in STATES:
            raise SpecificationError(
                f"Invalid state {state!r}; expected one of: {', '.join(STATES)}"
            )
        self.set_fields(node_id, state=state)

    def add(self, node: ManifestNode, *, before: str | None = None) -> None:
        if node.block_id in self.by_id():
            raise SpecificationError(f"Duplicate Manifest node id {node.block_id!r}")
        node.dirty = True
        if before is None:
            self.blocks.append(node)
        else:
            index = self.ids().index(before)
            self.blocks.insert(index, node)

    @classmethod
    def create_node(
        cls,
        block_type: str,
        block_id: str,
        name: str,
        *,
        number: int = 1,
        parent: str | None = None,
        state: str = "pending",
        depends: Iterable[str] = (),
        **fields: str | tuple[str, ...],
    ) -> ManifestNode:
        """Construct a canonical typed node for ``add`` or ``replace``."""
        if block_type not in _NODE_TYPES:
            raise SpecificationError(
                f"Invalid Manifest node type {block_type!r}; expected: {', '.join(BLOCK_TYPES)}"
            )
        values: dict[str, str | tuple[str, ...]] = {
            "id": block_id,
            "state": state,
            **fields,
        }
        dependencies = tuple(depends)
        if parent is not None:
            values["parent"] = parent
        if dependencies:
            values["depends"] = dependencies
        return _NODE_TYPES[block_type](
            block_type=block_type,
            number=number,
            name=name,
            block_id=block_id,
            state=state,
            parent=parent,
            depends=dependencies,
            scope=str(values.get("scope", "")).strip() or None,
            fields=values,
            dirty=True,
        )

    def replace(self, node_id: str, node: ManifestNode, *, preserve_verified: bool = False) -> None:
        current = self.node(node_id)
        if preserve_verified and current.state == "closed/verified":
            return
        if node.block_id != node_id and node.block_id in self.by_id():
            raise SpecificationError(f"Duplicate Manifest node id {node.block_id!r}")
        node.dirty = True
        self.blocks[self.blocks.index(current)] = node

    def remove(self, node_id: str, *, cascade: bool = False) -> None:
        targets = {node_id}
        if cascade:
            targets.update(item.block_id for item in self.children(node_id))
            targets.update(item.block_id for item in self.dependents(node_id, transitive=True))
        else:
            refs = [
                node.block_id
                for node in self.blocks
                if node.parent == node_id or node_id in node.depends
            ]
            if refs:
                raise SpecificationError(
                    f"Cannot remove {node_id!r}; referenced by: {', '.join(refs)}"
                )
        self.blocks[:] = [node for node in self.blocks if node.block_id not in targets]

    def move(self, node_id: str, *, before: str | None = None, after: str | None = None) -> None:
        if bool(before) == bool(after):
            raise SpecificationError("Specify exactly one of before= or after=")
        node = self.node(node_id)
        self.blocks.remove(node)
        anchor = self.node(before or after or "")
        index = self.blocks.index(anchor) + (1 if after else 0)
        self.blocks.insert(index, node)

    def regroup(self, node_id: str, parent_id: str | None) -> None:
        self.set_fields(node_id, parent=parent_id)
        self.validate(compatibility=self._compatibility)

    def reset(self, seed_ids: Iterable[str]) -> tuple[str, ...]:
        ids = self.reset_cascade(seed_ids)
        for node_id in ids:
            self.set_fields(node_id, state="pending", finding=None)
        return ids

    def set_metadata(self, **fields: str | None) -> None:
        for key, value in fields.items():
            if value is None:
                self.metadata.fields.pop(key, None)
            else:
                self.metadata.fields[key] = value
        self._sync_preamble()

    def set_applied_specs(self, records: Mapping[str, AppliedSpecRecord]) -> None:
        """Replace the typed applied-spec registry in memory."""
        lines = [
            f"{record.path} sha256={record.sha256} commit={record.commit or '-'} "
            f"applied_by={record.applied_by} applied_at={record.applied_at}"
            for _, record in sorted(records.items())
        ]
        self.applied_specs = dict(records)
        self.set_metadata(applied_specs="\n".join(lines))

    def _sync_preamble(self) -> None:
        existing = list(self.preamble)
        first_header = next(
            (index for index, line in enumerate(existing) if _PLAN_HEADER_RE.match(line)), None
        )
        if first_header is None:
            existing.insert(0, f"# MANIFEST: {self.project}")
        emitted: set[str] = set()
        output: list[str] = []
        index = 0
        while index < len(existing):
            match = _FIELD_RE.match(existing[index])
            if match and match.group(1).lower() in self.metadata.fields:
                key = match.group(1).lower()
                value = self.metadata.fields[key]
                emitted.add(key)
                if "\n" in value or match.group(2).strip() in _SCALAR_MARKERS:
                    output.append(f"{key}: |")
                    output.extend(f"  {line}" for line in value.splitlines())
                    index += 1
                    while index < len(existing) and (
                        not existing[index].strip() or existing[index][:1].isspace()
                    ):
                        index += 1
                    continue
                output.append(f"{key}: {value}")
            else:
                output.append(existing[index])
            index += 1
        insert_at = len(output)
        additions: list[str] = []
        for key, value in self.metadata.fields.items():
            if key in emitted:
                continue
            if "\n" in value:
                additions.append(f"{key}: |")
                additions.extend(f"  {line}" for line in value.splitlines())
            else:
                additions.append(f"{key}: {value}")
        if additions:
            while insert_at and not output[insert_at - 1].strip():
                insert_at -= 1
            output[insert_at:insert_at] = additions
        self.preamble = output

    def render(self) -> str:
        for node in self.blocks:
            if getattr(node, "dirty", False):
                self._sync_node(node)
        parts: list[str] = []
        preamble = list(self.preamble)
        while preamble and not preamble[-1].strip():
            preamble.pop()
        if preamble:
            parts.append("\n".join(preamble))
        for node in self.blocks:
            lines = list(node.lines)
            while lines and not lines[-1].strip():
                lines.pop()
            parts.append("\n".join(lines))
        return "\n\n".join(parts) + "\n"

    def save(self, path: Path | str | None = None) -> None:
        destination = Path(path) if path is not None else self.path
        self.validate(compatibility=self._compatibility)
        text = self.render()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent, delete=False, newline="\n"
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        temporary.replace(destination)
        self.path = destination


# Compatibility name; production callers can migrate without changing behavior.
BuildPlan = DrydockManifest
