"""Persistence for this Target. Shipped engines plus the schema generated from DATABASE.md."""

from pathlib import Path

from .db import Database, PersistenceError, UnknownOperation
from .schema import SCHEMA, open_database

__all__ = ["Database", "PersistenceError", "SCHEMA", "UnknownOperation", "initialize_database", "open_database"]


def initialize_database(dsn: str) -> Database:
    """Create missing declared tables/indexes and return the open store; preserve existing data.

    Explicit application initialization uses the generated schema, independently of cwd.
    Ordinary open_database calls do not initialize or migrate the store.
    """
    sql = (Path(__file__).resolve().parent.parent / "schema.sql").read_text(encoding="utf-8")
    database = open_database(dsn)
    try:
        database._initialize_schema(sql)
    except BaseException:
        database.close()
        raise
    return database
