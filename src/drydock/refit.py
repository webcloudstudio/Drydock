"""``drydock refit`` — reconcile Blueprint edits and optional change tickets into a build.

Each ``TICKET-NNN-{Name}.md`` file is read, its typed spec header is normalized (``Amends:``,
``Depends On:``, ``Version:``), stories and ACs are generated or refined, and MANIFEST.md is
patched with new story rows for those tickets. Independently, deterministic drift reconciliation
compares every ``applied_specs`` record against the current Blueprint content. Every changed
Blueprint resets its consumer blocks and their transitive dependents to ``pending`` and drops
stale provenance, so direct Blueprint authoring continues with the appropriate build frontier.
``DATABASE.md`` retains its operation-level invalidation policy. Tests inject a fake runner
instead of spending API credits.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock.artifact_blocks import RESERVED_BLOCK_NAMESPACE
from drydock.build_plan import (
    cascade_reset_from_ids,
    cascade_reset_ids,
    foundational_source,
    parse_build_plan,
    set_applied_specs,
    stale_applied_specs,
)
from drydock.change_ticket import parse_ticket_header
from drydock.database_contract import (
    changed_operation_contracts,
    changed_operation_ids_since,
    create_ticket_migration_records,
    parse_database_contract,
    parse_database_interface,
    parse_database_operation_fingerprints,
    staged_operation_ids,
    validate_database_interfaces,
)
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.manifest_edit import batch_set_block_fields
from drydock.normalized_ticket import (
    next_ticket_id,
    parse_normalized_ticket,
    render_normalized_ticket,
    set_normalized_ticket_status,
    split_front_matter,
    ticket_slug,
)
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

PROMPT_NAME = "refit"

# Reserves the nested ``=== AC <id> ===`` proof namespace out of the envelope grammar; see
# ``artifact_blocks``.
_BLOCK_RE = re.compile(
    rf"=== {RESERVED_BLOCK_NAMESPACE}(.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL
)
_BLOCK_START_RE = re.compile(r"^## \w[^:]*:\s+.+", re.MULTILINE)
_BLOCK_ID_RE = re.compile(r"^id:\s+(\S+)", re.MULTILINE)
_AMENDS_TABLE_RE = re.compile(r"\|\s*Amends\s*\|\s*([^|]+)\|")
_AMENDS_BARE_RE = re.compile(r"^Amends:\s*(\S+)", re.MULTILINE)
_DRYDOCK_AMENDS_RE = re.compile(r"^drydock_amends:\s*(\S+)", re.MULTILINE)
_DEPENDS_ON_RE = re.compile(r"\|\s*Depends On\s*\|\s*([^|]+)\|")
_BLUEPRINT_COMMENT_RE = re.compile(r"<!--\s*(?P<text>.*?)\s*-->", re.DOTALL)


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class RefitItem:
    ticket: Path
    # "conformed" | "skipped-no-amends" | "failed"
    status: str
    execution_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RefitReset:
    """One drifted Blueprint file and the manifest blocks reset for its rebuild."""

    path: str
    foundational: bool
    reset_ids: tuple[str, ...]


@dataclass(frozen=True)
class RefitResult:
    target_dir: Path
    items: list[RefitItem]
    resets: list[RefitReset] = field(default_factory=list)
    drift_errors: list[str] = field(default_factory=list)

    def conformed(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "conformed"]

    def skipped(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "skipped-no-amends"]

    def failed(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() or self.drift_errors else 0


def _parse_amends(ticket_text: str) -> str | None:
    """Extract Amends field value from a ticket. Checks header table then bare line."""
    m = _DRYDOCK_AMENDS_RE.search(ticket_text)
    if m:
        return m.group(1).strip()
    m = _AMENDS_TABLE_RE.search(ticket_text)
    if m:
        return m.group(1).strip()
    m = _AMENDS_BARE_RE.search(ticket_text)
    if m:
        return m.group(1).strip()
    return None


def _match_source_ticket(ticket_path: Path, ticket_text: str, blueprint_dir: Path) -> str | None:
    """Return the one Blueprint a raw ticket can deterministically amend."""
    front_matter = split_front_matter(ticket_text)
    explicit = front_matter.fields.get("amends") or _parse_amends(ticket_text)
    if explicit:
        return explicit if (blueprint_dir / explicit.split("#", 1)[0]).is_file() else None
    haystack = " ".join((ticket_path.stem, *front_matter.fields.values(), ticket_text))
    named = [
        path.name
        for path in blueprint_dir.glob("*.md")
        if path.stem.casefold() in haystack.casefold()
    ]
    if len(named) == 1:
        return named[0]
    operation_ids = set(re.findall(r"\b[A-Z][A-Z0-9-]*-\d{3}\b", haystack))
    database = blueprint_dir / "DATABASE.md"
    if (
        operation_ids
        and database.is_file()
        and "## Access Patterns" in database.read_text(encoding="utf-8")
    ):
        if operation_ids & set(
            parse_database_contract(database.read_text(encoding="utf-8")).by_id()
        ):
            return "DATABASE.md#Access-Patterns"
    # Textual matching is intentionally conservative: an exact title token match
    # is useful for raw tickets, while a tie remains a Commander-visible blocker.
    source_words = {
        word.casefold()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", haystack)
        if word.casefold() not in {"change", "feature", "ticket", "blueprint", "please"}
    }
    scored = []
    for path in blueprint_dir.glob("*.md"):
        words = set(re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", path.read_text(encoding="utf-8")))
        score = len(source_words & {word.casefold() for word in words})
        if score:
            scored.append((score, path.name))
    if not scored:
        return None
    best = max(score for score, _ in scored)
    candidates = [name for score, name in scored if score == best]
    return candidates[0] if best >= 2 and len(candidates) == 1 else None


def _database_ticket_fields(blueprint_dir: Path, amends: str, text: str) -> tuple[str, str | None]:
    """Classify a DATABASE ticket without exposing private schema detail to Features."""
    if amends.split("#", 1)[0] != "DATABASE.md":
        return "blueprint", None
    database = blueprint_dir / "DATABASE.md"
    if not database.is_file() or "## Access Patterns" not in database.read_text(encoding="utf-8"):
        return "database-private", None
    contract = parse_database_contract(database.read_text(encoding="utf-8"))
    matched = set(re.findall(r"\b[A-Z][A-Z0-9-]*-\d{3}\b", text)) & set(contract.by_id())
    if len(matched) == 1:
        pattern = contract.by_id()[next(iter(matched))]
        return "database-access-pattern", pattern.compatibility
    return "database-private", None


def _normalize_source_tickets(
    changes_dir: Path, blueprint_dir: Path
) -> tuple[list[RefitItem], list[str]]:
    """Create normalized tickets for raw files and retain unmatched source diagnostics."""
    if not changes_dir.is_dir():
        return [], []
    existing_refs = {
        normalized.drydock_fields["drydock_source_ref"]
        for path in changes_dir.glob("TICKET-*.md")
        if (normalized := parse_normalized_ticket(path)) is not None
    }
    items: list[RefitItem] = []
    errors: list[str] = []
    for path in sorted(p for p in changes_dir.glob("*.md") if p.is_file()):
        text = path.read_text(encoding="utf-8")
        if parse_normalized_ticket(path) is not None:
            continue
        source_ref = f"{path.name}#{hashlib.sha256(text.encode()).hexdigest()[:12]}"
        if source_ref in existing_refs:
            continue
        amends = _match_source_ticket(path, text, blueprint_dir)
        if not amends:
            error = f"{path.name}: cannot match ticket to one Blueprint"
            errors.append(error)
            items.append(RefitItem(ticket=path, status="failed", error=error))
            continue
        ticket_id = next_ticket_id(changes_dir)
        destination = changes_dir / f"{ticket_id}-{ticket_slug(path.stem)}.md"
        kind, compatibility = _database_ticket_fields(blueprint_dir, amends, text)
        try:
            destination.write_text(
                render_normalized_ticket(
                    path,
                    text,
                    ticket_id=ticket_id,
                    amends=amends,
                    kind=kind,
                    compatibility=compatibility,
                    source_ref=source_ref,
                ),
                encoding="utf-8",
                newline="\n",
            )
        except SpecificationError as exc:
            error = f"{path.name}: {exc}"
            errors.append(error)
            items.append(RefitItem(ticket=path, status="failed", error=error))
            continue
        items.append(RefitItem(ticket=destination, status="conformed"))
    return items, errors


def _normalize_blueprint_comments(
    blueprint_dir: Path, changes_dir: Path
) -> tuple[list[RefitItem], set[str]]:
    """Turn ordinary Feature Blueprint HTML comments into one ticket each."""
    existing_refs = {
        normalized.drydock_fields["drydock_source_ref"]
        for path in changes_dir.glob("TICKET-*.md")
        if (normalized := parse_normalized_ticket(path)) is not None
    }
    items: list[RefitItem] = []
    commented: set[str] = set()
    for path in sorted(blueprint_dir.glob("FEATURE-*.md")):
        for match in _BLUEPRINT_COMMENT_RE.finditer(path.read_text(encoding="utf-8")):
            comment = match.group("text").strip()
            if not comment:
                continue
            source_ref = f"{path.name}#comment-{hashlib.sha256(comment.encode()).hexdigest()[:12]}"
            commented.add(path.name)
            if source_ref in existing_refs:
                continue
            ticket_id = next_ticket_id(changes_dir)
            destination = changes_dir / f"{ticket_id}-{ticket_slug(comment)}.md"
            source_text = f"# Blueprint comment: {path.name}\n\n{comment}\n"
            destination.write_text(
                render_normalized_ticket(
                    path,
                    source_text,
                    ticket_id=ticket_id,
                    amends=path.name,
                    source_ref=source_ref,
                    source_kind="blueprint-comment",
                ),
                encoding="utf-8",
                newline="\n",
            )
            items.append(RefitItem(ticket=destination, status="conformed"))
    return items, commented


def _normalize_blueprint_drift(
    manifest_path: Path,
    blueprint_dir: Path,
    changes_dir: Path,
    *,
    commented_blueprints: set[str] | None = None,
) -> list[RefitItem]:
    """Represent each directly changed applied Blueprint as a normalized ticket."""
    if not manifest_path.is_file():
        return []
    plan = parse_build_plan(manifest_path)
    items: list[RefitItem] = []
    existing_refs = {
        normalized.drydock_fields["drydock_source_ref"]
        for path in changes_dir.glob("TICKET-*.md")
        if (normalized := parse_normalized_ticket(path)) is not None
    }
    for stale in stale_applied_specs(plan, blueprint_dir):
        source_path = blueprint_dir / stale.rel_path
        if not source_path.is_file():
            continue
        if stale.rel_path in (commented_blueprints or set()):
            continue
        source_text = source_path.read_text(encoding="utf-8")
        if stale.rel_path == "DATABASE.md" and "## Access Patterns" in source_text:
            record = plan.applied_specs.get("DATABASE.md")
            prior = (
                parse_database_operation_fingerprints(record.database_operations) if record else {}
            )
            changed = sorted(changed_operation_contracts(prior, source_text))
            if changed:
                contract = parse_database_contract(source_text).by_id()
                for identifier in changed:
                    source_ref = f"DATABASE.md#{identifier}:{stale.current_sha256[:12]}"
                    if source_ref in existing_refs:
                        continue
                    ticket_id = next_ticket_id(changes_dir)
                    destination = changes_dir / f"{ticket_id}-{ticket_slug(identifier)}.md"
                    compatibility = (
                        contract.get(identifier).compatibility
                        if identifier in contract
                        else "rebuild"
                    )
                    destination.write_text(
                        render_normalized_ticket(
                            source_path,
                            f"# Database access pattern change: {identifier}\n\n{source_text}",
                            ticket_id=ticket_id,
                            amends=f"DATABASE.md#Access-Patterns/{identifier}",
                            kind="database-access-pattern",
                            compatibility=compatibility,
                            source_ref=source_ref,
                            source_kind="blueprint-diff",
                        ),
                        encoding="utf-8",
                        newline="\n",
                    )
                    items.append(RefitItem(ticket=destination, status="conformed"))
                continue
        ticket_id = next_ticket_id(changes_dir)
        source_ref = f"{stale.rel_path}#{stale.current_sha256[:12]}"
        if source_ref in existing_refs:
            continue
        destination = changes_dir / f"{ticket_id}-{ticket_slug(stale.rel_path)}.md"
        evidence = (
            f"# Blueprint change: {stale.rel_path}\n\n"
            "The current Blueprint content differs from the previously applied Blueprint state.\n\n"
            f"{source_text}"
        )
        destination.write_text(
            render_normalized_ticket(
                source_path,
                evidence,
                ticket_id=ticket_id,
                amends=stale.rel_path,
                kind=(
                    "database-private"
                    if stale.rel_path == "DATABASE.md" and "## Access Patterns" in source_text
                    else "blueprint"
                ),
                source_ref=source_ref,
                source_kind="blueprint-diff",
            ),
            encoding="utf-8",
            newline="\n",
        )
        items.append(RefitItem(ticket=destination, status="conformed"))
    return items


def _attach_change_context(
    manifest_path: Path, changes_dir: Path, resets: Sequence[RefitReset]
) -> None:
    """Attach generated direct-edit and Blueprint-comment tickets to build context."""
    if not manifest_path.is_file() or not resets:
        return
    by_blueprint: dict[str, list[str]] = {}
    for path in changes_dir.glob("TICKET-*.md"):
        normalized = parse_normalized_ticket(path)
        if normalized and normalized.drydock_fields["drydock_source"] in {
            "blueprint-diff",
            "blueprint-comment",
        }:
            by_blueprint.setdefault(normalized.amends.split("#", 1)[0], []).append(
                f"changes/{path.name}"
            )
    if not by_blueprint:
        return
    plan = parse_build_plan(manifest_path)
    by_id = plan.by_id()
    updates: dict[str, dict[str, str | None]] = {}
    for reset in resets:
        tickets = by_blueprint.get(reset.path)
        if not tickets:
            continue
        for block_id in reset.reset_ids:
            block = by_id.get(block_id)
            if block is None:
                continue
            current = tuple(block.fields.get("context", ()))
            additions = tuple(ticket for ticket in tickets if ticket not in current)
            if additions:
                updates[block_id] = {"context": ", ".join((*current, *additions))}
    if updates:
        batch_set_block_fields(manifest_path, updates)


def _parse_parent_depends(parent_text: str) -> list[str]:
    """Read the Depends On field from a parent spec header table."""
    m = _DEPENDS_ON_RE.search(parent_text)
    if not m:
        return []
    raw = m.group(1).strip()
    return [f.strip() for f in raw.split(",") if f.strip()]


def _resolve_ticket_deps(amends: str, blueprint_dir: Path) -> list[str]:
    """Return [parent_spec] + parent's Depends On list (deterministic, no LLM).

    If the parent spec is absent, returns [amends] only rather than failing.
    """
    parent_path = blueprint_dir / amends.split("#", 1)[0]
    if not parent_path.is_file():
        return [amends]
    parent_text = parent_path.read_text(encoding="utf-8")
    parent_deps = _parse_parent_depends(parent_text)
    return [amends] + [d for d in parent_deps if d != amends]


def _assemble_refit_prompt(
    body: str,
    *,
    ticket_filename: str,
    ticket_text: str,
    parent_filename: str,
    parent_text: str,
    resolved_deps: list[str],
    today: str,
    scope: str = "amending",
    declared_stories: Sequence[str] = (),
) -> PromptAssembly:
    """Build the per-ticket PromptAssembly: system preamble + job block + content + body.

    ``STORY_IDS`` is what keeps re-conforming idempotent. ``refit_target`` reprocesses every
    ticket in ``changes/`` on every run, including tickets a previous run already conformed. A
    source-authored ticket already owns named stories in the Manifest, so unless those ids are
    handed back to the model it will invent fresh ones and ``_patch_manifest`` will append
    duplicates instead of replacing in place.
    """
    deps_str = ", ".join(resolved_deps) if resolved_deps else "(none)"
    job_lines = [
        "## Refit job",
        "",
        f"- TICKET_PATH: changes/{ticket_filename}",
        f"- DATE: {today}",
        f"- AMENDS: {parent_filename}",
        f"- DEPENDS_ON: {deps_str}",
        f"- SCOPE: {scope}",
    ]
    if declared_stories:
        job_lines.append(f"- STORY_IDS: {', '.join(declared_stories)}")
    job_lines.append("")
    return PromptAssembly(
        parts=(
            system_preamble_part(),
            section_heading_part("# Input Context"),
            lines_part("Refit job", job_lines, kind="job"),
            *contextual_markdown_parts(
                f"changes/{ticket_filename}",
                ticket_text,
                filename=ticket_filename,
                role="change ticket",
            ),
            *contextual_markdown_parts(
                parent_filename,
                parent_text,
                filename=parent_filename,
                role="parent spec",
            ),
            section_heading_part("# Agent Task"),
            part("Prompt body", body + "\n\n", kind="prompt-body"),
        )
    )


def _parse_refit_output(
    text: str, ticket_filename: str
) -> tuple[str | None, str | None, str | None]:
    """Extract ticket content and MANIFEST_ROWS from LLM output.

    Returns (ticket_content, manifest_rows, error_message).
    error_message is set when REFIT_ERROR.txt is present or output is malformed.
    """
    blocks = {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}

    if "REFIT_ERROR.txt" in blocks:
        return None, None, blocks["REFIT_ERROR.txt"]

    ticket_key = f"changes/{ticket_filename}"
    ticket_content = blocks.get(ticket_key)
    manifest_rows = blocks.get("MANIFEST_ROWS")

    if ticket_content is None and manifest_rows is None:
        return None, None, "LLM output contained no recognized artifact blocks"

    return ticket_content, manifest_rows, None


def _split_manifest_blocks(rows_text: str) -> list[str]:
    """Split MANIFEST_ROWS content into individual block strings."""
    parts = re.split(r"(?=^## )", rows_text.strip(), flags=re.MULTILINE)
    return [p for p in parts if p.strip() and p.lstrip().startswith("##")]


def _find_block_boundaries(text: str, block_id: str) -> tuple[int, int] | None:
    """Return (start, end) character offsets of the block with the given id, or None."""
    starts = [m.start() for m in _BLOCK_START_RE.finditer(text)]
    starts.append(len(text))

    for i, start in enumerate(starts[:-1]):
        end = starts[i + 1]
        block_text = text[start:end]
        id_match = _BLOCK_ID_RE.search(block_text)
        if id_match and id_match.group(1) == block_id:
            return start, end
    return None


def _patch_manifest(manifest_path: Path, new_rows: str) -> None:
    """Insert or update manifest rows.

    Rules:
    - closed/verified rows are left untouched.
    - pending/implemented rows with the same id are replaced.
    - New ids are appended.
    - The applied_specs block is never touched (it is in the preamble, not a ## block).
    """
    if not manifest_path.is_file() or not new_rows.strip():
        return

    from drydock.manifest import DrydockManifest

    graph = DrydockManifest.load(manifest_path, compatibility=True)
    new_blocks = _split_manifest_blocks(new_rows)
    replacement_ids: list[str] = []
    for block_text in new_blocks:
        id_match = _BLOCK_ID_RE.search(block_text)
        if not id_match:
            continue
        replacement_ids.append(id_match.group(1))
    if not replacement_ids:
        return

    # Parse one complete candidate graph so row references are resolved together.
    retained = [
        "\n".join(node.lines) for node in graph.blocks if node.block_id not in set(replacement_ids)
    ]
    candidate_text = "\n".join(graph.preamble).rstrip()
    candidate_text += "\n\n" + "\n\n".join([*retained, *new_blocks]) + "\n"
    proposed = DrydockManifest.parse(candidate_text, source=manifest_path, compatibility=True)

    proposed_by_id = proposed.by_id()
    for block_id in replacement_ids:
        node = proposed_by_id[block_id]
        if block_id in graph.by_id():
            graph.replace(block_id, node, preserve_verified=True)
        else:
            graph.add(node)
    graph.save()


def _database_reset_ids(plan, blueprint_dir: Path) -> tuple[str, ...] | None:
    """Return the scoped reset closure for planned rebuilding database operations.

    ``None`` means a legacy DATABASE Blueprint without the encapsulation surface; the caller
    retains the historic whole-file reset for that one migration path. A malformed new contract
    is an error, never a reason to broaden a reset.
    """
    database_path = blueprint_dir / "DATABASE.md"
    text = database_path.read_text(encoding="utf-8")
    if "## Access Patterns" not in text:
        return None
    contract = parse_database_contract(text, source=str(database_path))
    interfaces = {
        path.name: parse_database_interface(path.read_text(encoding="utf-8"), source=path.name)
        for path in blueprint_dir.glob("*.md")
        if path.name not in {"DATABASE.md", "DATABASE_compact.md"}
        and not path.name.endswith("_compact.md")
    }
    validate_database_interfaces(contract, interfaces)
    patterns = contract.by_id()
    staged = staged_operation_ids(blueprint_dir)
    unknown = set(staged) - set(patterns)
    if unknown:
        raise SpecificationError(
            "Blueprint migration references unknown access pattern(s): "
            + ", ".join(sorted(unknown))
        )
    record = plan.applied_specs.get("DATABASE.md")
    prior = parse_database_operation_fingerprints(record.database_operations) if record else {}
    # A Manifest snapshot, rather than Git history, determines the public contract
    # delta.  Old targets with no snapshot use their planned migration records and
    # otherwise contain the database-owner change only.
    if prior:
        changed = changed_operation_contracts(prior, text)
    else:
        # Targets built before the public snapshot existed may still have the
        # applied file commit.  Git is a one-time migration aid, never the
        # ongoing invalidation source; without either baseline Refit limits the
        # change to the DATABASE owner rather than broadening its impact.
        changed = (
            set(changed_operation_ids_since(blueprint_dir, record.commit) or ())
            if record
            else set()
        )
    active = set(staged) | changed
    rebuilding = {
        identifier
        for identifier in active
        if identifier in patterns and patterns[identifier].compatibility == "rebuild"
    }
    consumer_seeds = {
        block.block_id
        for block in plan.blocks
        for blueprint, uses in interfaces.items()
        if block.fields.get("implements", ()) == (blueprint,)
        and any(use.identifier in rebuilding for use in uses)
    }
    # Rebuild the persistence owner for private edits, data changes, and rebuild
    # changes without treating it as a broad dependency seed.  An ``unchanged``
    # public-contract revision records no rebuild at all.
    owner_required = not changed or any(
        identifier not in patterns or patterns[identifier].compatibility != "unchanged"
        for identifier in active
    )
    database_seeds = (
        {
            block.block_id
            for block in plan.blocks
            if "DATABASE.md" in block.fields.get("implements", ())
        }
        if owner_required
        else set()
    )
    return tuple(
        block.block_id
        for block in plan.blocks
        if block.block_id in database_seeds | set(cascade_reset_from_ids(plan, consumer_seeds))
    )


def _reconcile_drift(
    manifest_path: Path,
    blueprint_dir: Path,
) -> tuple[list[RefitReset], list[str]]:
    """Reset consumer blocks for every drifted applied specification.

    Blueprints are the source of truth. A direct edit is reconciled without a change ticket:
    its consumers and dependency closure return to ``pending`` and their stale provenance is
    removed. Tickets remain an optional additive workflow for work that does not edit a parent
    Blueprint.
    """
    if not manifest_path.is_file():
        return [], []

    plan = parse_build_plan(manifest_path)
    stale = stale_applied_specs(plan, blueprint_dir)
    if not stale:
        return [], []

    resets = reset_blueprint_consumers(
        manifest_path,
        blueprint_dir,
        [spec.rel_path for spec in stale],
        applied_commits={spec.rel_path: spec.record.commit for spec in stale},
    )
    return resets, []


def reset_blueprint_consumers(
    manifest_path: Path,
    blueprint_dir: Path,
    rel_paths: Sequence[str],
    *,
    applied_commits: Mapping[str, str] | None = None,
) -> list[RefitReset]:
    """Reset the Manifest blocks that consume changed Blueprint files, so build rebuilds them.

    Each file resets its cascade to ``pending``: the blocks that implement or reference it, their
    dependents and children, and reopened parent features. The file's ``applied_specs`` record and
    those stamped by reset blocks are dropped. ``DATABASE.md`` resets only the consumers of its
    changed rebuild operations when the encapsulation contract is present. ``applied_commits``
    names the commit each file was last applied at; it defaults to the file's own record.
    """
    paths = tuple(dict.fromkeys(rel_paths))
    if not paths or not manifest_path.is_file():
        return []
    plan = parse_build_plan(manifest_path)
    resets_by_path: dict[str, tuple[str, ...]] = {}
    for rel_path in paths:
        if rel_path == "DATABASE.md":
            scoped = _database_reset_ids(plan, blueprint_dir)
            resets_by_path[rel_path] = (
                cascade_reset_ids(plan, [rel_path]) if scoped is None else scoped
            )
        else:
            resets_by_path[rel_path] = cascade_reset_ids(plan, [rel_path])
    all_ids = tuple(dict.fromkeys(item for ids in resets_by_path.values() for item in ids))
    by_id = plan.by_id()
    updates: dict[str, dict[str, str | None]] = {
        block_id: {"state": "pending"} for block_id in all_ids if by_id[block_id].state != "pending"
    }
    if updates:
        batch_set_block_fields(manifest_path, updates)

    reset_set = set(all_ids)
    reset_paths = set(paths)
    remaining = {
        rel_path: record
        for rel_path, record in plan.applied_specs.items()
        if rel_path not in reset_paths and record.applied_by not in reset_set
    }
    if remaining != plan.applied_specs:
        set_applied_specs(manifest_path, remaining)

    return [
        RefitReset(
            path=rel_path,
            foundational=foundational_source(rel_path) is not None,
            reset_ids=resets_by_path[rel_path],
        )
        for rel_path in paths
    ]


def _refit_target(
    target_dir: Path,
    *,
    log_dir: Path | None = None,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> RefitResult:
    """Conform change tickets in blueprint/changes/ to the build process and patch MANIFEST.md."""
    from drydock.config import blueprint_dir_for, change_ticket_directory_for

    run = runner if runner is not None else run_prompt

    if not target_dir.is_dir():
        raise SpecificationError(f"Target directory not found: {target_dir}")

    blueprint_dir = blueprint_dir_for(target_dir)
    changes_dir = change_ticket_directory_for(target_dir)
    manifest_path = target_dir / "MANIFEST.md"

    changes_dir.mkdir(parents=True, exist_ok=True)
    normalized_items, normalization_errors = _normalize_source_tickets(changes_dir, blueprint_dir)
    comment_items, commented_blueprints = _normalize_blueprint_comments(blueprint_dir, changes_dir)
    normalized_items.extend(comment_items)
    normalized_items.extend(
        _normalize_blueprint_drift(
            manifest_path,
            blueprint_dir,
            changes_dir,
            commented_blueprints=commented_blueprints,
        )
    )

    tickets = []
    for path in sorted(p for p in changes_dir.glob("*.md") if p.is_file()):
        normalized = parse_normalized_ticket(path)
        if normalized is None:
            continue
        if normalized.drydock_fields["drydock_source"] in {
            "blueprint-diff",
            "blueprint-comment",
        }:
            continue
        if normalized.drydock_fields["drydock_status"] != "pending":
            continue
        tickets.append(path)

    prompt = load_prompt(PROMPT_NAME) if tickets else None
    today = date.today().isoformat()
    items: list[RefitItem] = [
        item
        for item in normalized_items
        if item.status == "failed"
        or (
            (normalized := parse_normalized_ticket(item.ticket)) is not None
            and normalized.drydock_fields["drydock_source"]
            in {"blueprint-diff", "blueprint-comment"}
        )
    ]
    database_tickets: list[Path] = []

    for ticket_path in tickets:
        assert prompt is not None
        ticket_text = ticket_path.read_text(encoding="utf-8")
        amends = _parse_amends(ticket_text)

        if amends is None:
            items.append(
                RefitItem(
                    ticket=ticket_path,
                    status="skipped-no-amends",
                    error="no Amends: field found",
                )
            )
            continue

        # Scope and declared story ids come from the ticket's own header when it has one. A
        # hand-authored ticket predating those fields parses to defaults rather than failing.
        header = parse_ticket_header(ticket_text)
        resolved_deps = _resolve_ticket_deps(amends, blueprint_dir)
        parent_path = blueprint_dir / amends.split("#", 1)[0]
        parent_text = parent_path.read_text(encoding="utf-8") if parent_path.is_file() else ""

        prompt_assembly = _assemble_refit_prompt(
            prompt.body,
            ticket_filename=ticket_path.name,
            ticket_text=ticket_text,
            parent_filename=amends,
            parent_text=parent_text,
            resolved_deps=resolved_deps,
            today=today,
            scope=header.scope if header else "amending",
            declared_stories=header.stories if header else (),
        )

        result = run(
            prompt_assembly.rendered_text,
            blueprint_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="refit",
            parameters={"ticket": str(ticket_path), "amends": amends},
            log_dir=log_dir,
            target=target_dir.name,
            on_text=on_text,
            prompt_assembly=prompt_assembly,
        )

        if not result.ok or not result.text.strip():
            items.append(
                RefitItem(
                    ticket=ticket_path,
                    status="failed",
                    execution_id=result.execution_id,
                    error="empty output" if result.ok else "LLM execution failed",
                )
            )
            continue

        ticket_content, manifest_rows, error_msg = _parse_refit_output(
            result.text, ticket_path.name
        )

        if error_msg:
            items.append(
                RefitItem(
                    ticket=ticket_path,
                    status="failed",
                    execution_id=result.execution_id,
                    error=error_msg,
                )
            )
            continue
        if not manifest_rows:
            items.append(
                RefitItem(
                    ticket=ticket_path,
                    status="failed",
                    execution_id=result.execution_id,
                    error="LLM output did not incorporate the ticket into MANIFEST_ROWS",
                )
            )
            continue

        if ticket_content and parse_normalized_ticket(ticket_path) is None:
            ticket_path.write_text(ticket_content.rstrip() + "\n", encoding="utf-8", newline="\n")
            ticket_text = ticket_content

        if manifest_rows:
            _patch_manifest(manifest_path, manifest_rows)
        set_normalized_ticket_status(ticket_path, "incorporated")

        items.append(
            RefitItem(
                ticket=ticket_path,
                status="conformed",
                execution_id=result.execution_id,
            )
        )

        if amends.split("#", 1)[0] == "DATABASE.md":
            database_tickets.append(ticket_path)

    database_tickets.extend(
        path
        for path in changes_dir.glob("TICKET-*.md")
        if (normalized := parse_normalized_ticket(path)) is not None
        and normalized.amends.split("#", 1)[0] == "DATABASE.md"
    )
    create_ticket_migration_records(blueprint_dir, dict.fromkeys(database_tickets))
    resets, drift_errors = _reconcile_drift(manifest_path, blueprint_dir)
    _attach_change_context(manifest_path, changes_dir, resets)

    return RefitResult(
        target_dir=target_dir,
        items=items,
        resets=resets,
        drift_errors=[*normalization_errors, *drift_errors],
    )


def _snapshot_refit_files(target_dir: Path, changes_dir: Path) -> dict[Path, str | None]:
    """Capture every refit-owned file so an unsuccessful transaction can be restored."""
    paths = [target_dir / "MANIFEST.md"]
    for directory in (changes_dir, target_dir / "blueprint" / "migrations"):
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    return {path: path.read_text(encoding="utf-8") if path.is_file() else None for path in paths}


def _restore_refit_files(
    snapshot: Mapping[Path, str | None], target_dir: Path, changes_dir: Path
) -> None:
    known = set(snapshot)
    for directory in (changes_dir, target_dir / "blueprint" / "migrations"):
        if directory.is_dir():
            for path in directory.rglob("*"):
                if path.is_file() and path not in known:
                    path.unlink()
    for path, content in snapshot.items():
        if content is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")


def _write_unincorporated_notification(target_dir: Path, errors: Sequence[str]) -> None:
    """Raise each unincorporated change ticket as a refit decision blocker."""
    if not errors:
        return
    from drydock.blockers import DECISION, Blocker, Blockers, now_utc, write_blockers

    target = target_dir.name
    write_blockers(
        target_dir,
        Blockers(
            summary="Unincorporated Change Tickets",
            target=target,
            source=f"drydock refit {target}",
            owner=f"refit {target}",
            declared=now_utc(),
            blockers=tuple(
                Blocker(
                    f"blocker-{index:03d}",
                    "Unincorporated change ticket",
                    DECISION,
                    question=f"{error}\n\nHow should refit incorporate this change?",
                )
                for index, error in enumerate(errors, start=1)
            ),
        ),
    )


def refit_target(
    target_dir: Path,
    *,
    log_dir: Path | None = None,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> RefitResult:
    """Run Refit atomically and checkpoint every written Target artifact in ``finally``."""
    from drydock.config import change_ticket_directory_for
    from drydock.target_git import commit_target

    changes_dir = change_ticket_directory_for(target_dir)
    snapshot = _snapshot_refit_files(target_dir, changes_dir)
    try:
        result = _refit_target(
            target_dir,
            log_dir=log_dir,
            runner=runner,
            on_text=on_text,
            model=model,
            llm_provider=llm_provider,
        )
        errors = [
            f"{item.ticket.name}: {item.error}" for item in result.failed() if item.error
        ] + result.drift_errors
        if errors:
            _restore_refit_files(snapshot, target_dir, changes_dir)
            _write_unincorporated_notification(target_dir, errors)
        elif (target_dir / "MANIFEST.md").is_file():
            from drydock.manifest_edit import optimize_build_blocks

            optimize_build_blocks(target_dir / "MANIFEST.md", pending_only=True)
        return result
    except Exception as exc:
        _restore_refit_files(snapshot, target_dir, changes_dir)
        _write_unincorporated_notification(target_dir, [str(exc)])
        raise
    finally:
        commit_target(target_dir, "Refit change tickets")
