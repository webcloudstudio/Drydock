"""Structured project-level acceptance criteria stored in ``SEA_TRIALS.md``."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import SpecificationError

TRIAL_TYPES = frozenset({"technical", "behavioral", "qualitative", "outcome", "guardrail"})
VERIFICATION_TYPES = frozenset({"proof", "measurement", "evidence", "llm"})
DETERMINISTIC_VERIFICATION = frozenset({"proof", "measurement"})

#: Types whose Criterion is an assertion and therefore carries an EARS Pattern.
ASSERTION_TYPES = frozenset({"technical", "behavioral", "guardrail"})

#: EARS templates. A criterion must match the template its declared Pattern names.
EARS_PATTERNS: dict[str, re.Pattern[str]] = {
    "ubiquitous": re.compile(r"^The .+ shall .+", re.I),
    "event": re.compile(r"^When .+, the .+ shall .+", re.I),
    "state": re.compile(r"^While .+, the .+ shall .+", re.I),
    "option": re.compile(r"^Where .+, the .+ shall .+", re.I),
    "unwanted": re.compile(r"^If .+, then the .+ shall .+", re.I),
}
EARS_SHAPES: dict[str, str] = {
    "ubiquitous": "The <system> shall <response>",
    "event": "When <trigger>, the <system> shall <response>",
    "state": "While <state>, the <system> shall <response>",
    "option": "Where <feature>, the <system> shall <response>",
    "unwanted": "If <trigger>, then the <system> shall <mitigation>",
}

_HEADING_RE = re.compile(r"^##\s+(?P<id>st-[a-z0-9-]+):\s*(?P<title>.+?)\s*$", re.I)
_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z ]+):\s*(?P<value>.*)$")
_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
_QUESTION_RE = re.compile(r"^-\s+(?P<id>q-[a-z0-9-]+):\s*(?P<text>.+?)\s*$", re.I)
#: Stack/Rigging selection is owned solely by the ``discovery-stack`` questionnaire. A Sea Trials
#: QUESTIONS entry that asks the Commander to pick Rigging stack components is a misplaced
#: duplicate and is dropped so stack is never asked in a second questionnaire.
_STACK_QUESTION_ID_RE = re.compile(r"(?:^|-)stack(?:-|$)", re.I)
_STACK_QUESTION_TEXT_RE = re.compile(
    r"\brigging\b|\bstack(?:\s+(?:component|selection|guidance))", re.I
)
_FIELD_NAMES = (
    "Type",
    "Required",
    "Criterion",
    "Verification",
    "Pattern",
    "Command",
    "Extract",
    "Evidence",
    "Baseline",
    "Operator",
    "Target",
    "Unit",
)
_INLINE_FIELD_RE = re.compile(r"(?:^|\s)(?P<key>" + "|".join(_FIELD_NAMES) + r"):", re.I)


@dataclass(frozen=True)
class SeaTrial:
    criterion_id: str
    title: str
    trial_type: str
    required: bool
    criterion: str
    verification: str
    pattern: str = ""
    command: tuple[str, ...] = ()
    extract: str = ""
    evidence: str = ""
    baseline: float | None = None
    operator: str = ""
    target: float | None = None
    unit: str = ""


def is_stack_selection_question(question_id: str, text: str) -> bool:
    """Return True when a Sea Trials question is really a stack/Rigging selection.

    Stack selection belongs only to ``discovery-stack``; such a question is never a Sea Trials
    measurement fact and must not be projected into a second questionnaire.
    """
    if _STACK_QUESTION_ID_RE.search(question_id):
        return True
    return bool(_STACK_QUESTION_TEXT_RE.search(text))


@dataclass(frozen=True)
class SeaTrialQuestion:
    question_id: str
    text: str


@dataclass(frozen=True)
class SeaTrialsDocument:
    project: str
    trials: tuple[SeaTrial, ...]
    questions: tuple[SeaTrialQuestion, ...]


#: Canonical reader documentation embedded in ``SEA_TRIALS.md``. Drydock owns this text and
#: reinserts it on every write, so the artifact explains itself wherever it is read. Authored
#: as h3 blocks; the QuarterDeck renders them as standout notes.
SEA_TRIALS_DOC = """\
### About Sea Trials

Sea Trials are project-level acceptance: what this project must achieve to be declared
delivered. `drydock analyze` derives them from the COMPASS and the sources before the work is
decomposed. `drydock build score` judges every criterion at the end and reports the verdicts in
`SCORECARD.md`.

Sea Trials are fixed up front and are not approved. Advancing to the next stage accepts the risk
these criteria describe. Read them now; they are the terms the finished project is measured
against.

Stories carry an `accepts:` field naming the criteria they implement, so most criteria are also
checked during the build. A criterion needs no implementing story to be judged at the end.

### Guardrails

A guardrail is a permanent *never* — a thing the project may not do regardless of how well it
scores. Guardrails are reported as `HELD`, `BREACHED`, or `UNPROVEN`. A breach fails the completion
gate outright, independent of every score. A guardrail whose evidence is missing is `UNPROVEN`
and also fails the gate: an unproven *never* is not held. A guardrail verified by proof must be
named by a Programmatic Acceptance `Sea Trials:` reference, or it is reported as lacking
implementation/proof coverage.

Guardrails are exempt from `accepts:` coverage. No story builds a prohibition.

### Questions

A `QUESTIONS:` block lists measurement facts only a human can supply — unknown baselines,
targets, workloads, or business measures. Drydock projects these into a QuarterDeck
questionnaire and preserves the answers across reruns. An unanswered question leaves its
criterion `INCONCLUSIVE` at scoring time.\
"""


def _number(value: str, *, field: str, criterion_id: str) -> float | None:
    if not value.strip():
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} has invalid {field}: {value!r}"
        ) from exc


def _command(value: str, criterion_id: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} Command must be a JSON argv array"
        ) from exc
    if (
        not isinstance(parsed, list)
        or not parsed
        or not all(isinstance(v, str) and v for v in parsed)
    ):
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} Command must be a non-empty JSON string array"
        )
    for element in parsed:
        if _PLACEHOLDER_RE.search(element):
            raise SpecificationError(
                f"SEA_TRIALS.md {criterion_id} Command must be a literal argv; "
                f"Drydock does not resolve the placeholder {element!r}"
            )
    return tuple(parsed)


def _extract(value: str, criterion_id: str) -> str:
    """Validate the optional measurement Extract pattern.

    ``Extract`` lets Drydock read the measured value out of a harness's own stdout, so no
    project-authored code stands between the harness and the score it is judged by. The pattern
    must capture the number in its first group.
    """
    pattern = value.strip()
    if not pattern:
        return ""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} Extract is not a valid regular expression: {exc}"
        ) from exc
    if compiled.groups < 1:
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} Extract must capture the measured value in a group"
        )
    return pattern


def _pattern(value: str, *, trial_type: str, criterion: str, criterion_id: str) -> str:
    """Validate the EARS Pattern against the trial type and the criterion wording."""
    pattern = value.strip().lower()
    if trial_type not in ASSERTION_TYPES:
        if pattern:
            raise SpecificationError(
                f"SEA_TRIALS.md {criterion_id} is {trial_type} and must not declare a Pattern; "
                "EARS applies only to technical, behavioral, and guardrail criteria"
            )
        return ""
    if not pattern:
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} is {trial_type} and is missing Pattern; "
            f"expected one of: {', '.join(sorted(EARS_PATTERNS))}"
        )
    if pattern not in EARS_PATTERNS:
        raise SpecificationError(f"SEA_TRIALS.md {criterion_id} has invalid Pattern: {pattern}")
    if trial_type == "guardrail" and pattern != "unwanted":
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} is a guardrail and must use Pattern: unwanted "
            f"({EARS_SHAPES['unwanted']})"
        )
    if not EARS_PATTERNS[pattern].match(criterion):
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} Criterion does not match the {pattern} EARS pattern; "
            f"expected: {EARS_SHAPES[pattern]}"
        )
    return pattern


def parse_sea_trials_text(text: str) -> SeaTrialsDocument:
    """Parse the structured Sea Trials contract, accepting the legacy table as qualitative AC."""
    first = text.splitlines()[0] if text.splitlines() else ""
    project = first.partition(":")[2].strip() if first.startswith("# Sea Trials:") else ""
    lines = text.splitlines()
    trials: list[SeaTrial] = []
    questions: list[SeaTrialQuestion] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        heading = _HEADING_RE.match(lines[index])
        if heading:
            criterion_id = heading.group("id").lower()
            if criterion_id in seen:
                raise SpecificationError(f"SEA_TRIALS.md duplicate criterion ID: {criterion_id}")
            seen.add(criterion_id)
            fields: dict[str, str] = {}
            index += 1
            # Any heading ends the field scan. Documentation blocks are h3, so a "## " test
            # would let their prose reach _FIELD_RE and overwrite this criterion's fields.
            while (
                index < len(lines)
                and not lines[index].lstrip().startswith("#")
                and lines[index].strip() != "QUESTIONS:"
            ):
                match = _FIELD_RE.match(lines[index].strip())
                if match:
                    fields[match.group("key").lower().replace(" ", "_")] = match.group(
                        "value"
                    ).strip()
                index += 1
            trial_type = fields.get("type", "qualitative").lower()
            verification = fields.get("verification", "llm").lower()
            required_raw = fields.get("required", "yes").lower()
            if trial_type not in TRIAL_TYPES:
                raise SpecificationError(
                    f"SEA_TRIALS.md {criterion_id} has invalid Type: {trial_type}"
                )
            if verification not in VERIFICATION_TYPES:
                raise SpecificationError(
                    f"SEA_TRIALS.md {criterion_id} has invalid Verification: {verification}"
                )
            if required_raw not in {"yes", "no"}:
                raise SpecificationError(f"SEA_TRIALS.md {criterion_id} Required must be yes or no")
            criterion = fields.get("criterion", "").strip()
            if not criterion:
                raise SpecificationError(f"SEA_TRIALS.md {criterion_id} is missing Criterion")
            trials.append(
                SeaTrial(
                    criterion_id=criterion_id,
                    title=heading.group("title").strip(),
                    trial_type=trial_type,
                    required=required_raw == "yes",
                    criterion=criterion,
                    verification=verification,
                    pattern=_pattern(
                        fields.get("pattern", ""),
                        trial_type=trial_type,
                        criterion=criterion,
                        criterion_id=criterion_id,
                    ),
                    command=_command(fields.get("command", ""), criterion_id),
                    extract=_extract(fields.get("extract", ""), criterion_id),
                    evidence=fields.get("evidence", ""),
                    baseline=_number(
                        fields.get("baseline", ""), field="Baseline", criterion_id=criterion_id
                    ),
                    operator=fields.get("operator", ""),
                    target=_number(
                        fields.get("target", ""), field="Target", criterion_id=criterion_id
                    ),
                    unit=fields.get("unit", ""),
                )
            )
            continue
        if lines[index].strip() == "QUESTIONS:":
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith("#"):
                match = _QUESTION_RE.match(lines[index].strip())
                if match and not is_stack_selection_question(
                    match.group("id"), match.group("text")
                ):
                    questions.append(
                        SeaTrialQuestion(match.group("id").lower(), match.group("text"))
                    )
                index += 1
            continue
        index += 1

    if not trials:
        # Backward-compatible import of the old four-column table.
        for line in lines:
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 4 or not re.fullmatch(r"st-[a-z0-9-]+", cells[0], re.I):
                continue
            criterion_id = cells[0].lower()
            if criterion_id in seen:
                raise SpecificationError(f"SEA_TRIALS.md duplicate criterion ID: {criterion_id}")
            seen.add(criterion_id)
            trials.append(
                SeaTrial(
                    criterion_id, cells[1], "qualitative", True, cells[1], "llm", evidence=cells[3]
                )
            )
    if not trials:
        raise SpecificationError("SEA_TRIALS.md contains no project acceptance criteria")
    return SeaTrialsDocument(project, tuple(trials), tuple(questions))


def _strip_documentation(text: str) -> str:
    """Drop every h3 block, so stale or model-authored documentation never survives a write."""
    lines = text.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].lstrip().startswith("### "):
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith("#"):
                index += 1
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept)


def _format_trial_fields(text: str) -> str:
    """Put populated criterion fields on aligned, individual lines."""
    lines = text.splitlines()
    formatted: list[str] = []
    index = 0
    while index < len(lines):
        if not _HEADING_RE.match(lines[index]):
            formatted.append(lines[index])
            index += 1
            continue

        formatted.append(lines[index])
        index += 1
        field_lines: list[str] = []
        while (
            index < len(lines)
            and not lines[index].lstrip().startswith("#")
            and lines[index].strip() != "QUESTIONS:"
        ):
            field_lines.append(lines[index].strip())
            index += 1

        field_text = " ".join(field_lines)
        matches = list(_INLINE_FIELD_RE.finditer(field_text))
        fields: dict[str, str] = {}
        for position, match in enumerate(matches):
            value_end = matches[position + 1].start() if position + 1 < len(matches) else None
            fields[match.group("key").lower()] = field_text[match.end() : value_end].strip()
        if fields:
            for name in _FIELD_NAMES:
                value = fields.get(name.lower(), "")
                if value:
                    label = name + ":"
                    formatted.append(
                        f"{label:<11}{value}" if len(label) < 11 else f"{label} {value}"
                    )
        else:
            formatted.extend(field_lines)
    return "\n".join(formatted)


def _drop_stack_questions(text: str) -> str:
    """Remove misplaced stack/Rigging selection lines from the QUESTIONS block.

    When every question is dropped, the now-empty ``QUESTIONS:`` header is dropped too so the
    written artifact never carries a bare header.
    """
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        match = _QUESTION_RE.match(line.strip())
        if match and is_stack_selection_question(match.group("id"), match.group("text")):
            continue
        kept.append(line)
    result: list[str] = []
    for position, line in enumerate(kept):
        if line.strip() == "QUESTIONS:":
            following = kept[position + 1 :]
            if not any(_QUESTION_RE.match(later.strip()) for later in following):
                continue
        result.append(line)
    return "\n".join(result)


def normalize_sea_trials_text(text: str) -> str:
    """Return the document with exactly the canonical documentation blocks after the title."""
    lines = _drop_stack_questions(_strip_documentation(text)).splitlines()
    title = ""
    if lines and lines[0].startswith("# Sea Trials:"):
        title, lines = lines[0], lines[1:]
    body = _format_trial_fields("\n".join(lines)).strip()
    sections = [section for section in (title, SEA_TRIALS_DOC, body) if section]
    return "\n\n".join(sections) + "\n"


def load_sea_trials(path: Path) -> SeaTrialsDocument:
    if not path.is_file():
        raise SpecificationError(f"SEA_TRIALS.md not found: {path}")
    return parse_sea_trials_text(path.read_text(encoding="utf-8"))


def project_questions(document: SeaTrialsDocument, path: Path) -> Path | None:
    """Write the normal QuarterDeck JSON projection for unresolved Markdown questions."""
    if not document.questions:
        if path.is_file():
            path.unlink()
        return None
    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    answers = {
        str(item.get("id", "")): str(item.get("answer", ""))
        for item in existing.get("questions", [])
        if isinstance(item, dict)
    }
    payload = {
        "id": "discovery-sea-trials",
        "title": "Sea Trials Measurement Questions",
        "purpose": "Complete project-level acceptance measurements before final scoring.",
        "state": "open",
        "questions": [
            {
                "id": question.question_id,
                "label": question.text,
                "input": "textarea",
                "answer": answers.get(question.question_id, ""),
            }
            for question in document.questions
        ],
    }
    if payload["questions"] and all(str(q["answer"]).strip() for q in payload["questions"]):
        payload["state"] = "answered"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path
