"""Advisory conformance scoring for imported raw specifications.

The model extracts cited facts.  This module owns inventory, validation, profile
activation, deterministic findings, side-effect detection, and report writing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.prompt_assembly import PromptAssembly
from drydock.prompts import load_prompt

PROMPT_NAME = "score_spec"
REPORT_NAME = "SPECIFICATION_SCORECARD.md"
MAX_CHUNK_BYTES = 80_000
MAX_PASS_BYTES = 200_000

FACT_TYPES = frozenset({
    "reference",
    "definition",
    "consumer",
    "entry_point",
    "help",
    "initialization",
    "ownership",
    "scope",
    "web_surface",
    "route",
    "navigation",
    "navigation_order",
    "action",
    "api",
    "api_consumer",
    "service",
    "service_consumer",
    "table",
    "field",
    "data_origin",
    "data_producer",
    "data_source",
    "data_consumer",
    "initial_condition",
    "pipeline",
    "trigger",
    "stage",
    "input",
    "output",
    "sink",
    "checkpoint",
    "schedule",
    "dataset",
    "feature",
    "target",
    "training",
    "evaluation",
    "artifact",
    "inference_consumer",
    "cli",
    "library",
    "library_consumer",
    "event",
    "event_consumer",
    "batch",
    "scheduler",
    "state",
    "state_consumer",
})


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]


@dataclass(frozen=True)
class SourceRecord:
    path: str
    bytes: int
    lines: int | None
    headings: int | None
    markdown: bool


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    source_path: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class Fact:
    type: str
    identifier: str
    value: str
    source_path: str
    line: int


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    sources: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ScoreSpecResult:
    report_path: Path
    report: str
    inventory: tuple[SourceRecord, ...]
    facts: tuple[Fact, ...]
    findings: tuple[Finding, ...]
    profiles: tuple[str, ...]
    extraction_passes: int

    def exit_code(self) -> int:
        return 0


@dataclass(frozen=True)
class _TreeStamp:
    size: int
    mtime_ns: int
    digest: str | None


_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_FENCE = re.compile(r"\A```[A-Za-z0-9_-]*\n|\n?```\Z")
_ENTITY_TYPES = FACT_TYPES - {
    "reference",
    "consumer",
    "navigation",
    "navigation_order",
    "action",
    "api_consumer",
    "service_consumer",
    "field",
    "data_origin",
    "data_producer",
    "data_source",
    "data_consumer",
    "initial_condition",
    "trigger",
    "stage",
    "input",
    "output",
    "sink",
    "checkpoint",
    "schedule",
    "feature",
    "target",
    "training",
    "evaluation",
    "artifact",
    "inference_consumer",
    "library_consumer",
    "event_consumer",
    "state_consumer",
}


def _normal(value: str) -> str:
    return " ".join(value.strip().lower().split())


def inventory_sources(sources_dir: Path) -> tuple[tuple[SourceRecord, ...], dict[str, str]]:
    """Inventory every regular path stably; ingest content only for Markdown files."""
    if not sources_dir.is_dir():
        raise SpecificationError(f"imported source directory not found: {sources_dir}")
    records: list[SourceRecord] = []
    markdown: dict[str, str] = {}
    paths = sorted(
        (path for path in sources_dir.rglob("*") if path.is_file()),
        key=lambda path: (
            path.relative_to(sources_dir).as_posix().casefold(),
            path.relative_to(sources_dir).as_posix(),
        ),
    )
    if not paths:
        raise SpecificationError(f"no imported sources found under {sources_dir}")
    for path in paths:
        rel = path.relative_to(sources_dir).as_posix()
        size = path.stat().st_size
        is_markdown = path.suffix.casefold() in {".md", ".markdown"}
        if not is_markdown:
            records.append(SourceRecord(rel, size, None, None, False))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SpecificationError(f"could not read Markdown source {rel}: {exc}") from exc
        line_count = len(text.splitlines())
        markdown[rel] = text
        records.append(SourceRecord(rel, size, line_count, len(_HEADING.findall(text)), True))
    return tuple(records), markdown


def _line_chunks(path: str, text: str, limit: int = MAX_CHUNK_BYTES) -> list[SourceChunk]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return [SourceChunk(f"{path}:1-0", path, 1, 0, "")]
    result: list[SourceChunk] = []
    start = 0
    while start < len(lines):
        end = start
        byte_count = 0
        while end < len(lines):
            line_bytes = len(lines[end].encode("utf-8"))
            if end > start and byte_count + line_bytes > limit:
                break
            byte_count += line_bytes
            end += 1
            if byte_count >= limit:
                break
        start_line, end_line = start + 1, end
        result.append(
            SourceChunk(
                f"{path}:{start_line}-{end_line}",
                path,
                start_line,
                end_line,
                "".join(lines[start:end]),
            )
        )
        start = end
    return result


def extraction_passes(
    markdown: dict[str, str], limit: int = MAX_PASS_BYTES
) -> tuple[tuple[SourceChunk, ...], ...]:
    chunks = [chunk for path, text in markdown.items() for chunk in _line_chunks(path, text)]
    passes: list[list[SourceChunk]] = []
    current: list[SourceChunk] = []
    current_bytes = 0
    for chunk in chunks:
        size = len(chunk.text.encode("utf-8"))
        if current and current_bytes + size > limit:
            passes.append(current)
            current, current_bytes = [], 0
        current.append(chunk)
        current_bytes += size
    if current:
        passes.append(current)
    return tuple(tuple(batch) for batch in passes)


def assemble_extraction_prompt(body: str, chunks: tuple[SourceChunk, ...]) -> PromptAssembly:
    schema = {
        "covered": [chunk.chunk_id for chunk in chunks],
        "facts": [
            {
                "type": "one allowed fact type",
                "identifier": "explicit identifier",
                "value": "explicit value or target identifier",
                "source_path": "relative path exactly as supplied",
                "line": 1,
            }
        ],
    }
    parts = [body.rstrip(), "\n\n# Extraction Job\n\n", "Allowed fact types:\n"]
    parts.append(", ".join(sorted(FACT_TYPES)))
    parts.extend([
        "\n\nReturn one JSON object with this shape:\n",
        json.dumps(schema, indent=2),
        "\n\nEvery fact carries exactly these five keys and no others. `line` is a bare JSON "
        "integer inside the cited chunk range, never a string. Facts using any other type, "
        "shape, or citation are discarded.\n",
    ])
    for chunk in chunks:
        parts.extend([
            f'\n<SOURCE chunk_id="{chunk.chunk_id}" path="{chunk.source_path}" '
            f'start_line="{chunk.start_line}" end_line="{chunk.end_line}">\n',
            "```markdown\n",
            chunk.text,
            "" if chunk.text.endswith("\n") else "\n",
            "```\n</SOURCE>\n",
        ])
    return PromptAssembly.single_prompt("".join(parts), label="score spec extraction")


def _json_object(text: str) -> dict[str, object]:
    stripped = _FENCE.sub("", text.strip()).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        # Tolerate a model that wraps the object in commentary; the object itself must still parse.
        invalid = SpecificationError(f"score spec extraction returned invalid JSON: {exc}")
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            raise invalid from exc
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            raise invalid from exc
    if not isinstance(payload, dict) or set(payload) != {"covered", "facts"}:
        raise SpecificationError("score spec extraction must contain exactly 'covered' and 'facts'")
    return payload


def parse_extraction(
    text: str,
    chunks: tuple[SourceChunk, ...],
    *,
    discarded: list[str] | None = None,
) -> tuple[Fact, ...]:
    """Parse one extraction pass.

    Payload-level contract violations are fatal: they mean the pass as a whole is untrustworthy.
    An individual malformed fact is discarded with a recorded reason so one bad record cannot
    destroy an otherwise complete extraction.
    """
    payload = _json_object(text)
    covered = payload["covered"]
    expected_coverage = {chunk.chunk_id for chunk in chunks}
    # Membership is the contract; ordering of the acknowledgement carries no meaning.
    if not isinstance(covered, list) or set(covered) != expected_coverage:
        raise SpecificationError(
            "score spec extraction did not confirm exact source-chunk coverage"
        )
    raw_facts = payload["facts"]
    if not isinstance(raw_facts, list):
        raise SpecificationError("score spec extraction 'facts' must be a list")
    ranges = {chunk.source_path: [] for chunk in chunks}
    for chunk in chunks:
        ranges[chunk.source_path].append((chunk.start_line, chunk.end_line))
    facts: list[Fact] = []
    required = {"type", "identifier", "value", "source_path", "line"}

    def drop(reason: str) -> None:
        if discarded is not None:
            discarded.append(reason)

    for index, raw in enumerate(raw_facts):
        if not isinstance(raw, dict):
            drop("record is not an object")
            continue
        if set(raw) - required:
            # Extra keys mean the model added judgment or commentary the contract prohibits.
            raise SpecificationError(f"score spec fact {index} has an invalid record shape")
        if set(raw) != required:
            drop("record is missing required fields")
            continue
        fact_type = raw["type"]
        identifier = raw["identifier"]
        value = raw["value"]
        source_path = raw["source_path"]
        line = _coerce_line(raw["line"])
        if not isinstance(fact_type, str) or not fact_type.strip():
            drop("type is empty or not a string")
            continue
        if fact_type not in FACT_TYPES:
            drop(f"unknown type {fact_type.strip().lower()!r}")
            continue
        if not all(
            isinstance(item, str) and item.strip() for item in (identifier, value, source_path)
        ):
            drop("identifier, value, or source_path is empty or not a string")
            continue
        if line is None:
            drop("line is not a positive integer")
            continue
        if source_path not in ranges or not any(
            start <= line <= end for start, end in ranges[source_path]
        ):
            drop("path or line falls outside this extraction pass")
            continue
        facts.append(Fact(fact_type, identifier.strip(), value.strip(), source_path, line))
    return tuple(facts)


def _coerce_line(value: object) -> int | None:
    """Accept a positive line number as an integer, an integral float, or a numeric string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 1 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            number = int(text)
            return number if number >= 1 else None
    return None


def summarize_discards(reasons: Iterable[str]) -> tuple[str, ...]:
    """Collapse per-fact discard reasons into stable, counted labels."""
    counts = Counter(reasons)
    return tuple(f"{reason} ({count})" for reason, count in sorted(counts.items()))


def normalize_facts(facts: Iterable[Fact]) -> tuple[Fact, ...]:
    unique = {
        (_normal(f.type), _normal(f.identifier), _normal(f.value), f.source_path, f.line): Fact(
            _normal(f.type), _normal(f.identifier), _normal(f.value), f.source_path, f.line
        )
        for f in facts
    }
    return tuple(
        sorted(
            unique.values(), key=lambda f: (f.type, f.identifier, f.value, f.source_path, f.line)
        )
    )


def activate_profiles(facts: Iterable[Fact]) -> tuple[str, ...]:
    types = {fact.type for fact in facts}
    profiles: list[str] = []
    catalogs = (
        ("web", {"web_surface", "route", "navigation", "navigation_order", "action", "api"}),
        ("service", {"service", "service_consumer"}),
        (
            "database",
            {
                "table",
                "field",
                "data_origin",
                "data_producer",
                "data_source",
                "data_consumer",
                "initial_condition",
            },
        ),
        ("pipeline", {"pipeline", "trigger", "stage", "input", "output", "sink", "checkpoint"}),
        (
            "data-science",
            {
                "dataset",
                "feature",
                "target",
                "training",
                "evaluation",
                "artifact",
                "inference_consumer",
            },
        ),
        ("cli", {"cli"}),
        ("library", {"library", "library_consumer"}),
        ("event-driven", {"event", "event_consumer"}),
        ("batch", {"batch"}),
        ("scheduler", {"scheduler"}),
    )
    for name, evidence in catalogs:
        if types & evidence:
            profiles.append(name)
    return tuple(profiles)


_SEVERITY = {
    "SIDEFX001": "Critical",
    "EXTRACT001": "Low",
    "REF001": "High",
    "DEF001": "Low",
    "CONS001": "Medium",
    "ENTRY001": "Medium",
    "HELP001": "Low",
    "INIT001": "Medium",
    "OWN001": "Medium",
    "SCOPE001": "Medium",
    "INV001": "Low",
    "ROUTE001": "High",
    "ROUTE002": "Low",
    "NAV001": "High",
    "NAV002": "High",
    "NAV003": "High",
    "ACT001": "High",
    "API001": "High",
    "API002": "Medium",
    "SRV001": "High",
    "SRV002": "Medium",
    "DATA001": "High",
    "DATA002": "High",
    "DATA003": "Medium",
    "DATA004": "High",
    "DATA005": "Medium",
    "DATA006": "Medium",
    "PIPE001": "High",
    "PIPE002": "High",
    "PIPE003": "High",
    "PIPE004": "High",
    "PIPE005": "High",
    "PIPE006": "Medium",
    "PIPE007": "Medium",
    "PIPE008": "Medium",
    "DS001": "High",
    "DS002": "High",
    "DS003": "High",
    "DS004": "High",
    "DS005": "Medium",
    "DS006": "High",
    "DS007": "High",
    "CLI001": "High",
    "CLI002": "Medium",
    "LIB001": "Medium",
    "EVT001": "High",
    "EVT002": "Medium",
    "BATCH001": "High",
    "SCHED001": "High",
    "STATE001": "High",
    "STATE002": "Medium",
}


def _fact_map(facts: Iterable[Fact]) -> dict[str, list[Fact]]:
    result: dict[str, list[Fact]] = defaultdict(list)
    for fact in facts:
        result[fact.type].append(fact)
    return result


def _sources(items: Iterable[Fact]) -> tuple[str, ...]:
    return tuple(sorted({item.source_path for item in items}, key=str.casefold))


def evaluate_facts(
    inventory: tuple[SourceRecord, ...],
    facts: tuple[Fact, ...],
    side_effects: tuple[str, ...] = (),
    discards: tuple[str, ...] = (),
) -> tuple[Finding, ...]:
    """Run fixed rule catalogs over normalized facts."""
    by = _fact_map(facts)
    profiles = activate_profiles(facts)
    findings: list[Finding] = []

    def add(code: str, items: Iterable[Fact] | tuple[str, ...], message: str) -> None:
        values = tuple(items)
        paths = values if values and isinstance(values[0], str) else _sources(values)  # type: ignore[arg-type]
        findings.append(Finding(code, _SEVERITY[code], tuple(paths), message))

    if side_effects:
        add("SIDEFX001", side_effects, "the extraction runner modified the guarded Target tree")
    if discards:
        add(
            "EXTRACT001",
            (),
            "extraction emitted malformed facts and they were discarded: " + "; ".join(discards),
        )

    definitions = {f.identifier for f in facts if f.type in _ENTITY_TYPES or f.type == "definition"}
    usages = by["reference"] + by["consumer"]
    for fact in by["reference"]:
        if fact.identifier not in definitions:
            add("REF001", (fact,), f"reference '{fact.identifier}' has no explicit definition")
    for fact in by["consumer"]:
        if fact.identifier not in definitions:
            add(
                "CONS001",
                (fact,),
                f"consumer target '{fact.identifier}' has no explicit definition",
            )
    used = {f.identifier for f in usages}
    for fact in by["definition"]:
        if fact.identifier not in used:
            add("DEF001", (fact,), f"definition '{fact.identifier}' has no explicit reference")
    application_profiles = set(profiles) - {"data-science"}
    all_markdown = tuple(record.path for record in inventory if record.markdown)
    if application_profiles and not by["entry_point"]:
        add("ENTRY001", all_markdown, "activated application surfaces have no explicit entry point")
    if ({"web", "cli"} & set(profiles)) and not by["help"]:
        add("HELP001", all_markdown, "interactive surface has no explicit help behavior")
    if application_profiles and not by["initialization"]:
        add(
            "INIT001",
            all_markdown,
            "activated application surfaces have no initialization contract",
        )
    if by["scope"] and not by["ownership"]:
        add("OWN001", by["scope"], "scope is explicit but ownership is not")
    if by["ownership"] and not by["scope"]:
        add("SCOPE001", by["ownership"], "ownership is explicit but scope is not")
    for record in inventory:
        if record.markdown and record.headings == 0:
            add("INV001", (record.path,), "Markdown source has no explicit heading structure")

    def undefined(ref_type: str, entity_type: str, code: str, label: str) -> None:
        declared = {f.identifier for f in by[entity_type]}
        for fact in by[ref_type]:
            if fact.value not in declared:
                add(
                    code,
                    (fact,),
                    f"{label} '{fact.value}' has no explicit {entity_type} definition",
                )

    def unused(entity_type: str, ref_types: tuple[str, ...], code: str, label: str) -> None:
        referenced = {f.value for kind in ref_types for f in by[kind]}
        for fact in by[entity_type]:
            if fact.identifier not in referenced:
                add(code, (fact,), f"{label} '{fact.identifier}' has no explicit consumer")

    if "web" in profiles:
        undefined("navigation", "route", "NAV001", "navigation destination")
        undefined("action", "route", "ACT001", "action destination")
        route_refs = {f.value for kind in ("navigation", "action") for f in by[kind]}
        for fact in by["reference"]:
            if fact.value == "route" and fact.identifier not in {f.identifier for f in by["route"]}:
                add("ROUTE001", (fact,), f"route '{fact.identifier}' is referenced but undefined")
        for fact in by["route"]:
            if fact.identifier not in route_refs:
                add(
                    "ROUTE002",
                    (fact,),
                    f"route '{fact.identifier}' has no navigation or action consumer",
                )
        for kind, code, label in (
            ("navigation", "NAV002", "membership"),
            ("navigation_order", "NAV003", "order"),
        ):
            grouped: dict[str, list[Fact]] = defaultdict(list)
            for fact in by[kind]:
                grouped[fact.identifier].append(fact)
            for identifier, items in grouped.items():
                if len({item.value for item in items}) > 1:
                    add(
                        code,
                        items,
                        f"navigation {label} for '{identifier}' conflicts across sources",
                    )
        undefined("api_consumer", "api", "API001", "API consumer target")
        unused("api", ("api_consumer",), "API002", "API")

    if "service" in profiles:
        undefined("service_consumer", "service", "SRV001", "service consumer target")
        unused("service", ("service_consumer",), "SRV002", "service")

    if "database" in profiles:
        tables = {f.identifier: f for f in by["table"]}
        table_relations = (
            "field",
            "data_origin",
            "data_producer",
            "data_source",
            "data_consumer",
            "initial_condition",
        )
        for kind in table_relations:
            for fact in by[kind]:
                if fact.identifier not in tables:
                    add("DATA001", (fact,), f"table '{fact.identifier}' is used but not defined")
        for name, table in tables.items():
            related = {
                kind: [f for f in by[kind] if f.identifier == name] for kind in table_relations
            }
            if not related["field"]:
                add("DATA002", (table,), f"table '{name}' has no explicit fields")
            if not related["data_origin"]:
                add("DATA003", (table,), f"table '{name}' has no explicit origin")
            if not (
                related["data_producer"]
                or related["data_source"]
                or any("external" in f.value for f in related["data_origin"])
            ):
                add(
                    "DATA004",
                    (table,),
                    f"table '{name}' has no producer, source, or external origin",
                )
            if not related["data_consumer"]:
                add("DATA005", (table,), f"table '{name}' has no explicit consumer")
            if not related["initial_condition"]:
                add("DATA006", (table,), f"table '{name}' has no explicit initial condition")

    def require_each(
        profile: str, owner_type: str, requirements: tuple[tuple[str, str, str], ...]
    ) -> None:
        if profile not in profiles:
            return
        for owner in by[owner_type]:
            for fact_type, code, label in requirements:
                if not any(f.identifier == owner.identifier for f in by[fact_type]):
                    add(
                        code, (owner,), f"{owner_type} '{owner.identifier}' has no explicit {label}"
                    )

    require_each(
        "pipeline",
        "pipeline",
        (
            ("trigger", "PIPE001", "trigger"),
            ("stage", "PIPE002", "stage"),
            ("input", "PIPE003", "input"),
            ("output", "PIPE004", "output"),
            ("sink", "PIPE005", "sink"),
            ("checkpoint", "PIPE006", "checkpoint"),
            ("schedule", "PIPE007", "schedule"),
            ("consumer", "PIPE008", "consumer"),
        ),
    )
    require_each(
        "data-science",
        "dataset",
        (
            ("feature", "DS001", "features"),
            ("target", "DS002", "target"),
            ("training", "DS003", "training flow"),
            ("evaluation", "DS004", "evaluation"),
            ("artifact", "DS005", "artifact"),
            ("inference_consumer", "DS006", "inference consumer"),
            ("data_origin", "DS007", "origin"),
        ),
    )
    require_each(
        "cli",
        "cli",
        (("entry_point", "CLI001", "entry point"), ("help", "CLI002", "help behavior")),
    )
    require_each("library", "library", (("library_consumer", "LIB001", "consumer"),))
    require_each(
        "event-driven",
        "event",
        (("trigger", "EVT001", "trigger"), ("event_consumer", "EVT002", "consumer")),
    )
    require_each("batch", "batch", (("schedule", "BATCH001", "schedule"),))
    require_each("scheduler", "scheduler", (("schedule", "SCHED001", "schedule"),))

    declared_states = {f.identifier for f in by["state"]}
    for fact in by["state_consumer"]:
        if fact.value not in declared_states:
            add("STATE001", (fact,), f"state '{fact.value}' is consumed but undefined")
    used_states = {f.value for f in by["state_consumer"]}
    for fact in by["state"]:
        if fact.identifier not in used_states:
            add("STATE002", (fact,), f"state '{fact.identifier}' has no explicit consumer")

    return tuple(findings)


def _tree_snapshot(target_dir: Path) -> dict[str, _TreeStamp]:
    snapshot: dict[str, _TreeStamp] = {}
    for path in sorted((p for p in target_dir.rglob("*") if p.is_file()), key=str):
        rel = path.relative_to(target_dir).as_posix()
        if rel == REPORT_NAME:
            continue
        stat = path.stat()
        digest = None
        if path.suffix.casefold() in {".md", ".markdown"}:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[rel] = _TreeStamp(stat.st_size, stat.st_mtime_ns, digest)
    return snapshot


def _changed_paths(before: dict[str, _TreeStamp], after: dict[str, _TreeStamp]) -> tuple[str, ...]:
    return tuple(
        sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    )


def render_report(
    inventory: tuple[SourceRecord, ...],
    findings: tuple[Finding, ...],
    profiles: tuple[str, ...],
    extraction_pass_count: int,
) -> str:
    markdown_count = sum(record.markdown for record in inventory)
    markdown_bytes = sum(record.bytes for record in inventory if record.markdown)
    markdown_lines = sum(record.lines or 0 for record in inventory if record.markdown)
    markdown_headings = sum(record.headings or 0 for record in inventory if record.markdown)
    lines = [
        "# Raw Specification Conformance Scorecard",
        "",
        f"- Inventory: {len(inventory)} files ({markdown_count} Markdown, {len(inventory) - markdown_count} non-Markdown)",
        f"- Markdown coverage: {markdown_bytes} bytes, {markdown_lines} lines, {markdown_headings} headings",
        f"- Extraction passes: {extraction_pass_count}",
        f"- Activated profiles: {', '.join(profiles) if profiles else 'none'}",
        "- Source coverage:",
    ]
    for record in inventory:
        if record.markdown:
            lines.append(
                f"  - `{record.path}` — {record.bytes} bytes, {record.lines} lines, "
                f"{record.headings} headings; content ingested"
            )
        else:
            lines.append(
                f"  - `{record.path}` — {record.bytes} bytes; inventoried without content ingestion"
            )
    lines.extend([
        "",
        "| Severity | Affected Sources | Conflict Discovered |",
        "|---|---|---|",
    ])
    for finding in findings:
        source_text = ", ".join(f"`{path}`" for path in finding.sources) or "—"
        message = finding.message.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {finding.severity} | {source_text} | {finding.code}: {message} |")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.chmod(temporary, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def score_spec(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    model: str | None = None,
    effort: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
    on_text: Callable[[str], None] | None = None,
) -> ScoreSpecResult:
    """Extract raw-source facts, evaluate them, and atomically write the advisory report."""
    sources_dir = target_dir / "blueprint" / "sources"
    inventory, markdown = inventory_sources(sources_dir)
    batches = extraction_passes(markdown)
    prompt = load_prompt(PROMPT_NAME)
    run = runner if runner is not None else run_prompt
    facts: list[Fact] = []
    side_effects: set[str] = set()
    discarded: list[str] = []
    for pass_number, batch in enumerate(batches, start=1):
        assembly = assemble_extraction_prompt(prompt.body, batch)
        before = _tree_snapshot(target_dir)
        result = run(
            assembly.rendered_text,
            target_dir,
            llm=llm_provider,
            model=model or prompt.model,
            effort=effort or prompt.effort,
            command_name="score spec",
            parameters={"target": target, "pass": pass_number, "passes": len(batches)},
            log_dir=log_dir,
            target=target,
            on_text=on_text,
            announce=False,
            prompt_assembly=assembly,
        )
        after = _tree_snapshot(target_dir)
        side_effects.update(_changed_paths(before, after))
        if not result.ok or not result.text.strip():
            raise SpecificationError(
                f"score spec extraction pass {pass_number} failed or returned no output"
            )
        facts.extend(parse_extraction(result.text, batch, discarded=discarded))
    normalized = normalize_facts(facts)
    profiles = activate_profiles(normalized)
    findings = evaluate_facts(
        inventory, normalized, tuple(sorted(side_effects)), summarize_discards(discarded)
    )
    report = render_report(inventory, findings, profiles, len(batches))
    report_path = target_dir / REPORT_NAME
    _atomic_write(report_path, report)
    return ScoreSpecResult(
        report_path,
        report,
        inventory,
        normalized,
        findings,
        profiles,
        len(batches),
    )
