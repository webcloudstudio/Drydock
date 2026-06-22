"""Tests for the rigging compaction capability."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.rigging_compact import _extract_compact_error, _finalize, _skip_path, compact, discover


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

    def run(prompt, working_directory, **kwargs):
        seen.append(prompt)
        return FakeRun()

    run.seen = seen  # type: ignore[attr-defined]
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

        forced = compact(name, root / name, force=True, runner=fake_runner())
        assert [i.status for i in forced.items] == ["compacted"]

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
        name, root = _blueprint(
            tmp_path, **{"DATABASE.md": "db\n", "BUSINESS_RULES.md": "rules\n"}
        )
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
        out = _finalize(text, rel_source="DATABASE.md", today="2026-06-22")
        assert out.startswith("<!-- Compacted from DATABASE.md on 2026-06-22")
        assert out.count("Compacted from") == 1
        assert "# T — Usage Surface" in out
        assert "```" not in out
