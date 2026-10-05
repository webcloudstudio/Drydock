"""Mechanical lineage against real temporary Git repositories, without agents."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from drydock import build_git
from drydock.build import StepAssembly, StepFile
from drydock.build_lineage import BuildLineage, now
from drydock.build_plan import parse_build_plan
from drydock.errors import SpecificationError
from drydock.llm import LlmStats


@pytest.fixture(autouse=True)
def git_identity(monkeypatch):
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Build test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "build@example.invalid")


def setup_lineage(tmp_path, monkeypatch, *, same_repository=False):
    target = tmp_path / "target"
    target.mkdir()
    app = target if same_repository else tmp_path / "application"
    app.mkdir(exist_ok=True)
    (target / "MANIFEST.md").write_text(
        "# MANIFEST: Demo\nstate: approved\n\n"
        "## story 1: Screen\nid: screen\nblock: 3\nphase: 2\n"
        "implements: SCREEN.md\ncontext: DEPENDENCY.md\nstate: pending\n"
    )
    spec = target / "SCREEN.md"
    spec.write_text("Screen specification\n")
    node = parse_build_plan(target / "MANIFEST.md").blocks[0]
    source = StepFile("SCREEN.md", "implements", 20, 5, False, spec)
    assembly = StepAssembly(
        "screen",
        "story",
        "Screen",
        None,
        (
            source,
            replace(source, name="DEPENDENCY.md", role="context"),
            replace(source, name="python_compact.md", role="stack"),
        ),
        "",
        0,
        20,
        5,
        False,
        50000,
    )
    monkeypatch.setenv("DRYDOCK_PARENT_TRANSCRIPT", str(tmp_path / "run.log"))
    lines = []
    lineage = BuildLineage("Demo", target, app, lines.append)
    lineage.begin("block-3", "Screen", (node,), (assembly,))
    return lineage, target, app, lines


def rows(target):
    return [json.loads(line) for line in (target / "BUILD_LINEAGE.jsonl").read_text().splitlines()]


def record(lineage, result=None, attempt=0):
    lineage.record(started_at=now(), result=result, attempt=attempt, status="built", details={})


def test_records_manifest_identity_stats_logs_and_committed_changes(tmp_path, monkeypatch):
    lineage, target, app, lines = setup_lineage(tmp_path, monkeypatch)
    (app / "screen.py").write_text("screen\n")
    (app / ".env").write_text("secret\n")
    result = SimpleNamespace(
        execution_id="exec-42",
        stats=LlmStats(input_tokens=12, output_tokens=8),
        record={"job": {"parameters": {"attempt": 0}}},
        artifacts=SimpleNamespace(paths=lambda: {"execution_records": "/logs/llm.jsonl"}),
    )
    record(lineage, result)
    row = rows(target)[0]
    assert row["implements"] == ["SCREEN.md"]
    assert row["manifest"]["nodes"][0]["block"] == "3"
    assert row["manifest"]["nodes"][0]["context"] == ["DEPENDENCY.md"]
    assert row["stats"]["input_tokens"] == 12
    assert row["execution_id"] == "exec-42"
    assert row["run_log"].endswith("run.log")
    assert row["artifacts"]["execution_records"] == "/logs/llm.jsonl"
    assert row["application"]["files"] == [{"path": "screen.py", "status": "A"}]
    assert len(row["application"]["after_commit"]) == 40
    assert (
        build_git.git(app, "show", f"{row['application']['after_commit']}:screen.py") == "screen\n"
    )
    assert row["target_checkpoint"]["commit_trailer"] in build_git.git(
        target, "log", "-1", "--format=%B"
    )
    assert "git: block-3 | SCREEN.md | call=1 | app=" in lines[-1]
    assert "DEPENDENCY" not in lines[-1] and "compact" not in lines[-1]
    assert not build_git.git(app, "status", "--porcelain")


def test_repeated_executions_preserve_added_modified_deleted_and_renamed(tmp_path, monkeypatch):
    lineage, target, app, _ = setup_lineage(tmp_path, monkeypatch)
    (app / "old name.txt").write_text("original\n" * 20)
    (app / "remove.py").write_text("delete\n")
    (app / "modify.py").write_text("one\n")
    record(lineage)
    (app / "old name.txt").rename(app / "new name.txt")
    (app / "remove.py").unlink()
    (app / "modify.py").write_text("two\n")
    record(lineage, attempt=1)
    record(lineage, attempt=2)
    first, second, third = rows(target)
    changes = {item["path"]: item for item in second["application"]["files"]}
    assert changes["remove.py"]["status"] == "D"
    assert changes["modify.py"]["status"] == "M"
    assert changes["new name.txt"]["old_path"] == "old name.txt"
    assert first["application"]["after_commit"] == second["application"]["before_commit"]
    assert first["step_id"] == second["step_id"] == third["step_id"]
    assert len({row["record_id"] for row in rows(target)}) == 3
    assert third["application"]["committed"] is False
    assert third["application"]["files"] == []


def test_baseline_is_not_attributed_and_parent_repository_is_not_used(tmp_path, monkeypatch):
    build_git.prepare(tmp_path)
    (tmp_path / "parent.txt").write_text("outside\n")
    parent = build_git.checkpoint(tmp_path, "Parent baseline")
    lineage, target, app, _ = setup_lineage(tmp_path, monkeypatch)
    assert build_git.head(tmp_path) == parent
    assert build_git.head(target)
    assert build_git.head(app) is None
    (app / "file.py").write_text("new\n")
    record(lineage)
    assert build_git.head(tmp_path) == parent


def test_same_repository_can_checkpoint_output_and_receipt(tmp_path, monkeypatch):
    lineage, target, app, _ = setup_lineage(tmp_path, monkeypatch, same_repository=True)
    (app / "app.py").write_text("app\n")
    record(lineage)
    (app / "app.py").write_text("updated\n")
    record(lineage, attempt=1)
    assert rows(target)[1]["application"]["files"] == [{"path": "app.py", "status": "M"}]


def test_target_commit_failure_is_recovered_without_duplicate_rows(tmp_path, monkeypatch):
    lineage, target, app, lines = setup_lineage(tmp_path, monkeypatch)
    (app / "app.py").write_text("app\n")
    checkpoint = build_git.checkpoint

    def fail_target(root, message):
        if root == target:
            raise SpecificationError("commit hook failed")
        return checkpoint(root, message)

    monkeypatch.setattr(build_git, "checkpoint", fail_target)
    with pytest.raises(SpecificationError, match="commit hook failed"):
        record(lineage)
    monkeypatch.setattr(build_git, "checkpoint", checkpoint)
    recovered = BuildLineage("Demo", target, app, lines.append)
    recovered.prepare()
    assert len(rows(target)) == 1
    assert rows(target)[0]["target_checkpoint"]["commit_trailer"] in build_git.git(
        target, "log", "-1", "--format=%B"
    )
    assert any("git: recovered block-3 | SCREEN.md" in line for line in lines)


def test_application_failure_preserves_pending_lineage_and_stops(tmp_path, monkeypatch):
    lineage, target, app, _ = setup_lineage(tmp_path, monkeypatch)
    (app / "app.py").write_text("app\n")
    checkpoint = build_git.checkpoint
    monkeypatch.setattr(
        build_git,
        "checkpoint",
        lambda *args: (_ for _ in ()).throw(SpecificationError("Git failed")),
    )
    with pytest.raises(SpecificationError, match="Git failed"):
        record(lineage)
    monkeypatch.setattr(build_git, "checkpoint", checkpoint)
    with pytest.raises(SpecificationError, match="Interrupted build checkpoint needs inspection"):
        BuildLineage("Demo", target, app).prepare()
    assert not (target / "BUILD_LINEAGE.jsonl").exists()
