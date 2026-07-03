#!/usr/bin/env python3
"""Create a persisted daily material file from Drydock Ship's Log."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from devblog_lib import (
    collect_tags,
    event_paragraph,
    load_cursor,
    load_shell_config,
    load_ships_log,
    material_cursor_path,
    relative_event_window,
    render_frontmatter,
    sanitize_text,
    select_events,
    select_period_events,
    select_window_events,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ships-log", help="Path to ships_log.jsonl")
    parser.add_argument("--output", help="Material markdown file to write")
    parser.add_argument(
        "--date", default=datetime.now().date().isoformat(), help="Material date (YYYY-MM-DD)"
    )
    parser.add_argument("--label", help="Material file label; defaults to the date")
    parser.add_argument(
        "--period-days",
        type=int,
        help="Select the next contiguous batch of unseen events spanning this many days",
    )
    parser.add_argument(
        "--window-start", help="Include only unseen events dated on/after this date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--window-end", help="Include only unseen events dated on/before this date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum events to include (default: unlimited with --period-days, else 5)",
    )
    parser.add_argument(
        "--event-id", action="append", default=[], help="Specific Ship's Log event id to include"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ignore the saved cursor and rebuild from the most recent events",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_shell_config()
    ships_log = Path(args.ships_log or cfg["SHIPS_LOG"]).resolve()
    material_dir = Path(cfg["MATERIAL_DIR"])
    material_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or args.date
    output = Path(args.output) if args.output else material_dir / f"{label}.md"
    cursor_file = material_cursor_path(cfg)

    records = load_ships_log(ships_log)
    cursor = {} if args.all or args.event_id else load_cursor(cursor_file)
    # A period window must see every unseen event before it filters by date,
    # otherwise a busy week gets truncated before the window logic ever runs.
    windowed = bool(args.window_start or args.window_end)
    limit = args.limit if args.limit is not None else (0 if (args.period_days or windowed) else 5)
    events = select_events(
        records,
        explicit_ids=args.event_id,
        last_event_id=cursor.get("last_event_id"),
        limit=max(limit, 0),
    )
    if windowed:
        events = select_window_events(events, start=args.window_start, end=args.window_end)
    elif args.period_days:
        events = select_period_events(events, days=args.period_days)
    if not events:
        print("create: no eligible Ship's Log events found for the requested selection.")
        return 0

    tags = collect_tags(events)
    window_start, window_end = relative_event_window(events)
    # An explicit window defines the published period (and therefore the post
    # date), even when the events cluster inside a narrower span.
    if args.window_start:
        window_start = args.window_start
    if args.window_end:
        window_end = args.window_end
    title = f"Drydock source material for {label}"
    intro = (
        f"This material file captures {len(events)} recent Drydock ship's log "
        f"entries in plain English so they can be reused in later blog drafting "
        f"or a richer rendering pass."
    )
    sections = [intro, ""]
    for event in events:
        sections.append(f"## {sanitize_text(str(event.get('title', 'Untitled event')))}")
        sections.append("")
        sections.append(event_paragraph(event))
        sections.append("")

    frontmatter = {
        "title": title,
        "date": args.date,
        "label": label,
        "material_type": "ships-log-daily",
        "period_days": str(args.period_days or ""),
        "event_count": str(len(events)),
        "window_start": window_start,
        "window_end": window_end,
        "last_event_id": str(events[-1].get("event_id", "")),
        "suggested_type": "devnote" if len(events) == 1 else "milestone",
        "suggested_title": sanitize_text(str(events[0].get("title", title)))
        if len(events) == 1
        else title,
        "tags": tags,
    }
    content = render_frontmatter(frontmatter) + "\n\n" + "\n".join(sections).strip() + "\n"
    output.write_text(content, encoding="utf-8")

    print(f"create: wrote {output} from {len(events)} Ship's Log event(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
