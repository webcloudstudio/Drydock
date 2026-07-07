"""Tests for deterministic build-output README generation."""

from __future__ import annotations

from pathlib import Path

from drydock.readme_generate import generate_readme


def _write_target(target_dir: Path, stack: str = "fastapi.md, python.md") -> None:
    blueprint_dir = target_dir / "blueprint"
    blueprint_dir.mkdir(parents=True)
    (target_dir / "METADATA.md").write_text(
        "name: Demo\ndisplay_name: Demo App\nshort_description: Generated demo.\nstack: \n",
        encoding="utf-8",
    )
    (blueprint_dir / "METADATA.md").write_text(
        f"name: Demo\ndisplay_name: Demo App\nshort_description: Generated demo.\nstack: {stack}\n",
        encoding="utf-8",
    )


def test_generate_readme_includes_first_run_start_and_next_steps(tmp_path: Path):
    target_dir = tmp_path / "target"
    build_dir = tmp_path / "build"
    _write_target(target_dir)
    (build_dir / "bin").mkdir(parents=True)
    (build_dir / "app").mkdir()
    (build_dir / "uv.lock").write_text("", encoding="utf-8")
    (build_dir / ".env.example").write_text("APP_PORT=8060\n", encoding="utf-8")
    (build_dir / "bin" / "start.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (build_dir / "bin" / "test.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (build_dir / "app" / "main.py").write_text(
        'APP_PORT = int(os.getenv("APP_PORT", "8060"))\n',
        encoding="utf-8",
    )

    readme_path = generate_readme(target_dir, build_dir)

    assert readme_path == build_dir / "README.md"
    text = readme_path.read_text(encoding="utf-8")
    assert "Copy `.env.example` to `.env`" in text
    assert "git remote -v" in text
    assert "git status --short" in text
    assert "uv sync" in text
    assert "bash bin/start.sh" in text
    assert "http://127.0.0.1:8060" in text
    assert "## Verification" in text
    assert "bash bin/test.sh" in text
    assert "## Next Steps" in text
    assert "Complete the first-run checks above." in text


def test_generate_readme_uses_existing_env_when_no_example(tmp_path: Path):
    target_dir = tmp_path / "target"
    build_dir = tmp_path / "build"
    _write_target(target_dir, stack="python.md")
    build_dir.mkdir()
    (build_dir / ".env").write_text("LOCAL_ONLY=1\n", encoding="utf-8")
    (build_dir / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (build_dir / "run.py").write_text("print('run')\n", encoding="utf-8")

    readme_path = generate_readme(target_dir, build_dir)

    text = readme_path.read_text(encoding="utf-8")
    assert "Review `.env` before starting" in text
    assert "pip install -e ." in text
    assert "python run.py" in text
    assert "python -m pytest" in text
    assert "Open `http://127.0.0.1" not in text
