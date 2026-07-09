"""Unit tests for skill provisioning (drydock.skills)."""

from __future__ import annotations

from pathlib import Path

from drydock.skills import sync_skills


def _make_skill(root: Path, name: str, version: str, body: str = "body") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: {version}\n---\n{body}\n", encoding="utf-8"
    )
    return skill_dir


class TestSyncSkills:
    def test_fresh_install_copies_all_skills(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0")
        _make_skill(source, "apply-refit", "1.0.0")
        project = tmp_path / "ws"

        result = sync_skills(project, source_root=source)

        assert sorted(result.installed) == ["apply-refit", "refit"]
        assert result.updated == []
        assert result.changed is True
        assert (project / ".claude" / "skills" / "refit" / "SKILL.md").is_file()
        assert (project / ".claude" / "skills" / "apply-refit" / "SKILL.md").is_file()

    def test_second_run_is_idempotent(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0")
        project = tmp_path / "ws"

        sync_skills(project, source_root=source)
        result = sync_skills(project, source_root=source)

        assert result.installed == []
        assert result.updated == []
        assert result.skipped == ["refit"]
        assert result.changed is False

    def test_newer_version_upgrades(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0", body="old")
        project = tmp_path / "ws"
        sync_skills(project, source_root=source)

        # Ship a newer version with changed content.
        _make_skill(tmp_path / "src2", "refit", "3.1.0", body="new")
        result = sync_skills(project, source_root=tmp_path / "src2")

        assert result.updated == ["refit"]
        installed = (project / ".claude" / "skills" / "refit" / "SKILL.md").read_text()
        assert "new" in installed

    def test_older_or_equal_version_does_not_downgrade(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0", body="current")
        project = tmp_path / "ws"
        sync_skills(project, source_root=source)

        _make_skill(tmp_path / "src2", "refit", "2.9.0", body="stale")
        result = sync_skills(project, source_root=tmp_path / "src2")

        assert result.skipped == ["refit"]
        installed = (project / ".claude" / "skills" / "refit" / "SKILL.md").read_text()
        assert "current" in installed

    def test_missing_version_treated_as_zero(self, tmp_path):
        source = tmp_path / "src"
        skill_dir = source / "refit"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: refit\n---\nbody\n", encoding="utf-8")
        project = tmp_path / "ws"

        first = sync_skills(project, source_root=source)
        second = sync_skills(project, source_root=source)

        assert first.installed == ["refit"]
        # Both versions parse to (0,); equal ⇒ no churn.
        assert second.skipped == ["refit"]

    def test_directory_without_skill_md_ignored(self, tmp_path):
        source = tmp_path / "src"
        (source / "not-a-skill").mkdir(parents=True)
        (source / "not-a-skill" / "README.md").write_text("x", encoding="utf-8")
        _make_skill(source, "refit", "1.0.0")
        project = tmp_path / "ws"

        result = sync_skills(project, source_root=source)

        assert result.installed == ["refit"]
        assert not (project / ".claude" / "skills" / "not-a-skill").exists()

    def test_missing_source_root_is_noop(self, tmp_path):
        project = tmp_path / "ws"
        result = sync_skills(project, source_root=tmp_path / "does-not-exist")

        assert result.changed is False
        assert not (project / ".claude").exists()

    def test_multi_file_skill_copied_whole(self, tmp_path):
        source = tmp_path / "src"
        skill_dir = _make_skill(source, "refit", "1.0.0")
        (skill_dir / "reference.md").write_text("extra\n", encoding="utf-8")
        project = tmp_path / "ws"

        sync_skills(project, source_root=source)

        assert (project / ".claude" / "skills" / "refit" / "reference.md").read_text() == "extra\n"
