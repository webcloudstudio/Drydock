"""Attribute Manifest stories to the source requirements they came from.

Planning decomposes a source into stories but records nothing about which sentence produced which
story, so the link has to be recovered by reading both. This is a closed-set matching problem, not
open decomposition: every candidate story already exists and is named, and the model's only job is
to say which requirement each one answers.

Two callers share it. ``plan`` runs it immediately after saving the Manifest, so lineage is
complete the moment planning finishes. ``refit --relineage`` runs it over a Target that predates
lineage entirely. Both feed the same prompt and the same validation.

A story that matches no requirement is recorded and left unattached rather than treated as an
error. Planning legitimately invents foundational work — scaffolding, configuration, an
application factory — that no sentence in the source asked for, and failing on that would make
the command unusable on exactly the Targets it exists to repair.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from drydock.lineage import Requirement
from drydock.manifest import DrydockManifest
from drydock.prompts import load_prompt

PROMPT_NAME = "lineage_attribute"

_TAG_RE = re.compile(
    r"<(?P<name>attribution|requirement|unattached)\b(?P<attrs>[^>]*?)"
    r"(?:/>|>(?P<body>.*?)</(?P=name)>)",
    re.DOTALL | re.IGNORECASE,
)
_ATTR_RE = re.compile(r"(\w+)\s*=\s*\"([^\"]*)\"")


@dataclass(frozen=True)
class TagBlock:
    name: str
    attrs: Mapping[str, str]
    text: str


@dataclass(frozen=True)
class Attribution:
    """What the model concluded about one source file."""

    requirements: tuple[Requirement, ...]
    unattached: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def parse_tag_blocks(text: str, *, names: frozenset[str]) -> tuple[TagBlock, ...]:
    """Read the tag blocks out of model output, ignoring any prose around them.

    Models preface structured output with commentary often enough that a strict whole-response
    parse is a reliability problem rather than a correctness gain.
    """
    blocks: list[TagBlock] = []
    for match in _TAG_RE.finditer(text):
        name = match.group("name").lower()
        if name not in names:
            continue
        attrs = {
            key.lower(): value.strip() for key, value in _ATTR_RE.findall(match.group("attrs"))
        }
        blocks.append(TagBlock(name=name, attrs=attrs, text=(match.group("body") or "").strip()))
    return tuple(blocks)


def story_ids(manifest: DrydockManifest) -> tuple[str, ...]:
    return tuple(node.block_id for node in manifest.blocks if node.block_type == "story")


def render_story_catalogue(manifest: DrydockManifest) -> str:
    lines: list[str] = []
    for node in manifest.blocks:
        if node.block_type != "story":
            continue
        implements = node.fields.get("implements", "")
        if isinstance(implements, tuple):
            implements = ", ".join(implements)
        summary = node.fields.get("summary", node.name)
        if isinstance(summary, tuple):
            summary = " ".join(summary)
        lines.append(f'  <story id="{node.block_id}" implements="{implements}">{summary}</story>')
    return "\n".join(lines)


def assemble_attribution_prompt(
    body: str, *, rel_path: str, source_text: str, manifest: DrydockManifest
) -> str:
    """Build the attribution job deterministically so it is testable without a process."""
    return (
        f"{body}\n\n"
        "# Attribution job\n\n"
        f'<source name="{rel_path}">\n{source_text.strip()}\n</source>\n\n'
        f"<stories>\n{render_story_catalogue(manifest)}\n</stories>\n"
    )


def parse_attribution_output(text: str) -> tuple[tuple[Requirement, ...], tuple[str, ...]]:
    """Read requirements and their stories out of the model response."""
    requirements: list[Requirement] = []
    unattached: list[str] = []
    for block in parse_tag_blocks(text, names=frozenset({"requirement", "unattached"})):
        if block.name == "unattached":
            story = block.attrs.get("story", "").strip()
            if story:
                unattached.append(story)
            continue
        name = block.attrs.get("name", "").strip()
        if not name:
            continue
        stories = tuple(
            item.strip() for item in block.attrs.get("stories", "").split(",") if item.strip()
        )
        requirements.append(Requirement(name=name, text=block.text, stories=stories))
    return tuple(requirements), tuple(unattached)


def validate_attribution(
    requirements: Sequence[Requirement],
    unattached: Sequence[str],
    *,
    known_stories: Sequence[str],
) -> Attribution:
    """Drop story ids that do not exist, with a warning rather than a failure.

    Attribution is a record of provenance, not an executable contract. A hallucinated id is worth
    reporting and worth discarding; it is not worth losing every correct attribution over.
    """
    known = set(known_stories)
    warnings: list[str] = []
    cleaned: list[Requirement] = []
    for requirement in requirements:
        kept = tuple(story for story in requirement.stories if story in known)
        dropped = tuple(story for story in requirement.stories if story not in known)
        if dropped:
            warnings.append(
                f"{requirement.name}: dropped unknown story id(s) {', '.join(sorted(dropped))}"
            )
        cleaned.append(Requirement(name=requirement.name, text=requirement.text, stories=kept))
    kept_unattached = tuple(story for story in unattached if story in known)
    return Attribution(tuple(cleaned), kept_unattached, tuple(warnings))


def attribute_source(
    rel_path: str,
    source_text: str,
    manifest: DrydockManifest,
    *,
    working_directory: Path,
    runner: Callable[..., object] | None = None,
    log_dir: Path | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    target: str | None = None,
) -> Attribution:
    """Attribute one source file's requirements to existing stories.

    Returns an empty attribution rather than raising when the model fails: an unlinked lineage
    record is a lesser harm than a failed ``plan``.
    """
    if not source_text.strip():
        return Attribution((), ())
    from drydock.llm import run_prompt

    prompt = load_prompt(PROMPT_NAME)
    run = runner if runner is not None else run_prompt
    assembled = assemble_attribution_prompt(
        prompt.body, rel_path=rel_path, source_text=source_text, manifest=manifest
    )
    result = run(
        assembled,
        working_directory,
        llm=llm_provider,
        model=model or prompt.model,
        command_name=PROMPT_NAME,
        parameters={"source": rel_path},
        log_dir=log_dir,
        target=target,
    )
    if not getattr(result, "ok", False) or not str(getattr(result, "text", "")).strip():
        return Attribution((), (), (f"{rel_path}: attribution unavailable",))
    requirements, unattached = parse_attribution_output(str(result.text))
    return validate_attribution(requirements, unattached, known_stories=story_ids(manifest))
