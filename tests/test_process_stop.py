"""``BLOCKERS.md`` is the one file that blocks a Target (ReadingList 20261022.205653)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

import drydock.cli
import drydock.llm
from drydock.blockers import (
    DECISION,
    RATE_LIMIT,
    TIMEOUT,
    Blocker,
    Blockers,
    batch_may_run_owner,
    environmental_blocker,
    may_auto_continue,
    parse_blockers,
    read_blockers,
    render_banner,
    render_blockers,
    reset_clock,
    write_blockers,
)
from drydock.cli import _build_parser, _declare_process_stop, _process_stop_gate
from drydock.errors import LlmError
from drydock.llm import FatalStop, fatal_stop, fatal_stop_reason, run_prompt
from tests.test_cli import APPROVED_PLAN_STATUS, run_cli
from tests.test_llm import FakePopen

USAGE_LIMIT = "You've hit your usage limit. Upgrade to Pro or try again at 9:31 PM."
DECLARED = "2026-10-24T18:38:12Z"


@pytest.fixture(autouse=True)
def _clean_process_state(monkeypatch):
    monkeypatch.setattr(drydock.cli, "_owner_run", None)
    monkeypatch.delenv(drydock.cli._OWNER_RERUN_ENV, raising=False)
    yield
    drydock.llm.set_primary_instruction("")


@pytest.mark.parametrize(
    ("error", "provider_error", "timed_out", "kind"),
    [
        (USAGE_LIMIT, f"provider rate limit: {USAGE_LIMIT}", False, "provider rate limit"),
        ("OAuth session expired", None, False, "provider authentication required"),
        ("OAuth token has expired.", None, False, "provider authentication required"),
        (
            "",
            '"api_error_status":429,"api_error":"usage_limit_reached"',
            False,
            "provider rate limit",
        ),
        ("", "rate_limit_error: Number of requests exceeded", False, "provider rate limit"),
        ("execution timed out", None, True, "provider timeout"),
        ("", "provider error 503: Service Unavailable", False, "provider outage"),
        ("", "provider error: Overloaded", False, "provider outage"),
        ("", "provider error 400: invalid request", False, None),
        ("response was not valid JSON", None, False, None),
    ],
)
def test_fatal_stop_reason_names_only_failures_another_call_cannot_fix(
    error, provider_error, timed_out, kind
):
    assert fatal_stop_reason(error, provider_error, timed_out=timed_out) == kind


def _usage_limited(monkeypatch) -> list[object]:
    raw = json.dumps({"type": "turn.failed", "error": {"message": USAGE_LIMIT}}) + "\n"
    spawned: list[object] = []

    def popen(command, **kwargs):
        spawned.append(command)
        return FakePopen(command, stdout_text=raw, returncode=1, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return spawned


def test_a_usage_limit_ends_the_process_provider_work(tmp_path, monkeypatch):
    """A retry loop above run_prompt must not resubmit into the same limit."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    spawned = _usage_limited(monkeypatch)

    first = run_prompt("Work", tmp_path, llm="codex", command_name="build")
    with pytest.raises(LlmError, match="provider rate limit"):
        run_prompt("Work again", tmp_path, llm="codex", command_name="build")

    assert not first.ok
    assert len(spawned) == 1
    stop = fatal_stop()
    assert stop is not None and stop.kind == "provider rate limit"
    assert USAGE_LIMIT in stop.message and stop.execution_id == first.execution_id


# --- 1. One format, written by one function ---------------------------------------------------


def _rate_limited(target: str = "TestTarget", attempts: int = 1, **fields) -> Blockers:
    return Blockers(
        summary="Rate Limit Hit",
        target=target,
        source=f"drydock build {target} --model gpt-6-luna",
        owner=f"build {target}",
        declared=DECLARED,
        execution="exec-1",
        attempts=attempts,
        blockers=(environmental_blocker(RATE_LIMIT, USAGE_LIMIT, declared=DECLARED),),
        **fields,
    )


def _analysis_decision(target: str = "TestTarget", resolution: str = "") -> Blockers:
    return Blockers(
        summary="Pick a database",
        target=target,
        source=f"drydock analyze {target}",
        owner=f"analyze {target}",
        declared=DECLARED,
        blockers=(
            Blocker(
                "blocker-001", "Pick a database", DECISION, question="Which?", resolution=resolution
            ),
        ),
    )


def test_the_file_round_trips_the_standard_format(tmp_path):
    path = write_blockers(tmp_path, _rate_limited())

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Blockers: Rate Limit Hit\n- target: TestTarget\n")
    assert "- owner:" not in text and "- attempts:" not in text and "- execution:" not in text
    assert "<!-- drydock-state:" in text
    assert "## blocker-001: Provider usage limit\n- kind: environmental\n" in text
    assert "- class: provider rate limit\n- auto-continue: after 21:31\n\n### Error\n" in text
    assert "### Commander Resolution" not in text
    assert read_blockers(tmp_path) == _rate_limited()


def test_only_analyze_and_refit_may_raise_a_decision_blocker(tmp_path):
    decision = _analysis_decision()
    with pytest.raises(ValueError, match="may not raise a decision blocker"):
        write_blockers(tmp_path, Blockers(**{**decision.__dict__, "owner": "build TestTarget"}))
    write_blockers(tmp_path, decision)
    write_blockers(tmp_path, Blockers(**{**decision.__dict__, "owner": "refit TestTarget"}))


def test_blocker_time_is_local_and_retry_state_survives_round_trip(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        blockers = _rate_limited(attempts=2)
        text = render_blockers(blockers)
        assert "- declared: 2026-10-24T14:38:12-04:00" in text
        assert parse_blockers(text) == blockers
        assert not batch_may_run_owner(parse_blockers(text))
        banner = render_banner(blockers)
        assert "2026-10-24T14:38:12-04:00" in banner
        assert "Attempts:" not in banner and "exec-1" not in banner
    finally:
        monkeypatch.undo()
        time.tzset()


def test_legacy_blocker_header_still_preserves_owner_and_retry_limit():
    old = (
        "# Blockers: Timeout\n- target: TestTarget\n- source: drydock build TestTarget\n"
        "- owner: build TestTarget\n- declared: 2026-10-24T18:38:12Z\n"
        "- execution: exec-old\n- attempts: 2\n\n"
        "## blocker-001: Timeout\n- kind: environmental\n- class: provider timeout\n"
        "- auto-continue: yes\n### Error\ntimed out\n### Commander Resolution\n"
    )
    parsed = parse_blockers(old)
    assert parsed.owner == "build TestTarget" and parsed.execution == "exec-old"
    assert not batch_may_run_owner(parsed)


def test_a_model_written_blocker_parses_as_a_decision():
    raw = (
        "# Blockers: P\n\n## blocker-001: Pick a db\nWhich database?\n\n"
        "### Commander Resolution\n\n<!-- Enter the decision, then re-run Analyze. -->\n"
    )

    (item,) = parse_blockers(raw).blockers

    assert (item.kind, item.title, item.question, item.resolution) == (
        DECISION,
        "Pick a db",
        "Which database?",
        "",
    )


@pytest.mark.parametrize(
    ("message", "clock"),
    [
        (USAGE_LIMIT, "21:31"),
        ("Usage limit reached. Resets 9pm.", "21:00"),
        ("limit; try again at 07:05", "07:05"),
        ("rate limited", None),
    ],
)
def test_a_rate_limit_reset_is_read_from_its_message(message, clock):
    assert reset_clock(message, None) == clock


def test_auto_continue_waits_for_the_stated_reset():
    blocker = environmental_blocker(RATE_LIMIT, "try again at 23:59", declared=DECLARED)
    declared_local = datetime(2026, 10, 24, 18, 38, 12, tzinfo=UTC).astimezone()
    reset = declared_local.replace(hour=23, minute=59, second=0)
    if reset < declared_local:
        reset = reset.replace(day=reset.day + 1)

    assert not may_auto_continue(blocker, DECLARED, now=declared_local)
    assert may_auto_continue(blocker, DECLARED, now=reset)


@pytest.mark.parametrize(
    "kind", ["provider authentication required", "invalid model", "provider unavailable"]
)
def test_login_model_and_cli_failures_never_auto_continue(kind):
    blocker = environmental_blocker(kind, "failed", declared=DECLARED)
    assert blocker.auto_continue == "no"
    assert not may_auto_continue(blocker, DECLARED, now=datetime(2030, 1, 1, tzinfo=UTC))


# --- 2. Gate and batch rules ------------------------------------------------------------------


def _target(tmp_target_root, monkeypatch):
    from drydock.init_specification import init_specification

    target_dir = tmp_target_root / "TestTarget"
    init_specification("TestTarget", target_dir)
    (target_dir / "MANIFEST.md").write_text(APPROVED_PLAN_STATUS, encoding="utf-8")
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
    return target_dir


def _gate(argv: list[str]):
    return _process_stop_gate(_build_parser().parse_args(argv))


def _timed_out(target_dir: Path, attempts: int = 1) -> None:
    write_blockers(
        target_dir,
        Blockers(**{
            **_rate_limited(attempts=attempts).__dict__,
            "blockers": (environmental_blocker(TIMEOUT, "timed out", declared=DECLARED),),
        }),
    )


def test_a_fatal_stop_is_written_as_an_environmental_blocker(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    drydock.llm._record_fatal_stop(
        FatalStop("provider rate limit", USAGE_LIMIT, "codex", "build", "exec-1")
    )
    argv = ["build", "TestTarget", "--model", "gpt-6-luna"]

    assert _declare_process_stop(_build_parser().parse_args(argv), argv)

    recorded = read_blockers(target_dir)
    assert recorded is not None and recorded.owner == "build TestTarget"
    assert recorded.source == "drydock build TestTarget --model gpt-6-luna"
    assert recorded.execution == "exec-1" and recorded.attempts == 1
    (item,) = recorded.blockers
    assert item.blocker_class == "provider rate limit" and USAGE_LIMIT in item.error
    assert item.auto_continue == "after 21:31"


@pytest.mark.parametrize("recorded", [False, True])
def test_a_fatal_command_ends_with_the_blocker_error(
    tmp_target_root, isolated_config, monkeypatch, recorded
):
    from drydock.errors import RecordedError, SpecificationError, write_error_record

    target_dir = _target(tmp_target_root, monkeypatch)

    def fail(*args):
        print("Earlier progress")
        drydock.llm._record_fatal_stop(
            FatalStop("provider rate limit", USAGE_LIMIT, "codex", "plan", "quota")
        )
        if recorded:
            record = write_error_record(
                target_dir,
                command="plan",
                phase="LLM execution",
                classification="plan generation stalled",
                detail="stale rejection",
                recovery="retry",
            )
            raise RecordedError(record)
        raise SpecificationError("generic failure that hides the quota")

    monkeypatch.setattr(drydock.cli, "_dispatch", fail)
    monkeypatch.setattr(drydock.cli, "_prepare_target_repository", lambda args: None)
    monkeypatch.setattr(
        drydock.cli, "_standoff_diagnosis", lambda *a, **k: pytest.fail("diagnosis after quota")
    )
    rc, out, err = run_cli("plan", "TestTarget")

    assert rc == 1 and "Earlier progress" in out
    assert "BLOCKED: TestTarget" in err
    assert "plan generation stalled" not in err and "generic failure" not in err
    assert err.rstrip().endswith(f"Error: TestTarget: provider rate limit: {USAGE_LIMIT}")
    assert read_blockers(target_dir).execution == "quota"


def test_the_same_class_again_counts_an_attempt(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())
    drydock.llm._record_fatal_stop(
        FatalStop("provider rate limit", USAGE_LIMIT, "codex", "build", "exec-2")
    )

    _declare_process_stop(_build_parser().parse_args(["build", "TestTarget"]), None)

    recorded = read_blockers(target_dir)
    assert recorded is not None and recorded.attempts == 2 and recorded.execution == "exec-2"


@pytest.mark.parametrize("quiet", [False, True])
def test_uat_prints_the_halt_after_reports_and_checkpointing(
    tmp_path, isolated_config, monkeypatch, quiet
):
    import io
    from contextlib import redirect_stderr, redirect_stdout
    from types import SimpleNamespace

    from drydock import uat, uat_git

    case = tmp_path / "case"
    target_dir = case / "workspace" / "targets" / "TestTarget"
    target_dir.mkdir(parents=True)
    write_blockers(target_dir, _rate_limited())
    result = SimpleNamespace(
        status="failed",
        run_id="fake",
        elapsed_ms=1000,
        build_passes=1,
        usage={"calls": 1},
        execution_status="ERROR",
        acceptance_status="NOT_RUN",
        expected_verdict="PASSED",
        observed_verdict="ERROR",
        commands=(),
        degraded=(),
        target="TestTarget",
        fixture="TestTarget",
        output_dir=str(case),
        attestations=(),
        error=f"TestTarget: stopped at build: provider rate limit: {USAGE_LIMIT}",
    )
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(drydock.cli, "_uat_kit_roots", lambda *a, **k: [case])
    monkeypatch.setattr(drydock.cli, "_uat_resume_selection", lambda *a: (None, "init"))
    monkeypatch.setattr(drydock.cli, "_apply_bound_overrides", lambda *a: None)
    monkeypatch.setattr(uat_git, "ensure_kit_repositories", lambda *a: None)
    monkeypatch.setattr(
        uat_git, "checkpoint_kit_repositories", lambda *a: print("Checkpoint saved")
    )
    monkeypatch.setattr(uat, "run_uat", lambda *a, **k: ("fake", (result,)))
    monkeypatch.setattr(uat, "render_summary", lambda *a: "Summary")
    args = _build_parser().parse_args(["uat", "TestTarget", *(["--quiet"] if quiet else [])])
    console = io.StringIO()

    with redirect_stdout(console), redirect_stderr(console):
        assert drydock.cli.cmd_uat(args) == 1

    text = console.getvalue()
    assert text.index("Report:") < text.index("Checkpoint saved") < text.index("BLOCKED:")
    assert "UAT FAILED: TestTarget" in text
    assert "Error: TestTarget: stopped at build: provider rate limit:" in text
    assert text.rstrip().endswith("╯")


def test_ready_reports_a_block_and_ends_the_build_loop(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    assert run_cli("status", "TestTarget", "--ready")[0] == 0
    write_blockers(target_dir, _rate_limited())

    rc, out, err = run_cli("status", "TestTarget", "--ready")

    assert rc == 1
    assert out.startswith("BLOCKED: TestTarget  (build: provider rate limit")
    assert err == ""


def test_status_dashboard_ends_with_the_banner_and_its_recovery(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())

    rc, out, _ = run_cli("status", "TestTarget")

    assert rc == 0
    tail = out[out.index("BLOCKED: TestTarget") :]
    assert "build TestTarget" in tail and "Provider usage limit" in tail
    assert "Wait for the provider limit to reset" in tail


def test_a_batch_non_owner_is_refused(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    _timed_out(target_dir)
    monkeypatch.setattr(
        drydock.llm, "run_prompt", lambda *a, **k: pytest.fail("a blocked Target called a model")
    )

    rc, _, err = run_cli("analyze", "TestTarget")

    assert rc == 1
    assert "drydock analyze refused: TestTarget is blocked." in err
    assert read_blockers(target_dir) is not None


@pytest.mark.parametrize(
    ("attempts", "admitted"),
    [(1, True), (2, False)],
)
def test_a_batch_owner_auto_continues_once(
    tmp_target_root, isolated_config, monkeypatch, attempts, admitted
):
    target_dir = _target(tmp_target_root, monkeypatch)
    _timed_out(target_dir, attempts=attempts)

    assert _gate(["build", "TestTarget"]) is admitted


def test_a_batch_owner_waits_for_the_rate_limit_reset(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())
    blockers = read_blockers(target_dir)
    assert blockers is not None
    before = datetime(2026, 10, 24, 18, 39, tzinfo=UTC)
    after = datetime(2026, 10, 26, tzinfo=UTC)

    assert not batch_may_run_owner(blockers, before)
    assert batch_may_run_owner(blockers, after)


def test_a_batch_decision_owner_needs_every_resolution(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _analysis_decision())
    assert _gate(["analyze", "TestTarget"]) is False

    write_blockers(target_dir, _analysis_decision(resolution="Use SQLite."))
    assert _gate(["analyze", "TestTarget"]) is True


def test_plan_override_passes_an_analysis_decision_only(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _analysis_decision())
    assert _gate(["plan", "TestTarget"]) is False
    assert _gate(["plan", "TestTarget", "--override"]) is True

    _timed_out(target_dir)
    assert _gate(["plan", "TestTarget", "--override"]) is False


@pytest.mark.parametrize(
    "argv",
    [
        ["build", "status", "TestTarget"],
        ["plan", "verify", "TestTarget"],
        ["plan", "repair", "TestTarget"],
    ],
)
def test_every_target_command_refuses_while_blocked(
    tmp_target_root, isolated_config, monkeypatch, argv
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())

    assert _gate(argv) is False


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "TestTarget"],
        ["status", "TestTarget", "--ready"],
        ["uat", "TestTarget"],
        ["run", "quarterdeck", "TestTarget"],
    ],
)
def test_status_run_and_uat_ignore_the_block(tmp_target_root, isolated_config, monkeypatch, argv):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())

    assert _gate(argv) is True


def test_a_refusal_shows_the_error_once_without_internal_metadata(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    path = write_blockers(target_dir, _rate_limited())

    rc, _, err = run_cli("plan", "verify", "TestTarget")

    assert rc == 1
    assert "drydock plan refused: TestTarget is blocked." in err
    assert f"Blocker details: {path}" in err
    assert "Contents of" not in err
    assert "owner:" not in err and "Owner rerun" not in err and "Attempts:" not in err
    assert "execution:" not in err and "auto-continue" not in err
    assert err.count(USAGE_LIMIT) == 1
    assert "Rerun after resolving the error: drydock build TestTarget" in err
    assert "Commander Resolution" not in err
    assert path.is_file()


# --- 3. Interactive "How should we proceed?" and owner rerun ----------------------------------


def _interactive(monkeypatch, answers: list[str]) -> list[str]:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.__stdout__, "isatty", lambda: True, raising=False)
    prompts: list[str] = []

    def answer(prompt):
        prompts.append(prompt)
        return answers.pop(0)

    monkeypatch.setattr("builtins.input", answer)
    return prompts


def test_an_answer_is_written_as_the_commander_resolution(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _analysis_decision())
    prompts = _interactive(monkeypatch, ["Use SQLite."])

    assert _gate(["analyze", "TestTarget"]) is True

    assert prompts == ["How should we proceed? "]
    recorded = read_blockers(target_dir)
    assert recorded is not None and recorded.blockers[0].resolution == "Use SQLite."


def test_q_aborts(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())
    _interactive(monkeypatch, ["q"])
    monkeypatch.setattr(drydock.cli, "_run_owner", lambda b: pytest.fail("owner reran"))

    assert _gate(["diagnose", "TestTarget"]) is False
    assert read_blockers(target_dir) is not None


def test_a_non_owner_reruns_the_owner_then_continues(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())
    _interactive(monkeypatch, [""])
    reran: list[list[str]] = []

    def owner_succeeds(blockers):
        reran.append(blockers.rerun_tokens())
        (target_dir / "BLOCKERS.md").unlink()
        return 0

    monkeypatch.setattr(drydock.cli, "_run_owner", owner_succeeds)

    assert _gate(["diagnose", "TestTarget"]) is True
    assert reran == [["build", "TestTarget", "--model", "gpt-6-luna"]]


def test_a_failed_owner_rerun_ends_the_requested_command(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited())
    _interactive(monkeypatch, [""])
    monkeypatch.setattr(drydock.cli, "_run_owner", lambda blockers: 3)

    assert _gate(["diagnose", "TestTarget"]) == 3


def test_an_owner_success_archives_and_deletes_the_file(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    _timed_out(target_dir)
    assert _gate(["build", "TestTarget"]) is True

    drydock.cli._settle_owner_run(0)

    assert read_blockers(target_dir) is None
    archive = (target_dir / "logs" / "blockers.md").read_text(encoding="utf-8")
    assert "# Blockers: Rate Limit Hit" in archive


def test_an_ordinary_owner_failure_clears_environmental_blockers(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    _timed_out(target_dir)
    assert _gate(["build", "TestTarget"]) is True

    drydock.cli._settle_owner_run(1)

    assert read_blockers(target_dir) is None
    errors = (target_dir / "ERRORS.md").read_text(encoding="utf-8")
    assert "build TestTarget failed" in errors


def test_an_owner_child_is_admitted_without_asking(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _rate_limited(attempts=5))
    monkeypatch.setenv(drydock.cli._OWNER_RERUN_ENV, "build TestTarget")
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("the child asked"))

    assert _gate(["build", "TestTarget"]) is True


# --- 4. Resolution as primary instruction -----------------------------------------------------


def test_an_owner_rerun_leads_its_prompt_with_the_resolution(
    tmp_target_root, isolated_config, monkeypatch
):
    target_dir = _target(tmp_target_root, monkeypatch)
    write_blockers(target_dir, _analysis_decision(resolution="Use SQLite."))

    assert _gate(["analyze", "TestTarget"]) is True

    instruction = drydock.llm.primary_instruction()
    assert instruction.startswith("# Commander Resolution — primary instruction")
    assert "Use SQLite." in instruction


def test_no_resolution_leaves_the_prompt_unchanged(tmp_target_root, isolated_config, monkeypatch):
    target_dir = _target(tmp_target_root, monkeypatch)
    _timed_out(target_dir)

    assert _gate(["build", "TestTarget"]) is True
    assert drydock.llm.primary_instruction() == ""


def test_run_prompt_sends_the_primary_instruction_first(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    spawned: list[FakePopen] = []

    def popen(command, **kwargs):
        spawned.append(FakePopen(command, stdout_text="", returncode=0, **kwargs))
        return spawned[-1]

    monkeypatch.setattr(subprocess, "Popen", popen)
    drydock.llm.set_primary_instruction("# Commander Resolution — primary instruction\n\nGo.\n\n")

    run_prompt("Work", tmp_path, llm="codex", command_name="build")

    sent = spawned[0].stdin.getvalue()
    assert sent.startswith("# Commander Resolution — primary instruction")
    assert sent.rstrip().endswith("Work")


def test_the_rendered_file_parses_back(tmp_path):
    blockers = _analysis_decision(resolution="Use SQLite.")
    assert parse_blockers(render_blockers(blockers)) == blockers
