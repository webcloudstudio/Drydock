"""METADATA.md field parser, lifecycle tracker, and build-directory resolution.

``METADATA.md`` records project identity and lifecycle state. Fields are simple
``key: value`` lines; a tolerant scalar parser handles hand edits without a YAML
dependency.

Identity fields (set at init, prompted at analyze if blank):
  name, display_name, short_description, stack, version

Lifecycle fields (written by Drydock commands):
  build_state       — forward-only ladder: init → analyzed → planned → building → built
  build_sub_state   — command-specific phase within the current build_state
  last_analyzed     — ISO date of last successful drydock analyze
  last_planned      — ISO date of last successful drydock plan create
  last_built        — ISO date of last successful drydock build

Optional user-managed fields:
  build_dir, brand, git_repo, release_tag
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

METADATA_NAME = "METADATA.md"

BUILD_STATE_LADDER: tuple[str, ...] = ("init", "analyzed", "planned", "building", "built")

_FIELD_RE = re.compile(r"^([a-z_]+):\s*(.*)$")


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
        m = _FIELD_RE.match(line.rstrip())
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
    """Render a METADATA.md scaffold for a new target with all fields present."""
    dn = display_name.strip() or target
    sd = short_description.strip()
    return (
        "# AUTHORITATIVE PROJECT METADATA — FIELDS SHOULD BE CURRENT\n\n"
        f"name: {target}\n"
        f"display_name: {dn}\n"
        f"short_description: {sd}\n"
        f"stack: {stack}\n"
        f"version: {version}\n"
        "build_state: \n"
        "build_sub_state: \n"
        "last_analyzed: \n"
        "last_planned: \n"
        "last_built: \n"
        "build_dir: \n"
        "brand: \n"
        "git_repo: \n"
        "release_tag: \n"
    )


# ---------------------------------------------------------------------------
# Generic field writer
# ---------------------------------------------------------------------------


def set_field(path: Path, key: str, value: str, *, overwrite: bool = False) -> bool:
    """Write ``key: value`` into a METADATA.md file.

    With ``overwrite=False`` (default), skips when the field already has a
    non-empty value — preserving user edits.  With ``overwrite=True``, always
    replaces.  Returns True if written, False if skipped or file absent.
    """
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}:[ \t]*(.*)$", re.MULTILINE)
    m = pattern.search(text)
    if m:
        current = m.group(1).strip()
        if current and not overwrite:
            return False
        text = pattern.sub(f"{key}: {value}", text)
    elif re.search(r"^## ", text, re.MULTILINE):
        text = re.sub(r"^(## )", rf"{key}: {value}\n\n\1", text, count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{key}: {value}\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


# ---------------------------------------------------------------------------
# Lifecycle state
# ---------------------------------------------------------------------------


def get_build_state(target_dir: Path) -> str:
    """Return the current ``build_state`` from METADATA.md, defaulting to ``init``."""
    fields = parse_metadata(target_dir / METADATA_NAME)
    # Accept both the current field name and the legacy drydock_build_state name.
    state = fields.get("build_state") or fields.get("drydock_build_state", "init")
    return state if state in BUILD_STATE_LADDER else "init"


def set_build_state(target_dir: Path, state: str) -> bool:
    """Advance ``build_state`` in METADATA.md (forward-only).

    Returns True if the state was written, False if already at or past ``state``.
    Does nothing if METADATA.md does not exist.
    """
    if state not in BUILD_STATE_LADDER:
        raise ValueError(f"Unknown build state: {state!r}")
    path = target_dir / METADATA_NAME
    if not path.exists():
        return False
    current = get_build_state(target_dir)
    if BUILD_STATE_LADDER.index(state) <= BUILD_STATE_LADDER.index(current):
        return False
    # Write build_state; also migrate a legacy drydock_build_state field if present.
    text = path.read_text(encoding="utf-8")
    if re.search(r"^drydock_build_state:", text, re.MULTILINE):
        text = re.sub(
            r"^drydock_build_state:.*$", f"build_state: {state}", text, flags=re.MULTILINE
        )
        path.write_text(text, encoding="utf-8", newline="\n")
        return True
    set_field(path, "build_state", state, overwrite=True)
    return True


def set_sub_state(target_dir: Path, sub_state: str) -> None:
    """Write ``build_sub_state`` in METADATA.md."""
    set_field(target_dir / METADATA_NAME, "build_sub_state", sub_state, overwrite=True)


def get_sub_state(target_dir: Path) -> str:
    """Return the current ``build_sub_state`` from METADATA.md, or an empty string.

    Unlike ``build_state`` this is free-form: it names the phase a command is in, so it has no
    ladder to validate against and an unknown value is reported as written.
    """
    fields = parse_metadata(target_dir / METADATA_NAME)
    return (fields.get("build_sub_state") or "").strip()


def stamp_last(target_dir: Path, command: str) -> None:
    """Write today's ISO date to ``last_<command>`` in METADATA.md."""
    set_field(
        target_dir / METADATA_NAME,
        f"last_{command}",
        date.today().isoformat(),
        overwrite=True,
    )


def increment_version(target_dir: Path) -> str:
    """Increment ``version`` in METADATA.md by 0.01, starting at 0.01.

    Returns the new version string.  No-ops if METADATA.md is absent (returns
    ``"0.01"`` without writing).
    """
    path = target_dir / METADATA_NAME
    if not path.exists():
        return "0.01"
    fields = parse_metadata(path)
    current = fields.get("version", "").strip()
    try:
        new_val = round(float(current) + 0.01, 2) if current else 0.01
    except ValueError:
        new_val = 0.01
    new_version = f"{new_val:.2f}"
    set_field(path, "version", new_version, overwrite=True)
    return new_version


# ---------------------------------------------------------------------------
# Build directory resolution
# ---------------------------------------------------------------------------


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
