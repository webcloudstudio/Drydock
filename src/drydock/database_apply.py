"""Apply the generated ``schema.sql`` to the Target's configured store.

The DATABASE step generates the DDL, and Rigging forbids the application from creating schema at
startup, so Drydock owns applying it. It applies it at the DATABASE step and again before every
acceptance run, so a criterion that drives the application through its own client finds the
declared tables in any later step, after a resume, or after the store was deleted. The DDL is
``CREATE ... IF NOT EXISTS`` throughout, so reapplying is a no-op.

The schema is applied through the build's own ``persistence`` package under the Target
interpreter, so the engine is the one the DSN selects (SQLite, PostgreSQL, or any driver the
package carries) and the driver is the one the application itself imports.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from drydock.paths import get_language_dir
from drydock.target_environment import resolve_target_environment

SCHEMA_FILENAME = "schema.sql"
#: The store the application opens when nothing overrides it; ``Rigging/stack/persistence.md``.
DEFAULT_DSN = "data/app.db"
APPLY_TIMEOUT_SECONDS = 120

_APPLY_SCRIPT = (get_language_dir("python") / "templates/apply.py.tmpl").read_text(encoding="utf-8")


@dataclass(frozen=True)
class SchemaApplication:
    applied: bool
    detail: str


def apply_schema(build_dir: Path, *, env: dict[str, str] | None = None) -> SchemaApplication | None:
    """Apply ``schema.sql`` to the configured store. ``None`` when the build declares no schema.

    Runs from ``build_dir``, as the application and its criteria do, so a relative SQLite path
    resolves to the same file they open.
    """
    schema = build_dir / SCHEMA_FILENAME
    if not schema.is_file() or not (build_dir / "persistence").is_dir():
        return None
    if (build_dir / "persistence" / "go.mod").is_file():
        return _apply_go_schema(build_dir, env=env)
    environment = resolve_target_environment(build_dir)
    if environment.interpreter is None:
        return SchemaApplication(False, f"schema not applied: {environment.detail}")
    child_env = {**(os.environ if env is None else env)}
    child_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(build_dir), child_env.get("PYTHONPATH", "")) if part
    )
    with tempfile.TemporaryDirectory(prefix="drydock-schema-") as tmp:
        script = Path(tmp) / "apply_schema.py"
        script.write_text(
            _APPLY_SCRIPT.format(default=DEFAULT_DSN, schema=str(schema)), encoding="utf-8"
        )
        try:
            completed = subprocess.run(
                [str(environment.interpreter), str(script)],
                cwd=build_dir,
                env=child_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=APPLY_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SchemaApplication(
                False, f"schema not applied: timed out after {APPLY_TIMEOUT_SECONDS}s"
            )
    if completed.returncode != 0:
        lines = (completed.stderr or completed.stdout).strip().splitlines()
        return SchemaApplication(
            False, f"schema not applied: {lines[-1] if lines else f'exit {completed.returncode}'}"
        )
    return SchemaApplication(True, f"schema applied to {completed.stdout.strip() or 'store'}")


__all__ = ["DEFAULT_DSN", "SchemaApplication", "apply_schema"]


def _apply_go_schema(build_dir: Path, *, env: dict[str, str] | None) -> SchemaApplication:
    go = shutil.which("go")
    if go is None:
        return SchemaApplication(False, "schema not applied: Go toolchain unavailable")
    try:
        result = subprocess.run(
            [go, "run", "drydock.local/persistence/cmd/drydock-schema"],
            cwd=build_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=APPLY_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SchemaApplication(False, f"schema not applied: {exc}")
    if result.returncode:
        return SchemaApplication(
            False, "schema not applied: " + (result.stderr or result.stdout).strip()
        )
    return SchemaApplication(True, result.stdout.strip())
