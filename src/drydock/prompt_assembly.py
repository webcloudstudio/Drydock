"""Shared prompt assembly parts, rendering, and prompt-cost estimation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drydock.prompt_headers import prompt_header_for_file, prompt_header_for_path


def estimate_tokens(byte_count: int) -> int:
    """Return Drydock's coarse token estimate: ``ceil(bytes / 4)``."""
    return (byte_count + 3) // 4


@dataclass(frozen=True)
class PromptPart:
    label: str
    text: str
    kind: str = "section"
    role: str | None = None
    path: Path | None = None
    included: bool = True

    @property
    def byte_count(self) -> int:
        return len(self.text.encode("utf-8"))

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.byte_count)

    def record(self, *, order: int) -> dict[str, object]:
        return {
            "order": order,
            "label": self.label,
            "kind": self.kind,
            "role": self.role,
            "path": str(self.path) if self.path is not None else None,
            "bytes": self.byte_count,
            "estimated_tokens": self.estimated_tokens,
            "included": self.included,
        }


@dataclass(frozen=True)
class PromptAssembly:
    parts: tuple[PromptPart, ...]

    @property
    def rendered_text(self) -> str:
        return "".join(part.text for part in self.parts if part.included)

    @property
    def total_bytes(self) -> int:
        return sum(part.byte_count for part in self.parts if part.included)

    @property
    def total_tokens_estimate(self) -> int:
        return sum(part.estimated_tokens for part in self.parts if part.included)

    def records(self) -> list[dict[str, object]]:
        return [part.record(order=index + 1) for index, part in enumerate(self.parts) if part.included]

    @classmethod
    def single_prompt(cls, text: str, *, label: str = "Prompt") -> PromptAssembly:
        return cls(parts=(PromptPart(label=label, kind="prompt", text=text),))


def part(
    label: str,
    text: str,
    *,
    kind: str = "section",
    role: str | None = None,
    path: Path | None = None,
    included: bool = True,
) -> PromptPart:
    return PromptPart(
        label=label,
        text=text,
        kind=kind,
        role=role,
        path=path,
        included=included,
    )


def lines_part(
    label: str,
    lines: list[str],
    *,
    kind: str = "section",
    role: str | None = None,
    path: Path | None = None,
    included: bool = True,
) -> PromptPart:
    return part(
        label,
        "\n".join(lines),
        kind=kind,
        role=role,
        path=path,
        included=included,
    )


def fenced_markdown_part(
    label: str,
    heading: str,
    body: str,
    *,
    kind: str = "file",
    role: str | None = None,
    path: Path | None = None,
) -> PromptPart:
    return part(
        label,
        "\n".join([heading, "", "```markdown", body.rstrip("\n"), "```", ""]),
        kind=kind,
        role=role,
        path=path,
    )


def fenced_block_part(
    label: str,
    heading: str,
    body: str,
    *,
    fence: str,
    kind: str = "file",
    role: str | None = None,
    path: Path | None = None,
) -> PromptPart:
    return part(
        label,
        "\n".join([heading, "", f"```{fence}", body.rstrip("\n"), "```", ""]),
        kind=kind,
        role=role,
        path=path,
    )


def fenced_text_part(
    label: str,
    heading: str,
    body: str,
    *,
    kind: str = "section",
    role: str | None = None,
    path: Path | None = None,
) -> PromptPart:
    return part(
        label,
        "\n".join([heading, "", "```text", body.rstrip("\n"), "```", ""]),
        kind=kind,
        role=role,
        path=path,
    )


def contextual_markdown_parts(
    label: str,
    heading: str,
    body: str,
    *,
    filename: str,
    role: str | None = None,
    path: Path | None = None,
) -> tuple[PromptPart, ...]:
    metadata = prompt_header_for_path(path) if path is not None else prompt_header_for_file(filename)
    parts: list[PromptPart] = []
    if metadata is not None:
        parts.append(
            part(
                f"{label} instructions",
                "\n".join(
                    [
                        f"## {metadata.label}",
                        metadata.prompt_text.rstrip("\n"),
                        "---",
                        "",
                    ]
                ),
                role="prompt instructions",
                path=path,
            )
        )
    parts.append(
        part(
            label,
            "\n".join(
                [
                    heading,
                    "",
                    "```markdown",
                    body.rstrip("\n"),
                    "```",
                    "---",
                    "",
                ]
            ),
            kind="file",
            role=role or (metadata.role if metadata is not None else None),
            path=path,
        )
    )
    return tuple(parts)


_SYSTEM_PREAMBLE = """\
# System Instructions

This prompt is divided into three sections:

1. **System Instructions** (this section) — structural orientation only. Do not treat this
   section as task input.

2. **Input Context** — begins with the heading `# Input Context`. Contains job metadata,
   rules, guidance, and source files. Two heading levels are used:
   - `##` — a metadata block, instruction block, or group header (e.g. job parameters,
     per-file guidance, section labels)
   - `###` — an individual source file in the format `### <filename> (<role>)`

3. **Agent Task** — begins with the heading `# Agent Task`. Defines your persona, constraints,
   and required outputs. Read all input context before acting on this section.

"""


def system_preamble_part() -> PromptPart:
    return PromptPart(label="System Instructions", text=_SYSTEM_PREAMBLE, kind="system")


def section_heading_part(heading: str) -> PromptPart:
    return PromptPart(label=heading, text=f"\n{heading}\n\n", kind="section-heading")


def contextual_fenced_parts(
    label: str,
    heading: str,
    body: str,
    *,
    filename: str,
    fence: str,
    role: str | None = None,
    path: Path | None = None,
) -> tuple[PromptPart, ...]:
    metadata = prompt_header_for_path(path) if path is not None else prompt_header_for_file(filename)
    parts: list[PromptPart] = []
    if metadata is not None:
        parts.append(
            part(
                f"{label} instructions",
                "\n".join(
                    [
                        f"## {metadata.label}",
                        metadata.prompt_text.rstrip("\n"),
                        "---",
                        "",
                    ]
                ),
                role="prompt instructions",
                path=path,
            )
        )
    parts.append(
        part(
            label,
            "\n".join(
                [
                    heading,
                    "",
                    f"```{fence}",
                    body.rstrip("\n"),
                    "```",
                    "---",
                    "",
                ]
            ),
            kind="file",
            role=role or (metadata.role if metadata is not None else None),
            path=path,
        )
    )
    return tuple(parts)
