"""Pytest fixtures for Drydock tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """A temporary Drydock workspace containing blueprints/ and targets/.

    Tests that need it set ``DRYDOCK_WORKSPACE`` to this path (or, equivalently,
    to ``tmp_spec_root.parent``).
    """
    ws = tmp_path / "workspace"
    (ws / "blueprints").mkdir(parents=True)
    (ws / "targets").mkdir(parents=True)
    return ws


@pytest.fixture()
def tmp_spec_root(tmp_workspace: Path) -> Path:
    """The blueprints root inside the temporary workspace."""
    return tmp_workspace / "blueprints"


@pytest.fixture()
def tmp_target_root(tmp_workspace: Path) -> Path:
    """The targets root inside the temporary workspace."""
    return tmp_workspace / "targets"


@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Redirect the user-scoped config path to a temp dir and clear env vars.

    Returns the Path to the isolated config directory.
    """
    cfg_dir = tmp_path / "drydock_config"
    cfg_dir.mkdir()

    import drydock.config

    monkeypatch.setattr(
        drydock.config,
        "_config_path",
        lambda: cfg_dir / ".env",
    )

    # Remove real env vars that could leak into tests
    for key in (
        "DRYDOCK_WORKSPACE",
        "LLM_PROVIDER",
        "QUARTERDECK_PORT",
    ):
        monkeypatch.delenv(key, raising=False)

    return cfg_dir
