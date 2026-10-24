"""Target build environment: a Python build is its own uv project."""

import tomllib

from drydock.target_environment import seed_python_project


def test_a_python_build_is_seeded_with_a_standalone_project(tmp_path):
    written = seed_python_project(tmp_path, "FxRates")

    assert written == tmp_path / "pyproject.toml"
    project = tomllib.loads(written.read_text(encoding="utf-8"))["project"]
    assert project == {
        "name": "fxrates",
        "version": "0.1.0",
        "requires-python": ">=3.11",
        "dependencies": [],
    }
    assert "tool" not in tomllib.loads(written.read_text(encoding="utf-8"))


def test_an_existing_project_is_never_overwritten(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'mine'\n", encoding="utf-8")

    assert seed_python_project(tmp_path, "FxRates") is None
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == "[project]\nname = 'mine'\n"


def test_a_target_name_becomes_a_valid_project_name(tmp_path):
    seed_python_project(tmp_path, "Drydock Stats_2")

    text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["project"]["name"] == "drydock-stats-2"
