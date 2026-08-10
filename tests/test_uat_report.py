from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from drydock.uat_report import build_case_kit, build_kit_index, prune_generated


def _case(
    kit_root: Path,
    *,
    run_id: str = "20260101T000000.000000Z",
    status: str = "passed",
    failing: bool = False,
    degraded: tuple[str, ...] = (),
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


def _links(page: Path) -> set[str]:
    return set(re.findall(r'href="([^"]+)"', page.read_text(encoding="utf-8")))


def test_case_kit_links_resolve_and_paths_are_relative(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    index = build_case_kit(case)

    links = _links(index)
    assert links
    assert all(not link.startswith(("/", "http")) for link in links)
    assert all((case / link).exists() for link in links)
    assert "evidence/commands/01-init.stdout.log" in links
    assert "build/commonmark/parser.py" in links


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


def test_the_kit_index_tags_a_degraded_run_distinctly(tmp_path: Path) -> None:
    kit = tmp_path / "Toml"
    (kit / "uat.json").parent.mkdir(parents=True, exist_ok=True)
    (kit / "uat.json").write_text("{}\n", encoding="utf-8")
    (kit / "README.md").write_text("# Toml\n", encoding="utf-8")
    _case(kit, status="degraded", degraded=("initial-build-1 exited 1",))

    page = build_kit_index(kit).read_text(encoding="utf-8")

    assert '<span class="tag degraded">DEGRADED</span>' in page
