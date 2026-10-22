"""Generated fixtures over the configured, already provisioned application store."""

from contextlib import contextmanager
import os
from pathlib import Path

from .schema import open_database


@contextmanager
def committed_session():
    """Use normal autocommit; the criterion owns idempotent recovery and business cleanup."""
    configured = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PATH") or "data/app.db"
    if not configured.startswith(("postgres://", "postgresql://")):
        if not Path(configured.split("://", 1)[-1]).is_file():
            raise RuntimeError("persistence store missing; rebuild the DATABASE step")
    database = open_database(configured)
    try:
        yield database
    finally:
        database.close()


@contextmanager
def db_session():
    """Share this connection with the feature; always roll back, never provision schema."""
    with committed_session() as database:
        with database.rollback_session():
            yield database
