"""Allowed models and aliases in ``model_config.jsonl``: resolution, validation, fatal stop."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from drydock import model_config
from drydock.config import config_set, get_model
from drydock.errors import ConfigurationError, LlmError
from drydock.llm import fatal_stop, fatal_stop_reason, resolve_provider, run_prompt
from tests.test_llm import FakePopen

CODEX_CACHE = {
    "models": [
        {"slug": "gpt-6.1-sol", "visibility": "list"},
        {"slug": "gpt-6-sol", "visibility": "list"},
        {"slug": "gpt-5.6-sol", "visibility": "list"},
        {"slug": "gpt-6-luna", "visibility": "list"},
        {"slug": "gpt-5.6-luna", "visibility": "list"},
        {"slug": "gpt-reserve", "visibility": "hide"},
    ]
}


@pytest.fixture()
def seed_models(tmp_path: Path, monkeypatch):
    """The seed's real model lists, with codex's catalog at a test file (absent by default)."""
    catalog = tmp_path / "models_cache.json"
    rows = []
    for line in model_config.seed_path().read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("catalog"):
            row["catalog"] = str(catalog)
        rows.append(json.dumps(row))
    path = tmp_path / "model_config.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("DRYDOCK_MODEL_CONFIG", str(path))
    return catalog


def test_seed_lives_at_the_repository_root():
    assert model_config.seed_path().parent == Path(__file__).resolve().parents[1]


def test_an_alias_selects_the_newest_catalog_model(seed_models):
    seed_models.write_text(json.dumps(CODEX_CACHE), encoding="utf-8")
    assert model_config.resolve_model("sol") == "gpt-6.1-sol"
    assert model_config.resolve_model("luna") == "gpt-6-luna"


def test_an_alias_falls_back_to_the_listed_models_without_a_catalog(seed_models):
    assert model_config.resolve_model("sol") == "gpt-6.1-sol"
    assert model_config.resolve_model("terra") == "gpt-5.6-terra"


def test_native_aliases_and_full_names_pass_through(seed_models):
    for name in ("haiku", "opus", "pro", "gpt-5.6-luna"):
        assert model_config.resolve_model(name) == name


def test_a_listed_name_selects_its_provider(seed_models):
    assert resolve_provider(None, "sol") == "codex"
    assert resolve_provider(None, "flash") == "gemini"
    assert resolve_provider(None, "haiku") == "claude"


def test_the_catalog_replaces_the_listed_models_and_hides_hidden_ones(seed_models):
    seed_models.write_text(json.dumps(CODEX_CACHE), encoding="utf-8")
    assert model_config.invalid_model("codex", "gpt-6.1-sol") is None
    assert model_config.invalid_model("codex", "gpt-6-astra") is not None
    assert model_config.invalid_model("codex", "gpt-reserve") is not None


def test_an_invalid_model_names_every_allowed_model(seed_models):
    problem = model_config.invalid_model("codex", "luna-x")
    assert problem.startswith("Invalid model: model 'luna-x' is not available on codex.")
    assert "Allowed codex models: sol, luna, astra, terra, gpt-6.1-sol" in problem
    assert model_config.invalid_model("claude", "claude-haiku-4-5") is not None


def test_an_alias_matching_no_model_is_invalid(seed_models):
    seed_models.write_text(json.dumps({"models": [{"slug": "gpt-6-luna"}]}), encoding="utf-8")
    assert "alias 'sol' matches no codex model" in model_config.invalid_model("codex", "sol")


def test_config_set_refuses_an_invalid_model(seed_models, isolated_config, monkeypatch):
    monkeypatch.delenv("DRYDOCK_MODEL", raising=False)
    with pytest.raises(ConfigurationError, match="Allowed claude models: haiku"):
        config_set("drydock_model", "claude-haiku-4-5")
    config_set("drydock_model", "sol")
    assert get_model() == "gpt-6.1-sol"


def test_run_prompt_stops_fatally_before_sending_an_invalid_model(
    seed_models, tmp_path, monkeypatch
):
    spawned: list[object] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a))

    with pytest.raises(LlmError, match="Allowed codex models"):
        run_prompt("Work", tmp_path, llm="codex", model="luna-x", announce=False)

    assert spawned == []
    stop = fatal_stop()
    assert stop is not None and stop.kind == "invalid model"
    assert "Allowed codex models: sol" in stop.recovery()


def test_run_prompt_sends_the_model_an_alias_selects(seed_models, tmp_path, monkeypatch):
    commands: list[list[str]] = []

    def popen(command, **kwargs):
        commands.append(command)
        return FakePopen(command, stdout_text="", returncode=0, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    run_prompt("Work", tmp_path, llm="codex", model="sol", announce=False)
    assert commands[0][commands[0].index("--model") + 1] == "gpt-6.1-sol"


@pytest.mark.parametrize(
    "provider_error",
    [
        "provider error: The 'luna' model is not supported when using Codex with a ChatGPT account.",
        "There's an issue with the selected model (claude-x). It may not exist.",
    ],
)
def test_a_provider_rejecting_the_model_is_fatal(provider_error):
    assert fatal_stop_reason("", provider_error) == "invalid model"
