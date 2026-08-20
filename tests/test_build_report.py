"""Tests for the deterministic post-build report.

The report joins recorded build evidence with recorded LLM usage. It must read both and
invent neither: a block with no usage record reports zero tokens and says so, and every
acceptance tally comes from the evidence rather than from a re-run.
"""

from __future__ import annotations

import json
from pathlib import Path

from drydock.build_report import build_score_report

_SINGLE_PASS = """# Evidence: Block Parsing (feature-block-parsing)

- block type: feature
- date: 2026-07-29
- resulting state: closed/verified
- story points (combined assembled cost): 1200
- execution id: exec-single

## Stories built
- Block Basics (block-basics) [story]
- Block Code (block-code) [story]

## Build directory changes
- parser.py

## Post-build programmatic acceptance
- PASS: block-basics-entrypoint (FEATURE-Block-Basics.md)
  intent: It parses.
- PASS: block-code-fences (FEATURE-Block-Code.md)
  intent: It fences.
"""

_REPAIRED = """# Evidence: Inline Parsing (feature-inline-parsing)

- block type: feature
- date: 2026-07-29
- resulting state: closed/verified
- story points (combined assembled cost): 900
- execution id: exec-repair

## Post-build programmatic acceptance
- PASS: inline-emphasis (FEATURE-Inline-Emphasis.md)
- PASS: inline-links (FEATURE-Inline-Links.md)

## Repair attempts
- attempt 0 (initial build): failed; 1/2 checks; 243/243 cases model=gpt-5.6-luna; execution exec-first
- attempt 1 (repair 1): built; 2/2 checks; 375/375 cases model=gpt-5.6-luna; execution exec-repair
"""

_FAILED = """# Evidence: Filter Delivery (feature-filter-delivery)

- block type: feature
- date: 2026-07-29
- resulting state: closed/failed
- story points (combined assembled cost): 500
- execution id: exec-failed

## Post-build programmatic acceptance
- PASS: filter-entrypoint (FEATURE-Filter.md)
- FAIL: verification-scoped-number (FEATURE-Verification-Scoped.md)

## Repair attempts
- attempt 0 (initial build): failed; 1/2 checks model=gpt-5.6-luna; execution exec-failed; stopped: acceptance criterion reported defective
"""


def _record(execution_id: str, *, input_tokens: int, cached: int, output: int, elapsed: int):
    return {
        "execution_id": execution_id,
        "job": {"command_name": "build", "llm": "codex", "model": "gpt-5.6-luna"},
        "result": {
            "returncode": 0,
            "stats": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached,
                "output_tokens": output,
                "elapsed_ms": elapsed,
            },
        },
        "status": "succeeded",
    }


def _setup(tmp_path: Path, evidence: dict[str, str], records: list[dict]) -> tuple[Path, Path]:
    target_dir = tmp_path / "commonmark"
    (target_dir / "evidence").mkdir(parents=True)
    for name, text in evidence.items():
        (target_dir / "evidence" / name).write_text(text, encoding="utf-8")
    records_path = tmp_path / "logs" / "llm.jsonl"
    records_path.parent.mkdir(parents=True)
    records_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return target_dir, records_path


def test_single_pass_block_reports_its_acceptance_and_usage(tmp_path):
    target_dir, records = _setup(
        tmp_path,
        {"feature-block-parsing.md": _SINGLE_PASS},
        [_record("exec-single", input_tokens=1000, cached=900, output=50, elapsed=60000)],
    )

    report = build_score_report("commonmark", target_dir, records_path=records)

    assert len(report.blocks) == 1
    block = report.blocks[0]
    assert block.block_id == "feature-block-parsing"
    assert block.name == "Block Parsing"
    assert block.verified
    assert (block.passed_checks, block.total_checks) == (2, 2)
    # A block that took one pass writes no repair section; its single attempt is the header.
    assert block.calls == 1
    assert not block.repaired
    assert block.stories == (
        "Block Basics (block-basics) [story]",
        "Block Code (block-code) [story]",
    )
    assert block.files_changed == ("parser.py",)
    # Codex reports input inclusive of cache reads, so total is not the sum.
    assert (block.total_input, block.cached_input, block.fresh_input) == (1000, 900, 100)
    assert block.output == 50
    assert block.cache_hit_rate == 0.9
    assert report.missing_usage == ()


def test_repaired_block_reports_every_pass_with_its_own_score(tmp_path):
    target_dir, records = _setup(
        tmp_path,
        {"feature-inline-parsing.md": _REPAIRED},
        [
            _record("exec-first", input_tokens=2000, cached=1600, output=80, elapsed=120000),
            _record("exec-repair", input_tokens=1000, cached=900, output=40, elapsed=30000),
        ],
    )

    report = build_score_report("commonmark", target_dir, records_path=records)
    block = report.blocks[0]

    assert block.calls == 2
    assert block.repaired
    first, second = block.attempts
    assert (first.index, first.status) == (0, "failed")
    assert (first.passed_checks, first.total_checks) == (1, 2)
    assert (first.passed_cases, first.total_cases) == (243, 243)
    assert first.label == "initial build"
    assert (second.index, second.status, second.label) == (1, "built", "repair 1")
    assert (second.passed_checks, second.total_checks) == (2, 2)
    # Usage rolls up across passes, so a repair's true cost is visible.
    assert block.total_input == 3000
    assert block.output == 120
    assert block.elapsed_ms == 150000
    assert report.repaired_blocks == (block,)


def test_a_pass_that_did_not_close_a_verified_block_reads_incomplete_not_failed(tmp_path):
    target_dir, records = _setup(
        tmp_path,
        {"feature-inline-parsing.md": _REPAIRED},
        [
            _record("exec-first", input_tokens=2000, cached=1600, output=80, elapsed=120000),
            _record("exec-repair", input_tokens=1000, cached=900, output=40, elapsed=30000),
        ],
    )

    report = build_score_report("commonmark", target_dir, records_path=records)
    block = report.blocks[0]
    first, second = block.attempts

    # The recorded status stays as the build loop wrote it; the reported outcome is the block's.
    assert first.status == "failed"
    assert block.outcome_of(first) == "incomplete"
    assert block.outcome_of(second) == "built"


def test_the_last_pass_of_an_unverified_block_still_reads_failed(tmp_path):
    target_dir, records = _setup(
        tmp_path,
        {"feature-filter-delivery.md": _FAILED},
        [_record("exec-failed", input_tokens=500, cached=400, output=20, elapsed=10000)],
    )

    report = build_score_report("commonmark", target_dir, records_path=records)
    block = report.blocks[0]

    assert block.outcome_of(block.attempts[-1]) == "failed"


def test_an_attempt_records_why_it_did_not_close(tmp_path):
    # A pass can meet every criterion and still be overturned. Without the reason the row reads
    # as a contradiction, so the reason is parsed and carried.
    evidence = _REPAIRED.replace(
        "- attempt 0 (initial build): failed; 1/2 checks; 243/243 cases "
        "model=gpt-5.6-luna; execution exec-first",
        "- attempt 0 (initial build): failed; 2/2 checks model=gpt-5.6-luna; "
        "execution exec-first; stopped: budget spent; "
        "reason: regression: inline-links, inline-code",
    )
    target_dir, records = _setup(
        tmp_path,
        {"feature-inline-parsing.md": evidence},
        [
            _record("exec-first", input_tokens=2000, cached=1600, output=80, elapsed=120000),
            _record("exec-repair", input_tokens=1000, cached=900, output=40, elapsed=30000),
        ],
    )

    report = build_score_report("commonmark", target_dir, records_path=records)
    first = report.blocks[0].attempts[0]

    assert first.stop_reason == "budget spent"
    assert first.reason == "regression: inline-links, inline-code"
    assert (first.passed_checks, first.total_checks) == (2, 2)


def test_failed_block_carries_its_failing_criteria_and_stop_reason(tmp_path):
    target_dir, records = _setup(
        tmp_path,
        {"feature-filter-delivery.md": _FAILED},
        [_record("exec-failed", input_tokens=500, cached=400, output=20, elapsed=10000)],
    )

    report = build_score_report("commonmark", target_dir, records_path=records)
    block = report.blocks[0]

    assert not block.verified
    assert block.state == "closed/failed"
    assert block.failed_check_ids == ("verification-scoped-number",)
    assert block.stop_reason == "acceptance criterion reported defective"
    assert report.failed_blocks == (block,)
    assert report.first_call_blocks == 0


def test_totals_roll_up_across_blocks(tmp_path):
    target_dir, records = _setup(
        tmp_path,
        {"a.md": _SINGLE_PASS, "b.md": _REPAIRED},
        [
            _record("exec-single", input_tokens=1000, cached=900, output=50, elapsed=60000),
            _record("exec-first", input_tokens=2000, cached=1600, output=80, elapsed=120000),
            _record("exec-repair", input_tokens=1000, cached=900, output=40, elapsed=30000),
        ],
    )

    report = build_score_report("commonmark", target_dir, records_path=records)

    assert len(report.blocks) == 2
    assert report.calls == 3
    assert report.total_input == 4000
    assert report.cached_input == 3400
    assert report.fresh_input == 600
    assert report.output == 170
    assert report.elapsed_ms == 210000
    assert report.cache_hit_rate == 0.85
    assert (report.passed_checks, report.total_checks) == (4, 4)
    assert report.first_call_blocks == 1
    assert report.models == ("gpt-5.6-luna",)


def test_an_execution_with_no_usage_record_is_reported_not_assumed_free(tmp_path):
    target_dir, records = _setup(tmp_path, {"feature-block-parsing.md": _SINGLE_PASS}, [])

    report = build_score_report("commonmark", target_dir, records_path=records)

    assert report.missing_usage == ("exec-single",)
    assert report.total_input == 0
    assert report.cache_hit_rate is None
    # The acceptance tally still comes from evidence, which does not depend on the usage log.
    assert (report.passed_checks, report.total_checks) == (2, 2)


def test_a_target_with_no_evidence_yields_an_empty_report(tmp_path):
    target_dir = tmp_path / "commonmark"
    target_dir.mkdir(parents=True)

    report = build_score_report(
        "commonmark", target_dir, records_path=tmp_path / "logs" / "llm.jsonl"
    )

    assert report.blocks == ()
    assert report.calls == 0
    assert report.cache_hit_rate is None


def test_claude_accounting_is_normalized_against_codex(tmp_path):
    """Claude reports input exclusive of cache reads; codex reports it inclusive. The report
    must present one contract so a cache hit rate means the same thing for both."""
    target_dir, records = _setup(tmp_path, {"feature-block-parsing.md": _SINGLE_PASS}, [])
    claude = _record("exec-single", input_tokens=100, cached=900, output=50, elapsed=1000)
    claude["job"]["llm"] = "claude"
    records.write_text(json.dumps(claude) + "\n", encoding="utf-8")

    report = build_score_report("commonmark", target_dir, records_path=records)
    block = report.blocks[0]

    assert block.total_input == 1000
    assert block.cached_input == 900
    assert block.fresh_input == 100
    assert block.cache_hit_rate == 0.9
