"""Phase-aware Commander's Chair builder.

``refresh_commanders_chair(target_dir)`` regenerates ``commanders_chair.html``
to reflect the target's current lifecycle phase (analyzed → planned → building).
Each phase shows the KPIs and story detail that are meaningful at that stage.

Called as a best-effort side-effect at the end of ``analyze``, ``plan create``,
``build``, and ``build verify``.  Any exception is swallowed so callers never
abort on a display failure.
"""

from __future__ import annotations

import json
import re
from datetime import date
from html import escape
from pathlib import Path

from drydock.metadata import get_build_state
from drydock.paths import get_quarterdeck_template_dir

# ---------------------------------------------------------------------------
# Constants shared with analyze.py (duplicated to avoid circular imports)
# ---------------------------------------------------------------------------

_QUESTIONNAIRE_DONE_STATES = {"done", "answered", "complete", "verified", "promoted"}

_QUALITY_META: dict[str, tuple[str, str, str]] = {
    "Ready": ("ready", "✓", "All blockers resolved. Ready for planning."),
    "Questions": ("questions", "⚠", "Open questions remain. Planning can proceed."),
    "Blocked": ("blocked", "✗", "Unresolved blockers. Review before continuing."),
}

_STORY_SECTION_RE = re.compile(
    r"^###\s+(?:(?:Feature Area|Feature)\s+\d+\s+—\s+|Feature:\s*)?(.+?)\s*$",
    re.MULTILINE,
)
_STORY_ROW_RE = re.compile(r"^\|\s*([A-Z][A-Z0-9-]+)\s*\|", re.MULTILINE)

# ---------------------------------------------------------------------------
# Badge CSS classes for story states (used in plan/build phases)
# ---------------------------------------------------------------------------

_STATE_BADGE: dict[str, tuple[str, str]] = {
    "pending": ("badge-pending", "pending"),
    "implemented": ("badge-review", "review"),
    "closed/verified": ("badge-verified", "done"),
    "closed/failed": ("badge-failed", "failed"),
}

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def refresh_commanders_chair(target_dir: Path) -> Path | None:
    """Regenerate commanders_chair.html for ``target_dir``'s current lifecycle phase.

    Returns the written path, or ``None`` if the template is missing or any
    error occurs.  Never raises.
    """
    try:
        template_path = get_quarterdeck_template_dir() / "commanders_chair.html"
        if not template_path.is_file():
            return None
        template = template_path.read_text(encoding="utf-8")
        today = date.today().isoformat()
        phase = get_build_state(target_dir)

        if phase in ("init", "analyzed"):
            html = _chair_for_analyzed(target_dir, template, today)
        elif phase == "planned":
            html = _chair_for_planned(target_dir, template, today)
        else:
            html = _chair_for_building(target_dir, template, today)

        if html is None:
            return None

        chair_path = target_dir / "QuarterDeck" / "commanders_chair.html"
        chair_path.parent.mkdir(parents=True, exist_ok=True)
        chair_path.write_text(html, encoding="utf-8", newline="\n")
        return chair_path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Phase builders
# ---------------------------------------------------------------------------


def _chair_for_analyzed(target_dir: Path, template: str, today: str) -> str | None:
    """Build the Chair HTML for the ``analyzed`` phase."""
    analysis_path = target_dir / "ANALYSIS.md"
    blockers_path = target_dir / "BLOCKERS.md"
    questionnaires_dir = target_dir / "QuarterDeck" / "questionnaires"

    analysis_text = analysis_path.read_text(encoding="utf-8") if analysis_path.is_file() else ""
    blockers_text = blockers_path.read_text(encoding="utf-8") if blockers_path.is_file() else None

    story_items = _story_items(analysis_text)
    question_items = _question_items(questionnaires_dir)
    blocker_items = _blocker_items(blockers_text)
    feature_items = _feature_items(analysis_text)

    story_count = len(story_items)
    question_count = len(question_items)
    blocker_count = 1 if blockers_text and blockers_text.strip() else 0
    feature_count = len(feature_items)

    quality = "Blocked" if blocker_count else ("Questions" if question_count else "Ready")
    target_name = target_dir.name

    stats_html = _stat_cards([
        (None, str(feature_count), "Features"),
        ("#stories", str(story_count), "Stories"),
        (None, str(question_count), "Questionnaires"),
        (None, str(blocker_count), "Blockers"),
    ])

    return _fill_chair(
        template,
        project_name=target_name,
        phase_label="Analyzed",
        generated_date=today,
        quality=quality,
        stats_html=stats_html,
        next_step=_analyzed_next_step(quality, target_name),
        question_count=question_count,
        stories_html=_list_html(story_items, empty="No stories found."),
        questions_html=_list_html(question_items, empty="No open questionnaires."),
        blockers_html=_list_html(blocker_items, empty="No blockers."),
        screens_html=_list_html(feature_items, empty="No features found."),
    )


def _chair_for_planned(target_dir: Path, template: str, today: str) -> str | None:
    """Build the Chair HTML for the ``planned`` phase."""
    from drydock.build_plan import parse_build_plan

    manifest_path = target_dir / "MANIFEST.md"
    if not manifest_path.is_file():
        return _chair_for_analyzed(target_dir, template, today)

    plan = parse_build_plan(manifest_path)
    target_name = target_dir.name

    stories = [b for b in plan.blocks if b.block_type in ("story", "spike")]
    features = [b for b in plan.blocks if b.block_type == "feature"]
    spikes = [b for b in plan.blocks if b.block_type == "spike"]

    stats_html = _stat_cards([
        (None, str(len(stories)), "Stories"),
        (None, str(len(features)), "Features"),
        (None, str(len(spikes)), "Spikes"),
        (None, plan.state.capitalize(), "Plan State"),
    ])

    if plan.state == "draft":
        next_step = f"Approve the manifest, then run: drydock build {target_name}"
    else:
        next_step = f"drydock build {target_name}"

    stories_html = _manifest_story_list(plan)

    return _fill_chair(
        template,
        project_name=target_name,
        phase_label="Planned",
        generated_date=today,
        quality="Ready",
        stats_html=stats_html,
        next_step=next_step,
        question_count=0,
        stories_html=stories_html,
        questions_html="",
        blockers_html="",
        screens_html="",
    )


def _chair_for_building(target_dir: Path, template: str, today: str) -> str | None:
    """Build the Chair HTML for the ``building`` / ``built`` phase."""
    from drydock.build_plan import parse_build_plan
    from drydock.build_status import build_status

    manifest_path = target_dir / "MANIFEST.md"
    if not manifest_path.is_file():
        return _chair_for_analyzed(target_dir, template, today)

    plan = parse_build_plan(manifest_path)
    status = build_status(plan)
    target_name = target_dir.name

    pct = status.percent_complete()
    stats_html = _stat_cards([
        (None, f"{pct}%", "Complete"),
        (None, str(status.steps_verified), "Verified"),
        (None, str(status.steps_implemented), "In Review"),
        (None, str(status.steps_failed), "Failed"),
    ])

    next_step = _build_next_step(status, plan, target_name)
    stories_html = _build_story_list(status)

    return _fill_chair(
        template,
        project_name=target_name,
        phase_label="Building",
        generated_date=today,
        quality="Ready",
        stats_html=stats_html,
        next_step=next_step,
        question_count=0,
        stories_html=stories_html,
        questions_html="",
        blockers_html="",
        screens_html="",
    )


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------


def _stat_cards(cards: list[tuple[str | None, str, str]]) -> str:
    """Render a row of stat cards.  Each card is (optional_href, value, label)."""
    parts: list[str] = []
    for href, value, label in cards:
        if href:
            parts.append(
                f'<a class="stat" href="{href}">'
                f'<div class="stat-value">{escape(value)}</div>'
                f'<div class="stat-label">{escape(label)}</div>'
                f"</a>"
            )
        else:
            parts.append(
                f'<div class="stat">'
                f'<div class="stat-value">{escape(value)}</div>'
                f'<div class="stat-label">{escape(label)}</div>'
                f"</div>"
            )
    return "\n".join(parts)


def _list_html(items: list[str], *, empty: str) -> str:
    if not items:
        return f'<p class="empty">{escape(empty)}</p>'
    rows = "\n".join(f"  <li>{escape(item)}</li>" for item in items)
    return f"<ul>\n{rows}\n</ul>"


def _manifest_story_list(plan) -> str:  # type: ignore[no-untyped-def]
    """Render manifest stories grouped by feature with [pending] badges."""
    by_feature: dict[str | None, list] = {}
    feature_names: dict[str, str] = {}
    for block in plan.blocks:
        if block.block_type == "feature":
            feature_names[block.block_id] = block.name
        if block.block_type in ("story", "spike"):
            by_feature.setdefault(block.parent, []).append(block)

    parts: list[str] = ['<div class="story-list">']
    for parent_id, stories in by_feature.items():
        if parent_id and parent_id in feature_names:
            parts.append(f'<div class="story-feature">{escape(feature_names[parent_id])}</div>')
        for s in stories:
            css, label = _STATE_BADGE.get(s.state, ("badge-pending", s.state))
            parts.append(
                f'<div class="story-row">'
                f'<span class="story-name">{escape(s.name)}</span>'
                f' <span class="badge {css}">{escape(label)}</span>'
                f"</div>"
            )
    parts.append("</div>")
    return "\n".join(parts)


def _build_story_list(status) -> str:  # type: ignore[no-untyped-def]
    """Render build-phase stories grouped by feature with colour-coded state badges."""
    parts: list[str] = ['<div class="story-list">']
    for group in status.groups:
        if group.name != "Ungrouped":
            parts.append(f'<div class="story-feature">{escape(group.name)}</div>')
        for step in group.steps:
            css, label = _STATE_BADGE.get(step.block.state, ("badge-pending", step.block.state))
            parts.append(
                f'<div class="story-row">'
                f'<span class="story-name">{escape(step.block.name)}</span>'
                f' <span class="badge {css}">{escape(label)}</span>'
                f"</div>"
            )
    parts.append("</div>")
    return "\n".join(parts)


def _fill_chair(
    template: str,
    *,
    project_name: str,
    phase_label: str,
    generated_date: str,
    quality: str,
    stats_html: str,
    next_step: str,
    question_count: int,
    stories_html: str,
    questions_html: str,
    blockers_html: str,
    screens_html: str,
) -> str:
    css_class, icon, desc = _QUALITY_META.get(quality, ("ready", "✓", quality))
    question_status = "Open questionnaires remain" if question_count else "No open questionnaires"
    if question_count:
        question_lead_html = (
            f'<h2>Questionnaires</h2><div class="question-status">{escape(question_status)}</div>'
        )
    else:
        question_lead_html = (
            '<div class="question-status question-status-inline">'
            f"<strong>Questionnaires:</strong> {escape(question_status)}</div>"
        )

    replacements = {
        "{{PROJECT_NAME}}": project_name,
        "{{PHASE_LABEL}}": phase_label,
        "{{GENERATED_DATE}}": generated_date,
        "{{QUALITY}}": quality,
        "{{QUALITY_CSS}}": css_class,
        "{{QUALITY_ICON}}": icon,
        "{{QUALITY_DESC}}": desc,
        "{{STATS_HTML}}": stats_html,
        "{{NEXT_STEP}}": next_step,
        "{{QUESTION_STATUS}}": question_status,
        "{{QUESTION_LEAD_HTML}}": question_lead_html,
        "{{STORIES_HTML}}": stories_html,
        "{{QUESTIONS_HTML}}": questions_html,
        "{{BLOCKERS_HTML}}": blockers_html,
        "{{SCREENS_HTML}}": screens_html,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


# ---------------------------------------------------------------------------
# Analyzed-phase helpers (parse ANALYSIS.md, BLOCKERS.md, questionnaires)
# ---------------------------------------------------------------------------


def _story_breakdown(analysis_text: str) -> list[tuple[str, int]]:
    body = _story_list_body(analysis_text)
    if not body:
        return []
    sections = list(_STORY_SECTION_RE.finditer(body))
    breakdown: list[tuple[str, int]] = []
    for index, match in enumerate(sections):
        start = match.end()
        end = sections[index + 1].start() if index + 1 < len(sections) else len(body)
        section_text = body[start:end]
        count = sum(1 for row in _STORY_ROW_RE.finditer(section_text) if row.group(1) not in {"ID"})
        if count:
            breakdown.append((match.group(1).strip(), count))
    return breakdown


def _render_story_breakdown_html(analysis_text: str) -> str:
    breakdown = _story_breakdown(analysis_text)
    if not breakdown:
        return ""
    items = "\n".join([
        '  <div class="story-breakdown-row">'
        f'<span class="story-breakdown-name">{escape(name)}</span>'
        f'<span class="story-breakdown-count">{count}</span>'
        "</div>"
        for name, count in breakdown
    ])
    return "\n".join([
        '<div class="story-breakdown">',
        '  <div class="story-breakdown-label">Story Shape</div>',
        items,
        "</div>",
    ])


def _story_items(analysis_text: str) -> list[str]:
    body = _story_list_body(analysis_text)
    if not body:
        return []
    items: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
            continue
        if not stripped.startswith("|") or set(stripped.replace("|", "").strip()) <= {"-"}:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0].lower() in {"id", "area", "#"}:
            continue
        if len(cells) >= 2 and cells[1].lower() in {"story", "stories"}:
            continue
        if len(cells) >= 2 and re.match(r"^[A-Z][A-Z0-9-]+$", cells[0]):
            items.append(f"{cells[0]} - {cells[1]}")
        elif len(cells) >= 2:
            items.append(f"{cells[0]} - {cells[1]}")
    return items


def _story_list_body(analysis_text: str) -> str:
    story_list = analysis_text.split("## Story List", 1)
    if len(story_list) != 2:
        return ""
    body = story_list[1]
    next_section = re.search(r"^##\s+", body, re.MULTILINE)
    if next_section:
        body = body[: next_section.start()]
    return body


def _feature_items(analysis_text: str) -> list[str]:
    return [name for name, _count in _story_breakdown(analysis_text)]


def _screen_items(analysis_text: str) -> list[str]:
    screens: list[str] = []
    body = _story_list_body(analysis_text)
    for heading in _STORY_SECTION_RE.findall(body):
        if "screen" in heading.lower():
            screens.append(heading.strip())
    for item in _story_items(analysis_text):
        if "screen" in item.lower() and item not in screens:
            screens.append(item)
    return screens


def _question_items(questionnaires_dir: Path) -> list[str]:
    if not questionnaires_dir.is_dir():
        return []
    items: list[str] = []
    for path in sorted(questionnaires_dir.glob("discovery-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            items.append(f"See questionnaire {path.name}")
            continue
        state = str(data.get("state", "open")).lower()
        if state in _QUESTIONNAIRE_DONE_STATES:
            continue
        label = str(data.get("title") or data.get("id") or path.stem)
        items.append(f"See questionnaire {label}")
    return items


def _blocker_items(blockers_text: str | None) -> list[str]:
    if not blockers_text:
        return []
    items = [
        match.group(1).strip()
        for match in re.finditer(r"^##\s+(.+?)\s*$", blockers_text, re.MULTILINE)
    ]
    return items or ["Review BLOCKERS.md"]


# ---------------------------------------------------------------------------
# Next-step logic
# ---------------------------------------------------------------------------


def _analyzed_next_step(quality: str, target: str) -> str:
    if quality == "Blocked":
        return f"Resolve blockers, then re-run: drydock analyze {target}"
    if quality == "Questions":
        return f"Review QuarterDeck action items, then run: drydock plan {target}"
    return f"drydock plan {target}"


def _build_next_step(status, plan, target: str) -> str:  # type: ignore[no-untyped-def]
    if status.steps_total == 0:
        return f"drydock build {target}"
    if status.steps_verified == status.steps_total:
        return f"drydock build score {target}"
    if status.steps_implemented:
        first_review = next(
            (
                step.block.block_id
                for group in status.groups
                for step in group.steps
                if step.block.state == "implemented"
            ),
            None,
        )
        if first_review:
            return f"drydock build verify {target} {first_review}"
    remaining = status.steps_pending
    return f"drydock build {target}  ({remaining} step{'s' if remaining != 1 else ''} remaining)"
