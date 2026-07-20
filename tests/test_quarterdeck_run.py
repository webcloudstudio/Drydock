"""Tests for serving the QuarterDeck runtime from the package against in-tree state."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

from drydock import quarterdeck_run
from drydock.errors import DrydockError


def test_project_installs_quarterdeck_runtime_dependencies():
    """The packaged QuarterDeck command must install the imports it shells out to."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = data["project"]["dependencies"]
    normalized = {dep.split("[", 1)[0].split(">=", 1)[0].lower() for dep in dependencies}

    assert {"fastapi", "markdown", "pydantic", "pyyaml", "uvicorn"} <= normalized


def _make_state(target_dir: Path) -> None:
    (target_dir / "QuarterDeck").mkdir(parents=True)
    (target_dir / "QuarterDeck" / "console.yaml").write_text("project: x\n", encoding="utf-8")


def _make_runtime(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "app.py").write_text("app = object()\n", encoding="utf-8")


def test_run_quarterdeck_points_runtime_at_in_tree_state(tmp_path, monkeypatch):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    _make_state(target_dir)
    runtime = tmp_path / "pkg" / "QuarterDeck"
    _make_runtime(runtime)

    captured = {}

    def fake_run(cmd, *, cwd, env):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(quarterdeck_run.subprocess, "run", fake_run)

    result = quarterdeck_run.run_quarterdeck(target_dir, runtime_root=runtime)

    assert result.exit_code == 0
    assert captured["cwd"] == runtime.parent
    assert captured["env"]["QUARTERDECK_DIR"] == str(target_dir / "QuarterDeck")
    assert captured["env"]["QUARTERDECK_PROJECT_ROOT"] == str(target_dir)
    assert "QuarterDeck.app:app" in captured["cmd"]


def test_run_quarterdeck_uninitialized_state_raises(tmp_path):
    target_dir = tmp_path / "targets" / "Empty"
    target_dir.mkdir(parents=True)
    with pytest.raises(DrydockError, match="not initialized"):
        quarterdeck_run.run_quarterdeck(target_dir)


def test_run_quarterdeck_restores_missing_state_for_initialized_target(tmp_path, monkeypatch):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    (target_dir / "METADATA.md").write_text("name: Example\n", encoding="utf-8")
    runtime = tmp_path / "pkg" / "QuarterDeck"
    _make_runtime(runtime)

    class _Result:
        returncode = 0

    monkeypatch.setattr(quarterdeck_run.subprocess, "run", lambda *args, **kwargs: _Result())

    result = quarterdeck_run.run_quarterdeck(target_dir, runtime_root=runtime)

    assert result.exit_code == 0
    assert (target_dir / "QuarterDeck" / "console.yaml").is_file()


def test_ensure_quarterdeck_state_adds_blockers_to_legacy_console(tmp_path):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    _make_state(target_dir)
    console_path = target_dir / "QuarterDeck" / "console.yaml"
    console_path.write_text(
        "sections:\n  - { id: setup, label: Setup }\nitems:\n\nsources:\n",
        encoding="utf-8",
    )

    quarterdeck_run.ensure_quarterdeck_state(target_dir)

    console = console_path.read_text(encoding="utf-8")
    assert "id: blockers_doc" in console
    assert console.index("id: blockers_doc") < console.index("sources:")


def test_run_quarterdeck_missing_runtime_raises(tmp_path):
    target_dir = tmp_path / "targets" / "Example"
    target_dir.mkdir(parents=True)
    _make_state(target_dir)
    with pytest.raises(DrydockError, match="runtime not found"):
        quarterdeck_run.run_quarterdeck(target_dir, runtime_root=tmp_path / "absent")


def test_app_honors_external_state_env(tmp_path, monkeypatch):
    """The package runtime resolves console state from QUARTERDECK_DIR."""
    state = tmp_path / "targets" / "Example" / "QuarterDeck"
    state.mkdir(parents=True)
    monkeypatch.setenv("QUARTERDECK_DIR", str(state))
    monkeypatch.setenv("QUARTERDECK_PROJECT_ROOT", str(state.parent))

    app_path = Path(__file__).parents[1] / "QuarterDeck" / "app.py"
    spec = importlib.util.spec_from_file_location("quarterdeck_app_env_test", app_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.BASE_DIR == state.resolve()
    assert module.PROJECT_ROOT == state.parent.resolve()
    assert module.CONFIG_PATH == state.resolve() / "console.yaml"
