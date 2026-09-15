"""Validate acceptance repairs and release their obsolete decision gates."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from drydock.acceptance import malformed_criteria, parse_programmatic_acceptance_text
from drydock.decisions import load_decisions, write_decisions


def validate_acceptance_repair(before: str, after: str, source: str) -> str:
    """Reject broken or silently removed criteria without executing generated code."""
    try:
        checks = parse_programmatic_acceptance_text(after, source=source)
    except ValueError as error:
        return str(error)
    defects = malformed_criteria(checks)
    if defects:
        return "; ".join(item.rendered for item in defects)
    try:
        previous = parse_programmatic_acceptance_text(before, source=source)
    except ValueError:
        if not checks:
            return "repair removed the malformed acceptance container without replacing its checks"
        return ""
    missing = {item.check_id for item in previous} - {item.check_id for item in checks}
    if missing:
        return f"repair removed acceptance criteria: {', '.join(sorted(missing))}"
    return ""


def retire_repaired_decisions(target_dir: Path, originals: dict[str, str]) -> tuple[str, ...]:
    """Retire only malformed-check gates whose criterion was changed and now compiles.

    This clears an authoring impediment, not an acceptance verdict. Reset consumers must still
    execute the repaired checks during build. Commander-authored records are never overwritten.
    """
    from drydock.config import blueprint_dir_for

    blueprint = blueprint_dir_for(target_dir)
    repaired: set[str] = set()
    for source, before in originals.items():
        after = (blueprint / source).read_text(encoding="utf-8")
        if after == before or validate_acceptance_repair(before, after, source):
            continue
        checks = parse_programmatic_acceptance_text(after, source=source)
        try:
            previous = {
                item.check_id: item.code
                for item in parse_programmatic_acceptance_text(before, source=source)
            }
        except ValueError:
            previous = {}
        for item in checks:
            if previous.get(item.check_id) != item.code:
                repaired.add(f"acceptance-{source}-{item.check_id}-malformed")
                repaired.add(f"build-skip-{source}-{item.check_id}".lower().replace(" ", "-"))
        if checks:
            repaired.add(f"acceptance-{source}-container-malformed")
    path = target_dir / "DECISIONS.json"
    decisions = load_decisions(path)
    retired = tuple(
        item.id
        for item in decisions
        if item.id in repaired and not item.archived and not item.is_human_authored
    )
    if retired:
        write_decisions(
            path,
            tuple(
                replace(
                    item, archived=True, system_choice="Repaired by diagnose; rebuild verifies AC."
                )
                if item.id in retired
                else item
                for item in decisions
            ),
        )
    return retired
