#!/usr/bin/env python3
"""Rewrite a material file into a disclosure-checked blog draft using one agent call."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from devblog_lib import (
    clean_agent_markdown,
    draft_prompt,
    load_shell_config,
    load_text,
    material_cursor_path,
    maybe_load_text,
    parse_frontmatter,
    render_frontmatter,
    run_agent,
    sanitize_text,
    save_cursor,
    slugify,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("material", help="Material markdown file created by scripts/create.py")
    parser.add_argument("--output", help="Draft markdown file to write")
    parser.add_argument("--title", help="Override the generated title")
    parser.add_argument(
        "--type", choices=["devnote", "milestone"], help="Override the generated post type"
    )
    parser.add_argument("--date", help="Override the publication date (YYYY-MM-DD)")
    parser.add_argument("--label", help="Label to carry through output naming when useful")
    parser.add_argument(
        "--agent", choices=["claude", "codex"], help="Override the configured subscription CLI"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_shell_config()
    posts_dir = Path(cfg["POSTS_DIR"])
    posts_dir.mkdir(parents=True, exist_ok=True)

    material_path = Path(args.material)
    parsed = parse_frontmatter(material_path.read_text(encoding="utf-8"))
    # The post is dated by the work it covers, not by when it was generated.
    date_value = args.date or str(
        parsed.frontmatter.get("window_end")
        or parsed.frontmatter.get("date", datetime.now().date().isoformat())
    )
    title = args.title or str(
        parsed.frontmatter.get(
            "suggested_title", parsed.frontmatter.get("title", "Drydock development note")
        )
    )
    post_type = args.type or str(parsed.frontmatter.get("suggested_type", "devnote"))
    agent = args.agent or cfg["AGENT"]
    generation = load_text(Path(cfg["GENERATION"]))
    disclosure = load_text(Path(cfg["DISCLOSURE"]))
    branding_posts = maybe_load_text(Path(cfg["BRANDING_POSTS"]))
    branding_main = maybe_load_text(Path(cfg["BRANDING_MAIN"]))
    prompt = draft_prompt(
        generation,
        disclosure,
        material_path.read_text(encoding="utf-8"),
        date_value,
        post_type,
        branding_posts=branding_posts,
        branding_main=branding_main,
    )
    result = run_agent(prompt, agent)
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        print(f"format: {agent} rewrite failed for {material_path}", file=sys.stderr)
        return result.returncode
    rendered = clean_agent_markdown(result.stdout)
    generated = parse_frontmatter(rendered)
    if not generated.frontmatter.get("title"):
        print("format: agent output did not include YAML frontmatter.", file=sys.stderr)
        return 2
    if args.title:
        generated.frontmatter["title"] = sanitize_text(title)
    if args.type:
        generated.frontmatter["type"] = post_type
    generated.frontmatter["date"] = date_value
    generated.frontmatter.pop("tags", None)
    generated.frontmatter.pop("subtitle", None)

    title_value = sanitize_text(str(generated.frontmatter.get("title", title)))
    filename = f"{date_value}-{slugify(title_value)}.md"
    output = Path(args.output) if args.output else posts_dir / filename
    output.write_text(
        render_frontmatter(generated.frontmatter) + "\n\n" + generated.body.strip() + "\n",
        encoding="utf-8",
    )

    lint = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "check_disclosure.py"), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    if lint.stdout.strip():
        print(lint.stdout.strip())
    if lint.stderr.strip():
        print(lint.stderr.strip(), file=sys.stderr)
    if lint.returncode != 0:
        print(f"format: wrote {output}, but disclosure lint flagged issues.", file=sys.stderr)
        return lint.returncode

    last_event_id = str(parsed.frontmatter.get("last_event_id", ""))
    if last_event_id:
        save_cursor(material_cursor_path(cfg), last_event_id)

    print(f"format: wrote {output} with one {agent} subscription call")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
