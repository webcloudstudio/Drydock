"""Durable Commander decisions promoted from answered planning questions."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.questions import MarkdownQuestion, parse_questions

FILENAME = "planning-feedback.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PlanningDecision:
    decision_id: str
    question_id: str
    origin: str
    question: str
    answer: str
    answered_at: str
    source_blueprint: str
    status: str = "active"
    disposition: str = "retained"
    realization: str = ""
    reason: str = ""
    subject: str = ""


def feedback_path(target_dir: Path) -> Path:
    return target_dir / "QuarterDeck" / FILENAME


def decision_id(question: MarkdownQuestion) -> str:
    semantic = " ".join(question.question.lower().split())
    digest = hashlib.sha256(
        f"{question.origin}\0{question.question_id}\0{semantic}".encode()
    ).hexdigest()[:16]
    return f"decision-{digest}"


def load_feedback(target_dir: Path) -> tuple[PlanningDecision, ...]:
    path = feedback_path(target_dir)
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpecificationError(f"Invalid persistent Plan feedback {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions", []), list):
        raise SpecificationError(f"Invalid persistent Plan feedback structure: {path}")
    decisions = []
    for raw in payload.get("decisions", []):
        try:
            decisions.append(PlanningDecision(**raw))
        except (TypeError, AttributeError) as exc:
            raise SpecificationError(f"Invalid persistent Plan feedback record in {path}") from exc
    return tuple(decisions)


def authoritative_artifact(target_dir: Path, item: PlanningDecision) -> Path | None:
    """Return an existing artifact that owns this decision, preferring its realization."""
    for raw in (item.realization, item.source_blueprint):
        token = raw.strip().split(maxsplit=1)[0].split("#", 1)[0] if raw.strip() else ""
        if not token:
            continue
        candidates = [target_dir / token]
        if "/" not in token and token.lower().endswith(".md"):
            candidates.insert(0, target_dir / "blueprint" / token)
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def save_feedback(target_dir: Path, decisions: tuple[PlanningDecision, ...]) -> Path:
    path = feedback_path(target_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "decisions": [asdict(item) for item in decisions],
    }
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


def harvest_answered_questions(target_dir: Path) -> tuple[PlanningDecision, ...]:
    """Promote answered governed artifacts while preserving filename-independent history.

    Imported material below ``blueprint/sources/`` is user-authored provenance, not a
    Drydock-governed Blueprint artifact.  Only top-level Blueprint Markdown participates
    in the canonical Questions contract.
    """
    existing = {item.decision_id: item for item in load_feedback(target_dir)}
    candidates = list(sorted((target_dir / "blueprint").glob("*.md")))
    sea_trials = target_dir / "SEA_TRIALS.md"
    if sea_trials.is_file():
        candidates.append(sea_trials)
    now = datetime.now(UTC).isoformat()
    for path in candidates:
        try:
            questions = parse_questions(path.read_text(encoding="utf-8"), source=str(path))
        except (OSError, UnicodeError):
            continue
        for question in questions:
            if question.status != "answered":
                continue
            key = decision_id(question)
            prior = existing.get(key)
            source = path.relative_to(target_dir).as_posix()
            existing[key] = PlanningDecision(
                decision_id=key,
                question_id=question.question_id,
                origin=question.origin,
                question=question.question,
                answer=question.answer,
                answered_at=prior.answered_at if prior else now,
                source_blueprint=source,
                status="active",
                disposition=prior.disposition if prior else "retained",
                realization=prior.realization if prior else "",
                reason=prior.reason if prior else "",
                subject=question.name,
            )
    questionnaire_dir = target_dir / "QuarterDeck" / "questionnaires"
    if questionnaire_dir.is_dir():
        for path in sorted(questionnaire_dir.glob("discovery-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            for raw in payload.get("questions", []):
                answer = str(raw.get("answer", "")).strip()
                question_text = str(raw.get("prompt") or raw.get("label") or "").strip()
                question_id = str(raw.get("id") or "").strip()
                if not answer or not question_text or not question_id:
                    continue
                question = MarkdownQuestion(
                    question_id=(
                        question_id if question_id.startswith("Q-") else f"Q-{question_id}"
                    ),
                    name=str(raw.get("label") or question_id).strip(),
                    origin="analyze-questionnaire",
                    status="answered",
                    question=question_text,
                    answer=answer,
                )
                key = decision_id(question)
                prior = existing.get(key)
                existing[key] = PlanningDecision(
                    decision_id=key,
                    question_id=question.question_id,
                    origin=question.origin,
                    question=question.question,
                    answer=question.answer,
                    answered_at=prior.answered_at if prior else now,
                    source_blueprint=(f"QuarterDeck/questionnaires/{path.name}#{question_id}"),
                    status="active",
                    disposition=prior.disposition if prior else "retained",
                    realization=prior.realization if prior else "",
                    reason=prior.reason if prior else "",
                    subject=question.name,
                )
    decisions = tuple(sorted(existing.values(), key=lambda item: item.decision_id))
    if decisions:
        save_feedback(target_dir, decisions)
    return decisions


def render_feedback_prompt(decisions: tuple[PlanningDecision, ...]) -> str:
    active = [item for item in decisions if item.status == "active"]
    if not active:
        return ""
    lines = [
        "## Persistent Plan feedback",
        "",
        "These Commander decisions survive Blueprint renames and decomposition changes. Apply each",
        "decision to normal specification content; do not recreate it as a question.",
        "",
    ]
    for item in active:
        lines.extend([
            f"### {item.decision_id}",
            f"- Subject: {item.subject or item.question_id}",
            f"- Question: {item.question}",
            f"- Decision: {item.answer}",
            f"- Prior source: {item.source_blueprint}",
            "",
        ])
    return "\n".join(lines)


def apply_manifest_dispositions(
    target_dir: Path,
    manifest_feedback: str,
) -> tuple[PlanningDecision, ...]:
    """Apply optional current-plan dispositions while retaining every omitted decision."""
    current = {item.decision_id: item for item in load_feedback(target_dir)}
    for raw in manifest_feedback.splitlines():
        parts = raw.strip().split(maxsplit=2)
        if len(parts) < 2 or parts[0] not in current:
            continue
        key, disposition = parts[:2]
        if disposition not in {"applied", "retained", "retired"}:
            continue
        detail = parts[2].strip() if len(parts) == 3 else ""
        prior = current[key]
        realization = detail if disposition == "applied" else ""
        reason = detail if disposition == "retired" else ""
        current[key] = PlanningDecision(**{
            **asdict(prior),
            "status": "retired" if disposition == "retired" else "active",
            "disposition": disposition,
            "realization": realization,
            "reason": reason,
        })
    decisions = tuple(sorted(current.values(), key=lambda item: item.decision_id))
    if decisions:
        save_feedback(target_dir, decisions)
    return decisions


def update_feedback_answer(
    target_dir: Path,
    decision_id_value: str,
    answer: str,
) -> PlanningDecision:
    """Edit durable feedback only when its authoritative source artifact is absent."""
    value = answer.strip()
    if not value:
        raise ValueError("Planning feedback answer must not be empty")
    decisions = list(load_feedback(target_dir))
    for index, item in enumerate(decisions):
        if item.decision_id != decision_id_value:
            continue
        if authoritative_artifact(target_dir, item) is not None:
            raise ValueError("Edit this answer in its authoritative artifact")
        updated = PlanningDecision(**{
            **asdict(item),
            "answer": value,
            "answered_at": datetime.now(UTC).isoformat(),
            "status": "active",
            "disposition": "retained",
        })
        decisions[index] = updated
        save_feedback(target_dir, tuple(decisions))
        return updated
    raise ValueError(f"Unknown planning decision {decision_id_value!r}")
