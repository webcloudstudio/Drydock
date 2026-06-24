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
    content = "\n".join(lines)
    role_attr = f' role="{role}"' if role else ""
    path_attr = f' path="{path}"' if path else ""
    text = f'<pblock label="{label}" kind="{kind}"{role_attr}{path_attr}>\n{content}\n</pblock>\n\n'
    return PromptPart(label=label, text=text, kind=kind, role=role, path=path, included=included)


def fenced_markdown_part(
    label: str,
    body: str,
    *,
    kind: str = "file",
    role: str | None = None,
    path: Path | None = None,
) -> PromptPart:
    role_attr = f' role="{role}"' if role else ""
    path_attr = f' path="{path}"' if path else ""
    text = f'<pblock filename="{label}"{role_attr}{path_attr}>\n```markdown\n{body.rstrip()}\n```\n</pblock>\n\n'
    return PromptPart(label=label, text=text, kind=kind, role=role, path=path)


def fenced_block_part(
    label: str,
    body: str,
    *,
    fence: str,
    kind: str = "file",
    role: str | None = None,
    path: Path | None = None,
) -> PromptPart:
    role_attr = f' role="{role}"' if role else ""
    path_attr = f' path="{path}"' if path else ""
    text = f'<pblock filename="{label}"{role_attr}{path_attr}>\n```{fence}\n{body.rstrip()}\n```\n</pblock>\n\n'
    return PromptPart(label=label, text=text, kind=kind, role=role, path=path)


def fenced_text_part(
    label: str,
    body: str,
    *,
    kind: str = "section",
    role: str | None = None,
    path: Path | None = None,
) -> PromptPart:
    role_attr = f' role="{role}"' if role else ""
    path_attr = f' path="{path}"' if path else ""
    text = f'<pblock label="{label}"{role_attr}{path_attr}>\n```text\n{body.rstrip()}\n```\n</pblock>\n\n'
    return PromptPart(label=label, text=text, kind=kind, role=role, path=path)


def contextual_markdown_parts(
    label: str,
    body: str,
    *,
    filename: str,
    role: str | None = None,
    path: Path | None = None,
) -> tuple[PromptPart, ...]:
    metadata = prompt_header_for_path(path) if path is not None else prompt_header_for_file(filename)
    effective_role = role or (metadata.role if metadata is not None else None)
    role_attr = f' role="{effective_role}"' if effective_role else ""
    path_attr = f' path="{path}"' if path else ""
    guidance_attr = ""
    if metadata is not None and metadata.prompt_text.strip():
        guidance_attr = f' guidance="{metadata.prompt_text.strip()}"'
    text = (
        f'<pblock filename="{label}"{role_attr}{path_attr}{guidance_attr}>\n'
        f"```markdown\n{body.rstrip()}\n```\n"
        f"</pblock>\n\n"
    )
    return (PromptPart(label=label, text=text, kind="file", role=effective_role, path=path),)


_SYSTEM_PREAMBLE = """\
# System Instructions

This prompt is divided into three sections:

1. **System Instructions** (this section) — structural orientation only. Do not treat this
   section as task input.

2. **Input Context** — begins with the heading `# Input Context`. All blocks are wrapped in
   `<pblock>` tags. Two block types:
   - File blocks: `<pblock filename="<name>" role="<role>" guidance="...">` — optional
     `guidance` attribute carries context-specific instructions; content is in a fenced block.
   - Metadata/section blocks: `<pblock label="<label>" kind="<kind>">` — job parameters,
     rules, instructions, or group headers.

3. **Agent Task** — begins with the heading `# Agent Task`. Defines your persona, constraints,
   and required outputs. Read all input context before acting on this section.

"""


def system_preamble_part() -> PromptPart:
    return PromptPart(label="System Instructions", text=_SYSTEM_PREAMBLE, kind="system")


def section_heading_part(heading: str) -> PromptPart:
    return PromptPart(label=heading, text=f"\n{heading}\n\n", kind="section-heading")


def contextual_fenced_parts(
    label: str,
    body: str,
    *,
    filename: str,
    fence: str,
    role: str | None = None,
    path: Path | None = None,
) -> tuple[PromptPart, ...]:
    metadata = prompt_header_for_path(path) if path is not None else prompt_header_for_file(filename)
    effective_role = role or (metadata.role if metadata is not None else None)
    role_attr = f' role="{effective_role}"' if effective_role else ""
    path_attr = f' path="{path}"' if path else ""
    guidance_attr = ""
    if metadata is not None and metadata.prompt_text.strip():
        guidance_attr = f' guidance="{metadata.prompt_text.strip()}"'
    text = (
        f'<pblock filename="{label}"{role_attr}{path_attr}{guidance_attr}>\n'
        f"```{fence}\n{body.rstrip()}\n```\n"
        f"</pblock>\n\n"
    )
    return (PromptPart(label=label, text=text, kind="file", role=effective_role, path=path),)
