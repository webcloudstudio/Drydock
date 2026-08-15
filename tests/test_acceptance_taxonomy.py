import json

import pytest

from drydock import acceptance_taxonomy
from drydock.errors import ConfigurationError


def test_shipped_taxonomy_contains_runtime_harness_failures():
    taxonomy = acceptance_taxonomy.load_acceptance_failure_taxonomy()

    assert "NameError" in taxonomy.malformed_exceptions
    assert "TypeError" in taxonomy.malformed_exceptions
    assert "PermissionError" in taxonomy.environment_exceptions


def test_invalid_taxonomy_fails_as_configuration(tmp_path, monkeypatch):
    payload = {
        "version": 1,
        "malformed_exceptions": ["NameError", "NameError"],
        "environment_exceptions": ["PermissionError"],
    }
    (tmp_path / acceptance_taxonomy.TAXONOMY_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setattr(acceptance_taxonomy, "get_rigging_root", lambda: tmp_path)
    acceptance_taxonomy.load_acceptance_failure_taxonomy.cache_clear()

    with pytest.raises(ConfigurationError, match="duplicate names"):
        acceptance_taxonomy.load_acceptance_failure_taxonomy()

    acceptance_taxonomy.load_acceptance_failure_taxonomy.cache_clear()
