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
    assert "Delivered code" in manifest["artifacts"]
    assert manifest["environment"]["provider"] == "codex"


def test_case_kit_reports_failure_and_quotes_the_recorded_output(tmp_path: Path) -> None:
    case = _case(tmp_path / "run", status="failed", failing=True)

    index = build_case_kit(case)

    page = index.read_text(encoding="utf-8")
    assert "commonmark: FAILED" in page
    assert "commonmark: build exited 1" in page
    assert "boom: acceptance failed" in page
    assert "exit 1" in page


def test_case_kit_states_success_only_when_every_command_exited_zero(tmp_path: Path) -> None:
    case = _case(tmp_path / "run")

    page = build_case_kit(case).read_text(encoding="utf-8")

    assert "commonmark: PASSED" in page
    assert "every required command exited 0" in page
    assert "drydock build commonmark" in page


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
