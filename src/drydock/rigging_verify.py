"""``drydock rigging verify`` — check that a built target project's Rigging is current.

Reports per-check pass/fail:
  - AGENTS.md injected block exists and matches the current BUSINESS_RULES_compact.md
  - METADATA.md has required human-authored fields: name, short_description
  - METADATA.md has Drydock provenance stamp fields
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from drydock.config import build_dir_for
from drydock.metadata import parse_metadata
from drydock.paths import get_rigging_root
from drydock.rigging_update import COMPACT_FILENAME, MARKER_END, MARKER_START

AGENTS_FILENAME = "AGENTS.md"
METADATA_FILENAME = "METADATA.md"

REQUIRED_HUMAN_FIELDS = ("name", "short_description")
REQUIRED_STAMP_FIELDS = (
    "drydock_target",
    "drydock_build_directory",
    "drydock_project_state",
    "drydock_rigging_updated",
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""


def _extract_injected_block(text: str) -> str | None:
    """Extract the content between the rigging markers, or None if absent."""
    lines = text.splitlines()
    in_block = False
    block_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == MARKER_START:
            in_block = True
            continue
        if stripped == MARKER_END:
            break
        if in_block:
            block_lines.append(line)
    return "\n".join(block_lines) if in_block else None


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def verify(target: str) -> tuple[int, list[CheckResult]]:
    """Run all compliance checks for the built target. Returns (exit_code, checks)."""
    checks: list[CheckResult] = []

    build_dir = build_dir_for(target)

    # --- Check 1: AGENTS.md injected block matches current compact ---
    rigging_root = get_rigging_root()
    compact_path = rigging_root / COMPACT_FILENAME
    agents_path = build_dir / AGENTS_FILENAME

    if not compact_path.exists():
        checks.append(
            CheckResult(
                "rigging_compact_exists",
                False,
                f"{COMPACT_FILENAME} not found — run: drydock rigging compact <Blueprint> <Target> --all",
            )
        )
    elif not agents_path.exists():
        checks.append(
            CheckResult(
                "agents_md_exists",
                False,
                f"{AGENTS_FILENAME} not found in {build_dir}",
            )
        )
    else:
        current_compact = compact_path.read_text(encoding="utf-8")
        agents_text = agents_path.read_text(encoding="utf-8")
        injected = _extract_injected_block(agents_text)
        if injected is None:
            checks.append(
                CheckResult(
                    "rigging_block_present",
                    False,
                    f"{AGENTS_FILENAME} has no {MARKER_START} block — run: drydock rigging update {target}",
                )
            )
        elif _content_hash(injected) != _content_hash(current_compact):
            checks.append(
                CheckResult(
                    "rigging_block_current",
                    False,
                    f"injected block is stale — run: drydock rigging update {target}",
                )
            )
        else:
            checks.append(CheckResult("rigging_block_current", True))

    # --- Check 2 & 3: METADATA.md required fields ---
    metadata_path = build_dir / METADATA_FILENAME
    if not metadata_path.exists():
        for field in REQUIRED_HUMAN_FIELDS + REQUIRED_STAMP_FIELDS:
            checks.append(CheckResult(field, False, f"{METADATA_FILENAME} not found"))
    else:
        fields = parse_metadata(metadata_path)
        for field in REQUIRED_HUMAN_FIELDS:
            present = bool(fields.get(field, "").strip())
            checks.append(
                CheckResult(
                    field,
                    present,
                    "" if present else f"missing required field '{field}' in {METADATA_FILENAME}",
                )
            )
        for field in REQUIRED_STAMP_FIELDS:
            present = bool(fields.get(field, "").strip())
            checks.append(
                CheckResult(
                    field,
                    present,
                    ""
                    if present
                    else f"missing stamp field '{field}' — run: drydock rigging update {target}",
                )
            )

    exit_code = 0 if all(c.passed for c in checks) else 1
    return exit_code, checks
