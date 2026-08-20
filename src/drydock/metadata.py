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

import os
import re
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

METADATA_NAME = "METADATA.md"
IDENTITY_FIELDS = frozenset({"display_name", "short_description"})

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
        "updated: \n"
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


def _atomic_write(path: Path, text: str) -> None:
    """Replace *path* atomically with UTF-8 metadata text."""
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _replace_field(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:[ \t]*(.*)$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(f"{key}: {value}", text)
    if re.search(r"^## ", text, re.MULTILINE):
        return re.sub(r"^(## )", rf"{key}: {value}\n\n\1", text, count=1, flags=re.MULTILINE)
    return text.rstrip("\n") + f"\n{key}: {value}\n"


def _next_version(current: str) -> str:
    try:
        value = round(float(current) + 0.01, 2) if current else 0.01
    except ValueError:
        value = 0.01
    return f"{value:.2f}"


def set_fields(path: Path, values: Mapping[str, str], *, overwrite: bool = False) -> bool:
    """Atomically persist changed metadata fields and stamp its revision.

    One effective change increments ``version`` and sets ``updated`` once, regardless of the
    number of fields written.  This is the mutation boundary used by Drydock and QuarterDeck.
    """
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    fields = parse_metadata(path)
    changed = False
    for key, value in values.items():
        current = fields.get(key, "").strip()
        if current == value:
            continue
        if current and not overwrite:
            continue
        text = _replace_field(text, key, value)
        fields[key] = value
        changed = True
    if not changed:
        return False
    text = _replace_field(text, "version", _next_version(fields.get("version", "")))
    text = _replace_field(text, "updated", datetime.now(UTC).isoformat(timespec="seconds"))
    _atomic_write(path, text)
    return True


def set_field(path: Path, key: str, value: str, *, overwrite: bool = False) -> bool:
    """Write one field through :func:`set_fields`."""
    return set_fields(path, {key: value}, overwrite=overwrite)


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
        fields = parse_metadata(path)
        text = _replace_field(text, "version", _next_version(fields.get("version", "")))
        text = _replace_field(text, "updated", datetime.now(UTC).isoformat(timespec="seconds"))
        _atomic_write(path, text)
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
    new_version = _next_version(fields.get("version", ""))
    text = _replace_field(path.read_text(encoding="utf-8"), "version", new_version)
    text = _replace_field(text, "updated", datetime.now(UTC).isoformat(timespec="seconds"))
    _atomic_write(path, text)
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
