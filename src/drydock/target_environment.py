"""Resolve the interpreter used to execute Target-owned Python acceptance."""

from __future__ import annotations

import shutil
import subprocess
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


def is_python_project(build_dir: Path) -> bool:
    return any((build_dir / name).is_file() for name in ("pyproject.toml", "uv.lock"))


def resolve_target_environment(build_dir: Path) -> TargetEnvironment:
    """Return the Target interpreter without consulting Drydock's ``sys.executable``.

    Python/uv projects are strict: acceptance runs only through their local ``.venv``.
    The ``python3`` fallback is retained for non-project script fixtures and imported kits.
    """
    interpreter = _venv_python(build_dir)
    if interpreter.is_file():
        return TargetEnvironment(interpreter, "Target .venv selected")
    if is_python_project(build_dir):
        return TargetEnvironment(None, "Target Python project has no .venv")
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
