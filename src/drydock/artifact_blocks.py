"""Strict parsing for LLM-emitted artifact blocks."""

from __future__ import annotations

import re
from collections.abc import Iterable
from re import Pattern

from drydock.errors import DrydockError

_ARTIFACT_BLOCK_RE = re.compile(
    r"^===\s*(?P<name>[^\n=]+?)\s*===\s*\n(?P<body>.*?)^===\s*END\s+(?P=name)\s*===\s*$",
    re.MULTILINE | re.DOTALL,
)


def parse_artifact_blocks(
    text: str,
    *,
    label: str,
    allowed_names: Iterable[str] | None = None,
    allowed_prefixes: Iterable[str] = (),
    allowed_suffixes: Iterable[str] = (),
    allowed_patterns: Iterable[str | Pattern[str]] = (),
) -> dict[str, str]:
    """Return artifact-name -> body and reject malformed/noisy model output.

    The accepted format is:

    ``=== NAME ===``
    ``...content...``
    ``=== END NAME ===``

    No text may appear outside artifact blocks. Duplicate names are rejected. Optional allow-lists
    let callers fail before any generated artifact is written.
    """
    blocks: dict[str, str] = {}
    allowed_set = set(allowed_names or ())
    prefixes = tuple(allowed_prefixes)
    suffixes = tuple(allowed_suffixes)
    patterns = tuple(
        re.compile(pattern) if isinstance(pattern, str) else pattern for pattern in allowed_patterns
    )
    cursor = 0

    for match in _ARTIFACT_BLOCK_RE.finditer(text):
        outside = text[cursor : match.start()]
        if outside.strip():
            raise DrydockError(
                f"{label} failed: LLM output did not satisfy the artifact contract.\n"
                "  Text appeared outside delimited artifact blocks.\n"
                "  No generated artifacts were written."
            )
        name = match.group("name").strip()
        if name in blocks:
            raise DrydockError(
                f"{label} failed: LLM output did not satisfy the artifact contract.\n"
                f"  Duplicate artifact block: {name}\n"
                "  No generated artifacts were written."
            )
        if not _is_allowed(name, allowed_set, prefixes, suffixes, patterns):
            raise DrydockError(
                f"{label} failed: LLM output contained an unexpected artifact block: {name}\n"
                "  No generated artifacts were written."
            )
        blocks[name] = match.group("body").strip()
        cursor = match.end()

    if text[cursor:].strip():
        raise DrydockError(
            f"{label} failed: LLM output did not satisfy the artifact contract.\n"
            "  Text appeared outside delimited artifact blocks.\n"
            "  No generated artifacts were written."
        )
    if not blocks:
        raise DrydockError(
            f"{label} failed: LLM output did not contain any delimited artifact blocks.\n"
            "  No generated artifacts were written."
        )
    return blocks


def _is_allowed(
    name: str,
    allowed_names: set[str],
    allowed_prefixes: tuple[str, ...],
    allowed_suffixes: tuple[str, ...],
    allowed_patterns: tuple[Pattern[str], ...],
) -> bool:
    if allowed_names and name in allowed_names:
        return True
    if any(name.startswith(prefix) for prefix in allowed_prefixes):
        return True
    if any(name.endswith(suffix) for suffix in allowed_suffixes):
        return True
    if any(pattern.fullmatch(name) for pattern in allowed_patterns):
        return True
    return (
        not allowed_names and not allowed_prefixes and not allowed_suffixes and not allowed_patterns
    )
