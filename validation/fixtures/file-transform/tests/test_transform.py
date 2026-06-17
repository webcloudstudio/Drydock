from __future__ import annotations

import json
from pathlib import Path

from transform import main, summarize_csv


def test_summarize_csv():
    summary = summarize_csv(Path("data/input.csv"))
    assert summary["count"] == 3
    assert summary["total_amount"] == 30


def test_main_writes_json(tmp_path):
    output = tmp_path / "out.json"
    rc = main(["data/input.csv", str(output)])
    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["names"] == ["alpha", "beta", "gamma"]
