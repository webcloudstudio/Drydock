"""Strict parsing for LLM-emitted artifact blocks."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePath
from re import Pattern

from drydock.errors import DrydockError

_OPEN_BLOCK_RE = re.compile(r"^===\s*(?P<name>[^\n=]+?)\s*===\s*$")
_END_BLOCK_RE = re.compile(r"^===\s*END\s+(?P<name>[^\n=]+?)\s*===\s*$")
_WRITE_CALL_RE = re.compile(
    r'<invoke name="Write">\s*'
    r"<parameter name=\"(?:path|file_path)\">(?P<path>.*?)</parameter>\s*"
    r"<parameter name=\"content\">(?P<content>.*?)</parameter>\s*"
    r"</invoke>",
    re.DOTALL,
)
_FUNCTION_WRAPPER_RE = re.compile(r"</?function_calls>\s*")


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
    allowed_set = set(allowed_names or ())
    prefixes = tuple(allowed_prefixes)
    suffixes = tuple(allowed_suffixes)
    patterns = tuple(
        re.compile(pattern) if isinstance(pattern, str) else pattern for pattern in allowed_patterns
    )
    text = _repair_missing_leading_delimiter(text)
    transcript_blocks = _parse_write_call_blocks(
        text,
        label=label,
        allowed_names=allowed_set,
        allowed_prefixes=prefixes,
        allowed_suffixes=suffixes,
        allowed_patterns=patterns,
        strict=False,
    )
    if transcript_blocks:
        return transcript_blocks
    blocks = _parse_delimited_blocks(text, label=label)
    if not blocks:
        transcript_blocks = _parse_write_call_blocks(
            text,
            label=label,
            allowed_names=allowed_set,
            allowed_prefixes=prefixes,
            allowed_suffixes=suffixes,
            allowed_patterns=patterns,
            strict=True,
        )
        if transcript_blocks:
            return transcript_blocks
        if text.strip():
            raise _outside_text_error(label)
        raise DrydockError(
            f"{label} failed: LLM output did not contain any delimited artifact blocks.\n"
            "  No generated artifacts were written."
        )
    for name in blocks:
        if not _is_allowed(name, allowed_set, prefixes, suffixes, patterns):
            raise DrydockError(
                f"{label} failed: LLM output contained an unexpected artifact block: {name}\n"
                "  No generated artifacts were written."
            )
    return blocks


def _parse_delimited_blocks(text: str, *, label: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    current_name: str | None = None
    current_body: list[str] = []
    outside: list[str] = []
    saw_delimiter = False

    for line in text.splitlines(keepends=True):
        open_match = _OPEN_BLOCK_RE.match(line.strip())
        end_match = _END_BLOCK_RE.match(line.strip())

        if current_name is None:
            if end_match and not blocks and _outside_has_text(outside):
                if any("===" in chunk for chunk in outside):
                    raise _outside_text_error(label)
                current_name = end_match.group("name").strip()
                current_body = outside
                outside = []
                blocks[current_name] = "".join(current_body).rstrip().strip()
                current_name = None
                current_body = []
                saw_delimiter = True
                continue
            if open_match:
                if _outside_has_text(outside):
                    raise _outside_text_error(label)
                current_name = open_match.group("name").strip()
                current_body = []
                outside = []
                saw_delimiter = True
                continue
            outside.append(line)
            continue

        if end_match and end_match.group("name").strip() == current_name:
            if current_name in blocks:
                raise DrydockError(
                    f"{label} failed: LLM output did not satisfy the artifact contract.\n"
                    f"  Duplicate artifact block: {current_name}\n"
                    "  No generated artifacts were written."
                )
            blocks[current_name] = "".join(current_body).strip()
            current_name = None
            current_body = []
            saw_delimiter = True
            continue
        current_body.append(line)

    if current_name is not None:
        if current_name in blocks:
            raise DrydockError(
                f"{label} failed: LLM output did not satisfy the artifact contract.\n"
                f"  Duplicate artifact block: {current_name}\n"
                "  No generated artifacts were written."
            )
        blocks[current_name] = "".join(current_body).strip()
        saw_delimiter = True

    if _outside_has_text(outside):
        raise _outside_text_error(label)
    return blocks if saw_delimiter else {}


def _repair_missing_leading_delimiter(text: str) -> str:
    if not text or text.lstrip().startswith("==="):
        return text
    lines = text.splitlines(keepends=True)
    outside: list[str] = []
    for index, line in enumerate(lines):
        end_match = _END_BLOCK_RE.match(line.strip())
        if end_match:
            if not _outside_has_text(outside):
                return text
            if any("===" in chunk for chunk in outside):
                return text
            name = end_match.group("name").strip()
            leading_body = "".join(outside).rstrip("\n")
            remainder = "".join(lines[index + 1 :])
            if f"=== {name} ===" in remainder:
                return text
            repaired = f"=== {name} ===\n{leading_body}\n=== END {name} ==="
            return repaired + (
                "\n" + remainder if remainder and not remainder.startswith("\n") else remainder
            )
        open_match = _OPEN_BLOCK_RE.match(line.strip())
        if open_match:
            return text
        outside.append(line)
    return text


def _parse_write_call_blocks(
    text: str,
    *,
    label: str,
    allowed_names: set[str],
    allowed_prefixes: tuple[str, ...],
    allowed_suffixes: tuple[str, ...],
    allowed_patterns: tuple[Pattern[str], ...],
    strict: bool,
) -> dict[str, str]:
    blocks: dict[str, str] = {}
    cursor = 0
    saw_write = False
    for match in _WRITE_CALL_RE.finditer(text):
        outside = text[cursor : match.start()]
        if _FUNCTION_WRAPPER_RE.sub("", outside).strip():
            if strict:
                raise _outside_text_error(label)
            return {}
        raw_path = match.group("path").strip().replace("\\", "/")
        name = PurePath(raw_path).name
        if not _is_allowed(
            name, allowed_names, allowed_prefixes, allowed_suffixes, allowed_patterns
        ):
            if strict:
                raise DrydockError(
                    f"{label} failed: LLM output contained an unexpected artifact block: {name}\n"
                    "  No generated artifacts were written."
                )
            return {}
        if name in blocks:
            if strict:
                raise DrydockError(
                    f"{label} failed: LLM output did not satisfy the artifact contract.\n"
                    f"  Duplicate artifact block: {name}\n"
                    "  No generated artifacts were written."
                )
            return {}
        blocks[name] = match.group("content").strip()
        cursor = match.end()
        saw_write = True
    if not saw_write:
        return {}
    if _FUNCTION_WRAPPER_RE.sub("", text[cursor:]).strip():
        if strict:
            raise _outside_text_error(label)
        return {}
    return blocks


def _outside_has_text(chunks: list[str]) -> bool:
    return bool("".join(chunks).strip())


def _outside_text_error(label: str) -> DrydockError:
    return DrydockError(
        f"{label} failed: LLM output did not satisfy the artifact contract.\n"
        "  Text appeared outside delimited artifact blocks.\n"
        "  No generated artifacts were written."
    )


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
