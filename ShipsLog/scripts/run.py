#!/usr/bin/env python3
"""Create material, format it with one agent call, and render a post preview."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from devblog_lib import load_shell_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ships-log", help="Path to ships_log.jsonl")
    parser.add_argument(
        "--date", default=datetime.now().date().isoformat(), help="Run date (YYYY-MM-DD)"
    )
    parser.add_argument("--label", help="Material file label; defaults to the date")
    parser.add_argument(
        "--period-days",
        type=int,
        default=7,
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
        help="Maximum new events to include (default: unlimited within the period window)",
    )
    parser.add_argument(
        "--event-id", action="append", default=[], help="Specific Ship's Log event id to include"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ignore the saved cursor and rebuild from the newest events",
    )
    parser.add_argument(
        "--agent", choices=["claude", "codex"], help="Override the configured subscription CLI"
    )
    parser.add_argument(
        "--type", choices=["devnote", "milestone"], help="Override the generated post type"
    )
    return parser


def run_step(args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    return proc


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_shell_config()
    label = args.label or args.date
    material_path = Path(cfg["MATERIAL_DIR"]) / f"{label}.md"

    create_cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "create.py"),
        "--date",
        args.date,
    ]
    if args.limit is not None:
        create_cmd.extend(["--limit", str(args.limit)])
    if args.label:
        create_cmd.extend(["--label", args.label])
    windowed = bool(args.window_start or args.window_end)
    if args.window_start:
        create_cmd.extend(["--window-start", args.window_start])
    if args.window_end:
        create_cmd.extend(["--window-end", args.window_end])
    if args.period_days and not windowed:
        create_cmd.extend(["--period-days", str(args.period_days)])
    if args.ships_log:
        create_cmd.extend(["--ships-log", args.ships_log])
    if args.all:
        create_cmd.append("--all")
    for event_id in args.event_id:
        create_cmd.extend(["--event-id", event_id])
    create_proc = run_step(create_cmd)
    if create_proc.returncode != 0:
        return create_proc.returncode

    format_cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "format.py"),
        str(material_path),
    ]
    if args.label:
        format_cmd.extend(["--label", args.label])
    if args.agent:
        format_cmd.extend(["--agent", args.agent])
    if args.type:
        format_cmd.extend(["--type", args.type])
    format_proc = run_step(format_cmd)
    if format_proc.returncode != 0:
        return format_proc.returncode

    post_line = next(
        (line for line in format_proc.stdout.splitlines() if line.startswith("format: wrote ")), ""
    )
    post_path = post_line.replace("format: wrote ", "").split(" with one ", 1)[0].strip()
    if not post_path:
        return 2
    render_proc = run_step([
        sys.executable,
        str(Path(__file__).resolve().parent / "render.py"),
        post_path,
    ])
    return render_proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
