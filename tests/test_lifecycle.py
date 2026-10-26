"""The build lifecycle shared by ``drydock run builder`` and ``drydock uat``."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from drydock.blockers import DECISION, Blocker, Blockers, read_blockers, write_blockers
from drydock.errors import UsageError
from drydock.lifecycle import (
    BLOCKED,
    COMPLETE,
    HALTED,
    INCOMPLETE,
    NEEDS_SOURCES,
    BuildRun,
    Lifecycle,
    Policy,
    Position,
    SourceInput,
    render_outcome,
)
from drydock.uat import CommandResult

Rule = Callable[[tuple[str, ...], dict[str, str]], int]


class FakeDrydock:
    """A runner that plays each child command against a real temporary Target directory."""

    def __init__(self, target_dir: Path, rules: dict[str, Rule] | None = None) -> None:
        self.target_dir = target_dir
        self.rules = rules or {}
        self.calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
        self.ready = [0, 1]

    def __call__(self, argv, cwd, env, output_dir, label) -> CommandResult:
        parts = tuple(argv[3:])
        name = label.split("-", 1)[1]
        self.calls.append((name, parts, env))
        output_dir.mkdir(parents=True, exist_ok=True)
        stdout = output_dir / f"{label}.stdout.log"
        stderr = output_dir / f"{label}.stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        rule = next((rule for key, rule in self.rules.items() if name.startswith(key)), None)
        code = rule(parts, env) if rule is not None else self._default(parts)
        return CommandResult(tuple(argv), code, 5, str(stdout), str(stderr), label, str(cwd))

    def _default(self, parts: tuple[str, ...]) -> int:
        root = self.target_dir
        if parts[0] == "init":
            (root / "blueprint" / "sources").mkdir(parents=True, exist_ok=True)
            (root / "METADATA.md").write_text("# Metadata\n", encoding="utf-8")
        elif parts[0] == "import":
            (root / "blueprint" / "sources" / "spec.md").write_text("# Spec\n", encoding="utf-8")
        elif parts[0] == "analyze":
            (root / "ANALYSIS.md").write_text("# Analysis\n", encoding="utf-8")
        elif parts[:2] == ("plan", root.name):
            (root / "MANIFEST.md").write_text("# Manifest\n", encoding="utf-8")
        elif parts[0] == "status" and parts[-1] == "--ready":
            return self.ready.pop(0) if self.ready else 1
        return 0

    def labels(self) -> list[str]:
        return [name for name, _, _ in self.calls]


def _run(target_dir: Path, fake: FakeDrydock, **kwargs) -> tuple[BuildRun, object]:
    run = BuildRun(
        target_dir.name,
        target_dir,
        kwargs.pop("policy", Policy(repair_attempts=2, diagnose_attempts=1)),
        runner=fake,
        env={"DRYDOCK_MODEL": "sonnet"},
        run_id="20261025.120000",
        **kwargs,
    )
    return run, run.execute()


def _journal(run: BuildRun) -> list[dict]:
    return [json.loads(line) for line in run.journal.path.read_text().splitlines()]


def _source(tmp_path: Path) -> SourceInput:
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")
    return SourceInput.parse(str(spec), directory=False)


# -- SourceInput ------------------------------------------------------------------------------


def test_source_input_defaults_and_named_formats(tmp_path: Path) -> None:
    spec = tmp_path / "INTENT.md"
    spec.write_text("intent\n", encoding="utf-8")
    assert SourceInput.parse(str(spec), directory=False).format == "auto"
    assert SourceInput.parse(f"compass={spec}", directory=False) == SourceInput(spec, "compass")
    assert SourceInput.parse(str(tmp_path), directory=True).format == "markdown"
    assert SourceInput.parse(f"source={tmp_path}", directory=True).format == "source"


def test_source_input_rejects_a_missing_path_and_auto_for_a_directory(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="--infile: not a file"):
        SourceInput.parse(str(tmp_path / "absent.md"), directory=False)
    with pytest.raises(UsageError, match="--indir: not a directory"):
        SourceInput.parse(str(tmp_path / "absent"), directory=True)
    with pytest.raises(UsageError, match="needs markdown or source"):
        SourceInput.parse(f"auto={tmp_path}", directory=True)


# -- Lifecycle loop policy -------------------------------------------------------------------


def _lifecycle(codes: dict[str, list[int]], policy: Policy):
    calls: list[str] = []
    halts: list[str] = []

    def execute(parts, label, *, required=True):
        calls.append(label)
        queue = next((q for key, q in codes.items() if label.endswith(key)), [0])
        code = queue.pop(0) if len(queue) > 1 else queue[0]
        return CommandResult(("drydock", *parts), code, 1, "", "", label)

    def halt(stage, reason, *, summary, result=None, explanation=""):
        halts.append(summary or stage)

    return Lifecycle("Demo", policy, execute=execute, halt=halt), calls, halts


def test_a_failed_build_is_diagnosed_once_then_rebuilt() -> None:
    lifecycle, calls, halts = _lifecycle(
        {"-ready": [0, 0, 1], "-build-1": [1]}, Policy(repair_attempts=1, diagnose_attempts=1)
    )
    assert lifecycle.build("initial") == COMPLETE
    assert calls == [
        "initial-ready",
        "initial-build-1",
        "initial-diagnose-1",
        "initial-ready",
        "initial-build-2",
        "initial-ready",
        "initial-complete",
    ]
    assert not halts


def test_without_a_diagnose_budget_a_failed_build_halts() -> None:
    lifecycle, calls, halts = _lifecycle(
        {"-ready": [0], "-build-1": [1]}, Policy(repair_attempts=1)
    )
    assert lifecycle.build("initial") == HALTED
    assert calls == ["initial-ready", "initial-build-1"]
    assert halts == ["initial-build-1 exited 1"]


def test_unfinished_work_is_diagnosed_then_reported_incomplete_past_the_budget() -> None:
    lifecycle, calls, _ = _lifecycle(
        {"-ready": [0, 1, 1], "-complete": [1]}, Policy(repair_attempts=1, diagnose_attempts=1)
    )
    assert lifecycle.build("initial") == INCOMPLETE
    assert calls == [
        "initial-ready",
        "initial-build-1",
        "initial-ready",
        "initial-complete",
        "initial-diagnose-1",
        "initial-ready",
        "initial-complete",
    ]


def test_unattended_policy_waives_gates_and_routes_the_plan_model() -> None:
    seen: list[tuple[str, ...]] = []

    def execute(parts, label, *, required=True):
        seen.append(tuple(parts))
        return CommandResult(tuple(parts), 0, 1, "", "", label)

    policy = Policy(repair_attempts=3, unattended=True, plan_model="opus")
    lifecycle = Lifecycle("Demo", policy, execute=execute, halt=lambda *a, **k: None)
    lifecycle.plan()
    lifecycle.verify_plan()
    assert seen == [
        ("plan", "Demo", "--override", "--plan-override-model", "opus"),
        ("plan", "verify", "Demo", "--plan-override-model", "opus"),
    ]


# -- Position --------------------------------------------------------------------------------


def test_position_reads_the_next_stage_from_the_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "Demo"
    assert Position.of(target).next_stage() == "init"
    (target / "blueprint" / "sources").mkdir(parents=True)
    (target / "METADATA.md").write_text("x", encoding="utf-8")
    (target / "blueprint" / "sources" / ".gitkeep").write_text("", encoding="utf-8")
    assert Position.of(target).next_stage() == "import"
    (target / "blueprint" / "sources" / "spec.md").write_text("x", encoding="utf-8")
    (target / "ANALYSIS.md").write_text("x", encoding="utf-8")
    assert Position.of(target).next_stage() == "plan"


# -- BuildRun --------------------------------------------------------------------------------


def test_a_fresh_target_runs_the_whole_lifecycle_and_journals_it(tmp_path: Path) -> None:
    target = tmp_path / "targets" / "Demo"
    fake = FakeDrydock(target)
    run, outcome = _run(target, fake, inputs=(_source(tmp_path),))

    assert outcome.status == COMPLETE and outcome.exit_code == 0
    assert fake.labels() == [
        "init",
        "import-sources",
        "analyze",
        "plan",
        "plan-verify",
        "after-plan-build-status",
        "initial-ready",
        "initial-build-1",
        "initial-ready",
        "initial-complete",
        "after-initial-build-build-status",
    ]
    build = next(parts for name, parts, _ in fake.calls if name == "initial-build-1")
    assert build == ("build", "Demo", "--repair-attempts", "2")
    records = _journal(run)
    assert [r["event"] for r in records] == ["start", *["step"] * 11, "end"]
    assert records[0]["stages"] == ["init", "import", "analyze", "plan", "verify", "build"]
    assert records[0]["next_stage"] == "init"
    assert records[1]["stage"] == "init" and records[1]["argv"] == ["drydock", "init", "Demo"]
    assert records[1]["stdout"] == "commands/01-init.stdout.log"
    assert records[-1]["status"] == COMPLETE
    assert run.journal.path == target / "logs" / "runs" / "20261025.120000" / "RUN.jsonl"


def test_a_complete_target_says_so_and_exits(tmp_path: Path) -> None:
    target = tmp_path / "targets" / "Demo"
    _run(target, FakeDrydock(target), inputs=(_source(tmp_path),))
    (target / "PROJECT_STATUS.jsonl").write_text(
        json.dumps({"label": "BUILT", "result": "pass", "at": "2026-10-25T12:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    fake = FakeDrydock(target)
    fake.ready = []
    _, outcome = _run(target, fake)

    assert outcome.status == COMPLETE
    assert fake.labels() == [
        "initial-ready",
        "initial-unstarted-check",
        "initial-complete",
        "after-initial-build-build-status",
    ]
    assert render_outcome(outcome, "Demo").startswith("╭─ BUILD COMPLETE: Demo")


def test_a_target_without_sources_or_inputs_stops_after_init(tmp_path: Path) -> None:
    target = tmp_path / "targets" / "Demo"
    fake = FakeDrydock(target)
    _, outcome = _run(target, fake)
    assert outcome.status == NEEDS_SOURCES and outcome.exit_code == 2
    assert fake.labels() == ["init"]
    assert "--infile or --indir" in outcome.reason


def _analysis_question(target: Path) -> None:
    write_blockers(
        target,
        Blockers(
            summary="Analysis question",
            target=target.name,
            source=f"drydock analyze {target.name}",
            owner=f"analyze {target.name}",
            blockers=(Blocker("blocker-001", "Which store?", DECISION, question="SQL or files?"),),
        ),
    )


def _blocked_plan(target: Path) -> FakeDrydock:
    def analyze(parts, env):
        (target / "ANALYSIS.md").write_text("# Analysis\n", encoding="utf-8")
        if env.get("DRYDOCK_OWNER_RERUN"):
            (target / "BLOCKERS.md").unlink()
        else:
            _analysis_question(target)
        return 0

    def plan(parts, env):
        if read_blockers(target) is not None:
            return 1  # the stop gate refuses a non-owner
        (target / "MANIFEST.md").write_text("# Manifest\n", encoding="utf-8")
        return 0

    return FakeDrydock(target, {"analyze": analyze, "plan": plan, "owner-rerun": analyze})


def test_a_question_is_asked_and_its_owner_rerun_before_the_lifecycle_continues(
    tmp_path: Path,
) -> None:
    target = tmp_path / "targets" / "Demo"
    fake = _blocked_plan(target)
    asked: list[str] = []
    shown: list[str] = []

    def ask(target_dir: Path, blockers: Blockers) -> bool:
        asked.append(blockers.owner)
        return True

    run, outcome = _run(
        target,
        fake,
        inputs=(_source(tmp_path),),
        ask=ask,
        on_blocker=lambda blockers: shown.append(blockers.summary),
    )

    assert outcome.status == COMPLETE
    assert asked == ["analyze Demo"] and shown == ["Analysis question"]
    labels = fake.labels()
    assert labels[:6] == [
        "init",
        "import-sources",
        "analyze",
        "plan",
        "owner-rerun-analyze",
        "plan",
    ]
    rerun = fake.calls[4]
    assert rerun[1] == ("analyze", "Demo")
    assert rerun[2]["DRYDOCK_OWNER_RERUN"] == "analyze Demo"
    events = [r for r in _journal(run) if r["event"] == "blocker"]
    assert events[0]["owner"] == "analyze Demo" and events[0]["outcome"] == "owner rerun"


def test_an_unanswered_question_stops_an_unattended_run(tmp_path: Path) -> None:
    target = tmp_path / "targets" / "Demo"
    fake = _blocked_plan(target)
    run, outcome = _run(target, fake, inputs=(_source(tmp_path),))

    assert outcome.status == BLOCKED and outcome.exit_code == 1
    assert fake.labels() == ["init", "import-sources", "analyze", "plan"]
    assert _journal(run)[-2]["outcome"] == "refused unattended"


def test_uat_lifecycle_sequence_is_unchanged(tmp_path: Path) -> None:
    """The extracted lifecycle issues UAT's established step sequence."""
    from datetime import UTC, datetime

    from drydock.uat import run_uat

    kit = tmp_path / "fx" / "ReadingList"
    (kit / "sources").mkdir(parents=True)
    (kit / "sources" / "reading-list.md").write_text("# Initial\n", encoding="utf-8")
    (kit / "uat.json").write_text(
        json.dumps({
            "target": "ReadingList",
            "sources": ["sources/reading-list.md"],
            "updates": [],
            "test_command": ["sh", "bin/test.sh"],
            "acceptance": {"full": ["sh", "sources/full_test.sh"]},
        }),
        encoding="utf-8",
    )
    labels: list[str] = []
    ready = [0, 1]

    def runner(argv, cwd, env, output_dir, label):
        labels.append(label)
        output_dir.mkdir(parents=True, exist_ok=True)
        out, err = output_dir / f"{label}.out", output_dir / f"{label}.err"
        out.write_text("", encoding="utf-8")
        err.write_text("", encoding="utf-8")
        code = (ready.pop(0) if ready else 1) if label.endswith("-ready") else 0
        return CommandResult(tuple(argv), code, 1, str(out), str(err), label, str(cwd))

    run_uat(
        tmp_path,
        selected=None,
        uat_root=tmp_path / "fx",
        model="m",
        provider="claude",
        runner=runner,
        now=datetime(2026, 8, 7, tzinfo=UTC),
    )
    assert labels == [
        "01-init",
        "02-import-sources",
        "03-analyze",
        "04-plan",
        "05-plan-verify",
        "06-after-plan-build-status",
        "07-after-plan-target-status",
        "08-after-plan-workspace-status",
        "09-initial-ready",
        "10-initial-build-1",
        "11-initial-ready",
        "12-initial-complete",
        "13-after-initial-build-build-status",
        "14-after-initial-build-target-status",
        "15-after-initial-build-workspace-status",
        "16-test",
        "17-score-acceptance",
        "18-score-build-report",
        "19-score-release",
    ]


# -- CLI -------------------------------------------------------------------------------------


def _cli(*args: str) -> tuple[int, str, str]:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    from drydock.cli import main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            main(list(args))
        except SystemExit as exc:
            return int(exc.code or 0), out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


def test_infile_and_indir_repeat_in_command_line_order() -> None:
    from drydock.cli import _build_parser

    ns = _build_parser().parse_args([
        "run",
        "builder",
        "Demo",
        "--infile",
        "compass=I.md",
        "--indir",
        "specs",
        "--infile",
        "b",
    ])
    assert ns.inputs == [("file", "compass=I.md"), ("dir", "specs"), ("file", "b")]


def test_run_builder_accepts_the_plan_model_and_rejects_a_missing_input(
    isolated_config, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    rc, _, err = _cli(
        "run", "builder", "Demo", "--plan-override-model", "opus", "--indir", str(tmp_path / "x")
    )
    assert rc == 2
    assert "--indir: not a directory" in err


def test_run_builder_drives_the_lifecycle_and_closes_with_its_outcome(
    isolated_config, tmp_path: Path, monkeypatch
) -> None:
    import drydock.uat

    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    target = tmp_path / "targets" / "Demo"
    fake = FakeDrydock(target)
    monkeypatch.setattr(drydock.uat, "make_streaming_runner", lambda sink: fake)
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec\n", encoding="utf-8")

    rc, out, _ = _cli("run", "builder", "Demo", "--infile", str(spec), "--model", "sonnet")

    assert rc == 0
    assert "BUILD COMPLETE: Demo" in out
    imported = next(parts for name, parts, _ in fake.calls if name == "import-sources")
    assert imported == ("import", "Demo", str(spec.resolve()), "--format", "auto")
    assert all(env["DRYDOCK_MODEL"] == "sonnet" for _, _, env in fake.calls)
    assert all("DRYDOCK_PARENT_TRANSCRIPT" not in env for _, _, env in fake.calls)
    assert list((target / "logs" / "runs").glob("*/RUN.jsonl"))


def test_a_diagnosis_that_fails_halts_the_build() -> None:
    lifecycle, calls, halts = _lifecycle(
        {"-ready": [1], "-unstarted-check": [1], "-diagnose-1": [1]},
        Policy(repair_attempts=1, diagnose_attempts=1),
    )
    assert lifecycle.build("initial") == HALTED
    assert calls == ["initial-ready", "initial-unstarted-check", "initial-diagnose-1"]
    assert halts == ["initial: diagnosis did not restore progress"]
