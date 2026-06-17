#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_repo_imports() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate one validation run directory.")
    parser.add_argument("run_dir", type=Path, help="Path to validation/reports/<run-id>")
    parser.add_argument("--output-json", type=Path, help="Write summary JSON to this path.")
    parser.add_argument("--output-md", type=Path, help="Write summary Markdown to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    _bootstrap_repo_imports()
    from drydock.validation_harness import render_summary_markdown

    parser = build_parser()
    args = parser.parse_args(argv)
    scored_files = sorted(args.run_dir.glob("*/scored.json"))
    if not scored_files:
        raise SystemExit(f"no scored.json files found under {args.run_dir}")
    cases = [json.loads(path.read_text(encoding="utf-8")) for path in scored_files]
    recurring: dict[str, int] = {}
    for case in cases:
        for gap in case.get("gaps", []):
            recurring[gap] = recurring.get(gap, 0) + 1
    average_score = round(sum(int(case["score"]) for case in cases) / len(cases))
    top_gap = ""
    if recurring:
        top_gap = sorted(recurring.items(), key=lambda item: (-item[1], item[0]))[0][0]
    payload = {
        "case_count": len(cases),
        "average_score": average_score,
        "band": next(
            name
            for threshold, name in ((90, "SEAWORTHY"), (75, "SEA_TRIALS"), (60, "TAKING_WATER"), (0, "DRY_DOCK"))
            if average_score >= threshold
        ),
        "all_passed": all(bool(case["passed"]) for case in cases),
        "top_gap": top_gap,
        "recurring_gaps": dict(sorted(recurring.items(), key=lambda item: (-item[1], item[0]))),
        "cases": sorted(cases, key=lambda case: case["slug"]),
    }
    if args.output_json:
        args.output_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(render_summary_markdown(payload) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
