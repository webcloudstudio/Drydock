from __future__ import annotations

import io
from datetime import datetime

from drydock.uat_console import StepConsole, format_argv


def _console(**kwargs) -> tuple[StepConsole, io.StringIO]:
    stream = io.StringIO()
    console = StepConsole(
        stream,
        width=60,
        clock=lambda: datetime(2026, 8, 9, 14, 3, 11),
        **kwargs,
    )
    return console, stream


def test_format_argv_reads_as_a_typed_command() -> None:
    assert format_argv(("/usr/bin/python3", "-m", "drydock", "analyze", "Toml")) == (
        "drydock analyze Toml"
    )
    assert format_argv(("sh", "bin/test.sh")) == "sh bin/test.sh"


def test_format_argv_keeps_a_multi_line_argument_on_one_line() -> None:
    line = format_argv(("python", "-c", "import sys\nprint('x')\n"))

    assert line == "python -c import sys print('x')"


def test_step_frames_child_output_with_stage_headers_and_a_gutter() -> None:
    console, stream = _console()

    console.event("Toml: analyze")
    console.step(("/usr/bin/python3", "-m", "drydock", "analyze", "Toml"), "09-analyze")
    console.chunk("stdout", "Analyzing Blueprint\n")
    console.chunk("stderr", "warning: no stack\n")
    console.finish(0, 64200)

    lines = stream.getvalue().splitlines()
    assert lines[1].startswith("── Toml · step 9: analyze")
    assert lines[1].endswith("14:03:11 ──")
    assert lines[2] == "   drydock analyze Toml"
    assert lines[3] == " │ Analyzing Blueprint"
    assert lines[4] == " ! warning: no stack"
    assert "exit 0   1m 4.2s" in lines[5]


def test_partial_and_redrawn_lines_reach_the_terminal_unchanged() -> None:
    console, stream = _console()

    console.chunk("stdout", "pass 1")
    console.chunk("stdout", "\rpass 2")

    # No trailing newline is invented, and the redraw keeps its carriage return.
    assert stream.getvalue() == " │ pass 1\r │ pass 2"


def test_crlf_output_is_not_given_a_second_gutter() -> None:
    console, stream = _console()

    console.chunk("stdout", "line\r\nnext\r\n")

    assert stream.getvalue() == " │ line\r\n │ next\r\n"


def test_an_open_line_is_closed_before_the_other_stream_writes() -> None:
    console, stream = _console()

    console.chunk("stdout", "working")
    console.chunk("stderr", "boom\n")

    assert stream.getvalue() == " │ working\n ! boom\n"


def test_quiet_reports_stage_names_only() -> None:
    console, stream = _console(quiet=True)

    console.event("Toml: analyze")
    console.step(("/usr/bin/python3", "-m", "drydock", "analyze", "Toml"), "09-analyze")
    console.chunk("stdout", "Analyzing Blueprint\n")
    console.finish(0, 100)

    assert stream.getvalue() == "UAT: Toml: analyze\n"
