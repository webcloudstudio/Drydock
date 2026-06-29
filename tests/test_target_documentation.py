"""Tests for Target documentation generation and assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import DrydockError, SpecificationError, UsageError
from drydock.target_documentation import (
    assemble_documentation,
    document_target,
    generate_documentation,
    parse_generated_docs,
)

LLM_OUTPUT = """=== DOC-OVERVIEW.md ===
# Overview

The system tracks build evidence.
=== END DOC-OVERVIEW.md ===

=== DOC-FEATURES.md ===
# Features

## Evidence Review

Reviewers inspect accepted work.
=== END DOC-FEATURES.md ===

=== DOC-SCREENS.md ===
# Screens

## Dashboard

Shows current state.
=== END DOC-SCREENS.md ===

=== DOC-ARCHITECTURE.md ===
# Architecture

## Runtime

CLI modules write target artifacts.
=== END DOC-ARCHITECTURE.md ===
"""


@dataclass(frozen=True)
class FakeRun:
    text: str = LLM_OUTPUT
    ok: bool = True
    execution_id: str = "exec-1"


def _make_target(tmp_target_root: Path, name: str = "Demo") -> Path:
    target_dir = tmp_target_root / name
    (target_dir / "blueprint").mkdir(parents=True)
    (target_dir / "METADATA.md").write_text(
        "name: Demo\ndisplay_name: Demo Target\nshort_description: Evidence tracker\n",
        encoding="utf-8",
    )
    (target_dir / "blueprint" / "FEATURE-EVIDENCE.md").write_text(
        "# Evidence\n\nBuild evidence is reviewed by humans.\n",
        encoding="utf-8",
    )
    (target_dir / "MANIFEST.md").write_text(
        "# MANIFEST: Demo\nstate: approved\n\nid: evidence-review\nkind: story\nstate: pending\n",
        encoding="utf-8",
    )
    return target_dir


def test_parse_generated_docs_requires_required_blocks():
    with pytest.raises(DrydockError, match="DOC-FEATURES.md"):
        parse_generated_docs(
            "=== DOC-OVERVIEW.md ===\n# Overview\n=== END DOC-OVERVIEW.md ===\n",
            sections=("OVERVIEW", "FEATURES", "SCREENS", "ARCHITECTURE"),
        )


def test_parse_generated_docs_rejects_unexpected_file():
    with pytest.raises(DrydockError, match="unexpected"):
        parse_generated_docs(
            LLM_OUTPUT + "\n=== DOC-DATABASE.md ===\n# Database\n=== END DOC-DATABASE.md ===\n",
            sections=("OVERVIEW", "FEATURES", "SCREENS", "ARCHITECTURE"),
        )


def test_parse_generated_docs_rejects_text_outside_blocks():
    with pytest.raises(DrydockError, match="Text appeared outside"):
        parse_generated_docs(
            "Here are the files.\n" + LLM_OUTPUT,
            sections=("OVERVIEW", "FEATURES", "SCREENS", "ARCHITECTURE"),
        )


def test_generate_documentation_writes_doc_files_and_config(
    tmp_target_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target_dir = _make_target(tmp_target_root)
    build_root = tmp_path / "build"
    monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))
    calls = []

    def fake_runner(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeRun()

    result = generate_documentation(
        "Demo",
        tmp_target_root,
        model="sonnet",
        llm_provider="claude",
        runner=fake_runner,
    )

    assert (target_dir / "documentation.yaml").exists()
    assert not (target_dir / "docs" / "documentation.yaml").exists()
    assert result.docs_dir == build_root / "Demo" / "docs"
    assert (
        (result.docs_dir / "DOC-OVERVIEW.md").read_text(encoding="utf-8").startswith("# Overview")
    )
    assert sorted(path.name for path in result.files) == [
        "DOC-ARCHITECTURE.md",
        "DOC-FEATURES.md",
        "DOC-OVERVIEW.md",
        "DOC-SCREENS.md",
    ]
    assert calls[0][1]["command_name"] == "document generate"
    assert calls[0][1]["target"] == "Demo"
    assert "# MANIFEST: Demo" in calls[0][0][0]


def test_generate_documentation_missing_target_fails(tmp_target_root: Path):
    with pytest.raises(SpecificationError, match="Target not found"):
        generate_documentation("Missing", tmp_target_root, runner=lambda *a, **k: FakeRun())


def test_generate_documentation_bad_model_output_fails(
    tmp_target_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _make_target(tmp_target_root)
    monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(tmp_path / "build"))

    def fake_runner(*args, **kwargs):
        return FakeRun(text="No blocks")

    with pytest.raises(DrydockError, match="Text appeared outside"):
        generate_documentation("Demo", tmp_target_root, runner=fake_runner)

    assert not (tmp_path / "build" / "Demo" / "docs").exists()


def test_assemble_documentation_writes_sidebar_app(
    tmp_target_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target_dir = _make_target(tmp_target_root)
    build_root = tmp_path / "build"
    monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))
    docs = build_root / "Demo" / "docs"
    docs.mkdir(parents=True)
    (docs / "DOC-OVERVIEW.md").write_text("# Overview\n\nHello.\n", encoding="utf-8")
    (docs / "DOC-FEATURES.md").write_text(
        "# Features\n\n## Evidence Review\n\nReview evidence.\n", encoding="utf-8"
    )

    result = assemble_documentation("Demo", tmp_target_root)
    html = result.output.read_text(encoding="utf-8")

    assert result.output == docs / "index.html"
    assert (target_dir / "documentation.yaml").exists()
    assert (docs / "styles" / "spec.css").exists()
    assert 'class="sidebar"' in html
    assert "showGuide" in html
    assert "Evidence Review" in html
    assert "marked.parse" in html


def test_assemble_documentation_missing_docs_fails(
    tmp_target_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _make_target(tmp_target_root)
    monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(tmp_path / "build"))

    with pytest.raises(SpecificationError, match="No DOC-\\*\\.md"):
        assemble_documentation("Demo", tmp_target_root)


def test_assemble_documentation_bad_theme_fails(
    tmp_target_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _make_target(tmp_target_root)
    build_root = tmp_path / "build"
    monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))
    docs = build_root / "Demo" / "docs"
    docs.mkdir(parents=True)
    (docs / "DOC-OVERVIEW.md").write_text("# Overview\n", encoding="utf-8")

    with pytest.raises(UsageError, match="Unknown documentation theme"):
        assemble_documentation("Demo", tmp_target_root, theme="unknown")


def test_document_target_runs_generate_then_assemble(
    tmp_target_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _make_target(tmp_target_root)
    build_root = tmp_path / "build"
    monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))

    generated, assembled = document_target(
        "Demo",
        tmp_target_root,
        runner=lambda *a, **k: FakeRun(),
    )

    assert (generated.docs_dir / "DOC-OVERVIEW.md").exists()
    assert generated.docs_dir == build_root / "Demo" / "docs"
    assert assembled.output.exists()
