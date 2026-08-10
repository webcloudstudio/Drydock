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

#: Types whose Criterion is an assertion and therefore normally carries an EARS Pattern. EARS is
#: preferred writing discipline for these types, not a requirement: ``Pattern`` is optional
#: everywhere and a criterion that reads better as plain English is notated ``other``.
ASSERTION_TYPES = frozenset({"technical", "behavioral", "guardrail"})

#: EARS templates. A criterion conforms when it matches the template its declared Pattern names.
#: The system noun takes an optional article, so a proper-noun system ("Marina shall") conforms
#: exactly as a common-noun system ("the parser shall") does.
EARS_PATTERNS: dict[str, re.Pattern[str]] = {
    "ubiquitous": re.compile(r"^(?:The\s+)?.+ shall .+", re.I),
    "event": re.compile(r"^When .+, (?:the\s+)?.+ shall .+", re.I),
    "state": re.compile(r"^While .+, (?:the\s+)?.+ shall .+", re.I),
    "option": re.compile(r"^Where .+, (?:the\s+)?.+ shall .+", re.I),
    "unwanted": re.compile(r"^If .+, then (?:the\s+)?.+ shall .+", re.I),
}
EARS_SHAPES: dict[str, str] = {
    "ubiquitous": "The <system> shall <response>",
    "event": "When <trigger>, the <system> shall <response>",
    "state": "While <state>, the <system> shall <response>",
    "option": "Where <feature>, the <system> shall <response>",
    "unwanted": "If <trigger>, then the <system> shall <mitigation>",
}

#: The notation a criterion is written in. Drydock derives this on every read and overwrites it on
#: every write; it is descriptive, never a gate.
NOTATIONS = frozenset({"ears", "other"})

_UNIVERSAL_SUITE_RE = re.compile(
    r"\b(?:all|every|complete|full|zero\s+(?:failures?|errors?))\b|100\s*%",
    re.I,
)
_SUITE_RE = re.compile(r"\b(?:test|conformance|suite|cases?|examples?)\b", re.I)


def derive_notation(pattern: str, criterion: str) -> str:
    """Return the notation a criterion is written in: ``ears`` or ``other``.

    A criterion is ``ears`` only when it declares one of the five EARS patterns *and* its prose
    matches that pattern's shape exactly. Anything else — no Pattern, an unrecognized Pattern name,
    or prose that does not follow the declared shape — is ``other``: plain English, equally binding,
    and judged on its stated intent. Nothing in Drydock computes on the notation; it is recorded so
    a human reader and the judge model know which discipline the sentence follows.
    """
    name = pattern.strip().lower()
    if name not in EARS_PATTERNS:
        return "other"
    return "ears" if EARS_PATTERNS[name].match(criterion.strip()) else "other"


def _is_universal_suite_criterion(criterion: str, command: tuple[str, ...]) -> bool:
    """Whether a Sea Trial describes complete supplied-suite conformance.

    Such a requirement is a proof that the unfiltered suite succeeds. It is not a scalar
    measurement: converting it to a remembered test count makes the generated contract depend on
    model knowledge rather than the supplied corpus.
    """
    return bool(command and _UNIVERSAL_SUITE_RE.search(criterion) and _SUITE_RE.search(criterion))


def _validate_universal_suite_contract(
    *,
    criterion_id: str,
    criterion: str,
    verification: str,
    command: tuple[str, ...],
    extract: str,
    evidence: str,
    baseline: float | None,
    operator: str,
    target: float | None,
    unit: str,
) -> None:
    """Reject a numeric representation of an all-cases/full-suite requirement."""
    if not _is_universal_suite_criterion(criterion, command):
        return
    if verification != "proof":
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} is a complete-suite requirement and must use "
            "Verification: proof, not measurement"
        )
    forbidden = (
        extract,
        evidence,
        "" if baseline is None else str(baseline),
        operator,
        "" if target is None else str(target),
        unit,
    )
    if any(forbidden):
        raise SpecificationError(
            f"SEA_TRIALS.md {criterion_id} is a complete-suite proof and must not declare "
            "Extract, Evidence, Baseline, Operator, Target, or Unit"
        )


_HEADING_RE = re.compile(r"^##\s+(?P<id>st-[a-z0-9-]+):\s*(?P<title>.+?)\s*$", re.I)
_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z ]+):\s*(?P<value>.*)$")
_PLACEHOLDER_RE = re.compile(r"<[^<>]+>")
#: Stack/Rigging selection is owned solely by ``TECHNOLOGY_STACK.md``. A Sea Trials
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
    "Notation",
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
    notation: str = "other"
    command: tuple[str, ...] = ()
    extract: str = ""
    evidence: str = ""
    baseline: float | None = None
    operator: str = ""
    target: float | None = None
    unit: str = ""


def is_stack_selection_question(question_id: str, text: str) -> bool:
    """Return True when a Sea Trials question is really a stack/Rigging selection.

    Stack selection belongs only to ``TECHNOLOGY_STACK.md``; such a question is never a Sea Trials
    measurement fact and must not be projected into a second questionnaire.
    """
    if _STACK_QUESTION_ID_RE.search(question_id):
        return True
    return bool(_STACK_QUESTION_TEXT_RE.search(text))


@dataclass(frozen=True)
class SeaTrialQuestion:
    question_id: str
    text: str
    status: str = "open"
    answer: str = ""


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

### Notation

Every criterion carries a `Notation` of `ears` or `other`. Drydock derives it and rewrites it on
every write. `ears` means the criterion declares an EARS `Pattern` and its sentence matches that
pattern exactly. `other` means plain English. Both are equally binding and are judged on what they
state; the notation records the writing discipline and changes no verdict.

### Guardrails

A guardrail is a permanent *never* — a thing the project may not do regardless of how well it
scores. Guardrails are reported as `HELD`, `BREACHED`, or `UNPROVEN`. A breach fails the completion
gate outright, independent of every score.

`UNPROVEN` means no evidence settled the prohibition either way. It does not fail the gate. Nothing
demonstrated a violation, and many prohibitions worth writing down admit no automated proof at all.
The gate instead completes as `COMPLETE — MANUAL VERIFICATION REQUIRED` and names every unproven
guardrail as a check a human owes before release. Binding a proof to a guardrail with a Programmatic
Acceptance `Sea Trials:` reference settles it mechanically and removes the manual check; it is not
required.

Guardrails are exempt from `accepts:` coverage and from proof-reference coverage. No story builds a
prohibition.

They are graded on what you claimed about them. A guardrail you marked `Verification: evidence` or
`llm` carries no weight in the technical score: you declared it unprovable, and a project is not
marked down for writing such a prohibition down. A guardrail you marked `Verification: proof` or
`measurement` is graded like any other assertion, because you declared it provable — leaving it
unbound scores as model opinion and costs acceptance coverage until a Programmatic Acceptance
`Sea Trials:` reference reaches it. Neither form fails the gate.

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


def _pattern(value: str) -> str:
    """Normalize the declared EARS Pattern name, or return ``""``.

    ``Pattern`` is optional and decorative on every trial type: it names the shape the author aimed
    for. An absent or unrecognized name is not an error — it simply leaves the criterion notated
    ``other`` by :func:`derive_notation`.
    """
    pattern = value.strip().lower()
    return pattern if pattern in EARS_PATTERNS else ""


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
            while index < len(lines) and not lines[index].lstrip().startswith("#"):
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
            command = _command(fields.get("command", ""), criterion_id)
            extract = _extract(fields.get("extract", ""), criterion_id)
            evidence = fields.get("evidence", "")
            baseline = _number(
                fields.get("baseline", ""), field="Baseline", criterion_id=criterion_id
            )
            operator = fields.get("operator", "")
            target = _number(fields.get("target", ""), field="Target", criterion_id=criterion_id)
            unit = fields.get("unit", "")
            _validate_universal_suite_contract(
                criterion_id=criterion_id,
                criterion=criterion,
                verification=verification,
                command=command,
                extract=extract,
                evidence=evidence,
                baseline=baseline,
                operator=operator,
                target=target,
                unit=unit,
            )
            pattern = _pattern(fields.get("pattern", ""))
            trials.append(
                SeaTrial(
                    criterion_id=criterion_id,
                    title=heading.group("title").strip(),
                    trial_type=trial_type,
                    required=required_raw == "yes",
                    criterion=criterion,
                    verification=verification,
                    pattern=pattern,
                    notation=derive_notation(pattern, criterion),
                    command=command,
                    extract=extract,
                    evidence=evidence,
                    baseline=baseline,
                    operator=operator,
                    target=target,
                    unit=unit,
                )
            )
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
    """Drop h3 documentation blocks after the canonical Questions section is removed."""
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
    """Put populated criterion fields on aligned, individual lines.

    ``Notation`` is Drydock's, not the author's: it is derived from the criterion's own Pattern and
    prose and overwrites whatever the source carried. Deriving it here rather than from a parsed
    document keeps :func:`normalize_sea_trials_text` unable to raise, so raw model output is still
    normalized before it is validated.
    """
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
        while index < len(lines) and not lines[index].lstrip().startswith("#"):
            field_lines.append(lines[index].strip())
            index += 1

        field_text = " ".join(field_lines)
        matches = list(_INLINE_FIELD_RE.finditer(field_text))
        fields: dict[str, str] = {}
        for position, match in enumerate(matches):
            value_end = matches[position + 1].start() if position + 1 < len(matches) else None
            fields[match.group("key").lower()] = field_text[match.end() : value_end].strip()
        if fields:
            fields["notation"] = derive_notation(
                fields.get("pattern", ""), fields.get("criterion", "")
            )
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


def normalize_sea_trials_text(text: str) -> str:
    """Return canonical Sea Trials content without the retired Questions section."""
    without_questions = re.sub(
        r"^## Questions\s*$\n.*?(?=^##\s+|\Z)",
        "",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    without_questions = re.sub(
        r"^## Reader Guide\s*$.*\Z",
        "",
        without_questions,
        flags=re.MULTILINE | re.DOTALL,
    )
    lines = _strip_documentation(without_questions).splitlines()
    title = ""
    if lines and lines[0].startswith("# Sea Trials:"):
        title, lines = lines[0], lines[1:]
    body = _format_trial_fields("\n".join(lines)).strip()
    if body and not re.search(r"^##\s+", body, re.MULTILINE):
        body = "## Trials\n\n" + body
    reader_guide = "## Reader Guide\n\n" + SEA_TRIALS_DOC
    sections = [section for section in (title, body, reader_guide) if section]
    return "\n\n".join(sections) + "\n"


def load_sea_trials(path: Path) -> SeaTrialsDocument:
    if not path.is_file():
        raise SpecificationError(f"SEA_TRIALS.md not found: {path}")
    return parse_sea_trials_text(path.read_text(encoding="utf-8"))


def project_questions(document: SeaTrialsDocument, path: Path) -> Path | None:
    """Sea Trials has no question projection; decisions are persisted in DECISIONS.json."""
    del document, path
    return None
