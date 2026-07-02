"""Tests for the Drydock CLI entry point."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from drydock import __copyright__, __version__
from drydock.cli import main


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


class TestHelpAndVersion:
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
            "prompt",
            "document",
            "publish",
            "rigging",
            "plan",
            "build",
            "refit",
            "analyze",
            "import",
            "run",
            "shipslog",
        ):
            assert cmd in out, f"Command {cmd!r} missing from --help"

    def test_help_exposes_shipslog_publishing_not_recording(self):
        rc, out, _ = run_cli("--help")
        assert rc == 0
        # Publishing is public; the recording utility stays repository-local.
        assert "shipslog" in out
        assert "ships_log.py" not in out

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

    def test_command_prints_copyright_to_stderr(self, isolated_config):
        _, _, err = run_cli("config", "show")
        assert __copyright__ in err
        assert __version__ in err


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

    def test_config_set_prompt_warn_kb(self, isolated_config):
        rc, out, err = run_cli("config", "set", "prompt_warn_kb", "75")
        assert rc == 0
        assert "75" in out

    def test_config_set_invalid_prompt_warn_kb_fails(self, isolated_config):
        rc, out, err = run_cli("config", "set", "prompt_warn_kb", "fifty")
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


class TestLlmOverrideFlags:
    def test_status_help_lists_llm_flags(self):
        rc, out, _ = run_cli("status", "--help")
        assert rc == 0
        assert "--llm-provider" in out
        assert "--model" in out

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
        monkeypatch.setattr("drydock.build_run._ensure_drydock_source_clean", lambda: None)
        monkeypatch.setattr("drydock.build_run.ensure_compact_files", lambda *a, **k: None)

        rc, out, err = run_cli("build", "ExampleTarget", "--build-dir", str(tmp_path / "out"))

        assert rc == 0, err
        assert "[built]" in out
        assert "foundation" in out
        assert "Setting up git directory in" in out
        assert "Ran git commit to commit changes" in out
        assert (target / "evidence" / "foundation.md").is_file()

    def test_build_step_force_rebuilds_selected_step(
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
        monkeypatch.setattr("drydock.build_run._ensure_drydock_source_clean", lambda: None)
        monkeypatch.setattr("drydock.build_run.ensure_compact_files", lambda *a, **k: None)

        rc, out, err = run_cli(
            "build",
            "ExampleTarget",
            "--step",
            "foundation",
            "--force",
            "--build-dir",
            str(tmp_path / "out"),
        )

        assert rc == 0, err
        assert "Building step: foundation" in out
        assert "Force rebuild: resetting foundation and child ACs to pending" in out
        assert "[built]" in out
        assert "foundation" in out
        assert "RESULT: 1 built, 0 failed" in out

    def test_build_with_legacy_implemented_step_does_not_print_verify_command(
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
        monkeypatch.setattr("drydock.build_run._ensure_drydock_source_clean", lambda: None)
        monkeypatch.setattr("drydock.build_run.ensure_compact_files", lambda *a, **k: None)

        rc, out, err = run_cli("build", "ExampleTarget", "--build-dir", str(tmp_path / "out"))

        assert rc == 0, err
        assert "Review required before more build work can run" not in out
        assert "drydock build verify ExampleTarget awaiting-checks" not in out
        assert "Legacy implemented steps remain" in out


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
        assert (quarterdeck / "tickets.json").is_file()
        assert not (quarterdeck / "app.py").exists()
        config = (quarterdeck / "console.yaml").read_text(encoding="utf-8")
        assert config.index('label: "Sea Trials"') < config.index('label: "Soundings"')

        # Build readiness is not gated by plan state — running is the approval.
        # A pending story with no unmet dependencies is buildable immediately.
        rc, out, err = run_cli("build", "status", "ExampleTarget")
        assert rc == 0, err
        assert "Buildable now: story-status" in out

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
        assert "IMPORTED" in out
        assert "sources/req.md" in out

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
        assert "IMPORTED" in out

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
        assert "IMPORTED" in out

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


class TestStubs:
    """Deferred commands must exit 2, print a message, and not write anything."""

    STUB_CASES = [
        (["build", "score", "MyTarget"], "build score"),
    ]

    @pytest.mark.parametrize("args,label", STUB_CASES)
    def test_stub_exits_2(self, args, label, tmp_path):
        rc, out, err = run_cli(*args)
        assert rc == 2, f"{label!r} should exit 2, got {rc}"

    @pytest.mark.parametrize("args,label", STUB_CASES)
    def test_stub_prints_not_implemented(self, args, label, tmp_path):
        rc, out, err = run_cli(*args)
        combined = out + err
        assert "not implemented" in combined, f"{label!r}: expected 'not implemented' in output"

    @pytest.mark.parametrize("args,label", STUB_CASES)
    def test_stub_does_not_write_files(self, args, label, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_cli(*args)
        written = list(tmp_path.rglob("*"))
        assert not written, f"{label!r} wrote files: {written}"


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
