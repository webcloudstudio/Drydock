"""Deterministic prompt-context labels for injected files."""

from __future__ import annotations

from pathlib import Path

from drydock.prompt_headers import prompt_header_for_path


def source_file_role(path: Path) -> str:
    """Return the configured role label for an injected source file."""
    header = prompt_header_for_path(path)
    if header is not None and header.role:
        return header.role
    return "source reference"


def prompt_source_header(label: str, path: Path) -> str:
    """Return a deterministic prompt header for one injected source file."""
    return f"{label} - {source_file_role(path)}"
