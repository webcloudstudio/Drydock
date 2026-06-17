from __future__ import annotations

import json
import sys
from pathlib import Path


def load_items(db_path: Path) -> list[dict]:
    if not db_path.exists():
        return []
    return json.loads(db_path.read_text(encoding="utf-8"))


def save_items(db_path: Path, items: list[dict]) -> None:
    db_path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def cmd_add(db_path: Path, text: str) -> int:
    items = load_items(db_path)
    items.append({"text": text, "done": False})
    save_items(db_path, items)
    print(f"added: {text}")
    return 0


def cmd_list(db_path: Path) -> int:
    items = load_items(db_path)
    for index, item in enumerate(items, start=1):
        marker = "x" if item["done"] else " "
        print(f"{index}. [{marker}] {item['text']}")
    return 0


def cmd_done(db_path: Path, index_text: str) -> int:
    items = load_items(db_path)
    try:
        index = int(index_text) - 1
        items[index]["done"] = True
    except (ValueError, IndexError):
        print(f"invalid item: {index_text}", file=sys.stderr)
        return 1
    save_items(db_path, items)
    print(f"done: {index_text}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: python todo.py <db.json> <add|list|done> [value]", file=sys.stderr)
        return 2

    db_path = Path(args[0])
    command = args[1]
    if command == "add" and len(args) >= 3:
        return cmd_add(db_path, " ".join(args[2:]))
    if command == "list" and len(args) == 2:
        return cmd_list(db_path)
    if command == "done" and len(args) == 3:
        return cmd_done(db_path, args[2])
    print(f"unknown or invalid command: {' '.join(args[1:])}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
