"""Tests for the Drydock CLI entry point."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from drydock import __copyright__, __version__
from drydock.acceptance import AcceptanceObservation, AcceptanceRunResult
from drydock.build_run import BuildStepResult
from drydock.cli import (
    _print_dimensions,
    _render_build_failures,
    _stream_build,
    _stream_status_only,
    _stream_stdout,
    main,
)


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

    assert "Story Inline Parsing [inlines]" in rendered
    assert "Fixed parsing and rendering behavior." in rendered
    assert "inline-suite: 271 passed, 64 failed · change +71 passed, -71 failed" in rendered
    assert "remaining acceptance:" in rendered
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
        _stream_build("tests: FAILED (2/3) — block-conformance")
        _stream_build("repair: attempt 1/1 · 1 failing check(s)")

        assert capsys.readouterr().out == (
            "\ntests: FAILED (2/3) — block-conformance\nrepair: attempt 1/1 · 1 failing check(s)\n"
        )

    def test_stream_status_only_drops_model_json_payload(self, capsys):
        """Scoring commands parse the model's JSON; the console must not echo it."""
        _stream_stdout._at_line_start = True  # type: ignore[attr-defined]
        _stream_status_only('{"dimensions": {"build_quality": 0}}')
        _stream_status_only("AUTO-COMPACT: fresh")

        assert capsys.readouterr().out == "AUTO-COMPACT: fresh\n"

    def test_print_dimensions_marks_scores_under_the_gate(self, capsys):
        _print_dimensions({"build_quality": 0, "test_coverage": 90})

        out = capsys.readouterr().out
        assert "build_quality    0   BELOW GATE" in out
        assert "test_coverage   90\n" in out

    def test_help_shows_copyright(self):
        rc, out, err = run_cli("--help")
        assert rc == 0
        assert __copyright__ in out
        assert "Blueprint-driven" in out

    def test_help_shows_all_top_commands(self):
        rc, out, _ = run_cli("--help")
        for cmd in (
            "status",
            "config",
            "init",
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

    def test_score_help_shows_ac_and_release(self):
        rc, out, _ = run_cli("score", "--help")
        assert rc == 0
        assert "score ac" in out
        assert "score release" in out

    def test_score_bad_subverb_is_usage_error(self):
        rc, _, err = run_cli("score", "bogus", "Demo")
        assert rc == 2
        assert "ac|release" in err

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
        assert "default 3" in out
        assert "--escalate-model" in out
        assert "--reset-failed" not in out
        assert "--force" not in out

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
        assert "Warning: SEA_TRIALS.md was not created" in err


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
        # Conform pass is on by default and suppressed by --no-conform.
        assert seen["kwargs"]["conform"] is True

        rc, out, err = run_cli("plan", "Proj", "--no-conform")
        assert rc == 0, err
        assert seen["kwargs"]["conform"] is False


class TestPlanInspection:
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

    def test_build_verify_marks_step_and_acs_verified(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)

        rc, out, err = run_cli("build", "verify", "ExampleTarget", "awaiting-checks")

        assert rc == 0, err
        assert "Verified: awaiting-checks" in out
        assert "Acceptance checks: system-starts" in out
        manifest = (tmp_target_root / "ExampleTarget" / "MANIFEST.md").read_text(encoding="utf-8")
        assert "id: awaiting-checks\nstate: closed/verified" in manifest
        assert "id: system-starts\nparent: awaiting-checks\nstate: closed/verified" in manifest

    def test_build_verify_already_verified_is_success(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        run_cli("build", "verify", "ExampleTarget", "awaiting-checks")

        rc, out, err = run_cli("build", "verify", "ExampleTarget", "awaiting-checks")

        assert rc == 0, err
        assert "Already verified: awaiting-checks" in out

    def test_build_verify_usage_error(self):
        rc, out, err = run_cli("build", "verify")

        assert rc == 2
        assert "Usage: drydock build verify" in err

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
        assert re.search(
            r"BUILD ExampleTarget started at \d{4}-\d{2}-\d{2} ",
            out,
        )
        assert "BUILD COMPLETE ExampleTarget" in out
        assert re.search(r"completed at \d{4}-\d{2}-\d{2} ", out)
        assert re.search(r"elapsed: ", out)
        assert "result: built" in out
        assert "foundation" in out
        # The build performs no git operations, so it prints no git status lines.
        assert "git" not in out.lower()
        assert (target / "evidence" / "foundation.md").is_file()

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
        assert "result: FAILED" in out
        # The failure block closes the run: it comes after the completion header, not mid-stream.
        assert out.index("BUILD FAILED: ExampleTarget") > out.index("BUILD COMPLETE ExampleTarget")
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
        assert "(foundation)" in out
        assert "(service)" in out
        assert "The backend diverges from the spec." in out
        assert "Story recovery (dependency order)" in out
        assert "drydock build ExampleTarget --story foundation --repair-attempts 2" in out
        assert "drydock build ExampleTarget --story service --repair-attempts 2" in out

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
        assert "llm-provider: codex / gpt-5.4" in out

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
        assert "result: built" in out
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
        assert "full reset:" in out
        assert "result: built" in out
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
        assert "result: built" in out

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
        assert "normalize order: updated MANIFEST.md" in out
        assert "(feature-core-story)" in out
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
        assert "drydock build verify ExampleTarget awaiting-checks" not in out


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
        "## Open Questions\n\n- None.\n"
        "=== END ARCHITECTURE.md ===\n"
        "=== FEATURE-Status.md ===\n"
        "# FEATURE: Status\n\n"
        "| Field | Value |\n|---|---|\n| Version | 20260616 V1 |\n"
        "| Description | Status command. |\n| Phase | 1 |\n\n"
        "## Programmatic Acceptance\n\n- None.\n\n## User Acceptance\n\n"
        "- Status command exits successfully.\n\n"
        "## Guardrails\n\n- None.\n\n## Open Questions\n\n- None.\n"
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
        monkeypatch.setattr("drydock.planning_session.ensure_compact_files", lambda *a, **k: None)

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
        assert "Authored 2 Blueprint spec file(s)" in out
        assert "review the manifest build tree in the Planning Session" in out
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
        assert "No Blueprint or Manifest artifacts were written" in err
        assert not (target / "MANIFEST.md").exists()
        assert not (target / "QuarterDeck" / "tickets.json").exists()

    @pytest.mark.parametrize("verb", ["create", "init", "show", "approve", "revise", "reject"])
    def test_plan_has_no_public_subcommands(self, verb):
        rc, out, err = run_cli("plan", verb, "Example", "Target")

        assert rc == 2
        assert "usage: drydock" in err
        assert "unrecognized arguments: Example Target" in err


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
        assert f" - Source: {source}" in out
        assert f" - Target: {tmp_target_root / 'Tgt' / 'blueprint' / 'sources'}/" in out
        assert "  req.md" in out
        assert "IMPORTED" not in out
        assert "Blueprint:" not in out
        assert "SAVED AS" not in out
        assert "Next step: drydock analyze Tgt" in out

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
        assert " - Target:" in out
        assert "  app.py" in out

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
        assert " - Target:" in out
        assert "  memory/constitution.md" in out

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
                score=84,
                dimensions={"build_quality": 40, "test_coverage": 90},
                complete=False,
                scorecard_path=target / "SCORECARD.md",
                evidence_path=target / "evidence" / "build-score.json",
                blockers=("Required Sea Trial st-one is FAIL",),
                exit_code=lambda: 1,
            ),
        )

        rc, out, err = run_cli("build", "score", "ExampleTarget")

        assert rc == 1, err
        assert "Build score: 84/100" in out
        assert "build_quality   40   BELOW GATE" in out
        assert "Completion gate: INCOMPLETE" in out
        assert "Required Sea Trial st-one is FAIL" in out


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
        assert re.search(r"\b\d{1,2}-\d{1,2}:\s+✅\s+drydock analyze MyProject", out)
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
        assert re.search(r"\b\d{1,2}-\d{1,2}:\s+❌\s+drydock analyze MyProject", out)

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
        assert "BLOCKED: Unplanned" in err
        assert "drydock plan" in err

    def test_status_ready_exits_0_while_buildable(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "TestTarget", "--ready")
        assert rc == 0, err
        assert out == ""
        assert __copyright__ not in out
        assert "READY TO BUILD: TestTarget" in err

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
        assert rc == 1, err
        assert "BUILD COMPLETE: TestTarget" in err

    def test_status_ready_exits_1_when_blocked(self, tmp_target_root, isolated_config, monkeypatch):
        from drydock.init_specification import init_specification

        target_dir = tmp_target_root / "Unplanned"
        init_specification("Unplanned", target_dir)
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_target_root.parent))
        rc, out, err = run_cli("status", "Unplanned", "--ready")
        assert rc == 1
        assert "NOT READY: Unplanned" in err

    def test_status_check_and_ready_mutually_exclusive(
        self, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_target_root, monkeypatch)
        rc, out, err = run_cli("status", "TestTarget", "--check", "--ready")
        assert rc == 2


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
