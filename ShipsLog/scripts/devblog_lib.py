#!/usr/bin/env python3
"""Shared helpers for the Ship's Log driven dev-blog pipeline."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RIGGING_DIR = "/mnt/c/Users/barlo/projects/Drydock/Rigging"

CFG_DEFAULTS = {
    "SHIPS_LOG": "/mnt/c/Users/barlo/projects/Drydock/logs/ships_log.jsonl",
    "MATERIAL_DIR": str(ROOT / "blog" / "material"),
    "POSTS_DIR": str(ROOT / "blog" / "posts"),
    "AGENT": "claude",
    "GENERATION": str(ROOT / "blog" / "GENERATION.md"),
    "DISCLOSURE": str(ROOT / "blog" / "DISCLOSURE.md"),
    # Live source, not a local copy: Rigging is Ed's maintained brand/voice source
    # and drifts over time; a frozen copy inside this package goes stale silently.
    "BRANDING_POSTS": f"{RIGGING_DIR}/BRANDING_POSTS.md",
    "BRANDING_MAIN": f"{RIGGING_DIR}/BRANDING_MAIN.md",
    "LOGO": "/mnt/c/Users/barlo/projects/Drydock/docs/drydock_logo.png",
}

SAFE_EVENT_TYPES = {"decision", "milestone"}

REPLACEMENTS = [
    (r"\b[\w.-]+/", "private path "),
    (r"\b[\w.-]+(?:/[\w.-]+)+/?\b", "private path"),
    (r"(?:/[A-Za-z0-9_.-]+){2,}", "private path"),
    (r"[A-Za-z]:\\[\\\w.\-]+", "private path"),
    (r"\b[\w.-]+\.(?:py|ts|tsx|js|rs|go|java|rb|c|cpp|h|sh|md|json|yaml|yml)\b", "internal file"),
    (r"\b[a-z]+(?:_[a-z0-9]+){1,}\b", "internal symbol"),
    (r"\b[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+\b", "internal reference"),
    (r"\b[a-z_][a-z0-9_]*=[A-Za-z0-9_]+\b", "internal setting"),
    (r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", "internal configuration name"),
    (r"--[a-z0-9-]+", "a command option"),
    (r"`[^`]+`", "internal term"),
]


@dataclass
class MaterialFile:
    frontmatter: dict[str, object]
    body: str


@dataclass
class AgentResult:
    stdout: str
    stderr: str
    returncode: int


def load_shell_config() -> dict[str, str]:
    cfg = dict(CFG_DEFAULTS)
    path = ROOT / "blog.config.sh"
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^(\w+)="([^"]*)"', line.strip())
        if match and match.group(1) in cfg:
            value = match.group(2)
            if "$" not in value:
                cfg[match.group(1)] = value
    return cfg


def load_ships_log(path: Path) -> list[dict]:
    records: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        records.append(json.loads(raw))
    records.sort(key=lambda item: item.get("recorded_at", ""))
    return records


def superseded_ids(records: list[dict]) -> set[str]:
    ids: set[str] = set()
    for record in records:
        for value in record.get("supersedes", []):
            if isinstance(value, str):
                ids.add(value)
    return ids


def load_cursor(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_cursor(path: Path, event_id: str) -> None:
    path.write_text(json.dumps({"last_event_id": event_id}, indent=2) + "\n", encoding="utf-8")


def material_cursor_path(cfg: dict[str, str]) -> Path:
    return Path(cfg["MATERIAL_DIR"]) / ".ships_log_cursor.json"


def select_events(
    records: list[dict],
    *,
    explicit_ids: list[str] | None = None,
    last_event_id: str | None = None,
    limit: int = 5,
) -> list[dict]:
    blocked = superseded_ids(records)
    candidates = [
        r
        for r in records
        if r.get("event_type") in SAFE_EVENT_TYPES and r.get("event_id") not in blocked
    ]
    if explicit_ids:
        wanted = set(explicit_ids)
        return [record for record in candidates if record.get("event_id") in wanted]
    if last_event_id:
        seen = False
        filtered: list[dict] = []
        for record in candidates:
            if seen:
                filtered.append(record)
            elif record.get("event_id") == last_event_id:
                seen = True
        candidates = filtered
    if limit > 0 and len(candidates) > limit:
        candidates = candidates[-limit:]
    return candidates


def select_period_events(records: list[dict], *, days: int) -> list[dict]:
    if not records or days <= 0:
        return records
    start_value = parse_iso_date(str(records[0].get("recorded_at", "")))
    start_date = datetime.strptime(start_value, "%Y-%m-%d").date()
    end_date = start_date + timedelta(days=days - 1)
    selected: list[dict] = []
    for record in records:
        record_date = datetime.strptime(
            parse_iso_date(str(record.get("recorded_at", ""))), "%Y-%m-%d"
        ).date()
        if record_date <= end_date:
            selected.append(record)
        else:
            break
    return selected


def select_window_events(
    records: list[dict], *, start: str | None = None, end: str | None = None
) -> list[dict]:
    """Keep only events dated inside an explicit [start, end] ISO date window."""
    selected: list[dict] = []
    for record in records:
        record_date = parse_iso_date(str(record.get("recorded_at", "")))
        if start and record_date < start:
            continue
        if end and record_date > end:
            break
        selected.append(record)
    return selected


def sanitize_text(text: str) -> str:
    cleaned = text.replace("\n", " ").strip()
    for pattern, replacement in REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace("  ", " ").strip(" -")
    return cleaned


def sentence(text: str) -> str:
    value = sanitize_text(text)
    if not value:
        return ""
    if value[-1] not in ".!?":
        value += "."
    return value[0].upper() + value[1:]


def plain_sentence(text: str) -> str:
    """Normalize whitespace and punctuation without scrubbing real content.

    Unlike sentence()/sanitize_text(), this keeps identifiers, paths, and flags
    intact: blog/material/ is a private working surface, never published, and
    the disclosure gate belongs at publish time (format.py's rewrite plus
    check_disclosure.py), not here where it only destroys the source signal.
    """
    value = text.replace("\n", " ").strip()
    value = re.sub(r"\s+", " ", value)
    if not value:
        return ""
    if value[-1] not in ".!?":
        value += "."
    return value[0].upper() + value[1:]


def event_paragraph(record: dict) -> str:
    title = plain_sentence(str(record.get("title", "Untitled event"))).rstrip(".")
    summary = plain_sentence(str(record.get("summary", "")))
    rationale = plain_sentence(str(record.get("rationale", "")))
    alternatives = record.get("alternatives", [])
    event_type = str(record.get("event_type", "decision"))
    parts = [
        f"{record.get('recorded_at', '')[:10]} ({event_type}): {title}.",
    ]
    if summary:
        parts.append(summary)
    if rationale:
        parts.append(f"The rationale was straightforward: {rationale[0].lower() + rationale[1:]}")
    rejected = []
    for item in alternatives:
        option = plain_sentence(str(item.get("option", ""))).rstrip(".")
        reason = plain_sentence(str(item.get("reason_rejected", "")))
        if option and reason:
            rejected.append(f"{option} was rejected because {reason[0].lower() + reason[1:]}")
    if rejected:
        parts.append("Rejected alternatives stayed visible: " + " ".join(rejected))
    return " ".join(part.strip() for part in parts if part.strip())


def collect_tags(records: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for record in records:
        for tag in record.get("tags", []):
            if not isinstance(tag, str):
                continue
            value = tag.strip().lower()
            if re.fullmatch(r"[a-z0-9-]+", value):
                counts[value] = counts.get(value, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [tag for tag, _count in ordered[:4]]


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or f"draft-{date.today().isoformat()}"


def render_frontmatter(frontmatter: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value)
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def parse_frontmatter(text: str) -> MaterialFile:
    if not text.startswith("---\n"):
        return MaterialFile({}, text.strip())
    end = text.find("\n---\n", 4)
    if end == -1:
        return MaterialFile({}, text.strip())
    raw_frontmatter = text[4:end]
    body = text[end + 5 :].strip()
    data: dict[str, object] = {}
    for line in raw_frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip() for item in value[1:-1].split(",") if item.strip()]
            data[key] = items
        else:
            data[key] = value
    return MaterialFile(data, body)


def strip_frontmatter(text: str) -> str:
    return parse_frontmatter(text).body


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def maybe_load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def parse_iso_date(value: str) -> str:
    return value[:10] if value else date.today().isoformat()


def run_agent(prompt: str, agent: str) -> AgentResult:
    if agent == "claude":
        proc = subprocess.run(
            ["claude", "-p"],
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
        )
    elif agent == "codex":
        runtime_home = prepare_codex_home()
        env = os.environ.copy()
        env["CODEX_HOME"] = str(runtime_home)
        proc = subprocess.run(
            ["codex", "exec", prompt],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    else:
        raise ValueError(f"unknown AGENT '{agent}'")
    return AgentResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def extract_brand_identity(branding_main: str) -> str:
    """Pull just the Identity/Feel line out of BRANDING_MAIN.md.

    BRANDING_MAIN.md is a CSS/typography/palette spec for the documentation
    website theme; none of that is relevant to a text-voice rewrite prompt.
    Only the one-line "feel" statement carries signal here.
    """
    match = re.search(r"^\s*-\s*\*\*Feel:\*\*\s*(.+)$", branding_main, re.MULTILINE)
    return match.group(1).strip() if match else ""


def draft_prompt(
    generation: str,
    disclosure: str,
    material_text: str,
    date_value: str,
    post_type: str,
    branding_posts: str = "",
    branding_main: str = "",
) -> str:
    prompt = (
        f"You are producing one {post_type} entry of the Drydock Development Log.\n\n"
        "Read the rules documents and the material file. Output only the finished Markdown post "
        "(YAML frontmatter plus body) and nothing else.\n\n"
        "Requirements:\n"
        "- The material file is the source of truth. Every bullet you write restates a real "
        "recorded event with its real date; invent nothing.\n"
        "- Follow GENERATION.md exactly: fixed-format title, lead paragraph, then "
        "'## Milestones' and '## Changes' sections of dated bullets.\n"
        "- Write in the voice of a canonical specification: present-tense, declarative, "
        "third-person, concrete. Name Drydock, its commands, and its components.\n"
        "- Do not write an essay, a thesis, a slogan, or a 'transferable principle'.\n"
        "- Frontmatter fields: title, date, type, summary only. No tags, no subtitle.\n"
        f"- Use the post date {date_value} (the end of the work window).\n\n"
        "===== GENERATION.md =====\n"
        f"{generation}\n\n"
        "===== DISCLOSURE.md =====\n"
        f"{disclosure}\n\n"
    )
    identity = extract_brand_identity(branding_main)
    if identity:
        prompt += "===== Identity =====\n" + identity + "\n\n"
    if branding_posts.strip():
        prompt += "===== BRANDING_POSTS.md =====\n" + branding_posts + "\n\n"
    prompt += "===== MATERIAL FILE =====\n" + material_text + "\n"
    return prompt


def clean_agent_markdown(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:markdown)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # The nested `claude -p` call inherits the operator's own global CLAUDE.md
    # contract and appends its completion terminator/section markers to raw
    # output; strip those so they never leak into a published post body.
    cleaned = re.sub(
        r"\n*-{3,}\s*(?:NEXT STEPS|QUESTIONS)\s*-{3,}.*",
        "",
        cleaned,
        flags=re.DOTALL,
    )
    cleaned = re.sub(r"\n*-{3,}\s*REQUEST COMPLETED\s*-{3,}\s*$", "", cleaned)
    return cleaned.strip() + "\n"


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def relative_event_window(records: list[dict]) -> tuple[str, str]:
    if not records:
        today = date.today().isoformat()
        return today, today
    dates = [parse_iso_date(str(record.get("recorded_at", ""))) for record in records]
    return min(dates), max(dates)


def prepare_codex_home() -> Path:
    runtime_home = Path(tempfile.mkdtemp(prefix="devblog-codex-", dir="/tmp"))
    auth_src = Path.home() / ".codex" / "auth.json"
    if auth_src.exists():
        runtime_home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(auth_src, runtime_home / "auth.json")
    return runtime_home
