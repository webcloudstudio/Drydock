"""model_config.jsonl: matching, estimates, price-limit escalation, and calibration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drydock import model_config
from drydock.errors import ConfigurationError
from drydock.model_config import (
    ESCALATION_FRACTION,
    Observation,
    apply,
    calibration_notice,
    claude_request_usage,
    escalation,
    load,
    parse,
    propose,
    read_observations,
    record_observation,
    seed_path,
    unprobed_cli,
)


def _seed() -> model_config.ModelConfig:
    return parse(seed_path().read_text(encoding="utf-8"), seed_path())


def _observation(**fields) -> Observation:
    base = dict(
        at="2026-10-13T00:00:00Z",
        model="haiku",
        resolved_model="claude-haiku-5-5",
        provider="claude",
        mode="build",
        cli_version="2.1.296",
        prompt_bytes=26_100,
        first_request_tokens=0,
    )
    base.update(fields)
    return Observation(**base)


class TestSeed:
    def test_seed_parses_with_a_catch_all_row(self):
        config = _seed()
        assert config.model("anything-unknown").match == ("*",)

    @pytest.mark.parametrize(
        ("model", "label"),
        [
            ("claude-haiku-4-5", "haiku-4|haiku-3"),
            ("haiku", "haiku"),
            ("claude-haiku-5-5", "haiku"),
            ("Sonnet", "sonnet"),
            ("claude-opus-5-5", "opus"),
            ("claude-fable-5-1", "fable|claude"),
            ("gpt-6.1-sol", "sol"),
            ("gpt-5.6-luna", "gpt-|gpt5|codex|luna|o3-|o4-"),
        ],
    )
    def test_first_matching_row_wins(self, model, label):
        assert _seed().model(model).label == label

    def test_only_opus_and_sol_default_to_low_effort(self):
        config = _seed()
        assert {p.label: p.effort for p in config.models if p.effort} == {
            "opus": "low",
            "sol": "low",
        }

    def test_invalid_row_effort_is_rejected(self, tmp_path):
        row = _seed().rows[-1] | {"effort": "extreme"}
        path = tmp_path / "model_config.jsonl"
        with pytest.raises(ConfigurationError, match="extreme"):
            parse(json.dumps(row), path)

    def test_only_haiku_5_5_has_a_price_limit(self):
        config = _seed()
        limited = [p.label for p in config.models if p.prompt_limit_tokens]
        assert limited == ["haiku"]
        assert config.model("haiku").escalate_model == "sonnet"
        assert config.model("haiku").prompt_limit_tokens == 100_000

    def test_build_tool_surface_is_a_code_builder(self):
        args = _seed().provider("claude").args(allow_tools=True)
        assert args[args.index("--tools") + 1] == "Bash,Read,Edit,Write,Glob,Grep"
        assert "--strict-mcp-config" in args

    def test_text_runs_get_no_tools(self):
        args = _seed().provider("claude").args(allow_tools=False)
        assert args[args.index("--tools") + 1] == ""


class TestLoad:
    def test_live_copy_is_created_from_the_seed(self, tmp_path, monkeypatch):
        live = tmp_path / "cfg" / "model_config.jsonl"
        monkeypatch.setenv("DRYDOCK_MODEL_CONFIG", str(live))
        config = load()
        assert live.read_text(encoding="utf-8") == seed_path().read_text(encoding="utf-8")
        assert config.path == live

    def test_edits_to_the_live_copy_are_read(self, set_model_fields):
        set_model_fields(prompt_target_tokens=1234)
        assert load().model("haiku").prompt_target_tokens == 1234

    @pytest.mark.parametrize(
        "line",
        [
            "not json",
            '{"kind": "other"}',
            '{"kind": "model", "provider": "claude", "match": ["x"]}',
            '{"kind": "model", "provider": "claude", "match": ["x"], "bytes_per_token": 0,'
            ' "overhead_tokens": {}, "prompt_target_tokens": 1, "prompt_warning_tokens": 1}',
        ],
    )
    def test_invalid_rows_are_configuration_errors(self, line):
        with pytest.raises(ConfigurationError):
            parse(line + "\n", Path("model_config.jsonl"))


class TestEstimate:
    def test_estimate_uses_the_model_ratio(self, set_model_fields):
        set_model_fields(bytes_per_token=2.5)
        assert model_config.estimate_tokens(1000, "haiku") == 400

    def test_story_points_follow_the_active_model(self, set_model_fields, monkeypatch):
        from drydock.build import story_points_for

        set_model_fields(bytes_per_token=2.0)
        monkeypatch.setenv("DRYDOCK_MODEL", "haiku")
        assert story_points_for(1001) == 501


class TestEscalation:
    def _limit_bytes(self, profile, allow_tools: bool) -> int:
        """Largest prompt whose estimate stays at or under the escalation threshold."""
        threshold = ESCALATION_FRACTION * profile.prompt_limit_tokens
        budget = int(threshold) - profile.overhead(allow_tools)
        return int(budget * profile.bytes_per_token)

    def test_under_the_threshold_stays_on_haiku(self):
        profile = load().model("haiku")
        size = self._limit_bytes(profile, True)
        assert escalation("haiku", size, allow_tools=True) is None

    def test_over_98_percent_runs_on_the_escalation_model(self):
        profile = load().model("haiku")
        size = self._limit_bytes(profile, True) + 8 * int(profile.bytes_per_token)
        found = escalation("haiku", size, allow_tools=True)
        assert found is not None
        assert found.to_model == "sonnet"
        assert found.estimated_tokens > ESCALATION_FRACTION * found.limit_tokens

    def test_overhead_counts_toward_the_limit(self):
        profile = load().model("haiku")
        size = self._limit_bytes(profile, False)
        assert escalation("haiku", size, allow_tools=False) is None
        assert escalation("haiku", size, allow_tools=True) is not None

    def test_resumed_context_counts_toward_the_limit(self):
        assert escalation("haiku", 400, allow_tools=True, prior_context_tokens=99_000)

    def test_models_without_a_limit_never_escalate(self):
        assert escalation("sonnet", 10_000_000, allow_tools=True) is None


class TestCalibration:
    def test_request_usage_reads_first_and_last_requests(self):
        events = [
            {
                "type": "system",
                "subtype": "init",
                "model": "claude-haiku-5-5",
                "claude_code_version": "2.1.296",
            },
            {"type": "assistant", "message": {"usage": {"input_tokens": 0}}},
            {
                "type": "assistant",
                "message": {"usage": {"input_tokens": 9, "cache_creation_input_tokens": 1000}},
            },
            {
                "type": "assistant",
                "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": 5000}},
            },
        ]
        usage = claude_request_usage(events)
        assert usage.resolved_model == "claude-haiku-5-5"
        assert usage.cli_version == "2.1.296"
        assert usage.first_request_tokens == 1009
        assert usage.last_request_tokens == 5001

    def test_observations_round_trip(self, tmp_path):
        record_observation(tmp_path, _observation(first_request_tokens=17_437))
        assert read_observations(tmp_path) == [_observation(first_request_tokens=17_437)]

    def test_ratio_is_proposed_from_ordinary_runs(self, set_model_fields):
        set_model_fields(bytes_per_token=4.0, overhead_tokens={"build": 7437, "text": 2813})
        config = load()
        # 26,100 bytes at 2.61 bytes per token = 10,000 tokens, plus the build overhead.
        runs = [_observation(first_request_tokens=17_437) for _ in range(3)]
        runs.append(_observation(first_request_tokens=90_000, resumed=True))
        (proposal,) = propose(config, runs)
        assert proposal.field == "bytes_per_token"
        assert proposal.proposed == 2.61
        assert proposal.runs == 3

    def test_too_few_runs_propose_nothing(self, set_model_fields):
        set_model_fields(bytes_per_token=4.0, overhead_tokens={"build": 7437, "text": 2813})
        runs = [_observation(first_request_tokens=17_437) for _ in range(2)]
        assert propose(load(), runs) == []

    def test_probe_proposes_overhead(self, set_model_fields):
        set_model_fields(overhead_tokens={"build": 7437, "text": 2813})
        probe = _observation(probe=True, prompt_bytes=40, first_request_tokens=9010)
        (proposal,) = propose(load(), [probe])
        assert proposal.field == "overhead_tokens.build"
        assert proposal.proposed == 9000

    def test_matching_evidence_proposes_nothing(self, set_model_fields):
        set_model_fields(bytes_per_token=2.61, overhead_tokens={"build": 7437, "text": 2813})
        runs = [_observation(first_request_tokens=17_437) for _ in range(3)]
        assert propose(load(), runs) == []

    def test_apply_writes_only_the_proposed_fields(self, set_model_fields):
        path = set_model_fields(bytes_per_token=4.0, overhead_tokens={"build": 7437, "text": 2813})
        before = [json.loads(line) for line in path.read_text().splitlines()]
        runs = [_observation(first_request_tokens=17_437) for _ in range(3)]
        apply(load(), propose(load(), runs), today="2026-10-13")
        after = [json.loads(line) for line in path.read_text().splitlines()]
        changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        index = load().model("haiku").index
        assert changed == [index]
        assert after[index]["bytes_per_token"] == 2.61
        assert after[index]["measured"] == {"cli": "2.1.296", "at": "2026-10-13", "runs": 3}
        assert load().model("haiku").bytes_per_token == 2.61

    def test_unprobed_cli_is_detected(self):
        config = load()
        assert unprobed_cli(config, _observation(cli_version="9.9.9"))
        assert not unprobed_cli(config, _observation(cli_version="2.1.296"))

    def test_notice_is_reported_once(self, tmp_path, set_model_fields):
        set_model_fields(bytes_per_token=4.0, overhead_tokens={"build": 7437, "text": 2813})
        for _ in range(3):
            record_observation(tmp_path, _observation(first_request_tokens=17_437))
        notice = calibration_notice(tmp_path)
        assert notice is not None
        assert "bytes_per_token 4.0 -> 2.61" in notice
        assert calibration_notice(tmp_path) is None

    def test_no_evidence_no_notice(self, tmp_path):
        assert calibration_notice(tmp_path) is None
