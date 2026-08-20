"""Tests for the Drydock CLI entry point."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from drydock import __copyright__, __version__
from drydock.acceptance import AcceptanceObservation, AcceptanceRunResult
from drydock.build_run import BuildStepResult
from drydock.cli import (
    _build_running_command,
    _render_build_failures,
    _stream_build,
    _stream_build_summary,
    _stream_status_only,
    _stream_stdout,
    main,
)


def test_build_running_command_includes_explicit_flags():
    from types import SimpleNamespace

    args = SimpleNamespace(
        Target="Marina",
        build_dir=None,
        step=None,
        story=None,
        continue_=False,
        reset=False,
        ungate=True,
        normalize_order=False,
        dry_run=False,
        show_prompt=False,
        # Unset, not "happens to equal the default": the budget is configurable, so the echoed
        # command must not freeze this run's value into a flag the operator never typed.
        repair_attempts=None,
        escalate_model=None,
        model=None,
        llm_provider=None,
        effort=None,
    )

    assert _build_running_command(args) == "drydock build Marina --ungate"


def test_build_running_command_echoes_an_explicit_repair_budget():
    from types import SimpleNamespace

    args = SimpleNamespace(
        Target="Marina",
        build_dir=None,
        step=None,
        story=None,
        continue_=False,
        reset=False,
        ungate=False,
        normalize_order=False,
        dry_run=False,
        show_prompt=False,
        repair_attempts=12,
        escalate_model=None,
        model=None,
        llm_provider=None,
        effort=None,
    )

    assert _build_running_command(args) == "drydock build Marina --repair-attempts 12"


def run_cli(*args: str) -> tuple[int, str, str]:
    """Run main() in-process, capturing stdout/stderr and exit code."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            main(list(args))
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
        else:
            rc = 0
    return rc, out.getvalue(), err.getvalue()


def test_failure_renderer_shows_agent_summary_story_acceptance_and_progress():
    baseline = AcceptanceObservation(
        check_id="inline-suite",
        source="FEATURE-Inlines.md",
        intent="Inline conformance passes.",
        passed=False,
        return_code=1,
        stdout="200 passed, 135 failed\n",
        stderr="",
    )
    final = AcceptanceRunResult(
        check_id="inline-suite",
        source="FEATURE-Inlines.md",
        intent="Inline conformance passes.",
        passed=False,
        return_code=1,
        stdout="271 passed, 64 failed\n",
        stderr="assert result.returncode == 0\nAssertionError\n",
    )
    step = BuildStepResult(
        block_id="inlines",
        name="Inline Parsing",
        block_type="story",
        status="failed",
        state="closed/failed",
        story_points=1,
        error="programmatic acceptance failed: inline-suite",
        failure_detail="Inline suite remains red.",
        owned_pre_acceptance=(baseline,),
        owned_acceptance=(final,),
        agent_summary="Fixed parsing and rendering behavior.",
        agent_blockers="Nested emphasis remains nonconformant.",
    )

    rendered = _render_build_failures("commonmark", [step], hint="continue", story_recovery=())

    assert "Provenance" in rendered
    assert "Block: Inline Parsing [inlines]" in rendered
    assert "Story: Inline Parsing [inlines]" in rendered
    assert "Fixed parsing and rendering behavior." in rendered
    assert "inline-suite: 271 passed, 64 failed · change +71 passed, -71 failed" in rendered
    assert "Acceptance checks:" in rendered
    assert "Assertion" in rendered
    assert "Code: assert result.returncode == 0" in rendered
    assert "Process exit code: 1" in rendered
    assert "Error: AssertionError" in rendered
    assert "Recovery" in rendered
    # The plain rebuild continues the build; it is named without the --ungate bypass.
    assert "Run: drydock build commonmark\n" in rendered
    assert "to continue the build" in rendered
    assert "--ungate" not in rendered
    assert "--step inlines" not in rendered
    assert "Nested emphasis remains nonconformant." in rendered


class TestHelpAndVersion:
    def test_stream_stdout_newline_terminates_status_messages(self, capsys):
        _stream_stdout._at_line_start = True  # type: ignore[attr-defined]
        _stream_stdout("AUTO-COMPACT: fresh")
        _stream_stdout("BUILD QUEUE: 1 ready block")

        assert capsys.readouterr().out == "AUTO-COMPACT: fresh\nBUILD QUEUE: 1 ready block\n"

    def test_stream_stdout_preserves_model_text_delta(self, capsys):
        _stream_stdout._at_line_start = True  # type: ignore[attr-defined]
        _stream_stdout("partial")
        _stream_stdout(" word")

        assert capsys.readouterr().out == "partial word"

    def test_stream_stdout_separates_status_after_model_delta(self, capsys):
        _stream_stdout._at_line_start = True  # type: ignore[attr-defined]
        _stream_stdout("partial")
        _stream_stdout("BUILD QUEUE: 1 ready block")

        assert capsys.readouterr().out == "partial\nBUILD QUEUE: 1 ready block\n"

    def test_stream_build_terminates_every_line(self, capsys):
        _stream_build._at_line_start = True  # type: ignore[attr-defined]
        _stream_build("RESUME: seeding first pass with 1 failing check(s)")
        _stream_build("REPAIR ATTEMPT 1/1: 1 failing check(s)")

        assert capsys.readouterr().out == (
            "RESUME: seeding first pass with 1 failing check(s)\n"
            "REPAIR ATTEMPT 1/1: 1 failing check(s)\n"
        )

    def test_stream_build_emits_blank_separator_and_whole_lines(self, capsys):
        _stream_build("")
        _stream_build(
            "acceptance: call 2 · 2/3 AC passed · failed: block-conformance (240/260 cases)"
        )
        _stream_build("repair: attempt 1/1 · 1 failing check(s)")

        assert capsys.readouterr().out == (
            "\nacceptance: call 2 · 2/3 AC passed · "
            "failed: block-conformance (240/260 cases)\n"
            "repair: attempt 1/1 · 1 failing check(s)\n"
        )

    def test_stream_build_summary_shows_llm_scope_and_acceptance_only(self, capsys):
        _stream_build_summary("returned: ok · exec-1")
        _stream_build_summary("LLM BUILD: Markdown Parsing [feature-parsing]")
        _stream_build_summary(
            "  stories: Block Parsing [block-parsing], Inline Parsing [inline-parsing]"
        )
        _stream_build_summary("  call: 2 of up to 4 · automatic repair 1 of 3 · codex/gpt")
        # Token accounting is written to the execution's .llm.log, never to build progress.
        _stream_build_summary("  tokens: in=1,000 · fresh 100 · cached 900 (90% hit) · out=50")
        _stream_build_summary("  failing: block-conformance (240/260 cases)")
        _stream_build_summary(
            "acceptance: call 2 · 2/3 AC passed · failed: block-conformance (240/260 cases)"
        )
        _stream_build_summary("files: 1 changed — parser.py")

        assert (
            capsys.readouterr().out == "\nLLM BUILD: Markdown Parsing [feature-parsing]\n"
            "  stories: Block Parsing [block-parsing], Inline Parsing [inline-parsing]\n"
            "  call: 2 of up to 4 · automatic repair 1 of 3 · codex/gpt\n"
            "  failing: block-conformance (240/260 cases)\n"
            "acceptance: call 2 · 2/3 AC passed · "
            "failed: block-conformance (240/260 cases)\n"
        )

    def test_stream_build_summary_shows_why_the_repair_loop_stopped(self, capsys):
        # A loop that ends below its budget must account for the shortfall without --debug.
        # The per-attempt counter stays hidden; the ``call:`` line already carries it.
        _stream_build_summary("repair: attempt 1/3 · 1 failing check(s)")
        _stream_build_summary("repair: stopped — deterministic acceptance score did not improve")
        _stream_build_summary("repair: escalation — final attempt using opus")

        assert capsys.readouterr().out == (
            "repair: stopped — deterministic acceptance score did not improve\n"
            "repair: escalation — final attempt using opus\n"
        )

    def test_stream_status_only_drops_model_json_payload(self, capsys):
        """Scoring output omits parsed JSON and provider command evidence."""
        _stream_stdout._at_line_start = True  # type: ignore[attr-defined]
        _stream_status_only('{"dimensions": {"build_quality": 0}}')
        _stream_status_only("  $ /bin/bash -lc 'pytest -q'")
        _stream_status_only("  -> exit 0")
        _stream_status_only("  [running] 30s elapsed, no provider output for 30s")
        _stream_status_only("AUTO-COMPACT: fresh")

        assert capsys.readouterr().out == (
            "  [running] 30s elapsed, no provider output for 30s\nAUTO-COMPACT: fresh\n"
        )

    def test_help_shows_copyright(self):
        rc, out, err = run_cli("--help")
        assert rc == 0
        assert __copyright__ in out
        assert "Blueprint-driven" in out

    def test_help_documents_global_debug_contract_without_verbose(self):
        rc, out, err = run_cli("--help")

        assert rc == 0, err
        assert (
            "Show detailed command output, DEBUG log messages, LLM execution "
            "diagnostics, and full tracebacks."
        ) in " ".join(out.split())
        assert "--verbose" not in out

    def test_help_shows_all_top_commands(self):
        rc, out, _ = run_cli("--help")
        for cmd in (
            "status",
            "config",
            "init",
            "uat",
            "validate",
            "document",
            "publish",
            "rigging",
            "plan",
            "build",
            "refit",
            "analyze",
            "import",
            "run",
        ):
            assert cmd in out, f"Command {cmd!r} missing from --help"
        assert "prompt" not in out
        assert "survey" not in out

    def test_help_lists_score_command(self):
        _, out, _ = run_cli("--help")
        assert "score" in out

    def test_uat_help_describes_isolation_and_explicit_source_bundles(self):
        rc, out, err = run_cli("uat", "--help")

        assert rc == 0, err
        assert "explicit source bundle" in out
        assert "test_command" in out
        assert "isolated" in out
        assert "--max-build-passes" in out
        assert "--report" in out
        assert "--quiet" in out
        assert "streams to the console" in out
        assert "--stage" in out
        assert "Resume" in out or "resume" in out

    def test_uat_run_requires_a_resume_stage(self):
        rc, _, err = run_cli("uat", "ReadingList", "--run", "20260809T000000.000000Z")
        assert rc == 2
        assert "--run requires --stage or --from-step" in err

    def test_uat_help_offers_resuming_at_a_recorded_step(self):
        rc, out, err = run_cli("uat", "--help")

        assert rc == 0, err
        assert "--from-step" in out
        assert "--steps" in out

    def test_uat_rejects_a_step_resume_without_a_kit(self):
        rc, _, err = run_cli("uat", "--from-step", "16")
        assert rc == 2
        assert "--from-step requires <Project>" in err

    def test_uat_rejects_a_step_listing_without_a_kit(self):
        rc, _, err = run_cli("uat", "--steps")
        assert rc == 2
        assert "--steps requires <Project>" in err

    def test_uat_refuses_both_a_stage_and_a_step(self):
        rc, _, err = run_cli("uat", "ReadingList", "--stage", "score", "--from-step", "16")
        assert rc == 2
        assert "--from-step" in err

    def test_uat_rejects_an_unknown_resume_stage(self):
        rc, _, err = run_cli("uat", "ReadingList", "--stage", "compile")
        assert rc == 2
        assert "--stage" in err

    def test_uat_report_without_any_kit_is_a_usage_error(self):
        rc, _, err = run_cli("uat", "--report", "--uat-root", "/nonexistent/uat")
        assert rc == 2
        assert "No UAT kits found" in err

    def test_uat_report_initializes_and_commits_selected_kit(self, tmp_path, monkeypatch):
        import drydock.cli as cli_module

        monkeypatch.setenv("GIT_AUTHOR_NAME", "Drydock Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "drydock@example.test")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Drydock Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "drydock@example.test")
        kit = tmp_path / "uat" / "ReadingList"
        kit.mkdir(parents=True)
        (kit / "uat.json").write_text("{}\n", encoding="utf-8")

        def fake_report(kits):
            (kits[0] / "index.html").write_text("report\n", encoding="utf-8")
            return 0

        monkeypatch.setattr(cli_module, "_uat_report", fake_report)

        rc, _, err = run_cli("uat", "--report", "ReadingList", "--uat-root", str(tmp_path / "uat"))

        assert rc == 0, err
        assert (kit / ".git").is_dir()
        assert (
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=kit,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            == ""
        )
        assert (
            subprocess.run(
                ["git", "show", "HEAD:index.html"],
                cwd=kit,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            == "report\n"
        )

    def test_uat_usage_exit_still_commits_selected_kit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Drydock Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "drydock@example.test")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Drydock Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "drydock@example.test")
        kit = tmp_path / "uat" / "ReadingList"
        kit.mkdir(parents=True)
        (kit / "uat.json").write_text("{}\n", encoding="utf-8")

        rc, _, err = run_cli(
            "uat",
            "ReadingList",
            "--run",
            "run-1",
            "--uat-root",
            str(tmp_path / "uat"),
        )

        assert rc == 2
        assert "--run requires --stage" in err
        assert (
            subprocess.run(
                ["git", "show", "HEAD:uat.json"],
                cwd=kit,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            == "{}\n"
        )

    def test_score_help_shows_ac_and_release(self):
        rc, out, _ = run_cli("score", "--help")
        assert rc == 0
        assert "score ac" in out
        assert "score release" in out

    def test_score_bad_subverb_is_usage_error(self):
        rc, _, err = run_cli("score", "bogus", "Demo")
        assert rc == 2
        assert "ac|build|release" in err

    def test_score_help_shows_report(self):
        rc, out, _ = run_cli("score", "--help")
        assert rc == 0
        assert "score report" in out
        assert "drydock_receipt/index.html" in out

    def test_score_report_without_a_target_is_a_usage_error(self):
        rc, _, err = run_cli("score", "report")
        assert rc == 2
        assert "report" in err

    def test_score_report_for_an_uninitialized_target_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        rc, _, err = run_cli("score", "report", "NoSuchTarget")
        assert rc == 1
        assert "NoSuchTarget" in err

    def test_score_release_prints_the_listing_and_names_each_manual_check(
        self, tmp_path, monkeypatch, capsys
    ):
        """The listing is the whole answer, and a MANUAL criterion exits 0.

        Nothing was observed to be absent or wrong; one criterion no machine can settle is named
        as a check a human owes, in a line that reads differently from a failure.
        """
        from drydock.cli import cmd_score_release
        from drydock.gate_policy import PASSED
        from drydock.score import ReleaseResult

        manual = (
            "st-003 needs manual verification: The application shall never store a book whose "
            "title or author is empty."
        )
        result = ReleaseResult(
            target="Demo",
            verdict=PASSED,
            statement="Demo: PASSED — 2 of 3\n\n  st-001  MET     observed\n",
            criteria=(),
            blockers=(),
            attestations=(manual,),
            warnings=(),
            improvements=(),
            scorecard_path=tmp_path / "SCORECARD.md",
            evidence_path=tmp_path / "score-release.json",
            execution_id="exec-1",
        )
        monkeypatch.setattr("drydock.config.require_target_dir", lambda target: tmp_path)
        monkeypatch.setattr("drydock.score.score_release", lambda *a, **k: result)
        monkeypatch.setattr(
            "drydock.quarterdeck_state.refresh_commanders_chair", lambda target_dir: None
        )

        rc = cmd_score_release("Demo")
        out = capsys.readouterr().out

        assert rc == 0
        assert "Demo: PASSED — 2 of 3" in out
        assert "st-001  MET     observed" in out
        assert f"  MANUAL VERIFICATION: {manual}" in out

    def test_parse_score_ac_args_accepts_step_flag(self):
        from drydock.cli import _parse_score_ac_args

        assert _parse_score_ac_args(["Demo"]) == ("Demo", None)
        assert _parse_score_ac_args(["Demo", "--step", "block-parsing"]) == (
            "Demo",
            "block-parsing",
        )
        assert _parse_score_ac_args(["--step", "block-parsing", "Demo"]) == (
            "Demo",
            "block-parsing",
        )
        assert _parse_score_ac_args(["Demo", "--step=block-parsing"]) == (
            "Demo",
            "block-parsing",
        )

    def test_parse_score_ac_args_requires_one_target(self):
        from drydock.cli import UsageError, _parse_score_ac_args

        for bad in ([], ["a", "b"], ["Demo", "--step"]):
            try:
                _parse_score_ac_args(bad)
            except UsageError:
                pass
            else:
                raise AssertionError(f"expected UsageError for {bad!r}")

    def test_version_shows_version_and_copyright(self):
        rc, out, err = run_cli("--version")
        # argparse prints version to stdout
        combined = out + err
        assert __version__ in combined
        assert __copyright__ in combined

    def test_no_args_shows_help(self):
        rc, out, _ = run_cli()
        assert rc == 0
        assert "drydock" in out.lower()

    def test_invalid_top_level_command_shows_help(self):
        rc, out, err = run_cli("configure")

        assert rc == 2
        assert out == ""
        assert "usage: drydock" in err
        assert "config" in err
        assert "init" in err
        assert "error: argument <command>: invalid choice: 'configure'" in err

    def test_command_prints_copyright_to_stdout(self, isolated_config):
        out, err = run_cli("config", "show")[1:]
        assert __copyright__ in out
        assert __version__ in out

    def test_status_writes_plain_transcript_without_debug_log(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        monkeypatch.setenv("DRYDOCK_TEST_COMMAND_LOGGING", "1")

        rc, out, err = run_cli("status")

        assert rc == 0, err
        # Transcripts are named <stamp>_[<target>_]<command>[_<llm>].log; status names no
        # provider because it calls no model.
        transcripts = list((tmp_workspace / "logs").glob("*_status.log"))
        debug_logs = list((tmp_workspace / "logs").glob("*_status.debug.log"))
        assert len(transcripts) == 1
        assert debug_logs == []
        assert transcripts[0].read_text(encoding="utf-8") == out
        assert "INFO" not in transcripts[0].read_text(encoding="utf-8")
        assert "command: status" not in err

    def test_effort_is_an_invocation_wide_override(self):
        """``--effort`` is stripped from argv wherever it appears and published as the
        configured level, so every LLM-assisted command resolves the same depth."""
        from drydock.cli import _extract_global_overrides

        cleaned, overrides = _extract_global_overrides(["analyze", "MyTarget", "--effort", "xhigh"])
        assert cleaned == ["analyze", "MyTarget"]
        assert overrides["effort"] == "xhigh"

        cleaned, overrides = _extract_global_overrides(["build", "--effort=MAX", "MyTarget"])
        assert cleaned == ["build", "MyTarget"]
        assert overrides["effort"] == "max"

    def test_unknown_effort_level_names_the_valid_choices(self):
        from drydock.cli import UsageError, _extract_global_overrides

        with pytest.raises(UsageError) as excinfo:
            _extract_global_overrides(["analyze", "MyTarget", "--effort", "ludicrous"])
        message = str(excinfo.value)
        assert "ludicrous" in message
        for level in ("low", "medium", "high", "xhigh", "max"):
            assert level in message

        with pytest.raises(UsageError, match="expected one argument"):
            _extract_global_overrides(["analyze", "MyTarget", "--effort"])

    def test_effort_flag_becomes_the_configured_effort(self, isolated_config, monkeypatch):
        """The flag reaches every capability through the configured value rather than
        through each command signature."""
        # setenv registers the key with monkeypatch so teardown removes what the CLI writes.
        monkeypatch.setenv("DRYDOCK_EFFORT", "")
        from drydock.config import get_effort

        run_cli("config", "show", "--effort", "high")
        assert get_effort() == "high"

    def test_debug_after_command_prints_diagnostics_without_debug_log(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        monkeypatch.setenv("DRYDOCK_TEST_COMMAND_LOGGING", "1")

        rc, _, err = run_cli("status", "--debug")

        assert rc == 0, err
        assert "INFO     drydock.cli  command: status --debug" in err
        assert list((tmp_workspace / "logs").glob("*.debug.log")) == []

    def test_nested_command_appends_to_parent_transcript_and_skips_history(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        """Commands run by build tooling are implementation detail, not user commands."""
        from drydock.logging import setup_command_logging

        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        monkeypatch.setenv("DRYDOCK_TEST_COMMAND_LOGGING", "1")
        outer = setup_command_logging(tmp_workspace / "logs", "build", stdout=sys.stdout)
        monkeypatch.setenv("DRYDOCK_PARENT_TRANSCRIPT", str(outer.transcript_path))
        try:
            rc, out, err = run_cli("config", "set", "drydock_workspace", str(tmp_workspace))
        finally:
            outer.close()

        assert rc == 0, err
        assert list((tmp_workspace / "logs").glob("*.log")) == [outer.transcript_path]
        assert outer.transcript_path.read_text(encoding="utf-8") == out
        assert not (tmp_workspace / "logs" / "history.jsonl").exists()

    def test_top_level_command_retains_its_history_record(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        monkeypatch.setenv("DRYDOCK_TEST_COMMAND_LOGGING", "1")

        rc, _, err = run_cli("config", "set", "drydock_workspace", str(tmp_workspace))

        assert rc == 0, err
        history = (tmp_workspace / "logs" / "history.jsonl").read_text(encoding="utf-8")
        assert '"command": "drydock config set drydock_workspace' in history

    def test_history_record_can_be_joined_to_the_transcript_it_names(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        """``time`` is minute-resolution, so the record carries the transcript's own stamp.

        Without it a reader cannot tell which of a minute's transcripts belongs to a command,
        which is exactly the join ``drydock score report`` needs.
        """
        import json

        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        monkeypatch.setenv("DRYDOCK_TEST_COMMAND_LOGGING", "1")

        rc, _, err = run_cli("config", "set", "drydock_workspace", str(tmp_workspace))

        assert rc == 0, err
        lines = (tmp_workspace / "logs" / "history.jsonl").read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[-1])
        transcript = tmp_workspace / record["transcript"]
        assert transcript.is_file()
        assert transcript.name.startswith(record["stamp"])
        assert record["argv"] == ["config", "set", "drydock_workspace", str(tmp_workspace)]
        assert isinstance(record["elapsed_ms"], int)

    def test_pytest_fixture_command_does_not_write_workspace_logs(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))

        rc, _, err = run_cli("config", "set", "drydock_workspace", str(tmp_workspace))

        assert rc == 0, err
        assert not (tmp_workspace / "logs").exists()


class TestPromptReview:
    def test_help_lists_review_subcommand(self):
        rc, out, _ = run_cli("prompt", "--help")
        assert rc == 0
        assert "review" in out

    def test_prompt_review_runs(self, tmp_path, isolated_config, monkeypatch):
        import drydock.config

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        result = type(
            "ReviewResult",
            (),
            {
                "review_path": repo_root / "docs" / "prompt_reviews" / "analyze.md",
                "archive_path": None,
                "overall_score": 8.4,
                "rating_band": "Workable",
                "review_model": "opus",
            },
        )()
        result.review_path.parent.mkdir(parents=True)
        result.review_path.write_text("review\n", encoding="utf-8")
        monkeypatch.setattr(drydock.config, "get_workspace", lambda: tmp_path)
        monkeypatch.setattr("drydock.paths.get_repo_root", lambda: repo_root)
        monkeypatch.setattr(
            "drydock.prompt_review.review_prompt", lambda component, **kwargs: result
        )

        rc, out, err = run_cli("prompt", "review", "analyze")

        assert rc == 0
        assert "Score: 8.4/10" in out
        assert "prompt_reviews/analyze.md" in out


class TestConfigShow:
    def test_config_show_runs(self, isolated_config):
        rc, out, err = run_cli("config", "show")
        assert rc == 0
        assert "drydock_build_directory" in out
        assert "drydock_workspace" in out

    def test_config_show_defaults_when_unset(self, isolated_config):
        rc, out, _ = run_cli("config", "show")
        assert rc == 0
        assert "drydock_workspace" in out
        assert "(default)" in out


class TestConfigSet:
    def test_config_set_valid(self, tmp_workspace, isolated_config):
        rc, out, err = run_cli("config", "set", "drydock_workspace", str(tmp_workspace))
        assert rc == 0
        assert "drydock_workspace" in out

    def test_config_set_drydock_build_directory(self, tmp_path, isolated_config):
        build_root = tmp_path / "builds"
        build_root.mkdir()
        rc, out, err = run_cli("config", "set", "drydock_build_directory", str(build_root))
        assert rc == 0
        assert "drydock_build_directory" in out

    def test_config_set_persists(self, tmp_workspace, isolated_config):
        run_cli("config", "set", "drydock_workspace", str(tmp_workspace))
        rc, out, _ = run_cli("config", "show")
        assert str(tmp_workspace) in out

    def test_config_set_nonexistent_dir_fails(self, isolated_config):
        rc, out, err = run_cli("config", "set", "drydock_workspace", "/does/not/exist")
        assert rc == 1
        assert "error" in err.lower()

    def test_config_set_llm_provider(self, isolated_config):
        rc, out, err = run_cli("config", "set", "llm_provider", "codex")
        assert rc == 0
        assert "codex" in out

    def test_config_set_prompt_warn_tokens(self, isolated_config):
        rc, out, err = run_cli("config", "set", "prompt_warn_tokens", "75000")
        assert rc == 0
        assert "75000" in out

    def test_config_set_invalid_prompt_warn_tokens_fails(self, isolated_config):
        rc, out, err = run_cli("config", "set", "prompt_warn_tokens", "fifty")
        assert rc == 1
        assert "error" in err.lower()


class TestInit:
    def test_init_creates_target_baseline(self, tmp_target_root, isolated_config):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        rc, out, err = run_cli("init", "TestProject")
        assert rc == 0
        target = tmp_target_root / "TestProject"
        assert "Target:" in out
        for path in (
            "METADATA.md",
            "blueprint/sources/.gitkeep",
            "evidence/.gitkeep",
            "logs/.gitkeep",
            "QuarterDeck/console.yaml",
        ):
            assert (target / path).is_file(), f"{path} missing"
        assert not (target / "QuarterDeck" / "tickets.json").exists()
        # SEA_TRIALS.md and SOUNDINGS.md are generated by analyze, not init.
        assert not (target / "SEA_TRIALS.md").is_file()
        assert not (target / "SOUNDINGS.md").is_file()
        # The console runtime is served from the package, not copied into the target.
        assert not (target / "QuarterDeck" / "app.py").exists()
        assert not (target / "QuarterDeck" / "requirements.txt").exists()
        assert not (target / "target.yaml").exists()
        assert not (target / "docs").exists()

    def test_init_is_idempotent_and_preserves_existing_files(
        self, tmp_target_root, isolated_config
    ):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        run_cli("init", "TestProject")
        metadata = tmp_target_root / "TestProject" / "METADATA.md"
        original = metadata.read_text(encoding="utf-8")

        rc, out, err = run_cli("init", "TestProject")

        assert rc == 0
        assert metadata.read_text(encoding="utf-8") == original
        assert "existing baseline files preserved" in out

    def test_init_rejects_blueprint_options(self, tmp_target_root, isolated_config):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        rc, out, err = run_cli("init", "TestProject", "--force")
        assert rc == 2

    def test_init_rejects_path_traversal(self, tmp_target_root, isolated_config):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        rc, out, err = run_cli("init", "../evil")
        assert rc == 1

    def test_init_rejects_empty_name(self, tmp_target_root, isolated_config):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        rc, out, err = run_cli("init", "")
        assert rc != 0


class TestValidate:
    def _setup_spec(self, tmp_target_root, isolated_config):
        from drydock.init_specification import init_specification

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        target_dir = tmp_target_root / "TestProject"
        init_specification("TestProject", target_dir)
        return target_dir

    def test_validate_after_init_exits_zero(self, tmp_target_root, isolated_config):
        self._setup_spec(tmp_target_root, isolated_config)
        rc, out, err = run_cli("validate", "TestProject")
        assert rc == 0  # warnings are OK, no failures expected after init

    def test_validate_nonexistent_spec_fails(self, tmp_target_root, isolated_config):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        rc, out, err = run_cli("validate", "DoesNotExist")
        assert rc == 1

    def test_validate_verbose_shows_passes(self, tmp_target_root, isolated_config):
        self._setup_spec(tmp_target_root, isolated_config)
        rc_plain, out_plain, _ = run_cli("validate", "TestProject")
        rc_verb, out_verb, _ = run_cli("validate", "TestProject", "--verbose")
        assert rc_verb == 0
        assert "PASS" in out_verb
        assert len(out_verb) > len(out_plain)

    def test_validate_missing_required_file_fails(self, tmp_target_root, isolated_config):
        target_dir = self._setup_spec(tmp_target_root, isolated_config)
        # Put target in Implement phase so ARCHITECTURE.md is required
        (target_dir / "MANIFEST.md").write_text("# MANIFEST: Example\n", encoding="utf-8")
        (target_dir / "blueprint" / "ARCHITECTURE.md").unlink()
        rc, out, err = run_cli("validate", "TestProject")
        assert rc == 1
        assert "ARCHITECTURE" in out

    def test_validate_shows_result_summary(self, tmp_target_root, isolated_config):
        self._setup_spec(tmp_target_root, isolated_config)
        rc, out, _ = run_cli("validate", "TestProject")
        assert "✓" in out or "✗" in out or "⚠" in out


class TestRiggingCompact:
    """`rigging compact` discovers stale files and writes _compact.md siblings."""

    @staticmethod
    def _fake_run_prompt(monkeypatch, *, ok=True, text="# X — Compact\n\n- must stay\n"):
        from types import SimpleNamespace

        def fake(prompt, working_directory, **kwargs):
            return SimpleNamespace(ok=ok, text=text, execution_id="exec-test")

        monkeypatch.setattr("drydock.rigging_compact.run_prompt", fake)

    def _setup_blueprint(self, tmp_target_root, name="Proj", **files):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        spec = tmp_target_root / name / "blueprint"
        spec.mkdir(parents=True)
        for fname, body in (files or {"DATABASE.md": "class X: ...\n"}).items():
            (spec / fname).write_text(body, encoding="utf-8")
        return spec

    def test_help_lists_flags(self):
        rc, out, _ = run_cli("rigging", "compact", "--help")
        assert rc == 0
        assert "--all" in out and "--force" in out

    def test_compacts_and_reports(self, tmp_target_root, isolated_config, monkeypatch):
        spec = self._setup_blueprint(tmp_target_root)
        self._fake_run_prompt(monkeypatch)
        rc, out, err = run_cli("rigging", "compact", "Proj")
        assert rc == 0, err
        assert (spec / "DATABASE_compact.md").exists()
        assert "1 compacted" in out
        assert "exec-test" in out
        assert (
            "AUTO-COMPACT: compacting DATABASE.md -> DATABASE_compact.md "
            "[Database API via rigging_compact_database.md]"
        ) in out
        assert "Database API via rigging_compact_database.md" in out

    def test_failed_execution_exits_one(self, tmp_target_root, isolated_config, monkeypatch):
        self._setup_blueprint(tmp_target_root)
        self._fake_run_prompt(monkeypatch, ok=False, text="")
        rc, out, err = run_cli("rigging", "compact", "Proj")
        assert rc == 1
        assert "1 failed" in out

    def test_nothing_to_compact(self, tmp_target_root, isolated_config, monkeypatch):
        self._setup_blueprint(tmp_target_root, **{"README.md": "no compactables\n"})
        self._fake_run_prompt(monkeypatch)
        rc, out, err = run_cli("rigging", "compact", "Proj")
        assert rc == 0
        assert "Nothing to compact" in out

    def test_reports_contracts_role_for_non_database_file(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        spec = self._setup_blueprint(tmp_target_root, **{"FEATURE-Status.md": "GET /status\n"})
        self._fake_run_prompt(monkeypatch)
        rc, out, err = run_cli(
            "rigging", "compact", "Proj", "--include-file", str(spec / "FEATURE-Status.md")
        )
        assert rc == 0, err
        assert "Contracts via rigging_compact_contracts.md" in out


class TestAnalyzeCommand:
    def test_help_lists_llm_provider_flag(self):
        rc, out, _ = run_cli("analyze", "--help")
        assert rc == 0
        assert "--llm-provider" in out

    def test_build_help_lists_reset_normalize_and_dry_run_flags(self):
        rc, out, _ = run_cli("build", "--help")
        assert rc == 0
        assert "--build-dir" in out
        assert "--reset" in out
        assert "--story" in out
        assert "--continue" in out
        assert "--normalize-order" in out
        assert "--dry-run" in out
        assert "--show-prompt" in out
        assert "--repair-attempts" in out
        assert "default 6" in out
        assert "--escalate-model" in out
        assert "--reset-failed" not in out
        assert "--force" not in out

    @pytest.mark.parametrize(
        "argv",
        [("build", "Marina", "--help"), ("build", "--help", "Marina")],
    )
    def test_build_help_is_handled_before_build_dispatch(self, monkeypatch, argv):
        def fail_if_called(_args):
            pytest.fail("build execution must not start for --help")

        monkeypatch.setattr("drydock.cli.cmd_build", fail_if_called)

        rc, out, err = run_cli(*argv)

        assert rc == 0, err
        assert "Build or inspect build state." in out
        assert "--ungate" in out

    @pytest.mark.parametrize(
        "argv",
        [("build", "Marina", "--ungate"), ("build", "--ungate", "Marina")],
    )
    def test_build_flags_are_applied_in_either_operand_order(self, monkeypatch, argv):
        seen = {}

        def fake_build(build_args):
            seen.update(vars(build_args))
            return 0

        monkeypatch.setattr("drydock.cli.cmd_build", fake_build)

        rc, _out, err = run_cli(*argv)

        assert rc == 0, err
        assert seen["Target"] == "Marina"
        assert seen["ungate"] is True

    def test_plan_and_build_help_describe_override(self):
        for command in ("plan", "build"):
            rc, out, _ = run_cli(command, "--help")
            assert rc == 0
            assert "--override" in out
            # The help must name what override does not waive; a reader who assumes it waives
            # everything will trust a green run over a blocked analysis.
            assert "BLOCKERS.md" in out

    @pytest.mark.parametrize(
        "argv",
        [("build", "Marina", "--override"), ("build", "--override", "Marina")],
    )
    def test_build_override_is_applied_in_either_operand_order(self, monkeypatch, argv):
        seen = {}

        def fake_build(build_args):
            seen.update(vars(build_args))
            return 0

        monkeypatch.setattr("drydock.cli.cmd_build", fake_build)

        rc, _out, err = run_cli(*argv)

        assert rc == 0, err
        assert seen["Target"] == "Marina"
        assert seen["override"] is True

    def test_document_and_score_help_list_dispatcher_only_options(self):
        rc, document_help, _ = run_cli("document", "--help")
        assert rc == 0
        assert "--theme" in document_help

        rc, score_help, _ = run_cli("score", "--help")
        assert rc == 0
        assert "--step <id>" in score_help

    def test_analyze_passes_cli_provider_override(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        target_dir = tmp_target_root / "Proj"
        (target_dir / "blueprint").mkdir(parents=True)

        seen = {}

        def fake_analyze(target, passed_target_dir, **kwargs):
            seen["target"] = target
            seen["target_dir"] = passed_target_dir
            seen["kwargs"] = kwargs
            return SimpleNamespace(
                ok=True,
                target_dir=passed_target_dir,
                analysis_path=passed_target_dir / "ANALYSIS.md",
                sea_trials_path=passed_target_dir / "SEA_TRIALS.md",
                soundings_path=passed_target_dir / "SOUNDINGS.md",
                compass_path=None,
                discovery_paths=(),
                commanders_chair_path=None,
                quality="Ready",
                story_count=0,
                question_count=0,
                blocker_count=0,
                screen_count=0,
                stack="python",
            )

        monkeypatch.setattr("drydock.analyze.analyze", fake_analyze)

        rc, out, err = run_cli("analyze", "Proj", "--llm-provider", "codex")

        assert rc == 0, err
        assert seen["target"] == "Proj"
        assert seen["target_dir"] == target_dir
        assert seen["kwargs"]["llm_provider"] == "codex"

    def test_analyze_prints_sea_trials_blocker_as_warning(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        target_dir = tmp_target_root / "Proj"
        (target_dir / "blueprint").mkdir(parents=True)
        blockers_path = target_dir / "BLOCKERS.md"
        blockers_path.write_text(
            "# Blockers\n\n"
            "## blocker-sea-trials: Define project acceptance criteria\n"
            "SEA_TRIALS.md was not created because analyze could not derive valid criteria.\n",
            encoding="utf-8",
        )
        result = SimpleNamespace(
            ok=True,
            target_dir=target_dir,
            analysis_path=target_dir / "ANALYSIS.md",
            sea_trials_path=target_dir / "SEA_TRIALS.md",
            sea_trials_created=False,
            warnings=("SEA_TRIALS.md was not created: analyze returned no acceptance criteria.",),
            compass_path=None,
            discovery_paths=(),
            commanders_chair_path=None,
            blockers_path=blockers_path,
            quality="Blocked",
            story_count=0,
            feature_count=0,
            question_count=0,
            blocker_count=1,
            screen_count=0,
            stack="python",
        )
        monkeypatch.setattr("drydock.analyze.analyze", lambda *args, **kwargs: result)

        rc, out, err = run_cli("analyze", "Proj")

        assert rc == 0
        assert "SEA_TRIALS.md →" not in out  # the success line is not printed
        assert "Quality: ✗  Blocked" in out
        # The blocker is a prominent closing banner naming the blocker and the fix.
        assert "BLOCKER — FIX TO PROCEED: Proj" in out
        assert "blocker-sea-trials: Define project acceptance criteria" in out
        assert "Edit BLOCKERS.md" in out
        assert "Re-run: drydock analyze Proj" in out
        assert "drydock run quarterdeck Proj" in out
        # Warnings print on stdout so they survive in the run transcript, which tees stdout only.
        assert "Warning: SEA_TRIALS.md was not created" in out
        assert "Warning:" not in err


class TestLlmOverrideFlags:
    def test_status_help_lists_llm_flags(self):
        rc, out, _ = run_cli("status", "--help")
        assert rc == 0
        assert "--llm-provider" in out
        assert "--model" in out

    def test_status_accepts_global_llm_overrides_from_installed_entrypoint(
        self, isolated_config, monkeypatch
    ):
        seen = []
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "drydock",
                "status",
                "Example",
                "--llm-provider",
                "codex",
                "--model",
                "gpt-5.6-luna",
            ],
        )
        monkeypatch.setattr(
            "drydock.cli.cmd_status_blueprint_target",
            lambda blueprint, target: seen.append((blueprint, target)) or 0,
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert seen == [("Example", "Example")]

    def test_plan_help_lists_llm_flags(self):
        rc, out, _ = run_cli("plan", "--help")
        assert rc == 0
        assert "--llm-provider" in out
        assert "--model" in out

    def test_survey_help_lists_llm_flags(self):
        rc, out, _ = run_cli("survey", "--help")
        assert rc == 0
        assert "--llm-provider" in out
        assert "--model" in out

    def test_prompt_review_help_lists_llm_flags(self):
        rc, out, _ = run_cli("prompt", "review", "--help")
        assert rc == 0
        assert "--llm-provider" in out
        assert "--model" in out

    def test_rigging_compact_help_lists_llm_flags(self):
        rc, out, _ = run_cli("rigging", "compact", "--help")
        assert rc == 0
        assert "--llm-provider" in out
        assert "--model" in out

    def test_status_accepts_global_llm_overrides(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        target = tmp_target_root / "Drydock"
        (target / "blueprint").mkdir(parents=True)

        rc, out, err = run_cli("status", "Drydock", "--llm-provider", "codex", "--model", "gpt-5.4")

        assert rc == 0, err
        assert "Drydock status" in out

    def test_build_status_accepts_global_llm_overrides(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        target.mkdir()
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nupdated: 2026-06-11T12:00:00\nplan_hash: abc123\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, out, err = run_cli(
            "build",
            "status",
            "ExampleTarget",
            "--llm-provider",
            "codex",
            "--model",
            "gpt-5.4",
        )

        assert rc == 0, err
        assert "Blueprint: ExampleTarget" in out

    def test_build_forwards_global_llm_overrides_to_cmd_build(self, isolated_config, monkeypatch):
        """``drydock build <Target>`` has its global LLM flags stripped from argv before
        the build sub-parser runs, so the dispatcher must carry them onto the build
        namespace. Without this the build silently runs on the configured default model."""
        seen: dict[str, str | None] = {}
        monkeypatch.setattr(
            sys,
            "argv",
            ["drydock", "build", "Example", "--llm-provider", "codex", "--model", "gpt-5.6-luna"],
        )
        monkeypatch.setattr(
            "drydock.cli.cmd_build",
            lambda build_args: (
                seen.update(model=build_args.model, llm_provider=build_args.llm_provider) or 0
            ),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert seen == {"model": "gpt-5.6-luna", "llm_provider": "codex"}

    def test_build_rejects_provider_model_mismatch_up_front(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nupdated: 2026-06-11T12:00:00\nplan_hash: abc123\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, out, err = run_cli(
            "build", "ExampleTarget", "--llm-provider", "codex", "--model", "opus"
        )

        assert rc == 2
        assert "Model/provider mismatch" in err
        assert "--llm-provider claude" in err
        # The failure is up front: no build banner should have printed.
        assert "BUILD COMMAND START" not in out

    def test_plan_passes_cli_overrides(self, tmp_target_root, isolated_config, monkeypatch):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        target_dir = tmp_target_root / "Proj"
        (target_dir / "blueprint" / "sources").mkdir(parents=True)
        (target_dir / "ANALYSIS.md").write_text(
            "# Blueprint Analysis: Proj\n\nQuality: Questions\n\n## Story List\n\nProject type: `cli`\n",
            encoding="utf-8",
        )

        seen = {}

        def fake_create_plan(blueprint, target, target_directory, **kwargs):
            seen["kwargs"] = kwargs
            kwargs["on_text"]("[plan-score]Topology Created:  True\nBlueprints Created: 5 / 10\n")
            return SimpleNamespace(
                plan=SimpleNamespace(
                    project="Proj",
                    path=target_dir / "MANIFEST.md",
                    state="draft",
                    blocks=[],
                    state_counts=lambda: {
                        "pending": 0,
                        "implemented": 0,
                        "closed/verified": 0,
                        "closed/failed": 0,
                    },
                ),
                quarterdeck_dir=target_dir / "QuarterDeck",
                authored_files=(),
                target_dir=target_dir,
                warnings=(),
                plan_mode="full-rewrite",
                conformed_files=(),
            )

        monkeypatch.setattr("drydock.planning_session.create_plan", fake_create_plan)

        rc, out, err = run_cli(
            "plan",
            "Proj",
            "--llm-provider",
            "codex",
            "--model",
            "gpt-5.4",
        )

        assert rc == 0, err
        assert seen["kwargs"]["llm_provider"] == "codex"
        assert seen["kwargs"]["model"] == "gpt-5.4"
        assert callable(seen["kwargs"]["on_text"])
        assert seen["kwargs"]["on_text"] is not print
        assert "Topology Created:  True" in out
        assert "Blueprints Created: 5 / 10" in out
        # Conform pass is on by default and suppressed by --no-conform.
        assert seen["kwargs"]["conform"] is True

        rc, out, err = run_cli("plan", "Proj", "--no-conform")
        assert rc == 0, err
        assert seen["kwargs"]["conform"] is False

    def test_plan_conflict_returns_deferred_banner(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        from drydock.errors import ErrorRecord
        from drydock.planning_session import PlanDeferredResult

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        target_dir = tmp_target_root / "Proj"
        (target_dir / "blueprint" / "sources").mkdir(parents=True)
        error_path = target_dir / "ERRORS.md"
        record = ErrorRecord(
            command="plan",
            phase="product decision",
            timestamp="t",
            classification="plan requires a product decision",
            detail=(
                "Confirmed conflict:\nReason:\n- sources/a.md and sources/b.md govern the "
                "same scope differently."
            ),
            recovery="Choose the governing clause.",
            execution_id="exec-123",
            challenge_execution_id="exec-456",
            state="Deferred",
        )

        def fake_create_plan(*args, **kwargs):
            return PlanDeferredResult(
                target_dir=target_dir,
                error_record=record,
                errors_path=error_path,
                detail=record.detail,
                initial_execution_id="exec-123",
                challenge_execution_id="exec-456",
                plan_mode="full-rewrite",
            )

        monkeypatch.setattr("drydock.planning_session.create_plan", fake_create_plan)

        rc, out, err = run_cli("plan", "Proj")

        assert rc == 2
        assert not err
        assert "PLAN DEFERRED" in out
        assert "sources/a.md and sources/b.md" in out
        assert "Choose the governing clause." in out
        assert "ERRORS.md:" in out
        assert "drydock run quarterdeck Proj" in out
        assert "drydock plan Proj" in out
        assert "exec-123" in out
        assert "exec-456" in out


class TestPlanInspection:
    @pytest.fixture(autouse=True)
    def _guardrail_is_not_the_subject_of_plan_inspection(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.compass_guardrail.validate_guardrail", lambda *args, **kwargs: None
        )

    PLAN = """# MANIFEST: Example
updated: 2026-06-11T12:00:00
plan_hash: abc123

## story 1: Foundation
id: foundation
state: closed/verified

## story 2: Import documents
id: import-documents
depends: foundation
state: pending

## story 3: Awaiting checks
id: awaiting-checks
state: implemented

## ac 1: System starts
id: system-starts
parent: awaiting-checks
state: pending
"""

    def _setup(self, tmp_target_root, monkeypatch):
        target = tmp_target_root / "ExampleTarget"
        target.mkdir()
        (target / "MANIFEST.md").write_text(self.PLAN, encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

    def test_build_status_reports_grouped_progress_and_frontier(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)

        rc, out, err = run_cli("build", "status", "ExampleTarget")

        assert rc == 0, err
        assert f"Target: {tmp_target_root / 'ExampleTarget'}" in out
        assert "[done]" in out  # foundation is closed/verified
        assert "import-documents" in out
        assert "<- next" in out  # import-documents is buildable
        assert "Steps: 3 total" in out
        assert "Buildable now: import-documents" in out

    def test_build_status_usage_error(self):
        rc, out, err = run_cli("build", "status")

        assert rc == 2
        assert "Usage: drydock build status" in err

    def test_build_executes_buildable_frontier(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            out_dir = Path(a[1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "foundation.txt").write_text("built\n", encoding="utf-8")
            return SimpleNamespace(
                ok=True,
                text=(
                    "RESULT: SUCCESS\n\n"
                    "FILES CHANGED:\n"
                    "- foundation.txt\n\n"
                    "SUMMARY:\n"
                    "Built foundation.\n"
                ),
                execution_id="exec-fake",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, err = run_cli("build", "ExampleTarget", "--build-dir", str(tmp_path / "out"))

        assert rc == 0, err
        assert "Build: ExampleTarget" in out
        assert "scope: entire project" in out
        assert "frontier: foundation" in out
        assert re.search(r"elapsed: ", out)
        assert "built: foundation — closed/verified · execution exec-fake" in out
        assert "foundation" in out
        assert "Target - setup project workspace git store" in out
        assert "Target - committed project workspace git store" in out
        assert (target / "evidence" / "foundation.md").is_file()

    def test_build_reports_failed_block_as_resume_frontier(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "state: closed/failed\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--dry-run",
            "--build-dir",
            str(tmp_path / "out"),
        )

        assert rc == 0, err
        assert "frontier: resume foundation" in out
        assert "frontier: empty" not in out

    def test_build_failure_prints_force_hint(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            return SimpleNamespace(
                ok=False,
                text="",
                stderr="provider crashed",
                execution_id="exec-fake",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, _ = run_cli("build", "ExampleTarget", "--build-dir", str(tmp_path / "out"))

        assert rc == 1
        assert "failed: foundation — closed/failed · execution exec-fake" in out
        assert "result: 0 built, 1 failed" in out
        # The actionable failure block closes the run after the concise summary.
        assert out.index("BUILD FAILED: ExampleTarget") > out.index("result: 0 built, 1 failed")
        assert "Foundation [foundation]" in out
        assert "LLM execution failed" in out
        assert "rerun drydock build to continue this step" in out
        assert "add --reset to discard its work" in out

    def test_build_multi_story_failure_prints_one_banner_with_detail(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## feature 1: Catalog\nid: feature-catalog\nsummary: Catalog block.\n"
            "state: pending\n\n"
            "## story 2: Foundation\nid: foundation\nparent: feature-catalog\n"
            "implements: DATABASE.md\ninstructions: |\n  Build it.\nstate: pending\n\n"
            "## story 3: Service\nid: service\nparent: feature-catalog\n"
            "implements: SERVICE.md\ninstructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        (target / "blueprint" / "SERVICE.md").write_text("Svc.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            return SimpleNamespace(
                ok=True,
                text=(
                    "RESULT: FAILURE\n"
                    "FAILURE_SUMMARY: Full conformance requirement not met.\n"
                    "FAILURE_DETAIL: The backend diverges from the spec.\n"
                ),
                stderr="",
                execution_id="exec-fake",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, _ = run_cli("build", "ExampleTarget", "--build-dir", str(tmp_path / "out"))

        assert rc == 1
        # Both stories are accounted for, but the failure block renders once per execution.
        assert out.count("BUILD FAILED: ExampleTarget") == 1
        assert "(1 step)" in out
        assert "failed: feature-catalog — closed/failed · execution exec-fake" in out
        assert "The backend diverges from the spec." in out
        assert "Story recovery (dependency order)" in out
        assert "drydock build ExampleTarget --story foundation --repair-attempts 6" in out
        assert "drydock build ExampleTarget --story service --repair-attempts 6" in out

    def test_build_failure_diagnosis_reaches_errors_and_evidence(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        from drydock.diagnose import reset_diagnosis_guard

        reset_diagnosis_guard()
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _build(*a, **k):
            return SimpleNamespace(
                ok=True,
                text=(
                    "RESULT: FAILURE\n"
                    "FAILURE_SUMMARY: Full conformance requirement not met.\n"
                    "FAILURE_DETAIL: The backend diverges from the spec.\n"
                ),
                stderr="",
                execution_id="exec-fake",
            )

        def _diagnose(*a, **k):
            return SimpleNamespace(
                ok=True,
                text="CAUSE: the build wrapped a library instead of writing the parser.\n"
                "DO: rerun drydock build ExampleTarget",
                execution_id="exec-diag",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _build)
        monkeypatch.setattr("drydock.llm.run_prompt", _diagnose)

        rc, out, err = run_cli("build", "ExampleTarget", "--build-dir", str(tmp_path / "out"))

        assert rc == 1
        assert "A MAJOR ERROR HAS OCCURRED" in err
        diagnosis = "CAUSE: the build wrapped a library instead of writing the parser."
        assert diagnosis in (target / "ERRORS.md").read_text(encoding="utf-8")
        evidence = (target / "evidence" / "foundation.md").read_text(encoding="utf-8")
        assert "## Diagnosis" in evidence
        assert diagnosis in evidence
        reset_diagnosis_guard()

    def test_build_dry_run_prints_prompt_without_writes(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        manifest = (
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n"
        )
        (target / "MANIFEST.md").write_text(manifest, encoding="utf-8")
        (target / "COMPASS.md").write_text("Compass.\n", encoding="utf-8")
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            raise AssertionError("dry-run must not invoke the LLM runner")

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)
        build_dir = tmp_path / "out"

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--build-dir",
            str(build_dir),
            "--dry-run",
        )

        assert rc == 0, err
        assert "mode: DRY RUN — no LLM call" in out
        assert "\ndry run: no reusable compacts are written\n" in out
        assert "\ndry run assembled files\n" in out
        assert "Role       File" in out
        assert "implements DATABASE.md" in out
        assert "dry run prompt: assembled" in out
        assert "dry run prompt: hidden; use --show-prompt to print it" in out
        assert "dry run prompt begin" not in out
        assert "dry run prompt end" not in out
        assert "- BUILD_SCOPE: exactly one MANIFEST.md step" not in out
        assert "DB." not in out
        assert "result: dry-run complete" in out
        assert "dry-run result: 0 built, 0 failed" in out
        assert "refreshdry run" not in out
        assert "FILES  -" not in out
        assert not build_dir.exists()
        assert not (target / "evidence").exists()
        assert (target / "MANIFEST.md").read_text(encoding="utf-8") == manifest

    def test_build_prints_resolved_llm_from_config(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from drydock.config import config_set

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "COMPASS.md").write_text("Compass.\n", encoding="utf-8")
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        config_set("llm_provider", "codex")
        config_set("drydock_model", "gpt-5.4")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            raise AssertionError("dry-run must not invoke the LLM runner")

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--build-dir",
            str(tmp_path / "out"),
            "--dry-run",
        )

        assert rc == 0, err
        assert "frontier: foundation" in out
        assert "dry-run result: 0 built, 0 failed, 1 unchanged" in out

    def test_build_dry_run_show_prompt_prints_full_prompt(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "COMPASS.md").write_text("Compass.\n", encoding="utf-8")
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--build-dir",
            str(tmp_path / "out"),
            "--dry-run",
            "--show-prompt",
        )

        assert rc == 0, err
        assert "mode: full prompt output enabled by --show-prompt" in out
        assert "dry run prompt begin" in out
        assert "dry run prompt end" in out
        assert "- BUILD_SCOPE: exactly one MANIFEST.md step" in out
        assert "DB." in out

    def test_build_step_reset_rebuilds_selected_step(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: closed/verified\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            out_dir = Path(a[1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "foundation.txt").write_text("rebuilt\n", encoding="utf-8")
            return SimpleNamespace(
                ok=True,
                text="RESULT: SUCCESS\n\nFILES CHANGED:\n- foundation.txt\n\nSUMMARY:\nRebuilt.\n",
                execution_id="exec-fake",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--step",
            "foundation",
            "--reset",
            "--build-dir",
            str(tmp_path / "out"),
        )

        assert rc == 0, err
        assert "scope: step foundation" in out
        assert "reset: foundation" in out
        assert "built: foundation — closed/verified · execution exec-fake" in out
        assert "foundation" in out
        assert "result: 1 built, 0 failed" in out

    def test_build_reset_resets_whole_project_then_builds_frontier(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## feature 1: Core\nid: core\nfinding: failed group\nstate: closed/failed\n\n"
            "## story 1: Foundation\nid: foundation\nparent: core\n"
            "implements: DATABASE.md\nfinding: failed story\n"
            "instructions: |\n  Build it.\nstate: closed/failed\n\n"
            "## ac 1: Foundation Passes\nid: foundation-passes\nparent: foundation\n"
            "kind: smoke\ncheck: true\nstate: closed/failed\n",
            encoding="utf-8",
        )
        (target / "COMPASS.md").write_text("Compass.\n", encoding="utf-8")
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            out_dir = Path(a[1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "foundation.txt").write_text("rebuilt\n", encoding="utf-8")
            return SimpleNamespace(
                ok=True,
                text="RESULT: SUCCESS\n\nFILES CHANGED:\n- foundation.txt\n\nSUMMARY:\nRebuilt.\n",
                execution_id="exec-fake",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--reset",
            "--build-dir",
            str(tmp_path / "out"),
        )

        assert rc == 0, err
        assert "reset: entire project (all blocks + build directory)" in out
        assert "built: core — closed/verified · execution exec-fake" in out
        text = (target / "MANIFEST.md").read_text(encoding="utf-8")
        assert "finding: failed" not in text
        assert "state: closed/failed" not in text

    def test_build_step_and_story_are_mutually_exclusive(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, _out, err = run_cli(
            "build", "ExampleTarget", "--step", "foundation", "--story", "foundation"
        )
        assert rc == 2
        assert "--step and --story are mutually exclusive" in err

    def test_build_continue_and_reset_are_mutually_exclusive(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, _out, err = run_cli("build", "ExampleTarget", "--continue", "--reset")
        assert rc == 2
        assert "--continue and --reset are mutually exclusive" in err

    def test_build_continue_behaves_as_default(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## story 1: Foundation\nid: foundation\nimplements: DATABASE.md\n"
            "instructions: |\n  Build it.\nstate: pending\n",
            encoding="utf-8",
        )
        (target / "COMPASS.md").write_text("Compass.\n", encoding="utf-8")
        (target / "blueprint" / "DATABASE.md").write_text("DB.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        def _run(*a, **k):
            out_dir = Path(a[1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "foundation.txt").write_text("built\n", encoding="utf-8")
            return SimpleNamespace(
                ok=True,
                text="RESULT: SUCCESS\n\nFILES CHANGED:\n- foundation.txt\n\nSUMMARY:\nBuilt.\n",
                execution_id="exec-fake",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, err = run_cli(
            "build", "ExampleTarget", "--continue", "--build-dir", str(tmp_path / "out")
        )
        assert rc == 0, err
        assert "built: foundation — closed/verified · execution exec-fake" in out

    def test_build_normalize_order_reorders_manifest_then_builds_frontier(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: ExampleTarget\nstate: draft\n\n"
            "## feature 1: Screen Setup\nid: screen-setup\nsummary: Screen.\nstate: pending\n\n"
            "## story 1: Screen Setup\nid: screen-setup-story\nparent: screen-setup\n"
            "implements: SCREEN-SETUP.md\nscope: both\ninstructions: |\n  Build screen.\n"
            "state: pending\n\n"
            "## feature 2: Feature Core\nid: feature-core\nsummary: Core.\nstate: pending\n\n"
            "## story 2: Feature Core\nid: feature-core-story\nparent: feature-core\n"
            "implements: FEATURE-CORE.md\nscope: both\ninstructions: |\n  Build core.\n"
            "state: pending\n",
            encoding="utf-8",
        )
        (target / "COMPASS.md").write_text("Compass.\n", encoding="utf-8")
        (target / "blueprint" / "SCREEN-SETUP.md").write_text("Screen.\n", encoding="utf-8")
        (target / "blueprint" / "FEATURE-CORE.md").write_text("Core.\n", encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        calls = iter(("core", "screen"))

        def _run(*a, **k):
            out_dir = Path(a[1])
            out_dir.mkdir(parents=True, exist_ok=True)
            name = next(calls)
            (out_dir / f"{name}.txt").write_text("built\n", encoding="utf-8")
            return SimpleNamespace(
                ok=True,
                text=f"RESULT: SUCCESS\n\nFILES CHANGED:\n- {name}.txt\n\nSUMMARY:\nBuilt.\n",
                execution_id="exec-fake",
            )

        monkeypatch.setattr("drydock.build_run.run_prompt", _run)

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--normalize-order",
            "--build-dir",
            str(tmp_path / "out"),
        )

        assert rc == 0, out + err
        assert "optimize build blocks: updated MANIFEST.md" in out
        assert "built: feature-core — closed/verified · execution exec-fake" in out
        text = (target / "MANIFEST.md").read_text(encoding="utf-8")
        assert text.index("id: feature-core") < text.index("id: screen-setup")

    def test_build_with_blocked_pending_step_reports_external_dependency(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        target = tmp_target_root / "ExampleTarget"
        target.mkdir()
        manifest = self.PLAN.replace(
            "id: import-documents\ndepends: foundation\nstate: pending",
            "id: import-documents\ndepends: awaiting-checks\nstate: pending",
        )
        (target / "MANIFEST.md").write_text(manifest, encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, out, err = run_cli("build", "ExampleTarget", "--build-dir", str(tmp_path / "out"))

        assert rc == 1
        assert "unverified external dependencies: Awaiting checks [awaiting-checks]" in err
        assert "Awaiting checks [awaiting-checks]: state=implemented" in err
        assert "Options:" in err
        assert "Review and normalize in QuarterDeck" in err
        assert "Story Retry: drydock build ExampleTarget --step awaiting-checks" in err
        assert "drydock build status ExampleTarget" in err


class TestPlanningSession:
    def _configure(self, tmp_target_root, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

    _LLM_OUTPUT = (
        "=== ARCHITECTURE.md ===\n"
        "# ARCHITECTURE: ExampleTarget\n\n"
        "| Field | Value |\n|---|---|\n| Version | 20260616 V1 |\n"
        "| Description | Status command architecture. |\n| Phase | 1 |\n\n"
        "## Programmatic Acceptance\n\n- None.\n\n## User Acceptance\n\n- None.\n\n"
        "## Guardrails\n\n- None.\n\n"
        "## Questions\n\n- None.\n"
        "=== END ARCHITECTURE.md ===\n"
        "=== FEATURE-Status.md ===\n"
        "# FEATURE: Status\n\n"
        "| Field | Value |\n|---|---|\n| Version | 20260616 V1 |\n"
        "| Description | Status command. |\n| Phase | 1 |\n\n"
        "## Programmatic Acceptance\n\n- None.\n\n## User Acceptance\n\n"
        "- Status command exits successfully.\n\n"
        "## Guardrails\n\n- None.\n\n## Questions\n\n- None.\n"
        "=== END FEATURE-Status.md ===\n"
        "=== MANIFEST.md ===\n"
        "# MANIFEST: ExampleTarget\nupdated: 2026-06-16\nplan_hash: test\nstate: draft\n\n"
        "## feature 1: Status\nid: feature-status\nsummary: Status workflow.\nstate: pending\n\n"
        "## story 1: Deliver Status\nid: story-status\nparent: feature-status\n"
        "summary: Build status.\nimplements: FEATURE-Status.md\nscope: both\nstate: pending\n\n"
        "## ac 1: Status command exits successfully\nid: ac-status-exits\nparent: story-status\n"
        "kind: assertion\nstate: pending\n"
        "=== END MANIFEST.md ===\n"
    )

    def _patch_runner(self, monkeypatch, text: str | None = None):
        from types import SimpleNamespace

        payload = text if text is not None else self._LLM_OUTPUT

        def _run(*a, **k):
            return SimpleNamespace(ok=True, text=payload, execution_id="exec-fake")

        monkeypatch.setattr("drydock.planning_session.run_prompt", _run)

    def test_markdown_import_plan_create_and_approve(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        source = tmp_path / "request.md"
        source.write_text(
            "# Request\n\nBuild a status command.\n\n## Acceptance Criteria\n\n"
            "- Status command exits successfully.\n",
            encoding="utf-8",
        )

        rc, out, err = run_cli("import", "ExampleTarget", str(source), "--format", "markdown")
        assert rc == 0, err
        bp = tmp_target_root / "ExampleTarget" / "blueprint"
        assert (bp / "sources" / "request.md").is_file()

        # plan requires a reviewed analysis and a fake LLM runner.
        (tmp_target_root / "ExampleTarget" / "ANALYSIS.md").write_text(
            "# Blueprint Analysis: ExampleTarget\n\nQuality: Questions\n\n"
            "## Story List\n\nProject type: `cli`\n",
            encoding="utf-8",
        )
        self._patch_runner(monkeypatch)

        rc, out, err = run_cli("plan", "ExampleTarget")
        assert rc == 0, err
        assert "Plan state:" not in out
        assert "Graph: 1 features, 1 stories, 0 spikes, 1 acceptance gates" in out
        assert "Warnings: 0" in out
        assert "Outcome: updated" in out
        assert "Execution: exec-fake" in out
        assert "Review:" in out
        assert "=== ARCHITECTURE.md ===" not in out
        assert "Status command exits successfully." not in out
        assert not (bp.parent / "BUILD_COMPASS.md").exists()
        assert "Status command exits successfully." in (bp / "FEATURE-Status.md").read_text(
            encoding="utf-8"
        )
        plan_path = tmp_target_root / "ExampleTarget" / "MANIFEST.md"
        assert "story-status" in plan_path.read_text(encoding="utf-8")
        quarterdeck = tmp_target_root / "ExampleTarget" / "QuarterDeck"
        assert (quarterdeck / "console.yaml").is_file()
        assert not (quarterdeck / "tickets.json").exists()
        assert not (quarterdeck / "app.py").exists()
        config = (quarterdeck / "console.yaml").read_text(encoding="utf-8")
        assert config.index('label: "Sea Trials"') < config.index('label: "Soundings"')

        # Build readiness is not gated by plan state — running is the approval.
        # A pending grouped block with no unmet external dependencies is buildable immediately.
        rc, out, err = run_cli("build", "status", "ExampleTarget")
        assert rc == 0, err
        assert "Buildable now: feature-status" in out

    def test_plan_invalid_llm_output_prints_clear_failure(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        target = tmp_target_root / "ExampleTarget"
        (target / "blueprint" / "sources").mkdir(parents=True)
        (target / "blueprint" / "sources" / "request.md").write_text(
            "# Request\n\nBuild a status command.\n", encoding="utf-8"
        )
        (target / "ANALYSIS.md").write_text(
            "# Blueprint Analysis: ExampleTarget\n\nQuality: Questions\n\n"
            "## Story List\n\nProject type: `cli`\n",
            encoding="utf-8",
        )
        bad_manifest = (
            "=== MANIFEST.md ===\n"
            "# MANIFEST: ExampleTarget\nupdated: 2026-06-16\nplan_hash: test\nstate: draft\n\n"
            "## story 1: Bad\nid: bad\nsummary: Bad plan.\nimplements: GHOST.md\n"
            "state: pending\n\n"
            "## ac 1: Bad check\nid: bad-check\nparent: bad\nkind: assertion\nstate: pending\n"
            "=== END MANIFEST.md ===\n"
        )
        self._patch_runner(monkeypatch, bad_manifest)

        rc, out, err = run_cli("plan", "ExampleTarget")

        assert rc == 1
        assert "Plan generation failed" in err
        assert "implements missing spec file 'GHOST.md'" in err
        assert "No files were changed" in err
        assert not (target / "MANIFEST.md").exists()
        assert not (target / "QuarterDeck" / "tickets.json").exists()

    @pytest.mark.parametrize("verb", ["create", "init", "show", "approve", "revise", "reject"])
    def test_plan_rejects_a_verb_it_does_not_publish(self, verb):
        """``verify`` and ``repair`` are the only sub-verbs; anything else is an operand."""
        rc, out, err = run_cli("plan", verb, "Example", "Target")

        assert rc == 2
        assert "Unexpected operand for drydock plan" in err

    @pytest.mark.parametrize("verb", ["verify", "repair"])
    def test_plan_publishes_its_sub_verbs(self, verb):
        rc, out, err = run_cli("plan", verb)

        assert rc == 2
        assert f"drydock plan {verb} requires a Target" in err


class TestPlanVerifyAndRepair:
    """The two-command workflow: verification is free and decides whether repair is paid for."""

    _BROKEN = (
        "# FEATURE: Broken\n\n## Programmatic Acceptance\n\n"
        "=== AC path-filter ===\n"
        "Intent: Filtered paths select only matching locations.\n\n"
        "import subprocess\n\n"
        'result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)\n'
        "assert result.returncode == 0\n"
        "=== END AC path-filter ===\n"
    )
    _RUNNABLE = (
        "# FEATURE: Ok\n\n## Programmatic Acceptance\n\n"
        "=== AC ok ===\nIntent: Runs.\n\nimport json\n\n"
        'assert "a" in json.dumps({"a": 1})\n'
        "=== END AC ok ===\n"
    )

    def _configure(self, tmp_target_root, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

    def test_plan_verify_exits_zero_on_a_runnable_blueprint(
        self, tmp_target_root, isolated_config, monkeypatch, make_blueprint
    ):
        self._configure(tmp_target_root, monkeypatch)
        make_blueprint("Proj", {"FEATURE-Ok.md": self._RUNNABLE})

        rc, out, err = run_cli("plan", "verify", "Proj")

        assert rc == 0, err
        assert "every one can run" in out

    def test_plan_verify_exits_one_and_names_the_criterion(
        self, tmp_target_root, isolated_config, monkeypatch, make_blueprint
    ):
        self._configure(tmp_target_root, monkeypatch)
        make_blueprint("Proj", {"FEATURE-Broken.md": self._BROKEN})

        rc, out, err = run_cli("plan", "verify", "Proj")

        assert rc == 1
        assert "FEATURE-Broken.md [path-filter]" in out
        assert "drydock plan repair Proj" in out

    def test_plan_verify_never_writes(
        self, tmp_target_root, isolated_config, monkeypatch, make_blueprint
    ):
        self._configure(tmp_target_root, monkeypatch)
        blueprint = make_blueprint("Proj", {"FEATURE-Broken.md": self._BROKEN})
        before = (blueprint / "FEATURE-Broken.md").read_text(encoding="utf-8")

        run_cli("plan", "verify", "Proj")

        assert (blueprint / "FEATURE-Broken.md").read_text(encoding="utf-8") == before


class TestImport:
    def _configure(self, tmp_target_root, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

    def test_import_markdown_copies_source_file(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        source = tmp_path / "spec.md"
        source.write_text("# Spec\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(source), "--format", "markdown")

        assert rc == 0, err
        assert (tmp_target_root / "Tgt" / "blueprint" / "sources" / "spec.md").is_file()

    def test_import_markdown_prints_imported_paths(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        source = tmp_path / "req.md"
        source.write_text("# Req\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(source), "--format", "markdown")

        assert rc == 0, err
        assert f"Source: {source}" in out
        assert f"Target: {tmp_target_root / 'Tgt' / 'blueprint' / 'sources'}/" in out
        assert "\nreq.md" in out
        assert "IMPORTED" not in out
        assert "Blueprint:" not in out
        assert "SAVED AS" not in out
        assert "Next step" not in out

    def test_import_markdown_auto_detects_markdown_file(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        source = tmp_path / "spec.md"
        source.write_text("# Spec\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(source), "--format", "auto")

        assert rc == 0, err
        assert (tmp_target_root / "Tgt" / "blueprint" / "sources" / "spec.md").is_file()

    def test_import_auto_rejects_directory(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        src_dir = tmp_path / "docs"
        src_dir.mkdir()
        (src_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(src_dir), "--format", "auto")

        assert rc == 2
        assert "--format auto requires a file" in err
        assert not (tmp_target_root / "Tgt").exists()

    def test_import_update_needs_no_source_argument(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        src_dir = tmp_path / "docs"
        src_dir.mkdir()
        (src_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        assert run_cli("import", "Tgt", str(src_dir), "--format", "markdown")[0] == 0
        (src_dir / "spec.md").write_text("# Spec revised\n", encoding="utf-8")
        (src_dir / "extra.md").write_text("# Extra\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", "--update")

        assert rc == 0, err
        assert "1 added, 1 changed, 0 deleted, 0 unchanged" in out
        sources = tmp_target_root / "Tgt" / "blueprint" / "sources"
        assert (sources / "spec.md").read_text(encoding="utf-8") == "# Spec revised\n"
        assert (sources / "extra.md").is_file()

    def test_import_update_rejects_source_argument(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)

        rc, out, err = run_cli("import", "Tgt", str(tmp_path), "--update")

        assert rc == 2
        assert "do not pass <Source>" in err

    def test_import_without_source_or_update_is_usage_error(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)

        rc, out, err = run_cli("import", "Tgt")

        assert rc == 2
        assert "requires <Source>" in err

    def test_import_single_file_keeps_prior_directory_root(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        src_dir = tmp_path / "docs"
        src_dir.mkdir()
        (src_dir / "a.md").write_text("# A\n", encoding="utf-8")
        (src_dir / "b.md").write_text("# B\n", encoding="utf-8")
        assert run_cli("import", "Tgt", str(src_dir), "--format", "markdown")[0] == 0

        # Re-importing one member file must not narrow the recorded root to that file.
        assert run_cli("import", "Tgt", str(src_dir / "b.md"), "--format", "markdown")[0] == 0

        rc, out, err = run_cli("import", "Tgt", "--update")

        assert rc == 0, err
        assert "0 deleted" in out

    def test_import_missing_source_returns_1(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)

        rc, out, err = run_cli(
            "import", "Tgt", str(tmp_path / "nonexistent.md"), "--format", "markdown"
        )

        assert rc == 1

    def test_import_source_copies_code_files(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        src_dir = tmp_path / "myapp"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x = 1\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(src_dir), "--format", "source")

        assert rc == 0, err
        assert (tmp_target_root / "Tgt" / "blueprint" / "sources" / "app.py").is_file()
        assert "Target:" in out
        assert "\napp.py" in out

    def test_import_auto_rejects_source_directory(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        src_dir = tmp_path / "myapp"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("x = 1\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(src_dir), "--format", "auto")

        assert rc == 2
        assert "--format auto requires a file" in err
        assert not (tmp_target_root / "Tgt").exists()

    def test_import_speckit_copies_specify_structure(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        src_dir = tmp_path / "sk"
        (src_dir / ".specify" / "memory").mkdir(parents=True)
        (src_dir / ".specify" / "memory" / "constitution.md").write_text("# C\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(src_dir), "--format", "speckit")

        assert rc == 0, err
        sources = tmp_target_root / "Tgt" / "blueprint" / "sources"
        assert (sources / "memory" / "constitution.md").is_file()
        assert not (sources / ".specify").exists()
        assert "Target:" in out
        assert "\nmemory/constitution.md" in out

    def test_import_speckit_auto_detects_speckit_directory(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        src_dir = tmp_path / "sk"
        (src_dir / ".specify" / "memory").mkdir(parents=True)
        (src_dir / ".specify" / "memory" / "constitution.md").write_text("# C\n", encoding="utf-8")

        rc, out, err = run_cli("import", "Tgt", str(src_dir), "--format", "auto")

        assert rc == 2
        assert "--format auto requires a file" in err

    def test_import_compass_rejects_directory(
        self, tmp_path, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_target_root, monkeypatch)
        source = tmp_path / "compass"
        source.mkdir()

        rc, out, err = run_cli("import", "Tgt", str(source), "--format", "compass")

        assert rc == 1
        assert "Compass import requires a file" in err
        assert not (tmp_target_root / "Tgt").exists()

    def test_import_help_shows_arguments(self):
        rc, out, err = run_cli("import", "--help")
        assert rc == 0
        combined = out + err
        assert "<Target>" in combined
        assert "<Source>" in combined


class TestBuildScore:
    def test_reports_aggregate_gate(self, tmp_target_root, isolated_config, monkeypatch):
        from types import SimpleNamespace

        target = tmp_target_root / "ExampleTarget"
        target.mkdir()
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        monkeypatch.setattr(
            "drydock.build_score.score_target",
            lambda *args, **kwargs: SimpleNamespace(
                complete=False,
                scorecard_path=target / "SCORECARD.md",
                evidence_path=target / "evidence" / "build-score.json",
                blockers=("Required Sea Trial st-one is FAIL",),
                attestations=(),
                exit_code=lambda: 1,
            ),
        )

        rc, out, err = run_cli("build", "score", "ExampleTarget")

        assert rc == 1, err
        assert "Completion gate: INCOMPLETE" in out
        assert "Required Sea Trial st-one is FAIL" in out
        assert "ATTESTATION REQUIRED" not in out


class TestRefit:
    """drydock refit CLI contract."""

    def test_help_mentions_target(self):
        rc, out, err = run_cli("refit", "--help")
        assert rc == 0
        combined = out + err
        assert "<Target>" in combined

    def test_missing_target_exits_2(self):
        rc, out, err = run_cli("refit")
        assert rc == 2

    def test_no_changes_dir_exits_0(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = tmp_path / "targets" / "MyProject"
        (target / "blueprint").mkdir(parents=True)
        rc, out, err = run_cli("refit", "MyProject")
        assert rc == 0
        assert "nothing to do" in (out + err).lower()

    def test_help_lists_sources_and_relineage(self):
        rc, out, err = run_cli("refit", "--help")
        combined = out + err
        assert rc == 0
        assert "--sources" in combined
        assert "--relineage" in combined

    def test_sources_and_relineage_are_mutually_exclusive_exit_2(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = tmp_path / "targets" / "MyProject"
        (target / "blueprint").mkdir(parents=True)
        rc, out, err = run_cli("refit", "MyProject", "--sources", "--relineage")
        assert rc == 2
        assert "mutually exclusive" in (out + err).lower()

    def test_relineage_upgrades_a_target_without_a_repository(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = tmp_path / "targets" / "MyProject"
        (target / "blueprint" / "sources").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: MyProject\nstate: approved\n", encoding="utf-8"
        )
        rc, out, err = run_cli("refit", "MyProject", "--relineage")
        assert rc == 0, err
        assert (target / ".git").is_dir()
        assert "Target - setup project workspace git store" in out
        assert "Target - committed project workspace git store" in out

    def test_sources_with_no_pending_versions_exits_0(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
        target = tmp_path / "targets" / "MyProject"
        (target / "blueprint" / "sources").mkdir(parents=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: MyProject\nstate: approved\n", encoding="utf-8"
        )
        rc, out, err = run_cli("refit", "MyProject", "--sources")
        assert rc == 0
        assert "no pending source versions" in (out + err).lower()


class TestDocumentAssemble:
    """drydock document assemble renders Target DOC files."""

    @staticmethod
    def _make_target(tmp_target_root, build_root, name: str = "MyTarget"):
        target = tmp_target_root / name
        target.mkdir(parents=True)
        docs = build_root / name / "docs"
        docs.mkdir(parents=True)
        (target / "METADATA.md").write_text(
            "name: MyTarget\ndisplay_name: My Target\nshort_description: Test docs\n",
            encoding="utf-8",
        )
        (target / "blueprint").mkdir(parents=True, exist_ok=True)
        (target / "MANIFEST.md").write_text(
            "# MANIFEST: MyTarget\nstate: approved\n", encoding="utf-8"
        )
        (docs / "DOC-OVERVIEW.md").write_text("# Overview\n\nHello.\n", encoding="utf-8")
        return target

    def test_document_assemble_builds_output(
        self, tmp_target_root, tmp_path, isolated_config, monkeypatch
    ):
        build_root = tmp_path / "build"
        self._make_target(tmp_target_root, build_root)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))

        rc, out, err = run_cli("document", "assemble", "MyTarget")

        assert rc == 0
        assert (build_root / "MyTarget" / "docs" / "index.html").exists()
        assert "Assembled documentation" in out

    def test_document_assemble_no_args_exits_usage(self):
        rc, out, err = run_cli("document", "assemble")
        assert rc == 2
        assert "Usage: drydock document assemble <Target>" in err

    def test_document_assemble_is_not_a_stub(
        self, tmp_target_root, tmp_path, isolated_config, monkeypatch
    ):
        build_root = tmp_path / "build"
        self._make_target(tmp_target_root, build_root)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))
        rc, out, err = run_cli("document", "assemble", "MyTarget")
        combined = out + err
        assert "not implemented" not in combined.lower()


class TestPublish:
    """drydock publish renders frontmatter Markdown to HTML."""

    SOURCE = """---
title: Published
eyebrow: Paper
subtitle: Deterministic output
author: Ed
studio: Studio
year: 2026
---

## Body

Published content.
"""

    def test_publish_writes_html(self, tmp_path):
        source = tmp_path / "paper.md"
        output = tmp_path / "site" / "paper.html"
        source.write_text(self.SOURCE, encoding="utf-8")

        rc, out, err = run_cli("publish", str(source), "--output", str(output), "--theme", "slate")

        assert rc == 0
        assert output.exists()
        assert "Published HTML:" in out
        assert "Theme: slate" in out
        assert 'body class="theme-slate"' in output.read_text(encoding="utf-8")

    def test_publish_flatten_writes_section_pages(self, tmp_path):
        source = tmp_path / "paper.md"
        output = tmp_path / "site" / "paper.html"
        source.write_text(self.SOURCE, encoding="utf-8")

        rc, out, err = run_cli("publish", str(source), "--output", str(output), "--flatten")

        section = tmp_path / "site" / "paper_sections" / "body.html"
        assert rc == 0
        assert output.exists()
        assert section.exists()
        assert "Published HTML:" in out
        assert 'location.replace("paper_sections/introduction.html")' in output.read_text(
            encoding="utf-8"
        )
        assert "# Body" in section.read_text(encoding="utf-8")

    def test_publish_requires_output(self, tmp_path):
        source = tmp_path / "paper.md"
        source.write_text(self.SOURCE, encoding="utf-8")

        rc, out, err = run_cli("publish", str(source))

        assert rc == 2
        assert "the following arguments are required: --output" in err

    def test_publish_missing_source_never_calls_llm_diagnosis(self, tmp_path, monkeypatch):
        def fail_if_called(*args, **kwargs):
            raise AssertionError("deterministic FileNotFoundError reached the LLM")

        monkeypatch.setattr("drydock.llm.run_prompt", fail_if_called)
        missing = tmp_path / "missing.md"

        rc, out, err = run_cli("publish", str(missing), "--output", str(tmp_path / "output.html"))

        assert rc == 1
        assert out.startswith("Drydock ")
        assert "FileNotFoundError" in err
        assert str(missing) in err
        assert "A MAJOR ERROR HAS OCCURRED" not in err
        assert "is diagnosing" not in err


class TestRunQuarterdeck:
    """drydock run quarterdeck dispatches to quarterdeck_run.run_quarterdeck."""

    @staticmethod
    def _make_target(tmp_target_root, name: str = "MyTarget"):
        qd = tmp_target_root / name / "QuarterDeck"
        qd.mkdir(parents=True)
        # State-only console marker; the runtime is served from the package.
        (qd / "console.yaml").write_text("project: x\n", encoding="utf-8")
        return tmp_target_root / name

    def test_run_quarterdeck_dispatches(self, tmp_target_root, isolated_config, monkeypatch):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        self._make_target(tmp_target_root)

        calls: list = []

        def fake_run(target_dir, *, port, host):
            calls.append({"target_dir": target_dir, "port": port, "host": host})
            return SimpleNamespace(exit_code=0)

        monkeypatch.setattr("drydock.quarterdeck_run.run_quarterdeck", fake_run)
        rc, out, err = run_cli("run", "quarterdeck", "MyTarget")
        assert rc == 0
        assert calls
        assert calls[0]["port"] == 8080
        assert calls[0]["host"] == "127.0.0.1"

    def test_run_shows_help_instead_of_stub(self):
        rc, out, err = run_cli("run")

        assert rc == 0
        assert "quarterdeck" in out
        assert "not implemented" not in out + err

    def test_run_quarterdeck_without_target_uses_sole_target(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        target = self._make_target(tmp_target_root, "OnlyTarget")
        calls: list = []

        def fake_run(target_dir, *, port, host):
            calls.append({"target_dir": target_dir, "port": port, "host": host})
            return SimpleNamespace(exit_code=0)

        monkeypatch.setattr("drydock.quarterdeck_run.run_quarterdeck", fake_run)
        rc, out, err = run_cli("run", "quarterdeck")

        assert rc == 0
        assert calls == [{"target_dir": target, "port": 8080, "host": "127.0.0.1"}]
        assert str(target) in out

    def test_run_quarterdeck_without_target_uses_most_recently_updated_target(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        older = self._make_target(tmp_target_root, "Older")
        latest = self._make_target(tmp_target_root, "Latest")
        nested_artifact = latest / "blueprint" / "FEATURE.md"
        nested_artifact.parent.mkdir()
        nested_artifact.write_text("latest\n", encoding="utf-8")
        old_ns = 1_000_000_000
        new_ns = 2_000_000_000
        for path in [older, *older.rglob("*"), latest, *latest.rglob("*")]:
            os.utime(path, ns=(old_ns, old_ns), follow_symlinks=False)
        os.utime(nested_artifact, ns=(new_ns, new_ns))
        calls: list[Path] = []

        def fake_run(target_dir, *, port, host):
            calls.append(target_dir)
            return SimpleNamespace(exit_code=0)

        monkeypatch.setattr("drydock.quarterdeck_run.run_quarterdeck", fake_run)
        rc, out, err = run_cli("run", "quarterdeck")

        assert rc == 0
        assert err == ""
        assert calls == [latest]
        assert str(latest) in out

    def test_run_quarterdeck_without_target_reports_empty_workspace(
        self, tmp_target_root, isolated_config
    ):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))

        rc, out, err = run_cli("run", "quarterdeck")

        assert rc == 1
        assert "No initialized Target found" in err

    def test_run_quarterdeck_custom_port(self, tmp_target_root, isolated_config, monkeypatch):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        self._make_target(tmp_target_root)

        calls: list = []

        def fake_run(target_dir, *, port, host):
            calls.append(port)
            return SimpleNamespace(exit_code=0)

        monkeypatch.setattr("drydock.quarterdeck_run.run_quarterdeck", fake_run)
        rc, out, err = run_cli("run", "quarterdeck", "MyTarget", "--port", "9090")
        assert rc == 0
        assert calls[0] == 9090

    def test_run_quarterdeck_custom_host(self, tmp_target_root, isolated_config, monkeypatch):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        self._make_target(tmp_target_root)

        calls: list = []

        def fake_run(target_dir, *, port, host):
            calls.append(host)
            return SimpleNamespace(exit_code=0)

        monkeypatch.setattr("drydock.quarterdeck_run.run_quarterdeck", fake_run)
        rc, out, err = run_cli("run", "quarterdeck", "MyTarget", "--host", "0.0.0.0")
        assert rc == 0
        assert calls[0] == "0.0.0.0"

    def test_run_quarterdeck_missing_app_py_raises(self, tmp_target_root, isolated_config):
        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        (tmp_target_root / "Empty").mkdir()
        rc, out, err = run_cli("run", "quarterdeck", "Empty")
        assert rc == 1
        assert "error" in err.lower()

    def test_run_quarterdeck_config_port_used(self, tmp_target_root, isolated_config, monkeypatch):
        from types import SimpleNamespace

        run_cli("config", "set", "drydock_workspace", str(tmp_target_root.parent))
        run_cli("config", "set", "quarterdeck_port", "7777")
        self._make_target(tmp_target_root)

        calls: list = []

        def fake_run(target_dir, *, port, host):
            calls.append(port)
            return SimpleNamespace(exit_code=0)

        monkeypatch.setattr("drydock.quarterdeck_run.run_quarterdeck", fake_run)
        rc, out, err = run_cli("run", "quarterdeck", "MyTarget")
        assert rc == 0
        assert calls[0] == 7777


APPROVED_PLAN_STATUS = """\
# MANIFEST: TestTarget
state: approved
updated: 2026-01-01T00:00:00
plan_hash: abc123

## story 1: Core feature
id: core-feature
state: pending

## story 2: Done feature
id: done-feature
state: closed/verified
"""


class TestStatus:
    def _setup(self, tmp_target_root, monkeypatch):
        from drydock.init_specification import init_specification

        target_dir = tmp_target_root / "TestTarget"
        init_specification("TestTarget", target_dir)
        (target_dir / "MANIFEST.md").write_text(APPROVED_PLAN_STATUS, encoding="utf-8")
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

    def test_status_blueprint_target_reports_plan_state(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "TestTarget")
        assert rc == 0, err
        assert "TestTarget" in out
        assert "Phase" in out
        assert "Implement" in out
        assert "core-feature" in out

    def test_status_blueprint_reports_validation_summary(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "TestTarget")
        assert rc == 0, err
        assert "TestTarget" in out
        assert "Blueprint" in out
        assert "0 errors" in out
        assert "Next step" in out

    def test_status_uses_compact_grammar_for_analysis_and_review(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        target_dir = tmp_target_root / "TestTarget"
        (target_dir / "ANALYSIS.md").write_text(
            "Quality: Questions\n  Stories: 11\n  Questions: 1\n  Blockers: 0\n",
            encoding="utf-8",
        )
        questionnaire_dir = target_dir / "QuarterDeck" / "questionnaires"
        questionnaire_dir.mkdir(parents=True)
        (questionnaire_dir / "discovery-one.json").write_text("{}\n", encoding="utf-8")

        rc, out, err = run_cli("status", "TestTarget")

        assert rc == 0, err
        assert "Questions · 11 stories · 1 question · 0 blockers" in out
        assert "No blockers · 1 questionnaire" in out
        assert "1 questions" not in out
        assert "1 questionnaires" not in out

    def test_status_reports_open_blocking_decisions_in_the_review_line(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        """jq run 20260816.160223 printed ``No blockers`` with a blocking decision open.

        The decision gates its own story at build; the Review line has to say so. Phase routing is
        deliberately untouched — ``BLOCKERS.md`` is absent, so the target stays in Implement rather
        than being sent back to Arrange to answer a file that does not exist.
        """
        import json

        self._setup(tmp_target_root, monkeypatch)
        target_dir = tmp_target_root / "TestTarget"
        (target_dir / "DECISIONS.json").write_text(
            json.dumps([
                {
                    "id": "acceptance-FEATURE-A.md-a-malformed",
                    "type": "text",
                    "severity": "blocking",
                    "origin": "plan",
                    "blueprint": "FEATURE-A.md",
                    "story": "core-feature",
                    "status": "open",
                    "archived": False,
                    "title": "Acceptance criterion a cannot execute",
                    "description": "criterion is not valid Python",
                    "options": [],
                    "system_choice": "",
                },
                {
                    "id": "plan-001",
                    "type": "choice",
                    "severity": "material",
                    "origin": "plan",
                    "blueprint": "ARCHITECTURE.md",
                    "story": None,
                    "status": "recommended",
                    "archived": False,
                    "title": "Numeric representation",
                    "description": "",
                    "options": [],
                    "system_choice": "decimal",
                },
            ]),
            encoding="utf-8",
        )

        rc, out, err = run_cli("status", "TestTarget")

        assert rc == 0, err
        assert "1 open blocking decision" in out
        assert "No blockers" not in out
        assert "Implement" in out
        assert "Edit BLOCKERS.md" not in out

    def test_status_ignores_answered_and_archived_blocking_decisions(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        import json

        self._setup(tmp_target_root, monkeypatch)
        target_dir = tmp_target_root / "TestTarget"
        questionnaire_dir = target_dir / "QuarterDeck" / "questionnaires"
        questionnaire_dir.mkdir(parents=True)
        (questionnaire_dir / "discovery-one.json").write_text("{}\n", encoding="utf-8")
        (target_dir / "DECISIONS.json").write_text(
            json.dumps([
                {
                    "id": "answered",
                    "type": "text",
                    "severity": "blocking",
                    "origin": "plan",
                    "blueprint": "FEATURE-A.md",
                    "story": "core-feature",
                    "status": "answered",
                    "archived": False,
                    "title": "Answered",
                    "description": "",
                    "options": [],
                    "system_choice": "",
                },
                {
                    "id": "archived",
                    "type": "text",
                    "severity": "blocking",
                    "origin": "plan",
                    "blueprint": "FEATURE-A.md",
                    "story": "core-feature",
                    "status": "open",
                    "archived": True,
                    "title": "Archived",
                    "description": "",
                    "options": [],
                    "system_choice": "",
                },
            ]),
            encoding="utf-8",
        )

        rc, out, err = run_cli("status", "TestTarget")

        assert rc == 0, err
        assert "No blockers · 1 questionnaire" in out

    def test_status_target_without_manifest_reports_preplan_state(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        from drydock.init_specification import init_specification

        target_dir = tmp_target_root / "TestTarget"
        init_specification("TestTarget", target_dir)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))

        rc, out, err = run_cli("status", "TestTarget")

        assert rc == 0, err
        assert "Arrange" in out
        assert "Plan" in out
        assert "not created" in out
        assert "drydock plan TestTarget" in out

    def test_status_no_args_no_activity_exits_zero(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        monkeypatch.chdir(tmp_target_root)
        rc, out, err = run_cli("status")
        assert rc == 0

    def test_status_no_args_configured_workspace_without_targets_recommends_init(
        self, tmp_path, isolated_config, monkeypatch
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        run_cli("config", "set", "drydock_workspace", str(workspace))
        monkeypatch.chdir(workspace)

        rc, out, err = run_cli("status")

        assert rc == 0, err
        assert "drydock init <Target>" in out
        assert "config set drydock_workspace" not in out

    def test_status_no_args_shows_initialized_target(self, tmp_path, isolated_config, monkeypatch):
        from drydock.init_target import init_target

        workspace = tmp_path / "ws"
        workspace.mkdir()
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(workspace))
        init_target("MyProject", workspace / "targets")

        rc, out, err = run_cli("status")
        assert rc == 0, err
        assert "MyProject" in out
        assert "Phase:" in out
        assert "Next Step:" in out

    def test_status_no_args_formats_run_history_with_month_day(
        self, tmp_path, isolated_config, monkeypatch
    ):
        from drydock.config import append_command_history
        from drydock.init_target import init_target

        workspace = tmp_path / "ws"
        workspace.mkdir()
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(workspace))
        init_target("MyProject", workspace / "targets")
        append_command_history(
            workspace, "drydock analyze MyProject", target="MyProject", return_code=0
        )

        rc, out, err = run_cli("status")

        assert rc == 0, err
        assert re.search(r"\b\d{1,2}-\d{1,2}:\s+[✅✓]\s+drydock analyze MyProject", out)
        assert "drydock analyze MyProject" in out

    def test_status_no_args_formats_failed_run_history_with_month_day(
        self, tmp_path, isolated_config, monkeypatch
    ):
        from drydock.config import append_command_history
        from drydock.init_target import init_target

        workspace = tmp_path / "ws"
        workspace.mkdir()
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(workspace))
        init_target("MyProject", workspace / "targets")
        append_command_history(
            workspace, "drydock analyze MyProject", target="MyProject", return_code=1
        )

        rc, out, err = run_cli("status")

        assert rc == 0, err
        assert re.search(r"\b\d{1,2}-\d{1,2}:\s+[❌✗]\s+drydock analyze MyProject", out)

    def test_activity_recorded_after_status_command(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        run_cli("status", "TestTarget")

        from drydock.config import get_last_activity

        activity = get_last_activity()
        assert activity["blueprint"] == "TestTarget"
        assert activity["target"] == "TestTarget"
        assert activity["command"] == "status"
        assert activity["time"] != ""

    def test_status_too_many_args_exits_2(self, tmp_target_root, isolated_config, monkeypatch):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "A", "B", "C")
        assert rc == 2

    def test_status_check_exits_1_while_work_remains(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "TestTarget", "--check")
        assert rc == 1, err
        assert out.startswith("INCOMPLETE: TestTarget")

    def test_status_check_exits_0_when_all_blocks_verified(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        manifest = tmp_target_root / "TestTarget" / "MANIFEST.md"
        manifest.write_text(
            APPROVED_PLAN_STATUS.replace("state: pending", "state: closed/verified").replace(
                "state: implemented", "state: closed/verified"
            ),
            encoding="utf-8",
        )
        rc, out, err = run_cli("status", "TestTarget", "--check")
        assert rc == 0, err
        assert out.startswith("COMPLETE: TestTarget")

    def test_status_check_flag_before_target(self, tmp_target_root, isolated_config, monkeypatch):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "--check", "TestTarget")
        assert rc == 1, err
        assert out.startswith("INCOMPLETE: TestTarget")

    def test_status_never_creates_or_commits_the_target_git_store(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        """A query must not mutate what it reports on.

        Initializing and checkpointing the store also prints two banner lines onto stdout, which
        is the machine-readable contract ``--check`` and ``--ready`` hand to a calling script.
        """
        self._setup(tmp_target_root, monkeypatch)
        target = tmp_target_root / "TestTarget"

        for argv in (("status", "TestTarget"), ("status", "TestTarget", "--check")):
            run_cli(*argv)
            assert not (target / ".git").exists(), argv

    def test_status_check_unknown_target_exits_2(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "NoSuchTarget", "--check")
        assert rc == 2

    def test_status_check_without_target_exits_2(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "--check")
        assert rc == 2

    def test_status_check_unplanned_target_exits_2_and_aborts_loop(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        from drydock.init_specification import init_specification

        target_dir = tmp_target_root / "Unplanned"
        init_specification("Unplanned", target_dir)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        rc, out, err = run_cli("status", "Unplanned", "--check")
        assert rc == 2
        assert "BLOCKED: Unplanned" in out
        assert "drydock plan" in out
        assert err == ""

    def test_status_ready_exits_0_while_buildable(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "TestTarget", "--ready")
        assert rc == 0, err
        assert "READY TO BUILD: TestTarget" in out
        assert __copyright__ not in out
        assert err == ""

    def test_status_ready_exits_1_when_complete(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        manifest = tmp_target_root / "TestTarget" / "MANIFEST.md"
        manifest.write_text(
            APPROVED_PLAN_STATUS.replace("state: pending", "state: closed/verified").replace(
                "state: implemented", "state: closed/verified"
            ),
            encoding="utf-8",
        )
        rc, out, err = run_cli("status", "TestTarget", "--ready")
        assert rc == 1
        assert "BUILD COMPLETE: TestTarget" in out
        assert err == ""

    def test_status_ready_exits_1_when_incomplete_but_frontier_is_empty(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        manifest = tmp_target_root / "TestTarget" / "MANIFEST.md"
        manifest.write_text(
            APPROVED_PLAN_STATUS.replace("state: pending", "state: closed/implemented"),
            encoding="utf-8",
        )

        check_rc, _, _ = run_cli("status", "TestTarget", "--check")
        ready_rc, out, err = run_cli("status", "TestTarget", "--ready")

        assert check_rc == 1
        assert ready_rc == 1
        assert err == ""
        assert "NOT READY: TestTarget  (no buildable frontier)" in out

    def test_status_ready_exits_1_when_blocked(self, tmp_target_root, isolated_config, monkeypatch):
        from drydock.init_specification import init_specification

        target_dir = tmp_target_root / "Unplanned"
        init_specification("Unplanned", target_dir)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        rc, out, err = run_cli("status", "Unplanned", "--ready")
        assert rc == 1
        assert "NOT READY: Unplanned" in out
        assert err == ""

    def test_status_check_and_ready_mutually_exclusive(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "TestTarget", "--check", "--ready")
        assert rc == 2


def test_render_recorded_error_keeps_indented_code_lines_intact():
    # An acceptance failure chain is structure, not prose. Reflowing it to 72 columns split the
    # failing assertion across two lines mid-regex, which is precisely the line the reader needs.
    from drydock.cli import _render_recorded_error
    from drydock.errors import ErrorRecord

    assertion = (
        '        assertion: assert re.search(r"\\b0\\s+errors?\\b", '
        "result.stdout, re.IGNORECASE) → AssertionError"
    )
    record = ErrorRecord(
        command="build",
        phase="post-output validation",
        timestamp="t",
        classification="programmatic acceptance failed: complete-conformance",
        detail='Block "Block 6" [block-6] failed its acceptance criteria.\n' + assertion,
        recovery="Use: drydock build toml --ungate",
    )
    out = _render_recorded_error(record)

    assert assertion.strip() in out
    assert any(line.rstrip().endswith("→ AssertionError") for line in out.splitlines())


def test_render_recorded_error_shows_diagnostic_and_recovery():
    from drydock.cli import _render_recorded_error
    from drydock.errors import ErrorRecord

    detail = (
        "Plan integrity check failed: architecture: 0 Programmatic Acceptance "
        "assertion(s) across its implemented spec(s), which declare a programmatic "
        "surface; author several concrete Python assertions or justify None inline."
    )
    record = ErrorRecord(
        command="plan",
        phase="post-output validation",
        timestamp="t",
        classification="plan output validation failed",
        detail=detail,
        recovery="Correct the plan input, then run: drydock plan commonmark",
    )
    out = _render_recorded_error(record)

    # The diagnostic itself is on screen, not just the filename.
    assert "Plan integrity check failed" in out
    assert "author several concrete Python assertions" in out
    assert "POST-LLM FAILURE  ·  plan  ·  plan output validation failed" in out
    assert "Recovery" in out
    assert "Correct the plan input, then run: drydock plan commonmark" in out
    # The record's own path and a QuarterDeck pointer are noise: errors are not approved there.
    assert "ERRORS.md" not in out
    assert "quarterdeck" not in out
    # The long diagnostic is wrapped: its start and end land on different lines.
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if "Plan integrity check failed" in line)
    end = next(i for i, line in enumerate(lines) if "justify None inline" in line)
    assert end > start
    # Every line except the standalone file-path/command lines (indented 4 spaces) fits the border.
    assert all(len(line) <= 72 for line in lines if not line.startswith("    "))


def test_render_plan_deferred_is_prominent_and_actionable(tmp_path):
    from drydock.cli import _render_plan_deferred
    from drydock.errors import ErrorRecord
    from drydock.planning_session import PlanDeferredResult

    record = ErrorRecord(
        command="plan",
        phase="product decision",
        timestamp="t",
        classification="plan requires a product decision",
        detail=(
            "Confirmed conflict:\nReason:\n- sources/a.md clause A conflicts with "
            "COMPASS.md clause B in the runtime scope."
        ),
        recovery="Correct clause A or select clause B.",
        execution_id="exec-123",
        challenge_execution_id="exec-456",
        state="Deferred",
    )
    result = PlanDeferredResult(
        target_dir=tmp_path,
        error_record=record,
        errors_path=tmp_path / "ERRORS.md",
        detail=record.detail,
        initial_execution_id="exec-123",
        challenge_execution_id="exec-456",
    )

    out = _render_plan_deferred(result, target="Marina")

    assert "PLAN DEFERRED" in out
    assert "plan requires a product decision" in out
    assert "sources/a.md clause A" in out
    assert "Correct clause A or select clause B." in out
    assert "ERRORS.md:" in out
    assert "No model-generated" in out
    assert "drydock run quarterdeck Marina" in out
    assert "drydock plan Marina" in out
    assert "exec-123" in out
    assert "exec-456" in out


def test_render_plan_challenge_failure_includes_original_failure_and_recovery():
    from drydock.cli import _render_recorded_error
    from drydock.errors import ErrorRecord

    record = ErrorRecord(
        command="plan",
        phase="post-output validation",
        timestamp="t",
        classification="plan conflict challenge failed",
        detail=(
            "Initial declaration:\nReason:\n- sources/a.md conflicts with COMPASS.md.\n\n"
            "Challenge failure:\nprovider unavailable"
        ),
        recovery="Inspect evidence, then run: drydock plan Marina",
        execution_id="exec-123",
        challenge_execution_id="exec-456",
    )

    out = _render_recorded_error(record, target="Marina")

    assert "PLAN FAILED" in out
    assert "sources/a.md conflicts with COMPASS.md" in out
    assert "provider unavailable" in out
    assert "ERRORS.md:" in out
    assert "drydock run quarterdeck Marina" in out
    assert "drydock plan Marina" in out
    assert "exec-123" in out
    assert "exec-456" in out


def test_render_recorded_error_omits_recovery_when_empty():
    from drydock.cli import _render_recorded_error
    from drydock.errors import ErrorRecord

    record = ErrorRecord(
        command="analyze",
        phase="post-output validation",
        timestamp="t",
        classification="analysis failed",
        detail="Something went wrong.",
        recovery="",
    )
    out = _render_recorded_error(record)
    assert "Recovery" not in out
    assert "Something went wrong." in out


class TestStandoffDiagnosis:
    """The CLI's opaque-failure hook: banner, diagnosis, persistence, and suppression."""

    @staticmethod
    def _args(target: str, **overrides):
        import argparse

        values = {
            "Target": target,
            "no_diagnose": False,
            "llm_provider": "claude",
            "model": "sonnet",
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    @staticmethod
    def _runner(text="CAUSE: the agent wrote no files.\nDO: rerun drydock build widgets"):
        from dataclasses import dataclass

        @dataclass
        class FakeRun:
            ok: bool = True
            text: str = ""
            execution_id: str = "exec-fake"

        def run(prompt, working_directory, **kwargs):
            run.seen.append(prompt)
            run.kwargs.append(kwargs)
            return FakeRun(text=text)

        run.seen = []  # type: ignore[attr-defined]
        run.kwargs = []  # type: ignore[attr-defined]
        return run

    @pytest.fixture()
    def target_dir(self, tmp_workspace, tmp_target_root, isolated_config, monkeypatch):
        from drydock.diagnose import reset_diagnosis_guard
        from drydock.errors import write_error_record

        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        reset_diagnosis_guard()
        tgt = tmp_target_root / "widgets"
        tgt.mkdir(parents=True)
        write_error_record(
            tgt,
            command="build",
            phase="LLM execution",
            classification="no build files written",
            detail="The agent finished but produced nothing.",
            recovery="Rerun the block.",
        )
        yield tgt
        reset_diagnosis_guard()

    def test_opaque_failure_prints_banner_and_persists_diagnosis(self, target_dir, capsys):
        from drydock.cli import _standoff_diagnosis
        from drydock.errors import read_error_record, write_error_record

        record = write_error_record(
            target_dir,
            command="build",
            phase="LLM execution",
            classification="no build files written",
            detail="The agent finished but produced nothing.",
            recovery="Rerun the block.",
        )
        runner = self._runner()
        _standoff_diagnosis(
            self._args("widgets"),
            ["build", "widgets"],
            record=record,
            runner=runner,
        )

        err = capsys.readouterr().err
        assert "A MAJOR ERROR HAS OCCURRED" in err
        assert "claude/sonnet is diagnosing" in err
        assert "CAUSE: the agent wrote no files." in err
        assert runner.kwargs[0]["log_dir"] == target_dir.parents[1] / "logs"

        persisted = read_error_record(target_dir)
        assert persisted is not None
        assert "DO: rerun drydock build widgets" in persisted.diagnosis
        assert persisted.recovery == "Rerun the block."

    def test_remainder_command_diagnoses_against_its_target_directory(self, target_dir, capsys):
        """``drydock build`` carries its Target in the operand list, not a ``Target`` attribute.

        The diagnosis must still run against that Target's workspace rather than falling back
        to the working directory, which holds none of the Target's evidence.
        """
        import argparse

        from drydock.cli import _standoff_diagnosis
        from drydock.errors import read_error_record, write_error_record

        record = write_error_record(
            target_dir,
            command="build",
            phase="LLM execution",
            classification="no build files written",
            detail="The agent finished but produced nothing.",
            recovery="Rerun the block.",
        )
        args = argparse.Namespace(
            command="build",
            args=["widgets", "--reset"],
            no_diagnose=False,
            llm_provider="claude",
            model="sonnet",
        )
        runner = self._runner()
        _standoff_diagnosis(args, ["build", "widgets", "--reset"], record=record, runner=runner)

        assert runner.kwargs, "the diagnosis never ran"
        assert runner.kwargs[0]["log_dir"] == target_dir.parents[1] / "logs"
        persisted = read_error_record(target_dir)
        assert persisted is not None
        assert "DO: rerun drydock build widgets" in persisted.diagnosis

    def test_diagnosis_also_appended_to_evidence_file(self, target_dir, capsys):
        from drydock.cli import _standoff_diagnosis
        from drydock.errors import write_error_record

        evidence = target_dir / "evidence" / "block.md"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("# Evidence\n\n## Failure\n- summary: broke\n", encoding="utf-8")
        record = write_error_record(
            target_dir,
            command="build",
            phase="build step",
            classification="agent-reported failure: conformance not met",
            detail="The build diverged from the spec.",
            recovery="Rerun the block.",
            evidence=evidence,
        )
        _standoff_diagnosis(
            self._args("widgets"), ["build", "widgets"], record=record, runner=self._runner()
        )

        text = evidence.read_text(encoding="utf-8")
        assert "## Diagnosis" in text
        assert "DO: rerun drydock build widgets" in text
        # Idempotent: a second diagnosis replaces rather than stacks the section.
        from drydock.diagnose import reset_diagnosis_guard

        reset_diagnosis_guard()
        _standoff_diagnosis(
            self._args("widgets"), ["build", "widgets"], record=record, runner=self._runner()
        )
        assert evidence.read_text(encoding="utf-8").count("## Diagnosis") == 1

    def test_programmatic_acceptance_failure_is_not_diagnosed(self, target_dir, capsys):
        from drydock.cli import _standoff_diagnosis
        from drydock.errors import write_error_record

        evidence = target_dir / "evidence" / "block.md"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("# Evidence\n", encoding="utf-8")
        record = write_error_record(
            target_dir,
            command="build",
            phase="build step",
            classification="programmatic acceptance failed: check-1",
            detail="An acceptance assertion failed.",
            recovery="Fix the code.",
            evidence=evidence,
        )
        runner = self._runner()
        _standoff_diagnosis(
            self._args("widgets"), ["build", "widgets"], record=record, runner=runner
        )

        assert runner.seen == []
        assert "## Diagnosis" not in evidence.read_text(encoding="utf-8")

    def test_no_diagnose_flag_suppresses_the_call(self, target_dir, capsys):
        from drydock.cli import _standoff_diagnosis
        from drydock.errors import read_error_record

        runner = self._runner()
        _standoff_diagnosis(
            self._args("widgets", no_diagnose=True),
            ["build", "widgets"],
            record=read_error_record(target_dir),
            runner=runner,
        )

        assert runner.seen == []
        assert "A MAJOR ERROR HAS OCCURRED" not in capsys.readouterr().err

    def test_config_disables_the_call(self, target_dir, capsys, monkeypatch):
        from drydock.cli import _standoff_diagnosis
        from drydock.errors import read_error_record

        monkeypatch.setenv("DRYDOCK_DIAGNOSE", "false")
        runner = self._runner()
        _standoff_diagnosis(
            self._args("widgets"),
            ["build", "widgets"],
            record=read_error_record(target_dir),
            runner=runner,
        )

        assert runner.seen == []
        assert "A MAJOR ERROR HAS OCCURRED" not in capsys.readouterr().err

    def test_blocked_classification_is_not_diagnosed(self, target_dir, capsys):
        from drydock.cli import _standoff_diagnosis
        from drydock.errors import write_error_record

        record = write_error_record(
            target_dir,
            command="build",
            phase="build step",
            classification="dependency legitimacy gate failed: 2 issue(s)",
            detail="Two packages are unpublished.",
            recovery="Remove them.",
        )
        runner = self._runner()
        _standoff_diagnosis(
            self._args("widgets"), ["build", "widgets"], record=record, runner=runner
        )

        assert runner.seen == []
        assert "A MAJOR ERROR HAS OCCURRED" not in capsys.readouterr().err

    def test_usage_error_still_exits_2_without_a_banner(self):
        rc, _out, err = run_cli("build")
        assert rc == 2
        assert "A MAJOR ERROR HAS OCCURRED" not in err


def test_failure_renderer_explains_a_run_that_stopped_below_its_call_budget():
    final = AcceptanceRunResult(
        check_id="verification-scoped-number",
        source="FEATURE-Verification-Scoped.md",
        intent="The supplied harness supports example selection.",
        passed=False,
        return_code=1,
        stdout="",
        stderr="AssertionError\n",
    )
    step = BuildStepResult(
        block_id="filter-interface",
        name="Filter Interface",
        block_type="story",
        status="failed",
        state="closed/failed",
        story_points=1,
        error="programmatic acceptance failed: verification-scoped-number",
        owned_acceptance=(final,),
        stop_reason="acceptance criterion reported defective",
        calls_used=1,
        calls_budget=4,
    )

    rendered = _render_build_failures("commonmark", [step], hint="continue", story_recovery=())

    assert "stopped early: 1 of 4 calls · acceptance criterion reported defective" in rendered
    assert "repair the assertion in the Blueprint specification" in rendered


def test_failure_renderer_omits_the_stop_line_when_the_budget_was_spent():
    step = BuildStepResult(
        block_id="inlines",
        name="Inline Parsing",
        block_type="story",
        status="failed",
        state="closed/failed",
        story_points=1,
        error="programmatic acceptance failed: inline-suite",
        failure_detail="Inline suite remains red.",
    )

    rendered = _render_build_failures("commonmark", [step], hint="continue", story_recovery=())

    assert "stopped early" not in rendered


class TestBuildScoreRendering:
    """The post-build report is formatting over a prepared report; no logs are read here."""

    class _Attempt:
        def __init__(self, index, status, passed, total, cases=None, stop="", reason=""):
            self.index, self.status = index, status
            self.passed_checks, self.total_checks = passed, total
            self.passed_cases, self.total_cases = cases, cases
            self.stop_reason = stop
            self.reason = reason
            self.total_input, self.cached_input, self.fresh_input = 1000, 900, 100
            self.output, self.elapsed_ms = 50, 61000

        @property
        def label(self):
            return "initial build" if self.index == 0 else f"repair {self.index}"

        @property
        def cache_hit_rate(self):
            return 0.9

    class _Block:
        def __init__(self, name, block_id, state, passed, total, attempts, failing=()):
            self.name, self.block_id, self.state = name, block_id, state
            self.passed_checks, self.total_checks = passed, total
            self.attempts = tuple(attempts)
            self.failed_check_ids = failing
            self.total_input, self.cached_input, self.fresh_input = 1000, 900, 100
            self.output, self.elapsed_ms = 50, 61000

        @property
        def verified(self):
            return self.state == "closed/verified"

        @property
        def calls(self):
            return len(self.attempts)

        @property
        def repaired(self):
            return self.calls > 1

        @property
        def cache_hit_rate(self):
            return 0.9

        @property
        def stop_reason(self):
            return self.attempts[-1].stop_reason if self.attempts else ""

        def outcome_of(self, attempt):
            if not self.attempts or attempt.index != self.attempts[-1].index:
                return "incomplete"
            return "built" if self.verified else "failed"

    class _Report:
        def __init__(self, blocks, missing=()):
            self.target = "commonmark"
            self.evidence_dir = "/t/evidence"
            self.records_path = "/t/logs/llm.jsonl"
            self.blocks = tuple(blocks)
            self.missing_usage = missing
            self.total_input, self.cached_input, self.fresh_input = 1000, 900, 100
            self.output, self.elapsed_ms = 50, 61000
            self.passed_checks, self.total_checks = 3, 3
            self.models = ("gpt-5.6-luna",)

        @property
        def calls(self):
            return sum(b.calls for b in self.blocks)

        @property
        def cache_hit_rate(self):
            return 0.9

        @property
        def repaired_blocks(self):
            return tuple(b for b in self.blocks if b.repaired)

        @property
        def failed_blocks(self):
            return tuple(b for b in self.blocks if not b.verified)

        @property
        def first_call_blocks(self):
            return sum(1 for b in self.blocks if b.verified and not b.repaired)

    def test_clean_build_renders_a_table_without_a_repairs_section(self):
        from drydock.cli import _render_build_score

        block = self._Block(
            "Block Parsing",
            "feature-block-parsing",
            "closed/verified",
            3,
            3,
            [self._Attempt(0, "built", 3, 3)],
        )
        out = "\n".join(_render_build_score(self._Report([block])))

        assert "Build report: commonmark" in out
        assert "✓ Block Parsing" in out
        assert "96.7%" not in out and "90.0%" in out
        assert "1 on first call" in out
        assert "Repairs" not in out
        assert "Not verified" not in out

    def test_a_repair_is_broken_out_pass_by_pass(self):
        from drydock.cli import _render_build_score

        block = self._Block(
            "Inline Parsing",
            "feature-inline-parsing",
            "closed/verified",
            2,
            2,
            [
                self._Attempt(0, "failed", 1, 2, cases=243),
                self._Attempt(1, "built", 2, 2, cases=375),
            ],
        )
        out = "\n".join(_render_build_score(self._Report([block])))

        assert "Repairs" in out
        # A pass that did not close a block that went on to verify is incomplete, not failed.
        assert "initial build  incomplete 1/2 AC · 243/243 cases" in out
        assert "repair 1       built      2/2 AC · 375/375 cases" in out

    def test_a_pass_that_met_every_criterion_and_still_reopened_names_why(self):
        from drydock.cli import _render_build_score

        block = self._Block(
            "Inline Parsing",
            "feature-inline-parsing",
            "closed/verified",
            2,
            2,
            [
                self._Attempt(0, "failed", 2, 2, reason="regression: inline-links"),
                self._Attempt(1, "built", 2, 2),
            ],
        )
        out = "\n".join(_render_build_score(self._Report([block])))

        # "failed · 2/2 AC" was a contradiction; the reason is what the reader needs.
        assert "initial build  incomplete 2/2 AC" in out
        assert "regression: inline-links" in out

    def test_a_failed_block_names_its_criteria_and_stop_reason(self):
        from drydock.cli import _render_build_score

        block = self._Block(
            "Filter Delivery",
            "feature-filter-delivery",
            "closed/failed",
            1,
            2,
            [self._Attempt(0, "failed", 1, 2, stop="acceptance criterion reported defective")],
            failing=("verification-scoped-number",),
        )
        out = "\n".join(_render_build_score(self._Report([block])))

        assert "✗ Filter Delivery" in out
        assert "Not verified" in out
        assert "failing AC: verification-scoped-number" in out
        assert "stopped: acceptance criterion reported defective" in out

    def test_missing_usage_is_disclosed_rather_than_read_as_zero_cost(self):
        from drydock.cli import _render_build_score

        block = self._Block(
            "Block Parsing",
            "feature-block-parsing",
            "closed/verified",
            3,
            3,
            [self._Attempt(0, "built", 3, 3)],
        )
        out = "\n".join(_render_build_score(self._Report([block], missing=("exec-1",))))

        assert "1 execution(s) have no usage record" in out

    def test_an_empty_report_says_so(self):
        from drydock.cli import _render_build_score

        out = "\n".join(_render_build_score(self._Report([])))

        assert "No build evidence found" in out

    def test_compact_clock_scales_from_seconds_to_hours(self):
        from drydock.cli import _compact_clock

        assert _compact_clock(48_000) == "48s"
        assert _compact_clock(430_000) == "7m 10s"
        assert _compact_clock(3_780_000) == "1h 03m"
        assert _compact_clock(-5) == "0s"


class TestExecutionBoundFlags:
    """A bound flag overrides the configured value for one run, and only for that run."""

    def test_a_flag_overrides_the_configured_bound(self, monkeypatch):
        from types import SimpleNamespace

        from drydock.cli import _apply_bound_overrides
        from drydock.config import get_capture_output_limit_mb, max_consecutive_stalls

        monkeypatch.setenv("DRYDOCK_CAPTURE_OUTPUT_LIMIT", "8")
        monkeypatch.setenv("DRYDOCK_REPAIR_STALL_LIMIT", "2")
        _apply_bound_overrides(
            SimpleNamespace(capture_output_limit=64, repair_stall_limit=5, sandbox_mem_limit=None)
        )

        assert get_capture_output_limit_mb() == 64
        assert max_consecutive_stalls() == 5

    def test_an_unset_flag_leaves_the_configured_bound_alone(self, monkeypatch):
        from types import SimpleNamespace

        from drydock.cli import _apply_bound_overrides
        from drydock.config import get_capture_output_limit_mb

        monkeypatch.setenv("DRYDOCK_CAPTURE_OUTPUT_LIMIT", "16")
        _apply_bound_overrides(SimpleNamespace(capture_output_limit=None, repair_stall_limit=None))

        assert get_capture_output_limit_mb() == 16

    def test_the_repair_budget_falls_back_to_configuration(self, monkeypatch):
        from types import SimpleNamespace

        from drydock.cli import _resolved_repair_attempts

        monkeypatch.setenv("DRYDOCK_REPAIR_ATTEMPTS", "12")
        assert _resolved_repair_attempts(SimpleNamespace(repair_attempts=None)) == 12
        # An explicit flag still wins over the configured budget.
        assert _resolved_repair_attempts(SimpleNamespace(repair_attempts=3)) == 3

    def test_both_build_and_uat_accept_every_bound(self):
        for command in ("build", "uat"):
            code, out, err = run_cli(command, "--help")
            text = out + err
            assert code == 0
            for flag in (
                "--repair-attempts",
                "--repair-stall-limit",
                "--capture-output-limit",
                "--sandbox-mem-limit",
            ):
                assert flag in text, f"{flag} missing from drydock {command} --help"
