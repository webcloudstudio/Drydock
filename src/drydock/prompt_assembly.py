"""Shared prompt assembly parts, rendering, and prompt-cost estimation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
