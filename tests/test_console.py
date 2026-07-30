"""Console encoding detection and ASCII transliteration."""

from __future__ import annotations

import io
import os
import sys

import pytest

from drydock import console


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
def _clear_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-detect during tests, and let monkeypatch restore whatever a test writes."""
    monkeypatch.setenv("DRYDOCK_ASCII", "")


# ── to_ascii ────────────────────────────────────────────────────────────────


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
    ],
)
def test_to_ascii_maps_known_glyphs(text: str, expected: str) -> None:
    assert console.to_ascii(text) == expected


def test_to_ascii_output_is_always_ascii() -> None:
    result = console.to_ascii("日本語 ✓ ← ﬁ")
    assert result.isascii()
    result.encode("cp1252")  # never raises for any downstream codec


def test_to_ascii_preserves_ascii_identity() -> None:
    text = "  build  12/20  OK\n"
    assert console.to_ascii(text) is text


# ── detection ───────────────────────────────────────────────────────────────


def test_utf8_stream_supports_unicode() -> None:
    assert console.stream_supports_unicode(_Stream("utf-8")) is True


@pytest.mark.parametrize("encoding", ["cp1252", "cp437", "cp850", "ascii", "latin-1"])
def test_legacy_code_pages_do_not_support_unicode(encoding: str) -> None:
    assert console.stream_supports_unicode(_Stream(encoding)) is False


def test_unknown_encoding_falls_back_to_ascii() -> None:
    assert console.stream_supports_unicode(_Stream("not-a-codec")) is False
    assert console.stream_supports_unicode(None) is False


def test_in_memory_sink_keeps_unicode() -> None:
    """A buffer that names no encoding cannot fail to encode, so it is not downgraded."""
    assert console.stream_supports_unicode(_Stream(None)) is True
    assert console.stream_supports_unicode(io.StringIO()) is True


def test_env_forces_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRYDOCK_ASCII", "1")
    assert console.stream_supports_unicode(_Stream("utf-8")) is False


def test_env_forces_unicode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRYDOCK_ASCII", "0")
    assert console.stream_supports_unicode(_Stream("cp1252")) is True


# ── AsciiStream ─────────────────────────────────────────────────────────────


def test_ascii_stream_translates_on_write() -> None:
    target = _Stream("cp1252")
    stream = console.AsciiStream(target)
    written = stream.write("── ✓ done\n")
    assert target.getvalue() == "-- v done\n"
    assert written == len("── ✓ done\n")  # reported length is the caller's text


def test_ascii_stream_delegates_terminal_traits() -> None:
    target = _Stream("cp1252", tty=True)
    stream = console.AsciiStream(target)
    assert stream.isatty() is True
    assert stream.wrapped is target


# ── configure_stdio ─────────────────────────────────────────────────────────


def test_configure_stdio_wraps_incapable_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _Stream("cp1252"))
    monkeypatch.setattr(sys, "stderr", _Stream("cp1252"))
    assert console.configure_stdio() is False
    assert isinstance(sys.stdout, console.AsciiStream)
    print("plan ─ ✓")
    assert sys.stdout.wrapped.getvalue() == "plan - v\n"


def test_configure_stdio_leaves_capable_stream_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _Stream("utf-8")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("utf-8"))
    assert console.configure_stdio() is True
    assert sys.stdout is target


def test_configure_stdio_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", _Stream("cp1252"))
    monkeypatch.setattr(sys, "stderr", _Stream("cp1252"))
    console.configure_stdio()
    first = sys.stdout
    console.configure_stdio()
    assert sys.stdout is first


def test_configure_stdio_unwraps_when_unicode_is_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    target = _Stream("cp1252")
    monkeypatch.setattr(sys, "stdout", target)
    monkeypatch.setattr(sys, "stderr", _Stream("cp1252"))
    console.configure_stdio()
    assert isinstance(sys.stdout, console.AsciiStream)
    monkeypatch.setenv("DRYDOCK_ASCII", "0")
    assert console.configure_stdio() is True
    assert sys.stdout is target


# ── CLI contract ────────────────────────────────────────────────────────────


def test_ascii_flag_is_an_invocation_wide_override() -> None:
    from drydock.cli import _extract_global_overrides

    cleaned, overrides = _extract_global_overrides(["status", "MyTarget", "--ascii"])
    assert cleaned == ["status", "MyTarget"]
    assert overrides["ascii"] is True

    cleaned, overrides = _extract_global_overrides(["--unicode", "build", "MyTarget"])
    assert cleaned == ["build", "MyTarget"]
    assert overrides["ascii"] is False

    _cleaned, overrides = _extract_global_overrides(["status"])
    assert overrides["ascii"] is None


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
    assert isinstance(sys.stdout, console.AsciiStream)
    assert target.getvalue().isascii()
    assert os.environ["DRYDOCK_ASCII"] == "1"


# ── Windows console host ────────────────────────────────────────────────────


def test_legacy_windows_console_is_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Windows console reports utf-8 whatever its code page, so the code page decides."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(console, "_console_code_page", lambda: 437)
    stream = _Stream("utf-8", tty=True)
    assert console.legacy_windows_console(stream) is True
    assert console.stream_supports_unicode(stream) is False


def test_utf8_code_page_keeps_unicode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(console, "_console_code_page", lambda: 65001)
    assert console.stream_supports_unicode(_Stream("utf-8", tty=True)) is True


def test_windows_terminal_keeps_unicode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("WT_SESSION", "abc-123")
    monkeypatch.setattr(console, "_console_code_page", lambda: 437)
    assert console.stream_supports_unicode(_Stream("utf-8", tty=True)) is True


def test_windows_redirect_is_judged_by_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirected output has no console host; its own encoding decides."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(console, "_console_code_page", lambda: 437)
    assert console.stream_supports_unicode(_Stream("utf-8", tty=False)) is True
    assert console.stream_supports_unicode(_Stream("cp1252", tty=False)) is False


def test_code_page_lookup_is_none_off_windows() -> None:
    if os.name != "nt":
        assert console._console_code_page() is None
