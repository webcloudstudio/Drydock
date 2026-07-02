"""Tests for drydock shipslog week-window computation and orchestration."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from drydock.errors import DrydockError, UsageError
from drydock.shipslog import (
    align_week_start,
    complete_week_windows,
    generate,
    load_package_config,
    resolve_package_dir,
)

THU = date(2026, 6, 11)  # a Thursday — an aligned week start


def _event(event_id: str, recorded: str, event_type: str = "decision") -> dict:
    return {
        "event_id": event_id,
        "recorded_at": f"{recorded}T12:00:00Z",
        "event_type": event_type,
        "title": f"Event {event_id}",
    }


def make_package(tmp_path: Path, events: list[dict], cursor: str | None = None) -> Path:
    package = tmp_path / "ShipsLog"
    (package / "blog" / "material").mkdir(parents=True)
    (package / "scripts").mkdir()
    ships_log = tmp_path / "ships_log.jsonl"
    ships_log.write_text(
        "".join(json.dumps(e) + "\n" for e in events),
        encoding="utf-8",
    )
    (package / "blog.config.sh").write_text(
        f'SHIPS_LOG="{ships_log}"\nAGENT="claude"\n',
        encoding="utf-8",
    )
    if cursor:
        (package / "blog" / "material" / ".ships_log_cursor.json").write_text(
            json.dumps({"last_event_id": cursor}),
            encoding="utf-8",
        )
    return package


class TestWeekWindows:
    def test_align_snaps_down_to_thursday(self):
        assert align_week_start(date(2026, 6, 11)) == THU  # Thursday itself
        assert align_week_start(date(2026, 6, 15)) == THU  # Monday inside the week
        assert align_week_start(date(2026, 6, 17)) == THU  # Wednesday, last day

    def test_no_window_until_week_fully_elapsed(self):
        assert complete_week_windows(THU, date(2026, 6, 17)) == []
        assert complete_week_windows(THU, date(2026, 6, 18)) == [(THU, date(2026, 6, 17))]

    def test_consecutive_aligned_windows(self):
        windows = complete_week_windows(date(2026, 6, 15), date(2026, 7, 2))
        assert windows == [
            (date(2026, 6, 11), date(2026, 6, 17)),
            (date(2026, 6, 18), date(2026, 6, 24)),
            (date(2026, 6, 25), date(2026, 7, 1)),
        ]


class TestResolvePackageDir:
    def test_explicit_dir_must_be_a_package(self, tmp_path):
        with pytest.raises(UsageError):
            resolve_package_dir(str(tmp_path))

    def test_explicit_dir_resolves(self, tmp_path):
        package = make_package(tmp_path, [])
        assert resolve_package_dir(str(package)) == package.resolve()

    def test_local_shipslog_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DRYDOCK_SHIPSLOG_DIR", raising=False)
        package = make_package(tmp_path, [])
        assert resolve_package_dir(None, cwd=tmp_path) == package

    def test_missing_everywhere_errors(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DRYDOCK_SHIPSLOG_DIR", raising=False)
        with pytest.raises(DrydockError):
            resolve_package_dir(None, cwd=tmp_path)

    def test_configured_dir(self, tmp_path, monkeypatch):
        package = make_package(tmp_path, [])
        monkeypatch.setenv("DRYDOCK_SHIPSLOG_DIR", str(package))
        assert resolve_package_dir(None, cwd=tmp_path / "elsewhere") == package


class TestGenerate:
    def test_one_post_per_complete_week_with_events(self, tmp_path):
        events = [
            _event("a", "2026-06-12"),
            _event("b", "2026-06-20", "milestone"),
            _event("c", "2026-07-02"),  # current week — never published
        ]
        package = make_package(tmp_path, events)
        calls: list[tuple[date, date]] = []

        def fake_runner(_package_dir, start, end):
            calls.append((start, end))
            return 0

        result = generate(package, today=date(2026, 7, 2), runner=fake_runner)
        assert calls == [
            (date(2026, 6, 11), date(2026, 6, 17)),
            (date(2026, 6, 18), date(2026, 6, 24)),
        ]
        statuses = [(w.start, w.status) for w in result.weeks]
        assert statuses == [
            (date(2026, 6, 11), "generated"),
            (date(2026, 6, 18), "generated"),
            (date(2026, 6, 25), "empty"),
        ]
        assert result.pending_window == (date(2026, 7, 2), date(2026, 7, 8))
        assert result.pending_events == 1
        assert result.exit_code() == 0

    def test_dry_run_invokes_nothing(self, tmp_path):
        package = make_package(tmp_path, [_event("a", "2026-06-12")])

        def exploding_runner(*_args):  # pragma: no cover - must not run
            raise AssertionError("dry run must not execute the pipeline")

        result = generate(package, today=date(2026, 7, 2), dry_run=True, runner=exploding_runner)
        assert [w.status for w in result.weeks] == ["planned", "empty", "empty"]

    def test_cursor_excludes_published_events(self, tmp_path):
        events = [_event("a", "2026-06-12"), _event("b", "2026-06-20")]
        package = make_package(tmp_path, events, cursor="a")
        calls: list[tuple[date, date]] = []
        generate(package, today=date(2026, 7, 2), runner=lambda _p, s, e: calls.append((s, e)) or 0)
        assert calls == [(date(2026, 6, 18), date(2026, 6, 24))]

    def test_failure_stops_and_sets_exit_code(self, tmp_path):
        events = [_event("a", "2026-06-12"), _event("b", "2026-06-20")]
        package = make_package(tmp_path, events)
        result = generate(package, today=date(2026, 7, 2), runner=lambda *_a: 1)
        assert [w.status for w in result.weeks] == ["failed"]
        assert result.exit_code() == 1

    def test_non_publishable_and_superseded_events_ignored(self, tmp_path):
        events = [
            _event("a", "2026-06-12"),
            {**_event("b", "2026-06-13"), "event_type": "note"},
            {**_event("c", "2026-06-19"), "supersedes": ["a"]},
        ]
        package = make_package(tmp_path, events)
        calls: list[tuple[date, date]] = []
        result = generate(
            package, today=date(2026, 7, 2), runner=lambda _p, s, e: calls.append((s, e)) or 0
        )
        # "a" is superseded and "b" is not publishable; only "c"'s week runs.
        assert calls == [(date(2026, 6, 18), date(2026, 6, 24))]
        assert result.exit_code() == 0

    def test_no_unseen_events_is_a_clean_noop(self, tmp_path):
        package = make_package(tmp_path, [_event("a", "2026-06-12")], cursor="a")
        result = generate(package, today=date(2026, 7, 2), runner=lambda *_a: 1)
        assert result.weeks == []
        assert result.exit_code() == 0

    def test_missing_ships_log_errors(self, tmp_path):
        package = make_package(tmp_path, [])
        (tmp_path / "ships_log.jsonl").unlink()
        with pytest.raises(DrydockError):
            generate(package, today=date(2026, 7, 2))


class TestLoadPackageConfig:
    def test_reads_simple_assignments_only(self, tmp_path):
        package = make_package(tmp_path, [])
        (package / "blog.config.sh").write_text(
            'SHIPS_LOG="/x/ships_log.jsonl"\nROOT="$(pwd)"\n# comment\n',
            encoding="utf-8",
        )
        cfg = load_package_config(package)
        assert cfg == {"SHIPS_LOG": "/x/ships_log.jsonl"}
