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
    parser = argparse.ArgumentParser(description="Score one validation case from raw evidence.")
    parser.add_argument("spec", type=Path, help="Path to validation/specs/<slug>.md")
    parser.add_argument("result", type=Path, help="Path to result.json emitted by test_<slug>.sh")
    parser.add_argument("--output-json", type=Path, help="Write scored JSON to this path.")
    parser.add_argument("--output-md", type=Path, help="Write Markdown scorecard to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    _bootstrap_repo_imports()
    from drydock.validation_harness import (
        load_result_payload,
        parse_case_spec,
        render_case_markdown,
        score_case,
    )

    parser = build_parser()
    args = parser.parse_args(argv)
    spec = parse_case_spec(args.spec)
    payload = load_result_payload(args.result)
    scored = score_case(spec, payload, result_path=args.result)
    if args.output_json:
        args.output_json.write_text(json.dumps(scored.to_dict(), indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(render_case_markdown(scored) + "\n", encoding="utf-8")
    print(json.dumps(scored.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
