"""Disposable agent-test stores and detection of changes to managed SQLite state.

This is lifecycle isolation and evidence preservation, not an OS security sandbox. Never
restore over a possibly concurrent writer. External services need their own isolation policy.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from drydock.build_plan import BuildPlan
from drydock.database_apply import DEFAULT_DSN, PROVENANCE_FILENAME, apply_schema
from drydock.paths import get_language_dir


def _fingerprint(path: Path) -> tuple[str | None, str | None]:
    # WAL contains committed writes that need not have reached the main file yet.
    return tuple(
        sha256(item.read_bytes()).hexdigest() if item.is_file() else None
        for item in (path, Path(str(path) + "-wal"))
    )


def _logical_state(path: Path) -> tuple[tuple[str, ...], tuple[int, ...], tuple[str, ...]]:
    """Read a consistent logical SQLite image, including committed WAL contents.

    Unsupported or unreadable databases fail closed rather than being treated as unchanged.
    """
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    ) as source:
        with closing(sqlite3.connect(":memory:")) as copy:
            deadline = time.monotonic() + 5

            def progress(_status: int, _remaining: int, _total: int) -> None:
                if time.monotonic() > deadline:
                    raise TimeoutError("SQLite state comparison timed out")

            source.backup(copy, pages=128, progress=progress, sleep=0.05)
            pragmas = tuple(
                copy.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("user_version", "application_id", "auto_vacuum")
            )
            rowids = []
            for _, name, kind, _, without_rowid, _ in copy.execute("PRAGMA table_list"):
                if kind != "table" or without_rowid or name.startswith("sqlite_"):
                    continue
                quoted = '"' + name.replace('"', '""') + '"'
                columns = {row[1].lower() for row in copy.execute(f"PRAGMA table_xinfo({quoted})")}
                alias = next(
                    (item for item in ("rowid", "_rowid_", "oid") if item not in columns), None
                )
                if alias is None:
                    raise ValueError("cannot verify shadowed SQLite rowids")
                rowids.extend(
                    repr((name, *row)) for row in copy.execute(f"SELECT {alias}, * FROM {quoted}")
                )
            return tuple(sorted(copy.iterdump())), pragmas, tuple(sorted(rowids))


_ISOLATION_PLUGIN = "drydock_store_isolation"


def _per_test_isolation(call_dir: Path, template: Path) -> dict[str, str]:
    """Child environment that gives each project pytest test its own copy of ``template``.

    The plugin is Drydock's, staged beside the call store and removed with it; nothing is
    written into the product. The provisioned call store becomes a read-only template.
    """
    plugin_dir = call_dir / "plugin"
    plugin_dir.mkdir()
    shutil.copyfile(
        Path(__file__).with_name("pytest_store_isolation.py"),
        plugin_dir / f"{_ISOLATION_PLUGIN}.py",
    )
    shutil.copyfile(
        get_language_dir("python") / "acceptance" / "drydock_acceptance.py",
        plugin_dir / "drydock_acceptance.py",
    )
    return {
        "DRYDOCK_STORE_TEMPLATE": str(template),
        "PYTHONPATH": os.pathsep.join(
            part for part in (str(plugin_dir), os.environ.get("PYTHONPATH", "")) if part
        ),
        "PYTEST_ADDOPTS": " ".join(
            part
            for part in (os.environ.get("PYTEST_ADDOPTS", ""), f"-p {_ISOLATION_PLUGIN}")
            if part
        ),
    }


@dataclass
class AgentStore:
    build_dir: Path
    target_dir: Path
    environment: dict[str, str] = field(default_factory=dict)
    violation: str = ""
    ready: bool = False
    backup_path: Path | None = None
    _canonical: Path | None = None
    _before: tuple[str | None, str | None] | None = None
    _temporary: Path | None = None

    def __enter__(self) -> AgentStore:
        if not (self.build_dir / PROVENANCE_FILENAME).is_file():
            self.ready = True
            return self
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PATH") or DEFAULT_DSN
        if dsn.startswith(("postgres://", "postgresql://")):
            self.ready = True
            return self  # Remote-store isolation is an explicit, separate capability.
        raw = Path(dsn.split("://", 1)[-1]).expanduser()
        canonical = (raw if raw.is_absolute() else self.build_dir / raw).resolve()
        managed = canonical.is_relative_to(self.build_dir.resolve())
        if managed and not canonical.is_file():
            raise RuntimeError(
                "persistence store missing; restore the store or rebuild the DATABASE owner"
            )
        # Snapshots stay outside the disposable tree and are retained only on a violation.
        if managed:
            root = self.target_dir / "evidence" / "managed-state"
            root.mkdir(parents=True, exist_ok=True)
            # Database contents are recovery material, not Target Git history.
            ignore = root / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n", encoding="utf-8")
            backup_dir = Path(tempfile.mkdtemp(prefix="sqlite-", dir=root))
            backup_dir.chmod(0o700)
            self.backup_path = backup_dir / "app.db"
            try:
                with sqlite3.connect(canonical.as_uri() + "?mode=ro", uri=True) as source:
                    with sqlite3.connect(self.backup_path) as backup:
                        source.backup(backup)
                self.backup_path.chmod(0o600)
                self._canonical, self._before = canonical, _fingerprint(canonical)
            except BaseException:
                shutil.rmtree(backup_dir)
                raise
        # A fresh schema has no previous test's business rows. The agent inherits both DSNs.
        root = self.build_dir / ".drydock-tests"
        root.mkdir(exist_ok=True)
        self._temporary = Path(tempfile.mkdtemp(prefix="store-", dir=root))
        test_path = self._temporary / "app.db"
        self.environment = {"DATABASE_URL": str(test_path), "DATABASE_PATH": str(test_path)}
        try:
            applied = apply_schema(self.build_dir, env={**os.environ, **self.environment})
            if applied is None or not applied.applied:
                raise RuntimeError(
                    "disposable test store provisioning failed: "
                    + (applied.detail if applied else "no persistence declaration")
                )
        except BaseException:
            self.__exit__(None, None, None)
            raise
        self.environment.update(_per_test_isolation(self._temporary, test_path))
        self.ready = True
        return self

    def __exit__(self, *exc) -> None:
        try:
            diagnosis = "could not be verified"
            try:
                changed = (
                    self._canonical is not None and _fingerprint(self._canonical) != self._before
                )
            except OSError:
                changed = True  # Retain the snapshot when state cannot be verified.
            if changed and self._canonical is not None and self._canonical.is_file():
                try:
                    before_check = _fingerprint(self._canonical)
                    same = _logical_state(self.backup_path) == _logical_state(self._canonical)
                    # A concurrent physical change makes the comparison inconclusive.
                    stable = before_check == _fingerprint(self._canonical)
                    changed = not same or not stable
                    if stable and not same:
                        diagnosis = "has different schema or data"
                except (OSError, sqlite3.Error, ValueError, TypeError, TimeoutError):
                    changed = True
            elif changed and self._canonical is not None and not self._canonical.exists():
                diagnosis = "is missing"
            if changed:
                self.violation = (
                    f"Managed SQLite state changed or {diagnosis} during agent execution. "
                    f"Retained pre-call snapshot: {self.backup_path}. "
                    "Review the retained evidence through the persistence owner before continuing; "
                    "no automatic overwrite or reprovisioning was performed."
                )
            elif self.backup_path is not None:
                shutil.rmtree(self.backup_path.parent, ignore_errors=True)
        finally:
            if self._temporary is not None:
                shutil.rmtree(self._temporary, ignore_errors=True)


def database_owner(plan: BuildPlan) -> str | None:
    return next(
        (
            story.block_id
            for story in plan.blocks
            if "DATABASE.md" in story.fields.get("implements", ())
        ),
        None,
    )


def persistence_recovery(target: str, owner: str | None, detail: str) -> str:
    """Preserve data first; identify the provisioning owner instead of retrying its consumer."""
    owner_text = f"DATABASE story `{owner}`" if owner else "the story implementing DATABASE.md"
    return (
        f"Review persistence evidence through {owner_text}; restore only if required.\n"
        "Preserve existing data and any retained managed-state snapshot; provisioning an empty "
        "store is not data recovery.\n"
        f"{detail}\n"
        f"After the store is verified and any required recovery is complete, run: drydock build {target}"
    )
