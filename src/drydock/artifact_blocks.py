"""Strict parsing for LLM-emitted artifact blocks."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from re import Pattern
from typing import TypeVar

from drydock.errors import DrydockError
from drydock.prompt_assembly import PromptAssembly, lines_part

R = TypeVar("R")

#: Two protocols share the ``=== NAME ===`` line grammar, at different nesting levels. This module
#: owns the *envelope*: one artifact file per block, never nested. ``acceptance.py`` owns the
#: *proof* protocol, whose ``=== AC <id> ===`` blocks live inside an artifact body. An envelope
#: parser that reads a proof delimiter as an artifact boundary collapses or orphans every
#: Blueprint carrying a criterion, so the envelope grammar reserves the ``AC`` namespace: an
#: artifact is a file, and no file is named ``AC something``. Every envelope pattern in the
#: codebase must carry this guard — see ``planning_session``, ``plan_shape``, and ``refit``.
#:
#: The guard absorbs an optional ``END`` itself so it is position-independent. A pattern that
#: writes the end marker as ``(?:END )?`` would otherwise backtrack that group to empty and match
#: ``=== END AC <id> ===`` with the name ``END AC <id>``, defeating a guard placed after it.
#: Placed *before* an optional ``END``, or after a literal one, this rejects both spellings.
RESERVED_BLOCK_NAMESPACE = r"(?!(?:END\s+)?AC\s)"

#: The invariant-boundary form. The artifact name appears exactly once, at the open, where it is
#: being typed deliberately; the close is a constant token with nothing to recall and nothing to
#: collide with. This is MIME multipart discipline, and it exists because a close delimiter that
#: repeats the name competes with the artifact's own content for the model's attention: the one
#: artifact ever observed to close wrongly was the one whose first heading restated its filename
#: stem. The named form below stays valid and stays checked, so nothing already recorded stops
#: parsing.
ARTIFACT_OPEN_TEMPLATE = "=== BEGIN ARTIFACT {name} ==="
ARTIFACT_CLOSE_TOKEN = "=== END ARTIFACT ==="

_INVARIANT_OPEN_RE = re.compile(
    rf"^===\s*BEGIN\s+ARTIFACT\s+{RESERVED_BLOCK_NAMESPACE}(?P<name>[^\n=]+?)\s*===\s*$"
)
_INVARIANT_END_RE = re.compile(r"^===\s*END\s+ARTIFACT\s*===\s*$")
_OPEN_BLOCK_RE = re.compile(
    rf"^===\s*(?!END\s){RESERVED_BLOCK_NAMESPACE}(?P<name>[^\n=]+?)\s*===\s*$"
)
_END_BLOCK_RE = re.compile(rf"^===\s*END\s+{RESERVED_BLOCK_NAMESPACE}(?P<name>[^\n=]+?)\s*===\s*$")
_WRITE_CALL_RE = re.compile(
    r'<invoke name="Write">\s*'
    r"<parameter name=\"(?:path|file_path)\">(?P<path>.*?)</parameter>\s*"
    r"<parameter name=\"content\">(?P<content>.*?)</parameter>\s*"
    r"</invoke>",
    re.DOTALL,
)
_FUNCTION_WRAPPER_RE = re.compile(r"</?function_calls>\s*")
_IGNORABLE_OUTSIDE_LINE_RE = re.compile(
    r"^(?:Continuing|Next|Proceeding|Writing|Now writing)\b.*$",
    re.IGNORECASE,
)

_RESERVED_NAME_RE = re.compile(r"^(?:END\s+)?AC\s")

#: Stray text is narration a model wraps around intact artifact blocks ("I'll produce the analysis
#: from the injected sources."). It is discarded and reported, never written. Outside text shaped
#: like content — a heading, list, table, fence, JSON, markup, a delimiter, or more than a few
#: lines — still fails the parse, because it may be an artifact body that lost its boundary.
_STRAY_LINE_LIMIT = 3
_STRAY_CHAR_LIMIT = 500
_CONTENT_LINE_RE = re.compile(r"^(?:#|```|~~~|\||[-*+]\s|\d+[.)]\s|[{\[<])")

_OPEN = "open"
_CLOSE = "close"


@dataclass(frozen=True)
class ArtifactDefect:
    """One artifact-scoped parse defect, named so the operator can act on it."""

    name: str
    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name}: {self.reason}"


@dataclass(frozen=True)
class StrayText:
    """Narration found outside the artifact blocks and discarded."""

    where: str
    text: str

    def __str__(self) -> str:
        flat = " ".join(self.text.split())
        quoted = flat if len(flat) <= 200 else flat[:197] + "..."
        return f'stray text {self.where} discarded: "{quoted}"'


def is_stray_text(text: str) -> bool:
    """Whether outside text is short narration rather than content that lost its boundary."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or len(lines) > _STRAY_LINE_LIMIT or sum(map(len, lines)) > _STRAY_CHAR_LIMIT:
        return False
    if "===" in text:
        return False
    return not any(_CONTENT_LINE_RE.match(line) for line in lines)


def stray_reporter(
    on_text: Callable[[str], None] | None, tag: str
) -> Callable[[StrayText], None] | None:
    """Print each discarded stray text as one ``[tag]`` console line."""
    if on_text is None:
        return None
    return lambda stray: on_text(f"[{tag}] {stray}\n")


#: How much of a reply without artifacts the retry quotes back, matching plan's Stage 1 retry.
_RETRY_REPLY_QUOTE_LIMIT = 4000


def carries_no_artifact(text: str) -> bool:
    """Whether a non-empty reply holds no artifact delimiter at all: prose, a question, a refusal.

    Narration around intact artifacts is a parse question. A reply with no artifact is a
    different outcome — the model answered in place of the task — and the only repair is to ask
    again, saying why.
    """
    if not text.strip() or _WRITE_CALL_RE.search(text):
        return False
    delimiters = (_INVARIANT_OPEN_RE, _INVARIANT_END_RE, _OPEN_BLOCK_RE, _END_BLOCK_RE)
    return not any(
        pattern.match(line.strip()) for line in text.splitlines() for pattern in delimiters
    )


def response_excerpt(text: str, limit: int = 240) -> str:
    """One line from the start of a response, for a refusal the console would otherwise hide."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def no_artifact_retry_assembly(
    prompt_assembly: PromptAssembly, *, reply: str, unattended: bool = False
) -> PromptAssembly:
    """The original prompt plus why the reply was refused, for the one corrective call.

    The original parts stay byte-identical so the prefix remains cacheable. Without the appended
    reason a retry is the call that failed and draws the same answer (LayersTesting
    ``20261021.180733``: analyze answered with a question and the run ended).
    """
    quoted = reply.strip()
    if len(quoted) > _RETRY_REPLY_QUOTE_LIMIT:
        quoted = quoted[:_RETRY_REPLY_QUOTE_LIMIT] + " …"
    policy = (
        "No Commander is available, and no prose reply reaches a person."
        if unattended
        else "A prose reply reaches no one. Drydock reads only artifact blocks."
    )
    lines = [
        "# Artifact Retry",
        "",
        "Your previous reply contained no artifact blocks, so Drydock wrote nothing.",
        policy,
        "You have no tools, and nobody answers questions during this run. Do not ask, refuse,",
        "or explain. Resolve each point you raised from the input context, choose the narrowest",
        "reading consistent with it, and record any genuine open point where the Agent Task",
        "routes it.",
        "Reply now with only the artifact blocks the Agent Task requires, in its delimiter form.",
        "",
        "Your previous reply:",
        "",
        quoted,
    ]
    return PromptAssembly(
        parts=(*prompt_assembly.parts, lines_part("Artifact retry", lines, kind="repair"))
    )


def retry_reply_without_artifacts(
    result: R,
    prompt_assembly: PromptAssembly,
    rerun: Callable[[PromptAssembly], R],
    *,
    tag: str,
    on_text: Callable[[str], None] | None = None,
    unattended: bool = False,
) -> R:
    """Return ``result``, or one rerun carrying the refusal reason when its reply held no artifact.

    ``rerun`` executes an assembly exactly as the first call did. A second reply without
    artifacts is returned as is and fails the caller's ordinary parse.
    """
    text = str(getattr(result, "text", "") or "")
    if not getattr(result, "ok", False) or not carries_no_artifact(text):
        return result
    if on_text is not None:
        on_text(
            f"[{tag}] response without artifacts, retrying once with the reason: "
            f'"{response_excerpt(text)}"\n'
        )
    return rerun(no_artifact_retry_assembly(prompt_assembly, reply=text, unattended=unattended))


@dataclass(frozen=True)
class ArtifactParseResult:
    """Accepted artifacts plus the per-artifact defects observed alongside them.

    ``rejected`` names artifacts the parser judged and refused. ``repaired`` names artifacts that
    were accepted despite a defect in their delimiters. Neither costs an artifact the parser did
    not judge — that is P-3: no gate may discard work it did not judge. ``stray`` holds the
    narration discarded from outside the blocks.
    """

    blocks: dict[str, str] = field(default_factory=dict)
    rejected: tuple[ArtifactDefect, ...] = ()
    repaired: tuple[ArtifactDefect, ...] = ()
    stray: tuple[StrayText, ...] = ()

    @property
    def defects(self) -> tuple[ArtifactDefect, ...]:
        return self.repaired + self.rejected


def artifact_open(name: str) -> str:
    """The opening delimiter for ``name``, in the invariant form."""
    return ARTIFACT_OPEN_TEMPLATE.format(name=name)


def wrap_artifact(name: str, body: str) -> str:
    """``body`` enclosed in the invariant boundary, as the parser expects to read it."""
    return f"{artifact_open(name)}\n{body.strip()}\n{ARTIFACT_CLOSE_TOKEN}"


def emission_contract_lines(names: Sequence[str]) -> list[str]:
    """The delimiter grammar, stated for a model, rendered from the constants above.

    A prompt assembled in Python states the grammar the same way a prompt in ``prompts/``
    does, and neither hand-types a delimiter. The rule this exists to enforce: a prompt
    must never demonstrate a boundary syntax it does not want back. A repair prompt that
    wrapped its input in XML tags and asked for a delimited block got XML tags back, and
    the corrected artifact inside them was discarded unread.
    """
    lines = [
        "Emit each artifact below in exactly this form, and emit no other text:",
        "",
        artifact_open("<FILENAME>"),
        "<the complete file body>",
        ARTIFACT_CLOSE_TOKEN,
        "",
        "The filename appears once, in the opening delimiter. The closing delimiter is the",
        "constant token above and never carries a name.",
    ]
    if names:
        lines.extend([
            "",
            "Emit exactly one such block for each of: " + ", ".join(names) + ".",
        ])
    return lines


def parse_artifact_blocks(
    text: str,
    *,
    label: str,
    allowed_names: Iterable[str] | None = None,
    allowed_prefixes: Iterable[str] = (),
    allowed_suffixes: Iterable[str] = (),
    allowed_patterns: Iterable[str | Pattern[str]] = (),
    on_defect: Callable[[ArtifactDefect], None] | None = None,
    on_stray: Callable[[StrayText], None] | None = None,
) -> dict[str, str]:
    """Return artifact-name -> body and reject malformed/noisy model output.

    The accepted format is either the invariant-boundary form::

        === BEGIN ARTIFACT NAME ===
        ...content...
        === END ARTIFACT ===

    or the named-close form::

        === NAME ===
        ...content...
        === END NAME ===

    Short narration outside the blocks is discarded and reported through ``on_stray``; any other
    outside text fails the parse. A later block with the same filename replaces its earlier
    draft. A block whose name is not allowed is rejected individually: the caller receives
    every artifact the parser did accept, and states for itself which artifacts it required.
    Defects are reported through ``on_defect``.
    """
    result = parse_artifact_report(
        text,
        label=label,
        allowed_names=allowed_names,
        allowed_prefixes=allowed_prefixes,
        allowed_suffixes=allowed_suffixes,
        allowed_patterns=allowed_patterns,
    )
    if on_defect is not None:
        for defect in result.defects:
            on_defect(defect)
    if on_stray is not None:
        for stray in result.stray:
            on_stray(stray)
    return result.blocks


def parse_artifact_report(
    text: str,
    *,
    label: str,
    allowed_names: Iterable[str] | None = None,
    allowed_prefixes: Iterable[str] = (),
    allowed_suffixes: Iterable[str] = (),
    allowed_patterns: Iterable[str | Pattern[str]] = (),
) -> ArtifactParseResult:
    """Parse artifact blocks and return the accepted set alongside its per-artifact defects."""
    allowed_set = set(allowed_names or ())
    prefixes = tuple(allowed_prefixes)
    suffixes = tuple(allowed_suffixes)
    patterns = tuple(
        re.compile(pattern) if isinstance(pattern, str) else pattern for pattern in allowed_patterns
    )
    text = _repair_missing_leading_delimiter(text)
    transcript_blocks = _parse_write_call_blocks(
        text,
        label=label,
        allowed_names=allowed_set,
        allowed_prefixes=prefixes,
        allowed_suffixes=suffixes,
        allowed_patterns=patterns,
        strict=False,
    )
    if transcript_blocks:
        return ArtifactParseResult(blocks=transcript_blocks)
    parsed = _parse_delimited_blocks(text, label=label)
    if not parsed.blocks:
        transcript_blocks = _parse_write_call_blocks(
            text,
            label=label,
            allowed_names=allowed_set,
            allowed_prefixes=prefixes,
            allowed_suffixes=suffixes,
            allowed_patterns=patterns,
            strict=True,
        )
        if transcript_blocks:
            return ArtifactParseResult(blocks=transcript_blocks)
        if parsed.rejected:
            return parsed
        if text.strip():
            raise _outside_text_error(label, text, where="with no artifact block")
        raise DrydockError(
            f"{label} failed: LLM output did not contain any delimited artifact blocks.\n"
            "  No generated artifacts were written."
        )
    accepted: dict[str, str] = {}
    rejected = list(parsed.rejected)
    for name, body in parsed.blocks.items():
        if _is_allowed(name, allowed_set, prefixes, suffixes, patterns):
            accepted[name] = body
            continue
        rejected.append(
            ArtifactDefect(name=name, reason="not an artifact this command emits; block discarded")
        )
    return ArtifactParseResult(
        blocks=accepted, rejected=tuple(rejected), repaired=parsed.repaired, stray=parsed.stray
    )


@dataclass(frozen=True)
class DelimiterPairing:
    """Which artifacts opened, and which of them reached a close, under either boundary grammar.

    Several checks elsewhere in the codebase ask a structural question of the raw response —
    *did everything that opened also close?* — rather than of the parsed blocks. Counting names
    with the named-close regex answers that question wrongly the moment an artifact closes with
    the invariant ``=== END ARTIFACT ===`` token, because the close carries no name to count:
    every artifact reads as unclosed and every close reads as an orphan. Pairing is therefore
    computed once, by walking the delimiters in order, and shared.

    ``closed`` lists the names that opened and closed, in the order they closed, including
    repeated drafts of the same filename. ``unclosed`` lists the names that opened and did
    not, which is the tail a truncated response leaves behind. ``orphan_closes`` lists named
    closes that arrived with nothing open — the signature of a dropped opening delimiter. An
    invariant close names nothing, so it can never appear there. ``premature_closes`` lists the
    artifact that closed last when content and then an invariant close followed with nothing
    open: the model wrote the close token inside the body, so the parsed body lost its tail
    (FxRates ``20261024.183153`` dropped ``FEATURE-CLI-Load.md``'s Guardrails this way).
    """

    closed: tuple[str, ...] = ()
    unclosed: tuple[str, ...] = ()
    orphan_closes: tuple[str, ...] = ()
    premature_closes: tuple[str, ...] = ()

    @property
    def opened(self) -> tuple[str, ...]:
        """Every name that opened a block, closed or not."""
        return self.closed + self.unclosed


def pair_artifact_delimiters(text: str) -> DelimiterPairing:
    """Pair artifact delimiters by position, in whichever boundary grammar they are written.

    Mirrors :func:`_parse_delimited_blocks` rather than re-deriving the rules: an open with a
    block already open closes nothing and leaves that block unclosed; a close terminates the open
    block whether or not it names it (§30.2); a name-mismatched close followed by real content is
    a transposed boundary and opens the artifact it names. A close with nothing open pairs with
    nothing and is left to the parser, which owns recovering the dropped opener.
    """
    closed: list[str] = []
    unclosed: list[str] = []
    orphan_closes: list[str] = []
    premature_closes: list[str] = []
    current: str | None = None
    # The artifact closed last, and whether non-blank content has followed its close.
    last_closed: str | None = None
    content_after_close = False

    lines = text.splitlines()
    for index, line in enumerate(lines):
        classified = _classify(line)
        if classified is None:
            if current is None and line.strip():
                content_after_close = True
            continue
        kind, marker_name = classified
        if kind == _OPEN:
            if current is not None:
                unclosed.append(current)
            assert marker_name is not None
            current = marker_name
            last_closed = None
            continue
        if current is None:
            if marker_name is not None:
                orphan_closes.append(marker_name)
            elif last_closed is not None and content_after_close:
                premature_closes.append(last_closed)
                last_closed = None
            continue
        closed.append(current)
        last_closed = current
        content_after_close = False
        if marker_name is None or marker_name == current:
            current = None
        elif _closes_the_open_block(lines, index=index):
            current = None
        else:
            current = marker_name

    if current is not None:
        unclosed.append(current)
    return DelimiterPairing(
        closed=tuple(closed),
        unclosed=tuple(unclosed),
        orphan_closes=tuple(orphan_closes),
        premature_closes=tuple(premature_closes),
    )


def _classify(line: str) -> tuple[str, str | None] | None:
    """Return ``(kind, name)`` for a delimiter line, or ``None`` for content.

    The invariant forms are tested first: ``=== END ARTIFACT ===`` also matches the named-close
    grammar with the name ``ARTIFACT``, and ``=== BEGIN ARTIFACT X ===`` also matches the open
    grammar with the name ``BEGIN ARTIFACT X``.

    ``RESERVED_BLOCK_NAMESPACE`` is re-checked against the extracted name because the patterns
    lead with ``\\s*``, which backtracks to empty and lets the guard read the leading space
    instead of the name. The reserved namespace is what keeps the nested ``=== AC <id> ===``
    proof protocol out of the envelope grammar, so it is enforced where it cannot be evaded.
    """
    stripped = line.strip()
    if _INVARIANT_END_RE.match(stripped):
        return (_CLOSE, None)
    invariant_open = _INVARIANT_OPEN_RE.match(stripped)
    if invariant_open:
        return _guarded(_OPEN, invariant_open.group("name"))
    end_match = _END_BLOCK_RE.match(stripped)
    if end_match:
        return _guarded(_CLOSE, end_match.group("name"))
    open_match = _OPEN_BLOCK_RE.match(stripped)
    if open_match:
        return _guarded(_OPEN, open_match.group("name"))
    return None


def envelope_spans(text: str) -> tuple[tuple[bool, str], ...]:
    """Split intact envelopes into body/boundary spans and outside spans, without rewriting.

    Ambiguous boundaries must reach the owning parser unchanged for its recovery policy.
    """
    spans: list[tuple[bool, str]] = []
    current: str | None = None
    seen: set[str] = set()
    for line in text.splitlines(keepends=True):
        marker = _classify(line)
        inside = current is not None
        if marker is not None:
            kind, name = marker
            if kind == _OPEN:
                if current is not None:
                    raise ValueError("nested artifact opener")
                assert name is not None
                seen.add(name)
                current = name
            else:
                if current is None or (name is not None and name != current):
                    raise ValueError("orphan or mismatched artifact close")
                current = None
            inside = True
        if spans and spans[-1][0] == inside:
            spans[-1] = (inside, spans[-1][1] + line)
        else:
            spans.append((inside, line))
    if current is not None or not seen:
        raise ValueError("incomplete or missing artifact envelope")
    return tuple(spans)


def repair_final_artifact_close(text: str) -> tuple[str, tuple[str, ...]]:
    """Complete only the observed invariant close missing its trailing equals at EOF.

    A candidate must have entirely unambiguous envelopes. Missing closes and nested
    openers and conflicting closes remain the caller's validation/retry responsibility.
    """
    lines = text.splitlines(keepends=True)
    index = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    if index is None or lines[index].strip() != "=== END ARTIFACT":
        return text, ()
    if sum(line.strip() == "=== END ARTIFACT" for line in lines) != 1:
        return text, ()
    pairing = pair_artifact_delimiters(text)
    if len(pairing.unclosed) != 1:
        return text, ()
    name = pairing.unclosed[0]
    lines[index] = lines[index].replace("=== END ARTIFACT", ARTIFACT_CLOSE_TOKEN, 1)
    candidate = "".join(lines)
    try:
        envelope_spans(candidate)
    except ValueError:
        return text, ()
    return candidate, (f"{name}: completed final `=== END ARTIFACT` as `{ARTIFACT_CLOSE_TOKEN}`",)


def _guarded(kind: str, raw_name: str) -> tuple[str, str | None] | None:
    name = raw_name.strip()
    if _RESERVED_NAME_RE.match(name):
        return None
    return (kind, name)


def _has_later_opening_delimiter(lines: list[str], *, index: int, name: str) -> bool:
    for later_line in lines[index + 1 :]:
        classified = _classify(later_line)
        if classified and classified[0] == _OPEN and classified[1] == name:
            return True
    return False


def _closes_the_open_block(lines: list[str], *, index: int) -> bool:
    """Whether a name-mismatched close terminates the open block rather than starting a new one.

    The same line spells two different accidents. ``=== END next ===`` written in place of
    ``=== END current ===`` plus ``=== next ===`` is a *transposed boundary*: real content follows
    it and belongs to ``next``. ``=== END COMPASS ===`` written in place of
    ``=== END COMPASS.md ===`` is a *misnamed close*: nothing follows it but the next artifact's
    opener, or the end of the response.

    Position separates them, which is the only thing that can: the close's name is a checksum on
    the open, and fuzzy-matching the two would throw away the property that makes an unclosed
    container detectable at all.
    """
    for later_line in lines[index + 1 :]:
        if not later_line.strip():
            continue
        if _classify(later_line) is not None:
            return True
        return False
    return True


def _parse_delimited_blocks(text: str, *, label: str) -> ArtifactParseResult:
    blocks: dict[str, str] = {}
    rejected: list[ArtifactDefect] = []
    repaired: list[ArtifactDefect] = []
    current_name: str | None = None
    current_body: list[str] = []
    outside: list[str] = []
    stray: list[StrayText] = []
    orphan_close_outside = False
    saw_delimiter = False

    def discard_stray(where: str, *, after_artifacts: bool) -> None:
        """Keep narration out of the artifacts; fail on outside text that may be content."""
        chunk = "".join(outside)
        if not orphan_close_outside and is_stray_text(chunk):
            stray.append(StrayText(where=where, text=chunk.strip()))
            return
        raise _outside_text_error(label, chunk, where=where, after_artifacts=after_artifacts)

    def record(name: str) -> None:
        """A later body replaces the earlier draft of the same file."""
        blocks[name] = "".join(current_body).strip()

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        classified = _classify(line)
        kind = classified[0] if classified else None
        marker_name = classified[1] if classified else None

        if current_name is None:
            if kind == _CLOSE and marker_name is None:
                # An invariant close with nothing open names no artifact and can open nothing.
                # Text beside it may be a body whose opener was dropped, so it is never stray.
                orphan_close_outside = True
                continue
            if (
                kind == _CLOSE
                and marker_name is not None
                and not blocks
                and _outside_has_text(outside)
            ):
                if any("===" in chunk for chunk in outside):
                    raise _outside_text_error(
                        label, "".join(outside), where="before the first artifact block"
                    )
                current_name = marker_name
                current_body = outside
                outside = []
                record(current_name)
                current_name = None
                current_body = []
                saw_delimiter = True
                continue
            orphan_opener = (
                kind == _CLOSE
                and marker_name is not None
                and saw_delimiter
                and not _outside_has_text(outside, after_artifacts=True)
                and not _has_later_opening_delimiter(lines, index=index, name=marker_name)
            )
            if kind == _OPEN or orphan_opener:
                if _outside_has_text(outside, after_artifacts=saw_delimiter):
                    discard_stray(
                        "between artifact blocks"
                        if saw_delimiter
                        else "before the first artifact block",
                        after_artifacts=saw_delimiter,
                    )
                # An END delimiter with no block open cannot close anything: the model dropped
                # the opener, and the block runs to the delimiter that closes it.
                assert marker_name is not None
                current_name = marker_name
                current_body = []
                outside = []
                orphan_close_outside = False
                saw_delimiter = True
                continue
            outside.append(line)
            continue

        if kind == _CLOSE and (marker_name is None or marker_name == current_name):
            record(current_name)
            current_name = None
            current_body = []
            saw_delimiter = True
            continue

        if kind == _CLOSE and _closes_the_open_block(lines, index=index):
            # §30.2 — recognise the close by position and report the name disagreement, rather
            # than inventing a block named after the marker. The old parser read this line as an
            # opener, then failed the allow-list on a block the model never opened, which named
            # the wrong artifact and said nothing about the one that was actually wrong.
            repaired.append(
                ArtifactDefect(
                    name=current_name,
                    reason=(
                        f"closed by `{line.strip()}` rather than "
                        f"`=== END {current_name} ===`; accepted by position"
                    ),
                )
            )
            record(current_name)
            current_name = None
            current_body = []
            saw_delimiter = True
            continue

        transposed = (
            kind == _CLOSE
            and marker_name is not None
            and not _has_later_opening_delimiter(lines, index=index, name=marker_name)
        )
        if kind == _OPEN or transposed:
            # Recover when the model omits an END delimiter between otherwise well-formed
            # artifact blocks, or transposes it onto the next artifact (`=== END next ===` in
            # place of `=== END current ===` plus the opener). A delimiter cannot be content
            # under the artifact protocol, so it closes the current block and starts the next.
            # A later opener for the same name means the model restarted the artifact instead:
            # that stays ambiguous and remains body text.
            assert marker_name is not None
            record(current_name)
            current_name = marker_name
            current_body = []
            saw_delimiter = True
            continue
        current_body.append(line)

    if current_name is not None:
        if current_name in blocks:
            blocks.pop(current_name)
            rejected.append(
                ArtifactDefect(current_name, "final update is unclosed; block discarded")
            )
        else:
            record(current_name)
        saw_delimiter = True

    if _outside_has_text(outside, after_artifacts=saw_delimiter):
        if saw_delimiter:
            discard_stray("after the last artifact block", after_artifacts=True)
        else:
            raise _outside_text_error(
                label, "".join(outside), where="with no artifact block", after_artifacts=False
            )
    if not saw_delimiter:
        blocks = {}
    return ArtifactParseResult(
        blocks=blocks, rejected=tuple(rejected), repaired=tuple(repaired), stray=tuple(stray)
    )


def _repair_missing_leading_delimiter(text: str) -> str:
    if not text or text.lstrip().startswith("==="):
        return text
    lines = text.splitlines(keepends=True)
    outside: list[str] = []
    for index, line in enumerate(lines):
        classified = _classify(line)
        if classified is not None and classified[0] == _CLOSE:
            name = classified[1]
            if name is None:
                # The invariant close carries no name, so the dropped opener cannot be recovered.
                return text
            if not _outside_has_text(outside):
                return text
            if any("===" in chunk for chunk in outside):
                return text
            leading_body = "".join(outside).rstrip("\n")
            remainder = "".join(lines[index + 1 :])
            if f"=== {name} ===" in remainder:
                return text
            repaired = f"=== {name} ===\n{leading_body}\n=== END {name} ==="
            return repaired + (
                "\n" + remainder if remainder and not remainder.startswith("\n") else remainder
            )
        if classified is not None:
            return text
        outside.append(line)
    return text


def _parse_write_call_blocks(
    text: str,
    *,
    label: str,
    allowed_names: set[str],
    allowed_prefixes: tuple[str, ...],
    allowed_suffixes: tuple[str, ...],
    allowed_patterns: tuple[Pattern[str], ...],
    strict: bool,
) -> dict[str, str]:
    blocks: dict[str, str] = {}
    cursor = 0
    saw_write = False
    for match in _WRITE_CALL_RE.finditer(text):
        outside = text[cursor : match.start()]
        if _outside_text_in_write_transcript(outside, after_artifacts=saw_write):
            if strict:
                raise _outside_text_error(
                    label,
                    _FUNCTION_WRAPPER_RE.sub("", outside),
                    where="between artifact blocks"
                    if saw_write
                    else "before the first artifact block",
                    after_artifacts=saw_write,
                )
            return {}
        raw_path = match.group("path").strip().replace("\\", "/")
        name = PurePath(raw_path).name
        if not _is_allowed(
            name, allowed_names, allowed_prefixes, allowed_suffixes, allowed_patterns
        ):
            if strict:
                raise DrydockError(
                    f"{label} failed: LLM output contained an unexpected artifact block: {name}\n"
                    "  No generated artifacts were written."
                )
            return {}
        if name in blocks:
            if strict:
                raise DrydockError(
                    f"{label} failed: LLM output did not satisfy the artifact contract.\n"
                    f"  Duplicate artifact block: {name}\n"
                    "  No generated artifacts were written."
                )
            return {}
        blocks[name] = match.group("content").strip()
        cursor = match.end()
        saw_write = True
    if not saw_write:
        return {}
    if _outside_text_in_write_transcript(text[cursor:], after_artifacts=saw_write):
        if strict:
            raise _outside_text_error(
                label,
                _FUNCTION_WRAPPER_RE.sub("", text[cursor:]),
                where="after the last artifact block",
                after_artifacts=saw_write,
            )
        return {}
    return blocks


def _outside_has_text(chunks: list[str], *, after_artifacts: bool = False) -> bool:
    return _has_substantive_outside_text("".join(chunks), after_artifacts=after_artifacts)


def _outside_text_in_write_transcript(text: str, *, after_artifacts: bool) -> bool:
    stripped = _FUNCTION_WRAPPER_RE.sub("", text)
    return _has_substantive_outside_text(stripped, after_artifacts=after_artifacts)


def _has_substantive_outside_text(text: str, *, after_artifacts: bool) -> bool:
    return _first_stray_line(text, after_artifacts=after_artifacts) is not None


def _first_stray_line(text: str, *, after_artifacts: bool) -> str | None:
    """Return the first outside line the contract rejects, or ``None`` when there is none."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if after_artifacts and _IGNORABLE_OUTSIDE_LINE_RE.match(stripped):
            continue
        return stripped
    return None


def _outside_text_error(
    label: str, outside: str = "", *, where: str = "", after_artifacts: bool = False
) -> DrydockError:
    # Name where the stray text sits and quote its first line, so the operator can see the
    # violation without opening the model output.
    stray = _first_stray_line(outside, after_artifacts=after_artifacts)
    detail = ""
    if stray is not None:
        quoted = stray if len(stray) <= 120 else stray[:117] + "..."
        detail = f"  Stray text {where}: {quoted!r}\n" if where else f"  Stray text: {quoted!r}\n"
    return DrydockError(
        f"{label} failed: LLM output did not satisfy the artifact contract.\n"
        "  Text appeared outside delimited artifact blocks.\n"
        f"{detail}"
        "  No generated artifacts were written."
    )


def _is_allowed(
    name: str,
    allowed_names: set[str],
    allowed_prefixes: tuple[str, ...],
    allowed_suffixes: tuple[str, ...],
    allowed_patterns: tuple[Pattern[str], ...],
) -> bool:
    if allowed_names and name in allowed_names:
        return True
    if any(name.startswith(prefix) for prefix in allowed_prefixes):
        return True
    if any(name.endswith(suffix) for suffix in allowed_suffixes):
        return True
    if any(pattern.fullmatch(name) for pattern in allowed_patterns):
        return True
    return (
        not allowed_names and not allowed_prefixes and not allowed_suffixes and not allowed_patterns
    )
