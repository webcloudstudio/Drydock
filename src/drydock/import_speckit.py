"""Import a Spec Kit project into a Drydock Blueprint via LLM translation.

Discovers `.specify/memory/constitution.md` and `specs/<feature>/` directories, assembles a
translation prompt, and writes the resulting Blueprint files and a conversion report.

The LLM emits text only; file writing is deterministic in this module so tests inject a fake
runner without spending API credits.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from drydock.errors import LlmError, SpecificationError
from drydock.import_source import _ROOT_TEMPLATE_NAMES, parse_file_blocks
from drydock.init_specification import init_specification
from drydock.llm import run_prompt
from drydock.prompts import load_prompt

PROMPT_NAME = "import_speckit"

_CONVERSION_REPORT_RE = re.compile(
    r"<conversion-report>(.*?)</conversion-report>", re.DOTALL
)

CONVERSION_REPORT_FILENAME = "sources/speckit_conversion_report.md"


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...
    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]


@dataclass(frozen=True)
class SpecKitFeature:
    name: str
    spec: str | None = None
    plan: str | None = None
    research: str | None = None
    data_model: str | None = None
    contracts: dict[str, str] = field(default_factory=dict)
    quickstart: str | None = None


@dataclass(frozen=True)
class ImportSpecKitResult:
    blueprint: str
    target: str
    blueprint_dir: Path
    source: Path
    features_found: tuple[str, ...]
    files_written: tuple[str, ...]
    conversion_report: Path
    execution_id: str


def _read_optional(path: Path) -> str | None:
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
    return None


def _read_contracts(feature_dir: Path) -> dict[str, str]:
    contracts: dict[str, str] = {}
    contracts_dir = feature_dir / "contracts"
    if contracts_dir.is_dir():
        try:
            for p in sorted(contracts_dir.iterdir()):
                if p.is_file():
                    content = _read_optional(p)
                    if content is not None:
                        contracts[p.name] = content
        except OSError:
            pass
    return contracts


def _discover_speckit(source: Path) -> tuple[str | None, list[SpecKitFeature]]:
    """Discover Spec Kit constitution and feature directories.

    Raises SpecificationError if source is not a Spec Kit project.
    """
    specify_dir = source / ".specify"
    if not specify_dir.is_dir():
        raise SpecificationError(
            f"Not a Spec Kit project (no .specify/ directory): {source}\n"
            "  Use --format markdown or --format source for other source types."
        )

    constitution = _read_optional(specify_dir / "memory" / "constitution.md")

    features: list[SpecKitFeature] = []
    specs_dir = source / "specs"
    if specs_dir.is_dir():
        try:
            for feature_dir in sorted(specs_dir.iterdir()):
                if not feature_dir.is_dir():
                    continue
                features.append(
                    SpecKitFeature(
                        name=feature_dir.name,
                        spec=_read_optional(feature_dir / "spec.md"),
                        plan=_read_optional(feature_dir / "plan.md"),
                        research=_read_optional(feature_dir / "research.md"),
                        data_model=_read_optional(feature_dir / "data-model.md"),
                        contracts=_read_contracts(feature_dir),
                        quickstart=_read_optional(feature_dir / "quickstart.md"),
                    )
                )
        except OSError:
            pass

    return constitution, features


def _fence(label: str, content: str | None) -> str:
    if content is None:
        return ""
    return f"#### {label}\n```markdown\n{content}\n```\n"


def _assemble_prompt(
    prompt_body: str,
    blueprint: str,
    constitution: str | None,
    features: list[SpecKitFeature],
) -> str:
    sections: list[str] = []

    if constitution is not None:
        sections.append(f"### .specify/memory/constitution.md\n```markdown\n{constitution}\n```")
    else:
        sections.append("### .specify/memory/constitution.md\n*(not present)*")

    for feature in features:
        parts: list[str] = [f"### specs/{feature.name}/"]
        parts.append(_fence(f"specs/{feature.name}/spec.md", feature.spec))
        parts.append(_fence(f"specs/{feature.name}/plan.md", feature.plan))
        parts.append(_fence(f"specs/{feature.name}/research.md", feature.research))
        parts.append(_fence(f"specs/{feature.name}/data-model.md", feature.data_model))
        for contract_name, contract_content in feature.contracts.items():
            parts.append(_fence(f"specs/{feature.name}/contracts/{contract_name}", contract_content))
        parts.append(_fence(f"specs/{feature.name}/quickstart.md", feature.quickstart))
        sections.append("\n".join(p for p in parts if p))

    speckit_content = "\n\n".join(sections)

    return (
        prompt_body.replace("{{PROJECT_NAME}}", blueprint)
        .replace("{{SPECKIT_CONTENT}}", speckit_content)
    )


def import_speckit(
    blueprint: str,
    target: str,
    source: Path,
    target_directory: Path,
    *,
    runner: RunnerFn = run_prompt,
) -> ImportSpecKitResult:
    """Translate a Spec Kit project into a Drydock Blueprint using an LLM."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SpecificationError(
            f"Import source must be a directory for --format speckit: {source}"
        )

    constitution, features = _discover_speckit(source)

    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    init_specification(blueprint, target_dir, update=True)

    prompt = load_prompt(PROMPT_NAME)
    full_prompt = _assemble_prompt(prompt.body, blueprint, constitution, features)

    result = runner(
        full_prompt,
        blueprint_dir,
        command_name=PROMPT_NAME,
        parameters={
            "blueprint": blueprint,
            "target": target,
            "source": str(source),
            "features": [f.name for f in features],
        },
    )

    if not result.ok:
        raise LlmError(
            f"LLM execution failed for import_speckit; execution_id={result.execution_id}"
        )

    files = parse_file_blocks(result.text)

    # Write conversion report regardless of file count
    report_content = ""
    report_match = _CONVERSION_REPORT_RE.search(result.text)
    if report_match:
        report_content = report_match.group(1).strip()
    else:
        report_content = (
            "# Spec Kit Conversion Report\n\nNo structured report was produced by the LLM.\n"
        )

    report_path = blueprint_dir / "sources" / "speckit_conversion_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_content + "\n", encoding="utf-8", newline="\n")

    if not files:
        raise SpecificationError(
            "LLM output contained no <file path=\"...\"> blocks; "
            "cannot write Blueprint files. Conversion report written to "
            f"{report_path.relative_to(blueprint_dir)}."
        )

    written: list[str] = []
    for name, content in files.items():
        dest = (target_dir if name in _ROOT_TEMPLATE_NAMES else blueprint_dir) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content + "\n", encoding="utf-8", newline="\n")
        written.append(name)

    return ImportSpecKitResult(
        blueprint=blueprint,
        target=target,
        blueprint_dir=blueprint_dir,
        source=source,
        features_found=tuple(f.name for f in features),
        files_written=tuple(sorted(written)),
        conversion_report=report_path,
        execution_id=result.execution_id,
    )
