"""Resolve the interpreter used to execute Target-owned Python acceptance."""

from __future__ import annotations

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
