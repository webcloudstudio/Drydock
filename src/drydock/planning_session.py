"""Create deterministic draft BUILD_PLAN.md files and Planning Session projections."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from drydock.build_plan import BuildPlan, parse_build_plan
from drydock.errors import SpecificationError
from drydock.paths import get_quarterdeck_root
from drydock.plan_intent import init_plan_intent

_ENTRY_RE = re.compile(r"(?m)^([^#\s][^\s]*\.md)\b")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s*)?(.*\S)\s*$")


@dataclass(frozen=True)
class PlanCreateResult:
    plan: BuildPlan
    target_dir: Path
    quarterdeck_dir: Path
    changed: bool


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or "work"


def _section_bullets(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    active = False
    bullets: list[str] = []
    for line in lines:
        if re.match(rf"^##\s+{re.escape(heading)}\s*$", line, re.IGNORECASE):
            active = True
            continue
        if active and line.startswith("## "):
            break
        if active:
            match = _BULLET_RE.match(line)
            if match and match.group(1).lower() not in {"none.", "none", "(add criteria here)"}:
                bullets.append(match.group(1))
    return bullets


def _ordered_inputs(blueprint_dir: Path) -> list[Path]:
    intent = blueprint_dir / "BUILD_PLAN_INTENT.md"
    if not intent.is_file():
        raise SpecificationError(
            f"BUILD_PLAN_INTENT.md not found after planning inventory: {intent}"
        )
    paths: list[Path] = []
    for match in _ENTRY_RE.finditer(intent.read_text(encoding="utf-8")):
        path = blueprint_dir / match.group(1)
        if path.is_file():
            paths.append(path)
    if not paths:
        raise SpecificationError(f"No planned Markdown inputs found in {intent}")
    return paths


def _plan_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _block(
    block_type: str,
    number: int,
    name: str,
    **fields: str,
) -> str:
    lines = [f"## {block_type} {number}: {name}"]
    lines.extend(f"{key}: {value}" for key, value in fields.items() if value)
    return "\n".join(lines)


def _generate_plan_text(
    blueprint: str, blueprint_dir: Path, inputs: list[Path], old: BuildPlan | None
) -> str:
    old_states = {block.block_id: block.state for block in old.blocks} if old else {}
    digest = _plan_hash(inputs)
    unchanged = old is not None and old.plan_hash == digest
    plan_state = old.state if unchanged else "draft"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017

    blocks: list[str] = []
    feature_number = story_number = spike_number = ac_number = 0
    last_story = ""
    for path in inputs:
        relative = path.relative_to(blueprint_dir).as_posix()
        name = path.stem.removeprefix("FEATURE-").removeprefix("SCREEN-").replace("-", " ")
        name = name.strip().title()
        text = path.read_text(encoding="utf-8")
        parent = ""
        file_spikes: list[str] = []

        if path.name.startswith("FEATURE-"):
            feature_number += 1
            feature_id = f"feature-{_slug(name)}"
            parent = feature_id
            blocks.append(
                _block(
                    "feature",
                    feature_number,
                    name,
                    id=feature_id,
                    summary=f"Deliver the {name} workflow.",
                    state=old_states.get(feature_id, "pending"),
                )
            )

        for question in _section_bullets(text, "Open Questions"):
            spike_number += 1
            spike_id = f"spike-{_slug(question)}"
            file_spikes.append(spike_id)
            fields = {
                "id": spike_id,
                "summary": question,
                "question": question,
                "context": relative,
                "state": old_states.get(spike_id, "pending"),
            }
            if parent:
                fields["parent"] = parent
            blocks.append(_block("spike", spike_number, question, **fields))
            ac_number += 1
            ac_id = f"ac-{spike_id}-resolved"
            blocks.append(
                _block(
                    "ac",
                    ac_number,
                    f"Decision resolves: {question}",
                    id=ac_id,
                    parent=spike_id,
                    kind="assertion",
                    state=old_states.get(ac_id, "pending"),
                )
            )

        story_number += 1
        story_id = f"story-{_slug(path.stem)}"
        fields = {
            "id": story_id,
            "summary": f"Deliver the work defined by {relative}.",
            "implements": relative,
            "scope": "both" if path.name.startswith(("FEATURE-", "SCREEN-")) else "target",
            "state": old_states.get(story_id, "pending"),
        }
        if parent:
            fields["parent"] = parent
        dependencies = ([last_story] if last_story else []) + file_spikes
        if dependencies:
            fields["depends"] = ", ".join(dependencies)
        blocks.append(_block("story", story_number, f"Deliver {name}", **fields))
        last_story = story_id

        criteria = _section_bullets(text, "Acceptance Criteria")
        if not criteria:
            criteria = [f"Delivered behavior matches {relative}"]
        for criterion in criteria:
            ac_number += 1
            ac_id = f"ac-{story_id}-{_slug(criterion)}"
            blocks.append(
                _block(
                    "ac",
                    ac_number,
                    criterion,
                    id=ac_id,
                    parent=story_id,
                    kind="assertion",
                    state=old_states.get(ac_id, "pending"),
                )
            )
        if parent:
            ac_number += 1
            ac_id = f"ac-{parent}-accepted"
            blocks.append(
                _block(
                    "ac",
                    ac_number,
                    f"{name} workflow is accepted",
                    id=ac_id,
                    parent=parent,
                    kind="assertion",
                    state=old_states.get(ac_id, "pending"),
                )
            )

    return (
        f"# BUILD_PLAN: {blueprint}\n"
        f"updated: {now}\n"
        f"plan_hash: {digest}\n"
        f"state: {plan_state}\n\n" + "\n\n".join(blocks) + "\n"
    )


def _ticket_status(state: str) -> str:
    return {
        "pending": "backlog",
        "implemented": "review",
        "closed/verified": "done",
        "closed/failed": "review",
    }.get(state, "backlog")


def _write_quarterdeck(plan: BuildPlan, target_dir: Path) -> Path:
    quarterdeck = target_dir / "QuarterDeck"
    quarterdeck.mkdir(parents=True, exist_ok=True)
    runtime = get_quarterdeck_root()
    for name in ("app.py", "requirements.txt"):
        source = runtime / name
        if source.is_file():
            shutil.copyfile(source, quarterdeck / name)

    ac_by_parent: dict[str, list[str]] = {}
    for block in plan.blocks:
        if block.block_type == "ac" and block.parent:
            ac_by_parent.setdefault(block.parent, []).append(block.name)
    tickets = []
    for block in plan.blocks:
        if block.block_type == "ac":
            continue
        ticket = {
            "id": block.block_id,
            "title": block.name,
            "kind": block.block_type,
            "status": _ticket_status(block.state),
            "body": str(block.fields.get("summary", "")),
        }
        if block.parent:
            ticket["parent"] = block.parent
        if ac_by_parent.get(block.block_id):
            ticket["ac"] = ac_by_parent[block.block_id]
        tickets.append(ticket)
    (quarterdeck / "tickets.json").write_text(
        json.dumps({"tickets": tickets}, indent=2) + "\n", encoding="utf-8"
    )
    (quarterdeck / "planning-session.md").write_text(
        f"# Planning Session: {plan.project}\n\n"
        f"Plan state: **{plan.state}**\n\n"
        "Review the proposed decomposition and acceptance gates on the Delivery Board. "
        "Approve the complete plan here before building.\n",
        encoding="utf-8",
    )
    config = f"""console:
  name: {plan.project} Planning Session
  default_item: planning_session
  state_db: data/console_state.sqlite

project:
  id: {_slug(plan.project)}
  name: {plan.project}
  description: "Review and approve the executable Drydock plan."

sections:
  - {{ id: core, label: "Drydock Core", dot: "#0d9488", pinned: true }}
  - {{ id: build_plan, label: "Build Plan", dot: "#d97706" }}

items:
  - {{ id: planning_session, label: "Planning Session", section: core, type: plan_decision, plan_path: {json.dumps(str(plan.path))} }}
  - {{ id: board, label: "Delivery Board", section: build_plan, type: kanban, path: tickets.json }}
"""
    (quarterdeck / "console.yaml").write_text(config, encoding="utf-8")
    return quarterdeck


def create_plan(
    blueprint: str,
    target: str,
    blueprint_directory: Path,
    target_directory: Path,
) -> PlanCreateResult:
    blueprint_dir = blueprint_directory / blueprint
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")
    init_plan_intent(blueprint, blueprint_directory)
    inputs = _ordered_inputs(blueprint_dir)
    target_dir = target_directory / target
    target_dir.mkdir(parents=True, exist_ok=True)
    plan_path = target_dir / "BUILD_PLAN.md"
    old = parse_build_plan(plan_path) if plan_path.is_file() else None
    text = _generate_plan_text(blueprint, blueprint_dir, inputs, old)
    changed = not plan_path.is_file() or plan_path.read_text(encoding="utf-8") != text
    plan_path.write_text(text, encoding="utf-8", newline="\n")
    plan = parse_build_plan(plan_path)
    quarterdeck = _write_quarterdeck(plan, target_dir)
    return PlanCreateResult(
        plan=plan, target_dir=target_dir, quarterdeck_dir=quarterdeck, changed=changed
    )
