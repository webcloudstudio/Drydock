"""Exercise the operator helper exclusively against temporary kit trees."""

import json
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "helpers" / "delete_failed_uat_runs.sh"


def invoke(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HELPER), "--uat-root", str(root), *args],
        cwd=root.parent,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("delete", [False, True])
def test_cleanup_uses_only_explicit_failed_status(tmp_path: Path, delete: bool) -> None:
    root = tmp_path / "fixture kits"
    runs = root / "Example" / "runs"
    receipts = {
        "failed": {"status": "failed"},
        # A fixture can expect a product failure and still pass UAT.
        "passed": {"status": "passed", "acceptance_status": "FAIL"},
        "degraded": {"status": "degraded"},
        "unknown": {"status": "unknown"},
        "no-status": {},
        "invalid-shape": [],
    }
    for name, payload in receipts.items():
        run = runs / name
        run.mkdir(parents=True)
        (run / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    (runs / "failed" / "nested").mkdir()
    (runs / "failed" / "nested" / "artifact").write_text("evidence")
    for name in ("incomplete", "malformed"):
        (runs / name).mkdir()
    (runs / "malformed" / "result.json").write_text("{")
    (runs / "invalid-encoding").mkdir()
    (runs / "invalid-encoding" / "result.json").write_bytes(b"\xff")
    index = root / "Example" / "index.html"
    index.write_text("original index")

    result = invoke(root, *(["--delete"] if delete else []))

    assert result.returncode == 0, result.stderr
    assert (runs / "failed").exists() is not delete
    assert "1 failed run(s)" in result.stdout
    assert ("DELETED " if delete else "WOULD DELETE ") in result.stdout
    for name in (*receipts, "incomplete", "malformed", "invalid-encoding"):
        if name != "failed":
            assert (runs / name).is_dir()
    assert index.read_text() == "original index"


def test_cleanup_skips_symlinked_boundaries_and_receipts(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    run = root / "Example" / "runs" / "failed"
    run.mkdir(parents=True)
    (run / "result.json").write_text('{"status": "failed"}')
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "result.json").write_text('{"status": "failed"}')
    (root / "kit-link").symlink_to(root / "Example", target_is_directory=True)
    other = root / "Other"
    other.mkdir()
    (other / "runs").symlink_to(run.parent, target_is_directory=True)
    (run.parent / "run-link").symlink_to(outside, target_is_directory=True)
    linked_receipt = run.parent / "linked-receipt"
    linked_receipt.mkdir()
    (linked_receipt / "result.json").symlink_to(outside / "result.json")
    # A symlink inside a deletable run must not remove its destination.
    (run / "artifact-link").symlink_to(outside, target_is_directory=True)

    result = invoke(root, "--delete")

    assert result.returncode == 0, result.stderr
    assert not run.exists()
    assert outside.is_dir()
    assert (outside / "result.json").is_file()
    assert linked_receipt.is_dir()
    assert "1 failed run(s) deleted" in result.stdout


def test_missing_root_is_an_operational_error(tmp_path: Path) -> None:
    result = invoke(tmp_path / "missing", "--delete")
    assert result.returncode == 1
    assert "not a directory" in result.stderr


def test_invalid_option_is_a_usage_error(tmp_path: Path) -> None:
    result = invoke(tmp_path, "--invalid")
    assert result.returncode == 2
