"""Tests for the rigging compaction capability."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.rigging_compact import _finalize, compact, discover


@dataclass
class FakeRun:
    """Stand-in for an LlmResult — never spends API credits."""

    ok: bool = True
    text: str = "# Thing — Compact\n\n- rule must stay verbatim\n"
    execution_id: str = "exec-fake"


def fake_runner(*calls: object):
    """Return a runner that records prompts and yields canned results."""
    seen: list[str] = []

    def run(prompt, working_directory, **kwargs):
        seen.append(prompt)
        return FakeRun()

    run.seen = seen  # type: ignore[attr-defined]
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


class TestCompact:
    def test_writes_siblings_with_provenance_and_exit_zero(self, tmp_path):
        name, root = _blueprint(
            tmp_path, **{"DATABASE.md": "# DB\nclass X: ...\n", "BUSINESS_RULES.md": "must X\n"}
        )
        result = compact(name, root, runner=fake_runner())
        assert result.exit_code() == 0
        assert {i.status for i in result.items} == {"compacted"}
        compact_file = root / name / "DATABASE_compact.md"
        assert compact_file.exists()
        head = compact_file.read_text(encoding="utf-8").splitlines()[0]
        assert head.startswith("<!-- Compacted from DATABASE.md")

    def test_freshness_gate_skips_then_force_recompacts(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        compact(name, root, runner=fake_runner())
        # Make the compact strictly newer than the source.
        compact_file = root / name / "DATABASE_compact.md"
        future = compact_file.stat().st_mtime + 100
        os.utime(compact_file, (future, future))

        again = compact(name, root, runner=fake_runner())
        assert [i.status for i in again.items] == ["skipped-fresh"]

        forced = compact(name, root, force=True, runner=fake_runner())
        assert [i.status for i in forced.items] == ["compacted"]

    def test_failed_runner_marks_failed_and_exit_one(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})

        def failing(prompt, wd, **kwargs):
            return FakeRun(ok=False, text="")

        result = compact(name, root, runner=failing)
        assert result.exit_code() == 1
        assert result.items[0].status == "failed"
        assert not (root / name / "DATABASE_compact.md").exists()

    def test_empty_output_is_a_failure(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "db\n"})
        result = compact(name, root, runner=lambda p, wd, **k: FakeRun(text="   \n"))
        assert result.items[0].status == "failed"
        assert result.items[0].error == "empty output"

    def test_assembled_prompt_carries_job_context(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"DATABASE.md": "secret-token\n"})
        runner = fake_runner()
        compact(name, root, runner=runner)
        prompt = runner.seen[0]  # type: ignore[attr-defined]
        assert "## Compaction job" in prompt
        assert "SOURCE_PATH: DATABASE.md" in prompt
        assert "secret-token" in prompt  # source content was injected

    def test_unknown_blueprint_raises(self, tmp_path):
        root = tmp_path / "specs"
        root.mkdir()
        with pytest.raises(SpecificationError, match="not found"):
            compact("missing", root, runner=fake_runner())

    def test_nothing_to_compact_is_clean(self, tmp_path):
        name, root = _blueprint(tmp_path, **{"README.md": "no compactables\n"})
        result = compact(name, root, runner=fake_runner())
        assert result.items == []
        assert result.exit_code() == 0


class TestFinalize:
    def test_strips_outer_fence_and_dedupes_provenance(self):
        text = "```markdown\n<!-- Compacted from old by old -->\n# T — Compact\nbody\n```"
        out = _finalize(text, rel_source="DATABASE.md", today="2026-06-11")
        assert out.startswith("<!-- Compacted from DATABASE.md on 2026-06-11")
        assert out.count("Compacted from") == 1
        assert "# T — Compact" in out
        assert "```" not in out
