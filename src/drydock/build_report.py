"""Deterministic post-build report: what each block cost and how it fared.

The build already writes everything this report needs. Per-block outcomes — state, acceptance
tallies, and one line per repair attempt — are recorded in ``targets/<T>/evidence/*.md``. Token
accounting and wall time for every LLM call are recorded in ``logs/llm.jsonl``. Both are keyed
by execution id, so the report is a join, not a recomputation: no LLM runs, nothing executes,
and nothing is written.

The module produces data only. Rendering belongs to the caller, so the same report serves the
console today and the QuarterDeck later without either owning the other's format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from drydock.llm_usage import normalize_tokens, read_records

__all__ = [
    "AttemptScore",
    "BlockScore",
    "BuildScoreReport",
    "build_score_report",
]

_HEADING_RE = re.compile(r"^# Evidence:\s*(?P<name>.+?)\s*\((?P<block_id>[^()]+)\)\s*$")
_FIELD_RE = re.compile(r"^-\s*(?P<key>[^:]+?)\s*:\s*(?P<value>.*)$")
_SECTION_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$")
_VERDICT_RE = re.compile(r"^-\s*(?P<mark>PASS|FAIL):\s*(?P<check_id>\S+)")
# Mirrors the line build_run writes for each pass; every field after the status is optional.
_ATTEMPT_RE = re.compile(
    r"^-\s*attempt\s+(?P<index>\d+)\s*\([^)]*\):\s*(?P<status>[^;]+)"
    r"(?:;\s*(?P<checks>\d+)/(?P<total_checks>\d+)\s+checks)?"
    r"(?:;\s*(?P<cases>\d+)/(?P<total_cases>\d+)\s+cases)?"
    r"(?:\s*model=(?P<model>\S+?))?"
    r"(?:;\s*execution\s+(?P<execution>\S+?))?"
    r"(?:;\s*stopped:\s*(?P<stopped>.+?))?\s*$"
)


@dataclass(frozen=True)
class AttemptScore:
    """One LLM pass over one block: attempt 0 is the initial build, 1.. are repairs."""

    index: int
    execution_id: str = ""
    model: str = ""
    provider: str = ""
    status: str = ""
    passed_checks: int | None = None
    total_checks: int | None = None
    passed_cases: int | None = None
    total_cases: int | None = None
    stop_reason: str = ""
    # Joined from the execution record. Zero means "no usage recorded", never "free".
    total_input: int = 0
    cached_input: int = 0
    output: int = 0
    elapsed_ms: int = 0
    usage_found: bool = False

    @property
    def fresh_input(self) -> int:
        return max(self.total_input - self.cached_input, 0)

    @property
    def cache_hit_rate(self) -> float | None:
        """Cache-read share of everything sent, or ``None`` when nothing was sent."""
        if self.total_input <= 0:
            return None
        return self.cached_input / self.total_input

    @property
    def label(self) -> str:
        return "initial build" if self.index == 0 else f"repair {self.index}"


@dataclass(frozen=True)
class BlockScore:
    """One built block, with every pass it took and the acceptance it ended on."""

    block_id: str
    name: str
    block_type: str = ""
    state: str = ""
    date: str = ""
    story_points: int = 0
    attempts: tuple[AttemptScore, ...] = ()
    passed_checks: int = 0
    total_checks: int = 0
    failed_check_ids: tuple[str, ...] = ()
    files_changed: tuple[str, ...] = ()
    stories: tuple[str, ...] = ()

    @property
    def calls(self) -> int:
        return len(self.attempts)

    @property
    def repaired(self) -> bool:
        return self.calls > 1

    @property
    def verified(self) -> bool:
        return self.state == "closed/verified"

    @property
    def total_input(self) -> int:
        return sum(a.total_input for a in self.attempts)

    @property
    def cached_input(self) -> int:
        return sum(a.cached_input for a in self.attempts)

    @property
    def fresh_input(self) -> int:
        return sum(a.fresh_input for a in self.attempts)

    @property
    def output(self) -> int:
        return sum(a.output for a in self.attempts)

    @property
    def elapsed_ms(self) -> int:
        return sum(a.elapsed_ms for a in self.attempts)

    @property
    def cache_hit_rate(self) -> float | None:
        if self.total_input <= 0:
            return None
        return self.cached_input / self.total_input

    @property
    def stop_reason(self) -> str:
        return self.attempts[-1].stop_reason if self.attempts else ""


@dataclass(frozen=True)
class BuildScoreReport:
    """Every block the current evidence describes, newest build state as recorded."""

    target: str
    evidence_dir: Path
    records_path: Path
    blocks: tuple[BlockScore, ...] = field(default_factory=tuple)
    missing_usage: tuple[str, ...] = ()

    @property
    def calls(self) -> int:
        return sum(block.calls for block in self.blocks)

    @property
    def repaired_blocks(self) -> tuple[BlockScore, ...]:
        return tuple(block for block in self.blocks if block.repaired)

    @property
    def failed_blocks(self) -> tuple[BlockScore, ...]:
        return tuple(block for block in self.blocks if not block.verified)

    @property
    def total_input(self) -> int:
        return sum(block.total_input for block in self.blocks)

    @property
    def cached_input(self) -> int:
        return sum(block.cached_input for block in self.blocks)

    @property
    def fresh_input(self) -> int:
        return sum(block.fresh_input for block in self.blocks)

    @property
    def output(self) -> int:
        return sum(block.output for block in self.blocks)

    @property
    def elapsed_ms(self) -> int:
        return sum(block.elapsed_ms for block in self.blocks)

    @property
    def cache_hit_rate(self) -> float | None:
        if self.total_input <= 0:
            return None
        return self.cached_input / self.total_input

    @property
    def passed_checks(self) -> int:
        return sum(block.passed_checks for block in self.blocks)

    @property
    def total_checks(self) -> int:
        return sum(block.total_checks for block in self.blocks)

    @property
    def first_call_blocks(self) -> int:
        """Blocks that reached their final state without a repair pass."""
        return sum(1 for block in self.blocks if block.verified and not block.repaired)

    @property
    def models(self) -> tuple[str, ...]:
        seen = {a.model for block in self.blocks for a in block.attempts if a.model}
        return tuple(sorted(seen))


def _int(value: str) -> int:
    try:
        return int(value.replace(",", "").strip())
    except (AttributeError, ValueError):
        return 0


def _parse_evidence(text: str, block_id_hint: str) -> tuple[BlockScore, tuple[str, ...]]:
    """Parse one evidence file into a block score and its ordered attempt execution ids."""
    fields: dict[str, str] = {}
    name = block_id_hint
    block_id = block_id_hint
    section = ""
    verdicts: list[tuple[str, str]] = []
    attempts: list[AttemptScore] = []
    files: list[str] = []
    stories: list[str] = []

    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _HEADING_RE.match(line)
        if heading:
            name = heading.group("name")
            block_id = heading.group("block_id")
            continue
        section_match = _SECTION_RE.match(line)
        if section_match:
            section = section_match.group("name").strip().lower()
            continue
        if not line.startswith("-"):
            continue
        if not section:
            field_match = _FIELD_RE.match(line)
            if field_match:
                fields[field_match.group("key").strip().lower()] = field_match.group("value")
            continue
        if section == "post-build programmatic acceptance":
            verdict = _VERDICT_RE.match(line)
            if verdict:
                verdicts.append((verdict.group("mark"), verdict.group("check_id")))
            continue
        if section == "build directory changes":
            files.append(line.lstrip("- ").strip())
            continue
        if section == "stories built":
            stories.append(line.lstrip("- ").strip())
            continue
        if section == "repair attempts":
            attempt = _ATTEMPT_RE.match(line)
            if attempt is None:
                continue
            attempts.append(
                AttemptScore(
                    index=int(attempt.group("index")),
                    execution_id=(attempt.group("execution") or "").strip("; ").strip(),
                    model=attempt.group("model") or "",
                    status=(attempt.group("status") or "").strip(),
                    passed_checks=(
                        int(attempt.group("checks")) if attempt.group("checks") else None
                    ),
                    total_checks=(
                        int(attempt.group("total_checks"))
                        if attempt.group("total_checks")
                        else None
                    ),
                    passed_cases=(int(attempt.group("cases")) if attempt.group("cases") else None),
                    total_cases=(
                        int(attempt.group("total_cases")) if attempt.group("total_cases") else None
                    ),
                    stop_reason=(attempt.group("stopped") or "").strip(),
                )
            )

    passed = sum(1 for mark, _ in verdicts if mark == "PASS")
    failed_ids = tuple(check_id for mark, check_id in verdicts if mark == "FAIL")
    state = fields.get("resulting state", "")

    if not attempts:
        # A block that took one pass writes no ``## Repair attempts`` section. Its single
        # attempt is the file header, and the acceptance tally is the post-build verdict list.
        attempts = [
            AttemptScore(
                index=0,
                execution_id=fields.get("execution id", "").strip(),
                status="built" if state == "closed/verified" else "failed",
                passed_checks=passed if verdicts else None,
                total_checks=len(verdicts) if verdicts else None,
            )
        ]

    story_points = _int(
        next((value for key, value in fields.items() if key.startswith("story points")), "0")
    )
    block = BlockScore(
        block_id=block_id,
        name=name,
        block_type=fields.get("block type", ""),
        state=state,
        date=fields.get("date", ""),
        story_points=story_points,
        attempts=tuple(attempts),
        passed_checks=passed,
        total_checks=len(verdicts),
        failed_check_ids=failed_ids,
        files_changed=tuple(files),
        stories=tuple(stories),
    )
    return block, tuple(a.execution_id for a in attempts)


def _usage_index(records_path: Path) -> dict[str, tuple[int, int, int, int, str, str]]:
    """Map execution id -> (total_input, cached, output, elapsed_ms, provider, model)."""
    records, _invalid = read_records(records_path)
    index: dict[str, tuple[int, int, int, int, str, str]] = {}
    for record in records:
        execution_id = str(record.get("execution_id") or "")
        if not execution_id:
            continue
        job = record.get("job") if isinstance(record.get("job"), dict) else {}
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        provider = str(job.get("llm") or "")
        total_input, cached, output = normalize_tokens(provider, stats)
        try:
            elapsed = int(stats.get("elapsed_ms") or 0)
        except (TypeError, ValueError):
            elapsed = 0
        index[execution_id] = (
            total_input,
            cached,
            output,
            elapsed,
            provider,
            str(job.get("model") or ""),
        )
    return index


def build_score_report(target: str, target_dir: Path, *, records_path: Path) -> BuildScoreReport:
    """Join recorded build evidence with recorded LLM usage. Reads only; writes nothing."""
    evidence_dir = target_dir / "evidence"
    usage = _usage_index(records_path)
    blocks: list[BlockScore] = []
    missing: list[str] = []

    for path in sorted(evidence_dir.glob("*.md")) if evidence_dir.is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        block, _ids = _parse_evidence(text, path.stem)
        # Attach usage per attempt. An attempt whose execution is absent from the log keeps
        # zeroed counters and is reported as missing rather than silently costing nothing.
        attempts: list[AttemptScore] = []
        for attempt in block.attempts:
            entry = usage.get(attempt.execution_id) if attempt.execution_id else None
            if entry is None:
                if attempt.execution_id:
                    missing.append(attempt.execution_id)
                attempts.append(attempt)
                continue
            total_input, cached, output, elapsed, provider, model = entry
            attempts.append(
                AttemptScore(**{
                    **attempt.__dict__,
                    "model": attempt.model or model,
                    "provider": provider,
                    "total_input": total_input,
                    "cached_input": cached,
                    "output": output,
                    "elapsed_ms": elapsed,
                    "usage_found": True,
                })
            )
        blocks.append(BlockScore(**{**block.__dict__, "attempts": tuple(attempts)}))

    blocks.sort(key=lambda b: (b.attempts[0].execution_id if b.attempts else "", b.block_id))
    return BuildScoreReport(
        target=target,
        evidence_dir=evidence_dir,
        records_path=records_path,
        blocks=tuple(blocks),
        missing_usage=tuple(dict.fromkeys(missing)),
    )
