"""Provision Drydock's Claude Code skills into a project's ``.claude/skills`` tree.

Skills ship inside Rigging (``Rigging/skills/<name>/SKILL.md``). ``drydock init`` calls
:func:`sync_skills` so a managed workspace always carries the current skills. Each skill
declares a semantic ``version`` in its SKILL.md frontmatter; a skill is (re)installed when
the workspace copy is absent or its version is lower than the shipped version. Version is a
deterministic upgrade signal — unlike filesystem mtimes, which reproducible wheel builds
normalize.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from drydock.paths import get_rigging_root

_VERSION_RE = re.compile(r"^version:\s*(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass
class SkillSyncResult:
    """Outcome of one :func:`sync_skills` call."""

    dest_root: Path
    installed: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.installed or self.updated)


def _parse_version(skill_md: Path) -> tuple[int, ...]:
    """Return the frontmatter ``version`` as a comparable tuple; ``(0,)`` if absent."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return (0,)
    front = _FRONTMATTER_RE.match(text)
    scope = front.group(1) if front else text
    match = _VERSION_RE.search(scope)
    if not match:
        return (0,)
    return _version_tuple(match.group(1))


def _version_tuple(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in raw.strip().strip('"').strip("'").split("."):
        digits = re.match(r"\d+", chunk)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts) or (0,)


def _copy_skill(source_dir: Path, dest_dir: Path) -> None:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(source_dir, dest_dir)


def sync_skills(project_root: Path, *, source_root: Path | None = None) -> SkillSyncResult:
    """Install or upgrade shipped skills under ``project_root/.claude/skills``.

    A skill directory is one holding a ``SKILL.md``. For each shipped skill:

    - install it if the destination ``SKILL.md`` is missing;
    - upgrade it if the shipped ``version`` is greater than the installed ``version``;
    - otherwise leave the destination untouched.
    """
    source = source_root if source_root is not None else get_rigging_root() / "skills"
    dest_root = project_root / ".claude" / "skills"
    result = SkillSyncResult(dest_root=dest_root)

    if not source.is_dir():
        return result

    for source_dir in sorted(source.iterdir()):
        source_md = source_dir / "SKILL.md"
        if not source_dir.is_dir() or not source_md.is_file():
            continue

        name = source_dir.name
        dest_dir = dest_root / name
        dest_md = dest_dir / "SKILL.md"
        shipped = _parse_version(source_md)

        if not dest_md.is_file():
            _copy_skill(source_dir, dest_dir)
            result.installed.append(name)
            continue

        installed = _parse_version(dest_md)
        if shipped > installed:
            _copy_skill(source_dir, dest_dir)
            result.updated.append(name)
        else:
            result.skipped.append(name)

    return result
