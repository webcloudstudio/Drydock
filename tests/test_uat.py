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
    (fixture / "spec_1.md").write_text("# Initial\n", encoding="utf-8")
    if updated:
        (fixture / "spec_2.md").write_text("# Updated\n", encoding="utf-8")
    (fixture / "uat.json").write_text(json.dumps({"target": name}), encoding="utf-8")
    return fixture


def test_discover_fixtures_orders_specifications_numerically(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (fixture / "spec_10.md").write_text("# Later\n", encoding="utf-8")

    found = discover_fixtures(tmp_path)

    assert [path.name for path in found[0].specifications] == [
        "spec_1.md",
        "spec_2.md",
        "spec_10.md",
    ]


def test_discover_selected_fixture_rejects_unknown_project(tmp_path: Path) -> None:
    _fixture(tmp_path)

    with pytest.raises(SpecificationError, match="Unknown UAT fixture"):
        discover_fixtures(tmp_path, "Missing")


def test_run_uat_builds_initial_and_updated_specs_and_keeps_scores_advisory(
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
    assert ("refit", "ReadingList", "--sources") in calls
    assert any(call[:2] == ("import", "ReadingList") and "--update" in call for call in calls)
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
