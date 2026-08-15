"""Validated runtime-failure taxonomy for governed acceptance assertions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache

from drydock.errors import ConfigurationError
from drydock.paths import get_rigging_root

TAXONOMY_FILENAME = "acceptance_failure_taxonomy.json"
_EXPECTED_KEYS = {"version", "malformed_exceptions", "environment_exceptions"}


@dataclass(frozen=True)
class AcceptanceFailureTaxonomy:
    malformed_exceptions: frozenset[str]
    environment_exceptions: frozenset[str]


def _exception_names(payload: object, key: str) -> frozenset[str]:
    if not isinstance(payload, list) or not payload:
        raise ConfigurationError(f"{TAXONOMY_FILENAME}: {key} must be a non-empty list")
    if any(not isinstance(name, str) or not name.strip() for name in payload):
        raise ConfigurationError(f"{TAXONOMY_FILENAME}: {key} contains an invalid exception name")
    names = [name.strip() for name in payload]
    if len(names) != len(set(names)):
        raise ConfigurationError(f"{TAXONOMY_FILENAME}: {key} contains duplicate names")
    return frozenset(names)


@cache
def load_acceptance_failure_taxonomy() -> AcceptanceFailureTaxonomy:
    """Load and validate the packaged exception categories used by runtime attribution."""
    path = get_rigging_root() / TAXONOMY_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"acceptance failure taxonomy not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(f"{path}: taxonomy root must be an object")
    unknown = set(payload) - _EXPECTED_KEYS
    missing = _EXPECTED_KEYS - set(payload)
    if unknown or missing:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise ConfigurationError(f"{path}: invalid taxonomy schema ({'; '.join(details)})")
    if payload["version"] != 1:
        raise ConfigurationError(f"{path}: unsupported taxonomy version {payload['version']!r}")
    return AcceptanceFailureTaxonomy(
        malformed_exceptions=_exception_names(
            payload["malformed_exceptions"], "malformed_exceptions"
        ),
        environment_exceptions=_exception_names(
            payload["environment_exceptions"], "environment_exceptions"
        ),
    )
