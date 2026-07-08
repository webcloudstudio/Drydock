#!/usr/bin/env python3
"""Verify wheel-embedded release resources.

The wheel ships a copy of Rigging at ``drydock/resources/Rigging/`` via Hatchling ``force-include``.
That copy must stay byte-for-byte identical to the root ``Rigging/`` so ``drydock init`` and
``drydock validate`` behave identically from an installed wheel and from the source tree.

The wheel also ships the canonical product specification at
``drydock/resources/docs/Drydock_Specification.md`` so installed releases have the same read-only
product authority as a source checkout.

This check needs only the built wheel in ``dist/`` — no Prototyper checkout — so it is safe to run
in CI. Build first (``uv build``), then run this script.

Exit codes: ``0`` identical, ``1`` drift detected, ``2`` usage/configuration error.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_RIGGING = REPO_ROOT / "Rigging"
SOURCE_SPECIFICATION = REPO_ROOT / "docs" / "Drydock_Specification.md"
DIST = REPO_ROOT / "dist"
WHEEL_PREFIX = "drydock/resources/Rigging/"
SPECIFICATION_WHEEL_PATH = "drydock/resources/docs/Drydock_Specification.md"

EXCLUDED_DIR_NAMES = {".ruff_cache", "__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILE_NAMES = {".DS_Store"}


def _is_excluded(rel: Path) -> bool:
    if rel.name in EXCLUDED_FILE_NAMES or rel.suffix in EXCLUDED_SUFFIXES:
        return True
    return any(part in EXCLUDED_DIR_NAMES for part in rel.parts)


def _source_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in SOURCE_RIGGING.rglob("*"):
        if path.is_file():
            rel = path.relative_to(SOURCE_RIGGING)
            if _is_excluded(rel):
                continue
            files[rel.as_posix()] = path.read_bytes()
    return files


def _wheel_files(wheel: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if not name.startswith(WHEEL_PREFIX) or name.endswith("/"):
                continue
            rel = Path(name[len(WHEEL_PREFIX) :])
            if _is_excluded(rel):
                continue
            files[rel.as_posix()] = zf.read(name)
    return files


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    wheels = sorted(DIST.glob("*.whl")) if DIST.is_dir() else []
    if not wheels:
        print(f"error: no wheel found in {DIST}; run 'uv build' first.", file=sys.stderr)
        return 2

    wheel = wheels[-1]
    source = _source_files()
    embedded = _wheel_files(wheel)
    errors: list[str] = []

    only_source = sorted(set(source) - set(embedded))
    only_wheel = sorted(set(embedded) - set(source))
    differing = sorted(
        rel for rel in set(source) & set(embedded) if _digest(source[rel]) != _digest(embedded[rel])
    )

    if only_source or only_wheel or differing:
        errors.append(f"wheel-rigging: DRIFT between source Rigging/ and {wheel.name}:")
        for rel in only_source:
            errors.append(f"  missing from wheel: {rel}")
        for rel in only_wheel:
            errors.append(f"  extra in wheel:     {rel}")
        for rel in differing:
            errors.append(f"  content differs:    {rel}")

    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        if SPECIFICATION_WHEEL_PATH not in names:
            errors.append(f"wheel-specification: missing {SPECIFICATION_WHEEL_PATH}")
        elif _digest(SOURCE_SPECIFICATION.read_bytes()) != _digest(
            zf.read(SPECIFICATION_WHEEL_PATH)
        ):
            errors.append(f"wheel-specification: content differs: {SPECIFICATION_WHEEL_PATH}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    print(f"wheel-rigging: OK — {len(source)} files identical ({wheel.name}).")
    print(f"wheel-specification: OK — {SPECIFICATION_WHEEL_PATH} ({wheel.name}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
