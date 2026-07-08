"""Initialize a target workspace with the baseline Drydock runtime."""

from __future__ import annotations

import errno
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import DrydockError
from drydock.metadata import render_metadata
from drydock.standard_artifacts import ensure_standard_artifacts, render_console

_TRAVERSAL_RE = re.compile(r"\.\.|[/\\]")
_UNSAFE_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


def _mkdir_one(path: Path) -> None:
    try:
        path.mkdir(exist_ok=True)
        return
    except OSError as exc:
        if exc.errno != errno.EEXIST or path.is_dir():
            raise

    # WSL/DrvFs zombie: stat returns ENOENT but mkdir returns EEXIST.
    # cmd.exe can create the directory on the Windows side, resolving the inconsistency.
    try:
        win_path = (
            subprocess
            .check_output(["wslpath", "-w", str(path)], stderr=subprocess.DEVNULL, timeout=5)
            .decode()
            .strip()
        )
        subprocess.run(
            ["cmd.exe", "/c", "mkdir", win_path],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass

    if not path.is_dir():
        raise OSError(
            errno.EEXIST,
            "File exists (WSL/DrvFs zombie — run `wsl --shutdown` and retry)",
            str(path),
        )


def _mkdir(path: Path) -> None:
    # Walk ancestors top-down so each parent uses the resilient _mkdir_one,
    # avoiding Python's built-in mkdir(parents=True) which hits the same stale-cache
    # bug when recursing into parent creation.
    if not path.parent.exists():
        _mkdir(path.parent)
    _mkdir_one(path)


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
    _mkdir(path.parent)
    path.write_text(content, encoding="utf-8", newline="\n")
    result.created.append(path)


def init_target(
    target: str,
    target_directory: Path,
    *,
    display_name: str = "",
    short_description: str = "",
) -> InitTargetResult:
    """Create the specification-independent baseline for a target project."""
    _validate_target(target)
    target_dir = target_directory / target
    result = InitTargetResult(target=target, target_dir=target_dir)

    try:
        _mkdir(target_dir)
        for directory in (
            "blueprint/sources",
            "blueprint/changes",
            "evidence",
            "logs",
            "QuarterDeck/data",
        ):
            path = target_dir / directory
            _mkdir(path)
            keep = path / ".gitkeep"
            _write_missing(keep, "", result)

        _write_missing(
            target_dir / "METADATA.md",
            render_metadata(target, display_name=display_name, short_description=short_description),
            result,
        )

        for path in ensure_standard_artifacts(target, target_dir):
            result.created.append(path)
        _write_missing(
            target_dir / "QuarterDeck" / "console.yaml",
            render_console(target),
            result,
        )
    except OSError as exc:
        raise DrydockError(f"Cannot initialize target {target_dir}: {exc}") from exc

    return result
