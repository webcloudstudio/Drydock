#!/usr/bin/env python3
"""Repository-local launcher for Drydock Ship's Log agent operations."""

from __future__ import annotations

# ruff: noqa: E402, I001

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from drydock.ships_log_tool import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
