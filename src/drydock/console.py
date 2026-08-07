"""Terminal output capability.

Drydock's console output uses box-drawing rules, status glyphs, arrows, and em dashes, and
LLM output streams arbitrary Unicode through the same stdout. Two different things can go
wrong there, and they need separate answers:

* The stream's *encoding* cannot carry the character. This raises ``UnicodeEncodeError``
  mid-command. The common cases are a Windows console on a legacy code page (``cp437``,
  ``cp850``, ``cp1252``), redirected output on a non-UTF-8 locale, and CI capture with
  ``LANG=C``. Encoding is a hard constraint: it is measurable, and it overrides everything.
* The terminal's *font* has no glyph for the character. Nothing raises; the user sees tofu
  boxes. A UTF-8 terminal is not evidence of an emoji font, so this cannot be probed. It can
  only be defaulted conservatively.

The old design defaulted to maximum output and searched for reasons to downgrade, which made
the second failure the default outcome on any terminal it did not recognize. This module
inverts that: output is rendered in the richest of three tiers that the host is *known* to
support.

===========  ==========================  ====================================================
Tier         Glyphs                      Requires
===========  ==========================  ====================================================
``emoji``    ``✅ ❌`` plus all below     a terminal known to carry an emoji font
``text``     ``✓ ✗ ⚠ ─ ═ → — · … ×``     a UTF-8-capable stream (the default for unknown hosts)
``ascii``    ``v x ! - = -> - | ...``     nothing at all
===========  ==========================  ====================================================

Nearly every glyph Drydock prints is a single-width BMP symbol present in any monospace font
shipped this decade, so the ``text`` tier keeps the icons. Only ``✅``/``❌`` are true emoji:
double-width, emoji-font-dependent, and a column-alignment hazard.

Resolution order:

1. ``DRYDOCK_GLYPHS`` (or ``--glyphs``) names a tier outright. ``DRYDOCK_ASCII`` and the older
   ``--ascii``/``--unicode`` remain as aliases for the bottom and top tiers.
2. An MSYS, MinGW, or Cygwin terminal is ASCII: these hosts can advertise UTF-8 while rendering
   status glyphs incorrectly, and their default fonts predate ``✓``.
3. A Windows console host on a non-UTF-8 code page is ASCII.
4. A POSIX terminal whose ``TERM`` names a limited-font host (``dumb``, ``linux``, ``vt100``,
   or nothing) is ASCII.
5. A terminal on the emoji allowlist is ``emoji``; anything else, including every redirect and
   capture buffer, is ``text``.
6. Whatever tier that produced is then capped by what the stream's encoding can actually encode.

The resolved tier is applied by wrapping ``sys.stdout``/``sys.stderr``, so every existing
``print`` call site is covered without change, including streamed model text.
"""

from __future__ import annotations

import io
import os
import sys
import unicodedata
from typing import TextIO

_GLYPHS_ENV = "DRYDOCK_GLYPHS"
_ASCII_ENV = "DRYDOCK_ASCII"

ASCII = "ascii"
TEXT = "text"
EMOJI = "emoji"

TIERS = (ASCII, TEXT, EMOJI)
_TIER_RANK = {tier: rank for rank, tier in enumerate(TIERS)}

# The characters each tier must be able to encode. A stream that cannot encode a tier's probe
# is capped at the tier below it.
TEXT_PROBE = "─═—–·→✓✗⚠…×“”‘’•"
EMOJI_PROBE = "✅❌⛔"

# Retained for callers and tests that predate the tier model.
PROBE = TEXT_PROBE + EMOJI_PROBE

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

# Emoji-presentation glyphs and their single-width text equivalents. Applied for the ``text``
# tier, where the codepoint is encodable but the terminal has no emoji font.
_EMOJI_FALLBACKS = {
    "✅": "✓",
    "❌": "✗",
    "❎": "✗",
    "☑": "✓",
    "✔": "✓",
    "✘": "✗",
    "⛔": "⚠",
    "🚫": "⚠",
    "❗": "!",
    "❓": "?",
    "➜": "→",
    "➔": "→",
}

# Codepoints below this are text symbols that any UTF-8 font is expected to carry. At or above
# it lies the supplementary emoji and pictograph space, which is demoted wholesale for the
# ``text`` tier: LLM output streams arbitrary emoji through the same stdout, and an unmapped
# one is tofu on a host that reached this tier.
_SUPPLEMENTARY_EMOJI_START = 0x1F000

# Zero-width joiners, variation selectors, and skin-tone modifiers carry no meaning once the
# glyph they decorate has been demoted, and each would otherwise become its own replacement.
_EMOJI_MODIFIERS = frozenset({0x200D, 0xFE0E, 0xFE0F, *range(0x1F3FB, 0x1F400)})

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
    " ": " ",  # no-break space
    " ": " ",  # thin space
    "​": "",  # zero-width space
    "©": "(C)",
    "®": "(R)",
    "™": "(TM)",
}

_TRANSLATE = str.maketrans(_FALLBACKS)
_EMOJI_TRANSLATE = str.maketrans(_EMOJI_FALLBACKS)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def to_text(text: str) -> str:
    """Return ``text`` with emoji-presentation characters demoted to text symbols.

    Mapped emoji become their single-width equivalent (``✅`` becomes ``✓``). Anything left in
    the supplementary emoji space becomes ``*``, since a host at this tier has no font for it;
    a run of them collapses to one mark so a joined sequence does not fan out.
    """
    if text.isascii():
        return text
    text = text.translate(_EMOJI_TRANSLATE)
    if not any(
        ord(char) >= _SUPPLEMENTARY_EMOJI_START or ord(char) in _EMOJI_MODIFIERS for char in text
    ):
        return text
    out: list[str] = []
    for char in text:
        code = ord(char)
        if code in _EMOJI_MODIFIERS:
            continue
        if code < _SUPPLEMENTARY_EMOJI_START:
            out.append(char)
            continue
        if not out or out[-1] != "*":
            out.append("*")
    return "".join(out)


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


def display_width(text: str) -> int:
    """The number of terminal cells ``text`` occupies. Emoji are two cells wide."""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def pad_display(text: str, width: int) -> str:
    """Left-align ``text`` in ``width`` terminal cells, counting double-width glyphs as two."""
    return text + " " * max(0, width - display_width(text))


def active_tier() -> str:
    """The tier ``sys.stdout`` is currently rendering at.

    Call sites that must choose a glyph *before* writing it — because the choice changes the
    column width — ask here rather than emitting an emoji and letting the wrapper shrink it.
    """
    stream = getattr(sys, "stdout", None)
    tier = getattr(stream, "tier", None)
    if isinstance(tier, str) and tier in _TIER_RANK:
        return tier
    return resolve_tier(stream)


def render(text: str, tier: str) -> str:
    """Return ``text`` rendered for ``tier``."""
    if tier == EMOJI or text.isascii():
        return text
    if tier == TEXT:
        return to_text(text)
    return to_ascii(text)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _forced_tier() -> str | None:
    """The tier named by the environment, or ``None`` to auto-detect."""
    value = (os.environ.get(_GLYPHS_ENV) or "").strip().lower()
    if value in _TIER_RANK:
        return value
    if value == "unicode":
        return EMOJI
    if value and value != "auto":
        return None  # an unreadable setting must not silently pick a tier
    legacy = (os.environ.get(_ASCII_ENV) or "").strip().lower()
    if legacy in _TRUE_VALUES:
        return ASCII
    if legacy in _FALSE_VALUES:
        return EMOJI
    return None


def _isatty(stream: TextIO | None) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, ValueError):
        return False


def msys_terminal(stream: TextIO | None = None) -> bool:
    """Whether this process is hosted by the MSYS/MinGW/Cygwin compatibility layer.

    These hosts can advertise UTF-8 through Python while producing confused emoji and status
    glyph output, and their default fonts (Lucida Console and kin) have box drawing but no
    ``✓``. The decision is made on environment markers alone: an MSYS terminal is a named pipe,
    not a Windows console, so ``isatty()`` is ``False`` there under a native Windows Python and
    an ``isatty()`` precondition would mean this rule never fired for the case it exists to
    catch. ``stream`` is accepted for symmetry and ignored.
    """
    markers = (
        os.environ.get("MSYSTEM", ""),
        os.environ.get("OSTYPE", ""),  # exported only by some shells; MSYSTEM is the reliable one
        os.environ.get("MINGW_PREFIX", ""),
        os.environ.get("TERM_PROGRAM", ""),
        sys.platform,
    )
    return any(
        marker.lower().startswith(("msys", "mingw", "cygwin", "/mingw", "mintty"))
        for marker in markers
        if marker
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
    if not _isatty(stream):
        return False  # a redirect is judged by its encoding, not by the console host
    if os.environ.get("WT_SESSION"):
        return False
    code_page = _console_code_page()
    return code_page is not None and code_page != 65001


# POSIX ``TERM`` values naming a host with a limited glyph repertoire, plus the empty string for
# a terminal that declares nothing. Only consulted for a tty, and only off Windows, where cmd
# and PowerShell leave ``TERM`` unset as a matter of course.
_ASCII_TERMS = frozenset({
    "",
    "dumb",
    "unknown",
    "vt52",
    "vt100",
    "vt102",
    "vt220",
    "linux",
    "cons25",
    "ansi",
    "sun",
    "wsvt25",
})

# Terminals known to ship or resolve a colour-emoji font. Everything absent from this list is
# rendered at the ``text`` tier, which is legible everywhere rather than pretty in some places.
_EMOJI_TERM_PROGRAMS = frozenset({
    "vscode",
    "iterm.app",
    "apple_terminal",
    "wezterm",
    "ghostty",
    "hyper",
    "tabby",
    "rio",
    "warpterminal",
})
_EMOJI_TERMS = frozenset({"xterm-kitty", "alacritty", "wezterm", "contour"})


def emoji_capable_host() -> bool:
    """Whether the hosting terminal is known to render colour emoji."""
    if os.environ.get("WT_SESSION"):
        return True  # Windows Terminal, including its PowerShell and WSL profiles
    if os.environ.get("KONSOLE_VERSION"):
        return True
    if os.environ.get("TERM_PROGRAM", "").strip().lower() in _EMOJI_TERM_PROGRAMS:
        return True
    if os.environ.get("TERM", "").strip().lower() in _EMOJI_TERMS:
        return True
    vte = os.environ.get("VTE_VERSION", "").strip()
    return vte.isdigit() and int(vte) >= 5000  # GNOME Terminal and the VTE family


def host_tier(stream: TextIO | None) -> str:
    """The richest tier the hosting terminal is known to render, ignoring encoding."""
    if stream is None:
        return ASCII
    if msys_terminal(stream):
        return ASCII
    if legacy_windows_console(stream):
        return ASCII
    if not _isatty(stream):
        # A redirect, a pipe, or a capture buffer: no font is involved, so nothing can be tofu,
        # but captured artifacts stay legible and diffable without emoji.
        return TEXT
    if os.name == "posix" and os.environ.get("TERM", "").strip().lower() in _ASCII_TERMS:
        return ASCII
    return EMOJI if emoji_capable_host() else TEXT


def encoding_tier(stream: TextIO | None) -> str:
    """The richest tier ``stream``'s own encoding can carry.

    A stream that reports no encoding is an in-memory text sink (``StringIO``, a capture
    buffer), not a console: nothing there can raise ``UnicodeEncodeError``, so it imposes no cap.
    """
    encoding = getattr(stream, "encoding", None) if stream is not None else None
    if not encoding:
        return EMOJI
    for tier, probe in ((EMOJI, EMOJI_PROBE), (TEXT, TEXT_PROBE)):
        try:
            probe.encode(encoding, errors="strict")
        except (UnicodeEncodeError, LookupError, TypeError):
            continue
        return tier
    return ASCII


def resolve_tier(stream: TextIO | None) -> str:
    """The tier ``stream`` should be rendered at.

    An explicit override replaces the host heuristic but never the encoding cap: forcing
    ``emoji`` onto a ``cp437`` stream would reintroduce the ``UnicodeEncodeError`` this module
    exists to prevent.
    """
    forced = _forced_tier()
    tier = forced if forced is not None else host_tier(stream)
    cap = encoding_tier(stream)
    return tier if _TIER_RANK[tier] <= _TIER_RANK[cap] else cap


def stream_supports_unicode(stream: TextIO | None) -> bool:
    """Whether ``stream`` keeps any non-ASCII glyphs. Retained for older callers."""
    return resolve_tier(stream) != ASCII


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

_vt_enabled: bool | None = None

# How the active tier was chosen, as of the last ``configure_stdio`` call.
_origin = "auto"


def _enable_windows_vt(stream: TextIO) -> bool:
    """Turn on ANSI escape processing for a Windows console, reporting whether it is on.

    Without ``ENABLE_VIRTUAL_TERMINAL_PROCESSING`` a legacy ``conhost`` prints the escape
    itself — ``←[32m`` — instead of colouring the text. The result is cached: the mode is a
    property of the console, not of the call.
    """
    global _vt_enabled
    if _vt_enabled is not None:
        return _vt_enabled
    _vt_enabled = False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11 if stream is sys.stdout else -12)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return _vt_enabled
        enable_virtual_terminal_processing = 0x0004
        if mode.value & enable_virtual_terminal_processing:
            _vt_enabled = True
        else:
            _vt_enabled = bool(
                kernel32.SetConsoleMode(handle, mode.value | enable_virtual_terminal_processing)
            )
    except Exception:
        _vt_enabled = False  # an unusual host must cost colour, never the command
    return _vt_enabled


def color_enabled(stream: TextIO | None = None) -> bool:
    """Whether ANSI colour may be written to ``stream``.

    Colour is a separate capability from glyphs: a terminal can render ``✓`` perfectly and
    still print escape sequences literally.
    """
    if stream is None:
        stream = getattr(sys, "stdout", None)
    if stream is None or os.environ.get("NO_COLOR"):
        return False
    if not _isatty(stream):
        return False
    if os.environ.get("TERM", "").strip().lower() in {"dumb", "unknown"}:
        return False
    if os.name == "nt" and not os.environ.get("WT_SESSION"):
        underlying = getattr(stream, "wrapped", stream)
        return _enable_windows_vt(underlying)
    return True


# ---------------------------------------------------------------------------
# Stream installation
# ---------------------------------------------------------------------------


class GlyphStream(io.TextIOBase):
    """Text stream wrapper that renders output at a fixed tier before writing."""

    def __init__(self, stream: TextIO, tier: str = ASCII) -> None:
        self._stream = stream
        self.tier = tier

    def write(self, text: str) -> int:
        self._stream.write(render(text, self.tier))
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


# The former name, kept so existing imports and pickled references keep working.
AsciiStream = GlyphStream


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


def configure_stdio() -> str:
    """Prepare ``sys.stdout`` and ``sys.stderr`` for this environment.

    Returns the tier ``sys.stdout`` resolved to. Safe to call more than once: a later call with
    a different override undoes the wrapper an earlier one installed.
    """
    global _origin
    # Recorded here rather than read back later: the command publishes its resolved tier to the
    # environment for its subprocesses, which would make every run look like it was forced.
    _origin = "forced" if _forced_tier() is not None else "auto"
    stdout_tier = TEXT
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        wrapped = isinstance(stream, GlyphStream)
        # An earlier call may have wrapped the stream before ``--glyphs`` was read, so re-running
        # must be able to undo its own decision.
        underlying = stream.wrapped if wrapped else stream
        tier = resolve_tier(underlying)
        if name == "stdout":
            stdout_tier = tier
        _relax_errors(underlying)
        if tier == EMOJI:
            if wrapped:
                setattr(sys, name, underlying)
            continue
        if wrapped:
            stream.tier = tier
        else:
            setattr(sys, name, GlyphStream(underlying, tier))
    return stdout_tier


# ---------------------------------------------------------------------------
# Self-report
# ---------------------------------------------------------------------------

_REPORTED_ENV = (
    "DRYDOCK_GLYPHS",
    "DRYDOCK_ASCII",
    "TERM",
    "TERM_PROGRAM",
    "COLORTERM",
    "MSYSTEM",
    "MINGW_PREFIX",
    "WT_SESSION",
    "VTE_VERSION",
    "KONSOLE_VERSION",
    "NO_COLOR",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
)

# One line carrying every glyph Drydock prints, for eyeballing what a terminal actually does.
SAMPLE = "✅ ❌ ⛔  ✓ ✗ ⚠  ─ ═ →  — · …  ×"


def console_report(stream: TextIO | None = None) -> list[tuple[str, str]]:
    """Name/value rows describing how this terminal was classified and why."""
    if stream is None:
        stream = getattr(sys, "stdout", None)
    underlying = getattr(stream, "wrapped", stream)
    rows = [
        ("platform", f"{sys.platform} (os.name={os.name})"),
        ("python", sys.version.split()[0]),
        ("stdout encoding", str(getattr(underlying, "encoding", None) or "-")),
        ("stdout isatty", "yes" if _isatty(underlying) else "no"),
        ("windows code page", str(_console_code_page() or "-")),
    ]
    rows += [(name, os.environ.get(name) or "-") for name in _REPORTED_ENV]
    rows += [
        ("msys/mingw host", "yes" if msys_terminal(underlying) else "no"),
        ("legacy windows console", "yes" if legacy_windows_console(underlying) else "no"),
        ("emoji-capable host", "yes" if emoji_capable_host() else "no"),
        ("host tier", host_tier(underlying)),
        ("encoding cap", encoding_tier(underlying)),
        ("resolved tier", f"{resolve_tier(underlying)} ({_origin})"),
        ("colour", "enabled" if color_enabled(stream) else "disabled"),
    ]
    return rows


def write_raw(stream: TextIO, text: str) -> bool:
    """Write ``text`` past any tier wrapper, reporting whether the stream accepted it.

    The diagnostic value of the sample lines is seeing what the terminal itself does with
    unfiltered Unicode: tofu in this line is the evidence that a downgrade was correct.
    """
    underlying = getattr(stream, "wrapped", stream)
    try:
        underlying.write(text)
        underlying.flush()
    except (UnicodeEncodeError, ValueError, OSError):
        return False
    return True
