"""Tests for `drydock prompt review`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.errors import DrydockError, SpecificationError
from drydock.prompt_review import (
    parse_review_payload,
    render_review_markdown,
    resolve_component,
    review_prompt,
)


@dataclass
class FakeRun:
    ok: bool = True
    text: str = ""
    execution_id: str = "exec-review"
    stats: object | None = None


_VALID_PAYLOAD = """\
{
  "scorecard": {
    "spec_alignment": 8.0,
    "input_realism": 6.0,
    "output_contract_safety": 5.0,
    "analytical_effectiveness": 7.0,
    "ambiguity_control": 6.0
  },
  "executive_assessment": "The prompt is workable but brittle where it refers to unseen inputs.",
  "general_recommendation": "Revise, do not rewrite; tighten the contract before relying on it broadly.",
  "best_plan": [
    "Remove references to inputs that are not injected.",
    "Align output examples with the parser contract."
  ],
  "findings": [
    {
      "severity": "critical",
      "title": "Prompt references unseen inputs",
      "evidence": "prompts/analyze.md checklist vs injected source-only contract",
      "impact": "This pushes the model toward hallucination or false uncertainty."
    },
    {
      "severity": "major",
      "title": "JSON example is unsafe",
      "evidence": "spike-stack example uses placeholder syntax not guaranteed to be valid JSON",
      "impact": "A malformed block can hard-fail downstream parsing."
    },
    {
      "severity": "moderate",
      "title": "Good block discipline",
      "evidence": "The prompt enumerates required output blocks and ordering clearly.",
      "impact": "This improves reproducibility and file splitting."
    }
  ],
  "strengths": [
    "The prompt names explicit output artifacts and forbids commentary outside the blocks."
  ],
  "open_questions": [
    "Should `Questions` and `Ready` remain distinct if both permit the next command?"
  ],
  "recommended_edits": [
    "Rewrite checklist items to test facts stated in imported sources or BUILD_CONFIGURATION.md only.",
    "Move stack-option instructions outside the JSON example and keep the example itself valid JSON."
  ],
  "review_method": [
    "Compared the prompt body to the authoritative spec slice and the matching notes file.",
    "Checked whether the consumer contract can parse every promised output safely."
  ]
}
"""


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "prompts").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "notes").mkdir()
    (repo / "src" / "drydock").mkdir(parents=True)
    (repo / "prompts" / "analyze.md").write_text(
        "---\nname: analyze\ndescription: x\nversion: 1\nintent: x\n---\nbody\n", encoding="utf-8"
    )
    (repo / "prompts" / "plan_create.md").write_text(
        "---\nname: plan_create\ndescription: x\nversion: 1\nintent: x\n---\nbody\n",
        encoding="utf-8",
    )
    (repo / "prompts" / "MANIFEST_CONTRACT.md").write_text(
        "# Manifest Contract\n", encoding="utf-8"
    )
    (repo / "prompts" / "BLUEPRINTS_CONTRACT.md").write_text(
        "# Blueprints Contract\n", encoding="utf-8"
    )
    (repo / "notes" / "notes_analyze.md").write_text("# Notes Analyze\n", encoding="utf-8")
    (repo / "notes" / "notes_plan.md").write_text("# Notes Plan\n", encoding="utf-8")
    (repo / "docs" / "Drydock_Specification.md").write_text(
        "\n".join([
            "# Drydock",
            "",
            "### Analyze Your Specification",
            "Analyze spec text.",
            "",
            "### Building and Reviewing the Build Plan / Manifest",
            "Plan spec text.",
        ]),
        encoding="utf-8",
    )
    (repo / "src" / "drydock" / "analyze.py").write_text(
        "PROMPT_NAME = 'analyze'\n", encoding="utf-8"
    )
    return repo


class TestResolveComponent:
    def test_known_component(self):
        component = resolve_component("analyze")
        assert component.command == "drydock analyze"

    def test_unknown_component_raises(self):
        with pytest.raises(SpecificationError, match="unknown prompt-review component"):
            resolve_component("nonesuch")


class TestParseReviewPayload:
    def test_parses_and_computes_weighted_score(self):
        review = parse_review_payload(_VALID_PAYLOAD, component=resolve_component("analyze"))
        assert review.overall_score == 6.6
        assert review.rating_band == "Brittle"
        assert review.scorecard["spec_alignment"] == 8.0

    def test_invalid_score_raises(self):
        bad = _VALID_PAYLOAD.replace('"input_realism": 6.0', '"input_realism": 12')
        with pytest.raises(DrydockError, match="between 0 and 10"):
            parse_review_payload(bad, component=resolve_component("analyze"))


class TestRenderReviewMarkdown:
    def test_renders_expected_sections(self):
        component = resolve_component("analyze")
        review = parse_review_payload(_VALID_PAYLOAD, component=component)
        rendered = render_review_markdown(
            review,
            component=component,
            reviewed_at="2026-06-15T12:00:00-04:00",
            review_model="opus",
        )
        assert "overall_score: 6.6/10" in rendered
        assert "## Findings" in rendered
        assert "Prompt Review: analyze" in rendered


class TestReviewPrompt:
    def test_writes_current_review(self, tmp_path, monkeypatch):
        repo = _make_repo(tmp_path)
        monkeypatch.setattr("drydock.prompt_review.get_repo_root", lambda: repo)
        monkeypatch.setattr(
            "drydock.prompt_review.load_prompt",
            lambda name: type("Prompt", (), {"body": "REVIEW BODY", "model": "opus"})(),
        )

        result = review_prompt("analyze", runner=lambda *a, **k: FakeRun(text=_VALID_PAYLOAD))

        assert result.component == "analyze"
        assert result.review_path == repo / "docs" / "prompt_reviews" / "analyze.md"
        assert result.review_path.is_file()
        text = result.review_path.read_text(encoding="utf-8")
        assert "review_model: opus" in text
        assert "overall_score: 6.6/10" in text
        assert result.archive_path is None

    def test_archives_previous_review(self, tmp_path, monkeypatch):
        repo = _make_repo(tmp_path)
        current = repo / "docs" / "prompt_reviews" / "analyze.md"
        current.parent.mkdir(parents=True)
        current.write_text("prior review\n", encoding="utf-8")
        monkeypatch.setattr("drydock.prompt_review.get_repo_root", lambda: repo)
        monkeypatch.setattr(
            "drydock.prompt_review.load_prompt",
            lambda name: type("Prompt", (), {"body": "REVIEW BODY", "model": "opus"})(),
        )

        result = review_prompt("analyze", runner=lambda *a, **k: FakeRun(text=_VALID_PAYLOAD))

        assert result.archive_path is not None
        assert result.archive_path.is_file()
        assert result.archive_path.read_text(encoding="utf-8") == "prior review\n"

    def test_missing_notes_file_fails(self, tmp_path, monkeypatch):
        repo = _make_repo(tmp_path)
        (repo / "notes" / "notes_analyze.md").unlink()
        monkeypatch.setattr("drydock.prompt_review.get_repo_root", lambda: repo)
        monkeypatch.setattr(
            "drydock.prompt_review.load_prompt",
            lambda name: type("Prompt", (), {"body": "REVIEW BODY", "model": "opus"})(),
        )

        with pytest.raises(SpecificationError, match="notes file not found"):
            review_prompt("analyze", runner=lambda *a, **k: FakeRun(text=_VALID_PAYLOAD))

    def test_cli_overrides_are_passed_to_runner(self, tmp_path, monkeypatch):
        repo = _make_repo(tmp_path)
        monkeypatch.setattr("drydock.prompt_review.get_repo_root", lambda: repo)
        monkeypatch.setattr(
            "drydock.prompt_review.load_prompt",
            lambda name: type("Prompt", (), {"body": "REVIEW BODY", "model": "opus"})(),
        )
        calls = []

        def runner(*a, **k):
            calls.append(k)
            return FakeRun(text=_VALID_PAYLOAD)

        review_prompt("analyze", runner=runner, model="gpt-5.4", llm_provider="codex")
        assert calls[0]["model"] == "gpt-5.4"
        assert calls[0]["llm"] == "codex"
