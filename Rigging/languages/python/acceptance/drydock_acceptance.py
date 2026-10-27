"""Harness-owned fixtures, available only inside Python acceptance criteria.

Configuration tests get a disposable working directory and SQLite file names. This fixture
creates no schema: ordinary persistence acceptance continues to use the provisioned store.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def database_environment(*, url: str | None = None, path: str | None = None):
    """Test SQLite configuration without redirecting the managed application store.

    ``None`` unsets a variable; ``""`` sets it empty. Other values are relative file names
    inside a new scratch directory. ``url`` may start with ``sqlite://``. Missing parents
    stay missing, permitting real open-failure tests. The yielded Path is also the working
    directory, so the application's default ``data/app.db`` is disposable. No DDL is applied.
    Environment and working directory are restored even when the product or assertion raises.
    """

    def configured(value: str | None, root: Path, *, is_url: bool) -> str | None:
        if value is None or value == "":
            return value
        if not isinstance(value, str):
            raise ValueError("database configuration must be a relative SQLite file name")
        prefix = "sqlite://" if is_url and value.startswith("sqlite://") else ""
        name = value[len(prefix) :]
        candidate = Path(name)
        if (
            not name
            or candidate.is_absolute()
            or ".." in candidate.parts
            or ":" in name
            or "\\" in name
            or candidate == Path(".")
        ):
            raise ValueError("database configuration must stay inside its scratch directory")
        return prefix + str(root / candidate)

    saved = {key: os.environ.get(key) for key in ("DATABASE_URL", "DATABASE_PATH")}
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="drydock-database-config-") as directory:
        root = Path(directory).resolve()
        values = {
            "DATABASE_URL": configured(url, root, is_url=True),
            "DATABASE_PATH": configured(path, root, is_url=False),
        }
        try:
            os.chdir(root)
            for key, value in values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            yield root
        finally:
            os.chdir(previous)
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
