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
    assert result.report.count("| Severity | Affected Sources | Conflict Discovered |") == 1
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


def test_universal_references_consumers_and_definitions_have_distinct_codes() -> None:
    facts = _facts(
        ("reference", "missing-reference", "object"),
        ("consumer", "missing-consumer-target", "screen"),
        ("definition", "unused-definition", "object"),
    )

    assert {"REF001", "CONS001", "DEF001"} <= _codes(evaluate_facts(_inventory(), facts))


def test_runner_mutation_is_reported_as_side_effect(tmp_path: Path) -> None:
    target, sources = _target(tmp_path, {"SPEC.md": "# Specification\n"})
    runner = ExtractionRunner(mutate=sources / "SPEC.md")
    result = score_spec("Demo", target, runner=runner, log_dir=tmp_path / "logs")

    assert "SIDEFX001" in _codes(result.findings)
    assert "blueprint/sources/SPEC.md" in result.report


def test_undefined_and_unused_surfaces_produce_fixed_codes() -> None:
    facts = _facts(
        ("route", "/unused", "GET"),
        ("navigation", "missing", "/missing"),
        ("api", "api-unused", "GET /api/unused"),
        ("api_consumer", "screen", "api-missing"),
        ("service", "service-unused", "worker"),
        ("service_consumer", "screen", "service-missing"),
        ("field", "table-missing", "id"),
        ("state", "idle", "initial"),
        ("state_consumer", "button", "busy"),
    )
    codes = _codes(evaluate_facts(_inventory(), facts))

    assert {
        "ROUTE002",
        "NAV001",
        "API001",
        "API002",
        "SRV001",
        "SRV002",
        "DATA001",
        "STATE001",
        "STATE002",
    } <= codes


def test_database_closure_codes_and_external_empty_exceptions() -> None:
    incomplete = _facts(("table", "orders", "persistent orders"))
    assert {"DATA002", "DATA003", "DATA004", "DATA005", "DATA006"} <= _codes(
        evaluate_facts(_inventory(), incomplete)
    )

    complete = _facts(
        ("table", "orders", "persistent orders"),
        ("field", "orders", "id"),
        ("data_origin", "orders", "external system"),
        ("data_consumer", "orders", "report"),
        ("initial_condition", "orders", "initially empty"),
        ("entry_point", "app", "start"),
        ("initialization", "app", "initialize"),
    )
    assert not (
        _codes(evaluate_facts(_inventory(), complete))
        & {"DATA002", "DATA003", "DATA004", "DATA005", "DATA006"}
    )


@pytest.mark.parametrize(
    ("surface", "expected_profile", "expected_code"),
    (
        (("pipeline", "daily", "ETL"), "pipeline", "PIPE001"),
        (("dataset", "training-set", "rows"), "data-science", "DS001"),
        (("cli", "tool", "command"), "cli", "CLI001"),
        (("library", "sdk", "package"), "library", "LIB001"),
        (("event", "created", "domain event"), "event-driven", "EVT001"),
        (("batch", "nightly", "job"), "batch", "BATCH001"),
        (("scheduler", "cron", "scheduler"), "scheduler", "SCHED001"),
    ),
)
def test_specialized_rules_activate_only_from_explicit_surface(
    surface, expected_profile, expected_code
) -> None:
    facts = _facts(surface)
    assert expected_profile in activate_profiles(facts)
    assert expected_code in _codes(evaluate_facts(_inventory(), facts))
    assert expected_code not in _codes(evaluate_facts(_inventory(), ()))


def test_help_does_not_apply_to_noninteractive_standard() -> None:
    assert "HELP001" not in _codes(evaluate_facts(_inventory(), ()))


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


def test_report_has_exactly_one_table_and_codes_prefix_messages() -> None:
    finding = Finding("REF001", "High", ("SPEC.md",), "missing definition")
    report = render_report(_inventory(), (finding,), (), 1)

    assert report.count("| Severity | Affected Sources | Conflict Discovered |") == 1
    assert "| REF001: missing definition |" in report


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
