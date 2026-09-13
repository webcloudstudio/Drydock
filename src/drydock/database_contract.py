"""Typed Blueprint contracts for encapsulated relational persistence.

``DATABASE.md`` owns the public repository operations.  Feature Blueprints only name those
operations through ``## Database Interface``; tables and Alembic implementation remain private.
Migration records under ``blueprint/migrations/`` are Drydock's planned/built ledger.  They are
not executable Alembic files and therefore never claim that a deployed database was upgraded.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from drydock.errors import SpecificationError

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+([A-Z][A-Z0-9-]*-\d{3})\s+—\s+(.+?)\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
_INPUT_OUTPUT_RE = re.compile(r"^(Input|Output):\s*(.+?)\s*$", re.MULTILINE)
_INTERFACE_RE = re.compile(
    r"^\s*-\s+`(?P<id>[A-Z][A-Z0-9-]*-\d{3})`\s+—\s+"
    r"(?P<access>read|write)\s*:\s*.*?\s+-\s+supplies:\s*(?P<input>.*?)"
    r"\s+-\s+returns:\s*(?P<output>.*?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_MIGRATION_FILE_RE = re.compile(
    r"^MIGRATION-(?:(?P<ticket>TICKET-\d+)-)?(?P<scope>[A-Z][A-Z0-9-]*(?:-\d{3})?)\.md$"
)
_OPERATION_ID_RE = re.compile(r"\b([A-Z][A-Z0-9-]*-\d{3})\b")
_COMPATIBILITY = frozenset({"unchanged", "data", "rebuild"})
_MIGRATION_STATES = frozenset({"planned", "built", "applied"})


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool = False


@dataclass(frozen=True)
class AccessPattern:
    identifier: str
    owner: str
    access: str
    repository_operation: str
    compatibility: str
    input_name: str
    inputs: tuple[Field, ...]
    output_name: str
    outputs: tuple[Field, ...]


@dataclass(frozen=True)
class DatabaseContract:
    patterns: tuple[AccessPattern, ...]

    def by_id(self) -> dict[str, AccessPattern]:
        return {item.identifier: item for item in self.patterns}


@dataclass(frozen=True)
class DatabaseUse:
    identifier: str
    access: str
    supplies: tuple[str, ...]
    returns: tuple[str, ...]


@dataclass(frozen=True)
class MigrationRecord:
    path: Path
    access_pattern: str
    revision: str
    compatibility: str
    state: str
    ticket_id: str = ""


def database_operation_fingerprints(text: str) -> str:
    """Serialize the public persistence contract for the applied-spec registry.

    The serialized value is deliberately token-safe because it lives inside the
    Manifest's compact ``applied_specs`` registry.  It excludes every private
    DATABASE section, so a repository/schema/migration edit cannot invalidate a
    Feature merely by changing DATABASE.md's file digest.
    """
    contract = parse_database_contract(text)
    entries: list[str] = []
    for pattern in contract.patterns:
        payload = "\x1f".join((
            pattern.identifier,
            pattern.owner,
            pattern.access,
            pattern.repository_operation,
            pattern.compatibility,
            pattern.input_name,
            *(f"{field.name}:{field.type}:{int(field.required)}" for field in pattern.inputs),
            pattern.output_name,
            *(f"{field.name}:{field.type}" for field in pattern.outputs),
        ))
        entries.append(f"{pattern.identifier}:{sha256(payload.encode()).hexdigest()}")
    return ";".join(entries)


def parse_database_operation_fingerprints(value: str) -> dict[str, str]:
    """Read the compact public-contract snapshot recorded in ``applied_specs``."""
    result: dict[str, str] = {}
    for item in value.split(";"):
        identifier, separator, fingerprint = item.partition(":")
        if (
            not separator
            or not _OPERATION_ID_RE.fullmatch(identifier)
            or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
        ):
            continue
        result[identifier] = fingerprint
    return result


def _section(text: str, heading: str) -> str:
    match = next((m for m in _SECTION_RE.finditer(text) if m.group(1).strip() == heading), None)
    if match is None:
        return ""
    next_match = _SECTION_RE.search(text, match.end())
    return text[match.end() : next_match.start() if next_match else len(text)]


def _rows(text: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        left, right = (part.strip() for part in match.groups())
        if left.casefold() == "field" or set(left) <= {"-", ":"}:
            continue
        result.append((left, right))
    return result


def _field_table(text: str, start: int) -> tuple[Field, ...]:
    fields: list[Field] = []
    seen_table = False
    for line in text[start:].splitlines():
        stripped = line.strip()
        if not stripped:
            if seen_table:
                break
            continue
        if not stripped.startswith("|"):
            if seen_table:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells[0].casefold() == "field" or set(cells[0]) <= {"-", ":"}:
            seen_table = True
            continue
        if len(cells) < 2:
            continue
        seen_table = True
        fields.append(
            Field(
                name=cells[0].strip("`"),
                type=cells[1].strip("`"),
                required=len(cells) > 2 and cells[2].casefold() in {"yes", "true", "required"},
            )
        )
    return tuple(fields)


def parse_database_contract(text: str, *, source: str = "DATABASE.md") -> DatabaseContract:
    """Parse the public operation surface from a DATABASE Blueprint."""
    access_patterns = _section(text, "Access Patterns")
    if not access_patterns.strip():
        raise SpecificationError(f"{source}: missing required ## Access Patterns section")
    patterns: list[AccessPattern] = []
    matches = list(_H3_RE.finditer(access_patterns))
    if not matches:
        raise SpecificationError(f"{source}: ## Access Patterns has no named operation")
    for index, match in enumerate(matches):
        block = access_patterns[
            match.end() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(access_patterns)
        ]
        metadata = {key.casefold(): value for key, value in _rows(block)}
        missing = [
            label
            for label in ("owner", "access", "repository operation", "compatibility")
            if not metadata.get(label)
        ]
        if missing:
            raise SpecificationError(
                f"{source}: {match.group(1)} missing access-pattern field(s): {', '.join(missing)}"
            )
        access = metadata["access"].casefold()
        compatibility = metadata["compatibility"].casefold()
        if access not in {"read", "write"}:
            raise SpecificationError(f"{source}: {match.group(1)} has invalid Access: {access}")
        if compatibility not in _COMPATIBILITY:
            raise SpecificationError(
                f"{source}: {match.group(1)} has invalid Compatibility: {compatibility}"
            )
        io = list(_INPUT_OUTPUT_RE.finditer(block))
        values: dict[str, tuple[str, tuple[Field, ...]]] = {}
        for io_match in io:
            values[io_match.group(1).casefold()] = (
                io_match.group(2).strip("` "),
                _field_table(block, io_match.end()),
            )
        if "input" not in values or "output" not in values:
            raise SpecificationError(f"{source}: {match.group(1)} requires Input and Output tables")
        patterns.append(
            AccessPattern(
                identifier=match.group(1),
                owner=metadata["owner"].strip(),
                access=access,
                repository_operation=metadata["repository operation"].strip("`"),
                compatibility=compatibility,
                input_name=values["input"][0],
                inputs=values["input"][1],
                output_name=values["output"][0],
                outputs=values["output"][1],
            )
        )
    ids = [pattern.identifier for pattern in patterns]
    if len(ids) != len(set(ids)):
        raise SpecificationError(f"{source}: duplicate access-pattern identifier")
    return DatabaseContract(tuple(patterns))


def parse_database_interface(text: str, *, source: str = "Blueprint") -> tuple[DatabaseUse, ...]:
    """Read a Blueprint's optional database-interface declaration."""
    section = _section(text, "Database Interface")
    if not section.strip():
        return ()
    uses: list[DatabaseUse] = []
    for match in _INTERFACE_RE.finditer(section):
        uses.append(
            DatabaseUse(
                identifier=match.group("id"),
                access=match.group("access").casefold(),
                supplies=_names(match.group("input")),
                returns=_names(match.group("output")),
            )
        )
    if not uses:
        raise SpecificationError(f"{source}: malformed ## Database Interface entry")
    return tuple(uses)


def _names(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip().strip("`") for item in value.split(",") if item.strip() and item.strip() != "—"
    )


def validate_database_interfaces(
    contract: DatabaseContract, interfaces: Mapping[str, Iterable[DatabaseUse]]
) -> None:
    """Reject feature contracts that escape the declared persistence API."""
    patterns = contract.by_id()
    for blueprint, uses in interfaces.items():
        for use in uses:
            pattern = patterns.get(use.identifier)
            if pattern is None:
                raise SpecificationError(
                    f"{blueprint}: unknown database operation {use.identifier}"
                )
            if pattern.owner != blueprint:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} is owned by {pattern.owner}, not this Blueprint"
                )
            if use.access != pattern.access:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} declares {use.access}, expected {pattern.access}"
                )
            allowed_input = {field.name for field in pattern.inputs}
            allowed_output = {field.name for field in pattern.outputs}
            required_input = {field.name for field in pattern.inputs if field.required}
            supplied, returned = set(use.supplies), set(use.returns)
            if unknown := supplied - allowed_input:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} supplies undeclared field(s): {', '.join(sorted(unknown))}"
                )
            if missing := required_input - supplied:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} omits required field(s): {', '.join(sorted(missing))}"
                )
            if unknown := returned - allowed_output:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} returns undeclared field(s): {', '.join(sorted(unknown))}"
                )


def migration_records(blueprint_dir: Path) -> tuple[MigrationRecord, ...]:
    """Load Blueprint migration ledger records. Missing ledger means no staged migration."""
    directory = blueprint_dir / "migrations"
    if not directory.is_dir():
        return ()
    records: list[MigrationRecord] = []
    for path in sorted(directory.glob("MIGRATION-*.md")):
        match = _MIGRATION_FILE_RE.match(path.name)
        if match is None:
            continue
        text = path.read_text(encoding="utf-8")
        rows = {key.casefold(): value for key, value in _rows(text)}
        scope = match.group("scope")
        access_pattern = rows.get("access pattern", scope).strip()
        compatibility = rows.get("compatibility", "").casefold()
        state = rows.get("state", "planned").casefold()
        if access_pattern != scope:
            raise SpecificationError(f"{path}: Access Pattern must match its filename scope")
        if compatibility not in _COMPATIBILITY or state not in _MIGRATION_STATES:
            raise SpecificationError(f"{path}: invalid Compatibility or State")
        if not _section(text, "Upgrade").strip() or not _section(text, "Downgrade").strip():
            raise SpecificationError(f"{path}: requires ## Upgrade and ## Downgrade snippets")
        records.append(
            MigrationRecord(
                path,
                access_pattern,
                rows.get("revision", "").strip(),
                compatibility,
                state,
                rows.get("Ticket", match.group("ticket") or "").strip(),
            )
        )
    return tuple(records)


def staged_operation_ids(blueprint_dir: Path) -> tuple[str, ...]:
    """Operations with a migration not yet built into the generated application."""
    return tuple(
        record.access_pattern
        for record in migration_records(blueprint_dir)
        if record.state == "planned"
    )


def mark_migrations_built(blueprint_dir: Path) -> tuple[Path, ...]:
    """Advance planned ledger records after their DATABASE build story completes."""
    changed: list[Path] = []
    for record in migration_records(blueprint_dir):
        if record.state != "planned":
            continue
        text = record.path.read_text(encoding="utf-8")
        updated, count = re.subn(r"(?m)^(\|\s*State\s*\|\s*)planned(\s*\|\s*)$", r"\1built\2", text)
        if count != 1:
            raise SpecificationError(f"{record.path}: requires one State row")
        record.path.write_text(updated, encoding="utf-8", newline="\n")
        changed.append(record.path)
    return tuple(changed)


def create_ticket_migration_records(
    blueprint_dir: Path, ticket_texts: Iterable[str | Path]
) -> tuple[Path, ...]:
    """Create planned ledger records for DATABASE ticket operations not already recorded.

    A ticket names affected operation ids; its migration blocks remain intentionally skeletal
    until the DATABASE build story renders the application-specific Alembic directives.
    """
    database_path = blueprint_dir / "DATABASE.md"
    if not database_path.is_file() or "## Access Patterns" not in database_path.read_text(
        encoding="utf-8"
    ):
        return ()
    contract = parse_database_contract(database_path.read_text(encoding="utf-8"))
    patterns = contract.by_id()
    requested: list[tuple[str, str, str]] = []
    for source in ticket_texts:
        path = source if isinstance(source, Path) else None
        text = path.read_text(encoding="utf-8") if path is not None else source
        ticket_match = re.search(r"^drydock_id:\s*(TICKET-\d+)", text, re.MULTILINE)
        ticket_id = ticket_match.group(1) if ticket_match else ""
        kind_match = re.search(r"^drydock_kind:\s*(\S+)", text, re.MULTILINE)
        kind = kind_match.group(1) if kind_match else "database-access-pattern"
        compatibility_match = re.search(r"^drydock_compatibility:\s*(\S+)", text, re.MULTILINE)
        compatibility = compatibility_match.group(1) if compatibility_match else ""
        amends_match = re.search(r"^drydock_amends:\s*(\S+)", text, re.MULTILINE)
        amended_ids = (
            set(_OPERATION_ID_RE.findall(amends_match.group(1))) & set(patterns)
            if amends_match
            else set()
        )
        operation_ids = (
            sorted(amended_ids)
            if amended_ids
            else sorted(set(_OPERATION_ID_RE.findall(text)) & set(patterns))
        )
        if kind == "database-access-pattern" and operation_ids:
            for identifier in operation_ids:
                requested.append((
                    ticket_id,
                    identifier,
                    compatibility or patterns[identifier].compatibility,
                ))
        elif kind in {"database-private", "database-data"} and ticket_id:
            requested.append((
                ticket_id,
                "DATABASE",
                "data" if kind == "database-data" else "rebuild",
            ))

    existing = {
        (record.ticket_id, record.access_pattern) for record in migration_records(blueprint_dir)
    }
    directory = blueprint_dir / "migrations"
    created: list[Path] = []
    for ticket_id, identifier, compatibility in requested:
        identity = (ticket_id, identifier)
        if identity in existing:
            continue
        path = directory / (
            f"MIGRATION-{ticket_id}-{identifier}.md" if ticket_id else f"MIGRATION-{identifier}.md"
        )
        directory.mkdir(parents=True, exist_ok=True)
        revision = "_".join(part.casefold() for part in (ticket_id, identifier) if part).replace(
            "-", "_"
        )
        ticket_row = f"| Ticket | {ticket_id} |\n" if ticket_id else ""
        path.write_text(
            f"# Migration: {ticket_id + ' ' if ticket_id else ''}{identifier}\n\n"
            "| Field | Value |\n"
            "|---|---|\n" + ticket_row + f"| Access Pattern | {identifier} |\n"
            f"| Revision | {revision} |\n"
            f"| Compatibility | {compatibility} |\n"
            "| State | planned |\n\n"
            "## Upgrade\n\n"
            "```python\n"
            f"# Implement the {identifier} schema change with Alembic op directives.\n"
            "```\n\n"
            "## Downgrade\n\n"
            "```python\n"
            f"# Reverse the {identifier} schema change when supported.\n"
            "```\n",
            encoding="utf-8",
            newline="\n",
        )
        created.append(path)
        existing.add(identity)
    return tuple(created)


def changed_operation_ids_since(blueprint_dir: Path, commit: str) -> tuple[str, ...] | None:
    """Compare DATABASE access patterns to the applied Git revision when it is available.

    ``None`` represents an unavailable Git baseline, not an empty diff. Callers still use the
    Blueprint migration ledger in that case, which keeps non-Git Targets deterministic.
    """
    if not commit or commit == "-":
        return None
    database_path = blueprint_dir / "DATABASE.md"
    if not database_path.is_file():
        return None
    root = subprocess.run(
        ["git", "-C", str(blueprint_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if root.returncode:
        return None
    root_path = Path(root.stdout.strip())
    try:
        relative = database_path.relative_to(root_path).as_posix()
    except ValueError:
        return None
    prior = subprocess.run(
        ["git", "-C", str(root_path), "show", f"{commit}:{relative}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if prior.returncode:
        return None
    old = parse_database_contract(prior.stdout, source=f"{commit}:{relative}").by_id()
    current = parse_database_contract(database_path.read_text(encoding="utf-8")).by_id()
    return tuple(
        sorted(
            identifier
            for identifier in set(old) | set(current)
            if old.get(identifier) != current.get(identifier)
        )
    )
