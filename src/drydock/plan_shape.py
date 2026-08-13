"""Shape conformance is a checker, not an instruction.

The planning prompt used to end by asking the model to verify its own delimiters and block
completeness. Absolute guardrails against shape failure come instead from a deterministic
post-checker over a **declared output contract** — the Hull Check of ``ideas/PROMPT_HARDENING.md``
— because that verification is free and reliable in code and unreliable in a prompt.

Prompt hardening and the plan restructure are complementary, not alternatives. Staging is what
makes a Second Pass affordable: re-emitting a two-file stage costs almost nothing, while
re-emitting a thirty-file monolith re-sends the entire input. Hardening addresses shape failure
only.

This module reports; it never repairs. A caller decides whether a defect set warrants a Second
Pass, an error record, or a refusal.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from drydock.artifact_blocks import pair_artifact_delimiters

# Delimiter grammar — including the ``AC`` namespace reservation that keeps the nested
# ``=== AC <id> ===`` proof blocks out of the envelope — lives in ``artifact_blocks`` and is
# reached only through ``pair_artifact_delimiters``. A second copy here is how this module came
# to read one boundary grammar while the parser read two.
_TYPED_HEADING_RE = re.compile(r"^#\s+[A-Za-z][A-Za-z0-9_-]*\s*:\s*.+?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ShapeDefect:
    """One violation of the declared output contract."""

    code: str
    artifact: str
    message: str

    def rendered(self) -> str:
        where = f"{self.artifact}: " if self.artifact else ""
        return f"{where}{self.message}"


@dataclass(frozen=True)
class OutputContract:
    """What a stage of the pipeline declares it will emit.

    A stage states its contract before it runs; the checker measures the response against it.
    Declaring the contract is what makes the check deterministic — without it, "complete" is a
    judgment call and lands back in the prompt.
    """

    #: Artifacts that must be present, by exact block name.
    required: tuple[str, ...] = ()
    #: The artifact that must appear first, when the contract fixes a leading artifact.
    #: A declaration emitted first is what makes a short response resumable: the count of
    #: what should exist survives even when most bodies do not.
    leading: str = ""
    #: The artifact that must appear last, when the contract fixes a terminal artifact.
    terminal: str = ""
    #: Blocks exempt from the typed-heading requirement.
    untyped: frozenset[str] = field(default_factory=frozenset)
    #: Whether every non-exempt Markdown artifact must carry a typed ``# Kind: Name`` heading.
    require_typed_headings: bool = True
    #: Whether any non-whitespace text outside the blocks is a violation.
    forbid_outside_text: bool = True


def has_typed_heading(body: str) -> bool:
    """Whether a Markdown artifact carries a typed ``# Kind: Name`` heading."""
    return bool(_TYPED_HEADING_RE.search(body))


def check_delimiters(text: str) -> tuple[ShapeDefect, ...]:
    """Verify every artifact appears in exactly one paired open/END delimiter set.

    Pairing is positional, so the check reads the invariant ``=== END ARTIFACT ===`` close and the
    named ``=== END <name> ===`` close alike. Counting names would report every invariant-form
    artifact as unclosed and every close as an orphan, because that close carries no name.
    """
    defects: list[ShapeDefect] = []
    pairing = pair_artifact_delimiters(text)
    opened = pairing.opened

    for name in opened:
        if opened.count(name) > 1:
            defects.append(ShapeDefect("duplicate-open", name, "opened more than once"))
            break
    for name in dict.fromkeys(pairing.unclosed):
        defects.append(ShapeDefect("unclosed", name, "opened with no matching `=== END` delimiter"))
    for name in dict.fromkeys(pairing.orphan_closes):
        defects.append(ShapeDefect("orphan-end", name, "closed with no matching opening delimiter"))
    return tuple(defects)


def check_contract(
    text: str,
    blocks: dict[str, str],
    contract: OutputContract,
) -> tuple[ShapeDefect, ...]:
    """Measure a parsed response against its declared output contract."""
    defects: list[ShapeDefect] = list(check_delimiters(text))

    for name in contract.required:
        if name not in blocks:
            defects.append(ShapeDefect("missing-artifact", name, "required artifact not emitted"))

    if contract.leading and blocks:
        first = tuple(blocks)[0]
        if contract.leading in blocks and first != contract.leading:
            defects.append(
                ShapeDefect(
                    "leading-artifact",
                    contract.leading,
                    f"must be the first artifact; found {first!r} first",
                )
            )

    if contract.terminal and blocks:
        last = tuple(blocks)[-1]
        if contract.terminal in blocks and last != contract.terminal:
            defects.append(
                ShapeDefect(
                    "terminal-artifact",
                    contract.terminal,
                    f"must be the final artifact; found {last!r} last",
                )
            )

    for name, body in blocks.items():
        if not body.strip():
            defects.append(ShapeDefect("empty-artifact", name, "artifact body is empty"))
            continue
        if (
            contract.require_typed_headings
            and name.lower().endswith(".md")
            and name not in contract.untyped
            and not _TYPED_HEADING_RE.search(body)
        ):
            defects.append(
                ShapeDefect(
                    "untyped-heading",
                    name,
                    "does not carry a typed `# Kind: Name` heading",
                )
            )
    return tuple(defects)


def render_defects(defects: Sequence[ShapeDefect]) -> str:
    return "\n  ".join(defect.rendered() for defect in defects)


def second_pass_instruction(defects: Sequence[ShapeDefect]) -> str:
    """Render the bounded correction a Second Pass re-emits, given a shape failure.

    A Second Pass re-emits only the named artifacts. That is what keeps it affordable — and what
    makes shape conformance worth checking in code rather than asking the model to self-audit.
    """
    artifacts = sorted({defect.artifact for defect in defects if defect.artifact})
    lines = [
        "The previous response violated the declared output contract:",
        "  " + render_defects(defects),
        "",
    ]
    if artifacts:
        lines.append(
            "Re-emit only these artifacts, each in a matching open/END delimiter pair, with "
            "nothing outside the blocks: " + ", ".join(artifacts)
        )
    else:
        lines.append("Re-emit the response with nothing outside the delimited artifact blocks.")
    return "\n".join(lines)
