"""Terminal output encoding.

Drydock's console output uses box-drawing rules, status glyphs, arrows, and em dashes, and
LLM output streams arbitrary Unicode through the same stdout. A stream whose encoding cannot
carry those characters raises ``UnicodeEncodeError`` mid-command: the common cases are a
Windows console on a legacy code page (``cp437``, ``cp850``, ``cp1252``), redirected output on
a non-UTF-8 locale, and CI log capture with ``LANG=C``.

This module detects that condition once, at process start, and installs an ASCII
transliterating writer over the affected stream. Every existing ``print`` call site is
covered without change, including streamed model text.

Detection order:

1. ``DRYDOCK_ASCII`` (or ``--ascii``) forces ASCII; ``DRYDOCK_ASCII=0`` forces Unicode.
2. An MSYS, MinGW, or Cygwin terminal is ASCII by default: compatibility terminals can report
   ``utf-8`` while rendering status glyphs incorrectly.
3. A Windows console host on a non-UTF-8 code page is ASCII.
4. Otherwise the stream's own encoding is probed with Drydock's glyph set.
"""

from __future__ import annotations

import io
import os
import sys
import unicodedata
from typing import TextIO

_ASCII_ENV = "DRYDOCK_ASCII"

# Every non-ASCII character Drydock itself emits, plus the punctuation LLM output supplies most
# often. A stream that cannot encode the whole probe is treated as ASCII-only.
PROBE = "─═—–·→✓✗✅❌⚠⛔…×“”‘’•"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

# Replacements are chosen to keep column alignment where the glyph appears in a table: the
# single-cell status marks stay one character wide.
_FALLBACKS = {
    "─": "-",
    "━": "-",
    "═": "=",
    "│": "|",
    "┃": "|",
    "┌": "+",
    "┐": "+",
    "└": "+",
    "┘": "+",
    "├": "+",
    "┤": "+",
    "┬": "+",
    "┴": "+",
    "┼": "+",
    "█": "#",
    "▓": "#",
    "▒": ":",
    "░": ".",
    "■": "#",
    "□": "-",
    "▸": ">",
    "▪": "*",
    "•": "*",
    "·": "|",
    "—": "-",
    "–": "-",
    "→": "->",
    "←": "<-",
    "↑": "^",
    "↓": "v",
    "⇒": "=>",
    "✓": "v",
    "✔": "v",
    "✗": "x",
    "✘": "x",
    "✅": "OK",
    "❌": "NO",
    "⚠": "!",
    "⛔": "!!",
    "…": "...",
    "×": "x",
    "≥": ">=",
    "≤": "<=",
    "≠": "!=",
    "±": "+/-",
    "“": '"',
    "”": '"',
    "„": '"',
    "‘": "'",
    "’": "'",
    "′": "'",
    "″": '"',
    " ": " ",
    " ": " ",
    "​": "",
    "©": "(C)",
    "®": "(R)",
    "™": "(TM)",
}

_TRANSLATE = str.maketrans(_FALLBACKS)


def to_ascii(text: str) -> str:
    """Return ``text`` with every non-ASCII character replaced by an ASCII equivalent.

    Known glyphs use the curated table. Anything left is decomposed (``é`` becomes ``e``) and
    whatever still will not fit becomes ``?``, so the result is always encodable by any codec.
    """
    if text.isascii():
        return text
    text = text.translate(_TRANSLATE)
    if text.isascii():
        return text
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.encode("ascii", "replace").decode("ascii")


def _forced_ascii() -> bool | None:
    """``True`` to force ASCII, ``False`` to force Unicode, ``None`` to auto-detect."""
    value = (os.environ.get(_ASCII_ENV) or "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return None


def stream_supports_unicode(stream: TextIO | None) -> bool:
    """Whether ``stream`` can encode Drydock's glyph set.

    A stream that reports no encoding is an in-memory text sink (``StringIO``, a capture
    buffer), not a console: nothing there can raise ``UnicodeEncodeError``, so it keeps the
    Unicode rendering. Only a stream that names an encoding is probed against it.
    """
    forced = _forced_ascii()
    if forced is not None:
        return not forced
    if stream is None:
        return False
    if msys_terminal(stream):
        return False
    if legacy_windows_console(stream):
        return False
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return True
    try:
        PROBE.encode(encoding, errors="strict")
    except (UnicodeEncodeError, LookupError, TypeError):
        return False
    return True


def msys_terminal(stream: TextIO | None) -> bool:
    """Whether a terminal is hosted by the MSYS/MinGW/Cygwin compatibility layer.

    These hosts can advertise UTF-8 through Python while still producing confused emoji and
    status glyph output. ``--unicode`` remains an explicit invocation-wide override.
    """
    if stream is None:
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    markers = (
        os.environ.get("MSYSTEM", ""),
        os.environ.get("OSTYPE", ""),
        sys.platform,
    )
    return any(
        marker.lower().startswith(("msys", "mingw", "cygwin")) for marker in markers if marker
    )


def _console_code_page() -> int | None:
    """The Windows console output code page, or ``None`` off Windows or when unavailable."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetConsoleOutputCP())  # type: ignore[attr-defined]
    except Exception:
        return None  # no console attached, or an unusual host; fall back to the encoding probe


def legacy_windows_console(stream: TextIO | None) -> bool:
    """Whether ``stream`` is a Windows console host that will not render Drydock's glyphs.

    Python reports ``utf-8`` for any Windows console because it writes through ``WriteConsoleW``,
    so the encoding probe always passes there. What actually decides legibility is the console
    host: ``conhost`` on a legacy code page draws a box for ``✓`` in its raster fonts. Windows
    Terminal (``WT_SESSION``) and a UTF-8 code page (65001) render the glyph set.
    """
    if os.name != "nt" or stream is None:
        return False
    try:
        if not stream.isatty():
            return False  # a redirect is judged by its encoding, not by the console host
    except (AttributeError, ValueError):
        return False
    if os.environ.get("WT_SESSION"):
        return False
    code_page = _console_code_page()
    return code_page is not None and code_page != 65001


class AsciiStream(io.TextIOBase):
    """Text stream wrapper that transliterates non-ASCII output before writing."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        self._stream.write(to_ascii(text))
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except (AttributeError, ValueError):
            return False

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        return self._stream.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._stream, "encoding", None) or "ascii"

    @property
    def errors(self) -> str | None:
        return getattr(self._stream, "errors", None)

    @property
    def wrapped(self) -> TextIO:
        return self._stream

    def __getattr__(self, name: str) -> object:
        return getattr(self._stream, name)


def _relax_errors(stream: TextIO) -> None:
    """Make a Unicode-capable stream non-fatal for characters it still cannot encode."""
    if getattr(stream, "errors", None) in {None, "backslashreplace", "replace"}:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(errors="backslashreplace")
    except (ValueError, OSError):
        pass  # output must never fail because the stream refused a reconfigure


def configure_stdio() -> bool:
    """Prepare ``sys.stdout`` and ``sys.stderr`` for this environment.

    Returns ``True`` when Unicode glyphs are kept, ``False`` when output was downgraded to
    ASCII. Safe to call more than once.
    """
    unicode_ok = True
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        wrapped = isinstance(stream, AsciiStream)
        # An earlier call may have wrapped the stream before ``--ascii``/``--unicode`` was
        # read, so re-running must be able to undo its own decision.
        underlying = stream.wrapped if wrapped else stream
        if stream_supports_unicode(underlying):
            if wrapped:
                setattr(sys, name, underlying)
            _relax_errors(underlying)
            continue
        unicode_ok = False
        if not wrapped:
            setattr(sys, name, AsciiStream(underlying))
    return unicode_ok
