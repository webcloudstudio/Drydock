"""Unit tests for skill provisioning (drydock.skills)."""

from __future__ import annotations

from pathlib import Path

from drydock.skills import AGENT_SKILLS_DIRS, sync_skills


def test_shipped_drydock_uat_skill_loads_versioned_diagnostic_prompt():
    skill = Path("Rigging/skills/drydock-uat/SKILL.md").read_text(encoding="utf-8")

    assert "name: drydock-uat" in skill
    assert "load_prompt('uat_diagnostic')" in skill
    assert "do not reconstruct the prompt from memory" in skill
    assert "Do not edit files or rerun the UAT" in skill


def test_metadata_version_upgrades_a_skill(tmp_path):
    source = tmp_path / "src"
    skill_dir = source / "diagnose"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: diagnose\nmetadata:\n  version: '2.0.0'\n---\nnew\n", encoding="utf-8"
    )
    project = tmp_path / "ws"
    for relative in AGENT_SKILLS_DIRS.values():
        installed = project / relative / "diagnose"
        installed.mkdir(parents=True)
        (installed / "SKILL.md").write_text(
            "---\nname: diagnose\nversion: 1.0.0\n---\nold\n", encoding="utf-8"
        )

    results = sync_skills(project, source_root=source)

    assert all(result.updated == ["diagnose"] for result in results.values())


def _make_skill(root: Path, name: str, version: str, body: str = "body") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: {version}\n---\n{body}\n", encoding="utf-8"
    )
    return skill_dir


class TestSyncSkills:
    def test_fresh_install_copies_all_skills_to_every_agent(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0")
        _make_skill(source, "apply-refit", "1.0.0")
        project = tmp_path / "ws"

        results = sync_skills(project, source_root=source)

        assert set(results) == set(AGENT_SKILLS_DIRS)
        for agent, relative in AGENT_SKILLS_DIRS.items():
            result = results[agent]
            assert sorted(result.installed) == ["apply-refit", "refit"]
            assert result.updated == []
            assert result.changed is True
            assert (project / relative / "refit" / "SKILL.md").is_file()
            assert (project / relative / "apply-refit" / "SKILL.md").is_file()

    def test_second_run_is_idempotent_for_every_agent(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0")
        project = tmp_path / "ws"

        sync_skills(project, source_root=source)
        results = sync_skills(project, source_root=source)

        for result in results.values():
            assert result.installed == []
            assert result.updated == []
            assert result.skipped == ["refit"]
            assert result.changed is False

    def test_newer_version_upgrades_every_agent(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0", body="old")
        project = tmp_path / "ws"
        sync_skills(project, source_root=source)

        # Ship a newer version with changed content.
        _make_skill(tmp_path / "src2", "refit", "3.1.0", body="new")
        results = sync_skills(project, source_root=tmp_path / "src2")

        for agent, relative in AGENT_SKILLS_DIRS.items():
            assert results[agent].updated == ["refit"]
            installed = (project / relative / "refit" / "SKILL.md").read_text()
            assert "new" in installed

    def test_older_or_equal_version_does_not_downgrade(self, tmp_path):
        source = tmp_path / "src"
        _make_skill(source, "refit", "3.0.0", body="current")
        project = tmp_path / "ws"
        sync_skills(project, source_root=source)

        _make_skill(tmp_path / "src2", "refit", "2.9.0", body="stale")
        results = sync_skills(project, source_root=tmp_path / "src2")

        for agent, relative in AGENT_SKILLS_DIRS.items():
            assert results[agent].skipped == ["refit"]
            installed = (project / relative / "refit" / "SKILL.md").read_text()
            assert "current" in installed

    def test_missing_version_treated_as_zero(self, tmp_path):
        source = tmp_path / "src"
        skill_dir = source / "refit"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: refit\n---\nbody\n", encoding="utf-8")
        project = tmp_path / "ws"

        first = sync_skills(project, source_root=source)
        second = sync_skills(project, source_root=source)

        for agent in AGENT_SKILLS_DIRS:
            assert first[agent].installed == ["refit"]
            # Both versions parse to (0,); equal ⇒ no churn.
            assert second[agent].skipped == ["refit"]

    def test_directory_without_skill_md_ignored(self, tmp_path):
        source = tmp_path / "src"
        (source / "not-a-skill").mkdir(parents=True)
        (source / "not-a-skill" / "README.md").write_text("x", encoding="utf-8")
        _make_skill(source, "refit", "1.0.0")
        project = tmp_path / "ws"

        results = sync_skills(project, source_root=source)

        for agent, relative in AGENT_SKILLS_DIRS.items():
            assert results[agent].installed == ["refit"]
            assert not (project / relative / "not-a-skill").exists()

    def test_missing_source_root_is_noop(self, tmp_path):
        project = tmp_path / "ws"
        results = sync_skills(project, source_root=tmp_path / "does-not-exist")

        for agent, relative in AGENT_SKILLS_DIRS.items():
            assert results[agent].changed is False
            assert not (project / relative).exists()

    def test_multi_file_skill_copied_whole(self, tmp_path):
        source = tmp_path / "src"
        skill_dir = _make_skill(source, "refit", "1.0.0")
        (skill_dir / "reference.md").write_text("extra\n", encoding="utf-8")
        project = tmp_path / "ws"

        sync_skills(project, source_root=source)

        for relative in AGENT_SKILLS_DIRS.values():
            assert (project / relative / "refit" / "reference.md").read_text() == "extra\n"
