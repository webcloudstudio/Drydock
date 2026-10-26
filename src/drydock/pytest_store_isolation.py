"""Per-test SQLite isolation for project tests a build agent runs.

Drydock never imports this module. ``build_state.AgentStore`` copies it into the call's private
directory and loads it into the provider child's pytest through ``PYTEST_ADDOPTS``. Each test
then opens its own copy of the call's freshly provisioned store, so committed rows and
``cli_runner`` writes from one test cannot reach the next. Without a template it does nothing,
which leaves an operator's own pytest run and canonical acceptance unchanged.
"""

import os
import sqlite3

import pytest

TEMPLATE_VARIABLE = "DRYDOCK_STORE_TEMPLATE"


@pytest.fixture(autouse=True)
def _drydock_isolated_store(tmp_path, monkeypatch):
    template = os.environ.get(TEMPLATE_VARIABLE, "")
    if template and os.path.isfile(template):
        store = tmp_path / "drydock-store.db"
        source = sqlite3.connect(f"file:{template}?mode=ro", uri=True)
        target = sqlite3.connect(store)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        monkeypatch.setenv("DATABASE_URL", str(store))
        monkeypatch.setenv("DATABASE_PATH", str(store))
    yield
