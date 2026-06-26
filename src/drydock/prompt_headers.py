"""JSON-backed metadata for prompt-facing files and injected context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from drydock.errors import DrydockError
from drydock.paths import get_prompts_root


@dataclass(frozen=True)
class PromptHeader:
    item_id: str | None
    filename: str
    label: str
    default_text: str | None
    role: str | None
    help_text: str
    prompt_text: str


@dataclass(frozen=True)
class PromptPrefixHeader:
    prefix: str
    label: str
    role: str | None
    help_text: str
    prompt_text: str


@dataclass(frozen=True)
class PromptPatternHeader:
    pattern: str
    label: str
    role: str | None
    help_text: str
    prompt_text: str


@lru_cache(maxsize=1)
def _load_payload() -> dict:
    path = get_prompts_root() / "prompts.json"
    if not path.is_file():
        raise DrydockError(f"prompt header metadata not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DrydockError("prompts.json root must be an object")
    return payload


@lru_cache(maxsize=1)
def _load_target_headers() -> tuple[PromptHeader, ...]:
    payload = _load_payload()
    target_docs = payload.get("target_docs")
    if not isinstance(target_docs, dict):
        raise DrydockError("prompts.json missing object field 'target_docs'")
    headers: list[PromptHeader] = []
    for filename, item in target_docs.items():
        if not isinstance(item, dict):
            raise DrydockError(f"prompts.json entry for {filename!r} is not an object")
        headers.append(
            PromptHeader(
                item_id=str(item.get("item_id", "")).strip() or None,
                filename=filename,
                label=str(item.get("label", "")).strip(),
                default_text=item.get("default_text"),
                role=str(item.get("role", "")).strip() or None,
                help_text=str(item.get("help_text", "")).strip(),
                prompt_text=str(item.get("prompt_text", "")).strip(),
            )
        )
    return tuple(headers)


@lru_cache(maxsize=1)
def _load_injected_headers() -> tuple[PromptHeader, ...]:
    payload = _load_payload()
    injected_files = payload.get("injected_files", {})
    if not isinstance(injected_files, dict):
        raise DrydockError("prompts.json field 'injected_files' must be an object")
    headers: list[PromptHeader] = []
    for filename, item in injected_files.items():
        if not isinstance(item, dict):
            raise DrydockError(f"prompts.json entry for {filename!r} is not an object")
        headers.append(
            PromptHeader(
                item_id=None,
                filename=filename,
                label=str(item.get("label", "")).strip(),
                default_text=item.get("default_text"),
                role=str(item.get("role", "")).strip() or None,
                help_text=str(item.get("help_text", "")).strip(),
                prompt_text=str(item.get("prompt_text", "")).strip(),
            )
        )
    return tuple(headers)


@lru_cache(maxsize=1)
def _load_prefix_headers() -> tuple[PromptPrefixHeader, ...]:
    payload = _load_payload()
    injected_prefixes = payload.get("injected_prefixes", [])
    if not isinstance(injected_prefixes, list):
        raise DrydockError("prompts.json field 'injected_prefixes' must be an array")
    headers: list[PromptPrefixHeader] = []
    for item in injected_prefixes:
        if not isinstance(item, dict):
            raise DrydockError("prompts.json injected_prefixes entries must be objects")
        headers.append(
            PromptPrefixHeader(
                prefix=str(item.get("prefix", "")).strip(),
                label=str(item.get("label", "")).strip(),
                role=str(item.get("role", "")).strip() or None,
                help_text=str(item.get("help_text", "")).strip(),
                prompt_text=str(item.get("prompt_text", "")).strip(),
            )
        )
    return tuple(headers)


@lru_cache(maxsize=1)
def _load_pattern_headers() -> tuple[PromptPatternHeader, ...]:
    payload = _load_payload()
    injected_patterns = payload.get("injected_patterns", [])
    if not isinstance(injected_patterns, list):
        raise DrydockError("prompts.json field 'injected_patterns' must be an array")
    headers: list[PromptPatternHeader] = []
    for item in injected_patterns:
        if not isinstance(item, dict):
            raise DrydockError("prompts.json injected_patterns entries must be objects")
        headers.append(
            PromptPatternHeader(
                pattern=str(item.get("pattern", "")).strip(),
                label=str(item.get("label", "")).strip(),
                role=str(item.get("role", "")).strip() or None,
                help_text=str(item.get("help_text", "")).strip(),
                prompt_text=str(item.get("prompt_text", "")).strip(),
            )
        )
    return tuple(headers)


def prompt_header(item_id: str) -> PromptHeader | None:
    for header in _load_target_headers():
        if header.item_id == item_id:
            return header
    return None


def prompt_header_for_file(filename: str) -> PromptHeader | None:
    for header in _load_target_headers():
        if header.filename == filename:
            return header
    for header in _load_injected_headers():
        if header.filename == filename:
            return header
    for header in _load_prefix_headers():
        if filename.startswith(header.prefix):
            return PromptHeader(
                item_id=None,
                filename=filename,
                label=header.label,
                default_text=None,
                role=header.role,
                help_text=header.help_text,
                prompt_text=header.prompt_text,
            )
    return None


def prompt_header_for_path(path: Path | str) -> PromptHeader | None:
    path_obj = Path(path)
    normalized = path_obj.as_posix().lstrip("./")
    for header in _load_pattern_headers():
        if (
            path_obj.match(header.pattern)
            or normalized == header.pattern
            or normalized.endswith(header.pattern.lstrip("./"))
        ):
            return PromptHeader(
                item_id=None,
                filename=path_obj.name,
                label=header.label,
                default_text=None,
                role=header.role,
                help_text=header.help_text,
                prompt_text=header.prompt_text,
            )
    return prompt_header_for_file(path_obj.name)


def prompt_headers() -> tuple[PromptHeader, ...]:
    return _load_target_headers()
