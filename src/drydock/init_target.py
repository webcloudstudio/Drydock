"""Initialize a target workspace with the baseline Drydock runtime."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import DrydockError
from drydock.paths import get_quarterdeck_root

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


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "target"


def _write_missing(path: Path, content: str, result: InitTargetResult) -> None:
    if path.exists():
        result.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    result.created.append(path)


def _copy_missing(source: Path, destination: Path, result: InitTargetResult) -> None:
    if destination.exists():
        result.skipped.append(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result.created.append(destination)


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

        runtime = get_quarterdeck_root()
        for name in ("app.py", "start.sh", "requirements.txt"):
            source = runtime / name
            if not source.is_file():
                raise DrydockError(f"QuarterDeck runtime file not found: {source}")
            _copy_missing(source, target_dir / "QuarterDeck" / name, result)

        _write_missing(
            target_dir / "QuarterDeck" / "pages" / "overview.md",
            f"# Commander's View: {target}\n\n"
            "This target is initialized and ready for Blueprint import and planning.\n",
            result,
        )
        _write_missing(
            target_dir / "QuarterDeck" / "tickets.json",
            json.dumps({"tickets": []}, indent=2) + "\n",
            result,
        )
        _write_missing(
            target_dir / "QuarterDeck" / "console.yaml",
            f"""console:
  name: {target} QuarterDeck
  default_item: commanders_view
  state_db: data/console_state.sqlite

project:
  id: {_slug(target)}
  name: {target}
  description: "Drydock target workspace."

sections:
  - {{ id: core, label: "Drydock Core", dot: "#0d9488", pinned: true }}
  - {{ id: build_plan, label: "Build Plan", dot: "#d97706" }}
  - {{ id: actions, label: "Action Items", dot: "#dc2626" }}
  - {{ id: project_pages, label: "Project Pages", dot: "#2563eb" }}
  - {{ id: archive, label: "Archive", dot: "#94a3b8", collapsed: true }}

items:
  - {{ id: commanders_view, label: "Commander's View", section: core, type: markdown, path: pages/overview.md }}
  - {{ id: board, label: "Delivery Board", section: build_plan, type: kanban, path: tickets.json }}
""",
            result,
        )
    except OSError as exc:
        raise DrydockError(f"Cannot initialize target {target_dir}: {exc}") from exc

    return result
