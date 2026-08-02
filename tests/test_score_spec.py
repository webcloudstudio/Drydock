"""Tests for the advisory raw-specification conformance audit."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from drydock.errors import SpecificationError
from drydock.score_spec import (
    FACT_TYPES,
    Fact,
    Finding,
    SourceRecord,
    activate_profiles,
    evaluate_facts,
    extraction_passes,
    parse_extraction,
    render_report,
    score_spec,
)


@dataclass
class FakeRun:
    text: str
    ok: bool = True
    execution_id: str = "score-spec-test"


@dataclass
class ExtractionRunner:
    facts: list[dict] = field(default_factory=list)
    mutate: Path | None = None
    calls: list[dict] = field(default_factory=list)

    def __call__(self, prompt: str, working_directory: Path, **kwargs) -> FakeRun:
        self.calls.append({"prompt": prompt, "cwd": working_directory, **kwargs})
        covered = re.findall(r'<SOURCE chunk_id="([^"]+)"', prompt)
        paths = {
            match.group(1): (int(match.group(2)), int(match.group(3)))
            for match in re.finditer(
                r'<SOURCE chunk_id="[^"]+" path="([^"]+)" start_line="(\d+)" end_line="(\d+)">',
                prompt,
            )
        }
        selected = [
            fact
            for fact in self.facts
            if fact["source_path"] in paths
            and paths[fact["source_path"]][0] <= fact["line"] <= paths[fact["source_path"]][1]
        ]
        if self.mutate is not None:
            self.mutate.write_text("changed by runner\n", encoding="utf-8")
            self.mutate = None
        return FakeRun(json.dumps({"covered": covered, "facts": selected}))


def _target(tmp_path: Path, files: dict[str, str | bytes]) -> tuple[Path, Path]:
    target = tmp_path / "targets" / "Demo"
    sources = target / "blueprint" / "sources"
    sources.mkdir(parents=True)
    for name, content in files.items():
        path = sources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return target, sources


def _fact(kind: str, identifier: str, value: str, path: str = "SPEC.md", line: int = 2) -> dict:
    assert kind in FACT_TYPES
    return {
        "type": kind,
        "identifier": identifier,
        "value": value,
        "source_path": path,
        "line": line,
    }


def _facts(*items: tuple[str, str, str]) -> tuple[Fact, ...]:
    return tuple(
        Fact(kind, identifier, value, "SPEC.md", index + 1)
        for index, (kind, identifier, value) in enumerate(items)
    )


def _inventory() -> tuple[SourceRecord, ...]:
    return (SourceRecord("SPEC.md", 100, 10, 1, True),)


def _codes(findings: tuple[Finding, ...]) -> set[str]:
    return {finding.code for finding in findings}


def test_short_markdown_produces_scorecard_and_identical_report(tmp_path: Path) -> None:
    target, _ = _target(tmp_path, {"STANDARD.md": "# Standard\n\nNormative text.\n"})
    runner = ExtractionRunner()
    result = score_spec("Demo", target, runner=runner, log_dir=tmp_path / "logs")

    assert result.exit_code() == 0
    assert result.findings == ()
    assert result.report_path.read_text(encoding="utf-8") == result.report
    assert result.report.count("| Code | Severity | Conflict Discovered | Affected Sources |") == 1
    assert "codex_sandbox" not in runner.calls[0]


def test_forty_markdown_files_are_all_inventoried(tmp_path: Path) -> None:
    target, _ = _target(
        tmp_path,
        {f"S-{index:02d}.md": f"# Source {index}\n\nFact {index}.\n" for index in range(40)},
    )
    result = score_spec("Demo", target, runner=ExtractionRunner(), log_dir=tmp_path / "logs")

    assert len(result.inventory) == 40
    assert all(record.markdown for record in result.inventory)
    assert "`S-00.md`" in result.report and "`S-39.md`" in result.report


def test_extraction_is_bounded_without_dropping_content() -> None:
    markdown = {f"S-{index}.md": "# H\n" + ("x" * 60) + "\n" for index in range(6)}
    passes = extraction_passes(markdown, limit=100)

    assert len(passes) > 1
    assert "".join(chunk.text for batch in passes for chunk in batch) == "".join(markdown.values())


def test_non_markdown_is_inventoried_but_never_injected(tmp_path: Path) -> None:
    target, _ = _target(
        tmp_path,
        {"SPEC.md": "# Specification\n", "secret.bin": b"DO-NOT-INJECT-THIS\xff\x00"},
    )
    runner = ExtractionRunner()
    result = score_spec("Demo", target, runner=runner, log_dir=tmp_path / "logs")

    assert any(record.path == "secret.bin" and not record.markdown for record in result.inventory)
    assert all("DO-NOT-INJECT-THIS" not in call["prompt"] for call in runner.calls)
    assert "`secret.bin`" in result.report


def test_navigation_conflicts_produce_fixed_codes() -> None:
    facts = _facts(
        ("route", "/home", "GET"),
        ("navigation", "home", "/home"),
        ("navigation", "home", "/other"),
        ("navigation_order", "home", "1"),
        ("navigation_order", "home", "2"),
    )

    assert {"NAV002", "NAV003"} <= _codes(evaluate_facts(_inventory(), facts))


def test_dangling_references_and_consumers_have_distinct_codes() -> None:
    facts = _facts(
        ("reference", "missing-reference", "object"),
        ("consumer", "missing-consumer-target", "screen"),
    )

    assert {"REF001", "CONS001"} <= _codes(evaluate_facts(_inventory(), facts))


def test_guardrails_are_captured_without_demanding_a_defined_subject() -> None:
    """A guardrail names its subject in prose; requiring a separate definition only adds noise."""
    facts = _facts(
        ("guardrail", "discovery execution", "discovery never executes operation declarations"),
        ("guardrail", "git controls", "no merge, reset, push, or branch controls"),
    )

    assert evaluate_facts(_inventory(), facts) == ()
    assert "guardrail" in FACT_TYPES


def test_a_definition_without_a_reference_is_not_a_finding() -> None:
    """Prose that names a thing once is normal writing, not a specification defect."""
    facts = _facts(("definition", "marina", "local-first application"))

    assert evaluate_facts(_inventory(), facts) == ()


def test_runner_mutation_is_reported_as_side_effect(tmp_path: Path) -> None:
    target, sources = _target(tmp_path, {"SPEC.md": "# Specification\n"})
    runner = ExtractionRunner(mutate=sources / "SPEC.md")
    result = score_spec("Demo", target, runner=runner, log_dir=tmp_path / "logs")

    assert "SIDEFX001" in _codes(result.findings)
    assert "blueprint/sources/SPEC.md" in result.report


def test_dangling_surface_targets_produce_fixed_codes() -> None:
    facts = _facts(
        ("route", "/defined", "GET"),
        ("navigation", "missing", "/missing"),
        ("api", "api-defined", "GET /api/defined"),
        ("api_consumer", "screen", "api-missing"),
        ("service", "service-defined", "worker"),
        ("service_consumer", "screen", "service-missing"),
        ("field", "table-missing", "id"),
        ("state", "idle", "initial"),
        ("state_consumer", "button", "busy"),
    )
    codes = _codes(evaluate_facts(_inventory(), facts))

    assert {"NAV001", "API001", "SRV001", "DATA001", "STATE001"} <= codes


@pytest.mark.parametrize(
    ("code", "surface"),
    (
        ("ROUTE002", ("route", "/unconsumed", "GET")),
        ("API002", ("api", "api-unconsumed", "GET /api/x")),
        ("SRV002", ("service", "service-unconsumed", "worker")),
        ("STATE002", ("state", "dirty", "checkout status")),
        ("DEF001", ("definition", "lonely", "object")),
        ("LIB001", ("library", "stack", "package")),
        ("HELP001", ("route", "/page", "GET")),
    ),
)
def test_absence_of_a_stated_consumer_is_not_a_finding(code: str, surface: tuple) -> None:
    """A specification need not name a consumer for every route, API, service, or status."""
    assert code not in _codes(evaluate_facts(_inventory(), _facts(surface)))


def test_database_closure_reports_population_and_readership_only() -> None:
    # 'audit' carries every relation, which proves the extraction captures them; 'orders' does not.
    incomplete = _facts(
        ("table", "orders", "persistent orders"),
        ("table", "audit", "persistent audit trail"),
        ("field", "audit", "create_dtm"),
        ("data_producer", "audit", "writer"),
        ("data_consumer", "audit", "report"),
    )
    codes = _codes(evaluate_facts(_inventory(), incomplete))

    assert {"DATA002", "DATA004", "DATA005"} <= codes
    assert not ({"DATA003", "DATA006"} & codes)

    complete = _facts(
        ("table", "orders", "persistent orders"),
        ("field", "orders", "id"),
        ("data_origin", "orders", "external system"),
        ("data_consumer", "orders", "report"),
    )
    assert not (_codes(evaluate_facts(_inventory(), complete)) & {"DATA002", "DATA004", "DATA005"})


def test_a_relation_no_table_ever_carries_is_unobserved_rather_than_missing() -> None:
    """Zero field facts corpus-wide means the extraction never captured columns, not that eight
    declared tables each forgot to declare any."""
    facts = _facts(
        ("table", "orders", "persistent orders"),
        ("table", "settings", "persistent settings"),
    )
    codes = _codes(evaluate_facts(_inventory(), facts))

    assert not ({"DATA002", "DATA004", "DATA005"} & codes)


def test_an_audit_column_never_read_is_not_reported() -> None:
    """Standard internal columns are written and rarely consumed; that is best practice."""
    facts = _facts(
        ("table", "orders", "persistent orders"),
        ("field", "orders", "create_user"),
        ("field", "orders", "create_dtm"),
        ("data_producer", "orders", "writer"),
        ("data_consumer", "orders", "report"),
    )

    assert evaluate_facts(_inventory(), facts) == ()


def test_table_relation_on_a_defined_nontable_subject_is_not_a_missing_table() -> None:
    """`agents.md` described as carrying content is a document, not an undeclared table."""
    facts = _facts(
        ("definition", "agents.md", "repository guidance document"),
        ("field", "agents.md", "capability marker"),
        ("table", "orders", "persistent orders"),
    )
    findings = evaluate_facts(_inventory(), facts)

    assert "DATA001" not in _codes(findings)
    assert all("agents.md" not in finding.message for finding in findings)


@pytest.mark.parametrize(
    ("anchor", "relation", "profile", "code"),
    (
        ("pipeline", "trigger", "pipeline", "PIPE001"),
        ("dataset", "feature", "data-science", "DS001"),
        ("cli", "entry_point", "cli", "CLI001"),
        ("event", "trigger", "event-driven", "EVT001"),
        ("batch", "schedule", "batch", "BATCH001"),
        ("scheduler", "schedule", "scheduler", "SCHED001"),
    ),
)
def test_specialized_rules_fire_only_against_demonstrated_relations(
    anchor: str, relation: str, profile: str, code: str
) -> None:
    bare = _facts((anchor, "incomplete", "surface"))
    assert profile in activate_profiles(bare)
    assert code not in _codes(evaluate_facts(_inventory(), bare))

    corroborated = _facts(
        (anchor, "incomplete", "surface"),
        (anchor, "complete", "surface"),
        (relation, "complete", "stated"),
    )
    findings = [f for f in evaluate_facts(_inventory(), corroborated) if f.code == code]

    assert [f.message for f in findings] == [
        message for message in (f"{anchor} 'incomplete' has no {_LABELS[code]}",)
    ]


_LABELS = {
    "PIPE001": "trigger",
    "DS001": "features",
    "CLI001": "entry point",
    "EVT001": "trigger",
    "BATCH001": "schedule",
    "SCHED001": "schedule",
}


def test_profiles_activate_on_anchor_surfaces_not_on_relation_types() -> None:
    """A `feature` or `target` fact in a web specification is not a data-science system."""
    web = _facts(
        ("route", "/home", "GET"),
        ("feature", "dashboard", "project overview"),
        ("target", "release", "next milestone"),
    )

    assert activate_profiles(web) == ("web",)
    assert activate_profiles(_facts(("dataset", "training-set", "rows"))) == ("data-science",)


def test_incomplete_extraction_does_not_replace_prior_scorecard(tmp_path: Path) -> None:
    target, _ = _target(tmp_path, {"SPEC.md": "# Specification\n"})
    report = target / "SPECIFICATION_SCORECARD.md"
    report.write_text("prior valid report\n", encoding="utf-8")

    def malformed(prompt: str, working_directory: Path, **kwargs) -> FakeRun:
        return FakeRun('{"facts": []}')

    with pytest.raises(SpecificationError, match="exactly 'covered' and 'facts'"):
        score_spec("Demo", target, runner=malformed, log_dir=tmp_path / "logs")
    assert report.read_text(encoding="utf-8") == "prior valid report\n"


def test_parse_extraction_rejects_uncited_or_extra_fields() -> None:
    from drydock.score_spec import SourceChunk

    chunks = (SourceChunk("SPEC.md:1-2", "SPEC.md", 1, 2, "# S\ntext\n"),)
    bad = {
        "covered": ["SPEC.md:1-2"],
        "facts": [{**_fact("definition", "x", "thing", line=3), "judgment": "good"}],
    }
    with pytest.raises(SpecificationError):
        parse_extraction(json.dumps(bad), chunks)


def _chunk():
    from drydock.score_spec import SourceChunk

    return (SourceChunk("SPEC.md:1-2", "SPEC.md", 1, 2, "# S\ntext\n"),)


@pytest.mark.parametrize(
    ("bad", "reason"),
    (
        ({"type": "vibe"}, "unknown type 'vibe'"),
        ({"type": ""}, "type is empty or not a string"),
        ({"identifier": "  "}, "identifier, value, or source_path is empty or not a string"),
        ({"line": 0}, "line is not a positive integer"),
        ({"line": True}, "line is not a positive integer"),
        ({"line": "later"}, "line is not a positive integer"),
        ({"line": 99}, "path or line falls outside this extraction pass"),
        ({"source_path": "OTHER.md"}, "path or line falls outside this extraction pass"),
    ),
)
def test_malformed_fact_is_discarded_not_fatal(bad: dict, reason: str) -> None:
    payload = {
        "covered": ["SPEC.md:1-2"],
        "facts": [
            _fact("definition", "x", "thing", line=1),
            {**_fact("definition", "y", "other", line=2), **bad},
        ],
    }
    discarded: list[str] = []
    facts = parse_extraction(json.dumps(payload), _chunk(), discarded=discarded)

    assert [fact.identifier for fact in facts] == ["x"]
    assert discarded == [reason]


@pytest.mark.parametrize("line", (2, "2", 2.0))
def test_line_accepts_integer_string_and_integral_float(line: object) -> None:
    payload = {
        "covered": ["SPEC.md:1-2"],
        "facts": [{**_fact("definition", "x", "thing"), "line": line}],
    }
    discarded: list[str] = []
    facts = parse_extraction(json.dumps(payload), _chunk(), discarded=discarded)

    assert discarded == []
    assert facts[0].line == 2


def test_envelope_survives_fences_and_reordered_coverage() -> None:
    from drydock.score_spec import SourceChunk

    chunks = (
        SourceChunk("SPEC.md:1-2", "SPEC.md", 1, 2, "# S\ntext\n"),
        SourceChunk("SPEC.md:3-4", "SPEC.md", 3, 4, "more\ntext\n"),
    )
    payload = {
        "covered": ["SPEC.md:3-4", "SPEC.md:1-2"],
        "facts": [_fact("definition", "x", "thing", line=1)],
    }
    wrapped = "Here is the result:\n```json\n" + json.dumps(payload) + "\n```\n"

    assert parse_extraction(wrapped, chunks)[0].identifier == "x"


def test_missing_coverage_remains_fatal() -> None:
    from drydock.score_spec import SourceChunk

    chunks = (
        SourceChunk("SPEC.md:1-2", "SPEC.md", 1, 2, "# S\ntext\n"),
        SourceChunk("SPEC.md:3-4", "SPEC.md", 3, 4, "more\ntext\n"),
    )
    payload = {"covered": ["SPEC.md:1-2"], "facts": []}

    with pytest.raises(SpecificationError, match="exact source-chunk coverage"):
        parse_extraction(json.dumps(payload), chunks)


def test_missing_field_is_discarded_but_extra_field_stays_fatal() -> None:
    short = {"covered": ["SPEC.md:1-2"], "facts": [{"type": "definition", "identifier": "x"}]}
    discarded: list[str] = []

    assert parse_extraction(json.dumps(short), _chunk(), discarded=discarded) == ()
    assert discarded == ["record is missing required fields"]

    judged = {
        "covered": ["SPEC.md:1-2"],
        "facts": [{**_fact("definition", "x", "thing", line=1), "judgment": "good"}],
    }
    with pytest.raises(SpecificationError, match="invalid record shape"):
        parse_extraction(json.dumps(judged), _chunk())


def test_discards_are_counted_and_reported_in_the_scorecard(tmp_path: Path) -> None:
    target, _ = _target(tmp_path, {"SPEC.md": "# Specification\nbody\n"})
    invented = {
        "type": "vibe",
        "identifier": "y",
        "value": "invented",
        "source_path": "SPEC.md",
        "line": 2,
    }
    runner = ExtractionRunner([invented, {**invented, "identifier": "z"}])
    result = score_spec("Demo", target, runner=runner, log_dir=tmp_path / "logs")

    assert result.exit_code() == 0
    assert "EXTRACT001" in _codes(result.findings)
    assert "unknown type 'vibe' (2)" in result.report


def test_report_leads_each_row_with_its_code_and_orders_by_severity() -> None:
    findings = (
        Finding("DATA005", "Medium", ("DATABASE.md",), "table 'orders' is never read"),
        Finding("REF001", "High", ("SPEC.md",), "missing definition"),
        Finding("SIDEFX001", "Critical", ("SPEC.md",), "tree modified"),
    )
    report = render_report(_inventory(), findings, (), 1)
    rows = [line for line in report.splitlines() if line.startswith("| ")]

    assert report.count("| Code | Severity | Conflict Discovered | Affected Sources |") == 1
    assert [row.split(" | ")[0].lstrip("| ") for row in rows[1:]] == [
        "SIDEFX001",
        "REF001",
        "DATA005",
    ]
    assert "| REF001 | High | missing definition | `SPEC.md` |" in report
    assert "- Findings: 3 (1 Critical, 1 High, 1 Medium)" in report


def test_report_caps_a_corpus_wide_source_list() -> None:
    sources = tuple(f"S-{index:02d}.md" for index in range(27))
    finding = Finding("INIT001", "Medium", sources, "no initialization contract")
    report = render_report(_inventory(), (finding,), (), 1)

    assert "`S-00.md`, `S-01.md`, `S-02.md`, `S-03.md` +23 more" in report
    assert "`S-26.md`" not in report.split("| Code |")[1]


def test_extraction_prompt_offers_guardrail_and_fences_off_table_misuse() -> None:
    from drydock.score_spec import SourceChunk, assemble_extraction_prompt

    chunks = (SourceChunk("SPEC.md:1-2", "SPEC.md", 1, 2, "# S\ntext\n"),)
    rendered = assemble_extraction_prompt("body", chunks).rendered_text

    assert "guardrail" in rendered
    assert "is never a `table`" in rendered


def test_prompt_is_registered_and_prohibits_judgment() -> None:
    from drydock.prompts import load_prompt

    prompt = load_prompt("score_spec")
    assert prompt.meta["command"] == "drydock score spec"
    assert "Do not make quality judgments" in prompt.body


def test_cli_prints_exactly_the_written_report(tmp_path: Path, monkeypatch, capsys) -> None:
    import drydock.config as config
    import drydock.score_spec as module
    from drydock import cli

    target = tmp_path / "targets" / "Demo"
    target.mkdir(parents=True)
    report_text = (
        "# Report\n\n| Severity | Affected Sources | Conflict Discovered |\n|---|---|---|\n"
    )
    report_path = target / "SPECIFICATION_SCORECARD.md"

    def fake_score(target_name: str, target_dir: Path, **kwargs):
        assert target_name == "Demo"
        report_path.write_text(report_text, encoding="utf-8")
        return SimpleNamespace(report=report_text, exit_code=lambda: 0)

    monkeypatch.setattr(config, "require_target_dir", lambda target_name: target)
    monkeypatch.setattr(config, "get_workspace", lambda: tmp_path)
    monkeypatch.setattr(config, "get_model", lambda value=None: value or "sonnet")
    monkeypatch.setattr(config, "get_effort", lambda value=None: value)
    monkeypatch.setattr(config, "get_llm_provider", lambda value=None: value or "claude")
    monkeypatch.setattr(module, "score_spec", fake_score)

    assert cli.cmd_score_spec("Demo") == 0
    assert capsys.readouterr().out == report_path.read_text(encoding="utf-8")


def test_score_spec_dispatch_forwards_invocation_overrides(monkeypatch) -> None:
    import drydock.config as config
    from drydock import cli

    received = {}

    def fake(target, **kwargs):
        received.update({"target": target, **kwargs})
        return 0

    monkeypatch.setattr(cli, "cmd_score_spec", fake)
    monkeypatch.setattr(config, "record_activity", lambda *args: None)
    args = SimpleNamespace(
        args=["spec", "Demo"], model="model-x", llm_provider="codex", effort="high"
    )

    assert cli._dispatch_score(args) == 0
    assert received == {
        "target": "Demo",
        "model": "model-x",
        "llm_provider": "codex",
        "effort": "high",
    }
