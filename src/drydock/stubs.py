"""Deferred command stubs — parse args, print not-implemented, exit 2."""

from __future__ import annotations

import sys


def not_implemented(command: str) -> None:
    """Print a standard not-implemented message and exit with code 2."""
    print(f"drydock {command}: not implemented", file=sys.stderr)
    sys.exit(2)
