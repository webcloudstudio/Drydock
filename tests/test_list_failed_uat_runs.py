"""Listing tests use temporary kit trees, never published UAT evidence."""

import json
import subprocess
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "helpers" / "list_failed_uat_runs.sh"


def invoke(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HELPER), "--uat-root", str(root), *args],
        cwd=root.parent,
        capture_output=True,
        text=True,
        check=False,
    )


def test_lists_only_failed_runs_without_writes(tmp_path: Path) -> None:
    root = tmp_path / "fixture kits"
    runs = root / "Example" / "runs"
    for name, payload in {
        "failed-b": {"status": "failed"},
        "failed-a": {"status": "failed"},
        "passed": {"status": "passed", "acceptance_status": "FAIL"},
        "degraded": {"status": "degraded"},
        "unknown": {"status": "unknown"},
        "missing-status": {},
        "invalid-shape": [],
    }.items():
        run = runs / name
        run.mkdir(parents=True)
        (run / "result.json").write_text(json.dumps(payload))
    for name in ("incomplete", "malformed", "invalid-encoding"):
        (runs / name).mkdir()
    (runs / "malformed" / "result.json").write_text("{")
    (runs / "invalid-encoding" / "result.json").write_bytes(b"\xff")
    (root / "kit-link").symlink_to(root / "Example", target_is_directory=True)
    other = root / "Other"
    other.mkdir()
    (other / "runs").symlink_to(runs, target_is_directory=True)
    (runs / "run-link").symlink_to(runs / "failed-a", target_is_directory=True)
    linked_receipt = runs / "linked-receipt"
    linked_receipt.mkdir()
    (linked_receipt / "result.json").symlink_to(runs / "failed-a" / "result.json")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}

    result = invoke(root)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(runs / "failed-a"), str(runs / "failed-b")]
    assert "2 failed run(s)." in result.stderr
    assert "unreadable result.json" in result.stderr
    assert "symlinked result.json" in result.stderr
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_empty_root_lists_zero_runs(tmp_path: Path) -> None:
    result = invoke(tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == "0 failed run(s).\n"


def test_missing_root_is_an_operational_error(tmp_path: Path) -> None:
    result = invoke(tmp_path / "missing")
    assert result.returncode == 1
    assert "not a directory" in result.stderr


def test_listing_rejects_delete_flag(tmp_path: Path) -> None:
    result = invoke(tmp_path, "--delete")
    assert result.returncode == 2
