"""Console capability detection, glyph tiers, and transliteration."""

from __future__ import annotations

import ast
import io
import os
import sys
from pathlib import Path

import pytest

from drydock import console

ASCII, TEXT, EMOJI = console.ASCII, console.TEXT, console.EMOJI

_HOST_ENV = (
    "DRYDOCK_GLYPHS",
    "DRYDOCK_ASCII",
    "MSYSTEM",
    "MINGW_PREFIX",
    "OSTYPE",
    "TERM",
    "TERM_PROGRAM",
    "WT_SESSION",
    "VTE_VERSION",
    "KONSOLE_VERSION",
    "NO_COLOR",
)


class _Stream(io.StringIO):
    """StringIO with a settable reported encoding, standing in for a console stream."""

    def __init__(self, encoding: str | None = "utf-8", tty: bool = True) -> None:
        super().__init__()
        self._encoding = encoding
        self._tty = tty

    @property
    def encoding(self) -> str | None:  # type: ignore[override]
        return self._encoding

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture(autouse=True)
def _clean_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an unidentified terminal, whatever the developer is running in."""
    for name in _HOST_ENV:
        monkeypatch.delenv(name, raising=False)
    # An ordinary, unremarkable terminal: capable of UTF-8, unidentifiable as an emoji host.
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(console, "_origin", "auto")
    monkeypatch.setattr(console, "_vt_enabled", None)


# ── rendering ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain text", "plain text"),
        ("─" * 5, "-----"),
        ("✓ PASS", "v PASS"),
        ("✗ FAIL", "x FAIL"),
        ("a — b", "a - b"),
        ("46 imported · 0 authored", "46 imported | 0 authored"),
        ("→ remediation", "-> remediation"),
        ("truncated…", "truncated..."),
        ("⚠ warning", "! warning"),
        ("“quoted”", '"quoted"'),
        ("résumé", "resume"),
        ("✅ built", "OK built"),
    ],
)
def test_to_ascii_maps_known_glyphs(text: str, expected: str) -> None:
    assert console.to_ascii(text) == expected


def test_to_ascii_output_is_always_ascii() -> None:
    result = console.to_ascii("日本語 ✓ ← ﬁ 🚀")
    assert result.isascii()
    result.encode("cp1252")  # never raises for any downstream codec


def test_to_ascii_preserves_ascii_identity() -> None:
    text = "  build  12/20  OK\n"
    assert console.to_ascii(text) is text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain text", "plain text"),
        ("✅ done", "✓ done"),
        ("❌ failed", "✗ failed"),
        ("⛔ blocked", "⚠ blocked"),
        ("✓ ─ → …", "✓ ─ → …"),  # text-tier glyphs pass through untouched
        ("résumé 日本語", "résumé 日本語"),  # prose is not transliterated at this tier
        ("🚀 shipped", "* shipped"),  # unmapped supplementary emoji cannot be rendered
        ("⚠️ warning", "⚠ warning"),  # a variation selector is not its own glyph
        ("👨‍👩 team", "* team"),  # a joined sequence collapses to one mark
    ],
)
def test_to_text_demotes_only_emoji(text: str, expected: str) -> None:
    assert console.to_text(text) == expected


def test_render_dispatches_on_tier() -> None:
    assert console.render("✅ ✓ ─", EMOJI) == "✅ ✓ ─"
    assert console.render("✅ ✓ ─", TEXT) == "✓ ✓ ─"
    assert console.render("✅ ✓ ─", ASCII) == "OK v -"


# ── host detection ──────────────────────────────────────────────────────────


def test_unknown_terminal_defaults_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """The heart of the design: an unrecognized terminal keeps ✓ and loses ✅.

    Defaulting to emoji is what produced tofu on every host without an emoji font, and no
    probe can tell the difference — encoding capability is not font capability.
    """
    monkeypatch.setenv("TERM", "xterm-256color")
    assert console.host_tier(_Stream("utf-8", tty=True)) == TEXT
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == TEXT


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WT_SESSION", "abc-123"),
        ("TERM_PROGRAM", "vscode"),
        ("TERM_PROGRAM", "iTerm.app"),
        ("TERM_PROGRAM", "WezTerm"),
        ("KONSOLE_VERSION", "220400"),
        ("VTE_VERSION", "6003"),
        ("TERM", "xterm-kitty"),
    ],
)
def test_known_emoji_hosts_keep_emoji(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    assert console.emoji_capable_host() is True
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == EMOJI


def test_old_vte_is_not_emoji_capable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VTE_VERSION", "4205")
    assert console.emoji_capable_host() is False


@pytest.mark.parametrize("term", ["dumb", "linux", "vt100", "", "unknown"])
def test_limited_posix_terminals_are_ascii(monkeypatch: pytest.MonkeyPatch, term: str) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("TERM", term)
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == ASCII


def test_missing_term_does_not_downgrade_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """cmd and PowerShell leave TERM unset as a matter of course; only POSIX ttys are judged."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("WT_SESSION", "abc-123")
    monkeypatch.setattr(console, "_console_code_page", lambda: 65001)
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == EMOJI


def test_redirect_is_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """No font is involved in a file or a pipe, but captured output stays diffable."""
    monkeypatch.setenv("WT_SESSION", "abc-123")
    assert console.host_tier(_Stream("utf-8", tty=False)) == TEXT


def test_in_memory_sink_imposes_no_encoding_cap() -> None:
    """A buffer that names no encoding cannot raise UnicodeEncodeError."""
    assert console.encoding_tier(_Stream(None)) == EMOJI
    assert console.encoding_tier(io.StringIO()) == EMOJI


def test_no_stream_is_ascii() -> None:
    assert console.host_tier(None) == ASCII
    assert console.resolve_tier(None) == ASCII


# ── MSYS / MinGW / Cygwin ───────────────────────────────────────────────────


def test_msys_is_detected_without_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression this module exists for.

    An MSYS terminal is a named pipe, so ``isatty()`` is False under a native Windows Python.
    Gating the MSYS rule on ``isatty()`` meant it never fired for Git Bash — the reported case.
    """
    monkeypatch.setenv("MSYSTEM", "MINGW64")
    assert console.msys_terminal(_Stream("utf-8", tty=False)) is True
    assert console.resolve_tier(_Stream("utf-8", tty=False)) == ASCII
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == ASCII


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MSYSTEM", "MSYS"),
        ("MINGW_PREFIX", "/mingw64"),
        ("OSTYPE", "cygwin"),
        ("TERM_PROGRAM", "mintty"),
    ],
)
def test_every_msys_marker_downgrades(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    assert console.msys_terminal(_Stream("utf-8", tty=True)) is True


def test_linux_ostype_is_not_msys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTYPE", "linux-gnu")
    assert console.msys_terminal(_Stream("utf-8", tty=True)) is False


# ── encoding cap ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("encoding", ["cp1252", "cp437", "cp850", "ascii", "latin-1"])
def test_legacy_code_pages_cap_at_ascii(encoding: str) -> None:
    assert console.encoding_tier(_Stream(encoding)) == ASCII


def test_unknown_encoding_caps_at_ascii() -> None:
    assert console.encoding_tier(_Stream("not-a-codec")) == ASCII


def test_utf8_carries_every_tier() -> None:
    assert console.encoding_tier(_Stream("utf-8")) == EMOJI


def test_encoding_cap_beats_an_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forcing emoji onto cp437 would reintroduce the UnicodeEncodeError this module prevents."""
    monkeypatch.setenv("DRYDOCK_GLYPHS", "emoji")
    assert console.resolve_tier(_Stream("cp437", tty=True)) == ASCII


def test_override_beats_the_host_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSYSTEM", "MINGW64")
    monkeypatch.setenv("DRYDOCK_GLYPHS", "emoji")
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == EMOJI


@pytest.mark.parametrize(
    ("env", "value", "expected"),
    [
        ("DRYDOCK_GLYPHS", "ascii", ASCII),
        ("DRYDOCK_GLYPHS", "text", TEXT),
        ("DRYDOCK_GLYPHS", "emoji", EMOJI),
        ("DRYDOCK_GLYPHS", "unicode", EMOJI),
        ("DRYDOCK_ASCII", "1", ASCII),
        ("DRYDOCK_ASCII", "0", EMOJI),
    ],
)
def test_environment_overrides(
    monkeypatch: pytest.MonkeyPatch, env: str, value: str, expected: str
) -> None:
    monkeypatch.setenv(env, value)
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == expected


def test_auto_and_junk_settings_fall_back_to_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    for value in ("auto", "", "  ", "neon"):
        monkeypatch.setenv("DRYDOCK_GLYPHS", value)
        assert console.resolve_tier(_Stream("utf-8", tty=True)) == TEXT


# ── colour ──────────────────────────────────────────────────────────────────


def test_color_needs_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv("TERM", "xterm-256color")
    assert console.color_enabled(_Stream("utf-8", tty=True)) is True
    assert console.color_enabled(_Stream("utf-8", tty=False)) is False


@pytest.mark.parametrize(("name", "value"), [("NO_COLOR", "1"), ("TERM", "dumb")])
def test_color_is_suppressed(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setenv(name, value)
    assert console.color_enabled(_Stream("utf-8", tty=True)) is False


def test_windows_color_requires_virtual_terminal_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy conhost without VT enabled prints ``←[32m`` instead of colouring."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(console, "_enable_windows_vt", lambda stream: False)
    assert console.color_enabled(_Stream("utf-8", tty=True)) is False
    monkeypatch.setattr(console, "_enable_windows_vt", lambda stream: True)
    assert console.color_enabled(_Stream("utf-8", tty=True)) is True


def test_windows_terminal_needs_no_console_mode_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("WT_SESSION", "abc-123")
    monkeypatch.setattr(
        console, "_enable_windows_vt", lambda stream: pytest.fail("must not be called")
    )
    assert console.color_enabled(_Stream("utf-8", tty=True)) is True


# ── GlyphStream ─────────────────────────────────────────────────────────────


def test_glyph_stream_renders_on_write() -> None:
    target = _Stream("cp1252")
    stream = console.GlyphStream(target, ASCII)
    written = stream.write("── ✓ done\n")
    assert target.getvalue() == "-- v done\n"
    assert written == len("── ✓ done\n")  # reported length is the caller's text


def test_glyph_stream_at_text_tier_keeps_symbols() -> None:
    target = _Stream("utf-8")
    console.GlyphStream(target, TEXT).write("✅ ── done 🚀\n")
    assert target.getvalue() == "✓ ── done *\n"


def test_glyph_stream_delegates_terminal_traits() -> None:
    target = _Stream("cp1252", tty=True)
    stream = console.GlyphStream(target, ASCII)
    assert stream.isatty() is True
    assert stream.wrapped is target


def test_ascii_stream_alias_is_retained() -> None:
    assert console.AsciiStream is console.GlyphStream


# ── configure_stdio ─────────────────────────────────────────────────────────


def test_configure_stdio_wraps_an_incapable_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _Stream("cp1252"))
    monkeypatch.setattr(sys, "stderr", _Stream("cp1252"))
    assert console.configure_stdio() == ASCII
    assert isinstance(sys.stdout, console.GlyphStream)
    print("plan ─ ✓")
    assert sys.stdout.wrapped.getvalue() == "plan - v\n"


def test_configure_stdio_wraps_a_utf8_stream_at_the_text_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _Stream("utf-8")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("utf-8"))
    assert console.configure_stdio() == TEXT
    print("built ✅ ─")
    assert target.getvalue() == "built ✓ ─\n"


def test_configure_stdio_leaves_an_emoji_host_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _Stream("utf-8")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("utf-8"))
    monkeypatch.setenv("DRYDOCK_GLYPHS", "emoji")
    assert console.configure_stdio() == EMOJI
    assert sys.stdout is target


def test_configure_stdio_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _Stream("cp1252"))
    monkeypatch.setattr(sys, "stderr", _Stream("cp1252"))
    console.configure_stdio()
    first = sys.stdout
    console.configure_stdio()
    assert sys.stdout is first


def test_configure_stdio_undoes_its_own_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _Stream("cp1252")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("cp1252"))
    console.configure_stdio()
    assert isinstance(sys.stdout, console.GlyphStream)
    monkeypatch.setenv("DRYDOCK_GLYPHS", "emoji")
    monkeypatch.setattr(sys.stdout.wrapped, "_encoding", "utf-8")
    assert console.configure_stdio() == EMOJI
    assert sys.stdout is target


def test_configure_stdio_retiers_an_existing_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _Stream("utf-8")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("utf-8"))
    console.configure_stdio()
    monkeypatch.setenv("DRYDOCK_GLYPHS", "ascii")
    assert console.configure_stdio() == ASCII
    assert sys.stdout.tier == ASCII


# ── Windows console host ────────────────────────────────────────────────────


def test_legacy_windows_console_is_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows console reports utf-8 whatever its code page, so the code page decides."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(console, "_console_code_page", lambda: 437)
    stream = _Stream("utf-8", tty=True)
    assert console.legacy_windows_console(stream) is True
    assert console.resolve_tier(stream) == ASCII


def test_utf8_code_page_keeps_glyphs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(console, "_console_code_page", lambda: 65001)
    assert console.legacy_windows_console(_Stream("utf-8", tty=True)) is False
    assert console.resolve_tier(_Stream("utf-8", tty=True)) == TEXT


def test_windows_redirect_is_judged_by_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirected output has no console host; its own encoding decides."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(console, "_console_code_page", lambda: 437)
    assert console.resolve_tier(_Stream("utf-8", tty=False)) == TEXT
    assert console.resolve_tier(_Stream("cp1252", tty=False)) == ASCII


def test_code_page_lookup_is_none_off_windows() -> None:
    if os.name != "nt":
        assert console._console_code_page() is None


# ── CLI contract ────────────────────────────────────────────────────────────


def test_glyph_flags_are_invocation_wide() -> None:
    from drydock.cli import _extract_global_overrides

    cleaned, overrides = _extract_global_overrides(["status", "MyTarget", "--ascii"])
    assert cleaned == ["status", "MyTarget"]
    assert overrides["ascii"] is True

    cleaned, overrides = _extract_global_overrides(["--unicode", "build", "MyTarget"])
    assert cleaned == ["build", "MyTarget"]
    assert overrides["ascii"] is False

    cleaned, overrides = _extract_global_overrides(["--glyphs", "text", "build", "MyTarget"])
    assert cleaned == ["build", "MyTarget"]
    assert overrides["glyphs"] == "text"

    cleaned, overrides = _extract_global_overrides(["build", "MyTarget", "--glyphs=ascii"])
    assert cleaned == ["build", "MyTarget"]
    assert overrides["glyphs"] == "ascii"

    _cleaned, overrides = _extract_global_overrides(["status"])
    assert overrides["glyphs"] is None
    assert overrides["ascii"] is None


@pytest.mark.parametrize("argv", [["--glyphs", "neon"], ["--glyphs"]])
def test_bad_glyph_tier_is_rejected(argv: list[str]) -> None:
    from drydock.cli import _extract_global_overrides
    from drydock.errors import UsageError

    with pytest.raises(UsageError):
        _extract_global_overrides([*argv, "status"])


def test_ascii_flag_downgrades_command_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """``drydock --ascii`` renders the masthead and command output without glyphs, and
    publishes the choice so subprocesses of the command render the same way."""
    from drydock.cli import main

    target = _Stream("utf-8")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("utf-8"))
    try:
        main(["config", "show", "--ascii"])
    except SystemExit:
        pass
    assert isinstance(sys.stdout, console.GlyphStream)
    assert target.getvalue().isascii()
    assert os.environ["DRYDOCK_GLYPHS"] == "ascii"
    assert os.environ["DRYDOCK_ASCII"] == "1"


def test_detected_tier_is_published_for_subprocesses(monkeypatch: pytest.MonkeyPatch) -> None:
    """A child's stdout is a pipe, so left to itself it would resolve a different tier."""
    from drydock.cli import main

    monkeypatch.setattr(sys, "stdout", _Stream("utf-8"))
    monkeypatch.setattr(sys, "stderr", _Stream("utf-8"))
    try:
        main(["config", "show"])
    except SystemExit:
        pass
    assert os.environ["DRYDOCK_GLYPHS"] == TEXT


def test_status_console_reports_and_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    from drydock.cli import main

    target = _Stream("utf-8")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("utf-8"))
    try:
        main(["status", "console"])
    except SystemExit:
        pass
    out = target.getvalue()
    assert "resolved tier" in out
    assert "host tier" in out
    # Each sample is written past the tier wrapper, so it shows what the terminal itself does.
    assert console.render(console.SAMPLE, EMOJI) in out
    assert console.render(console.SAMPLE, ASCII) in out


# ── subprocess decoding ─────────────────────────────────────────────────────


def test_every_text_subprocess_pins_utf8() -> None:
    """Child output is Drydock's output too.

    Without ``encoding=``, ``text=True`` decodes with the *locale* encoding — cp1252 on
    Windows, ascii under ``LANG=C``. The streamed LLM transcript then arrives as mojibake or
    raises ``UnicodeDecodeError``, and no amount of console work downstream can repair it.
    """
    offenders: list[str] = []
    for path in sorted((Path(__file__).resolve().parents[1] / "src" / "drydock").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            spawns = isinstance(func, ast.Attribute) and func.attr in {
                "run",
                "Popen",
                "call",
                "check_call",
                "check_output",
            }
            if not spawns or getattr(func.value, "id", None) != "subprocess":
                continue
            keywords = {kw.arg for kw in node.keywords if kw.arg}
            if not {"text", "universal_newlines"} & keywords:
                continue
            if "encoding" not in keywords:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
