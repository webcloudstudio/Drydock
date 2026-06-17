from __future__ import annotations

import json
from pathlib import Path

from todo import cmd_add, cmd_done, load_items, main


def test_add_and_done(tmp_path):
    db_path = tmp_path / "todo.json"
    assert cmd_add(db_path, "write tests") == 0
    assert cmd_done(db_path, "1") == 0
    items = load_items(db_path)
    assert items[0]["done"] is True


def test_main_list(tmp_path, capsys):
    db_path = tmp_path / "todo.json"
    db_path.write_text(json.dumps([{"text": "one", "done": False}]), encoding="utf-8")
    assert main([str(db_path), "list"]) == 0
    captured = capsys.readouterr()
    assert "one" in captured.out
