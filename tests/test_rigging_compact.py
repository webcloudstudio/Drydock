"""Tests for the rigging compaction capability."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.rigging_compact import (
    _extract_compact_error,
    _finalize,
    _strip_provenance,
    compact,
    discover,
    ensure_compact_files,
    resolve_role,
)


@dataclass
class FakeRun:
    """Stand-in for an LlmResult — never spends API credits."""

    ok: bool = True
    text: str = (
        "# Widget Service — Usage Surface\n\n"
        "### POST /widget\n"
        "Create a widget.\n\n"
        "| Parameter | Type | Required | Description |\n"
        "|-----------|------|----------|-------------|\n"
        "| name | str | yes | Display name |\n\n"
        "`Returns: WidgetResponse — {id, name}`\n"
    )
    execution_id: str = "exec-fake"


def fake_runner(*calls: object):
    """Return a runner that records prompts and yields canned results."""
    seen: list[str] = []
    seen_kwargs: list[dict[str, object]] = []

    def run(prompt, working_directory, **kwargs):
        seen.append(prompt)
        seen_kwargs.append(kwargs)
        return FakeRun()

    run.seen = seen  # type: ignore[attr-defined]
    run.seen_kwargs = seen_kwargs  # type: ignore[attr-defined]
    return run


def fake_runner_no_surface():
    """Runner that returns a COMPACT_ERROR response."""

    def run(prompt, working_directory, **kwargs):
        return FakeRun(text="COMPACT_ERROR: no technical surface — builder use only")

    return run


def _blueprint(tmp_path: Path, name: str = "bp", **files: str) -> tuple[str, Path]:
    root = tmp_path / "specs"
    root.mkdir()
    spec = root / name
    spec.mkdir()
    for fname, body in files.items():
        (spec / fname).write_text(body, encoding="utf-8")
    return name, root


class TestDiscover:
    def test_finds_required_pairs_and_existing_siblings_only(self, tmp_path):
        _, root = _blueprint(
            tmp_path,
            **{
                "DATABASE.md": "db",
                "BUSINESS_RULES.md": "rules",
                "NOTES.md": "no sibling, ignored",
                "STACK.md": "has a sibling",
                "STACK_compact.md": "the sibling",
            },
        )
        spec = root / "bp"
        names = [p.name for p in discover(spec)]
        assert names == ["DATABASE.md", "BUSINESS_RULES.md", "STACK.md"]
        assert "NOTES.md" not in names
        assert "STACK_compact.md" not in names  # never a source

    def test_missing_required_file_is_simply_absent(self, tmp_path):
        _, root = _blueprint(tmp_path, **{"DATABASE.md": "db"})
        assert [p.name for p in discover(root / "bp")] == ["DATABASE.md"]

    def test_include_files_adds_explicit_targets(self, tmp_path):
        _, root = _blueprint(tmp_path, **{"NOTES.md": "notes"})
        spec = root / "bp"
        extra = spec / "NOTES.md"
        names = [p.name for p in discover(spec, include_files=[extra])]
        assert "NOTES.md" in names

    def test_exclude_files_removes_from_discovered(self, tmp_path):
        _, root = _blueprint(
            tmp_path,
            **{"DATABASE.md": "db", "BUSINESS_RULES.md": "rules"},
        )
        spec = root / "bp"
        excluded = spec / "DATABASE.md"
        names = [p.name for p in discover(spec, exclude_files=[excluded])]
        assert "DATABASE.md" not in names
        assert "BUSINESS_RULES.md" in names

    def test_include_dir_adds_all_md_in_directory(self, tmp_path):
        _, root = _blueprint(tmp_path)
        spec = root / "bp"
        extra_dir = tmp_path / "extras"
        extra_dir.mkdir()
        (extra_dir / "FEATURE.md").write_text("feature", encoding="utf-8")
        (extra_dir / "IGNORE.txt").write_text("not md", encoding="utf-8")
        names = [p.name for p in discover(spec, include_dirs=[extra_dir])]
        assert "FEATURE.md" in names
        assert "IGNORE.txt" not in names

    def test_compact_files_never_added_via_include_file(self, tmp_path):
        _, root = _blueprint(tmp_path)
        spec = root / "bp"
        compact_file = spec / "FOO_compact.md"
        compact_file.write_text("compact", encoding="utf-8")
        names = [p.name for p in discover(spec, include_files=[compact_file])]
        assert "FOO_compact.md" not in names

    def test_skip_sibling_included_in_autodiscovery(self, tmp_path):
        _, root = _blueprint(tmp_path, **{"BRANDING.md": "branding"})
        spec = root / "bp"
        (spec / "BRANDING_compact.skip.md").write_text("<!-- no-surface -->", encoding="utf-8")
        names = [p.name for p in discover(spec)]
        assert "BRANDING.md" in names

    def test_skip_files_not_treated_as_sources(self, tmp_path):
        _, root = _blueprint(tmp_path, **{"BRANDING_compact.skip.md": "sentinel"})
        spec = root / "bp"
        names = [p.name for p in discover(spec)]
        assert "BRANDING_compact.skip.md" not in names


class TestCompact:
    def test_resolve_role_uses_exact_filename_matches(self):
        assert resolve_role(Path("ARCHITECTURE.md")).key == "architecture"
        assert resolve_role(Path("DATABASE.md")).key == "database_api"
        assert resolve_role(Path("FEATURE-Thing.md")).key == "contracts"

    def test_writes_siblings_with_provenance_and_exit_zero(self, tmp_path):
        name, root = _blueprint(
            tmp_path, **{"DATABASE.md": "# DB\nclass X: ...\n", "BUSINESS_RULES.md": "must X\n"}
        )
        result = compact(name, root / name, runner=fake_runner())
        assert result.exit_code() == 0
        assert {i.status for i in result.items} == {"compacted"}
        compact_file = root / name / "DATABASE_compact.md"
        assert compact_file.exists()
        head = compact_file.read_text(encoding="utf-8").splitlines()[0]
        assert head.startswith("<!-- Compacted from DATABASE.md")

    def test_freshness_gate_skips_then_force_recompacts(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        compact(name, root / name, runner=fake_runner())
        compact_file = root / name / "DATABASE_compact.md"
        future = compact_file.stat().st_mtime + 100
        os.utime(compact_file, (future, future))

        again = compact(name, root / name, runner=fake_runner())
        assert [i.status for i in again.items] == ["skipped-fresh"]

        # Force re-runs the LLM; an identical body keeps the existing bytes.
        forced = compact(name, root / name, force=True, runner=fake_runner())
        assert [i.status for i in forced.items] == ["skipped-unchanged"]

        def changed(prompt, wd, **kwargs):
            return FakeRun(text="# DB — Persistence Contract\n\n### new_store.read\n")

        rewritten = compact(name, root / name, force=True, runner=changed)
        assert [i.status for i in rewritten.items] == ["compacted"]

    def test_source_rewrite_with_unchanged_content_skips_via_sha(self, tmp_path):
        # A source rewritten with identical bytes (mtime bumped, sha unchanged)
        # must not re-trigger an LLM compaction run.
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        compact(name, root / name, runner=fake_runner())
        source = root / name / "DATABASE.md"
        future = source.stat().st_mtime + 100
        source.write_text("db\n", encoding="utf-8")
        os.utime(source, (future, future))

        calls: list[str] = []

        def counting_runner(prompt, working_directory, **kwargs):
            calls.append(prompt)
            return FakeRun()

        again = compact(name, root / name, runner=counting_runner)
        assert calls == []
        assert [i.status for i in again.items] == ["skipped-fresh"]

    def test_source_content_change_recompacts(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        compact(name, root / name, runner=fake_runner())
        source = root / name / "DATABASE.md"
        future = source.stat().st_mtime + 100
        source.write_text("db changed\n", encoding="utf-8")
        os.utime(source, (future, future))

        def changed(prompt, wd, **kwargs):
            return FakeRun(text="# DB — Persistence Contract\n\n### new_store.read\n")

        again = compact(name, root / name, runner=changed)
        assert [i.status for i in again.items] == ["compacted"]

    def test_unchanged_body_after_source_change_updates_provenance_only(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        compact(name, root / name, runner=fake_runner())
        compact_file = root / name / "DATABASE_compact.md"
        original = compact_file.read_text(encoding="utf-8")
        # Source content changes → regeneration runs; identical body → provenance
        # is rewritten (new source sha) but the body is untouched.
        source = root / name / "DATABASE.md"
        future = source.stat().st_mtime + 100
        source.write_text("db changed\n", encoding="utf-8")
        os.utime(source, (future, future))

        result = compact(name, root / name, runner=fake_runner())
        assert [i.status for i in result.items] == ["skipped-unchanged"]
        updated = compact_file.read_text(encoding="utf-8")
        assert _strip_provenance(updated) == _strip_provenance(original)
        assert result.exit_code() == 0

        # The recorded sha now matches the rewritten source, so the next run
        # skips without an LLM call.
        calls: list[str] = []

        def counting(prompt, wd, **kwargs):
            calls.append(prompt)
            return FakeRun()

        again = compact(name, root / name, runner=counting)
        assert calls == []
        assert [i.status for i in again.items] == ["skipped-fresh"]

    def test_existing_compact_is_not_injected_into_prompt(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        compact(name, root / name, runner=fake_runner())
        source = root / name / "DATABASE.md"
        future = source.stat().st_mtime + 100
        source.write_text("db changed\n", encoding="utf-8")
        os.utime(source, (future, future))

        runner = fake_runner()
        compact(name, root / name, runner=runner)
        prompt = runner.seen[0]  # type: ignore[attr-defined]
        assert 'filename="DATABASE_compact.md"' not in prompt
        assert 'filename="DATABASE.md"' in prompt

    def test_failed_runner_marks_failed_and_exit_one(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})

        def failing(prompt, wd, **kwargs):
            return FakeRun(ok=False, text="")

        result = compact(name, root / name, runner=failing)
        assert result.exit_code() == 1
        assert result.items[0].status == "failed"
        assert not (root / name / "DATABASE_compact.md").exists()

    def test_empty_output_is_a_failure(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        result = compact(name, root / name, runner=lambda p, wd, **k: FakeRun(text="   \n"))
        assert result.items[0].status == "failed"
        assert result.items[0].error == "empty output"

    def test_no_surface_response_writes_skip_file_not_compact(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "branding prose\n"})
        result = compact(name, root / name, runner=fake_runner_no_surface())
        assert result.exit_code() == 0
        assert result.items[0].status == "no-surface"
        assert not (root / name / "DATABASE_compact.md").exists()
        skip = root / name / "DATABASE_compact.skip.md"
        assert skip.exists()
        assert "no-surface" in skip.read_text(encoding="utf-8")

    def test_no_surface_skip_file_prevents_rerun(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "branding prose\n"})
        compact(name, root / name, runner=fake_runner_no_surface())
        # Second run: skip file exists and is newer → freshness gate fires
        runner = fake_runner_no_surface()
        result = compact(name, root / name, runner=runner)
        assert result.items[0].status == "skipped-fresh"

    def test_assembled_prompt_carries_job_context(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "secret-token\n"})
        runner = fake_runner()
        compact(name, root / name, runner=runner)
        prompt = runner.seen[0]  # type: ignore[attr-defined]
        assert "## Compaction job" in prompt
        assert "SOURCE_PATH: DATABASE.md" in prompt
        assert "secret-token" in prompt

    def test_runner_receives_role_metadata(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"ARCHITECTURE.md": "module layout\n"})
        runner = fake_runner()
        compact(name, root / name, include_files=[root / name / "ARCHITECTURE.md"], runner=runner)
        kwargs = runner.seen_kwargs[0]  # type: ignore[attr-defined]
        assert kwargs["parameters"]["role"] == "architecture"
        assert kwargs["parameters"]["prompt"] == "rigging_compact_architecture"

    def test_runner_does_not_stream_raw_model_text(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"ARCHITECTURE.md": "module layout\n"})
        runner = fake_runner()
        compact(
            name,
            root / name,
            include_files=[root / name / "ARCHITECTURE.md"],
            runner=runner,
            on_text=lambda _text: None,
        )
        kwargs = runner.seen_kwargs[0]  # type: ignore[attr-defined]
        assert kwargs["on_text"] is None

    def test_reports_source_before_runner_starts(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"ARCHITECTURE.md": "module layout\n"})
        events: list[str] = []

        def runner(prompt, working_directory, **kwargs):
            events.append("runner")
            return FakeRun()

        compact(
            name,
            root / name,
            include_files=[root / name / "ARCHITECTURE.md"],
            runner=runner,
            on_text=events.append,
        )

        assert events[0].startswith(
            "AUTO-COMPACT: compacting ARCHITECTURE.md -> ARCHITECTURE_compact.md "
            "[Architecture via rigging_compact_architecture.md]"
        )
        assert events[1] == "runner"

    def test_unknown_blueprint_raises(self, tmp_path):
        root = tmp_path / "specs"
        root.mkdir()
        with pytest.raises(SpecificationError, match="not found"):
            compact("missing", root / "missing", runner=fake_runner())

    def test_nothing_to_compact_is_clean(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"README.md": "no compactables\n"})
        result = compact(name, root / name, runner=fake_runner())
        assert result.items == []
        assert result.exit_code() == 0

    def test_include_file_arg_targets_explicit_file(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"NOTES.md": "# Notes\nGET /thing\n"})
        spec = root / name
        extra = spec / "NOTES.md"
        result = compact(name, spec, include_files=[extra], runner=fake_runner())
        assert any(i.source.name == "NOTES.md" for i in result.items)

    def test_exclude_file_arg_removes_required_pair(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n", "BUSINESS_RULES.md": "rules\n"})
        spec = root / name
        excluded = spec / "DATABASE.md"
        result = compact(name, spec, exclude_files=[excluded], runner=fake_runner())
        names = [i.source.name for i in result.items]
        assert "DATABASE.md" not in names
        assert "BUSINESS_RULES.md" in names


class TestExtractCompactError:
    def test_detects_compact_error_line(self):
        text = "COMPACT_ERROR: no technical surface — builder use only"
        assert _extract_compact_error(text) == "no technical surface — builder use only"

    def test_returns_none_for_normal_output(self):
        text = "# Widget — Usage Surface\n\n### GET /widget\nFetch a widget.\n"
        assert _extract_compact_error(text) is None

    def test_detects_error_embedded_in_output(self):
        text = "some preamble\nCOMPACT_ERROR: builder-only file\nsome trailing"
        assert _extract_compact_error(text) == "builder-only file"


class TestFinalize:
    def test_strips_outer_fence_and_dedupes_provenance(self):
        text = "```markdown\n<!-- Compacted from old by old -->\n# T — Usage Surface\nbody\n```"
        out = _finalize(text, rel_source="DATABASE.md", today="2026-06-22", source_sha="0" * 64)
        assert out.startswith(f"<!-- Compacted from DATABASE.md sha256={'0' * 64} on 2026-06-22")
        assert out.count("Compacted from") == 1
        assert "# T — Usage Surface" in out
        assert "```" not in out


class TestEnsureCompactFiles:
    def test_no_surface_is_fatal_for_required_sources(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "prose only\n"})
        with pytest.raises(SpecificationError, match="Auto-compaction failed for DATABASE.md"):
            ensure_compact_files(
                root / name,
                sources=[root / name / "DATABASE.md"],
                reason="test",
                runner=fake_runner_no_surface(),
            )

    def test_no_surface_is_non_fatal_for_optional_context_sources(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"SCREEN-UI.md": "layout prose only\n"})
        result = ensure_compact_files(
            root / name,
            sources=[root / name / "SCREEN-UI.md"],
            reason="test",
            runner=fake_runner_no_surface(),
        )
        assert result.items[0].status == "no-surface"
        # skip marker written so the source is not re-attempted every run
        assert (root / name / "SCREEN-UI_compact.skip.md").is_file()
        assert not (root / name / "SCREEN-UI_compact.md").exists()

    def test_optional_source_with_surface_gets_compact(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"FEATURE-X.md": "# X\nGET /x\n"})
        result = ensure_compact_files(
            root / name,
            sources=[root / name / "FEATURE-X.md"],
            reason="test",
            runner=fake_runner(),
        )
        assert result.items[0].status == "compacted"
        assert (root / name / "FEATURE-X_compact.md").is_file()


class TestCompassNeverCompacted:
    """The Compass files carry no contract surface and are never compaction sources."""

    def test_autodiscovery_skips_compass_with_existing_sibling(self, tmp_path):
        _, root = _blueprint(
            tmp_path,
            **{
                "COMPASS.md": "intent",
                "COMPASS_compact.md": "stale derivative",
                "DATABASE.md": "db",
            },
        )
        assert [p.name for p in discover(root / "bp")] == ["DATABASE.md"]

    def test_explicit_include_cannot_force_compass_compaction(self, tmp_path):
        _, root = _blueprint(
            tmp_path,
            **{
                "COMPASS.md": "intent",
                "PLAN_COMPASS.md": "plan direction",
                "ANALYZE_COMPASS.md": "analyze direction",
            },
        )
        spec = root / "bp"
        names = [
            p.name
            for p in discover(
                spec,
                include_files=[
                    spec / "COMPASS.md",
                    spec / "PLAN_COMPASS.md",
                    spec / "ANALYZE_COMPASS.md",
                ],
            )
        ]
        assert names == []

    def test_ensure_compact_files_ignores_compass(self, tmp_path):
        _, root = _blueprint(tmp_path, **{"COMPASS.md": "intent"})
        spec = root / "bp"
        runner = fake_runner()
        result = ensure_compact_files(
            spec, sources=[spec / "COMPASS.md"], reason="build", runner=runner
        )
        assert result.items == []
        assert runner.seen == []
        assert not (spec / "COMPASS_compact.md").exists()
