"""Launch a target project's QuarterDeck server."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import DrydockError

DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"


@dataclass
class QuarterDeckRunResult:
    exit_code: int


def run_quarterdeck(
    target_dir: Path,
    *,
    port: int = DEFAULT_PORT,
    host: str = DEFAULT_HOST,
) -> QuarterDeckRunResult:
    """Start the QuarterDeck server for target_dir.

    Runs uvicorn in-process (blocking) with the target directory as cwd so that
    ``QuarterDeck.app`` resolves correctly.  Uvicorn must be installed in the
    active Python environment (``pip install uvicorn[standard]``).
    """
    app_py = target_dir / "QuarterDeck" / "app.py"
    if not app_py.is_file():
        raise DrydockError(
            f"QuarterDeck not initialized at {target_dir / 'QuarterDeck'}\n"
            "  Run: drydock init <Target>"
        )

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
        cwd=target_dir,
    )
    return QuarterDeckRunResult(exit_code=result.returncode)
