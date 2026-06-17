"""Versioned task prompts with a required YAML frontmatter contract.

Every Drydock prompt is a Markdown file under ``prompts/`` named
``<command>_<subcommand>[_<modifier>].md`` and headed by a ``---`` frontmatter
block carrying the prompt contract metadata.

Required frontmatter fields: ``name``, ``description``, ``version``, ``intent``.
Optional fields commonly used: ``command``, ``model``, ``inputs``, ``output``.

``inputs`` is an ordered, comma-delimited list of logical input tokens — the
agent's declared injection (stack) order, COMPASS.md first. Single files are
named by filename; globbed groups use a suffix-less token (e.g. ``QUESTIONNAIRES``,
``TYPED_SPEC``). The assembler resolves each token to real paths.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import DrydockError
from drydock.paths import get_prompts_root

SectionRenderer = Callable[[], list[str]]

REQUIRED_FIELDS: tuple[str, ...] = ("name", "description", "version", "intent")

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Prompt:
    """A loaded prompt: parsed frontmatter metadata plus the prompt body."""

    name: str
    meta: dict[str, str]
    body: str
    path: Path

    @property
    def model(self) -> str | None:
        return self.meta.get("model")

    @property
    def input_tokens(self) -> tuple[str, ...]:
        """Ordered logical input tokens from the ``inputs`` frontmatter row.

        The declared injection order (COMPASS.md first). Empty when no ``inputs``
        row is present. The assembler resolves each token to real paths/globs.
        """
        raw = self.meta.get("inputs", "")
        return tuple(token.strip() for token in raw.split(",") if token.strip())

    @property
    def version(self) -> str:
        return self.meta["version"]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split ``--- key: value --- body`` into a scalar mapping and the body.

    A deliberately small parser: scalar ``key: value`` lines only, no nested
    structures, so Drydock carries no YAML dependency. Quotes around values are
    stripped. Blank lines and ``#`` comments inside the block are ignored.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        raise DrydockError("prompt is missing a '---' YAML frontmatter block")

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key_value = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", stripped)
        if key_value is None:
            raise DrydockError(f"prompt frontmatter line is not 'key: value': {line!r}")
        key, value = key_value.group(1), key_value.group(2).strip()
        meta[key] = value.strip("'\"")

    return meta, match.group(2).strip("\n")


def _validate(meta: dict[str, str], path: Path) -> None:
    missing = [field for field in REQUIRED_FIELDS if not meta.get(field)]
    if missing:
        raise DrydockError(
            f"prompt {path.name} is missing required frontmatter field(s): {', '.join(missing)}"
        )


def render_inputs(tokens: Iterable[str], renderers: Mapping[str, SectionRenderer]) -> list[str]:
    """Emit prompt sections for ``tokens`` in order, driven by the ``inputs:`` row.

    ``renderers`` maps an input token to a callable returning that section's lines
    (or an empty list to inject nothing — e.g. an absent conditional input). Tokens
    with no renderer are skipped: they are declared inputs whose meaning lives
    elsewhere (``COMPASS.md`` is the COMPASS_EXISTS flag for ``analyze``; ``BLOCKERS.md``
    is the refuse-if-present gate for ``plan create`` and never reaches assembly). This
    makes the prompt's ``inputs:`` order the single source of truth for injection order.
    """
    parts: list[str] = []
    for token in tokens:
        render = renderers.get(token)
        if render is None:
            continue
        parts.extend(render())
    return parts


def load_prompt(name: str) -> Prompt:
    """Load and validate ``prompts/<name>.md`` from the resolved prompts root."""
    path = get_prompts_root() / f"{name}.md"
    if not path.is_file():
        raise DrydockError(f"prompt not found: {path}")
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    _validate(meta, path)
    return Prompt(name=meta["name"], meta=meta, body=body, path=path)
