"""Internal planning-input inventory used by ``drydock plan create``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from drydock.errors import SpecificationError

_SKIPPED_FILES = {
    "ACCEPTANCE_CRITERIA.md",
    "ARCHITECTURE.md",
    "MANIFEST.md",
    "BUILD_PLAN_COMPASS.md",
    "IDEAS.md",
    "COMPASS.md",
    "METADATA.md",
    "README.md",
    "SCORECARD.md",
    "UI-GENERAL.md",
    "UI.md",
    "HOMEPAGE.md",
    "FEATURE-Example.md",
    "SCREEN-Example.md",
    "UI-Component-Example.md",
}

_IMPORTED_TEMPLATE_FILES = {
    "DATABASE.md",
    "FEATURE-Example.md",
    "SCREEN-Example.md",
    "UI-Component-Example.md",
}


class CompassStatus(Enum):
    CREATED = auto()
    UPDATED = auto()
    UNCHANGED = auto()


@dataclass(frozen=True)
class PlanCompassResult:
    blueprint: str
    blueprint_dir: Path
    compass_path: Path
    status: CompassStatus
    appended_files: tuple[str, ...] = ()
    section_count: int = 0


def _is_plannable_file(path: Path) -> bool:
    name = path.name
    if name in _SKIPPED_FILES:
        return False
    if re.match(r"^(AC|PATCH)-\d{3}-", name):
        return False
    return path.suffix.lower() == ".md"


def _size_annotation(path: Path) -> str:
    return f"({path.stat().st_size // 1024}k)"


def _discover_spec_files(blueprint_dir: Path) -> list[Path]:
    top_level = [path for path in sorted(blueprint_dir.glob("*.md")) if _is_plannable_file(path)]
    sources_dir = blueprint_dir / "sources"
    if (sources_dir / ".drydock-import").is_file():
        top_level = [path for path in top_level if path.name not in _IMPORTED_TEMPLATE_FILES]
    sources = (
        [path for path in sorted(sources_dir.rglob("*.md")) if path.is_file()]
        if sources_dir.is_dir()
        else []
    )
    return top_level + sources


def _display_name(path: Path, blueprint_dir: Path) -> str:
    return path.relative_to(blueprint_dir).as_posix()


def _write_new_compass(
    compass_path: Path, blueprint: str, blueprint_dir: Path, spec_files: list[Path]
) -> int:
    database = next((path for path in spec_files if path.name == "DATABASE.md"), None)
    sources = [path for path in spec_files if "sources" in path.relative_to(blueprint_dir).parts]
    remaining = [path for path in spec_files if path.name != "DATABASE.md" and path not in sources]

    lines = [
        f"# BUILD_PLAN_COMPASS.md — {blueprint}",
        f"# Created by: drydock plan create {blueprint} <Target>",
        "#",
        "# Reorder sections to set build order.",
        "# Prefix a file line with # to skip it from planning.",
        "# Re-run drydock plan create to append newly discovered Blueprint inputs.",
        "",
        "## Foundation",
    ]
    if database is not None:
        lines.append(f"{database.name} {_size_annotation(database)}")
    lines.append("")

    if remaining:
        lines.append("## Planned Work")
        for path in remaining:
            lines.append(f"{_display_name(path, blueprint_dir)} {_size_annotation(path)}")
        lines.append("")
    if sources:
        lines.append("## Imported Sources")
        for path in sources:
            lines.append(f"{_display_name(path, blueprint_dir)} {_size_annotation(path)}")
        lines.append("")

    compass_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return 1 + (1 if remaining else 0) + (1 if sources else 0)


def init_plan_compass(blueprint: str, target_dir: Path) -> PlanCompassResult:
    """Create or update the curated BUILD_PLAN_COMPASS.md file for a Blueprint."""
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(
            f"Blueprint directory not found: {blueprint_dir}\n"
            "  Import source material before creating a plan."
        )

    compass_path = blueprint_dir / "BUILD_PLAN_COMPASS.md"
    spec_files = _discover_spec_files(blueprint_dir)

    if not compass_path.exists():
        section_count = _write_new_compass(compass_path, blueprint, blueprint_dir, spec_files)
        return PlanCompassResult(
            blueprint=blueprint,
            blueprint_dir=blueprint_dir,
            compass_path=compass_path,
            status=CompassStatus.CREATED,
            section_count=section_count,
        )

    existing_text = compass_path.read_text(encoding="utf-8")
    referenced = set(re.findall(r"(?m)^#?\s*([^\s]+\.md)\b", existing_text))
    new_files = tuple(
        _display_name(path, blueprint_dir)
        for path in spec_files
        if _display_name(path, blueprint_dir) not in referenced
    )
    if not new_files:
        return PlanCompassResult(
            blueprint=blueprint,
            blueprint_dir=blueprint_dir,
            compass_path=compass_path,
            status=CompassStatus.UNCHANGED,
        )

    lines = ["", "", "## New Specs - place in build order"]
    for name in new_files:
        lines.append(f"{name} {_size_annotation(blueprint_dir / name)}")
    lines.append("")
    with compass_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))

    return PlanCompassResult(
        blueprint=blueprint,
        blueprint_dir=blueprint_dir,
        compass_path=compass_path,
        status=CompassStatus.UPDATED,
        appended_files=new_files,
    )
