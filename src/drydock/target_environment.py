"""Resolve the interpreter used to execute Target-owned Python acceptance."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TargetEnvironment:
    interpreter: Path | None
    detail: str
    provisioning_result: str = "not requested"


def _venv_python(build_dir: Path) -> Path:
    windows = build_dir / ".venv" / "Scripts" / "python.exe"
    return windows if windows.is_file() else build_dir / ".venv" / "bin" / "python"


def resolve_target_environment(build_dir: Path) -> TargetEnvironment:
    """Return the best interpreter available for Target acceptance.

    A Target-owned environment is preferred. A new build does not necessarily own one yet, so
    acceptance otherwise uses the active interpreter that is already running Drydock. Strict
    acceptance still replaces ``PYTHONPATH`` and therefore does not inherit repository-local
    modules merely because Drydock can import them.
    """
    interpreter = _venv_python(build_dir)
    if interpreter.is_file():
        return TargetEnvironment(interpreter, "Target .venv selected")
    active = Path(sys.executable)
    if active.is_file():
        return TargetEnvironment(active, "Drydock active Python selected")
    fallback = shutil.which("python3")
    if fallback:
        return TargetEnvironment(Path(fallback), "non-project python3 selected")
    return TargetEnvironment(None, "no Target interpreter or system python3 is available")


def seed_python_project(build_dir: Path, name: str) -> Path | None:
    """Write a standalone ``pyproject.toml`` into a Python build that has none.

    Python Rigging requires uv, and ``uv init`` run inside another uv project registers the build
    as a member of that project's workspace. A build that already holds a ``pyproject.toml`` stays
    its own project: ``uv init`` refuses to run there, and ``uv lock`` writes the build's own
    ``uv.lock``. Returns the file written, or ``None`` when one already exists.
    """
    path = build_dir / "pyproject.toml"
    if path.exists():
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "target"
    path.write_text(
        f'[project]\nname = "{slug}"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n'
        "dependencies = []\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def provision_uv_environment(build_dir: Path) -> TargetEnvironment:
    """Validate the lock and provision the Target `.venv` through its uv workflow."""
    if not (build_dir / "pyproject.toml").is_file() or not (build_dir / "uv.lock").is_file():
        return TargetEnvironment(None, "pyproject.toml and uv.lock are required", "not provisioned")
    uv = shutil.which("uv")
    if uv is None:
        return TargetEnvironment(None, "uv executable is unavailable", "not provisioned")
    completed = subprocess.run(
        [uv, "sync", "--locked"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "uv sync failed"
        return TargetEnvironment(None, detail, "uv sync --locked failed")
    from drydock.acceptance_requirements import invalidate_target_environment_inventory

    invalidate_target_environment_inventory()
    resolved = resolve_target_environment(build_dir)
    return TargetEnvironment(
        resolved.interpreter,
        resolved.detail,
        "uv sync --locked succeeded",
    )
