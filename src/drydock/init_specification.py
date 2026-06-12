"""Internal Blueprint template initialization used by import and conformance workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, auto
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.paths import get_spec_template_dir

_TRAVERSAL_RE = re.compile(r"\.\.|[/\\]")
_UNSAFE_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


class FileOutcome(Enum):
    CREATED = auto()
    UPDATED = auto()
    SKIPPED = auto()


@dataclass
class InitResult:
    spec_name: str
    spec_dir: Path
    outcomes: list[tuple[str, FileOutcome]] = field(default_factory=list)

    def created(self) -> list[str]:
        return [n for n, o in self.outcomes if o == FileOutcome.CREATED]

    def updated(self) -> list[str]:
        return [n for n, o in self.outcomes if o == FileOutcome.UPDATED]

    def skipped(self) -> list[str]:
        return [n for n, o in self.outcomes if o == FileOutcome.SKIPPED]


def _validate_spec_name(name: str) -> None:
    if not name or not name.strip():
        raise SpecificationError("Blueprint name must not be empty.")
    if _TRAVERSAL_RE.search(name):
        raise SpecificationError(
            f"Blueprint name must not contain path separators or '..': {name!r}"
        )
    if _UNSAFE_CHARS_RE.search(name):
        raise SpecificationError(f"Blueprint name contains invalid characters: {name!r}")
    if len(name) > 200:
        raise SpecificationError("Blueprint name is too long (max 200 characters).")


def _derive_display_name(slug: str) -> str:
    parts = re.split(r"[-_]+", slug)
    return " ".join(p.capitalize() for p in parts if p)


def _apply_tokens(text: str, slug: str, display_name: str, today: str, today_compact: str) -> str:
    return (
        text.replace("__PROJECT_NAME__", display_name)
        .replace("__PROJECT_SLUG__", slug)
        .replace("__SHORT_DESCRIPTION__", "TODO: add short description")
        .replace("__TODAY__", today)
        .replace("__TODAY_COMPACT__", today_compact)
    )


def init_specification(
    spec_name: str,
    blueprint_directory: Path,
    *,
    update: bool = False,
    force: bool = False,
) -> InitResult:
    """
    Create or update a Blueprint from packaged Typed Specification templates.

    Raises:
        SpecificationError: On invalid name or filesystem failure.
    """
    _validate_spec_name(spec_name)

    spec_dir = blueprint_directory / spec_name

    if spec_dir.exists() and not update and not force:
        raise SpecificationError(
            f"Directory already exists: {spec_dir}\n"
            "  Use --update to add missing files, or --force to overwrite all."
        )

    try:
        spec_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SpecificationError(f"Cannot create directory {spec_dir}: {exc}") from exc

    template_dir = get_spec_template_dir()
    if not template_dir.is_dir():
        raise SpecificationError(
            f"Template directory not found: {template_dir}\n"
            "  Reinstall drydock or run from the source tree."
        )

    today = date.today().isoformat()
    today_compact = date.today().strftime("%Y%m%d")
    display_name = _derive_display_name(spec_name)

    result = InitResult(spec_name=spec_name, spec_dir=spec_dir)

    for tmpl_path in sorted(template_dir.glob("*.md")):
        fname = tmpl_path.name
        dest = spec_dir / fname
        already_exists = dest.exists()

        if already_exists and not force:
            result.outcomes.append((fname, FileOutcome.SKIPPED))
            continue

        try:
            raw = tmpl_path.read_text(encoding="utf-8")
            processed = _apply_tokens(raw, spec_name, display_name, today, today_compact)
            dest.write_text(processed, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise SpecificationError(f"Cannot write {dest}: {exc}") from exc

        outcome = FileOutcome.UPDATED if already_exists else FileOutcome.CREATED
        result.outcomes.append((fname, outcome))

    return result
