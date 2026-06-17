#!/usr/bin/env bash
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_ROOT="${VALIDATION_REPORT_ROOT:-$REPO_ROOT/validation/reports}"
RUN_ID="${VALIDATION_RUN_ID:-$(date +%Y%m%dT%H%M%S)}"
CASE_SLUG="file-transform"
CASE_DIR="$REPO_ROOT/validation/fixtures/$CASE_SLUG"
SPEC_PATH="$REPO_ROOT/validation/specs/$CASE_SLUG.md"
OUTDIR="$REPORT_ROOT/$RUN_ID/$CASE_SLUG"
WORKDIR="$(mktemp -d)"
mkdir -p "$OUTDIR"

cleanup() {
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

cp -R "$CASE_DIR"/. "$WORKDIR"/
find "$WORKDIR" -type f | sed "s#^$WORKDIR/##" | sort > "$OUTDIR/artifacts.txt"

python3 -m py_compile "$WORKDIR/transform.py" >"$OUTDIR/build.stdout.log" 2>"$OUTDIR/build.stderr.log"
build_rc=$?
python3 "$WORKDIR/transform.py" "$WORKDIR/data/input.csv" "$WORKDIR/out.json" >"$OUTDIR/verify.stdout.log" 2>"$OUTDIR/verify.stderr.log"
verify_rc=$?
(cd "$WORKDIR" && python3 -m pytest -q tests) >>"$OUTDIR/verify.stdout.log" 2>>"$OUTDIR/verify.stderr.log"
pytest_rc=$?
python3 "$WORKDIR/transform.py" "$WORKDIR/data/missing.csv" "$WORKDIR/bad.json" >>"$OUTDIR/verify.stdout.log" 2>>"$OUTDIR/verify.stderr.log"
negative_rc=$?

WORKDIR="$WORKDIR" OUTDIR="$OUTDIR" BUILD_RC="$build_rc" VERIFY_RC="$verify_rc" PYTEST_RC="$pytest_rc" NEGATIVE_RC="$negative_rc" python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

workdir = Path(os.environ["WORKDIR"])
outdir = Path(os.environ["OUTDIR"])
build_rc = int(os.environ["BUILD_RC"])
verify_rc = int(os.environ["VERIFY_RC"])
pytest_rc = int(os.environ["PYTEST_RC"])
negative_rc = int(os.environ["NEGATIVE_RC"])

present = []
missing = []
for relpath in ("transform.py", "tests/test_transform.py", "data/input.csv"):
    if (workdir / relpath).is_file():
        present.append(relpath)
    else:
        missing.append(relpath)

produced = {}
expected = {}
output_path = workdir / "out.json"
expected_path = workdir / "data/expected.json"
if output_path.is_file():
    produced = json.loads(output_path.read_text(encoding="utf-8"))
if expected_path.is_file():
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

checks = [
    {
        "id": "TRANSFORM-A1",
        "status": "pass" if "transform.py" in present else "fail",
        "evidence": "transform.py present" if "transform.py" in present else "transform.py missing",
        "gaps": [] if "transform.py" in present else ["missing-artifact"],
    },
    {
        "id": "TRANSFORM-A2",
        "status": "pass" if produced == expected and produced else "fail",
        "evidence": "out.json matches expected.json" if produced == expected and produced else "out.json mismatch",
        "detail": json.dumps(produced, sort_keys=True),
        "gaps": [] if produced == expected and produced else ["wrong-output"],
    },
    {
        "id": "TRANSFORM-A3",
        "status": "pass" if verify_rc == 0 else "fail",
        "evidence": "transform command exited 0" if verify_rc == 0 else f"transform exited {verify_rc}",
        "gaps": [] if verify_rc == 0 else ["behavior-mismatch"],
    },
    {
        "id": "TRANSFORM-A4",
        "status": "pass" if pytest_rc == 0 else "fail",
        "evidence": "pytest passed" if pytest_rc == 0 else f"pytest exited {pytest_rc}",
        "gaps": [] if pytest_rc == 0 else ["missing-test"],
    },
    {
        "id": "TRANSFORM-A5",
        "status": "pass" if negative_rc != 0 and not (workdir / "bad.json").exists() else "fail",
        "evidence": "missing input returned non-zero" if negative_rc != 0 else "missing input returned success",
        "gaps": [] if negative_rc != 0 and not (workdir / "bad.json").exists() else ["shortcut-or-fabrication"],
    },
    {
        "id": "TRANSFORM-A6",
        "status": "pass" if "tests/test_transform.py" in present else "fail",
        "evidence": "tests/test_transform.py present" if "tests/test_transform.py" in present else "tests/test_transform.py missing",
        "gaps": [] if "tests/test_transform.py" in present else ["missing-artifact"],
    },
]
status = "pass"
if build_rc != 0 or verify_rc != 0 or pytest_rc != 0:
    status = "fail"
elif any(check["status"] != "pass" for check in checks):
    status = "partial"

payload = {
    "schema": 1,
    "case": "file-transform",
    "status": status,
    "build_exit_code": build_rc,
    "verify_exit_code": max(verify_rc, pytest_rc, 0 if negative_rc != 0 else 1),
    "artifacts_present": present,
    "artifacts_missing": missing,
    "checks": checks,
    "raw_paths": {
        "build_stdout": str(outdir / "build.stdout.log"),
        "build_stderr": str(outdir / "build.stderr.log"),
        "verify_stdout": str(outdir / "verify.stdout.log"),
        "verify_stderr": str(outdir / "verify.stderr.log"),
    },
}
(outdir / "result.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

python3 "$REPO_ROOT/validation/bin/score_case.py" \
    "$SPEC_PATH" \
    "$OUTDIR/result.json" \
    --output-json "$OUTDIR/scored.json" \
    --output-md "$OUTDIR/SCORECARD.md" \
    >"$OUTDIR/score.stdout.log"
score_rc=$?

exit "$score_rc"
