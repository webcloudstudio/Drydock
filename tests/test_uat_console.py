from __future__ import annotations

import io
from datetime import datetime

import pytest

from drydock.uat_console import StepConsole, format_argv


def _console(**kwargs) -> tuple[StepConsole, io.StringIO]:
    stream = io.StringIO()
    console = StepConsole(
        stream,
        width=60,
        clock=lambda: datetime(2026, 8, 9, 14, 3, 11),
        **kwargs,
    )
    return console, stream


def test_format_argv_reads_as_a_typed_command() -> None:
    assert format_argv(("/usr/bin/python3", "-m", "drydock", "analyze", "Toml")) == (
        "drydock analyze Toml"
    )
    assert format_argv(("sh", "bin/test.sh")) == "sh bin/test.sh"


def test_format_argv_keeps_a_multi_line_argument_on_one_line() -> None:
    line = format_argv(("python", "-c", "import sys\nprint('x')\n"))

    assert line == "python -c import sys print('x')"


def test_step_frames_child_output_with_stage_headers_and_a_gutter() -> None:
    console, stream = _console()

    console.event("Toml: analyze")
    console.step(("/usr/bin/python3", "-m", "drydock", "analyze", "Toml"), "09-analyze")
    console.chunk("stdout", "Analyzing Blueprint\n")
    console.chunk("stderr", "warning: no stack\n")
    console.finish(0, 64200)

    lines = stream.getvalue().splitlines()
    assert lines[1].startswith("── DRYDOCK ANALYZE TOML ")
    assert lines[1].endswith("14:03:11 ──")
    assert lines[2] == "   drydock analyze Toml"
    assert lines[3] == " │ Analyzing Blueprint"
    assert lines[4] == " ! warning: no stack"
    assert "OK   1m 4.2s" in lines[5]


def test_command_headers_number_repeats_and_keep_exact_invocation_below() -> None:
    console, stream = _console()
    console.event("CommonMark: initial-build")
    for count in (1, 2):
        argv = ("/usr/bin/python3", "-m", "drydock", "build", "commonmark", "--override")
        console.step(argv, f"{count + 9:02}-initial-build-{count}")
        console.finish(0, 10)
    console.event("AnotherKit: initial-build")
    console.step(argv, "10-initial-build-1")

    output = stream.getvalue()
    assert "DRYDOCK BUILD COMMONMARK [2]" in output
    assert "DRYDOCK BUILD COMMONMARK [1]" not in output
    assert output.count("   drydock build commonmark --override\n") == 3
    assert "initial-build-" not in output and "step 10" not in output
    assert "[3]" not in output  # Counts reset at the next kit.


def test_batch_next_lines_are_suppressed_even_when_fragmented() -> None:
    console, stream = _console()
    for label in ("10-initial-build-1", "11-after-initial-build-build-status"):
        console.step(("drydock", "build", "commonmark"), label)
        for char in "Next: drydock build commonmark\n":
            console.chunk("stdout", char)
        console.finish(0, 10)
    assert "Next:" not in stream.getvalue()


def test_hidden_status_failure_names_its_own_command() -> None:
    console, stream = _console()
    console.step(("drydock", "build", "commonmark"), "10-initial-build-1")
    console.finish(0, 10)
    console.step(("drydock", "status", "commonmark"), "12-after-initial-build-target-status")
    console.finish(1, 10)
    assert "STEP ERROR: DRYDOCK STATUS COMMONMARK" in stream.getvalue()


@pytest.mark.parametrize("no_color", [False, True])
def test_terminal_headers_successes_and_failures_use_semantic_colors(monkeypatch, no_color):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    if no_color:
        monkeypatch.setenv("NO_COLOR", "1")
    stream = Terminal()
    console = StepConsole(stream, width=60)
    console.step(("drydock", "build", "commonmark"), "10-initial-build-1")
    console.finish(0, 10)
    console.step(("drydock", "build", "commonmark"), "14-initial-build-2")
    console.finish(1, 10)
    output = stream.getvalue()
    if no_color:
        assert "\x1b[" not in output
    else:
        assert "\x1b[34m── DRYDOCK BUILD COMMONMARK" in output
        assert "\x1b[32m── DRYDOCK BUILD COMMONMARK" in output
        assert "\x1b[31m" + "#" * 60 in output


def test_partial_and_redrawn_lines_reach_the_terminal_unchanged() -> None:
    console, stream = _console()

    console.chunk("stdout", "pass 1")
    console.chunk("stdout", "\rpass 2")

    # No trailing newline is invented, and the redraw keeps its carriage return.
    assert stream.getvalue() == " │ pass 1\r │ pass 2"


def test_crlf_output_is_not_given_a_second_gutter() -> None:
    console, stream = _console()

    console.chunk("stdout", "line\r\nnext\r\n")

    assert stream.getvalue() == " │ line\r\n │ next\r\n"


def test_an_open_line_is_closed_before_the_other_stream_writes() -> None:
    console, stream = _console()

    console.chunk("stdout", "working")
    console.chunk("stderr", "boom\n")

    assert stream.getvalue() == " │ working\n ! boom\n"


def test_quiet_reports_stage_names_only() -> None:
    console, stream = _console(quiet=True)

    console.event("Toml: analyze")
    console.step(("/usr/bin/python3", "-m", "drydock", "analyze", "Toml"), "09-analyze")
    console.chunk("stdout", "Analyzing Blueprint\n")
    console.finish(0, 100)

    assert stream.getvalue() == "UAT: Toml: analyze\n"


def test_fragmented_noise_is_hidden_and_diagnostic_text_survives() -> None:
    console, stream = _console()
    console.step(("drydock", "build", "Toml"), "10-build")
    for char in "Drydock 0.8 Copyright (c) 2026\nTarget - committed project workspace git store\n":
        console.chunk("stdout", char)
    console.chunk("stdout", "progress")
    assert stream.getvalue().endswith(" │ progress")
    console.chunk("stdout", "\rcompleted\n")
    console.chunk("stderr", "error: schema mismatch")
    console.finish(1, 100)
    text = stream.getvalue()
    assert "Copyright" not in text and "git store" not in text
    assert "STEP ERROR:" in text and "error: schema mismatch" in text
    assert text.rstrip().endswith("#" * 60)


def test_plan_box_becomes_one_line_without_hiding_warnings() -> None:
    console, stream = _console()
    console.step(("drydock", "plan", "Toml"), "04-plan")
    text = (
        "========================================================================\n"
        "PLAN PROGRESS  ·  STAGE 2 · BLUEPRINT BATCH 1\n"
        "========================================================================\n"
        "Topology Created: True\nBlueprints Created: 5 / 20\n"
        "Manifest Created: False\nBlueprints Remaining: 15\n"
        "Batch Result: Accepted 5 Blueprint(s)\n"
        "========================================================================\n"
        "[plan] artifact rejected: invalid contract\n"
    )
    for char in text:
        console.chunk("stdout", char)
    console.finish(0, 100)
    output = stream.getvalue()
    assert (
        "Plan: STAGE 2 · BLUEPRINT BATCH 1 | Blueprints 5 / 20 | Accepted 5 Blueprint(s)" in output
    )
    assert "Topology Created" not in output and "===" not in output
    assert "[plan] artifact rejected: invalid contract" in output


def test_status_views_keep_summary_and_box_blocker_without_raw_file_dump() -> None:
    console, stream = _console()
    console.step(("drydock", "build", "status", "Toml"), "06-after-plan-build-status")
    console.chunk(
        "stdout", "Block: long tree\n  [pending] story A\nSteps: 20 total\nBuildable now: block-1\n"
    )
    console.finish(0, 100)
    for label in ("07-after-plan-target-status", "08-after-plan-workspace-status"):
        console.step(("drydock", "status", "Toml"), label)
        console.chunk("stdout", "Target: long path\nWorkflow: long history\n")
        console.finish(0, 100)
    console.step(("drydock", "build", "status", "Toml"), "11-after-initial-build-build-status")
    console.chunk(
        "stderr",
        "BLOCKED: Toml\n  blocker-001: build failed\nContents of /tmp/BLOCKERS.md:\nraw duplicated blocker\n",
    )
    console.finish(1, 100)
    output = stream.getvalue()
    assert "Steps: 20 total" in output and "Buildable now: block-1" in output
    assert "long tree" not in output and "long history" not in output
    assert "target-status" not in output and "workspace-status" not in output
    assert "STEP ERROR:" in output and "BLOCKED: Toml" in output
    assert "raw duplicated blocker" not in output


def test_ready_failure_is_not_presented_as_a_command_error() -> None:
    console, stream = _console()
    console.step(("drydock", "status", "Toml", "--ready"), "09-initial-ready")
    console.finish(1, 100)
    assert "NOT READY:" in stream.getvalue()
    assert "STEP ERROR:" not in stream.getvalue()


def test_result_box_wraps_ascii_and_long_diagnostics() -> None:
    from drydock.uat_console import result_box

    output = result_box("UAT FAILED: Toml", ["error " * 80], width=60)
    assert all(len(line) == 60 for line in output.splitlines())
    assert output.isascii()


def test_final_result_names_actual_failure_instead_of_status_snapshot(
    tmp_path, monkeypatch
) -> None:
    from drydock.uat import CommandResult, UATResult
    from drydock.uat_console import render_result

    error = tmp_path / "build.stderr.log"
    error.write_text("error: conflicting row class Rate\n", encoding="utf-8")
    result = UATResult(
        fixture="Toml",
        target="Toml",
        run_id="fake",
        status="failed",
        elapsed_ms=100,
        build_passes=1,
        output_dir=str(tmp_path),
        score_exit_codes={},
        usage={},
        error="build exited 1",
        commands=(
            CommandResult(
                ("drydock", "build", "Toml"), 1, 100, "", str(error), "10-initial-build-1"
            ),
            CommandResult(
                ("drydock", "build", "status", "Toml"), 1, 10, "", "", "11-after-build-build-status"
            ),
        ),
    )
    output = render_result(result)
    assert "UAT FAILED: Toml" in output
    assert "step 10: initial-build-1" in output
    assert "conflicting row class Rate" in output
    assert "step 11" not in output
    destination = io.StringIO()
    monkeypatch.setattr("drydock.console.color_enabled", lambda stream: stream is destination)
    assert render_result(result, stream=destination).startswith("\x1b[31m")


def test_console_compaction_preserves_verbatim_evidence(tmp_path) -> None:
    import os
    import sys

    from drydock.uat import subprocess_runner

    console, stream = _console()
    program = (
        "import sys\n"
        "print('Drydock 0.8 Copyright (c) 2026')\n"
        "print('Target - committed project workspace git store')\n"
        "sys.stderr.write('error: actual failure\\n')\n"
        "raise SystemExit(1)\n"
    )
    result = subprocess_runner(
        (sys.executable, "-c", program),
        tmp_path,
        dict(os.environ),
        tmp_path,
        "10-build",
        sink=console,
    )
    from pathlib import Path

    assert "Copyright" in Path(result.stdout_path).read_text()
    assert "git store" in Path(result.stdout_path).read_text()
    assert Path(result.stderr_path).read_text() == "error: actual failure\n"
    assert " │ Drydock" not in stream.getvalue()
    assert " │ Target - " not in stream.getvalue()
    assert "STEP ERROR:" in stream.getvalue()


def test_passing_expected_failure_keeps_recorded_verdict_and_manual_checks(
    tmp_path, monkeypatch
) -> None:
    from drydock.uat import UATResult
    from drydock.uat_console import render_result

    result = UATResult(
        fixture="Toml",
        target="Toml",
        run_id="fake",
        status="passed",
        elapsed_ms=100,
        build_passes=1,
        output_dir=str(tmp_path),
        commands=(),
        score_exit_codes={},
        usage={},
        expected_verdict="FAILED",
        observed_verdict="FAILED",
        acceptance_status="FAIL",
        error="expected conformance failure",
        attestations=("Confirm the guardrail",),
    )
    output = render_result(result)
    assert "UAT PASSED: Toml" in output
    assert "expected FAILED, observed FAILED" in output
    assert "Reported: expected conformance failure" in output
    assert "MANUAL TEST REQUIRED: Confirm the guardrail" in output
    assert "Last failed command" not in output
    destination = io.StringIO()
    monkeypatch.setattr("drydock.console.color_enabled", lambda stream: stream is destination)
    assert render_result(result, stream=destination).startswith("\x1b[32m")
