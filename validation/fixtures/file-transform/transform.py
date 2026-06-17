from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


def summarize_csv(input_path: Path) -> dict:
    rows = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    return {
        "count": len(rows),
        "names": [row["name"] for row in rows],
        "total_amount": sum(int(row["amount"]) for row in rows),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python transform.py <input.csv> <output.json>", file=sys.stderr)
        return 2
    input_path = Path(args[0])
    output_path = Path(args[1])
    if not input_path.is_file():
        print(f"missing input: {input_path}", file=sys.stderr)
        return 1
    summary = summarize_csv(input_path)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
