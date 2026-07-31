"""Project Blueprint questions into Manifest story-local execution gates."""

from __future__ import annotations

import re
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.manifest import DrydockManifest
from drydock.questions import parse_questions


def synchronize_manifest_question_gates(
    manifest_path: Path,
    blueprint_dir: Path,
    *,
    persist: bool = True,
) -> DrydockManifest:
    """Synchronize question counts and block only affected story nodes."""
    manifest = DrydockManifest.load(manifest_path, compatibility=True)
    changed = False
    for node in manifest.blocks:
        if node.block_type != "story":
            continue
        implements = node.fields.get("implements", ())
        names = implements if isinstance(implements, tuple) else (str(implements),)
        paths = tuple(
            blueprint_dir / str(name)
            for name in names
            if name
            and (blueprint_dir / str(name)).is_file()
            and (blueprint_dir / str(name)).suffix.lower() == ".md"
        )
        if not paths:
            continue
        governed = tuple(
            (path, text)
            for path in paths
            if re.search(
                r"^## Questions\s*$",
                (text := path.read_text(encoding="utf-8")),
                re.MULTILINE,
            )
        )
        if not governed:
            continue
        questions = tuple(
            question
            for path, text in governed
            for question in parse_questions(text, source=str(path))
        )
        open_count = sum(item.status == "open" for item in questions)
        answered_count = sum(item.status == "answered" for item in questions)
        summary = f"{open_count} open, {answered_count} answered"
        approved = str(node.fields.get("questions_approved", "")).lower() == "true"
        updates: dict[str, str | None] = {}
        if node.fields.get("questions") != summary:
            updates["questions"] = summary
        if open_count and not approved and node.state != "blocked/questions":
            updates["state"] = "blocked/questions"
        elif (not open_count or approved) and node.state == "blocked/questions":
            updates["state"] = "pending"
        if not open_count and "questions_approved" in node.fields:
            updates["questions_approved"] = None
        if updates:
            manifest.set_fields(node.block_id, **updates)
            changed = True
    if changed and persist:
        manifest.save()
    return manifest


def approve_story_questions(manifest_path: Path, story_id: str) -> DrydockManifest:
    """Record a current-Manifest-only override for one question-blocked story."""
    manifest = DrydockManifest.load(manifest_path, compatibility=True)
    node = manifest.node(story_id)
    if node.block_type != "story":
        raise SpecificationError(f"{story_id!r} is not a story")
    questions = str(node.fields.get("questions", ""))
    if not questions or questions.startswith("0 open"):
        raise SpecificationError(f"Story {story_id!r} has no unanswered questions")
    manifest.set_fields(story_id, questions_approved="true", state="pending")
    manifest.save()
    return manifest
