"""Pytest fixtures for Drydock tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ``main()`` publishes the glyph tier it resolved so its subprocesses render identically. That
# is one process per command in the field, but one process for the whole suite here, so a test
# that drives the CLI would otherwise fix the tier for every test that follows it.
# ``--model`` is published the same way, so a CLI test must not leave its model behind either.
_CONSOLE_ENV = ("DRYDOCK_GLYPHS", "DRYDOCK_ASCII", "DRYDOCK_MODEL")


@pytest.fixture(autouse=True)
def _isolate_console_env():
    saved = {name: os.environ.get(name) for name in _CONSOLE_ENV}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def _isolate_fatal_stop():
    """A fatal provider failure ends one process's LLM work; here that process is the suite."""
    from drydock.llm import reset_fatal_stop

    reset_fatal_stop()
    yield
    reset_fatal_stop()


@pytest.fixture(autouse=True)
def _isolate_model_config(tmp_path_factory: pytest.TempPathFactory, monkeypatch):
    """Point every test at a private copy of the packaged ``model_config.jsonl``.

    The live copy is user configuration that calibration rewrites, so a test must never read
    or create it. Every model row is pinned to 4 bytes per token so byte-derived token counts
    in tests do not depend on a tokenizer measurement; tests of the ratio itself write their
    own file.
    """
    import json

    from drydock.model_config import seed_path

    rows = []
    for line in seed_path().read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == "model":
            row["bytes_per_token"] = 4.0
        rows.append(json.dumps(row))
    path = tmp_path_factory.mktemp("model_config") / "model_config.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("DRYDOCK_MODEL_CONFIG", str(path))
    yield path


@pytest.fixture()
def set_model_fields(_isolate_model_config: Path):
    """Factory: overwrite fields on every model row of the test's ``model_config.jsonl``."""
    import json

    def _set(**fields) -> Path:
        rows = []
        for line in _isolate_model_config.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("kind") == "model":
                row.update(fields)
            rows.append(json.dumps(row))
        _isolate_model_config.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return _isolate_model_config

    return _set


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
        "DRYDOCK_MODEL",
        "LLM_PROVIDER",
        "QUARTERDECK_PORT",
        "POSTGRES_DSN",
    ):
        monkeypatch.delenv(key, raising=False)

    # Drydock has no default model: the model selects the provider, so guessing one would pick
    # a vendor too. Every real workspace therefore sets one, and so does every test that is not
    # specifically about an unset model.
    monkeypatch.setenv("DRYDOCK_MODEL", "sonnet")

    return cfg_dir
