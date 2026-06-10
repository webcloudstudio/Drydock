"""Rigging resource resolver — source tree vs installed package."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def _source_tree_rigging() -> Path | None:
    """Return root-level Rigging/ path if we are running from the source tree."""
    # Walk up from this file to find the repo root containing Rigging/
    here = Path(__file__).parent  # src/drydock/
    for candidate in [
        here.parent.parent,  # repo root (src/../..)
        here.parent.parent.parent,  # one level higher in editable installs
    ]:
        rigging = candidate / "Rigging"
        if rigging.is_dir() and (rigging / "spec_template").is_dir():
            return rigging
    return None


def get_rigging_root() -> Path:
    """
    Return the authoritative Rigging/ directory.

    Precedence:
      1. Root-level Rigging/ when running from the source tree.
      2. drydock/resources/Rigging/ inside the installed package.
    """
    src = _source_tree_rigging()
    if src is not None:
        return src

    # Installed package: use importlib.resources
    try:
        pkg_files = importlib.resources.files("drydock") / "resources" / "Rigging"
        # Materialise to a real filesystem path when possible
        with importlib.resources.as_file(pkg_files) as p:
            return Path(p)
    except (FileNotFoundError, TypeError) as exc:
        raise FileNotFoundError(
            "Rigging resources not found. Reinstall drydock or run from the source tree."
        ) from exc


def get_spec_template_dir() -> Path:
    """Return the spec_template/ directory inside Rigging."""
    return get_rigging_root() / "spec_template"


def get_stack_dir() -> Path:
    """Return the stack/ directory inside Rigging."""
    return get_rigging_root() / "stack"
