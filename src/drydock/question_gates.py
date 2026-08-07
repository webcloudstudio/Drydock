"""Project blocking decisions into Manifest story execution gates."""

from __future__ import annotations

from pathlib import Path

from drydock.decisions import load_decisions
from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest
from drydock.override import STORY_QUESTION, WaivedGate


def synchronize_manifest_question_gates(
    manifest_path: Path,
    blueprint_dir: Path,
    *,
    persist: bool = True,
    override: bool = False,
    waivers: list[WaivedGate] | None = None,
) -> DrydockManifest:
    """Block only stories attached to unanswered blocking DECISIONS records.

    Under ``override`` the attachment is recorded as a waiver instead of a gate: the story stays
    ``pending``, and a story already parked at ``blocked/questions`` is released.
    """
    del blueprint_dir  # attachment is persisted on the decision record
    manifest = DrydockManifest.load(manifest_path, compatibility=True)
    decisions = load_decisions(manifest_path.parent / "DECISIONS.json")
    blocking = {
        item
        for item in decisions
        if not item.archived and item.severity == "blocking" and not item.answer
    }
    changed = False
    for node in manifest.blocks:
        if node.block_type != "story":
            continue
        attached = [item for item in blocking if item.story == node.block_id]
        if not attached or override:
            if attached and waivers is not None:
                for item in attached:
                    waivers.append(
                        WaivedGate(
                            kind=STORY_QUESTION,
                            subject=node.block_id,
                            detail=(item.title or item.id).strip(),
                        )
                    )
            if node.state == "blocked/questions":
                manifest.set_fields(node.block_id, state="pending")
                changed = True
            continue
        updates: dict[str, str | None] = {}
        if node.state != "blocked/questions":
            updates["state"] = "blocked/questions"
        if updates:
            manifest.set_fields(node.block_id, **updates)
            changed = True
    if changed and persist:
        manifest.save()
    return manifest


def approve_story_questions(manifest_path: Path, story_id: str) -> DrydockManifest:
    """Reject the obsolete story-local approval escape hatch."""
    raise SpecificationError(
        f"{story_id!r} is governed by blocking DECISIONS.json records; answer the decision"
    )
