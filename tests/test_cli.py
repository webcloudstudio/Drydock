"""Tests for the Drydock CLI entry point."""

from __future__ import annotations

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
            "config",
            "init",
            "validate",
            "document",
            "rigging",
            "plan",
            "build",
            "iterate",
            "analyze",
            "import",
        ):
            assert cmd in out, f"Command {cmd!r} missing from --help"

    def test_help_does_not_expose_ships_log(self):
        rc, out, _ = run_cli("--help")
        assert rc == 0
        assert "log" not in out

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


class TestConfigShow:
    def test_config_show_runs(self, isolated_config):
        rc, out, err = run_cli("config", "show")
        assert rc == 0
        assert "blueprint_directory" in out
        assert "target_directory" in out

    def test_config_show_not_set(self, isolated_config):
        rc, out, _ = run_cli("config", "show")
        assert "not set" in out


class TestConfigSet:
    def test_config_set_valid(self, tmp_spec_root, isolated_config):
        rc, out, err = run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        assert rc == 0
        assert "blueprint_directory" in out

    def test_legacy_config_key_is_accepted(self, tmp_spec_root, isolated_config):
        rc, out, err = run_cli("config", "set", "specification_directory", str(tmp_spec_root))
        assert rc == 0
        assert "blueprint_directory" in out

    def test_config_set_persists(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        rc, out, _ = run_cli("config", "show")
        assert str(tmp_spec_root) in out

    def test_config_set_nonexistent_dir_fails(self, isolated_config):
        rc, out, err = run_cli("config", "set", "blueprint_directory", "/does/not/exist")
        assert rc == 1
        assert "error" in err.lower()

    def test_config_set_target_directory(self, tmp_target_root, isolated_config):
        rc, out, err = run_cli("config", "set", "target_directory", str(tmp_target_root))
        assert rc == 0

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
    def test_init_creates_spec_dir(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        rc, out, err = run_cli("init", "TestProject")
        assert rc == 0
        assert (tmp_spec_root / "TestProject").is_dir()

    def test_init_creates_metadata_md(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "TestProject")
        assert (tmp_spec_root / "TestProject" / "METADATA.md").exists()

    def test_init_creates_required_templates(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "TestProject")
        spec_dir = tmp_spec_root / "TestProject"
        for fname in ("METADATA.md", "README.md", "INTENT.md", "ARCHITECTURE.md"):
            assert (spec_dir / fname).exists(), f"{fname} missing"

    def test_init_replaces_tokens(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "TestProject")
        metadata = (tmp_spec_root / "TestProject" / "METADATA.md").read_text()
        assert "__PROJECT_NAME__" not in metadata
        assert "__PROJECT_SLUG__" not in metadata
        assert "TestProject" in metadata

    def test_init_existing_dir_fails_by_default(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "TestProject")
        rc, out, err = run_cli("init", "TestProject")
        assert rc == 1

    def test_init_update_is_non_destructive(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "TestProject")
        # Modify a template file
        meta = tmp_spec_root / "TestProject" / "METADATA.md"
        meta.write_text("MODIFIED CONTENT")
        # --update should not overwrite it
        run_cli("init", "TestProject", "--update")
        assert meta.read_text() == "MODIFIED CONTENT"

    def test_init_force_overwrites(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "TestProject")
        meta = tmp_spec_root / "TestProject" / "METADATA.md"
        meta.write_text("MODIFIED CONTENT")
        run_cli("init", "TestProject", "--force")
        assert meta.read_text() != "MODIFIED CONTENT"

    def test_init_rejects_path_traversal(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        rc, out, err = run_cli("init", "../evil")
        assert rc == 1

    def test_init_rejects_empty_name(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        rc, out, err = run_cli("init", "")
        assert rc != 0

    def test_init_display_name_from_slug(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "my-cool-project")
        metadata = (tmp_spec_root / "my-cool-project" / "METADATA.md").read_text()
        assert "My Cool Project" in metadata


class TestValidate:
    def _setup_spec(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        run_cli("init", "TestProject")
        return tmp_spec_root / "TestProject"

    def test_validate_after_init_exits_zero(self, tmp_spec_root, isolated_config):
        self._setup_spec(tmp_spec_root, isolated_config)
        rc, out, err = run_cli("validate", "TestProject")
        assert rc == 0  # warnings are OK, no failures expected after init

    def test_validate_nonexistent_spec_fails(self, tmp_spec_root, isolated_config):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        rc, out, err = run_cli("validate", "DoesNotExist")
        assert rc == 1

    def test_validate_verbose_shows_passes(self, tmp_spec_root, isolated_config):
        self._setup_spec(tmp_spec_root, isolated_config)
        rc_plain, out_plain, _ = run_cli("validate", "TestProject")
        rc_verb, out_verb, _ = run_cli("validate", "TestProject", "--verbose")
        assert rc_verb == 0
        assert "PASS" in out_verb
        assert len(out_verb) > len(out_plain)

    def test_validate_missing_required_file_fails(self, tmp_spec_root, isolated_config):
        spec_dir = self._setup_spec(tmp_spec_root, isolated_config)
        (spec_dir / "ARCHITECTURE.md").unlink()
        rc, out, err = run_cli("validate", "TestProject")
        assert rc == 1
        assert "ARCHITECTURE" in out

    def test_validate_shows_result_summary(self, tmp_spec_root, isolated_config):
        self._setup_spec(tmp_spec_root, isolated_config)
        rc, out, _ = run_cli("validate", "TestProject")
        assert "RESULT" in out


class TestRiggingCompact:
    """`rigging compact` discovers stale files and writes _compact.md siblings."""

    @staticmethod
    def _fake_run_prompt(monkeypatch, *, ok=True, text="# X — Compact\n\n- must stay\n"):
        from types import SimpleNamespace

        def fake(prompt, working_directory, **kwargs):
            return SimpleNamespace(ok=ok, text=text, execution_id="exec-test")

        monkeypatch.setattr("drydock.rigging_compact.run_prompt", fake)

    def _setup_blueprint(self, tmp_spec_root, name="Proj", **files):
        run_cli("config", "set", "blueprint_directory", str(tmp_spec_root))
        spec = tmp_spec_root / name
        spec.mkdir()
        for fname, body in (files or {"DATABASE.md": "class X: ...\n"}).items():
            (spec / fname).write_text(body, encoding="utf-8")
        return spec

    def test_help_lists_flags(self):
        rc, out, _ = run_cli("rigging", "compact", "--help")
        assert rc == 0
        assert "--all" in out and "--force" in out

    def test_compacts_and_reports(self, tmp_spec_root, isolated_config, monkeypatch):
        spec = self._setup_blueprint(tmp_spec_root)
        self._fake_run_prompt(monkeypatch)
        rc, out, err = run_cli("rigging", "compact", "Proj")
        assert rc == 0, err
        assert (spec / "DATABASE_compact.md").exists()
        assert "1 compacted" in out
        assert "exec-test" in out

    def test_failed_execution_exits_one(self, tmp_spec_root, isolated_config, monkeypatch):
        self._setup_blueprint(tmp_spec_root)
        self._fake_run_prompt(monkeypatch, ok=False, text="")
        rc, out, err = run_cli("rigging", "compact", "Proj")
        assert rc == 1
        assert "1 failed" in out

    def test_nothing_to_compact(self, tmp_spec_root, isolated_config, monkeypatch):
        self._setup_blueprint(tmp_spec_root, **{"README.md": "no compactables\n"})
        self._fake_run_prompt(monkeypatch)
        rc, out, err = run_cli("rigging", "compact", "Proj")
        assert rc == 0
        assert "Nothing to compact" in out


class TestPlanInspection:
    PLAN = """# BUILD_PLAN: Example
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

    def _setup(self, tmp_spec_root, tmp_target_root, monkeypatch):
        blueprint = tmp_spec_root / "Example"
        blueprint.mkdir()
        (blueprint / "BUILD_PLAN.md").write_text(self.PLAN, encoding="utf-8")
        monkeypatch.setenv("BLUEPRINT_DIRECTORY", str(tmp_spec_root))
        monkeypatch.setenv("TARGET_DIRECTORY", str(tmp_target_root))

    def test_plan_show_reports_blocks_and_summary(
        self, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_spec_root, tmp_target_root, monkeypatch)

        rc, out, err = run_cli("plan", "show", "Example")

        assert rc == 0, err
        assert "Blueprint: Example" in out
        assert "import-documents" in out
        assert "pending=2" in out
        assert "RUNNABLE" not in out

    def test_build_status_reports_runnable_frontier(
        self, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        self._setup(tmp_spec_root, tmp_target_root, monkeypatch)

        rc, out, err = run_cli("build", "status", "Example", "ExampleTarget")

        assert rc == 0, err
        assert f"Target: {tmp_target_root / 'ExampleTarget'}" in out
        assert "RUNNABLE        story import-documents" in out
        assert "RUNNABLE        ac    system-starts" in out
        assert "Runnable frontier: import-documents, system-starts" in out

    def test_build_status_usage_error(self):
        rc, out, err = run_cli("build", "status", "Example")

        assert rc == 2
        assert "Usage: drydock build status" in err


class TestPlanInit:
    def _setup_blueprint(self, tmp_spec_root, monkeypatch):
        blueprint = tmp_spec_root / "Example"
        blueprint.mkdir()
        monkeypatch.setenv("BLUEPRINT_DIRECTORY", str(tmp_spec_root))
        for name, body in {
            "METADATA.md": "metadata\n",
            "README.md": "readme\n",
            "INTENT.md": "intent\n",
            "ARCHITECTURE.md": "architecture\n",
            "DATABASE.md": "# Database\n",
            "FEATURE-Catalog.md": "# Feature\n",
            "SCREEN-Catalog.md": "# Screen\n",
        }.items():
            (blueprint / name).write_text(body, encoding="utf-8")
        return blueprint

    def test_plan_init_creates_intent_file(self, tmp_spec_root, isolated_config, monkeypatch):
        blueprint = self._setup_blueprint(tmp_spec_root, monkeypatch)

        rc, out, err = run_cli("plan", "init", "Example")

        assert rc == 0, err
        intent = blueprint / "BUILD_PLAN_INTENT.md"
        assert intent.exists()
        text = intent.read_text(encoding="utf-8")
        assert "## Foundation" in text
        assert "DATABASE.md" in text
        assert "## Planned Work" in text
        assert "FEATURE-Catalog.md" in text
        assert "SCREEN-Catalog.md" in text
        assert "METADATA.md" not in text
        assert "ARCHITECTURE.md" not in text
        assert "Created:" in out

    def test_plan_init_appends_new_specs_only(self, tmp_spec_root, isolated_config, monkeypatch):
        blueprint = self._setup_blueprint(tmp_spec_root, monkeypatch)
        intent = blueprint / "BUILD_PLAN_INTENT.md"
        intent.write_text(
            "# BUILD_PLAN_INTENT.md - Example\n\n## Planned Work\nFEATURE-Catalog.md (1k)\n",
            encoding="utf-8",
        )
        (blueprint / "FEATURE-Checkout.md").write_text("# Checkout\n", encoding="utf-8")

        rc, out, err = run_cli("plan", "init", "Example")

        assert rc == 0, err
        text = intent.read_text(encoding="utf-8")
        assert "## New Specs - place in build order" in text
        assert "FEATURE-Checkout.md" in text
        assert text.count("FEATURE-Catalog.md") == 1
        assert "APPENDED  FEATURE-Checkout.md" in out

    def test_plan_init_reports_when_up_to_date(self, tmp_spec_root, isolated_config, monkeypatch):
        blueprint = self._setup_blueprint(tmp_spec_root, monkeypatch)
        intent = blueprint / "BUILD_PLAN_INTENT.md"
        intent.write_text(
            (
                "# BUILD_PLAN_INTENT.md - Example\n\n"
                "## Foundation\nDATABASE.md (0k)\n\n"
                "## Planned Work\nFEATURE-Catalog.md (0k)\nSCREEN-Catalog.md (0k)\n"
            ),
            encoding="utf-8",
        )

        rc, out, err = run_cli("plan", "init", "Example")

        assert rc == 0, err
        assert "up to date" in out

    def test_plan_init_inventories_imported_sources(
        self, tmp_spec_root, isolated_config, monkeypatch
    ):
        blueprint = self._setup_blueprint(tmp_spec_root, monkeypatch)
        source = blueprint / "sources" / "notes" / "request.md"
        source.parent.mkdir(parents=True)
        source.write_text("# Request\n", encoding="utf-8")

        rc, out, err = run_cli("plan", "init", "Example")

        assert rc == 0, err
        text = (blueprint / "BUILD_PLAN_INTENT.md").read_text(encoding="utf-8")
        assert "## Imported Sources" in text
        assert "sources/notes/request.md" in text


class TestPlanningSession:
    def _configure(self, tmp_spec_root, tmp_target_root, monkeypatch):
        monkeypatch.setenv("BLUEPRINT_DIRECTORY", str(tmp_spec_root))
        monkeypatch.setenv("TARGET_DIRECTORY", str(tmp_target_root))

    def test_markdown_import_plan_create_and_approve(
        self, tmp_path, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_spec_root, tmp_target_root, monkeypatch)
        source = tmp_path / "request.md"
        source.write_text(
            "# Request\n\nBuild a status command.\n\n## Acceptance Criteria\n\n"
            "- Status command exits successfully.\n",
            encoding="utf-8",
        )

        rc, out, err = run_cli("import", "Example", str(source), "--format", "markdown")
        assert rc == 0, err
        assert (tmp_spec_root / "Example" / "sources" / "request.md").is_file()

        assert run_cli("plan", "init", "Example")[0] == 0
        rc, out, err = run_cli("plan", "create", "Example", "ExampleTarget")
        assert rc == 0, err
        assert "Plan state: draft" in out
        plan_path = tmp_spec_root / "Example" / "BUILD_PLAN.md"
        assert "Status command exits successfully." in plan_path.read_text(encoding="utf-8")
        quarterdeck = tmp_target_root / "ExampleTarget" / "QuarterDeck"
        assert (quarterdeck / "console.yaml").is_file()
        assert (quarterdeck / "tickets.json").is_file()
        assert (quarterdeck / "app.py").is_file()

        rc, out, err = run_cli("build", "status", "Example", "ExampleTarget")
        assert rc == 0, err
        assert "Runnable frontier: (none)" in out

        rc, out, err = run_cli("plan", "approve", "Example", "ExampleTarget")
        assert rc == 0, err
        assert "Plan state: approved" in out
        rc, out, err = run_cli("build", "status", "Example", "ExampleTarget")
        assert rc == 0, err
        assert "Runnable frontier: story-request" in out

        rc, out, err = run_cli(
            "plan", "revise", "Example", "ExampleTarget", "Split the status behavior."
        )
        assert rc == 0, err
        assert "Plan state: draft" in out
        text = plan_path.read_text(encoding="utf-8")
        assert "planning_decision: revise" in text
        assert "planning_feedback: Split the status behavior." in text

    def test_feature_spec_generates_feature_parent_and_acceptance(
        self, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        self._configure(tmp_spec_root, tmp_target_root, monkeypatch)
        blueprint = tmp_spec_root / "Example"
        blueprint.mkdir()
        (blueprint / "FEATURE-Catalog.md").write_text(
            "# FEATURE: Catalog\n\n## Acceptance Criteria\n\n- Catalog lists items.\n"
            "\n## Guardrails\n\n- None.\n\n## Open Questions\n\n- Which sort order?\n",
            encoding="utf-8",
        )
        assert run_cli("plan", "init", "Example")[0] == 0

        rc, out, err = run_cli("plan", "create", "Example", "Target")

        assert rc == 0, err
        text = (blueprint / "BUILD_PLAN.md").read_text(encoding="utf-8")
        assert "## feature 1: Catalog" in text
        assert "parent: feature-catalog" in text
        assert "Catalog workflow is accepted" in text
        assert "Which sort order?" in text
        assert "depends: spike-which-sort-order" in text


class TestStubs:
    """Deferred commands must exit 2, print a message, and not write anything."""

    STUB_CASES = [
        (["document", "generate", "MySpec", "MyTarget"], "document generate"),
        (["document", "assemble", "MySpec", "MyTarget"], "document assemble"),
        (["document", "MySpec", "MyTarget"], "document"),
        (["rigging", "update", "MyTarget"], "rigging update"),
        (["rigging", "verify", "MyTarget"], "rigging verify"),
        (["build", "score", "MySpec", "MyTarget"], "build score"),
        (["build", "MySpec", "MyTarget"], "build"),
        (["iterate", "MySpec", "MyTarget", "BOTH", "SomeScope", "SomeChange"], "iterate"),
        (["iterate", "MySpec", "MyTarget", "SPEC", "SomeScope", "SomeChange"], "iterate"),
        (["analyze", "MySpec"], "analyze"),
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
