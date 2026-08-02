"""Deterministic write authorization managed inside a Target Compass."""

from __future__ import annotations

from pathlib import Path

from drydock.config import build_dir_for
from drydock.errors import SpecificationError

START_MARKER = "<!-- drydock:build-write-guardrail:start -->"
END_MARKER = "<!-- drydock:build-write-guardrail:end -->"
HEADING = "## Build Write Guardrail"


def guardrail_text(target: str, target_dir: Path, *, build_dir: Path | None = None) -> str:
    """Render the managed guardrail with fully resolved active paths."""
    resolved_target = target_dir.expanduser().resolve()
    resolved_build = (build_dir or build_dir_for(target)).expanduser().resolve()
    lines = [
        START_MARKER,
        HEADING,
        "",
        f"- Authorized build directory: `{resolved_build}`",
        f"- Authorized Target directory: `{resolved_target}`",
        "- Build agents have permission to create, modify, and remove files required by the "
        "active build block inside these authorized directories.",
        "- No path outside these authorized directories may be modified.",
        "- Protected Drydock artifacts:",
        f"  - `{resolved_target / 'blueprint'}/`",
        f"  - `{resolved_target / 'MANIFEST.md'}`",
        f"  - `{resolved_target / 'COMPASS.md'}`",
        f"  - `{resolved_target / 'QuarterDeck'}/`",
        f"  - `{resolved_target / 'evidence'}/`",
        END_MARKER,
    ]
    return "\n".join(lines)


def apply_guardrail(
    content: str,
    target: str,
    target_dir: Path,
    *,
    build_dir: Path | None = None,
) -> str:
    """Add or replace exactly one managed guardrail section."""
    body = content.rstrip()
    start = body.find(START_MARKER)
    end = body.find(END_MARKER)
    if start >= 0 and end >= start:
        end += len(END_MARKER)
        body = (body[:start].rstrip() + "\n\n" + body[end:].lstrip()).rstrip()
    elif HEADING in body:
        # A markerless managed section from an early implementation is replaced through the
        # next level-two heading (or EOF), avoiding duplicate authorization text.
        start = body.index(HEADING)
        next_heading = body.find("\n## ", start + len(HEADING))
        end = len(body) if next_heading < 0 else next_heading + 1
        body = (body[:start].rstrip() + "\n\n" + body[end:].lstrip()).rstrip()
    managed = guardrail_text(target, target_dir, build_dir=build_dir)
    return f"{body}\n\n{managed}\n" if body else managed + "\n"


def strip_guardrail(content: str) -> str:
    """Remove the managed section before asking an LLM to author Compass prose."""
    start = content.find(START_MARKER)
    end = content.find(END_MARKER)
    if start < 0 or end < start:
        return content
    end += len(END_MARKER)
    return (content[:start].rstrip() + "\n\n" + content[end:].lstrip()).rstrip() + "\n"


def write_guardrail(
    compass_path: Path,
    target: str,
    target_dir: Path,
    *,
    build_dir: Path | None = None,
) -> None:
    """Mechanically normalize the guardrail in an existing Compass."""
    content = compass_path.read_text(encoding="utf-8") if compass_path.is_file() else ""
    normalized = apply_guardrail(content, target, target_dir, build_dir=build_dir)
    compass_path.parent.mkdir(parents=True, exist_ok=True)
    compass_path.write_text(normalized, encoding="utf-8", newline="\n")


def validate_guardrail(
    compass_path: Path,
    target: str,
    target_dir: Path,
    *,
    build_dir: Path | None = None,
) -> None:
    """Fail Build before execution when the persisted authorization is absent or stale."""
    expected = guardrail_text(target, target_dir, build_dir=build_dir)
    content = compass_path.read_text(encoding="utf-8") if compass_path.is_file() else ""
    if content.count(START_MARKER) == 1 and expected in content:
        return
    raise SpecificationError(
        "COMPASS.md Build Write Guardrail is missing or stale for the active configuration.\n"
        f"  Expected build directory: {(build_dir or build_dir_for(target)).resolve()}\n"
        f"  Expected Target directory: {target_dir.resolve()}\n"
        f"  Recreate it with: drydock analyze {target}"
    )
