"""JSON-backed metadata for prompt-facing target documents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from drydock.errors import DrydockError
from drydock.paths import get_prompts_root


@dataclass(frozen=True)
class PromptHeader:
    item_id: str
    filename: str
    label: str
    default_text: str | None
    help_text: str
    prompt_text: str


@lru_cache(maxsize=1)
def _load_headers() -> tuple[PromptHeader, ...]:
    path = get_prompts_root() / "prompts.json"
    if not path.is_file():
        raise DrydockError(f"prompt header metadata not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    target_docs = payload.get("target_docs")
    if not isinstance(target_docs, dict):
        raise DrydockError("prompts.json missing object field 'target_docs'")
    headers: list[PromptHeader] = []
    for filename, item in target_docs.items():
        if not isinstance(item, dict):
            raise DrydockError(f"prompts.json entry for {filename!r} is not an object")
        headers.append(
            PromptHeader(
                item_id=str(item.get("item_id", "")).strip(),
                filename=filename,
                label=str(item.get("label", "")).strip(),
                default_text=item.get("default_text"),
                help_text=str(item.get("help_text", "")).strip(),
                prompt_text=str(item.get("prompt_text", "")).strip(),
            )
        )
    return tuple(headers)


def prompt_header(item_id: str) -> PromptHeader | None:
    for header in _load_headers():
        if header.item_id == item_id:
            return header
    return None


def prompt_header_for_file(filename: str) -> PromptHeader | None:
    for header in _load_headers():
        if header.filename == filename:
            return header
    return None


def prompt_headers() -> tuple[PromptHeader, ...]:
    return _load_headers()
