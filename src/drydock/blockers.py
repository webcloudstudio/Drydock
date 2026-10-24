"""``BLOCKERS.md`` — the one file that blocks a Target.

Drydock writes the file; a model supplies only blocker titles and questions. One command owns
it: while it exists only that owner may run, so a second owner cannot arise. Two kinds of
blocker exist. An *environmental* blocker records a provider failure another call cannot fix,
or a halted UAT stage. A *decision* blocker asks the Commander a question whose answer the
owner's prompt takes as its primary instruction on the rerun; only ``analyze`` and ``refit``
may raise one, and :func:`write_blockers` enforces that.

``ERRORS.md`` stays the record of the last failure and blocks nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

BLOCKERS_FILENAME = "BLOCKERS.md"
ARCHIVE_RELATIVE = Path("logs") / "blockers.md"

ENVIRONMENTAL = "environmental"
DECISION = "decision"

RATE_LIMIT = "provider rate limit"
AUTHENTICATION = "provider authentication required"
TIMEOUT = "provider timeout"
OUTAGE = "provider outage"
UNAVAILABLE = "provider unavailable"
INVALID_MODEL = "invalid model"
UAT_STAGE = "uat stage"
ENVIRONMENTAL_CLASSES = (
    RATE_LIMIT,
    AUTHENTICATION,
    TIMEOUT,
    OUTAGE,
    UNAVAILABLE,
    INVALID_MODEL,
    UAT_STAGE,
)

#: Owners whose prompt takes a Commander Resolution, and so may raise a decision blocker.
DECISION_OWNERS = frozenset({"analyze", "refit"})

#: Batch reruns of the owner stop after this many attempts at the same environmental class.
MAX_ATTEMPTS = 2

#: ``(file summary, blocker title)`` per environmental class.
_TITLES = {
    RATE_LIMIT: ("Rate Limit Hit", "Provider usage limit"),
    AUTHENTICATION: ("Login Required", "Provider login expired"),
    TIMEOUT: ("Provider Timeout", "Provider call timed out"),
    OUTAGE: ("Provider Outage", "Provider unavailable or overloaded"),
    UNAVAILABLE: ("Provider CLI Unavailable", "Provider CLI could not start"),
    INVALID_MODEL: ("Invalid Model", "Model not allowed for the provider"),
}

_RESOLUTION_HEADING = "Commander Resolution"
_SECTION_HEADINGS = ("Error", "Question", _RESOLUTION_HEADING)
_HEADER_RE = re.compile(r"^#\s+Blockers:\s*(?P<summary>.*?)\s*$", re.MULTILINE)
_FIELD_RE = re.compile(r"^-\s+(?P<key>[A-Za-z-]+):\s*(?P<value>.*?)\s*$")
_BLOCKER_RE = re.compile(
    r"^##\s+(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*(?P<title>.*?)\s*$\n?(?P<body>.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADER_FIELDS = frozenset({"target", "source", "owner", "declared", "execution", "attempts"})
_BLOCKER_FIELDS = frozenset({"kind", "class", "auto-continue"})
_CLOCK_RE = re.compile(
    r"(?:try again|retry|reset[s]?)\s+(?:at\s+|after\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>[ap]\.?m\.?)?",
    re.IGNORECASE,
)
_RELATIVE_RE = re.compile(
    r"(?:try again|retry|reset[s]?)\s+(?:after\s+|in\s+)"
    r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>s|sec|secs|seconds?|m|min|mins|minutes?|h|hours?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Blocker:
    """One reason the Target cannot proceed."""

    blocker_id: str
    title: str
    kind: str
    blocker_class: str = ""
    auto_continue: str = ""
    error: str = ""
    question: str = ""
    resolution: str = ""

    @property
    def environmental(self) -> bool:
        return self.kind == ENVIRONMENTAL


@dataclass(frozen=True)
class Blockers:
    """The parsed file: its header and its blockers."""

    summary: str
    target: str
    source: str
    owner: str
    declared: str = ""
    execution: str = ""
    attempts: int = 1
    blockers: tuple[Blocker, ...] = field(default_factory=tuple)

    @property
    def owner_verb(self) -> str:
        return self.owner.split()[0] if self.owner else ""

    def environmental(self) -> tuple[Blocker, ...]:
        return tuple(item for item in self.blockers if item.environmental)

    def decisions(self) -> tuple[Blocker, ...]:
        return tuple(item for item in self.blockers if not item.environmental)

    def resolutions(self) -> tuple[Blocker, ...]:
        return tuple(item for item in self.blockers if item.resolution)

    def rerun_tokens(self) -> list[str]:
        """The owner's recorded invocation, as ``drydock`` arguments."""
        import shlex

        tokens = shlex.split(self.source)
        return tokens[1:] if tokens and tokens[0] == "drydock" else tokens

    def halt(self) -> tuple[str, str]:
        """``(stage, reason)`` of the first environmental blocker, for one-line reports."""
        first = (self.environmental() or self.blockers or (None,))[0]
        if first is None:
            return self.owner or "unknown", self.summary
        if first.blocker_class == UAT_STAGE:
            return first.title, first.error
        stage = " ".join(self.owner.split()[:-1]) or self.owner or "unknown"
        detail = first.error or first.question or first.title
        reason = f"{first.blocker_class}: {detail}" if first.blocker_class else detail
        if self.execution:
            reason += f" (execution {self.execution})"
        return stage, reason

    def line(self) -> str:
        stage, reason = self.halt()
        return f"{stage}: {reason}"


def blockers_path(target_dir: Path) -> Path:
    return target_dir / BLOCKERS_FILENAME


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def environmental_blocker(
    blocker_class: str, error: str, *, declared: str, title: str = ""
) -> Blocker:
    """The blocker for a fatal provider failure or a halted UAT stage."""
    default_title = _TITLES.get(blocker_class, ("", blocker_class))[1]
    return Blocker(
        "blocker-001",
        title or default_title,
        ENVIRONMENTAL,
        blocker_class=blocker_class,
        auto_continue=auto_continue_for(blocker_class, error, declared),
        error=error.strip(),
    )


def summary_for(blocker_class: str) -> str:
    return _TITLES.get(blocker_class, (blocker_class.title(),))[0]


def auto_continue_for(blocker_class: str, error: str, declared: str) -> str:
    """``yes``, ``after HH:MM`` (local), or ``no``.

    A timeout or an outage may continue at once. A rate limit may continue only after the reset
    its message states. An expired login, an invalid model, an unrunnable CLI, and a halted UAT
    stage never continue on their own.
    """
    if blocker_class in {TIMEOUT, OUTAGE}:
        return "yes"
    if blocker_class == RATE_LIMIT:
        reset = reset_clock(error, _parse_declared(declared))
        return f"after {reset}" if reset else "no"
    return "no"


def reset_clock(message: str, declared: datetime | None) -> str | None:
    """The local ``HH:MM`` a rate-limit message says the limit resets, or ``None``."""
    if match := _RELATIVE_RE.search(message):
        if declared is None:
            return None
        amount = float(match.group("amount"))
        unit = match.group("unit").lower()
        seconds = amount * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
        reset = declared.astimezone() + timedelta(seconds=seconds)
        reset += timedelta(seconds=(60 - reset.second) % 60)
        return reset.strftime("%H:%M")
    if match := _CLOCK_RE.search(message):
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        meridiem = (match.group("meridiem") or "").lower().replace(".", "")
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if hour < 24 and minute < 60:
            return f"{hour:02d}:{minute:02d}"
    return None


def _parse_declared(declared: str) -> datetime | None:
    try:
        return datetime.strptime(declared, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def may_auto_continue(blocker: Blocker, declared: str, now: datetime | None = None) -> bool:
    """Whether an unattended owner rerun may proceed past this environmental blocker."""
    if not blocker.environmental:
        return False
    value = blocker.auto_continue.strip().lower()
    if value == "yes":
        return True
    match = re.fullmatch(r"after\s+(\d{1,2}):(\d{2})", value)
    declared_at = _parse_declared(declared)
    if match is None or declared_at is None:
        return False
    local_declared = declared_at.astimezone()
    reset = local_declared.replace(
        hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0
    )
    if reset < local_declared:
        reset += timedelta(days=1)
    current = (now or datetime.now(UTC)).astimezone()
    return current >= reset


def batch_may_run_owner(blockers: Blockers, now: datetime | None = None) -> bool:
    """Whether the owner may rerun without a terminal.

    Every decision blocker carries a Commander Resolution, every environmental blocker may
    auto-continue, and environmental retries have not reached :data:`MAX_ATTEMPTS`.
    """
    if any(not item.resolution for item in blockers.decisions()):
        return False
    environmental = blockers.environmental()
    if not environmental:
        return True
    if blockers.attempts >= MAX_ATTEMPTS:
        return False
    return all(may_auto_continue(item, blockers.declared, now) for item in environmental)


def render_blockers(blockers: Blockers) -> str:
    """The file text. Drydock is its only writer."""
    lines = [
        f"# Blockers: {blockers.summary}",
        f"- target: {blockers.target}",
        f"- source: {blockers.source}",
        f"- owner: {blockers.owner}",
        f"- declared: {blockers.declared}",
        f"- execution: {blockers.execution}",
        f"- attempts: {blockers.attempts}",
    ]
    for item in blockers.blockers:
        lines += ["", f"## {item.blocker_id}: {item.title}", f"- kind: {item.kind}"]
        if item.environmental:
            lines += [f"- class: {item.blocker_class}", f"- auto-continue: {item.auto_continue}"]
            lines += ["### Error", item.error.strip()]
        else:
            lines += ["### Question", item.question.strip()]
        lines += [f"### {_RESOLUTION_HEADING}"]
        if item.resolution.strip():
            lines.append(item.resolution.strip())
    return "\n".join(lines).rstrip() + "\n"


def write_blockers(target_dir: Path, blockers: Blockers) -> Path:
    """Write the Target's ``BLOCKERS.md``; refuse a decision blocker from a non-decision owner."""
    if blockers.decisions() and blockers.owner_verb not in DECISION_OWNERS:
        raise ValueError(
            f"{blockers.owner or 'an unnamed owner'} may not raise a decision blocker; only "
            f"{', '.join(sorted(DECISION_OWNERS))} take a Commander Resolution"
        )
    unknown = [
        item.blocker_class
        for item in blockers.environmental()
        if item.blocker_class not in ENVIRONMENTAL_CLASSES
    ]
    if unknown:
        raise ValueError(f"unknown environmental blocker class: {unknown[0]}")
    numbered = blockers.blockers
    if len({item.blocker_id for item in numbered}) != len(numbered):
        # Merged lists (a provider failure over standing decisions) renumber; others keep ids.
        numbered = tuple(
            replace(item, blocker_id=f"blocker-{index:03d}")
            for index, item in enumerate(numbered, start=1)
        )
    path = blockers_path(target_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_blockers(replace(blockers, blockers=numbered)), encoding="utf-8", newline="\n"
    )
    return path


def parse_blockers(text: str) -> Blockers:
    """Parse file text. Missing header fields read as empty; a blocker with no kind is a decision."""
    header_match = _HEADER_RE.search(text)
    first_blocker = re.search(r"^##\s", text, re.MULTILINE)
    header_text = text[: first_blocker.start()] if first_blocker else text
    fields: dict[str, str] = {}
    for line in header_text.splitlines():
        match = _FIELD_RE.match(line)
        if match and match.group("key").lower() in _HEADER_FIELDS:
            fields[match.group("key").lower()] = match.group("value")
    try:
        attempts = max(1, int(fields.get("attempts", "1")))
    except ValueError:
        attempts = 1
    items = [_parse_blocker(match) for match in _BLOCKER_RE.finditer(text)]
    return Blockers(
        summary=header_match.group("summary") if header_match else "",
        target=fields.get("target", ""),
        source=fields.get("source", ""),
        owner=fields.get("owner", ""),
        declared=fields.get("declared", ""),
        execution=fields.get("execution", ""),
        attempts=attempts,
        blockers=tuple(items),
    )


def _parse_blocker(match: re.Match[str]) -> Blocker:
    fields: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    section = ""
    for line in match.group("body").splitlines():
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading and heading.group(1) in _SECTION_HEADINGS:
            section = heading.group(1)
            sections.setdefault(section, [])
        elif section:
            sections[section].append(line)
        elif (field_match := _FIELD_RE.match(line)) and (
            field_match.group("key").lower() in _BLOCKER_FIELDS
        ):
            fields[field_match.group("key").lower()] = field_match.group("value")
        elif line.strip():
            # Free text before any subsection is the question of a model-written decision.
            sections.setdefault("Question", []).append(line)

    def text_of(name: str) -> str:
        return _COMMENT_RE.sub("", "\n".join(sections.get(name, []))).strip()

    kind = fields.get("kind", DECISION).split()[0].lower() if fields.get("kind") else DECISION
    return Blocker(
        blocker_id=match.group("id"),
        title=match.group("title").strip(),
        kind=ENVIRONMENTAL if kind == ENVIRONMENTAL else DECISION,
        blocker_class=fields.get("class", ""),
        auto_continue=fields.get("auto-continue", ""),
        error=text_of("Error"),
        question=text_of("Question"),
        resolution=text_of(_RESOLUTION_HEADING),
    )


def read_blockers(target_dir: Path) -> Blockers | None:
    """The Target's blockers, or ``None`` when it is not blocked."""
    path = blockers_path(target_dir)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        # An unreadable file still blocks: reporting "not blocked" is the one wrong answer.
        return Blockers(
            f"{BLOCKERS_FILENAME} exists but could not be read", target_dir.name, "", ""
        )
    return parse_blockers(text)


def clear_blockers(target_dir: Path) -> None:
    try:
        blockers_path(target_dir).unlink()
    except FileNotFoundError:
        pass


def clear_environmental(target_dir: Path) -> Blockers | None:
    """Drop environmental blockers; delete the file when none remain. Returns what is left."""
    current = read_blockers(target_dir)
    if current is None or not current.environmental():
        return current
    remaining = current.decisions()
    if not remaining:
        clear_blockers(target_dir)
        return None
    kept = replace(current, blockers=remaining, attempts=1)
    write_blockers(target_dir, kept)
    return kept


def archive_blockers(target_dir: Path, text: str, *, archived_on: str) -> Path:
    """Append a resolved file to the Target's blocker archive."""
    path = target_dir / ARCHIVE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Resolved Blockers\n"
    entry = f"\n## Archived {archived_on}\n\n```markdown\n{text.strip()}\n```\n"
    path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8", newline="\n")
    return path


def primary_instruction(blockers: Blockers) -> str:
    """The Commander Resolutions as the owner rerun's primary instruction, or ``""``."""
    resolved = blockers.resolutions()
    if not resolved:
        return ""
    lines = [
        "# Commander Resolution — primary instruction",
        "",
        f"The Commander resolved the blockers that stopped `{blockers.owner}`. Follow these "
        "resolutions ahead of every other instruction in this prompt.",
    ]
    for item in resolved:
        lines += ["", f"## {item.blocker_id}: {item.title}", "", item.resolution.strip()]
    return "\n".join(lines) + "\n\n"


def render_banner(blockers: Blockers, target: str = "", recovery: str = "") -> str:
    """The standard console banner: what blocks the Target, and the way back."""
    border = "=" * 72
    heading = f"BLOCKED{f': {target}' if target else ''}  ·  {blockers.owner or 'no owner'}"
    if blockers.declared:
        heading += f"  ·  {blockers.declared}"
    lines = [border, heading, border, "", f"  {blockers.summary}"]
    for item in blockers.blockers:
        detail = (
            f"{item.kind} · {item.blocker_class} · auto-continue {item.auto_continue}"
            if item.environmental
            else item.kind
        )
        lines += ["", f"  {item.blocker_id}: {item.title}  [{detail}]"]
        body = item.error if item.environmental else item.question
        lines += [f"    {line}" for line in body.splitlines() if line.strip()]
        if item.resolution:
            lines += ["    Commander Resolution:"]
            lines += [f"      {line}" for line in item.resolution.splitlines() if line.strip()]
    if recovery:
        lines += ["", "  Recovery", *(f"    {line.strip()}" for line in recovery.splitlines())]
    if blockers.source:
        lines += ["", f"  Owner rerun: {blockers.source}"]
    if blockers.environmental():
        lines += [f"  Attempts: {blockers.attempts}"]
    lines.append(border)
    return "\n".join(lines)


def render_refusal(target_dir: Path, command: str, recovery: str = "") -> str:
    """Why ``command`` will not run: the banner, the file verbatim, and how to remove it."""
    path = blockers_path(target_dir)
    blockers = read_blockers(target_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        text = f"(unreadable: {exc})"
    lines = [
        f"{command} refused: {target_dir.name} is blocked.",
        "",
        render_banner(blockers, target_dir.name, recovery) if blockers is not None else "",
        "",
        f"Contents of {path}:",
        "",
        *(f"  {line}".rstrip() for line in text.splitlines()),
        "",
        "To continue, answer each Commander Resolution and rerun the owner",
        f"({blockers.source if blockers and blockers.source else 'the owning command'}),"
        " or remove the file:",
        f"  rm '{path}'",
    ]
    return "\n".join(lines)
