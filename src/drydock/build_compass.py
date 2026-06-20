"""BUILD_COMPASS.md — authored grouping/ordering of Blueprint spec files.

The file is the build-step grouping and ordering artifact consumed by ``drydock
build``: groups of spec files in build order, foundational groups first. It is
edited interactively in the QuarterDeck (move / combine / split) and stays
**clean** — authored content only, no numbers on disk.

Authored format. Groups are ``# `` (H1) headers; each non-blank line beneath a
header names one spec file, in build order::

    # Foundational
    FEATURE-Schema.md
    FEATURE-Auth.md

    # Screens
    SCREEN-Dashboard.md

Cost is **derived, never persisted**. Story points are a deterministic estimate
of token cost (``byte count / 4``); ``recompute_token_costs`` computes per-file,
per-group, and total rollups on demand. Costs never touch the file.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# An H1 header (exactly one leading ``#``) opens a group. ``##`` and deeper are
# not group headers.
_GROUP_RE = re.compile(r"^#(?!#)\s+(.+?)\s*$")

_DEFAULT_GROUP = "Unsorted"


# ── Authored model ───────────────────────────────────────────────────────────────


@dataclass
class CompassGroup:
    name: str
    files: list[str] = field(default_factory=list)


@dataclass
class BuildCompass:
    groups: list[CompassGroup] = field(default_factory=list)

    def file_names(self) -> list[str]:
        return [name for group in self.groups for name in group.files]


def parse_build_compass(text: str) -> BuildCompass:
    """Parse BUILD_COMPASS.md text into its authored grouping.

    Lines before the first group header are ignored. A file line may carry an
    optional ``- `` bullet prefix; it is stripped.
    """
    compass = BuildCompass()
    current: CompassGroup | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        header = _GROUP_RE.match(line)
        if header:
            current = CompassGroup(name=header.group(1).strip())
            compass.groups.append(current)
            continue
        if current is None:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line:
            current.files.append(line)
    return compass


def render_build_compass(compass: BuildCompass) -> str:
    """Render the authored grouping back to clean BUILD_COMPASS.md text.

    Authored content only — never any computed numbers. Round-trips with
    ``parse_build_compass``.
    """
    blocks: list[str] = []
    for group in compass.groups:
        lines = [f"# {group.name}"]
        lines.extend(group.files)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n" if blocks else ""


def seed_from_specs(spec_names: Iterable[str], *, group_name: str = _DEFAULT_GROUP) -> BuildCompass:
    """Seed a flat BUILD_COMPASS — one default group holding every spec file in
    the given order. The human regroups it in the QuarterDeck."""
    files = list(dict.fromkeys(spec_names))  # de-dupe, preserve order
    if not files:
        return BuildCompass()
    return BuildCompass(groups=[CompassGroup(name=group_name, files=files)])


# ── Derived cost (never persisted) ───────────────────────────────────────────────


@dataclass(frozen=True)
class FileCost:
    name: str
    token_count: int  # measured size in bytes
    story_points: int  # ceil(token_count / 4)
    missing: bool = False


@dataclass(frozen=True)
class GroupCost:
    name: str
    files: tuple[FileCost, ...]
    token_count: int
    story_points: int


@dataclass(frozen=True)
class CompassCost:
    groups: tuple[GroupCost, ...]
    total_token_count: int
    total_story_points: int


def story_points_for(token_count: int) -> int:
    """Story points = estimated token cost = ``byte count / 4`` (rounded up)."""
    return math.ceil(token_count / 4)


def recompute_token_costs(compass: BuildCompass, *, file_root: Path) -> CompassCost:
    """Derive per-file, per-group, and total costs from the authored grouping.

    For each file, ``token_count`` is its byte size under ``file_root`` and
    ``story_points`` is ``ceil(token_count / 4)``. A file whose path is absent
    contributes zero and is flagged ``missing``. Pure: reads files, writes
    nothing.
    """
    group_costs: list[GroupCost] = []
    total_tokens = 0
    total_points = 0
    for group in compass.groups:
        file_costs: list[FileCost] = []
        group_tokens = 0
        group_points = 0
        for name in group.files:
            path = file_root / name
            try:
                token_count = len(path.read_bytes())
                missing = False
            except OSError:
                token_count = 0
                missing = True
            points = story_points_for(token_count)
            file_costs.append(
                FileCost(
                    name=name,
                    token_count=token_count,
                    story_points=points,
                    missing=missing,
                )
            )
            group_tokens += token_count
            group_points += points
        group_costs.append(
            GroupCost(
                name=group.name,
                files=tuple(file_costs),
                token_count=group_tokens,
                story_points=group_points,
            )
        )
        total_tokens += group_tokens
        total_points += group_points
    return CompassCost(
        groups=tuple(group_costs),
        total_token_count=total_tokens,
        total_story_points=total_points,
    )
