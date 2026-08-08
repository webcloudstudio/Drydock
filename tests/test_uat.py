from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.uat import CommandResult, discover_fixtures, render_summary, run_uat


def _fixture(root: Path, name: str = "ReadingList", *, updated: bool = True) -> Path:
    fixture = root / name
    fixture.mkdir(parents=True)
    (fixture / "reading-list.md").write_text("# Initial\n", encoding="utf-8")
    updates: list[str] = []
    if updated:
        update = fixture / "updates" / "reading-list.md"
        update.parent.mkdir()
        update.write_text("# Updated\n", encoding="utf-8")
        updates.append("updates/reading-list.md")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": name,
            "sources": ["reading-list.md"],
            "updates": updates,
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )
    return fixture


def test_discover_fixture_uses_explicit_sources_and_updates(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    found = discover_fixtures(tmp_path)[0]

    assert found.sources == ((fixture / "reading-list.md").resolve(),)
    assert found.updates == ((fixture / "updates" / "reading-list.md").resolve(),)
    assert found.test_command == ("sh", "bin/test.sh")


def test_discover_selected_fixture_rejects_unknown_project(tmp_path: Path) -> None:
    _fixture(tmp_path)

    with pytest.raises(SpecificationError, match="Unknown UAT fixture"):
        discover_fixtures(tmp_path, "Missing")


def test_discover_fixture_loads_nested_local_source(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    source = fixture / "kit" / "suite.py"
    source.parent.mkdir()
    source.write_text("# suite\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": "Example",
            "sources": ["reading-list.md", "kit/suite.py"],
            "updates": [],
            "test_command": ["sh", "full_test.sh"],
        }),
        encoding="utf-8",
    )

    found = discover_fixtures(tmp_path)[0]

    assert found.sources == ((fixture / "reading-list.md").resolve(), source.resolve())
    assert found.test_command == ("sh", "full_test.sh")


def test_discover_fixture_rejects_source_outside_fixture(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    outside = tmp_path / "outside.py"
    outside.write_text("# outside\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "sources": ["../outside.py"],
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="Invalid UAT fixture source path"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_flattened_source_collision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    duplicate = fixture / "kit" / "reading-list.md"
    duplicate.parent.mkdir()
    duplicate.write_text("# duplicate\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "sources": ["reading-list.md", "kit/reading-list.md"],
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="collide after import flattening"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_update_for_unknown_basename(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    update = fixture / "other.md"
    update.write_text("# other\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "sources": ["reading-list.md"],
            "updates": ["other.md"],
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="replace an imported basename"):
        discover_fixtures(tmp_path)


def test_run_uat_builds_initial_and_updated_sources_and_keeps_scores_advisory(
    tmp_path: Path,
) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root)
    calls: list[tuple[str, ...]] = []
    ready_calls = 0

    def fake_runner(argv, cwd, env, output_dir, label):
        nonlocal ready_calls
        del cwd, env
        parts = tuple(argv[3:])
        calls.append(parts)
        returncode = 0
        if parts[:2] == ("status", "ReadingList") and "--ready" in parts:
            ready_calls += 1
            returncode = 0 if ready_calls in {1, 3} else 1
        if parts[:3] == ("score", "release", "ReadingList"):
            returncode = 1
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr))

    run_root, results = run_uat(
        tmp_path,
        selected=None,
        fixtures_root=fixtures_root,
        output_root=tmp_path / "runs",
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    result = results[0]
    assert result.status == "passed"
    assert result.build_passes == 2
    assert result.score_exit_codes == {"acceptance": 0, "build-report": 0, "release": 1}
    assert ("import", "ReadingList", "--update") in calls
    assert ("refit", "ReadingList", "--sources") in calls
    assert (run_root / "ReadingList" / "sources" / "reading-list.md").read_text() == "# Updated\n"
    assert (run_root / "summary.json").is_file()
    assert "ReadingList: PASSED" in (run_root / "SUMMARY.md").read_text(encoding="utf-8")


def test_required_pipeline_failure_stops_fixture_and_writes_result(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    def failing_runner(argv, cwd, env, output_dir, label):
        del cwd, env
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("failed", encoding="utf-8")
        returncode = 1 if tuple(argv[3:5]) == ("analyze", "ReadingList") else 0
        return CommandResult(tuple(argv), returncode, 1, str(stdout), str(stderr))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        fixtures_root=fixtures_root,
        output_root=tmp_path / "runs",
        model="test-model",
        provider="codex",
        runner=failing_runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert results[0].status == "failed"
    assert "analyze exited 1" in results[0].error
    assert "FAILED" in render_summary(results)


def test_run_uat_flattens_sources_and_tests_completed_build(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, name="CommonMark", updated=False)
    source = fixture / "test" / "spec_tests.py"
    source.parent.mkdir()
    source.write_text("# suite\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": "commonmark",
            "sources": ["reading-list.md", "test/spec_tests.py"],
            "updates": [],
            "test_command": ["sh", "full_test.sh"],
        }),
        encoding="utf-8",
    )
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        del env
        parts = tuple(argv)
        calls.append((parts, cwd))
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        returncode = 1 if parts[3:5] == ("status", "commonmark") and "--ready" in parts else 0
        return CommandResult(parts, returncode, 1, str(stdout), str(stderr))

    run_root, results = run_uat(
        tmp_path,
        selected="CommonMark",
        fixtures_root=fixtures_root,
        output_root=tmp_path / "runs",
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert results[0].status == "passed"
    staged_root = run_root / "CommonMark" / "sources"
    assert (staged_root / "spec_tests.py").read_text(encoding="utf-8") == "# suite\n"
    assert not (staged_root / "test").exists()
    assert any(str(staged_root) in argv for argv, _ in calls)
    assert (
        ("sh", "full_test.sh"),
        run_root / "CommonMark" / "build" / "commonmark",
    ) in calls
