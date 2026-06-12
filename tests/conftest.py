"""Pytest fixtures for Drydock tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """A temporary Drydock workspace containing targets/.

    Tests that need it set ``DRYDOCK_WORKSPACE`` to this path (equivalently,
    ``tmp_target_root.parent``).
    """
    ws = tmp_path / "workspace"
    (ws / "targets").mkdir(parents=True)
    return ws


@pytest.fixture()
def tmp_target_root(tmp_workspace: Path) -> Path:
    """The targets root inside the temporary workspace."""
    return tmp_workspace / "targets"


@pytest.fixture()
def make_blueprint(tmp_target_root: Path):
    """Factory: create ``targets/<name>/blueprint/`` with given files; return that dir."""

    def _make(name: str, files: dict[str, str] | None = None) -> Path:
        blueprint_dir = tmp_target_root / name / "blueprint"
        blueprint_dir.mkdir(parents=True, exist_ok=True)
        for fname, body in (files or {}).items():
            path = blueprint_dir / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return blueprint_dir

    return _make


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
