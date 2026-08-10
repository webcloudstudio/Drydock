from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drydock import technology_stack
from drydock.errors import SpecificationError
from drydock.uat import (
    CommandResult,
    discover_fixtures,
    make_streaming_runner,
    render_summary,
    run_uat,
    subprocess_runner,
)


def _fixture(root: Path, name: str = "ReadingList", *, updated: bool = True) -> Path:
    fixture = root / name
    fixture.mkdir(parents=True)
    (fixture / "sources").mkdir()
    (fixture / "sources" / "reading-list.md").write_text("# Initial\n", encoding="utf-8")
    updates: list[str] = []
    if updated:
        update = fixture / "updates" / "reading-list.md"
        update.parent.mkdir()
        update.write_text("# Updated\n", encoding="utf-8")
        updates.append("updates/reading-list.md")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": name,
            "sources": ["sources/reading-list.md"],
            "updates": updates,
            "test_command": ["sh", "bin/test.sh"],
        }),
        encoding="utf-8",
    )
    return fixture


def test_discover_fixture_uses_explicit_sources_and_updates(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    found = discover_fixtures(tmp_path)[0]

    assert found.sources == ((fixture / "sources" / "reading-list.md").resolve(),)
    assert found.updates == ((fixture / "updates" / "reading-list.md").resolve(),)
    assert found.test_command == ("sh", "bin/test.sh")


def test_discover_fixture_reads_declared_technology_stack(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (fixture / "TECHNOLOGY_STACK.md").write_text(
        technology_stack.render([technology_stack.StackEntry("Go", "go.md")], "2026-08-09"),
        encoding="utf-8",
    )

    found = discover_fixtures(tmp_path)[0]

    assert found.stack == fixture / "TECHNOLOGY_STACK.md"


def test_discover_fixture_without_technology_stack_leaves_the_choice_to_analyze(
    tmp_path: Path,
) -> None:
    _fixture(tmp_path)

    assert discover_fixtures(tmp_path)[0].stack is None


def test_discover_fixture_rejects_technology_stack_naming_unknown_rigging_file(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    (fixture / "TECHNOLOGY_STACK.md").write_text(
        technology_stack.render([technology_stack.StackEntry("Go", "nosuchstack.md")]),
        encoding="utf-8",
    )

    with pytest.raises(SpecificationError, match="nosuchstack.md"):
        discover_fixtures(tmp_path)


def test_discover_fixture_rejects_empty_technology_stack(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (fixture / "TECHNOLOGY_STACK.md").write_text("# Technology Stack\n", encoding="utf-8")

    with pytest.raises(SpecificationError, match="declares no technologies"):
        discover_fixtures(tmp_path)


def test_run_uat_seeds_declared_stack_into_target_before_analyze(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, updated=False)
    declared = technology_stack.render([technology_stack.StackEntry("Go", "go.md")], "2026-08-09")
    (fixture / "TECHNOLOGY_STACK.md").write_text(declared, encoding="utf-8")
    seen_at_analyze: list[str] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        parts = tuple(argv[3:])
        if parts[:1] == ("analyze",):
            path = (
                Path(env["DRYDOCK_WORKSPACE"])
                / "targets"
                / "ReadingList"
                / technology_stack.FILENAME
            )
            seen_at_analyze.append(path.read_text(encoding="utf-8"))
        returncode = 1 if parts[:2] == ("status", "ReadingList") and "--ready" in parts else 0
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert seen_at_analyze == [declared]


def test_discover_selected_fixture_rejects_unknown_project(tmp_path: Path) -> None:
    _fixture(tmp_path)

    with pytest.raises(SpecificationError, match="Unknown UAT kit"):
        discover_fixtures(tmp_path, "Missing")


def test_discover_fixture_loads_nested_local_source(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, updated=False)
    source = fixture / "kit" / "suite.py"
    source.parent.mkdir()
    source.write_text("# suite\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": "Example",
            "sources": ["sources/reading-list.md", "kit/suite.py"],
            "updates": [],
            "test_command": ["sh", "full_test.sh"],
        }),
        encoding="utf-8",
    )

    found = discover_fixtures(tmp_path)[0]

    assert found.sources == (
        (fixture / "sources" / "reading-list.md").resolve(),
        source.resolve(),
    )
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
            "sources": ["sources/reading-list.md", "kit/reading-list.md"],
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
            "sources": ["sources/reading-list.md"],
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
        del env
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
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_id, results = run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
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
    assert ("build", "status", "ReadingList") in calls
    assert ("status", "ReadingList") in calls
    assert ("status",) in calls
    case_root = fixtures_root / "ReadingList" / "runs" / run_id
    assert (case_root / "sources" / "reading-list.md").read_text() == "# Updated\n"
    evidence = json.loads((case_root / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    labels = [command["label"] for command in evidence["commands"]]
    assert any(label.endswith("after-refit-1-build-status") for label in labels)
    assert any(label.endswith("after-refit-1-build-workspace-status") for label in labels)
    assert (case_root / "result.json").is_file()
    assert "ReadingList: PASSED" in (case_root / "README.md").read_text(encoding="utf-8")
    assert (case_root / "index.html").is_file()


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
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=failing_runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    assert results[0].status == "failed"
    assert "analyze exited 1" in results[0].error
    assert "FAILED" in render_summary(results)
    evidence = Path(results[0].evidence_dir)
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["commands"]) == 3
    assert manifest["commands"][2]["returncode"] == 1
    assert manifest["commands"][2]["stdout"]["sha256"]
    assert manifest["commands"][2]["stderr"]["sha256"]
    assert (evidence / "README.md").is_file()


def test_uat_collects_llm_prompts_outputs_and_raw_transcripts(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    def evidence_runner(argv, cwd, env, output_dir, label):
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("standard output", encoding="utf-8")
        stderr.write_text("standard error", encoding="utf-8")
        logs = Path(env["DRYDOCK_WORKSPACE"]) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "call.prompt.md").write_text("prompt", encoding="utf-8")
        (logs / "call.output.txt").write_text("answer", encoding="utf-8")
        (logs / "call.raw.jsonl").write_text("{}\n", encoding="utf-8")
        (logs / "llm.jsonl").write_text("", encoding="utf-8")
        parts = tuple(argv)
        returncode = 1 if parts[3:5] == ("status", "ReadingList") and "--ready" in parts else 0
        return CommandResult(parts, returncode, 1, str(stdout), str(stderr), label, str(cwd))

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=evidence_runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )

    evidence = Path(results[0].evidence_dir)
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    assert (evidence / "prompts" / "call.prompt.md").read_text() == "prompt"
    assert (evidence / "prompt_outputs" / "call.output.txt").read_text() == "answer"
    assert (evidence / "provider_raw" / "call.raw.jsonl").read_text() == "{}\n"
    assert {item["kind"] for item in manifest["llm_artifacts"]} == {
        "prompt",
        "prompt_output",
        "provider_raw",
        "llm_execution_records",
    }
    labels = [command["label"] for command in manifest["commands"]]
    for suffix in (
        "after-plan-build-status",
        "after-plan-target-status",
        "after-plan-workspace-status",
        "after-initial-build-build-status",
        "after-initial-build-target-status",
        "after-initial-build-workspace-status",
    ):
        assert any(label.endswith(suffix) for label in labels)


def test_run_uat_flattens_sources_and_tests_completed_build(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    fixture = _fixture(fixtures_root, name="CommonMark", updated=False)
    source = fixture / "test" / "spec_tests.py"
    source.parent.mkdir()
    source.write_text("# suite\n", encoding="utf-8")
    (fixture / "uat.json").write_text(
        json.dumps({
            "target": "commonmark",
            "sources": ["sources/reading-list.md", "test/spec_tests.py"],
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

    run_id, results = run_uat(
        tmp_path,
        selected="CommonMark",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert results[0].status == "passed"
    staged_root = fixtures_root / "CommonMark" / "runs" / run_id / "sources"
    assert (staged_root / "spec_tests.py").read_text(encoding="utf-8") == "# suite\n"
    assert not (staged_root / "test").exists()
    assert any(str(staged_root) in argv for argv, _ in calls)
    assert (
        ("sh", "full_test.sh"),
        fixtures_root / "CommonMark" / "runs" / run_id / "build" / "commonmark",
    ) in calls


def test_run_uat_marks_every_child_command_as_a_uat_run(tmp_path: Path) -> None:
    # The mode has to cross a process boundary: each step is a separate `python -m drydock`.
    # `build` reads this to spend its whole repair budget instead of stopping on a flat pass.
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    seen: list[str | None] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        seen.append(env.get("DRYDOCK_UAT"))
        parts = tuple(argv[3:])
        returncode = 1 if parts[:2] == ("status", "ReadingList") and "--ready" in parts else 0
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert seen and set(seen) == {"1"}


class _RecordingSink:
    """Collect what a streaming runner reports, in order, without any console formatting."""

    def __init__(self) -> None:
        self.steps: list[tuple[tuple[str, ...], str]] = []
        self.chunks: list[tuple[str, str]] = []
        self.finished: list[tuple[int, int]] = []

    def step(self, argv, label) -> None:
        self.steps.append((tuple(argv), label))

    def chunk(self, source, text) -> None:
        self.chunks.append((source, text))

    def finish(self, returncode, elapsed_ms) -> None:
        self.finished.append((returncode, elapsed_ms))

    def text(self, source: str) -> str:
        return "".join(text for name, text in self.chunks if name == source)


def _child(program: str) -> tuple[str, ...]:
    return (sys.executable, "-c", program)


def test_subprocess_runner_tees_both_streams_to_the_sink_and_to_evidence(tmp_path: Path) -> None:
    sink = _RecordingSink()
    program = (
        "import sys\n"
        "sys.stdout.write('building step 1\\n')\n"
        "sys.stderr.write('warning: no stack\\n')\n"
        "sys.stdout.write('done\\n')\n"
    )

    result = subprocess_runner(
        _child(program), tmp_path, dict(os.environ), tmp_path, "07-build", sink=sink
    )

    assert result.returncode == 0
    assert result.label == "07-build"
    assert sink.steps == [(tuple(_child(program)), "07-build")]
    assert sink.text("stdout") == "building step 1\ndone\n"
    assert sink.text("stderr") == "warning: no stack\n"
    # The evidence logs still hold the child's complete output, unchanged by the console.
    assert Path(result.stdout_path).read_text(encoding="utf-8") == "building step 1\ndone\n"
    assert Path(result.stderr_path).read_text(encoding="utf-8") == "warning: no stack\n"
    assert sink.finished and sink.finished[0][0] == 0


def test_subprocess_runner_preserves_carriage_returns_and_unterminated_lines(
    tmp_path: Path,
) -> None:
    # A progress line redraws with \r and never ends with \n. Line-buffered teeing would hold
    # it back until the process exited, which is the failure this runner exists to prevent.
    sink = _RecordingSink()
    program = "import sys\nsys.stdout.write('pass 1\\rpass 2')\n"

    result = subprocess_runner(
        _child(program), tmp_path, dict(os.environ), tmp_path, "08-progress", sink=sink
    )

    assert sink.text("stdout") == "pass 1\rpass 2"
    # Read as bytes: universal-newline decoding would hide whether the \r survived.
    assert Path(result.stdout_path).read_bytes() == b"pass 1\rpass 2"


def test_subprocess_runner_reports_a_failing_child_with_its_output_preserved(
    tmp_path: Path,
) -> None:
    sink = _RecordingSink()
    program = "import sys\nsys.stderr.write('boom\\n')\nraise SystemExit(3)\n"

    result = subprocess_runner(
        _child(program), tmp_path, dict(os.environ), tmp_path, "09-fail", sink=sink
    )

    assert result.returncode == 3
    assert sink.finished[0][0] == 3
    assert Path(result.stderr_path).read_text(encoding="utf-8") == "boom\n"


def test_streaming_runner_matches_the_runner_contract(tmp_path: Path) -> None:
    sink = _RecordingSink()
    runner = make_streaming_runner(sink)

    result = runner(_child("print('ok')"), tmp_path, dict(os.environ), tmp_path, "01-init")

    assert result.returncode == 0
    assert sink.text("stdout").strip() == "ok"
    assert sink.steps[0][1] == "01-init"


def test_run_uat_gives_every_child_an_unbuffered_environment(tmp_path: Path) -> None:
    # Buffering into a pipe would withhold a step's output until it exited.
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    seen: list[str | None] = []

    def fake_runner(argv, cwd, env, output_dir, label):
        seen.append(env.get("PYTHONUNBUFFERED"))
        parts = tuple(argv[3:])
        returncode = 1 if parts[:2] == ("status", "ReadingList") and "--ready" in parts else 0
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    run_uat(
        tmp_path,
        selected=None,
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=fake_runner,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert seen and set(seen) == {"1"}


def _stub_runner(calls: list[tuple[str, ...]], *, fail: tuple[str, ...] = ()):
    """Return a runner that records lifecycle argv and fails the named stage."""

    def runner(argv, cwd, env, output_dir, label):
        del env
        parts = tuple(argv[3:])
        calls.append(parts)
        returncode = 0
        if parts[:2] == ("status", "ReadingList") and "--ready" in parts:
            returncode = 1  # never ready: one status check, no build pass
        if fail and parts[: len(fail)] == fail:
            returncode = 1
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(tuple(argv), returncode, 10, str(stdout), str(stderr), label, str(cwd))

    return runner


def _seed_target_artifact(fixtures_root: Path, run_id: str, name: str) -> None:
    """Write the Target artifact a resumed stage requires, which a fake runner never produces."""
    target = (
        fixtures_root / "ReadingList" / "runs" / run_id / "workspace" / "targets" / "ReadingList"
    )
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_text(f"# {name}\n", encoding="utf-8")


def test_resume_reenters_the_newest_run_at_the_named_stage(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    first: list[tuple[str, ...]] = []
    run_id, failed = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner(first, fail=("plan",)),
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    assert failed[0].status == "failed"
    _seed_target_artifact(fixtures_root, run_id, "ANALYSIS.md")

    resumed_calls: list[tuple[str, ...]] = []
    resumed_id, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner(resumed_calls),
        start_stage="plan",
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    # The resumed run re-enters the same directory: no new run id, no repeated LLM stages.
    assert resumed_id == run_id
    assert results[0].status == "passed"
    assert results[0].resumed_from == "plan"
    assert ("plan", "ReadingList", "--override") in resumed_calls
    assert not [parts for parts in resumed_calls if parts[:1] in {("init",), ("analyze",)}]
    assert not [parts for parts in resumed_calls if parts[:1] == ("import",)]


def test_resume_appends_to_the_prior_evidence_instead_of_overwriting_it(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    run_id, failed = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner([], fail=("plan",)),
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    case_root = fixtures_root / "ReadingList" / "runs" / run_id
    before = sorted(path.name for path in (case_root / "evidence" / "commands").glob("*.log"))
    _seed_target_artifact(fixtures_root, run_id, "ANALYSIS.md")

    _, results = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner([]),
        start_stage="plan",
        now=datetime(2026, 8, 10, tzinfo=UTC),
    )

    after = sorted(path.name for path in (case_root / "evidence" / "commands").glob("*.log"))
    assert set(before) <= set(after)
    # The prior attempt's commands stay in the receipt; the new ones continue the numbering.
    labels = [command.label for command in results[0].commands]
    assert labels[: len(failed[0].commands)] == [c.label for c in failed[0].commands]
    assert int(after[-1].split("-", 1)[0]) > int(before[-1].split("-", 1)[0])


def test_resume_rejects_an_unknown_stage_and_a_run_without_a_stage(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    with pytest.raises(SpecificationError, match="Unknown UAT stage"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner([]),
            start_stage="compile",
        )
    with pytest.raises(SpecificationError, match="resume stage"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner([]),
            run="20260809T000000.000000Z",
        )


def test_resume_without_a_prior_run_names_the_missing_history(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)

    with pytest.raises(SpecificationError, match="No completed run to resume"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner([]),
            start_stage="build",
        )


def test_resume_into_a_stage_with_no_input_names_the_producing_stage(tmp_path: Path) -> None:
    # Resuming at `build` after a failed `plan` must not spend two commands discovering that
    # no MANIFEST.md exists; it must name the stage that produces one.
    fixtures_root = tmp_path / "fixtures"
    _fixture(fixtures_root, updated=False)
    run_id, _ = run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner([], fail=("plan",)),
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    target = fixtures_root / "ReadingList" / "runs" / run_id / "workspace" / "targets"
    (target / "ReadingList").mkdir(parents=True)
    (target / "ReadingList" / "ANALYSIS.md").write_text("# analysis\n", encoding="utf-8")

    calls: list[tuple[str, ...]] = []
    with pytest.raises(SpecificationError, match=r"MANIFEST.md does not exist"):
        run_uat(
            tmp_path,
            selected="ReadingList",
            uat_root=fixtures_root,
            model="test-model",
            provider="codex",
            runner=_stub_runner(calls),
            start_stage="build",
        )
    assert calls == []

    # The stage whose input does exist is accepted.
    run_uat(
        tmp_path,
        selected="ReadingList",
        uat_root=fixtures_root,
        model="test-model",
        provider="codex",
        runner=_stub_runner(calls),
        start_stage="plan",
    )
    assert ("plan", "ReadingList", "--override") in calls
