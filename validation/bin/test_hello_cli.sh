#!/usr/bin/env bash
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_ROOT="${VALIDATION_REPORT_ROOT:-$REPO_ROOT/validation/reports}"
RUN_ID="${VALIDATION_RUN_ID:-$(date +%Y%m%dT%H%M%S)}"
CASE_SLUG="hello-cli"
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

python3 -m py_compile "$WORKDIR/app.py" >"$OUTDIR/build.stdout.log" 2>"$OUTDIR/build.stderr.log"
build_rc=$?
python3 "$WORKDIR/app.py" >"$OUTDIR/verify.stdout.log" 2>"$OUTDIR/verify.stderr.log"
verify_rc=$?
(cd "$WORKDIR" && python3 -m pytest -q tests) >>"$OUTDIR/verify.stdout.log" 2>>"$OUTDIR/verify.stderr.log"
pytest_rc=$?

WORKDIR="$WORKDIR" OUTDIR="$OUTDIR" BUILD_RC="$build_rc" VERIFY_RC="$verify_rc" PYTEST_RC="$pytest_rc" python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

workdir = Path(os.environ["WORKDIR"])
outdir = Path(os.environ["OUTDIR"])
build_rc = int(os.environ["BUILD_RC"])
verify_rc = int(os.environ["VERIFY_RC"])
pytest_rc = int(os.environ["PYTEST_RC"])

stdout = (outdir / "verify.stdout.log").read_text(encoding="utf-8")
stderr = (outdir / "verify.stderr.log").read_text(encoding="utf-8")
present = []
missing = []
for relpath in ("app.py", "tests/test_app.py"):
    if (workdir / relpath).is_file():
        present.append(relpath)
    else:
        missing.append(relpath)

checks = [
    {
        "id": "HELLO-A1",
        "status": "pass" if "app.py" in present else "fail",
        "evidence": "app.py present" if "app.py" in present else "app.py missing",
        "gaps": [] if "app.py" in present else ["missing-artifact"],
    },
    {
        "id": "HELLO-A2",
        "status": "pass" if verify_rc == 0 and stdout.splitlines()[0:1] == ["hello world"] else "fail",
        "evidence": "stdout starts with hello world" if verify_rc == 0 else f"program exited {verify_rc}",
        "detail": stdout.strip() or stderr.strip() or "no output",
        "gaps": [] if verify_rc == 0 and stdout.splitlines()[0:1] == ["hello world"] else ["wrong-output"],
    },
    {
        "id": "HELLO-A3",
        "status": "pass" if "tests/test_app.py" in present else "fail",
        "evidence": "tests/test_app.py present" if "tests/test_app.py" in present else "tests/test_app.py missing",
        "gaps": [] if "tests/test_app.py" in present else ["missing-artifact"],
    },
    {
        "id": "HELLO-A4",
        "status": "pass" if pytest_rc == 0 else "fail",
        "evidence": "pytest passed" if pytest_rc == 0 else f"pytest exited {pytest_rc}",
        "gaps": [] if pytest_rc == 0 else ["missing-test"],
    },
    {
        "id": "HELLO-A5",
        "status": "pass" if verify_rc == 0 and stderr.strip() == "" else "fail",
        "evidence": "stderr empty" if stderr.strip() == "" else "stderr not empty",
        "detail": stderr.strip(),
        "gaps": [] if verify_rc == 0 and stderr.strip() == "" else ["wrong-output"],
    },
]
status = "pass"
if build_rc != 0 or verify_rc != 0 or pytest_rc != 0:
    status = "fail"
elif any(check["status"] != "pass" for check in checks):
    status = "partial"

payload = {
    "schema": 1,
    "case": "hello-cli",
    "status": status,
    "build_exit_code": build_rc,
    "verify_exit_code": max(verify_rc, pytest_rc),
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
