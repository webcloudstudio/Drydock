"""``drydock rigging update`` — inject compact Rigging rules into a built target project.

Injects the current ``BUSINESS_RULES_compact.md`` from Rigging into the target project's
``AGENTS.md`` via ``# DRYDOCK_RIGGING_START`` / ``# DRYDOCK_RIGGING_END`` markers, and stamps
provenance fields into the built target's ``METADATA.md``.

``AGENTS.md`` is a contract on every built Drydock target and is always present.
"""

from __future__ import annotations

from datetime import UTC, datetime

from drydock.config import build_dir_for
from drydock.metadata import get_build_state, set_field
from drydock.paths import get_rigging_root

MARKER_START = "# DRYDOCK_RIGGING_START"
MARKER_END = "# DRYDOCK_RIGGING_END"

COMPACT_FILENAME = "BUSINESS_RULES_compact.md"
AGENTS_FILENAME = "AGENTS.md"
METADATA_FILENAME = "METADATA.md"


def _strip_rigging_block(text: str) -> str:
    """Remove the existing DRYDOCK_RIGGING_START…END block, if present."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == MARKER_START:
            in_block = True
        if not in_block:
            result.append(line)
        if in_block and stripped == MARKER_END:
            in_block = False
    return "".join(result)


def _inject_block(existing: str, compact_content: str) -> str:
    """Return AGENTS.md content with the rigging block appended."""
    base = _strip_rigging_block(existing).rstrip("\n")
    block = f"\n{MARKER_START}\n{compact_content.strip()}\n{MARKER_END}\n"
    return base + "\n" + block


def update(target: str, *, dry_run: bool = False) -> tuple[int, list[str]]:
    """Inject Rigging into the built target project.

    Returns (exit_code, log_lines).
    """
    log: list[str] = []

    # Resolve compact source
    rigging_root = get_rigging_root()
    compact_path = rigging_root / COMPACT_FILENAME
    if not compact_path.exists():
        log.append(
            f"ERROR: {COMPACT_FILENAME} not found in Rigging — run: drydock rigging compact <Blueprint> <Target> --all"
        )
        return 1, log

    compact_content = compact_path.read_text(encoding="utf-8")

    # Resolve built target directory
    build_dir = build_dir_for(target)
    agents_path = build_dir / AGENTS_FILENAME
    metadata_path = build_dir / METADATA_FILENAME

    if not agents_path.exists():
        log.append(f"ERROR: {AGENTS_FILENAME} not found in build directory: {build_dir}")
        return 1, log

    # --- Inject into AGENTS.md ---
    original = agents_path.read_text(encoding="utf-8")
    updated = _inject_block(original, compact_content)
    if updated == original:
        log.append(f"  ·  {AGENTS_FILENAME}  unchanged")
    else:
        if not dry_run:
            agents_path.write_text(updated, encoding="utf-8", newline="\n")
        log.append(f"  ✓  {AGENTS_FILENAME}  rigging block injected")

    # --- Stamp METADATA.md ---
    if not metadata_path.exists():
        log.append(f"  ·  {METADATA_FILENAME}  not found — skipping stamp")
    else:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Read project_state from the workspace Target METADATA.md (same build dir for now)
        workspace_state = get_build_state(build_dir)

        stamps = {
            "drydock_target": target,
            "drydock_build_directory": str(build_dir),
            "drydock_project_state": workspace_state,
            "drydock_rigging_updated": now,
        }
        for key, value in stamps.items():
            if not dry_run:
                set_field(metadata_path, key, value, overwrite=True)
            log.append(f"  ✓  {METADATA_FILENAME}  {key} = {value}")

    return 0, log
