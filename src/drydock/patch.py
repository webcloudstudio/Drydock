"""Parse and apply the unified diffs ``drydock diagnose`` proposes against governed files.

A diagnosis proposes edits to files the operator owns. Prose describing an edit is not something
an operator can accept with one keystroke, and free-form rewriting of a file a human wrote is not
something they should be asked to accept at all. A unified diff is the middle: readable before
approval, exact on application, and verifiable before either.

Verification is the point of this module. Every diff is applied to an in-memory copy first, and
one that does not apply is rejected before the operator ever sees it. Approving a change that then
fails to land is worse than never offering it.

Python ships a diff generator and no applier, so the applier is here. It is deliberately small:
context must match exactly, and only the hunk's position may drift. Fuzzy matching would let a
diff land somewhere it was never meant to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

#: ``#### 2. Require every criterion to name its assertion``
_HEADING_RE = re.compile(r"(?m)^####\s+(?P<index>\d+)\.\s*(?P<summary>.+?)\s*$")
_FILE_RE = re.compile(r"(?mi)^\s*(?:\*\*)?File:(?:\*\*)?\s*`?(?P<file>[^`\n]+?)`?\s*$")
_WHY_RE = re.compile(r"(?mi)^\s*(?:\*\*)?Why:(?:\*\*)?\s*(?P<why>.+?)\s*$")
_DIFF_FENCE_RE = re.compile(r"(?ms)^```(?:diff|patch)?\s*\n(?P<body>.*?)^```\s*$")
_HUNK_RE = re.compile(
    r"(?m)^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s*@@"
)

#: How far a hunk may slide from its stated line number before it is rejected. A governed file
#: is shown to the model with line numbers, so a correct diff lands at zero offset; the window
#: absorbs a trailing-newline or heading-numbering disagreement, not a misplaced edit.
MAX_OFFSET = 40


@dataclass(frozen=True)
class Hunk:
    """One ``@@`` block: where it claims to start, and the lines it expects and produces."""

    old_start: int
    #: Lines the hunk expects to find, in order — its context and its deletions.
    before: tuple[str, ...]
    #: Lines it leaves behind — its context and its additions.
    after: tuple[str, ...]


@dataclass(frozen=True)
class Amendment:
    """One proposed, reviewable edit to one governed file."""

    summary: str
    file: str
    why: str
    diff: str
    hunks: tuple[Hunk, ...] = ()
    #: Why this amendment was not offered, when it was not. Empty on an applicable one.
    rejection: str = ""

    def rejected(self, reason: str) -> Amendment:
        """This amendment, marked unapplicable, so the report can say so rather than drop it."""
        return replace(self, rejection=reason)

    def apply_to(self, text: str) -> str | None:
        """The file's contents with this amendment applied, or ``None`` when it does not apply.

        Never partially applies: a diff whose second hunk fails leaves the caller with nothing,
        because half an amendment is a corruption, not a smaller change.
        """
        if not self.hunks:
            return None
        lines = text.splitlines()
        offset = 0
        for hunk in self.hunks:
            found = _locate(lines, hunk, offset)
            if found is None:
                return None
            lines[found : found + len(hunk.before)] = list(hunk.after)
            offset += len(hunk.after) - len(hunk.before)
        trailing = "\n" if text.endswith("\n") or not text else ""
        return "\n".join(lines) + trailing


def parse_amendments(section: str) -> tuple[Amendment, ...]:
    """Every amendment the model proposed, in order, whether or not each one applies.

    Parsing is forgiving about the prose around an amendment and strict about its parts: an
    entry without a file, a reason, and a fenced diff is not an amendment and is skipped. A
    malformed proposal is silently absent rather than half-offered.
    """
    if not section.strip():
        return ()
    found: list[Amendment] = []
    headings = list(_HEADING_RE.finditer(section))
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(section)
        block = section[heading.end() : end]
        file_match = _FILE_RE.search(block)
        diff_match = _DIFF_FENCE_RE.search(block)
        if file_match is None or diff_match is None:
            continue
        why_match = _WHY_RE.search(block)
        diff = diff_match.group("body")
        found.append(
            Amendment(
                summary=heading.group("summary"),
                file=file_match.group("file").strip().lstrip("ab/").lstrip("/"),
                why=why_match.group("why").strip() if why_match else "",
                diff=diff,
                hunks=parse_hunks(diff),
            )
        )
    return tuple(found)


def parse_hunks(diff: str) -> tuple[Hunk, ...]:
    """The ``@@`` blocks of a unified diff, or ``()`` when it has none that parse.

    A line that is neither context, addition, nor deletion ends the hunk. Providers sometimes
    append commentary inside the fence; stopping at the first unrecognised line keeps that
    commentary out of the file instead of inserting it.
    """
    hunks: list[Hunk] = []
    matches = list(_HUNK_RE.finditer(diff))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(diff)
        body = diff[match.end() : end].splitlines()
        if body and not body[0].strip():
            body = body[1:]
        before: list[str] = []
        after: list[str] = []
        for line in body:
            if line.startswith("+"):
                after.append(line[1:])
            elif line.startswith("-"):
                before.append(line[1:])
            elif line.startswith(" "):
                before.append(line[1:])
                after.append(line[1:])
            elif line == "":
                # An emptied context line: providers strip the leading space on a blank line.
                before.append("")
                after.append("")
            elif line.startswith("\\"):
                continue  # "\ No newline at end of file"
            else:
                break
        if not before and not after:
            continue
        hunks.append(
            Hunk(
                old_start=int(match.group("old_start")),
                before=tuple(before),
                after=tuple(after),
            )
        )
    return tuple(hunks)


def _locate(lines: list[str], hunk: Hunk, offset: int) -> int | None:
    """The index where *hunk* matches, searching outward from its stated position.

    A pure-insertion hunk has no context to match, so it can only be trusted at the line it
    names; everything else must find its context exactly.
    """
    expected = max(0, hunk.old_start - 1 + offset)
    if not hunk.before:
        return expected if expected <= len(lines) else None
    for distance in range(MAX_OFFSET + 1):
        for candidate in {expected - distance, expected + distance}:
            if candidate < 0 or candidate + len(hunk.before) > len(lines):
                continue
            if lines[candidate : candidate + len(hunk.before)] == list(hunk.before):
                return candidate
    return None
