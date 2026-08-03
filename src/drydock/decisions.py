"""``DECISIONS.json`` — Plan and Build significant-decision disclosure record.

Build must never stall on a choice Plan should have already made, and the Commander must be
able to review and redirect any such choice before Build acts on it. Where the Blueprint,
guardrails, or stack declaration are silent on a needed decision, the Planning Crew decides,
proceeds as if it were chosen, and discloses the choice here.

``DECISIONS.json`` is the sole persistence target for these disclosures; Plan never writes a
decision back into a Blueprint file. On each run Plan keeps only human-authored items
(``commander_direction`` or ``override_text`` set) as fixed constraints and discards every other
prior item outright, re-deciding it fresh if the underlying gap still exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DECISIONS_BLOCK = "DECISIONS.json"
DECISIONS_FILENAME = "DECISIONS.json"

DECISION_TYPES = frozenset({"choice", "text"})
DECISION_SEVERITIES = frozenset({"low", "material", "blocking"})
DECISION_ORIGINS = frozenset({"plan", "build", "analyze-questionnaire"})
DECISION_STATUSES = frozenset({"open", "recommended", "answered"})

#: The two buckets a decision may attach to: a Blueprint file it governs, or the catch-all.
ARCHITECTURE_BLUEPRINT = "ARCHITECTURE.md"


@dataclass(frozen=True)
class DecisionOption:
    value: str
    label: str


@dataclass(frozen=True)
class Decision:
    id: str
    type: str
    severity: str
    origin: str
    blueprint: str
    story: str | None
    status: str
    archived: bool
    title: str
    description: str
    options: tuple[DecisionOption, ...]
    system_choice: str
    commander_direction: str | None = None
    override_text: str | None = None

    @property
    def is_human_authored(self) -> bool:
        """Whether a Commander has actually touched this item.

        Only these items are fixed constraints across a replan; every other item is an
        LLM-only disclosure and is re-decided fresh each run.
        """
        return bool(self.commander_direction) or bool(self.override_text)

    @property
    def answer(self) -> str:
        """Return the Commander response, regardless of response form."""
        return (self.override_text or self.commander_direction or "").strip()


def _options_from_raw(raw: object) -> tuple[DecisionOption, ...]:
    if not isinstance(raw, list):
        return ()
    options: list[DecisionOption] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", "")).strip()
        label = str(item.get("label", "")).strip()
        if value and label:
            options.append(DecisionOption(value, label))
    return tuple(options)


def parse_plan_decisions(text: str) -> tuple[Decision, ...]:
    """Parse a Plan-emitted ``DECISIONS.json`` body — freshly LLM-decided items only.

    A malformed payload or invalid item is dropped rather than failing the run: a decision
    disclosure defect must never block emission of the Blueprint and Manifest it describes.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    decisions: list[Decision] = []
    seen: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        decision_id = str(raw.get("id", "")).strip()
        decision_type = str(raw.get("type", "")).strip().lower()
        severity = str(raw.get("severity", "")).strip().lower()
        blueprint = str(raw.get("blueprint", "")).strip()
        title = str(raw.get("title", "")).strip()
        description = str(raw.get("description", "")).strip()
        system_choice = str(raw.get("system_choice", "")).strip()
        story_raw = raw.get("story")
        story = str(story_raw).strip() or None if story_raw else None
        options = _options_from_raw(raw.get("options"))
        if (
            not decision_id
            or decision_id in seen
            or decision_type not in DECISION_TYPES
            or severity not in DECISION_SEVERITIES
            or not blueprint
            or not title
            or not description
            or not system_choice
            or (decision_type == "choice" and not options)
        ):
            continue
        seen.add(decision_id)
        decisions.append(
            Decision(
                id=decision_id,
                type=decision_type,
                severity=severity,
                origin="plan",
                blueprint=blueprint,
                story=story,
                status="recommended",
                archived=False,
                title=title,
                description=description,
                options=options,
                system_choice=system_choice,
            )
        )
    return tuple(decisions)


def validate_decision_blueprints(
    decisions: tuple[Decision, ...], allowed_blueprints: frozenset[str]
) -> tuple[tuple[Decision, ...], tuple[str, ...]]:
    """Drop decisions attached to a Blueprint file the run did not emit.

    ``allowed_blueprints`` is the run's emitted specification set plus ``ARCHITECTURE.md``.
    """
    kept: list[Decision] = []
    warnings: list[str] = []
    for item in decisions:
        if item.blueprint != ARCHITECTURE_BLUEPRINT and item.blueprint not in allowed_blueprints:
            warnings.append(
                f"{item.id}: dropped decision attached to {item.blueprint!r} — not an emitted "
                "Blueprint file"
            )
            continue
        kept.append(item)
    return tuple(kept), tuple(warnings)


def load_decisions(path: Path) -> tuple[Decision, ...]:
    """Load a persisted ``DECISIONS.json``, tolerating an absent or malformed file."""
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    decisions: list[Decision] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        decision_id = raw.get("id")
        decision_type = raw.get("type")
        severity = raw.get("severity")
        if not decision_id or not decision_type or not severity:
            continue
        decisions.append(
            Decision(
                id=str(decision_id),
                type=str(decision_type),
                severity=str(severity),
                origin=str(raw.get("origin", "plan")),
                blueprint=str(raw.get("blueprint", "")),
                story=(str(raw["story"]) if raw.get("story") else None),
                status=str(raw.get("status", "recommended")),
                archived=bool(raw.get("archived", False)),
                title=str(raw.get("title", "")),
                description=str(raw.get("description", "")),
                options=_options_from_raw(raw.get("options")),
                system_choice=str(raw.get("system_choice", "")),
                commander_direction=(raw.get("commander_direction") or None),
                override_text=(raw.get("override_text") or None),
            )
        )
    return tuple(decisions)


def _decision_to_dict(item: Decision) -> dict:
    payload: dict = {
        "id": item.id,
        "type": item.type,
        "severity": item.severity,
        "origin": item.origin,
        "blueprint": item.blueprint,
        "story": item.story,
        "status": item.status,
        "archived": item.archived,
        "title": item.title,
        "description": item.description,
        "options": [{"value": o.value, "label": o.label} for o in item.options],
        "system_choice": item.system_choice,
    }
    if item.commander_direction:
        payload["commander_direction"] = item.commander_direction
    if item.override_text:
        payload["override_text"] = item.override_text
    return payload


def render_decisions(decisions: tuple[Decision, ...]) -> str:
    return json.dumps([_decision_to_dict(item) for item in decisions], indent=2) + "\n"


def write_decisions(path: Path, decisions: tuple[Decision, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_decisions(decisions), encoding="utf-8", newline="\n")


def reconcile_decisions(
    freshly_decided: tuple[Decision, ...], prior: tuple[Decision, ...]
) -> tuple[Decision, ...]:
    """Merge a Plan run's fresh disclosures with retained human-authored prior items.

    Only items a Commander has actually touched survive a replan unchanged; every other prior
    item is discarded even if the underlying gap still exists, because Plan re-decides it fresh.
    A fresh item sharing a retained item's id never overrides the retained, Commander-owned one.
    """
    retained = tuple(item for item in prior if item.is_human_authored)
    retained_ids = {item.id for item in retained}
    fresh = tuple(item for item in freshly_decided if item.id not in retained_ids)
    return retained + fresh


def questionnaire_decisions(target_dir: Path) -> tuple[Decision, ...]:
    """Convert answered Analyze questionnaires into the decision store.

    Questionnaire JSON remains an input compatibility format for Analyze. It is never a
    planning-feedback store and is not written by this function.
    """
    path = target_dir / DECISIONS_FILENAME
    existing = {item.id: item for item in load_decisions(path)}
    questionnaire_dir = target_dir / "QuarterDeck" / "questionnaires"
    for questionnaire in sorted(questionnaire_dir.glob("discovery-*.json")):
        try:
            payload = json.loads(questionnaire.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for raw in payload.get("questions", []):
            if not isinstance(raw, dict):
                continue
            answer = str(raw.get("answer", "")).strip()
            question_id = str(raw.get("id", "")).strip()
            prompt = str(raw.get("prompt") or raw.get("label") or "").strip()
            if not answer or not question_id or not prompt:
                continue
            record_id = f"analyze-{question_id}"
            prior = existing.get(record_id)
            existing[record_id] = Decision(
                id=record_id,
                type="text",
                severity="material",
                origin="analyze-questionnaire",
                blueprint=str(prior.blueprint if prior else "ARCHITECTURE.md"),
                story=prior.story if prior else None,
                status="answered",
                archived=False,
                title=str(raw.get("label") or question_id).strip(),
                description=prompt,
                options=(),
                system_choice=answer,
                commander_direction=answer,
                override_text=prior.override_text if prior else None,
            )
    decisions = tuple(sorted(existing.values(), key=lambda item: item.id))
    if decisions != load_decisions(path):
        write_decisions(path, decisions)
    return decisions


def render_commander_guidance(decisions: tuple[Decision, ...]) -> str:
    """Render active decisions for Plan/Build prompt context."""
    active = [item for item in decisions if not item.archived and item.answer]
    if not active:
        return ""
    lines = [
        "## Commander decisions",
        "",
        "Apply these decisions as constraints; do not recreate them as questions.",
        "",
    ]
    for item in active:
        lines.extend([
            f"### {item.id}",
            f"- Title: {item.title}",
            f"- Decision: {item.answer}",
            f"- Severity: {item.severity}",
            f"- Blueprint: {item.blueprint}",
            "",
        ])
    return "\n".join(lines)
