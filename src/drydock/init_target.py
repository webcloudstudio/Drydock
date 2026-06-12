"""Initialize a target workspace with the baseline Drydock runtime."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import DrydockError
from drydock.standard_artifacts import ensure_standard_artifacts, render_console
from drydock.target_manifest import TargetManifest

_TRAVERSAL_RE = re.compile(r"\.\.|[/\\]")
_UNSAFE_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


@dataclass
class InitTargetResult:
    target: str
    target_dir: Path
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def _validate_target(target: str) -> None:
    if not target or not target.strip():
        raise DrydockError("Target name must not be empty.")
    if _TRAVERSAL_RE.search(target):
        raise DrydockError(f"Target name must not contain path separators or '..': {target!r}")
    if _UNSAFE_CHARS_RE.search(target):
        raise DrydockError(f"Target name contains invalid characters: {target!r}")
    if len(target) > 200:
        raise DrydockError("Target name is too long (max 200 characters).")


def _write_missing(path: Path, content: str, result: InitTargetResult) -> None:
    if path.exists():
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    result.created.append(path)


def init_target(target: str, target_directory: Path) -> InitTargetResult:
    """Create the specification-independent baseline for a target project."""
    _validate_target(target)
    target_dir = target_directory / target
    result = InitTargetResult(target=target, target_dir=target_dir)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        for directory in ("docs", "evidence", "logs", "QuarterDeck/data"):
            path = target_dir / directory
            path.mkdir(parents=True, exist_ok=True)
            keep = path / ".gitkeep"
            _write_missing(keep, "", result)

        _write_missing(
            target_dir / "target.yaml",
            TargetManifest().render(),
            result,
        )

        for path in ensure_standard_artifacts(target, target_dir):
            result.created.append(path)
        _write_missing(
            target_dir / "QuarterDeck" / "tickets.json",
            json.dumps({"tickets": []}, indent=2) + "\n",
            result,
        )
        _write_missing(
            target_dir / "QuarterDeck" / "console.yaml",
            render_console(target),
            result,
        )
    except OSError as exc:
        raise DrydockError(f"Cannot initialize target {target_dir}: {exc}") from exc

    return result
