"""Structured project-level acceptance criteria stored in ``SEA_TRIALS.md``."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import SpecificationError

TRIAL_TYPES = frozenset({"technical", "behavioral", "qualitative", "outcome"})
VERIFICATION_TYPES = frozenset({"proof", "measurement", "evidence", "llm"})
_HEADING_RE = re.compile(r"^##\s+(?P<id>st-[a-z0-9-]+):\s*(?P<title>.+?)\s*$", re.I)
_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z ]+):\s*(?P<value>.*)$")
_QUESTION_RE = re.compile(r"^-\s+(?P<id>q-[a-z0-9-]+):\s*(?P<text>.+?)\s*$", re.I)


@dataclass(frozen=True)
class SeaTrial:
    criterion_id: str
    title: str
    trial_type: str
    required: bool
    criterion: str
    verification: str
    command: tuple[str, ...] = ()
    evidence: str = ""
    baseline: float | None = None
    operator: str = ""
    target: float | None = None
    unit: str = ""


@dataclass(frozen=True)
class SeaTrialQuestion:
    question_id: str
    text: str


@dataclass(frozen=True)
class SeaTrialsDocument:
    project: str
    trials: tuple[SeaTrial, ...]
    questions: tuple[SeaTrialQuestion, ...]


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
    return tuple(parsed)


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
            while (
                index < len(lines)
                and not lines[index].startswith("## ")
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
                    command=_command(fields.get("command", ""), criterion_id),
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
            while index < len(lines):
                match = _QUESTION_RE.match(lines[index].strip())
                if match:
                    questions.append(
                        SeaTrialQuestion(match.group("id").lower(), match.group("text"))
                    )
                index += 1
            break
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
