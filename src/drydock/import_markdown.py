"""Import arbitrary Markdown source material into a Drydock Blueprint."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from drydock.artifact_blocks import parse_artifact_blocks
from drydock.compass_sources import clear_compass_import_pending, seed_compass_from_sources
from drydock.errors import SpecificationError, UsageError
from drydock.init_specification import init_specification
from drydock.llm import run_prompt
from drydock.prompts import load_prompt
from drydock.source_refit import record_import_root

_COMPASS_PROMPT_NAME = "import_compass"


class _CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str


_RunnerFn = Callable[..., _CompletedRun]

_CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".go",
    ".rs",
    ".rb",
    ".java",
    ".cpp",
    ".c",
    ".h",
})


@dataclass(frozen=True)
class ImportResult:
    blueprint: str
    target: str
    blueprint_dir: Path
    source: Path
    imported: tuple[Path, ...]
    initialized: bool


def detect_import_format(source: Path) -> str:
    """Infer the import format from the source path.

    Precedence: speckit (.specify/ present) → source (code files present) → markdown.
    Raises UsageError when format cannot be determined.
    """
    if (source / ".specify").is_dir():
        return "speckit"
    if source.is_dir() and any(
        p.suffix in _CODE_EXTENSIONS for p in source.rglob("*") if p.is_file()
    ):
        return "source"
    if source.suffix.lower() == ".md":
        return "markdown"
    if source.is_dir() and any(p.suffix.lower() == ".md" for p in source.rglob("*") if p.is_file()):
        return "markdown"
    raise UsageError(
        f"Cannot detect import format for: {source}\n"
        "  Specify --format markdown, --format source, or --format speckit."
    )


def _import_files(source: Path) -> list[tuple[Path, Path]]:
    if source.is_file():
        return [(source, Path(source.name))]
    if not source.is_dir():
        raise SpecificationError(f"Import source not found: {source}")
    files = [
        (path, path.relative_to(source)) for path in sorted(source.rglob("*")) if path.is_file()
    ]
    if not files:
        raise SpecificationError(f"No files found under: {source}")
    return files


def import_markdown(
    blueprint: str, target: str, source: Path, target_directory: Path
) -> ImportResult:
    """Preserve a Markdown import file or directory under ``blueprint/sources/``.

    A directory is copied recursively without filtering by extension so referenced
    assets and companion files remain available to downstream analysis.

    Seeds only root identity files (METADATA.md, README.md). Typed spec files are
    ``plan create`` outputs; COMPASS.md is an ``analyze`` output. After import,
    ``blueprint/`` holds only ``sources/``.
    """
    source = source.expanduser().resolve()
    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    initialized = not (target_dir / "METADATA.md").exists()
    init_specification(blueprint, target_dir, update=True, root_identity_only=True)

    sources_dir = blueprint_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    record_import_root(sources_dir, source, "markdown")
    imported: list[Path] = []
    for source_path, relative in _import_files(source):
        destination = sources_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
        imported.append(destination)
    seed_compass_from_sources(target_dir, imported, overwrite_unpopulated=False)

    return ImportResult(
        blueprint=blueprint,
        target=target,
        blueprint_dir=blueprint_dir,
        source=source,
        imported=tuple(imported),
        initialized=initialized,
    )


def _assemble_compass_prompt(target: str, intent_text: str) -> str:
    prompt = load_prompt(_COMPASS_PROMPT_NAME)
    return "\n".join([
        prompt.body,
        "",
        "# Input Context",
        "",
        "## Import job",
        "",
        f"- TARGET_NAME: {target}",
        "",
        "## INTENT_DOCUMENT (Commander-supplied intent — normalize this)",
        "",
        "=== INTENT_DOCUMENT ===",
        intent_text.strip(),
        "=== END INTENT_DOCUMENT ===",
    ])


def import_intent(
    target: str,
    source: Path,
    target_directory: Path,
    *,
    force: bool = False,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
    runner: _RunnerFn | None = None,
) -> ImportResult:
    """Normalize a user intent document into COMPASS.md at the Target root.

    This is the only import format that runs an LLM. The source document is reformatted
    once into the canonical COMPASS.md sections, preserving the Commander's vocabulary;
    the written file is final and Commander-owned. ``drydock analyze`` never rewrites a
    populated COMPASS.md, so re-importing with ``--force`` is the way to regenerate it.
    """
    source = source.expanduser().resolve()
    if not source.exists():
        raise SpecificationError(f"Intent source not found: {source}")
    if not source.is_file():
        raise SpecificationError(f"Compass import requires a file: {source}")
    intent_text = source.read_text(encoding="utf-8")
    if not intent_text.strip():
        raise SpecificationError(f"Intent source is empty: {source}")

    target_dir = target_directory / target
    dest = target_dir / "COMPASS.md"
    if dest.is_file() and not force:
        raise SpecificationError(
            f"COMPASS.md already exists: {dest}\n  Use --force to overwrite it."
        )
    target_dir.mkdir(parents=True, exist_ok=True)

    run = runner if runner is not None else run_prompt
    result = run(
        _assemble_compass_prompt(target, intent_text),
        target_dir,
        llm=llm_provider,
        model=model,
        command_name="import_compass",
        parameters={"target": target, "source": str(source)},
        log_dir=log_dir,
        target=target,
    )
    if not result.ok or not result.text.strip():
        raise SpecificationError("Compass normalization failed: LLM execution failed")

    blocks = parse_artifact_blocks(
        result.text, label="import compass output", allowed_names={"COMPASS.md"}
    )
    compass_text = (blocks.get("COMPASS.md") or "").strip()
    if not compass_text:
        raise SpecificationError("Compass normalization failed: no COMPASS.md block in LLM output")

    from drydock.compass_guardrail import apply_guardrail

    dest.write_text(
        apply_guardrail(compass_text, target, target_dir), encoding="utf-8", newline="\n"
    )
    # The file is normalized and final at import time — no analyze pass is pending.
    clear_compass_import_pending(target_dir)

    return ImportResult(
        blueprint=target,
        target=target,
        blueprint_dir=target_dir,
        source=source,
        imported=(dest,),
        initialized=False,
    )
