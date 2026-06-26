from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from drydock.errors import SpecificationError
from drydock.validation_harness import (
    aggregate_results,
    load_result_payload,
    parse_case_spec,
    render_summary_markdown,
    score_case,
)


def test_parse_case_spec_reads_sections():
    spec = parse_case_spec(Path("validation/specs/hello-cli.md"))
    assert spec.slug == "hello-cli"
    assert spec.minimum_score == 85
    assert any(assertion.id == "HELLO-A2" for assertion in spec.assertions)


def test_parse_case_spec_rejects_missing_section(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(
        "# VALIDATION CASE: broken\n\n## Goal\n\nBroken.\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecificationError):
        parse_case_spec(path)


def test_load_result_payload_rejects_missing_keys(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"schema": 1, "case": "hello-cli"}), encoding="utf-8")
    with pytest.raises(SpecificationError):
        load_result_payload(path)


def test_score_case_computes_weighted_score_and_gaps(tmp_path):
    spec = parse_case_spec(Path("validation/specs/hello-cli.md"))
    result_path = tmp_path / "result.json"
    payload = {
        "schema": 1,
        "case": "hello-cli",
        "status": "partial",
        "build_exit_code": 0,
        "verify_exit_code": 0,
        "artifacts_present": ["app.py", "tests/test_app.py"],
        "artifacts_missing": [],
        "checks": [
            {"id": "HELLO-A1", "status": "pass", "evidence": "ok"},
            {
                "id": "HELLO-A2",
                "status": "fail",
                "evidence": "wrong text",
                "gaps": ["wrong-output"],
            },
            {"id": "HELLO-A3", "status": "pass", "evidence": "ok"},
            {"id": "HELLO-A4", "status": "pass", "evidence": "ok"},
            {"id": "HELLO-A5", "status": "pass", "evidence": "ok"},
        ],
        "raw_paths": {},
    }
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    scored = score_case(spec, load_result_payload(result_path), result_path=result_path)
    assert scored.score == 69
    assert "wrong-output" in scored.gaps
    assert scored.passed is False


def test_aggregate_results_ranks_recurring_gaps():
    case1 = score_case(
        parse_case_spec(Path("validation/specs/hello-cli.md")),
        {
            "schema": 1,
            "case": "hello-cli",
            "status": "pass",
            "build_exit_code": 0,
            "verify_exit_code": 0,
            "artifacts_present": ["app.py", "tests/test_app.py"],
            "artifacts_missing": [],
            "checks": [
                {"id": "HELLO-A1", "status": "pass", "evidence": "ok"},
                {"id": "HELLO-A2", "status": "pass", "evidence": "ok"},
                {"id": "HELLO-A3", "status": "pass", "evidence": "ok"},
                {
                    "id": "HELLO-A4",
                    "status": "partial",
                    "evidence": "weak",
                    "gaps": ["missing-test"],
                },
                {"id": "HELLO-A5", "status": "pass", "evidence": "ok"},
            ],
            "raw_paths": {},
        },
    )
    case2 = score_case(
        parse_case_spec(Path("validation/specs/file-transform.md")),
        {
            "schema": 1,
            "case": "file-transform",
            "status": "partial",
            "build_exit_code": 0,
            "verify_exit_code": 0,
            "artifacts_present": ["transform.py", "tests/test_transform.py", "data/input.csv"],
            "artifacts_missing": [],
            "checks": [
                {"id": "TRANSFORM-A1", "status": "pass", "evidence": "ok"},
                {"id": "TRANSFORM-A2", "status": "pass", "evidence": "ok"},
                {"id": "TRANSFORM-A3", "status": "pass", "evidence": "ok"},
                {
                    "id": "TRANSFORM-A4",
                    "status": "partial",
                    "evidence": "weak",
                    "gaps": ["missing-test"],
                },
                {"id": "TRANSFORM-A5", "status": "pass", "evidence": "ok"},
                {"id": "TRANSFORM-A6", "status": "pass", "evidence": "ok"},
            ],
            "raw_paths": {},
        },
    )
    summary = aggregate_results([case1, case2])
    assert summary["top_gap"] == "missing-test"
    assert "Validation Summary" in render_summary_markdown(summary)


def test_shell_runner_and_summary_smoke(tmp_path):
    report_root = tmp_path / "reports"
    env = os.environ.copy()
    env["VALIDATION_REPORT_ROOT"] = str(report_root)
    env["VALIDATION_RUN_ID"] = "testrun"

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "validation/bin/run_validation.sh"
    result = subprocess.run(
        ["bash", str(script), "hello-cli"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary_path = report_root / "testrun" / "SUMMARY.md"
    assert summary_path.is_file()
    assert "hello-cli" in summary_path.read_text(encoding="utf-8")
