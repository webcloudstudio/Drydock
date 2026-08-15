from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from drydock.report_render import _relative
from drydock.uat_report import (
    build_case_kit,
    build_kit_index,
    prune_generated,
    write_kit_index,
)


def test_recorded_absolute_artifact_is_relative_to_a_project_relative_report_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = Path("uat/ReadingList/runs/run-1")
    artifact = tmp_path / root / "workspace/logs/call.llm.log"

    assert _relative(artifact, root) == "workspace/logs/call.llm.log"


def _case(
    kit_root: Path,
    *,
    run_id: str = "20260101T000000.000000Z",
    status: str = "passed",
    failing: bool = False,
    degraded: tuple[str, ...] = (),
    attestations: tuple[str, ...] = (),
) -> Path:
    """Write a minimal but complete UAT run directory shaped like a real kit run."""
    case = kit_root / "runs" / run_id
    commands_dir = case / "evidence" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "01-init.stdout.log").write_text("initialized\n", encoding="utf-8")
    (commands_dir / "01-init.stderr.log").write_text("", encoding="utf-8")
    (commands_dir / "02-build.stdout.log").write_text("built\n", encoding="utf-8")
    (commands_dir / "02-build.stderr.log").write_text("boom: acceptance failed\n", encoding="utf-8")
    (case / "evidence" / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "commands": [], "llm_artifacts": []}), encoding="utf-8"
    )
    (case / "evidence" / "llm.jsonl").write_text("", encoding="utf-8")

    (case / "sources").mkdir()
    (case / "sources" / "spec.txt").write_text("# spec\n", encoding="utf-8")
    build = case / "build" / "commonmark"
    build.mkdir(parents=True)
    (build / "parser.py").write_text("VALUE = 1\n", encoding="utf-8")
    blueprint = case / "workspace" / "targets" / "commonmark" / "blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "ARCHITECTURE.md").write_text("# architecture\n", encoding="utf-8")
    (case / "workspace" / "logs").mkdir()
    (case / "workspace" / "logs" / "noise.log").write_text("x\n", encoding="utf-8")

    (case / "result.json").write_text(
        json.dumps({
            "fixture": "commonmark",
            "target": "commonmark",
            "run_id": run_id,
            "status": status,
            "elapsed_ms": 1500,
            "build_passes": 1,
            "output_dir": str(case),
            "evidence_dir": str(case / "evidence"),
            "error": "commonmark: build exited 1" if failing else "",
            "degraded": list(degraded),
            "attestations": list(attestations),
            "score_exit_codes": {"acceptance": 0},
            "usage": {"calls": 2, "input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 3},
            "environment": {"provider": "codex", "model": "test-model"},
            "commands": [
                {
                    "argv": ["/opt/venv/bin/python", "-m", "drydock", "init", "commonmark"],
                    "label": "01-init",
                    "returncode": 0,
                    "elapsed_ms": 100,
                    "cwd": str(case / "workspace"),
                    "stdout_path": str(commands_dir / "01-init.stdout.log"),
                    "stderr_path": str(commands_dir / "01-init.stderr.log"),
                },
                {
                    "argv": ["/opt/venv/bin/python", "-m", "drydock", "build", "commonmark"],
                    "label": "02-build",
                    "returncode": 1 if failing else 0,
                    "elapsed_ms": 900,
                    "cwd": str(case / "workspace"),
                    "stdout_path": str(commands_dir / "02-build.stdout.log"),
                    "stderr_path": str(commands_dir / "02-build.stderr.log"),
                },
            ],
        }),
        encoding="utf-8",
    )
    return case


def _mirror(case: Path, name: str = "call.prompt.md", body: str = "assembled prompt\n") -> None:
    """Record one transcript the way a real run does: in evidence, and again in the workspace.

    A run drives a Drydock workspace, so every prompt it assembles exists twice on disk. The
    kit has to choose one copy to publish; the fixture reproduces the choice.
    """
    (case / "evidence" / "prompts").mkdir(exist_ok=True)
    (case / "evidence" / "prompts" / name).write_text(body, encoding="utf-8")
    (case / "workspace" / "logs" / name).write_text(body, encoding="utf-8")
    llm_log = case / "workspace" / "logs" / "call.llm.log"
    llm_log.write_text("tokens: 5\n", encoding="utf-8")
    (case / "evidence" / "llm.jsonl").write_text(
        json.dumps({
            "execution_id": "exec-1",
            "status": "completed",
            "job": {"command_name": "build", "llm": "codex", "model": "test-model"},
            "result": {"returncode": 0, "stats": {"elapsed_ms": 10, "input_tokens": 5}},
            # The run records where it wrote the file, which is its own workspace.
            "artifacts": {
                "prompt": str(case / "workspace" / "logs" / name),
                "llm_log": str(llm_log),
            },
        })
        + "\n",
        encoding="utf-8",
    )


def _ignored(case: Path) -> set[str]:
    return {
        line.lstrip("/")
        for line in (case / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def _links(page: Path) -> set[str]:
    return set(re.findall(r'href="([^"]+)"', page.read_text(encoding="utf-8")))


def test_case_kit_links_resolve_and_paths_are_relative(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    index = build_case_kit(case)

    links = _links(index)
    assert links
    assert all(not link.startswith(("/", "http")) for link in links)
    assert all((case / link).exists() for link in links)
    # Every text artifact is reached through its styled viewer, never as raw text.
    assert "view/evidence/commands/01-init.stdout.log.html" in links
    assert "view/build/commonmark/parser.py.html" in links


def test_case_kit_rewrites_absolute_paths_in_the_run_record(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    build_case_kit(case)

    result = json.loads((case / "result.json").read_text(encoding="utf-8"))
    assert result["output_dir"] == "."
    assert result["evidence_dir"] == "evidence"
    assert result["commands"][0]["stdout_path"] == "evidence/commands/01-init.stdout.log"
    assert str(tmp_path) not in (case / "result.json").read_text(encoding="utf-8")


def test_case_kit_writes_verifiable_checksums_for_delivered_code(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    build_case_kit(case)

    sums = (case / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    indexed = {line.split("  ", 1)[1] for line in sums}
    assert "build/commonmark/parser.py" in indexed
    assert "sources/spec.txt" in indexed
    assert "workspace/targets/commonmark/blueprint/ARCHITECTURE.md" in indexed
    assert "result.json" in indexed
    assert "index.html" not in indexed
    assert "SHA256SUMS" not in indexed
    manifest = json.loads((case / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    assert "Build" in manifest["artifacts"]
    assert manifest["environment"]["provider"] == "codex"


def test_the_written_checksums_verify_against_the_kit_they_describe(tmp_path: Path) -> None:
    # The receipt's headline claim is `sha256sum -c SHA256SUMS`, so every recorded digest must
    # match the file as the rebuild left it — including artifacts the rebuild itself rewrites.
    case = _case(tmp_path / "run")

    build_case_kit(case)

    for line in (case / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        assert hashlib.sha256((case / relative).read_bytes()).hexdigest() == digest, relative

    manifest = json.loads((case / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    listed = {record["path"] for records in manifest["artifacts"].values() for record in records}
    assert "evidence/manifest.json" not in listed


def test_case_kit_reports_failure_and_quotes_the_recorded_output(tmp_path: Path) -> None:
    case = _case(tmp_path / "run", status="failed", failing=True)

    index = build_case_kit(case)

    page = index.read_text(encoding="utf-8")
    assert "commonmark: FAILED" in page
    assert "commonmark: build exited 1" in page
    assert "boom: acceptance failed" in page
    assert "FAIL 1" in page


def test_case_kit_states_success_only_when_every_command_exited_zero(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert "commonmark: PASSED" in page
    assert "every required command exited 0" in page
    assert "drydock build commonmark" in page


def test_case_kit_marks_a_resumed_run_instead_of_claiming_a_clean_lifecycle(
    tmp_path: Path,
) -> None:
    # A resumed run's table still carries the prior attempt's failed rows, so the passing
    # banner must say where the run re-entered rather than vouch for every command.
    case = _case(tmp_path / "run", failing=True)
    result = json.loads((case / "result.json").read_text(encoding="utf-8"))
    result["status"] = "passed"
    result["error"] = ""
    result["resumed_from"] = "build"
    (case / "result.json").write_text(json.dumps(result), encoding="utf-8")

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert "commonmark: PASSED" in page
    assert "Resumed at" in page
    assert "every required command exited 0" not in page


def test_case_kit_links_a_stream_only_when_it_captured_output(tmp_path: Path) -> None:
    # An empty stderr is the normal case for a command that printed nothing to it, so the step
    # offers no link to it and it does not read as evidence of a problem. The Evidence tree
    # still lists the file, because the tree is the directory, not a verdict.
    case = _case(tmp_path / "run")

    page = build_case_kit(case).read_text(encoding="utf-8")

    steps = page.split('id="panel-evidence"')[0]
    assert "evidence/commands/01-init.stderr.log" not in steps
    assert "evidence/commands/02-build.stderr.log" in steps


def test_case_kit_links_llm_activity_beside_the_command_streams(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    _mirror(case)
    stdout = case / "evidence" / "commands" / "02-build.stdout.log"
    stdout.write_text("2026-01-01  Calling CODEX/test-model (build)...\n", encoding="utf-8")

    page = build_case_kit(case).read_text(encoding="utf-8")
    steps = page.split('id="panel-llm"')[0]

    assert "<th>stdout</th><th>stderr</th><th>llm</th>" in steps
    assert "view/workspace/logs/call.llm.log.html" in steps
    assert ">llm</a>" in steps


def test_case_kit_derives_a_legacy_sibling_llm_activity_log(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    _mirror(case)
    records = case / "evidence" / "llm.jsonl"
    record = json.loads(records.read_text(encoding="utf-8"))
    del record["artifacts"]["llm_log"]
    records.write_text(json.dumps(record) + "\n", encoding="utf-8")
    stdout = case / "evidence" / "commands" / "02-build.stdout.log"
    stdout.write_text("2026-01-01  Calling CODEX/test-model (build)...\n", encoding="utf-8")

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert "view/workspace/logs/call.llm.log.html" in page


def test_case_kit_opens_every_evidence_link_in_its_own_tab(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    page = build_case_kit(case).read_text(encoding="utf-8")

    anchors = re.findall(r"<a\b[^>]*>", page)
    assert anchors
    assert all('target="_blank"' in anchor for anchor in anchors)


def test_case_kit_files_the_evidence_into_one_tree_per_directory(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "run", status="failed", failing=True)
    (case / "evidence" / "llm.jsonl").write_text(
        json.dumps({
            "execution_id": "exec-1",
            "status": "completed",
            "job": {"command_name": "build", "llm": "codex", "model": "test-model"},
            "result": {
                "returncode": 0,
                "stats": {"elapsed_ms": 10, "input_tokens": 5, "cached_input_tokens": 1},
            },
            "artifacts": {"prompt": str(case / "sources" / "spec.txt")},
        })
        + "\n",
        encoding="utf-8",
    )

    page = build_case_kit(case).read_text(encoding="utf-8")

    tabs = re.findall(r'<button type="button" data-panel="[^"]+">?[^>]*>([^<]+)</button>', page)
    assert tabs == ["Steps", "Error", "LLM", "Build", "Evidence", "Sources", "Workspace"]
    # Each tree is stated relative to the kit, not to the run directory it is rendered in.
    assert "runs/20260101T000000.000000Z/workspace/" in page
    # Digests belong in SHA256SUMS; a wall of hashes is not what a reviewer reads.
    assert re.search(r"[0-9a-f]{64}", page) is None


def test_case_kit_publishes_a_mirrored_transcript_once_from_evidence(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    _mirror(case)

    index = build_case_kit(case)

    links = _links(index)
    assert "view/evidence/prompts/call.prompt.md.html" in links
    assert "view/workspace/logs/call.prompt.md.html" not in links
    # The second copy is not rendered at all, so the kit carries one viewer, not two.
    assert not (case / "view" / "workspace" / "logs" / "call.prompt.md.html").exists()


def test_case_kit_ignores_the_copy_it_withheld_and_nothing_it_links(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    _mirror(case)

    index = build_case_kit(case)

    assert "workspace/logs/call.prompt.md" in _ignored(case)
    # The invariant that matters: index.html is the only way a committed kit is read, so a
    # path it links must never be a path git was told to skip.
    assert _ignored(case).isdisjoint(_links(index))


def test_case_kit_points_a_recorded_transcript_link_at_the_copy_it_published(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "run")
    _mirror(case)

    index = build_case_kit(case)

    # The run recorded the workspace path; the receipt has to resolve it to the published copy
    # or the LLM table links a file the kit deliberately withheld.
    assert "view/evidence/prompts/call.prompt.md.html" in _links(index)
    assert all("workspace/logs/call.prompt.md" not in link for link in _links(index))


def test_case_kit_keeps_workspace_files_that_evidence_does_not_carry(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    _mirror(case)

    index = build_case_kit(case)

    links = _links(index)
    # The Blueprint the run drove has no evidence twin and is the record of what was built.
    assert "view/workspace/targets/commonmark/blueprint/ARCHITECTURE.md.html" in links
    assert "view/workspace/logs/noise.log.html" in links
    assert _ignored(case) == {"workspace/logs/call.prompt.md"}


def test_case_kit_keeps_an_empty_workspace_log_beside_an_empty_evidence_log(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "run")
    # Every empty file shares one digest. "This command wrote no stderr" is a fact about the
    # run, so it must not be deduplicated away against an unrelated empty file.
    (case / "workspace" / "logs" / "build.stderr.log").write_text("", encoding="utf-8")

    page = build_case_kit(case).read_text(encoding="utf-8")

    # The fixture's evidence already holds an empty 01-init.stderr.log to collide with.
    assert _ignored(case) == set()
    assert "build.stderr.log" in page


def test_case_kit_withholds_agent_scaffolding_copied_into_the_workspace(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    skill = case / "workspace" / ".claude" / "skills" / "refit"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# refit\n", encoding="utf-8")

    index = build_case_kit(case)

    # Drydock's own tooling, not a record of what the run produced.
    assert "workspace/.claude/skills/refit/SKILL.md" in _ignored(case)
    assert all(".claude" not in link for link in _links(index))


def test_case_kit_drops_the_error_tab_when_nothing_failed(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert 'data-panel="error"' not in page
    assert 'data-panel="steps"' in page


def test_case_kit_stamps_the_verdict_and_carries_the_drydock_mark(tmp_path: Path) -> None:
    passing = build_case_kit(_case(tmp_path / "pass")).read_text(encoding="utf-8")
    failing = build_case_kit(_case(tmp_path / "fail", status="failed", failing=True)).read_text(
        encoding="utf-8"
    )

    assert '<div class="stamp pass"><span class="mark">Approved</span>' in passing
    assert '<div class="stamp fail"><span class="mark">Rejected</span>' in failing
    # The mark is inlined, so a kit copied off this machine keeps its letterhead.
    assert 'src="data:image/png;base64,' in passing


def test_case_kit_stamps_each_command_result_rather_than_printing_an_exit_code(
    tmp_path: Path,
) -> None:
    page = build_case_kit(_case(tmp_path / "run", status="failed", failing=True)).read_text(
        encoding="utf-8"
    )

    assert '<span class="tag pass" title="exit 0">OK</span>' in page
    assert '<span class="tag fail" title="exit 1">FAIL 1</span>' in page


def test_case_kit_never_labels_a_drydock_status_exit_as_a_failure(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    _stage(
        case,
        "03-complete",
        ["/opt/venv/bin/python", "-m", "drydock", "status", "commonmark", "--check"],
        1,
    )

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert '<span class="tag unknown" title="exit 1">EXIT 1</span>' in page
    assert 'Target completion check passed</td><td><span class="tag unknown">UNPROVEN' in page
    assert 'drydock status commonmark</code></td><td><span class="tag fail"' not in page


def test_case_kit_reports_usage_as_cached_and_uncached(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    (case / "evidence" / "llm.jsonl").write_text(
        json.dumps({
            "execution_id": "exec-1",
            "status": "completed",
            "job": {"command_name": "build", "llm": "codex", "model": "test-model"},
            "result": {
                "returncode": 0,
                "stats": {"elapsed_ms": 10, "input_tokens": 100, "cached_input_tokens": 60},
            },
            "artifacts": {},
        })
        + "\n",
        encoding="utf-8",
    )

    page = build_case_kit(case).read_text(encoding="utf-8")

    # Codex counts cache reads inside input_tokens, so 100 sent with 60 read from cache is
    # 40 charged at full rate. That is the split the provider bills.
    assert "<th>Cached</th><th>Uncached</th><th>Output</th>" in page
    assert '<td class="num">60</td><td class="num">40</td>' in page
    assert "cached 4 · uncached 6 · output 3" in page


def test_case_kit_names_the_directory_the_build_delivered_into(tmp_path: Path) -> None:
    page = build_case_kit(_case(tmp_path / "run")).read_text(encoding="utf-8")

    assert "runs/20260101T000000.000000Z/build/commonmark/" in page


def test_case_kit_marks_unprocessed_provider_output_as_raw(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    raw = case / "evidence" / "provider_raw"
    raw.mkdir()
    (raw / "call.raw.jsonl").write_text('{"type":"event"}\n', encoding="utf-8")

    page = build_case_kit(case).read_text(encoding="utf-8")

    marked = re.findall(r'>([^<]+)</a></td><td class="num">\d+</td><td><span class="tag raw"', page)
    # The provider transcript and the workspace runtime log; neither is the reviewable record.
    assert marked == ["call.raw.jsonl", "noise.log"]


def test_case_kit_prunes_regenerable_caches(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")
    cache = case / "build" / "commonmark" / "__pycache__"
    cache.mkdir()
    (cache / "parser.cpython-312.pyc").write_bytes(b"\x00")

    build_case_kit(case)

    assert not cache.exists()
    assert "__pycache__" not in (case / "SHA256SUMS").read_text(encoding="utf-8")


def test_prune_generated_ignores_a_missing_directory(tmp_path: Path) -> None:
    assert prune_generated(tmp_path / "absent") == 0


def test_kit_index_lists_every_run_and_reports_the_latest_verdict(tmp_path: Path) -> None:
    kit = tmp_path / "CommonMark"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    (kit / "README.md").write_text("# CommonMark\n", encoding="utf-8")
    _case(kit, run_id="20260101T000000.000000Z")
    case = _case(kit, run_id="20260102T000000.000000Z", status="failed", failing=True)

    index = build_kit_index(kit)

    page = index.read_text(encoding="utf-8")
    assert "latest run FAILED" in page
    # Newest first, and every run is reachable from the landing page.
    assert page.index("20260102T000000.000000Z") < page.index("20260101T000000.000000Z")
    assert "runs/20260102T000000.000000Z/index.html" in page
    assert (case / "index.html").is_file()
    assert all((kit / link).exists() for link in _links(index))


def test_kit_index_is_written_for_a_kit_with_no_runs(tmp_path: Path) -> None:
    kit = tmp_path / "CommonMark"
    kit.mkdir()

    page = build_kit_index(kit).read_text(encoding="utf-8")

    assert "latest run UNKNOWN" in page
    assert "No runs have been recorded" in page


def test_kit_index_is_a_project_page_over_the_documents_and_bundles_on_disk(
    tmp_path: Path,
) -> None:
    kit = tmp_path / "CommonMark"
    (kit / "sources").mkdir(parents=True)
    (kit / "inputs").mkdir()
    (kit / "updates").mkdir()
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    (kit / "README.md").write_text("# CommonMark\n", encoding="utf-8")
    (kit / "inputs" / "SEA_TRIALS.md").write_text("# Sea Trials\n", encoding="utf-8")
    (kit / "inputs" / "TECHNOLOGY_STACK.md").write_text("# Stack\n", encoding="utf-8")
    (kit / "NOTES.txt").write_text("loose file\n", encoding="utf-8")
    (kit / ".nojekyll").write_text("", encoding="utf-8")
    (kit / "sources" / "spec.md").write_text("# spec\n", encoding="utf-8")
    (kit / "updates" / "spec.md").write_text("# revised spec\n", encoding="utf-8")
    _case(kit, run_id="20260103T000000.000000Z")

    index = build_kit_index(kit)
    page = index.read_text(encoding="utf-8")

    assert "newest recorded run" in page
    for link in (
        "runs/20260103T000000.000000Z/index.html",
        "view/inputs/SEA_TRIALS.md.html",
        "view/inputs/TECHNOLOGY_STACK.md.html",
        "view/NOTES.txt.html",
        "view/sources/spec.md.html",
        "view/updates/spec.md.html",
    ):
        assert f'href="{link}"' in page
    # A kit page never links a document the kit does not ship, and publishing markers are
    # not project documents.
    assert "USER_NOTES.md" not in page
    assert ".nojekyll" not in page
    assert all((kit / link).exists() for link in _links(index))


def test_a_viewer_renders_markdown_inside_the_report_styling(tmp_path: Path) -> None:
    kit = tmp_path / "CommonMark"
    (kit / "inputs").mkdir(parents=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    (kit / "inputs" / "SEA_TRIALS.md").write_text(
        "# Sea Trials\n\n| ID | Verdict |\n|---|---|\n| st-001 | PASS |\n", encoding="utf-8"
    )

    build_kit_index(kit)

    viewer = (kit / "view" / "inputs" / "SEA_TRIALS.md.html").read_text(encoding="utf-8")
    assert "<h1>Sea Trials</h1>" in viewer
    assert "<td>st-001</td>" in viewer
    # The viewer carries the report's stylesheet and keeps the raw artifact one click away.
    assert 'href="../../assets/kit.css"' in viewer
    assert 'href="../../inputs/SEA_TRIALS.md"' in viewer
    assert (kit / "assets" / "kit.css").is_file()


def test_a_viewer_shows_a_log_as_source_and_nests_its_links_by_depth(tmp_path: Path) -> None:
    kit = tmp_path / "CommonMark"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    case = _case(kit, run_id="20260105T000000.000000Z")

    build_kit_index(kit)

    viewer = (case / "view" / "evidence" / "commands" / "01-init.stdout.log.html").read_text(
        encoding="utf-8"
    )
    assert "<pre>initialized" in viewer
    assert 'href="../../../assets/kit.css"' in viewer
    assert 'href="../../../evidence/commands/01-init.stdout.log"' in viewer
    assert 'href="../../../index.html"' in viewer


def test_generated_viewers_are_never_checksummed_and_never_outlive_their_artifact(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "run")

    build_case_kit(case)

    indexed = {
        line.split("  ", 1)[1]
        for line in (case / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    }
    assert not any(path.startswith(("view/", "assets/")) for path in indexed)

    stale = case / "view" / "evidence" / "commands" / "01-init.stdout.log.html"
    assert stale.is_file()
    (case / "evidence" / "commands" / "01-init.stdout.log").unlink()
    build_case_kit(case)
    assert not stale.exists()


def test_a_binary_artifact_keeps_its_raw_link_instead_of_a_viewer(tmp_path: Path) -> None:
    kit = tmp_path / "CommonMark"
    kit.mkdir()
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    (kit / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n binary")

    page = build_kit_index(kit).read_text(encoding="utf-8")

    assert 'href="diagram.png"' in page
    assert not (kit / "view" / "diagram.png.html").exists()


def test_kit_index_omits_a_bundle_directory_the_kit_does_not_ship(tmp_path: Path) -> None:
    kit = tmp_path / "Toml"
    (kit / "sources").mkdir(parents=True)
    (kit / "sources" / "spec.md").write_text("# spec\n", encoding="utf-8")
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")

    page = build_kit_index(kit).read_text(encoding="utf-8")

    assert "<h3>sources/</h3>" in page
    assert "<h3>updates/</h3>" not in page


def test_write_kit_index_refreshes_the_landing_page_without_rebuilding_runs(
    tmp_path: Path,
) -> None:
    kit = tmp_path / "CommonMark"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    case = _case(kit, run_id="20260104T000000.000000Z")
    (case / "index.html").write_text("stale receipt\n", encoding="utf-8")

    page = write_kit_index(kit).read_text(encoding="utf-8")

    assert "runs/20260104T000000.000000Z/index.html" in page
    # The run receipt is left exactly as found; only `--report` rebuilds it.
    assert (case / "index.html").read_text(encoding="utf-8") == "stale receipt\n"


def test_case_kit_requires_a_run_record(tmp_path: Path) -> None:
    case = tmp_path / "run" / "commonmark"
    case.mkdir(parents=True)

    with pytest.raises(ValueError, match="no readable result.json"):
        build_case_kit(case)


# --- Degraded runs -----------------------------------------------------------


def test_a_degraded_run_is_reported_as_neither_a_pass_nor_a_failure(tmp_path: Path) -> None:
    kit = tmp_path / "Toml"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    case = _case(
        kit,
        status="degraded",
        failing=True,
        degraded=("initial-build-1 exited 1", "test exited 1"),
    )

    page = build_case_kit(case).read_text(encoding="utf-8")
    readme = (case / "README.md").read_text(encoding="utf-8")

    assert "Degraded: <code>initial-build-1 exited 1; test exited 1</code>" in page
    assert "Every later stage ran against the work the build produced." in page
    assert "Failure:" not in page
    assert "- Degraded: initial-build-1 exited 1; test exited 1" in readme


def test_a_passing_run_names_the_guardrails_a_human_still_owes(tmp_path: Path) -> None:
    """An unproven guardrail qualifies the report; it does not reject the run.

    Nothing demonstrated a violation, so the verdict stamp stays Approved. The criterion is
    still named, because a prohibition the evidence could not settle needs a person to settle it.
    """
    kit = tmp_path / "ReadingList"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    unproven = (
        "Guardrail st-003 is UNPROVEN (no code-bound proof references this criterion): "
        "The application shall never store a book whose title or author is empty."
    )
    case = _case(kit, attestations=(unproven,))

    page = build_case_kit(case).read_text(encoding="utf-8")
    readme = (case / "README.md").read_text(encoding="utf-8")

    assert "Manual verification required" in page
    assert "1 project guardrail could not be settled from evidence" in page
    assert "st-003 is UNPROVEN" in page
    assert "Approved" in page
    assert "Rejected" not in page
    assert "## Manual verification required" in readme
    assert f"- {unproven}" in readme


def test_a_fully_proven_run_reports_nothing_to_verify_by_hand(tmp_path: Path) -> None:
    kit = tmp_path / "ReadingList"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    case = _case(kit)

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert "Manual verification required" not in page
    assert "Manual verification required" not in (case / "README.md").read_text(encoding="utf-8")


def test_the_kit_index_tags_a_degraded_run_distinctly(tmp_path: Path) -> None:
    kit = tmp_path / "Toml"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    (kit / "README.md").write_text("# Toml\n", encoding="utf-8")
    _case(kit, status="degraded", degraded=("initial-build-1 exited 1",))

    page = build_kit_index(kit).read_text(encoding="utf-8")

    assert '<span class="tag degraded">DEGRADED</span>' in page


def _stage(case: Path, label: str, argv: list[str], returncode: int) -> None:
    """Add one more executed lifecycle stage to a fixture run, with its captured streams."""
    commands_dir = case / "evidence" / "commands"
    # stdout carries the stage's account of itself; stderr is empty, which is the ordinary case
    # for a command that succeeded. An empty stream is never linked or given a viewer page.
    (commands_dir / f"{label}.stdout.log").write_text(f"{label} ran\n", encoding="utf-8")
    (commands_dir / f"{label}.stderr.log").write_text("", encoding="utf-8")
    record = json.loads((case / "result.json").read_text(encoding="utf-8"))
    record["commands"].append({
        "argv": argv,
        "label": label,
        "returncode": returncode,
        "elapsed_ms": 10,
        "cwd": str(case / "workspace"),
        "stdout_path": str(commands_dir / f"{label}.stdout.log"),
        "stderr_path": str(commands_dir / f"{label}.stderr.log"),
    })
    (case / "result.json").write_text(json.dumps(record), encoding="utf-8")


def _complete_run(kit: Path) -> Path:
    """A run that executed every stage the receipt reports on."""
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    case = _case(kit)
    (case / "sources" / "toml-v1.0.0.md").write_text("# TOML 1.0.0\n", encoding="utf-8")
    _stage(
        case,
        "03-initial-complete",
        ["/opt/venv/bin/python", "-m", "drydock", "status", "commonmark", "--check"],
        1,
    )
    _stage(case, "04-test", ["sh", "sources/full_test.sh"], 0)
    _stage(
        case,
        "05-score-acceptance",
        ["/opt/venv/bin/python", "-m", "drydock", "score", "ac", "commonmark"],
        0,
    )
    _stage(
        case,
        "06-score-release",
        ["/opt/venv/bin/python", "-m", "drydock", "score", "release", "commonmark"],
        0,
    )
    (case / "workspace" / "targets" / "commonmark" / "MANIFEST.md").write_text(
        "# manifest\n", encoding="utf-8"
    )
    return case


def test_the_receipt_states_six_claims_in_fixed_order_with_their_recorded_outcomes(
    tmp_path: Path,
) -> None:
    case = _complete_run(tmp_path / "CommonMark")

    page = build_case_kit(case).read_text(encoding="utf-8")
    claims = re.findall(
        r"<td>(Lifecycle completed|External conformance suite passed|Target completion check "
        r"passed|Acceptance score passed|Release score passed|Integrity verification passed)"
        r'</td><td><span class="tag (pass|fail|unknown)">(\w+)</span>',
        page,
    )

    assert [claim for claim, _, _ in claims] == [
        "Lifecycle completed",
        "External conformance suite passed",
        "Target completion check passed",
        "Acceptance score passed",
        "Release score passed",
        "Integrity verification passed",
    ]
    assert [verdict for _, _, verdict in claims] == [
        "PASS",
        "PASS",
        "UNPROVEN",
        "PASS",
        "PASS",
        "PASS",
    ]
    # The receipt reports the tally rather than letting the run status stand for every claim.
    assert "5 of 6 claims proven" in page
    assert "1 receipt claim is not proven (target completion check passed)" in page


def test_the_receipt_marks_a_claim_the_run_never_recorded_as_unproven(tmp_path: Path) -> None:
    kit = tmp_path / "CommonMark"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    case = _case(kit)

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert page.count('<span class="tag unknown">UNPROVEN</span>') == 3
    assert "No external test command is defined for this project." in page
    assert "No completion check was recorded for this run." in page
    assert "No release score was recorded for this run." in page
    # An unproven claim is never dressed up as a pass by the run status above it.
    assert "3 receipt claims are not proven" in page


def test_the_run_readme_leads_with_the_receipt_before_any_drydock_internals(
    tmp_path: Path,
) -> None:
    case = _complete_run(tmp_path / "CommonMark")

    build_case_kit(case)
    readme = (case / "README.md").read_text(encoding="utf-8")

    order = [
        readme.index(heading)
        for heading in (
            "## Receipt",
            "## Run facts",
            "## RUN SUMMARY",
            "## RUN NOTES:",
            "## Commands",
        )
    ]
    assert order == sorted(order)
    assert "5 of 6 receipt claims proven" in readme
    assert "| Target completion check passed | UNPROVEN |" in readme
    assert "[`sources/toml-v1.0.0.md`](sources/toml-v1.0.0.md)" in readme
    assert "(build/commonmark)" in readme
    assert "One run is evidence of one run. It is not a benchmark." in readme
    assert "It states no general success rate" not in readme
    assert "LLM execution is not deterministic" not in readme


def test_the_kit_index_carries_the_latest_run_receipt_with_run_scoped_links(
    tmp_path: Path,
) -> None:
    kit = tmp_path / "CommonMark"
    case = _complete_run(kit)
    run_id = case.name

    index = build_kit_index(kit)
    page = index.read_text(encoding="utf-8")

    assert "5 of 6 claims proven" in page
    assert f'href="runs/{run_id}/view/evidence/commands/04-test.stdout.log.html"' in page
    assert f'href="runs/{run_id}/build/commonmark/"' in page
    assert "RUN SUMMARY" in page
    assert "Input specification" in page
    assert "Delivered Code" in page
    assert "Test Results" in page
    assert "RUN NOTES:" in page
    assert "It is not a security certification of the delivered code." in page
    assert "Verify this run in five minutes" not in page
    assert all((kit / link).exists() for link in _links(index))


def test_the_uat_page_keeps_its_own_stamp_after_the_renderer_was_shared(tmp_path: Path) -> None:
    """``report_render`` now serves two reports; the UAT stamp must still say UAT.

    The letterhead sub-line is the one piece of chrome that names which report a reader is
    holding, and it is the only thing the extraction parameterized.
    """
    kit = tmp_path / "CommonMark"
    case = _complete_run(kit)

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert '<span class="sub">Drydock UAT</span>' in page
    assert "User Acceptance Test — Run Report" in page


def _write_stream(case: Path, label: str, stream: str, text: str) -> None:
    (case / "evidence" / "commands" / f"{label}.{stream}.log").write_text(text, encoding="utf-8")


def test_an_empty_artifact_is_listed_but_never_linked_or_given_a_viewer(tmp_path: Path) -> None:
    """A page reading "This file is empty." wastes a click and misleads on a failed command:
    the reader goes looking for the failure and is handed a blank stdout while the explanation
    sits in stderr. Observed in the CommonMark UAT of 2026-08-15."""
    case = _complete_run(tmp_path / "CommonMark")
    _write_stream(case, "04-test", "stdout", "")
    _write_stream(case, "04-test", "stderr", "sh: 0: cannot open full_test.sh: No such file\n")

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert not (case / "view" / "evidence" / "commands" / "04-test.stdout.log.html").exists()
    assert (case / "view" / "evidence" / "commands" / "04-test.stderr.log.html").exists()
    assert "04-test.stdout.log.html" not in page
    assert "This file is empty." not in page
    assert "04-test.stdout.log" in page  # still inventoried, marked empty


def test_the_failure_excerpt_quotes_the_first_failing_stage_not_only_the_last(
    tmp_path: Path,
) -> None:
    """The first non-zero stage is where the run diverged; later ones are usually its
    consequence — a test harness the aborted build never delivered. Quoting only the last hands
    the reader the symptom and hides the cause."""
    case = _complete_run(tmp_path / "CommonMark")
    record = json.loads((case / "result.json").read_text(encoding="utf-8"))
    for command in record["commands"]:
        if command["label"] in {"04-test", "06-score-release"}:
            command["returncode"] = 1
    (case / "result.json").write_text(json.dumps(record), encoding="utf-8")
    _write_stream(case, "04-test", "stderr", "cannot open full_test.sh\n")
    _write_stream(case, "06-score-release", "stderr", "release refused\n")

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert "Recorded failure output" in page
    assert "cannot open full_test.sh" in page
    assert "release refused" in page
    assert "where the run diverged" in page
