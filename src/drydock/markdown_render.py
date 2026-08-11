"""Deterministic Markdown-to-HTML rendering for generated reports.

Drydock writes its artifacts as Markdown and publishes them as browsable HTML, so a reader
who opens a document from a report sees the document, not its source. The subset rendered
here is the subset Drydock authors: headings, fenced code, GitHub-style tables, lists,
block quotes, rules, and inline emphasis, code, and links.

The renderer takes no dependency and produces the same HTML for the same input on every
machine, so a published report stays byte-reproducible.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator, Sequence

__all__ = ["render_markdown"]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^`]*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^ {0,3}>\s?(.*)$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")

#: Drydock writes typed artifacts as unwrapped ``Field: value`` lines with no blank line between
#: them. CommonMark folds those into one paragraph, which destroys the record. A field line
#: therefore starts a new visual line, while ordinary wrapped prose still reflows as a paragraph.
_FIELD = re.compile(r"^[A-Z][A-Za-z0-9 /_-]{0,30}:\s+\S")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.DOTALL)
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*]+?)(?<=\S)\*(?![*\w])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_SENTINEL = "\x00"
_BREAK = "\x00br\x00"


def _inline(text: str) -> str:
    """Render inline markup. Code spans are extracted first so they stay literal."""
    spans: list[str] = []

    def stash(match: re.Match[str]) -> str:
        spans.append(html.escape(match.group(2).strip()))
        return f"{_SENTINEL}{len(spans) - 1}{_SENTINEL}"

    staged = _CODE_SPAN.sub(stash, text)
    escaped = html.escape(staged)
    escaped = _LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', escaped
    )
    escaped = _BOLD.sub(lambda m: f"<strong>{m.group(2)}</strong>", escaped)
    escaped = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", escaped)
    escaped = _STRIKE.sub(lambda m: f"<del>{m.group(1)}</del>", escaped)
    for index, span in enumerate(spans):
        escaped = escaped.replace(f"{_SENTINEL}{index}{_SENTINEL}", f"<code>{span}</code>")
    return escaped


def _cells(row: str) -> list[str]:
    stripped = row.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_header(lines: Sequence[str], index: int) -> bool:
    return (
        "|" in lines[index]
        and index + 1 < len(lines)
        and "|" in lines[index + 1]
        and bool(_TABLE_DIVIDER.match(lines[index + 1]))
    )


def _render_table(lines: Sequence[str], start: int) -> tuple[str, int]:
    headers = _cells(lines[start])
    index = start + 2
    rows: list[list[str]] = []
    while index < len(lines) and lines[index].strip() and "|" in lines[index]:
        rows.append(_cells(lines[index]))
        index += 1
    head = "".join(f"<th>{_inline(cell)}</th>" for cell in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    return f'<div class="scroll">{table}</div>', index


def _list_indent(line: str) -> int:
    match = _BULLET.match(line) or _ORDERED.match(line)
    return len(match.group(1)) if match else 0


def _render_list(lines: Sequence[str], start: int, indent: int) -> tuple[str, int]:
    """Render one list level; deeper indentation recurses into a nested list."""
    ordered = bool(_ORDERED.match(lines[start]))
    items: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        match = _ORDERED.match(line) if ordered else _BULLET.match(line)
        if not match or len(match.group(1)) != indent:
            other = _BULLET.match(line) or _ORDERED.match(line)
            if other and len(other.group(1)) > indent and items:
                nested, index = _render_list(lines, index, len(other.group(1)))
                items[-1] += nested
                continue
            break
        items.append(_inline(match.groups()[-1]))
        index += 1
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{item}</li>" for item in items)
    return f"<{tag}>{body}</{tag}>", index


def _blocks(lines: Sequence[str]) -> Iterator[str]:
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            index += 1
            body: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith(marker):
                body.append(lines[index])
                index += 1
            index += 1  # closing fence, or the end of the document
            yield f"<pre><code>{html.escape(chr(10).join(body))}</code></pre>"
            continue

        if _RULE.match(line):
            index += 1
            yield "<hr>"
            continue

        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            index += 1
            yield f"<h{level}>{_inline(heading.group(2))}</h{level}>"
            continue

        if _is_table_header(lines, index):
            table, index = _render_table(lines, index)
            yield table
            continue

        if _BULLET.match(line) or _ORDERED.match(line):
            rendered, index = _render_list(lines, index, _list_indent(line))
            yield rendered
            continue

        if _QUOTE.match(line):
            quoted: list[str] = []
            while index < len(lines) and (match := _QUOTE.match(lines[index])):
                quoted.append(match.group(1))
                index += 1
            yield "<blockquote>" + "".join(_blocks(quoted)) + "</blockquote>"
            continue

        paragraph: list[str] = []
        while index < len(lines) and lines[index].strip():
            candidate = lines[index]
            if (
                _HEADING.match(candidate)
                or _RULE.match(candidate)
                or _FENCE.match(candidate)
                or _QUOTE.match(candidate)
                or _BULLET.match(candidate)
                or _ORDERED.match(candidate)
                or _is_table_header(lines, index)
            ):
                break
            paragraph.append(candidate.strip())
            index += 1
        if paragraph:
            # The break is marked, not written: _inline escapes its input, so real markup can
            # only be substituted in afterwards.
            joined = paragraph[0]
            for line in paragraph[1:]:
                joined += (_BREAK if _FIELD.match(line) else " ") + line
            yield f"<p>{_inline(joined).replace(_BREAK, '<br>')}</p>"


def render_markdown(text: str) -> str:
    """Render a Markdown document as an HTML fragment."""
    return "\n".join(_blocks(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")))
