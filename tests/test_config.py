"""Tests for drydock.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.config import (
    config_set,
    config_show,
    get_llm_provider,
    get_specification_directory,
    get_target_directory,
)
from drydock.errors import ConfigurationError


class TestConfigSet:
    def test_set_specification_directory(self, tmp_spec_root, isolated_config):
        cfg = config_set("specification_directory", str(tmp_spec_root))
        assert cfg.exists()
        content = cfg.read_text()
        assert "SPECIFICATION_DIRECTORY" in content
        assert str(tmp_spec_root) in content

    def test_set_target_directory(self, tmp_target_root, isolated_config):
        config_set("target_directory", str(tmp_target_root))
        val, source = _effective("TARGET_DIRECTORY", isolated_config)
        assert str(tmp_target_root) in val

    def test_set_nonexistent_directory_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="does not exist"):
            config_set("specification_directory", "/this/does/not/exist")

    def test_set_unknown_key_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="Unknown"):
            config_set("unknown_key", "/tmp")

    def test_set_expands_tilde(self, tmp_path, isolated_config, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        real_dir = tmp_path / "myspecs"
        real_dir.mkdir()
        cfg = config_set("specification_directory", "~/myspecs")
        content = cfg.read_text()
        assert str(real_dir) in content
        assert "~" not in content

    def test_set_preserves_other_keys(self, tmp_spec_root, tmp_target_root, isolated_config):
        config_set("specification_directory", str(tmp_spec_root))
        config_set("target_directory", str(tmp_target_root))
        from drydock.config import _config_path, _read_env_file

        data = _read_env_file(_config_path())
        assert "SPECIFICATION_DIRECTORY" in data
        assert "TARGET_DIRECTORY" in data

    def test_set_llm_provider(self, isolated_config):
        config_set("llm_provider", "codex")
        assert get_llm_provider() == "codex"

    def test_set_invalid_llm_provider_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="Valid values"):
            config_set("llm_provider", "other")


class TestConfigShow:
    def test_show_returns_three_rows(self, isolated_config):
        rows = config_show()
        assert len(rows) == 3

    def test_show_not_set_when_empty(self, isolated_config):
        rows = config_show()
        by_name = {name: value for name, value, _source in rows}
        assert by_name["specification_directory"] == "(not set)"
        assert by_name["target_directory"] == "(not set)"
        assert by_name["llm_provider"] == "claude"

    def test_show_reports_source_after_set(self, tmp_spec_root, isolated_config):
        config_set("specification_directory", str(tmp_spec_root))
        rows = config_show()
        spec_row = next(r for r in rows if r[0] == "specification_directory")
        assert str(tmp_spec_root) in spec_row[1]
        assert "config file" in spec_row[2]


class TestGetters:
    def test_get_spec_dir_when_set(self, tmp_spec_root, isolated_config):
        config_set("specification_directory", str(tmp_spec_root))
        assert get_specification_directory() == tmp_spec_root

    def test_get_spec_dir_raises_when_unset(self, isolated_config):
        with pytest.raises(ConfigurationError):
            get_specification_directory()

    def test_get_target_dir_raises_when_unset(self, isolated_config):
        with pytest.raises(ConfigurationError):
            get_target_directory()

    def test_env_var_overrides_file(
        self, tmp_spec_root, tmp_target_root, isolated_config, monkeypatch
    ):
        config_set("specification_directory", str(tmp_spec_root))
        monkeypatch.setenv("SPECIFICATION_DIRECTORY", str(tmp_target_root))
        result = get_specification_directory()
        assert result == tmp_target_root

    def test_llm_provider_defaults_to_claude(self, isolated_config):
        assert get_llm_provider() == "claude"

    def test_llm_provider_environment_overrides_file(self, isolated_config, monkeypatch):
        config_set("llm_provider", "claude")
        monkeypatch.setenv("LLM_PROVIDER", "codex")
        assert get_llm_provider() == "codex"


def _effective(key: str, cfg_dir: Path) -> tuple[str, str]:
    from drydock.config import _read_env_file

    env_file = cfg_dir / ".env"
    data = _read_env_file(env_file)
    return data.get(key, ""), "file"
