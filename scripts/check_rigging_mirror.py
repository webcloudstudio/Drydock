#!/usr/bin/env python3
"""Verify the Drydock ``Rigging/`` tree mirrors Prototyper ``RulesEngine/`` exactly.

Drydock ``Rigging/`` is a governed mirror of Prototyper ``RulesEngine/`` (see
DRYDOCK_DEVELOPMENT.md, "RulesEngine And Rigging Mirror Contract"). Their governed files must remain
byte-for-byte identical; transient artifacts (caches, compiled files) are excluded.

This check is local/pre-commit only. Prototyper is not present in CI, so the script exits ``0`` with
a notice when the reference repository cannot be resolved. CI instead verifies that the wheel-embedded
Rigging matches the source ``Rigging/`` (no Prototyper required).

Exit codes: ``0`` identical or skipped, ``1`` drift detected, ``2`` usage/configuration error.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RIGGING = REPO_ROOT / "Rigging"

# Transient, ignored artifacts that are never part of the governed identity.
EXCLUDED_DIR_NAMES = {".ruff_cache", "__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILE_NAMES = {".DS_Store"}


def _read_prototyper_directory() -> str | None:
    """Return the ``prototyper_directory`` value from METADATA.md, if present."""
    metadata = REPO_ROOT / "METADATA.md"
    if not metadata.is_file():
        return None
    for line in metadata.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("prototyper_directory:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _is_excluded(path: Path) -> bool:
    if path.name in EXCLUDED_FILE_NAMES or path.suffix in EXCLUDED_SUFFIXES:
        return True
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def _governed_files(root: Path) -> dict[str, Path]:
    """Map governed files under ``root`` to their relative POSIX paths."""
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root)
            if _is_excluded(rel):
                continue
            files[rel.as_posix()] = path
    return files


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not RIGGING.is_dir():
        print(f"error: Drydock Rigging not found at {RIGGING}", file=sys.stderr)
        return 2

    raw = _read_prototyper_directory()
    if raw is None:
        print("rigging-mirror: prototyper_directory not set in METADATA.md — skipping.")
        return 0

    reference = (REPO_ROOT / raw).resolve() / "RulesEngine"
    if not reference.is_dir():
        print(
            f"rigging-mirror: reference {reference} not present — skipping (CI/standalone checkout)."
        )
        return 0

    left = _governed_files(RIGGING)
    right = _governed_files(reference)

    only_drydock = sorted(set(left) - set(right))
    only_prototyper = sorted(set(right) - set(left))
    differing = sorted(
        rel for rel in set(left) & set(right) if _sha256(left[rel]) != _sha256(right[rel])
    )

    if not (only_drydock or only_prototyper or differing):
        print(f"rigging-mirror: OK — {len(left)} governed files identical.")
        return 0

    print("rigging-mirror: DRIFT detected between governed trees:", file=sys.stderr)
    print(f"  Drydock:    {RIGGING}", file=sys.stderr)
    print(f"  Prototyper: {reference}", file=sys.stderr)
    for rel in only_drydock:
        print(f"  only in Drydock Rigging/:        {rel}", file=sys.stderr)
    for rel in only_prototyper:
        print(f"  only in Prototyper RulesEngine/: {rel}", file=sys.stderr)
    for rel in differing:
        print(f"  content differs:                 {rel}", file=sys.stderr)
    print(
        "\nA rule change requires Ed's explicit authorization and must be applied identically to "
        "both trees.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
