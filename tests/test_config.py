"""Tests for drydock.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.config import (
    blueprint_dir_for,
    config_set,
    config_show,
    get_llm_provider,
    get_prompt_warn_kb,
    get_quarterdeck_port,
    get_target_directory,
    get_workspace,
)
from drydock.errors import ConfigurationError


class TestConfigSet:
    def test_set_drydock_workspace(self, tmp_workspace, isolated_config):
        cfg = config_set("drydock_workspace", str(tmp_workspace))
        assert cfg.exists()
        content = cfg.read_text()
        assert "DRYDOCK_WORKSPACE" in content
        assert str(tmp_workspace) in content

    def test_set_nonexistent_directory_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="does not exist"):
            config_set("drydock_workspace", "/this/does/not/exist")

    def test_set_unknown_key_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="Unknown"):
            config_set("unknown_key", "/tmp")

    def test_set_expands_tilde(self, tmp_path, isolated_config, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        real_dir = tmp_path / "myws"
        real_dir.mkdir()
        cfg = config_set("drydock_workspace", "~/myws")
        content = cfg.read_text()
        assert str(real_dir) in content
        assert "~" not in content

    def test_set_llm_provider(self, isolated_config):
        config_set("llm_provider", "codex")
        assert get_llm_provider() == "codex"

    def test_set_invalid_llm_provider_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="Valid values"):
            config_set("llm_provider", "other")

    def test_set_prompt_warn_kb(self, isolated_config):
        config_set("prompt_warn_kb", "75")
        assert get_prompt_warn_kb() == 75

    def test_set_invalid_prompt_warn_kb_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="positive integer"):
            config_set("prompt_warn_kb", "fifty")

    def test_set_zero_prompt_warn_kb_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="positive integer"):
            config_set("prompt_warn_kb", "0")


class TestConfigShow:
    def test_show_returns_four_rows(self, isolated_config):
        rows = config_show()
        assert len(rows) == 4

    def test_show_defaults_when_empty(self, isolated_config):
        rows = config_show()
        by_name = {name: (value, source) for name, value, source in rows}
        ws_value, ws_source = by_name["drydock_workspace"]
        assert ws_value != "(not set)"
        assert ws_source == "default"
        assert by_name["llm_provider"][0] == "claude"
        assert by_name["prompt_warn_kb"][0] == "50"
        assert by_name["quarterdeck_port"][0] == "8080"

    def test_show_reports_source_after_set(self, tmp_workspace, isolated_config):
        config_set("drydock_workspace", str(tmp_workspace))
        rows = config_show()
        ws_row = next(r for r in rows if r[0] == "drydock_workspace")
        assert str(tmp_workspace) in ws_row[1]
        assert "config file" in ws_row[2]


class TestWorkspaceResolution:
    def test_workspace_from_config_file(self, tmp_workspace, isolated_config):
        config_set("drydock_workspace", str(tmp_workspace))
        assert get_workspace() == tmp_workspace.resolve()

    def test_workspace_env_overrides_file(
        self, tmp_workspace, tmp_path, isolated_config, monkeypatch
    ):
        config_set("drydock_workspace", str(tmp_workspace))
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(other))
        assert get_workspace() == other

    def test_blueprint_dir_is_nested_in_target(self):
        target_dir = Path("/ws/targets/Example")
        assert blueprint_dir_for(target_dir) == target_dir / "blueprint"

    def test_target_directory_is_workspace_targets(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        assert get_target_directory() == tmp_workspace / "targets"

    def test_workspace_defaults_when_unset(self, isolated_config, tmp_path, monkeypatch):
        # No DRYDOCK_WORKSPACE: falls back to the Git top-level of cwd, else cwd.
        monkeypatch.chdir(tmp_path)
        assert isinstance(get_workspace(), Path)


class TestGetters:
    def test_llm_provider_defaults_to_claude(self, isolated_config):
        assert get_llm_provider() == "claude"

    def test_llm_provider_environment_overrides_file(self, isolated_config, monkeypatch):
        config_set("llm_provider", "claude")
        monkeypatch.setenv("LLM_PROVIDER", "codex")
        assert get_llm_provider() == "codex"

    def test_prompt_warn_kb_defaults_to_50(self, isolated_config):
        assert get_prompt_warn_kb() == 50

    def test_prompt_warn_kb_environment_overrides_file(self, isolated_config, monkeypatch):
        config_set("prompt_warn_kb", "75")
        monkeypatch.setenv("PROMPT_WARN_KB", "100")
        assert get_prompt_warn_kb() == 100

    def test_prompt_warn_kb_invalid_environment_raises(self, isolated_config, monkeypatch):
        monkeypatch.setenv("PROMPT_WARN_KB", "-5")
        with pytest.raises(ConfigurationError, match="positive integer"):
            get_prompt_warn_kb()

    def test_quarterdeck_port_defaults_to_8080(self, isolated_config):
        assert get_quarterdeck_port() == 8080

    def test_quarterdeck_port_set_persists(self, isolated_config):
        config_set("quarterdeck_port", "9090")
        assert get_quarterdeck_port() == 9090

    def test_quarterdeck_port_env_overrides_file(self, isolated_config, monkeypatch):
        config_set("quarterdeck_port", "9090")
        monkeypatch.setenv("QUARTERDECK_PORT", "7777")
        assert get_quarterdeck_port() == 7777

    def test_quarterdeck_port_invalid_raises(self, isolated_config, monkeypatch):
        monkeypatch.setenv("QUARTERDECK_PORT", "not-a-port")
        with pytest.raises(ConfigurationError, match="65535"):
            get_quarterdeck_port()


class TestConfigSetQuarterdeckPort:
    def test_set_valid_port(self, isolated_config):
        config_set("quarterdeck_port", "9090")
        assert get_quarterdeck_port() == 9090

    def test_set_port_1_is_valid(self, isolated_config):
        config_set("quarterdeck_port", "1")
        assert get_quarterdeck_port() == 1

    def test_set_port_65535_is_valid(self, isolated_config):
        config_set("quarterdeck_port", "65535")
        assert get_quarterdeck_port() == 65535

    def test_set_port_0_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="65535"):
            config_set("quarterdeck_port", "0")

    def test_set_port_65536_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="65535"):
            config_set("quarterdeck_port", "65536")

    def test_set_non_integer_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="65535"):
            config_set("quarterdeck_port", "eighty")
