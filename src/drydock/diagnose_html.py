"""The HTML surface of ``drydock diagnose``.

The Markdown is what an operator pastes into a ticket or hands to another agent. The page is
what they read. Both render from the same verified diagnosis, so neither can say something the
other does not.

It shares :mod:`drydock.report_render` with ``drydock score report`` — the same letterhead,
verdict stamp, tab strip, and table styling — so the two documents are recognisably the same
family, and it reads like an incident report because that is the shape a reader can act on. It
is a separate artifact all the same: a receipt proves what a run delivered, a diagnosis explains
why one stopped. Publishing them together would make the second look like a section of the first.

A receipt's kit machinery is deliberately absent. There is no file tree, no checksum manifest,
and no generated viewers: a diagnosis cites local paths rather than copying evidence, so it stays
a single page that opens from anywhere.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from pathlib import Path

from drydock.diagnose_evidence import Bundle
from drydock.diagnose_report import REQUIRED_SECTIONS, Diagnosis
from drydock.markdown_render import render_markdown
from drydock.report_render import _cell, _letterhead, _meta, _page, _table, _tabs, _verdict

#: The verdict stamp. A diagnosis has three outcomes, not two: a stop it explained, a run with
#: nothing live to explain, and an answer that did not satisfy the output contract.
_MARKS = {"fail": "STOPPED", "pass": "NO STOP", "warn": "INCOMPLETE"}


def render_page(bundle: Bundle, diagnosis: Diagnosis, *, stamp: str) -> str:
    """The diagnosis as a self-contained HTML page."""
    state = _state(bundle, diagnosis)
    heading = f"{bundle.target} — Diagnosis"
    docline = f"Run {bundle.run_stamp or 'not recorded'} · reported {stamp}"

    body = [
        _letterhead("DRYDOCK DIAGNOSE", heading, docline, state, _MARKS[state], "Drydock"),
        _verdict(state, _headline(bundle, diagnosis), _classification(bundle)),
        _meta(_facts(bundle, diagnosis)),
        _ladder_table(bundle),
        _tabs(_panels(bundle, diagnosis)),
    ]
    return _page(f"Drydock Diagnosis — {bundle.target}", "\n".join(body))


def write_page(bundle: Bundle, diagnosis: Diagnosis, *, stamp: str, directory: Path) -> Path:
    """Write the page beside its Markdown twin and return its path."""
    from drydock.diagnose_report import REPORT_PREFIX

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{REPORT_PREFIX}_{stamp}.html"
    path.write_text(render_page(bundle, diagnosis, stamp=stamp), encoding="utf-8", newline="\n")
    return path


def _state(bundle: Bundle, diagnosis: Diagnosis) -> str:
    """``fail`` when a stop was explained, ``warn`` when the answer was malformed, else ``pass``."""
    if not diagnosis.ok:
        return "warn"
    return "fail" if bundle.stop is not None else "pass"


def _headline(bundle: Bundle, diagnosis: Diagnosis) -> str:
    if not diagnosis.ok:
        return "Diagnosis incomplete"
    if bundle.stop is None:
        return f"No live failure recorded for {bundle.target}"
    return bundle.stop.headline


def _classification(bundle: Bundle) -> str:
    if bundle.stop is None or not bundle.stop.detail:
        return ""
    return html.escape(bundle.stop.detail)


def _facts(bundle: Bundle, diagnosis: Diagnosis) -> list[tuple[str, str]]:
    from drydock import __version__

    pairs = [
        ("Target", html.escape(bundle.target)),
        ("Run", bundle.run_stamp or "not recorded"),
        ("Drydock", __version__),
        ("Commands", str(len(bundle.commands))),
        ("Failed commands", str(len(bundle.failed_commands))),
    ]
    if bundle.stop is not None:
        pairs.append(("Attempts at the stop", str(bundle.stop.attempts)))
    if diagnosis.amendments:
        pairs.append(("Amendments", str(len(diagnosis.amendments))))
    return pairs


def _ladder_table(bundle: Bundle) -> str:
    """The milestone ladder, which is the first thing a reader looks for."""
    rows = []
    for row in bundle.ladder:
        answered = ", ".join(entry.label for entry in row.answered)
        rows.append([
            _cell(row.milestone, css=f"state {row.state.replace(' ', '-')}"),
            _cell(_STATE_WORDS[row.state]),
            _cell(row.label or "—"),
            _cell(_clock(row.at)),
            _cell(row.note or row.detail or "—"),
            _cell(answered or "—"),
        ])
    table = _table(["Milestone", "Result", "Recorded state", "When", "Detail", "Superseded"], rows)
    return f'<section class="block"><h2>Stage Ladder</h2>{table}</section>'


_STATE_WORDS = {"pass": "PASSED", "fail": "FAILED", "not run": "NOT RUN"}


def _panels(bundle: Bundle, diagnosis: Diagnosis) -> list[tuple[str, str, str]]:
    """The report's tabs, in the order a reader works through them."""
    panels: list[tuple[str, str, str]] = []

    findings = "".join(
        f"<h2>{html.escape(name)}</h2>{render_markdown(diagnosis.sections.get(name, ''))}"
        for name in REQUIRED_SECTIONS[:-1]
        if diagnosis.sections.get(name, "").strip()
    )
    panels.append(("findings", "Findings", findings))
    panels.append(("amendments", "Repair Proposal", _amendments_panel(diagnosis)))
    panels.append(("commands", "Commands", _commands_panel(bundle)))
    panels.append(("logs", "Log Files", _logs_panel(bundle)))
    if not diagnosis.ok:
        panels.append(("raw", "Raw Answer", _raw_panel(diagnosis)))
    return panels


def _amendments_panel(diagnosis: Diagnosis) -> str:
    blocks: list[str] = []
    for index, amendment in enumerate(diagnosis.amendments, start=1):
        blocks.append(
            f'<section class="block"><h3>{index}. {html.escape(amendment.summary)}</h3>'
            f"{_meta([('File', html.escape(amendment.file)), ('Why', html.escape(amendment.why))])}"
            f'<pre class="diff">{_diff_html(amendment.diff)}</pre></section>'
        )
    if not blocks:
        blocks.append('<p class="note">No amendments were offered.</p>')
    if diagnosis.unapplicable:
        rows = [
            [_cell(item.summary), _cell(item.file), _cell(item.rejection)]
            for item in diagnosis.unapplicable
        ]
        blocks.append(
            '<section class="block"><h3>Not Offered</h3>'
            "<p>Proposed, but could not be verified against the current files.</p>"
            f"{_table(['Amendment', 'File', 'Reason'], rows)}</section>"
        )
    return "".join(blocks)


def _diff_html(diff: str) -> str:
    """A unified diff with its added and removed lines coloured."""
    lines = []
    for line in diff.strip().splitlines():
        escaped = html.escape(line)
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            lines.append(f'<span class="hunk">{escaped}</span>')
        elif line.startswith("+"):
            lines.append(f'<span class="add">{escaped}</span>')
        elif line.startswith("-"):
            lines.append(f'<span class="del">{escaped}</span>')
        else:
            lines.append(escaped)
    return "\n".join(lines)


def _commands_panel(bundle: Bundle) -> str:
    rows = []
    for command in bundle.commands:
        code = int(command.get("return_code") or 0)
        rows.append([
            _cell(str(command.get("time") or "")),
            _cell(str(command.get("command") or ""), css="mono"),
            _cell(str(code), css="state " + ("pass" if code == 0 else "fail")),
        ])
    return _table(["When", "Command", "Exit"], rows)


def _logs_panel(bundle: Bundle) -> str:
    if not bundle.logs:
        return '<p class="note">No model-execution artifacts were recorded for this run.</p>'
    rows = [
        [
            _cell(log.role),
            _cell(log.path, css="mono"),
            _cell(f"{log.size:,}" if log.exists else "missing"),
            _cell(log.sha256[:16], css="mono"),
        ]
        for log in bundle.logs
    ]
    return (
        "<p>These files are local. Open them directly to verify anything in this report.</p>"
        + _table(["Role", "Path", "Bytes", "SHA-256"], rows)
    )


def _raw_panel(diagnosis: Diagnosis) -> str:
    problems = "".join(f"<li>{html.escape(problem)}</li>" for problem in diagnosis.problems)
    return (
        f"<h3>Contract violations</h3><ul>{problems}</ul>"
        f"<h3>Raw model answer</h3><pre>{html.escape(diagnosis.raw.strip())}</pre>"
    )


def _clock(at: str) -> str:
    if not at or "T" not in at:
        return at or "—"
    date, _, rest = at.partition("T")
    return f"{date} {rest[:5]}"


def _sections_of(diagnosis: Diagnosis) -> Sequence[str]:
    return [name for name in REQUIRED_SECTIONS if name in diagnosis.sections]
