"""Generate weekly development-log posts from the workspace Ship's Log.

Posts cover aligned Thursday-to-Wednesday weeks. A post is generated only for a
week that has fully elapsed and contains at least one unpublished decision or
milestone event, so the published index reads as a continuous chronological
record from the bottom of the page upward. The week in progress is never
published.

The rendering pipeline itself lives in the Ship's Log posts package (a
directory containing ``blog.config.sh`` and ``scripts/run.py``); this module
computes the week windows and drives that package once per eligible week.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from drydock.errors import DrydockError, UsageError

# Thursday — the weekly grid is anchored to the published development-log
# history, whose windows run Thursday through Wednesday.
WEEK_START_WEEKDAY = 3

PUBLISHABLE_EVENT_TYPES = {"decision", "milestone"}

_CURSOR_RELPATH = Path("blog") / "material" / ".ships_log_cursor.json"


@dataclass
class WeekResult:
    start: date
    end: date
    status: str  # "generated" | "planned" | "empty" | "failed"
    event_count: int = 0
    detail: str = ""


@dataclass
class ShipsLogResult:
    package_dir: Path
    ships_log: Path
    weeks: list[WeekResult] = field(default_factory=list)
    pending_window: tuple[date, date] | None = None
    pending_events: int = 0

    def generated(self) -> list[WeekResult]:
        return [w for w in self.weeks if w.status == "generated"]

    def failed(self) -> list[WeekResult]:
        return [w for w in self.weeks if w.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() else 0


def resolve_package_dir(cli_dir: str | None, cwd: Path | None = None) -> Path:
    """Resolve the posts package directory: --dir, then config, then ./ShipsLog."""
    if cli_dir:
        candidate = Path(cli_dir).expanduser().resolve()
        if not (candidate / "blog.config.sh").is_file():
            raise UsageError(f"Not a Ship's Log posts package (no blog.config.sh): {candidate}")
        return candidate

    from drydock.config import get_shipslog_dir

    configured = get_shipslog_dir()
    if configured is not None:
        if not (configured / "blog.config.sh").is_file():
            raise DrydockError(
                f"Configured shipslog_dir is not a posts package (no blog.config.sh): {configured}"
            )
        return configured

    local = (cwd or Path.cwd()) / "ShipsLog"
    if (local / "blog.config.sh").is_file():
        return local

    raise DrydockError(
        "No Ship's Log posts package found.\n"
        "  Set one: drydock config set shipslog_dir <path>\n"
        "  Or pass: drydock shipslog --dir <path>"
    )


def load_package_config(package_dir: Path) -> dict[str, str]:
    """Read simple KEY="value" assignments from the package's blog.config.sh."""
    cfg: dict[str, str] = {}
    for line in (package_dir / "blog.config.sh").read_text(encoding="utf-8").splitlines():
        match = re.match(r'^(\w+)="([^"]*)"', line.strip())
        if match and "$" not in match.group(2):
            cfg[match.group(1)] = match.group(2)
    return cfg


def _load_events(ships_log: Path) -> list[dict]:
    records = []
    for raw in ships_log.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            records.append(json.loads(raw))
    records.sort(key=lambda item: item.get("recorded_at", ""))
    superseded: set[str] = set()
    for record in records:
        for value in record.get("supersedes", []):
            if isinstance(value, str):
                superseded.add(value)
    return [
        r
        for r in records
        if r.get("event_type") in PUBLISHABLE_EVENT_TYPES and r.get("event_id") not in superseded
    ]


def _unseen_events(events: list[dict], last_event_id: str | None) -> list[dict]:
    if not last_event_id:
        return events
    for index, record in enumerate(events):
        if record.get("event_id") == last_event_id:
            return events[index + 1 :]
    return events


def _event_date(record: dict) -> date:
    return date.fromisoformat(str(record.get("recorded_at", ""))[:10])


def align_week_start(day: date) -> date:
    """Snap a date down to the start of its aligned week."""
    return day - timedelta(days=(day.weekday() - WEEK_START_WEEKDAY) % 7)


def complete_week_windows(first_day: date, today: date) -> list[tuple[date, date]]:
    """Aligned week windows from first_day's week through the last fully elapsed week."""
    windows: list[tuple[date, date]] = []
    start = align_week_start(first_day)
    while start + timedelta(days=7) <= today:
        windows.append((start, start + timedelta(days=6)))
        start += timedelta(days=7)
    return windows


def _run_week(package_dir: Path, start: date, end: date) -> int:
    cmd = [
        sys.executable,
        str(package_dir / "scripts" / "run.py"),
        "--window-start",
        start.isoformat(),
        "--window-end",
        end.isoformat(),
        "--date",
        end.isoformat(),
        "--label",
        f"{start.isoformat()}-to-{end.isoformat()}",
        "--type",
        "milestone",
    ]
    return subprocess.run(cmd, cwd=package_dir, check=False).returncode


def generate(
    package_dir: Path,
    *,
    today: date | None = None,
    dry_run: bool = False,
    runner=_run_week,
    on_text=None,
) -> ShipsLogResult:
    """Generate one post per fully elapsed aligned week with unpublished events."""
    emit = on_text or (lambda _text: None)
    today = today or date.today()
    cfg = load_package_config(package_dir)
    ships_log = Path(cfg.get("SHIPS_LOG", ""))
    if not ships_log.is_file():
        raise DrydockError(f"Ship's Log not found: {ships_log or '(SHIPS_LOG unset)'}")

    result = ShipsLogResult(package_dir=package_dir, ships_log=ships_log)

    cursor_path = package_dir / _CURSOR_RELPATH
    last_event_id = None
    if cursor_path.is_file():
        try:
            last_event_id = json.loads(cursor_path.read_text(encoding="utf-8")).get("last_event_id")
        except json.JSONDecodeError:
            last_event_id = None

    unseen = _unseen_events(_load_events(ships_log), last_event_id)
    if not unseen:
        return result

    windows = complete_week_windows(_event_date(unseen[0]), today)
    for start, end in windows:
        count = sum(1 for record in unseen if start <= _event_date(record) <= end)
        if count == 0:
            result.weeks.append(WeekResult(start, end, "empty"))
            continue
        if dry_run:
            result.weeks.append(WeekResult(start, end, "planned", event_count=count))
            continue
        emit(f"Generating {start.isoformat()} → {end.isoformat()} ({count} events)")
        rc = runner(package_dir, start, end)
        if rc != 0:
            result.weeks.append(
                WeekResult(start, end, "failed", event_count=count, detail=f"exit code {rc}")
            )
            # The cursor did not advance; later weeks would republish this one.
            break
        result.weeks.append(WeekResult(start, end, "generated", event_count=count))

    published_through = windows[-1][1] if windows else align_week_start(today) - timedelta(days=1)
    pending = sum(1 for record in unseen if _event_date(record) > published_through)
    if pending:
        pending_start = published_through + timedelta(days=1)
        result.pending_window = (pending_start, pending_start + timedelta(days=6))
        result.pending_events = pending
    return result
