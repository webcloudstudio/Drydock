"""Provision schema at the DATABASE step; verify existing stores without mutation thereafter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from drydock.paths import get_language_dir
from drydock.target_environment import resolve_target_environment

SCHEMA_FILENAME = "schema.sql"
VERIFICATION_FILENAME = "schema-verification.json"
#: Written by Drydock when it emits persistence from ``DATABASE.md``. No agent prompt names it, so
#: it, not the presence of files an agent can also write, says the DATABASE step has run.
PROVENANCE_FILENAME = ".drydock-persistence.json"
#: The store the application opens when nothing overrides it; ``Rigging/stack/persistence.md``.
DEFAULT_DSN = "data/app.db"
APPLY_TIMEOUT_SECONDS = 120

_APPLY_SCRIPT = (get_language_dir("python") / "templates/apply.py.tmpl").read_text(encoding="utf-8")


@dataclass(frozen=True)
class SchemaApplication:
    applied: bool
    detail: str


def apply_schema(
    build_dir: Path, *, env: dict[str, str] | None = None, verify_only: bool = False
) -> SchemaApplication | None:
    """Apply and verify the schema, or only verify it when ``verify_only`` is true.

    ``None`` means there is nothing to apply or verify: the build declares no schema, or, for
    verification, Drydock has not emitted persistence yet. Verification starts at Drydock's
    provenance record, not at ``schema.sql``: a step ordered before DATABASE may write the
    DATABASE-owned files itself, and the DATABASE step regenerates them. Verification never
    provisions a store.

    Runs from ``build_dir``, as the application and its criteria do, so a relative SQLite path
    resolves to the same file they open.
    """
    schema = build_dir / SCHEMA_FILENAME
    package = build_dir / "persistence"
    manifest = build_dir / VERIFICATION_FILENAME
    if verify_only and not (build_dir / PROVENANCE_FILENAME).is_file():
        return None
    if not schema.exists() and not manifest.exists():
        return None
    missing = [
        name
        for name, present in (
            (SCHEMA_FILENAME, schema.is_file()),
            ("persistence/", package.is_dir()),
            (VERIFICATION_FILENAME, manifest.is_file()),
        )
        if not present
    ]
    if missing:
        return SchemaApplication(
            False,
            "persistence artifacts missing after the DATABASE step: "
            + ", ".join(missing)
            + "; rebuild the DATABASE step",
        )
    child_env = {**(os.environ if env is None else env)}
    child_env["DRYDOCK_SCHEMA_VERIFY_ONLY"] = "1" if verify_only else "0"
    if (build_dir / "persistence" / "go.mod").is_file():
        return _apply_go_schema(build_dir, env=child_env)
    environment = resolve_target_environment(build_dir)
    if environment.interpreter is None:
        return SchemaApplication(False, f"schema not applied: {environment.detail}")
    child_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(build_dir), child_env.get("PYTHONPATH", "")) if part
    )
    with tempfile.TemporaryDirectory(prefix="drydock-schema-") as tmp:
        script = Path(tmp) / "apply_schema.py"
        script.write_text(
            _APPLY_SCRIPT.format(default=DEFAULT_DSN, schema=str(schema.resolve())),
            encoding="utf-8",
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
    return SchemaApplication(True, completed.stdout.strip())


def record_provenance(build_dir: Path, written: tuple[Path, ...]) -> Path:
    """Record that Drydock emitted ``written`` from ``DATABASE.md`` into ``build_dir``."""
    path = build_dir / PROVENANCE_FILENAME
    files = sorted(item.relative_to(build_dir).as_posix() for item in written)
    path.write_text(
        json.dumps({"source": "DATABASE.md", "files": files}, indent=2) + "\n", encoding="utf-8"
    )
    return path


def premature_artifacts(build_dir: Path) -> tuple[str, ...]:
    """Name DATABASE-owned files present before Drydock has emitted persistence.

    A ``persistence/`` package alone is not named: a step ordered before DATABASE may stand one
    up for the application factory to import.
    """
    if (build_dir / PROVENANCE_FILENAME).is_file():
        return ()
    return tuple(
        name for name in (SCHEMA_FILENAME, VERIFICATION_FILENAME) if (build_dir / name).exists()
    )


__all__ = [
    "DEFAULT_DSN",
    "PROVENANCE_FILENAME",
    "SchemaApplication",
    "apply_schema",
    "premature_artifacts",
    "record_provenance",
]


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
