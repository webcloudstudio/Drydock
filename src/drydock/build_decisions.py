"""Project optional Shipyard Crew decision reports into owning Blueprints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from drydock.questions import MarkdownQuestion, append_question

_PAYLOAD_RE = re.compile(
    r"<blueprint-decisions>\s*(?P<payload>.*?)\s*</blueprint-decisions>",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class BuildDecision:
    spec: str
    severity: str
    subject: str
    decision: str


def parse_build_decisions(text: str, allowed_specs: frozenset[str]) -> tuple[BuildDecision, ...]:
    """Return valid story-local decisions from an optional agent payload."""
    match = _PAYLOAD_RE.search(text)
    if match is None:
        return ()
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    decisions: list[BuildDecision] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        spec = str(raw.get("spec", "")).strip()
        severity = str(raw.get("severity", "material")).strip().lower()
        subject = str(raw.get("subject", "")).strip()
        decision = str(raw.get("decision", "")).strip()
        if (
            spec not in allowed_specs
            or "/" in spec
            or not spec.lower().endswith(".md")
            or severity not in {"low", "material"}
            or not subject
            or not decision
        ):
            continue
        decisions.append(BuildDecision(spec, severity, subject, decision))
    return tuple(decisions)


def record_build_decisions(
    text: str,
    *,
    blueprint_dir: Path,
    allowed_specs: frozenset[str],
) -> tuple[Path, ...]:
    """Append reported decisions to their owning governed specifications."""
    written: list[Path] = []
    for item in parse_build_decisions(text, allowed_specs):
        path = blueprint_dir / item.spec
        if not path.is_file():
            continue
        digest = hashlib.sha256(
            f"{item.spec}\0{item.subject}\0{item.decision}".encode()
        ).hexdigest()[:12]
        question = MarkdownQuestion(
            question_id=f"Q-build-{digest}",
            name=item.subject,
            origin="build",
            status="open",
            question=item.decision,
            answer="",
            severity=item.severity,
        )
        if append_question(path, question):
            written.append(path)
    return tuple(written)
