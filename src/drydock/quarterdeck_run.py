"""Launch a target project's QuarterDeck server."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import DrydockError
from drydock.paths import get_quarterdeck_root
from drydock.standard_artifacts import render_console

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"


@dataclass
class QuarterDeckRunResult:
    exit_code: int


def ensure_quarterdeck_state(target_dir: Path) -> Path:
    """Restore missing QuarterDeck state for an initialized Target.

    QuarterDeck is a regenerable presentation layer. A failed command must not
    make blocker recovery impossible merely because its ``console.yaml`` was
    absent. ``METADATA.md`` remains the initialization authority, so arbitrary
    directories are still rejected.
    """
    state_dir = target_dir / "QuarterDeck"
    console_path = state_dir / "console.yaml"
    if console_path.is_file():
        return state_dir
    if not (target_dir / "METADATA.md").is_file():
        raise DrydockError(
            f"QuarterDeck not initialized at {state_dir}\n  Run: drydock init <Target>"
        )
    state_dir.mkdir(parents=True, exist_ok=True)
    plan_path = target_dir / "MANIFEST.md"
    console_path.write_text(
        render_console(target_dir.name, plan_path=plan_path if plan_path.is_file() else None),
        encoding="utf-8",
        newline="\n",
    )
    from drydock.quarterdeck_state import refresh_commanders_chair

    refresh_commanders_chair(target_dir)
    return state_dir


def run_quarterdeck(
    target_dir: Path,
    *,
    port: int = DEFAULT_PORT,
    host: str = DEFAULT_HOST,
    runtime_root: Path | None = None,
) -> QuarterDeckRunResult:
    """Start the QuarterDeck server for ``target_dir``.

    The console runtime is served from the installed package (or source tree);
    only the Target's console *state* lives under ``target_dir/QuarterDeck``. The
    runtime is pointed at that in-tree state through ``QUARTERDECK_DIR`` and
    ``QUARTERDECK_PROJECT_ROOT``. Uvicorn must be installed in the active Python
    environment (``pip install uvicorn[standard]``).
    """
    state_dir = ensure_quarterdeck_state(target_dir)

    runtime = runtime_root or get_quarterdeck_root()
    if not (runtime / "app.py").is_file():
        raise DrydockError(f"QuarterDeck runtime not found: {runtime / 'app.py'}")

    env = os.environ.copy()
    env["QUARTERDECK_DIR"] = str(state_dir)
    env["QUARTERDECK_PROJECT_ROOT"] = str(target_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "QuarterDeck.app:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=runtime.parent,
        env=env,
    )
    return QuarterDeckRunResult(exit_code=result.returncode)
