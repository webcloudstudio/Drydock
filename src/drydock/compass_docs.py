"""Canonical metadata for target-root editable guidance documents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetDoc:
    item_id: str
    filename: str
    label: str
    default_text: str | None
    help_text: str
    prompt_text: str


_DOCS: tuple[TargetDoc, ...] = (
    TargetDoc(
        item_id="blockers_doc",
        filename="BLOCKERS.md",
        label="Blockers",
        default_text=None,
        help_text=(
            "Analyze writes this file only when planning is blocked. Answer the blocking questions "
            "directly in the document; clearing it unblocks downstream steps."
        ),
        prompt_text=(
            "Keep each blocker explicit: what is missing, why Drydock cannot proceed, and the "
            "human answer needed to resolve it."
        ),
    ),
    TargetDoc(
        item_id="compass_edit",
        filename="COMPASS.md",
        label="Compass",
        default_text=None,
        help_text=(
            "This file is injected into every build step as orientation for the builder. Keep it "
            "brief, directive, and free of duplicated source detail."
        ),
        prompt_text=(
            "Record only project intent, constraints, and guardrails that every implementation step "
            "must honor."
        ),
    ),
    TargetDoc(
        item_id="analyze_compass",
        filename="ANALYZE_COMPASS.md",
        label="Analyze Compass",
        default_text="# Analyze Compass\n",
        help_text=(
            "This file is injected into every `drydock analyze` run for this target. Keep only "
            "brief steering: priorities, decomposition guidance, and hard constraints."
        ),
        prompt_text=(
            "State the analysis steering, not restatements of the source material. Short directives "
            "only; the heading is the only seeded file content."
        ),
    ),
    TargetDoc(
        item_id="plan_compass",
        filename="PLAN_COMPASS.md",
        label="Plan Compass",
        default_text="# Plan Compass\n",
        help_text=(
            "This file is injected into every `drydock plan` run for this target. Use it to steer "
            "decomposition, ordering, and durable file boundaries."
        ),
        prompt_text=(
            "Capture planning directives only: decomposition preferences, ordering rules, and any "
            "non-default planning constraints."
        ),
    ),
)

_DOCS_BY_ITEM = {doc.item_id: doc for doc in _DOCS}
_DOCS_BY_FILE = {doc.filename: doc for doc in _DOCS}


def target_doc(item_id: str) -> TargetDoc | None:
    return _DOCS_BY_ITEM.get(item_id)


def target_doc_for_file(filename: str) -> TargetDoc | None:
    return _DOCS_BY_FILE.get(filename)


def target_docs() -> tuple[TargetDoc, ...]:
    return _DOCS
