"""Deterministic prompt-context labels for injected files."""

from __future__ import annotations

from pathlib import Path

_ROLE_BY_NAME = {
    "AGENTS.md": "service and endpoint inventory",
    "ARCHITECTURE.md": "architecture boundary and module layout",
    "BUILD_PLAN.md": "delivery plan draft",
    "BUILD_PLAN_INTENT.md": "planning intent and decomposition guidance",
    "CHANGE_LOG.md": "change history and scope deltas",
    "DATABASE.md": "persistence and data model authority",
    "FUNCTIONALITY.md": "capability inventory",
    "IDEAS.md": "backlog, options, and candidate scope",
    "INTENT.md": "product intent and objectives",
    "METADATA.md": "project metadata",
    "README.md": "project overview",
    "SPIKE_RESULTS.md": "research findings and resolved spikes",
    "UI-GENERAL.md": "shared UI contract",
}

_ROLE_BY_PREFIX = (
    ("FEATURE-", "feature contract"),
    ("SCREEN-", "screen contract"),
)


def source_file_role(path: Path) -> str:
    """Return the fixed role label for an injected source file."""
    name = path.name
    if name in _ROLE_BY_NAME:
        return _ROLE_BY_NAME[name]
    for prefix, role in _ROLE_BY_PREFIX:
        if name.startswith(prefix):
            return role
    return "source reference"


def prompt_source_header(label: str, path: Path) -> str:
    """Return a deterministic prompt header for one injected source file."""
    return f"{label} - {source_file_role(path)}"
