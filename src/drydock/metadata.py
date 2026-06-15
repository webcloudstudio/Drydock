"""METADATA.md field parser and Target manifest.

``METADATA.md`` records project identity plus a small manifest: the Blueprint
name and ``code_root`` (where the built/served code lives). Fields are simple
``key: value`` lines above the first ``## `` section, read with a tolerant
scalar parser so hand edits do not break resolution. There is no YAML dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

METADATA_NAME = "METADATA.md"
DEFAULT_CODE_ROOT = "../.."

BUILD_STATE_LADDER: tuple[str, ...] = ("init", "analyzed", "planned", "building", "built")


def parse_metadata(path: Path) -> dict[str, str]:
    """
    Parse a METADATA.md file and return a dict of field -> value.

    Handles both 'key: value' frontmatter-style lines and the
    '## Agent Instructions' section boundary (stops there).
    """
    fields: dict[str, str] = {}
    if not path.exists():
        return fields

    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        # Stop at section headers — metadata fields are above them
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


def render_metadata(
    target: str,
    *,
    blueprint: str | None = None,
    code_root: str = DEFAULT_CODE_ROOT,
    display_name: str = "",
    short_description: str = "",
) -> str:
    """Render a minimal project METADATA.md carrying the manifest fields."""
    dn = display_name.strip() or target
    sd = short_description.strip()
    return (
        f"# {target}\n\n"
        f"display_name: {dn}\n"
        f"short_description: {sd}\n\n"
        f"name: {target}\n"
        f"blueprint: {blueprint or target}\n"
        f"code_root: {code_root}\n"
        "status: IDEA\n"
        "type: oneshot\n\n"
        "## Agent Instructions\n\n"
        "Record unresolved questions in the `## Open Questions` section of the "
        "relevant blueprint file.\n"
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


def get_code_root(target_dir: Path) -> Path:
    """Resolve the Target's ``code_root`` to an absolute path.

    Relative roots resolve against the Target directory; an absent or empty value
    falls back to the default (``$DRYDOCK_WORKSPACE``).
    """
    fields = parse_metadata(target_dir / METADATA_NAME)
    value = fields.get("code_root") or DEFAULT_CODE_ROOT
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (target_dir / candidate).resolve()
