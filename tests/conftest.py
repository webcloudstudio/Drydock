"""Pytest fixtures for Drydock tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_spec_root(tmp_path: Path) -> Path:
    """A temporary directory to act as the specification_directory root."""
    d = tmp_path / "specs"
    d.mkdir()
    return d


@pytest.fixture()
def tmp_target_root(tmp_path: Path) -> Path:
    """A temporary directory to act as the target_directory root."""
    d = tmp_path / "targets"
    d.mkdir()
    return d


@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Redirect platformdirs config path to a temp dir and clear env vars.

    Returns the Path to the isolated config directory.
    """
    cfg_dir = tmp_path / "drydock_config"
    cfg_dir.mkdir()

    import platformdirs

    monkeypatch.setattr(
        platformdirs,
        "user_config_path",
        lambda app, appauthor=None, **kw: cfg_dir,
    )

    # Remove real env vars that could leak into tests
    for key in ("SPECIFICATION_DIRECTORY", "TARGET_DIRECTORY"):
        monkeypatch.delenv(key, raising=False)

    return cfg_dir
