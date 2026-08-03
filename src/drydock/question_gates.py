"""Project blocking decisions into Manifest story execution gates."""

from __future__ import annotations

from pathlib import Path

from drydock.decisions import load_decisions
from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest


def synchronize_manifest_question_gates(
    manifest_path: Path,
    blueprint_dir: Path,
    *,
    persist: bool = True,
) -> DrydockManifest:
    """Block only stories attached to unanswered blocking DECISIONS records."""
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
        if not attached:
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
