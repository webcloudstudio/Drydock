"""Project optional Shipyard Crew decision reports into owning Blueprints."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from drydock.acceptance import AcceptanceRunResult, ProgrammaticAcceptance
from drydock.decisions import Decision, load_decisions, write_decisions

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
    target_dir: Path | None = None,
) -> tuple[Path, ...]:
    """Persist reported non-blocking decisions in DECISIONS.json."""
    if target_dir is None:
        target_dir = blueprint_dir.parent
    path = target_dir / "DECISIONS.json"
    current = {item.id: item for item in load_decisions(path)}
    written = False
    for item in parse_build_decisions(text, allowed_specs):
        if not (blueprint_dir / item.spec).is_file():
            continue
        record_id = f"build-{item.spec}-{item.subject}".lower().replace(" ", "-")
        current.setdefault(
            record_id,
            Decision(
                id=record_id,
                type="text",
                severity=item.severity,
                origin="build",
                blueprint=item.spec,
                story=None,
                status="recommended",
                archived=False,
                title=item.subject,
                description=item.decision,
                options=(),
                system_choice=item.decision,
            ),
        )
        written = True
    if written:
        write_decisions(path, tuple(sorted(current.values(), key=lambda record: record.id)))
        return (path,)
    return ()


def record_skipped_acceptance_decisions(
    skipped: tuple[tuple[AcceptanceRunResult, ProgrammaticAcceptance, str | None], ...],
    *,
    target_dir: Path,
) -> tuple[Path, ...]:
    """Persist a reviewable decision for each acceptance skipped as invalid setup.

    Skipping keeps a defective generated check from blocking implementation, but it never
    silently turns the check green. The decision remains recommended until the Blueprint
    acceptance or its test setup is repaired.
    """
    if not skipped:
        return ()
    path = target_dir / "DECISIONS.json"
    current = {item.id: item for item in load_decisions(path)}
    for result, _check, story in skipped:
        check_id = str(getattr(result, "check_id"))
        source = str(getattr(result, "source"))
        reason = str(getattr(result, "error") or "acceptance setup was unavailable")
        record_id = f"build-skip-{source}-{check_id}".lower().replace(" ", "-")
        current.setdefault(
            record_id,
            Decision(
                id=record_id,
                type="text",
                severity="low",
                origin="build",
                blueprint=source,
                story=story,
                status="recommended",
                archived=False,
                title=f"Acceptance skipped: {check_id}",
                description=reason,
                options=(),
                system_choice=(
                    f"Leave {check_id} untested until its acceptance setup is repaired; "
                    "do not treat it as passed."
                ),
            ),
        )
    write_decisions(path, tuple(sorted(current.values(), key=lambda record: record.id)))
    return (path,)
