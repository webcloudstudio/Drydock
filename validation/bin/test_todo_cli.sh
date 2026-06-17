#!/usr/bin/env bash
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_ROOT="${VALIDATION_REPORT_ROOT:-$REPO_ROOT/validation/reports}"
RUN_ID="${VALIDATION_RUN_ID:-$(date +%Y%m%dT%H%M%S)}"
CASE_SLUG="todo-cli"
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
DB_PATH="$WORKDIR/state.json"

python3 -m py_compile "$WORKDIR/todo.py" >"$OUTDIR/build.stdout.log" 2>"$OUTDIR/build.stderr.log"
build_rc=$?
{
    python3 "$WORKDIR/todo.py" "$DB_PATH" add "write tests"
    python3 "$WORKDIR/todo.py" "$DB_PATH" add "ship scaffold"
    python3 "$WORKDIR/todo.py" "$DB_PATH" list
    python3 "$WORKDIR/todo.py" "$DB_PATH" done 1
    python3 "$WORKDIR/todo.py" "$DB_PATH" list
} >"$OUTDIR/verify.stdout.log" 2>"$OUTDIR/verify.stderr.log"
verify_rc=$?
(cd "$WORKDIR" && python3 -m pytest -q tests) >>"$OUTDIR/verify.stdout.log" 2>>"$OUTDIR/verify.stderr.log"
pytest_rc=$?
python3 "$WORKDIR/todo.py" "$DB_PATH" remove 99 >>"$OUTDIR/verify.stdout.log" 2>>"$OUTDIR/verify.stderr.log"
negative_rc=$?

WORKDIR="$WORKDIR" OUTDIR="$OUTDIR" DB_PATH="$DB_PATH" BUILD_RC="$build_rc" VERIFY_RC="$verify_rc" PYTEST_RC="$pytest_rc" NEGATIVE_RC="$negative_rc" python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

workdir = Path(os.environ["WORKDIR"])
outdir = Path(os.environ["OUTDIR"])
db_path = Path(os.environ["DB_PATH"])
build_rc = int(os.environ["BUILD_RC"])
verify_rc = int(os.environ["VERIFY_RC"])
pytest_rc = int(os.environ["PYTEST_RC"])
negative_rc = int(os.environ["NEGATIVE_RC"])

stdout = (outdir / "verify.stdout.log").read_text(encoding="utf-8")
present = []
missing = []
for relpath in ("todo.py", "tests/test_todo.py"):
    if (workdir / relpath).is_file():
        present.append(relpath)
    else:
        missing.append(relpath)

state = []
if db_path.is_file():
    state = json.loads(db_path.read_text(encoding="utf-8"))

checks = [
    {
        "id": "TODO-A1",
        "status": "pass" if "todo.py" in present else "fail",
        "evidence": "todo.py present" if "todo.py" in present else "todo.py missing",
        "gaps": [] if "todo.py" in present else ["missing-artifact"],
    },
    {
        "id": "TODO-A2",
        "status": "pass" if "write tests" in stdout and "ship scaffold" in stdout else "fail",
        "evidence": "list output includes added tasks" if "write tests" in stdout and "ship scaffold" in stdout else "list output missing tasks",
        "detail": stdout,
        "gaps": [] if "write tests" in stdout and "ship scaffold" in stdout else ["behavior-mismatch"],
    },
    {
        "id": "TODO-A3",
        "status": "pass" if state and state[0]["done"] is True else "fail",
        "evidence": "state persisted first task as done" if state and state[0]["done"] is True else "state did not persist done flag",
        "detail": json.dumps(state),
        "gaps": [] if state and state[0]["done"] is True else ["behavior-mismatch"],
    },
    {
        "id": "TODO-A4",
        "status": "pass" if db_path.is_file() else "fail",
        "evidence": "state.json created" if db_path.is_file() else "state.json missing",
        "gaps": [] if db_path.is_file() else ["missing-artifact"],
    },
    {
        "id": "TODO-A5",
        "status": "pass" if pytest_rc == 0 else "fail",
        "evidence": "pytest passed" if pytest_rc == 0 else f"pytest exited {pytest_rc}",
        "gaps": [] if pytest_rc == 0 else ["missing-test"],
    },
    {
        "id": "TODO-A6",
        "status": "pass" if negative_rc != 0 and len(state) == 2 else "fail",
        "evidence": "invalid subcommand failed without changing state" if negative_rc != 0 and len(state) == 2 else "invalid subcommand corrupted state or returned success",
        "gaps": [] if negative_rc != 0 and len(state) == 2 else ["contract-drift"],
    },
    {
        "id": "TODO-A7",
        "status": "pass" if "tests/test_todo.py" in present else "fail",
        "evidence": "tests/test_todo.py present" if "tests/test_todo.py" in present else "tests/test_todo.py missing",
        "gaps": [] if "tests/test_todo.py" in present else ["missing-artifact"],
    },
]
status = "pass"
if build_rc != 0 or verify_rc != 0 or pytest_rc != 0:
    status = "fail"
elif any(check["status"] != "pass" for check in checks):
    status = "partial"

payload = {
    "schema": 1,
    "case": "todo-cli",
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
