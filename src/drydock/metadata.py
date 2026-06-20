"""METADATA.md field parser and build-directory resolution.

``METADATA.md`` records project identity (name, display_name, short_description,
stack, version) and optional fields (brand, git_repo, release_tag, build_dir).
Fields are simple ``key: value`` lines; a tolerant scalar parser handles hand
edits without a YAML dependency.

``drydock_build_state`` is the lifecycle state field written by Drydock commands.
"""

from __future__ import annotations

import re
from pathlib import Path

METADATA_NAME = "METADATA.md"

BUILD_STATE_LADDER: tuple[str, ...] = ("init", "analyzed", "planned", "building", "built")


def parse_metadata(path: Path) -> dict[str, str]:
    """Parse a METADATA.md file and return a dict of field -> value.

    Reads ``key: value`` lines. Stops at the first ``## `` section header.
    """
    fields: dict[str, str] = {}
    if not path.exists():
        return fields

    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("## "):
            break
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def get_field(metadata: dict[str, str], key: str) -> str | None:
    """Return stripped value or None."""
    val = metadata.get(key, "").strip()
    return val if val else None


def load_metadata_vars(target_dir: Path) -> dict[str, str]:
    """Return all METADATA.md fields as a variable dict for prompt assembly."""
    return parse_metadata(target_dir / METADATA_NAME)


def render_metadata(
    target: str,
    *,
    display_name: str = "",
    short_description: str = "",
    stack: str = "",
    version: str = "",
) -> str:
    """Render a METADATA.md scaffold for a new target."""
    dn = display_name.strip() or target
    sd = short_description.strip()
    return (
        "# AUTHORITATIVE PROJECT METADATA — FIELDS SHOULD BE CURRENT\n\n"
        f"name: {target}\n"
        f"display_name: {dn}\n"
        f"short_description: {sd}\n"
        f"stack: {stack}\n"
        f"version: {version}\n"
    )


def get_build_state(target_dir: Path) -> str:
    """Return the current ``drydock_build_state`` from METADATA.md, defaulting to ``init``."""
    fields = parse_metadata(target_dir / METADATA_NAME)
    state = fields.get("drydock_build_state", "init")
    return state if state in BUILD_STATE_LADDER else "init"


def set_build_state(target_dir: Path, state: str) -> bool:
    """Advance ``drydock_build_state`` in METADATA.md (forward-only).

    Returns True if the state was written, False if already at or past ``state``.
    Does nothing if METADATA.md does not exist.
    """
    if state not in BUILD_STATE_LADDER:
        raise ValueError(f"Unknown build state: {state!r}")
    path = target_dir / METADATA_NAME
    if not path.exists():
        return False
    current = get_build_state(target_dir)
    curr_idx = BUILD_STATE_LADDER.index(current)
    new_idx = BUILD_STATE_LADDER.index(state)
    if new_idx <= curr_idx:
        return False
    text = path.read_text(encoding="utf-8")
    field = "drydock_build_state"
    new_line = f"{field}: {state}"
    if re.search(rf"^{field}:", text, re.MULTILINE):
        text = re.sub(rf"^{field}:.*$", new_line, text, flags=re.MULTILINE)
    elif re.search(r"^## ", text, re.MULTILINE):
        text = re.sub(r"^(## )", rf"{new_line}\n\n\1", text, count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{new_line}\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def get_build_dir(target: str, target_dir: Path, cli_override: str | None = None) -> Path:
    """Resolve where build output for this target should be written.

    Resolution order:
    1. ``cli_override`` (from ``--build-dir`` argument)
    2. ``build_dir`` field in METADATA.md
    3. ``$DRYDOCK_BUILD_DIRECTORY/<target>`` (config default)
    """
    if cli_override:
        return Path(cli_override).expanduser().resolve()
    fields = parse_metadata(target_dir / METADATA_NAME)
    stored = fields.get("build_dir", "").strip()
    if stored:
        return Path(stored).expanduser().resolve()
    from drydock.config import build_dir_for

    return build_dir_for(target)
