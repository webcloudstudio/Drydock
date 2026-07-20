"""Imported-source roles, Blueprint promotion, and build-asset staging."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import SpecificationError


@dataclass(frozen=True)
class SourceRole:
    path: str
    role: str
    plan_disposition: str
    build_disposition: str


_ROLE_HEADER = re.compile(r"^## Source Roles\s*$", re.M)


def parse_source_roles(analysis_text: str) -> dict[str, SourceRole]:
    """Read the optional Analyze-to-Plan source-role table.

    Older analyses remain usable: omitted rows default to source-reference/context/stage.
    """
    match = _ROLE_HEADER.search(analysis_text)
    if not match:
        return {}
    rows: dict[str, SourceRole] = {}
    for line in analysis_text[match.end() :].splitlines():
        if line.startswith("## "):
            break
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0].lower() in {"path", "---"} or set(cells[0]) == {"-"}:
            continue
        path, role, plan, build = cells
        if path:
            rows[path.removeprefix("sources/")] = SourceRole(
                path, role.lower(), plan.lower(), build.lower()
            )
    return rows


def promote_imported_sources(
    blueprint_dir: Path, roles: dict[str, SourceRole], target_dir: Path
) -> list[Path]:
    """Copy immutable imports to Blueprint build paths; author intent becomes Compass only."""
    sources_dir = blueprint_dir / "sources"
    if not sources_dir.is_dir():
        return []
    promoted: list[Path] = []
    for source in sorted(path for path in sources_dir.rglob("*") if path.is_file()):
        rel = source.relative_to(sources_dir).as_posix()
        if source.name in {".gitkeep", ".drydock-import"}:
            continue
        role = roles.get(rel)
        if role is not None and role.plan_disposition == "compass":
            _append_compass(target_dir / "COMPASS.md", source)
            continue
        destination = blueprint_dir / rel
        if destination.exists() and destination.resolve() != source.resolve():
            if destination.read_bytes() != source.read_bytes():
                raise SpecificationError(
                    f"Imported source promotion conflicts with existing Blueprint file: {rel}"
                )
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        promoted.append(destination)
    return promoted


def _append_compass(compass: Path, source: Path) -> None:
    content = source.read_text(encoding="utf-8").strip()
    if not content:
        return
    digest = hashlib.sha256(content.encode()).hexdigest()
    marker = f"<!-- Drydock author intent sha256={digest} source={source.name} -->"
    existing = compass.read_text(encoding="utf-8") if compass.is_file() else ""
    if marker in existing:
        return
    compass.parent.mkdir(parents=True, exist_ok=True)
    suffix = "\n\n" if existing.strip() else ""
    compass.write_text(
        existing.rstrip() + suffix + marker + "\n\n" + content + "\n", encoding="utf-8"
    )


def stage_context_file(
    source: Path, name: str, *, blueprint_dir: Path, build_dir: Path
) -> Path | None:
    """Copy a promoted context asset into the build tree, preserving its manifest path."""
    try:
        source.relative_to(blueprint_dir)
    except ValueError:
        return None
    if not source.is_file() or source.suffix == ".md":
        return None
    destination = build_dir / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination
