"""Terminal rendering for ``drydock diagnose``.

The report files are the record; this is what the operator reads while the command runs. Each
section is titled by a rule, prose is wrapped to the terminal, the facts are separated from the
``Not a defect:`` wreckage, and an amendment shows the diff it would apply before the operator is
asked to apply it.

Rendering is pure: a :class:`Style` carries colour and width, so tests render at a fixed width
with no escapes. Glyphs are left to :mod:`drydock.console`, whose stream wrapper demotes them on a
terminal that cannot draw them.
"""

from __future__ import annotations

import re
import shutil
import sys
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from drydock import console
from drydock.diagnose_evidence import Bundle
from drydock.diagnose_ladder import LadderRow, render_ladder
from drydock.patch import Amendment

MAX_WIDTH = 100
MIN_WIDTH = 40
#: A diff longer than this is cut in the prompt; the report always carries it whole.
MAX_DIFF_LINES = 60
INDENT = "  "

BOLD = "1"
DIM = "2"
RED = "31"
GREEN = "32"
YELLOW = "33"
CYAN = "36"

NOT_A_DEFECT = "Not a defect:"

_CODE_RE = re.compile(r"`([^`\n]+)`")
_BULLET_RE = re.compile(r"^(?P<marker>[-*•]|\d+[.)])\s+(?P<body>.*)$")
_NOT_A_DEFECT_RE = re.compile(r"^[-*•]\s+" + re.escape(NOT_A_DEFECT) + r"\s*(?P<body>.*)$")
_LADDER_MARKS = (("[FAIL]", (RED, BOLD)), ("[OK]", (GREEN,)))
_NBSP = "\u00a0"


@dataclass(frozen=True)
class Style:
    """How output is painted: whether ANSI colour is allowed, and the wrap width."""

    color: bool = False
    width: int = 80

    @classmethod
    def detect(cls, stream: TextIO | None = None) -> Style:
        """The style ``stream`` supports. Captured output gets no colour."""
        stream = stream if stream is not None else sys.stdout
        columns = shutil.get_terminal_size((MAX_WIDTH, 24)).columns
        return cls(
            color=console.color_enabled(stream),
            width=max(MIN_WIDTH, min(columns, MAX_WIDTH)),
        )

    def paint(self, text: str, *codes: str) -> str:
        if not self.color or not codes or not text:
            return text
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

    def code(self, text: str) -> str:
        """Paint inline `code` spans. Plain output keeps the backticks, which carry the meaning."""
        if not self.color:
            return text
        return _CODE_RE.sub(lambda match: self.paint(match.group(1), CYAN), text)

    def rule(self, title: str, *, char: str = "─", codes: Sequence[str] = (BOLD,)) -> str:
        """``── Title ─────`` across the width."""
        head = f"{char * 2} {title} "
        fill = char * max(2, self.width - console.display_width(head))
        return f"{self.paint(char * 2, DIM)} {self.paint(title, *codes)} {self.paint(fill, DIM)}"

    def wrap(self, text: str, *, first: str = INDENT, rest: str | None = None) -> list[str]:
        """Wrap ``text`` to the width. A `code` span is never split across lines."""
        protected = _CODE_RE.sub(lambda match: match.group(0).replace(" ", _NBSP), text)
        lines = textwrap.wrap(
            protected,
            width=self.width,
            initial_indent=first,
            subsequent_indent=first if rest is None else rest,
            break_long_words=False,
            break_on_hyphens=False,
        )
        return [line.replace(_NBSP, " ") for line in lines] or [first.rstrip()]


def render_banner(target: str, headline: str, failed: bool, style: Style) -> str:
    """The masthead: which Target, and the one-line verdict."""
    mark = style.paint("✗", RED, BOLD) if failed else style.paint("✓", GREEN, BOLD)
    verdict = style.paint(headline, RED, BOLD) if failed else style.paint(headline, BOLD)
    return "\n".join([
        style.rule(f"DRYDOCK DIAGNOSE · {target}", char="═"),
        f"{INDENT}{mark} {verdict}",
    ])


def render_ladder_lines(rows: Sequence[LadderRow], style: Style) -> str:
    """The deterministic ladder, with each state's mark coloured."""
    text = render_ladder(rows)
    if not style.color:
        return text
    painted: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("[--]"):
            line = style.paint(line, DIM)
        for mark, codes in _LADDER_MARKS:
            if line.lstrip().startswith(mark):
                line = line.replace(mark, style.paint(mark, *codes), 1)
                break
        painted.append(line)
    return "\n".join(painted)


def render_findings(bundle: Bundle, diagnosis, style: Style) -> str:
    """The diagnosis as the command's own output: enough to act on without opening the report."""
    sections = diagnosis.sections
    blocks = [
        _section(style, "Root Cause", _prose(style, sections.get("Root Cause", ""))),
        _section(style, "Details", _details(style, sections.get("Details", ""))),
    ]

    feedback = sections.get("Commander Feedback Requested", "").strip()
    if _is_none(feedback):
        blocks.append(
            _section(style, "Commander Feedback Requested", [INDENT + style.paint("None.", DIM)])
        )
    else:
        blocks.append(
            _section(
                style,
                "Commander Feedback Requested",
                _prose(style, feedback),
                codes=(YELLOW, BOLD),
            )
        )

    if diagnosis.amendments:
        lines: list[str] = []
        for index, amendment in enumerate(diagnosis.amendments, start=1):
            number = f"{index}. "
            lines += [
                style.code(line)
                for line in style.wrap(
                    amendment.summary,
                    first=INDENT + number,
                    rest=INDENT + " " * len(number),
                )
            ]
            lines.append(
                INDENT
                + " " * len(number)
                + style.paint(f"{amendment.file}  {_diff_size(amendment)}", DIM)
            )
        blocks.append(_section(style, "Repair Proposal", lines))
    if diagnosis.unapplicable:
        lines = [INDENT + style.paint("Proposed but not verified against the current files:", DIM)]
        for item in diagnosis.unapplicable:
            lines += style.wrap(
                f"{item.summary} ({item.file}) — {item.rejection}",
                first=INDENT + "• ",
                rest=INDENT + "  ",
            )
        blocks.append(_section(style, "Not Offered", lines, codes=(YELLOW, BOLD)))
    if bundle.missing:
        lines = [INDENT + style.paint("Conclusions were reached without:", DIM)]
        lines += style.wrap(", ".join(bundle.missing))
        blocks.append(_section(style, "Missing Evidence", lines))
    if not diagnosis.ok:
        blocks.append(
            _section(
                style,
                "Contract Violations",
                [INDENT + f"• {problem}" for problem in diagnosis.problems],
                codes=(RED, BOLD),
            )
        )
        raw = diagnosis.raw.strip() or "(empty)"
        blocks.append(_section(style, "Raw Model Answer", raw.splitlines()))
    return "\n\n".join(blocks)


def render_report_paths(markdown: Path, page: Path, style: Style) -> str:
    return "\n".join([
        style.rule("Report"),
        f"{INDENT}{style.paint('Markdown', DIM)}  {markdown}",
        f"{INDENT}{style.paint('Page    ', DIM)}  {page}",
    ])


def render_amendment(index: int, total: int, amendment: Amendment, style: Style) -> str:
    """One amendment as a card ending in the question. The operator sees the diff first."""
    lines = ["", style.rule(f"Amendment {index} of {total}", codes=(CYAN, BOLD))]
    lines += [style.paint(line, BOLD) for line in style.wrap(amendment.summary)]
    lines.append(f"{INDENT}{style.paint('File', DIM)}  {amendment.file}   {_diff_size(amendment)}")
    if amendment.why:
        wrapped = style.wrap(amendment.why, first=INDENT + "Why   ", rest=INDENT + " " * 6)
        lines += [style.code(line) for line in wrapped]
    lines.append("")
    lines += render_diff(amendment.diff, style)
    lines.append("")
    lines.append(f"{INDENT}Apply? [y/N] ")
    return "\n".join(lines)


def render_diff(diff: str, style: Style, *, limit: int = MAX_DIFF_LINES) -> list[str]:
    """The unified diff, coloured by line kind, cut at ``limit`` lines."""
    rows = diff.strip("\n").splitlines()
    shown: list[str] = []
    for row in rows[:limit]:
        row = row.rstrip()
        if row.startswith(("+++", "---")):
            codes: tuple[str, ...] = (DIM,)
        elif row.startswith("@@"):
            codes = (CYAN,)
        elif row.startswith("+"):
            codes = (GREEN,)
        elif row.startswith("-"):
            codes = (RED,)
        else:
            codes = (DIM,)
        shown.append((INDENT + "  " + style.paint(row, *codes)).rstrip())
    if len(rows) > limit:
        shown.append(
            INDENT + "  " + style.paint(f"… {len(rows) - limit} more lines in the report", DIM)
        )
    return shown


def _diff_size(amendment: Amendment) -> str:
    rows = amendment.diff.splitlines()
    added = sum(1 for row in rows if row.startswith("+") and not row.startswith("+++"))
    removed = sum(1 for row in rows if row.startswith("-") and not row.startswith("---"))
    return f"+{added} -{removed}"


def _section(
    style: Style, title: str, lines: Sequence[str], *, codes: Sequence[str] = (BOLD,)
) -> str:
    body = list(lines) or [INDENT + style.paint("Not returned by the diagnosis.", DIM)]
    return "\n".join([style.rule(title, codes=codes), *body])


def _details(style: Style, text: str) -> list[str]:
    """The evidence bullets, then the ``Not a defect:`` bullets under their own dimmed heading."""
    facts: list[str] = []
    wreckage: list[str] = []
    for line in text.strip().splitlines():
        match = _NOT_A_DEFECT_RE.match(line.strip())
        if match:
            wreckage.append(match.group("body"))
        else:
            facts.append(line)
    lines = _prose(style, "\n".join(facts))
    if wreckage:
        if lines:
            lines.append("")
        lines.append(INDENT + style.paint("Not defects", DIM, BOLD))
        for body in wreckage:
            lines += [
                style.paint(line, DIM)
                for line in style.wrap(body, first=INDENT + "· ", rest=INDENT + "  ")
            ]
    return lines


def _prose(style: Style, text: str) -> list[str]:
    """Markdown-ish prose wrapped to the width: paragraphs, bullets, and numbered items.

    A line that follows a bullet without a blank line continues that bullet, which is how the
    model soft-wraps a long item.
    """
    items: list[tuple[str, list[str]]] = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            if items and items[-1] != ("", []):
                items.append(("", []))
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            marker = "•" if bullet.group("marker") in {"-", "*", "•"} else bullet.group("marker")
            items.append((marker, [bullet.group("body")]))
        elif items and items[-1][1]:
            items[-1][1].append(line)
        else:
            items.append((" ", [line]))
    lines: list[str] = []
    for marker, words in items:
        if not words:
            lines.append("")
            continue
        body = " ".join(words)
        if marker == " ":
            wrapped = style.wrap(body)
        else:
            wrapped = style.wrap(
                body, first=f"{INDENT}{marker} ", rest=INDENT + " " * (len(marker) + 1)
            )
        lines += [style.code(line) for line in wrapped]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _is_none(text: str) -> bool:
    return text.strip().rstrip(".").lower() in {"", "none"}
