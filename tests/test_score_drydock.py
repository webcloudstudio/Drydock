"""Tests for `drydock score drydock` — the adversarial self-assessment."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

from drydock.errors import DrydockError, SpecificationError
from drydock.score_drydock import (
    HIGHEST_MODEL,
    HIGHEST_MODEL_PROVIDER,
    Feature,
    assemble_prompt,
    collect_prompt_files,
    feature_filename,
    parse_assessment,
    rank_features,
    render_index_markdown,
    score_drydock,
    slugify,
    write_assessment,
)


@dataclass
class FakeStats:
    model: str | None = None


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "exec-score-drydock"
    stats: object | None = None


@dataclass
class RecordingRunner:
    """Captures the call `score_drydock` makes so the contract can be asserted without a model."""

    reply: str
    stats: object | None = None
    calls: list[dict] = field(default_factory=list)

    def __call__(self, prompt: str, working_directory: Path, **kwargs) -> FakeRun:
        self.calls.append({"prompt": prompt, "cwd": working_directory, **kwargs})
        return FakeRun(text=self.reply, stats=self.stats)


def _feature(index: int, *, impact: int, complexity: int, title: str | None = None) -> dict:
    return {
        "id": f"DDF-{index:03d}",
        "title": title or f"Feature {index}",
        "area": "drydock plan",
        "problem": "Stories are decomposed without dependency edges.",
        "intent_reference": "Specification Decomposition Methodology",
        "evidence": "prompts/plan_create.md omits the Consumes rule for pipelines.",
        "recommendation": "Derive dependency edges from Provides/Consumes.",
        "impact": impact,
        "complexity": complexity,
        "project_types": ["Data pipeline"],
        "stories": [
            {
                "title": "Emit dependency edges",
                "statement": "As the Commander, I want dependency edges, so that build order is right.",
                "acceptance_criteria": ["parse_build_plan resolves every Consumes token."],
                "tests": ["test_plan_emits_dependency_edges"],
            }
        ],
        "definition_of_done": ["Manifest carries an edge for every Consumes token."],
        "implementation_plan": ["Update prompts/plan_create.md.", "Extend build_plan parsing."],
        "specification_impact": "none",
        "risks": ["Existing Manifests may need a refit."],
    }


def _payload(features: list[dict] | None = None, **overrides) -> str:
    body = {
        "executive_assessment": "Drydock holds its own contracts but decomposition is untested.",
        "systemic_risks": ["Acceptance criteria that cannot fail."],
        "project_type_gaps": [
            {
                "project_type": "Data pipeline / ETL",
                "gap": "No Typed Specification file describes datasets.",
                "evidence": "blueprint/ has no PIPELINE file type.",
                "severity": "high",
            }
        ],
        "features": features if features is not None else [_feature(1, impact=8, complexity=4)],
    }
    body.update(overrides)
    return json.dumps(body)


# ── payload parsing ───────────────────────────────────────────────────────────


def test_parse_assessment_reads_full_payload() -> None:
    assessment = parse_assessment(_payload())
    assert assessment.features[0].feature_id == "DDF-001"
    assert assessment.features[0].impact == 8
    assert assessment.features[0].stories[0].tests == ("test_plan_emits_dependency_edges",)
    assert assessment.project_type_gaps[0].severity == "high"


def test_parse_assessment_tolerates_a_fenced_reply() -> None:
    fenced = "```json\n" + _payload() + "\n```"
    assert parse_assessment(fenced).features[0].feature_id == "DDF-001"


def test_parse_assessment_rejects_non_json() -> None:
    with pytest.raises(DrydockError):
        parse_assessment("Here is my assessment: Drydock is fine.")


def test_parse_assessment_requires_features() -> None:
    with pytest.raises(DrydockError):
        parse_assessment(_payload(features=[]))


def test_parse_assessment_rejects_out_of_range_impact() -> None:
    with pytest.raises(DrydockError):
        parse_assessment(_payload([_feature(1, impact=11, complexity=4)]))


def test_parse_assessment_rejects_duplicate_feature_ids() -> None:
    duplicate = [_feature(1, impact=8, complexity=4), _feature(1, impact=5, complexity=2)]
    with pytest.raises(DrydockError):
        parse_assessment(_payload(duplicate))


def test_parse_assessment_requires_stories_per_feature() -> None:
    bare = _feature(1, impact=8, complexity=4)
    bare["stories"] = []
    with pytest.raises(DrydockError):
        parse_assessment(_payload([bare]))


def test_parse_assessment_requires_acceptance_criteria() -> None:
    weak = _feature(1, impact=8, complexity=4)
    weak["stories"][0]["acceptance_criteria"] = []
    with pytest.raises(DrydockError):
        parse_assessment(_payload([weak]))


# ── ranking ───────────────────────────────────────────────────────────────────


def test_features_rank_by_impact_then_cheapest_first() -> None:
    features = [
        _feature(1, impact=6, complexity=2),
        _feature(2, impact=9, complexity=8),
        _feature(3, impact=9, complexity=3),
    ]
    ranked = parse_assessment(_payload(features)).features
    assert [f.feature_id for f in ranked] == ["DDF-003", "DDF-002", "DDF-001"]


def test_rank_features_is_stable_on_full_ties() -> None:
    parsed = parse_assessment(
        _payload([_feature(2, impact=7, complexity=5), _feature(1, impact=7, complexity=5)])
    ).features
    assert [f.feature_id for f in rank_features(list(parsed))] == ["DDF-001", "DDF-002"]


def test_slugify_bounds_and_normalizes() -> None:
    assert slugify("Emit Dependency Edges!") == "emit-dependency-edges"
    assert slugify("!!!") == "feature"
    assert len(slugify("x" * 200)) <= 60


# ── writing ───────────────────────────────────────────────────────────────────


def _assessment_with(features: list[dict]):
    return parse_assessment(_payload(features))


def test_write_assessment_writes_ranked_feature_files_and_index(tmp_path: Path) -> None:
    assessment = _assessment_with([
        _feature(1, impact=6, complexity=2, title="Lower impact"),
        _feature(2, impact=9, complexity=3, title="Higher impact"),
    ])
    planning = tmp_path / "docs" / "drydock_planning"
    index_path, features, archive = write_assessment(
        assessment, planning, generated_at=datetime(2026, 7, 26, 9, 0), review_model="fable"
    )
    assert archive is None
    assert [path.name for path in features] == [
        "FEATURE-01-higher-impact.md",
        "FEATURE-02-lower-impact.md",
    ]
    index = index_path.read_text(encoding="utf-8")
    assert "FEATURE-01-higher-impact.md" in index
    assert "Project Type Coverage Gaps" in index
    assert "review_model: fable" in index

    top = features[0].read_text(encoding="utf-8")
    assert "impact: 9" in top
    assert "## Stories" in top
    assert "**Tests (RED first)**" in top
    assert "test_plan_emits_dependency_edges" in top
    assert "## Implementation Plan" in top


def test_write_assessment_archives_a_previous_plan(tmp_path: Path) -> None:
    planning = tmp_path / "docs" / "drydock_planning"
    planning.mkdir(parents=True)
    (planning / "INDEX.md").write_text("old index\n", encoding="utf-8")
    (planning / "FEATURE-01-old.md").write_text("annotated by hand\n", encoding="utf-8")

    assessment = _assessment_with([_feature(1, impact=8, complexity=4)])
    _, _, archive = write_assessment(
        assessment, planning, generated_at=datetime(2026, 7, 26, 9, 0), review_model="fable"
    )
    assert archive is not None
    assert (archive / "FEATURE-01-old.md").read_text(encoding="utf-8") == "annotated by hand\n"
    assert not (planning / "FEATURE-01-old.md").exists()


def test_index_reports_empty_gap_and_risk_sections(tmp_path: Path) -> None:
    assessment = parse_assessment(
        _payload([_feature(1, impact=8, complexity=4)], systemic_risks=[], project_type_gaps=[])
    )
    markdown = render_index_markdown(
        assessment,
        filenames={"DDF-001": "FEATURE-01-feature-1.md"},
        generated_at="2026-07-26T09:00:00",
        review_model="fable",
    )
    assert markdown.count("None reported.") == 2


def test_feature_filename_is_rank_ordered() -> None:
    feature = _assessment_with([_feature(1, impact=8, complexity=4)]).features[0]
    assert feature_filename(feature, 3) == "FEATURE-03-feature-1.md"
    assert isinstance(feature, Feature)


# ── prompt assembly ───────────────────────────────────────────────────────────


def test_assemble_prompt_injects_spec_and_every_prompt_contract() -> None:
    from drydock.paths import get_repo_root

    repo_root = get_repo_root()
    assembly = assemble_prompt(repo_root, "BODY", today="2026-07-26")
    text = assembly.rendered_text
    assert "Drydock_Specification.md" in text
    for prompt_path in collect_prompt_files(repo_root):
        assert prompt_path.name in text
    assert "Package module inventory" in text
    assert "score_drydock.py" in text
    assert text.rstrip().endswith("BODY")


def test_collect_prompt_files_excludes_the_archive() -> None:
    from drydock.paths import get_repo_root

    names = {path.name for path in collect_prompt_files(get_repo_root())}
    assert "score_drydock.md" in names
    assert not any("archive" in str(path) for path in collect_prompt_files(get_repo_root()))


def test_assemble_prompt_requires_the_specification(tmp_path: Path) -> None:
    with pytest.raises(SpecificationError):
        assemble_prompt(tmp_path, "BODY", today="2026-07-26")


# ── command behavior ──────────────────────────────────────────────────────────


def _throwaway_repo(tmp_path: Path) -> Path:
    """A minimal repo root, so command tests never write into the real docs/ tree."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "Drydock_Specification.md").write_text("# spec\n", encoding="utf-8")
    (repo / "prompts").mkdir()
    (repo / "prompts" / "plan_create.md").write_text("# plan prompt\n", encoding="utf-8")
    (repo / "src" / "drydock").mkdir(parents=True)
    (repo / "src" / "drydock" / "build.py").write_text('"""Builds."""\n', encoding="utf-8")
    return repo


def test_score_drydock_uses_the_highest_model_by_default(tmp_path: Path) -> None:
    runner = RecordingRunner(reply=_payload())
    score_drydock(runner=runner, repo_root=_throwaway_repo(tmp_path), log_dir=tmp_path)
    assert runner.calls[0]["model"] == HIGHEST_MODEL
    assert runner.calls[0]["command_name"] == "score drydock"


def test_score_drydock_honors_an_explicit_model_override(tmp_path: Path) -> None:
    runner = RecordingRunner(reply=_payload())
    score_drydock(
        runner=runner, repo_root=_throwaway_repo(tmp_path), log_dir=tmp_path, model="opus"
    )
    assert runner.calls[0]["model"] == "opus"


def test_score_drydock_uses_the_prompts_declared_effort(tmp_path: Path) -> None:
    """The assessment is one deep reasoning pass, so the prompt declares its own effort."""
    from drydock.config import EFFORT_LEVELS
    from drydock.prompts import load_prompt

    declared = load_prompt("score_drydock").effort
    assert declared in EFFORT_LEVELS

    runner = RecordingRunner(reply=_payload())
    score_drydock(runner=runner, repo_root=_throwaway_repo(tmp_path), log_dir=tmp_path)
    assert runner.calls[0]["effort"] == declared


def test_score_drydock_honors_an_explicit_effort_override(tmp_path: Path) -> None:
    runner = RecordingRunner(reply=_payload())
    score_drydock(
        runner=runner, repo_root=_throwaway_repo(tmp_path), log_dir=tmp_path, effort="low"
    )
    assert runner.calls[0]["effort"] == "low"


def test_score_drydock_pins_the_provider_that_serves_the_highest_model(tmp_path: Path) -> None:
    """The default model is a Claude model, so a codex-configured workspace must not be consulted:
    deferring to it would fail the run as a provider/model mismatch."""
    from drydock.llm import provider_model_conflict

    runner = RecordingRunner(reply=_payload())
    score_drydock(runner=runner, repo_root=_throwaway_repo(tmp_path), log_dir=tmp_path)
    call = runner.calls[0]
    assert call["llm"] == HIGHEST_MODEL_PROVIDER == "claude"
    assert provider_model_conflict(call["llm"], call["model"]) is None


def test_score_drydock_honors_an_explicit_provider_override(tmp_path: Path) -> None:
    runner = RecordingRunner(reply=_payload())
    score_drydock(
        runner=runner,
        repo_root=_throwaway_repo(tmp_path),
        log_dir=tmp_path,
        model="gpt-5",
        llm_provider="codex",
    )
    assert runner.calls[0]["llm"] == "codex"
    assert runner.calls[0]["model"] == "gpt-5"


def test_score_drydock_writes_the_plan_under_docs(tmp_path: Path) -> None:
    repo = _throwaway_repo(tmp_path)
    runner = RecordingRunner(reply=_payload(), stats=FakeStats(model="fable"))
    result = score_drydock(runner=runner, repo_root=repo, log_dir=tmp_path)

    assert result.planning_dir == repo / "docs" / "drydock_planning"
    assert result.index_path.is_file()
    assert result.feature_paths[0].is_file()
    assert result.review_model == "fable"
    assert result.exit_code() == 0


def test_score_drydock_fails_when_the_model_returns_nothing(tmp_path: Path) -> None:
    def empty_runner(prompt: str, cwd: Path, **kwargs) -> FakeRun:
        return FakeRun(ok=True, text="   ")

    with pytest.raises(SpecificationError):
        score_drydock(runner=empty_runner, repo_root=_throwaway_repo(tmp_path), log_dir=tmp_path)


def test_score_drydock_does_not_grant_the_agent_tools(tmp_path: Path) -> None:
    """The module writes the plan; the model only returns text."""
    runner = RecordingRunner(reply=_payload())
    score_drydock(runner=runner, repo_root=_throwaway_repo(tmp_path), log_dir=tmp_path)
    assert runner.calls[0].get("allow_tools") in (None, False)


# ── CLI contract ──────────────────────────────────────────────────────────────


def test_cli_dispatches_score_drydock_with_no_overrides(monkeypatch) -> None:
    import argparse

    from drydock import cli

    seen: dict = {}

    def fake(model=None, llm_provider=None, effort=None):
        seen.update({"model": model, "llm_provider": llm_provider})
        return 0

    monkeypatch.setattr(cli, "cmd_score_drydock", fake)
    args = argparse.Namespace(args=["drydock"], model=None, llm_provider=None)
    assert cli._dispatch_score(args) == 0
    assert seen == {"model": None, "llm_provider": None}


def test_cli_passes_invocation_wide_overrides_to_score_drydock(monkeypatch) -> None:
    """``--model`` / ``--llm-provider`` are stripped from argv before the score operands are
    parsed, so they must be read off the namespace or they are silently lost."""
    import argparse

    from drydock import cli

    seen: dict = {}

    def fake(model=None, llm_provider=None, effort=None):
        seen.update({"model": model, "llm_provider": llm_provider})
        return 0

    monkeypatch.setattr(cli, "cmd_score_drydock", fake)
    args = argparse.Namespace(args=["drydock"], model="opus", llm_provider="claude")
    assert cli._dispatch_score(args) == 0
    assert seen == {"model": "opus", "llm_provider": "claude"}


def test_cli_rejects_a_target_after_score_drydock() -> None:
    import argparse

    from drydock.cli import UsageError, _dispatch_score

    with pytest.raises(UsageError):
        _dispatch_score(argparse.Namespace(args=["drydock", "SomeTarget"], model=None))


def test_cli_rejects_operands_score_drydock_does_not_take() -> None:
    from drydock.cli import UsageError, _reject_score_drydock_operands

    assert _reject_score_drydock_operands([]) is None
    with pytest.raises(UsageError):
        _reject_score_drydock_operands(["SomeTarget"])


def test_cli_dispatches_the_invocation_wide_effort(monkeypatch) -> None:
    """``--effort`` is stripped from argv as an invocation-wide override, so the score
    dispatcher reads it from the namespace, not from its own operands."""
    import argparse

    from drydock import cli

    seen: dict = {}

    def fake(model=None, llm_provider=None, effort=None):
        seen.update({"model": model, "llm_provider": llm_provider, "effort": effort})
        return 0

    monkeypatch.setattr(cli, "cmd_score_drydock", fake)
    args = argparse.Namespace(args=["drydock"], model=None, llm_provider=None, effort="high")
    assert cli._dispatch_score(args) == 0
    assert seen == {"model": None, "llm_provider": None, "effort": "high"}


def test_cli_score_drydock_ignores_the_configured_codex_provider(monkeypatch) -> None:
    """The reported failure: a codex-configured workspace made the default fable run a hard
    provider/model mismatch. The command must not consult the configured provider at all."""
    import argparse

    from drydock import cli
    from drydock.llm import provider_model_conflict
    from drydock.score_drydock import HIGHEST_MODEL, HIGHEST_MODEL_PROVIDER

    monkeypatch.setenv("LLM_PROVIDER", "codex")
    seen: dict = {}

    def fake(model=None, llm_provider=None, effort=None):
        seen.update({"model": model, "llm_provider": llm_provider})
        return 0

    monkeypatch.setattr(cli, "cmd_score_drydock", fake)
    cli._dispatch_score(argparse.Namespace(args=["drydock"], model=None, llm_provider=None))
    resolved_provider = seen["llm_provider"] or HIGHEST_MODEL_PROVIDER
    resolved_model = seen["model"] or HIGHEST_MODEL
    assert provider_model_conflict(resolved_provider, resolved_model) is None


def test_cli_score_help_lists_the_drydock_subverb(capsys) -> None:
    from drydock.cli import main

    with pytest.raises(SystemExit):
        main(["score", "--help"])
    assert "drydock score drydock" in capsys.readouterr().out


def test_score_drydock_is_an_llm_invocation() -> None:
    import argparse

    from drydock.cli import _invocation_uses_llm

    assert _invocation_uses_llm(argparse.Namespace(command="score", args=["drydock"]))
    assert not _invocation_uses_llm(argparse.Namespace(command="score", args=["ac", "T"]))
