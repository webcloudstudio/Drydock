"""Tests for drydock.config."""

from __future__ import annotations

from pathlib import Path

import pytest

import drydock.config as config
from drydock.config import (
    DEFAULT_MODEL,
    DEFAULT_SANDBOX_MEM_LIMIT_MB,
    blueprint_dir_for,
    build_dir_for,
    config_set,
    config_show,
    get_build_directory,
    get_codex_sandbox,
    get_escalate_model,
    get_llm_provider,
    get_model,
    get_prompt_error_tokens,
    get_prompt_warn_tokens,
    get_quarterdeck_port,
    get_sandbox_mem_limit_mb,
    get_target_directory,
    get_workspace,
    settable_config_keys,
)
from drydock.errors import ConfigurationError


class TestConfigSet:
    def test_set_drydock_build_directory(self, tmp_path, isolated_config):
        build_root = tmp_path / "builds"
        build_root.mkdir()
        cfg = config_set("drydock_build_directory", str(build_root))
        assert cfg.exists()
        content = cfg.read_text()
        assert "DRYDOCK_BUILD_DIRECTORY" in content
        assert str(build_root) in content

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

    def test_effort_is_unset_by_default(self, isolated_config):
        """Unset means the provider's own default reasoning depth stands."""
        from drydock.config import get_effort

        assert get_effort() is None

    def test_set_effort(self, isolated_config):
        from drydock.config import get_effort

        config_set("drydock_effort", "XHigh")
        assert get_effort() == "xhigh"

    def test_clearing_effort_restores_the_provider_default(self, isolated_config):
        from drydock.config import get_effort

        config_set("drydock_effort", "high")
        config_set("drydock_effort", "")
        assert get_effort() is None

    def test_set_invalid_effort_names_the_valid_levels(self, isolated_config):
        with pytest.raises(ConfigurationError, match="low, medium, high, xhigh, max"):
            config_set("drydock_effort", "ludicrous")

    def test_codex_sandbox_defaults_to_danger_full_access(self, isolated_config):
        assert get_codex_sandbox() == "danger-full-access"

    def test_set_codex_sandbox(self, isolated_config):
        config_set("codex_sandbox", "workspace-write")
        assert get_codex_sandbox() == "workspace-write"

    def test_set_invalid_codex_sandbox_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="Valid values"):
            config_set("codex_sandbox", "docker")

    def test_sandbox_mem_limit_defaults(self, isolated_config):
        assert get_sandbox_mem_limit_mb() == DEFAULT_SANDBOX_MEM_LIMIT_MB

    def test_set_sandbox_mem_limit(self, isolated_config):
        # A JVM or Go toolchain reserves far more virtual address space than it uses.
        config_set("sandbox_mem_limit", "16384")
        assert get_sandbox_mem_limit_mb() == 16384

    def test_zero_sandbox_mem_limit_lifts_the_bound(self, isolated_config):
        config_set("sandbox_mem_limit", "0")
        assert get_sandbox_mem_limit_mb() == 0

    def test_set_invalid_sandbox_mem_limit_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="non-negative integer"):
            config_set("sandbox_mem_limit", "2GB")

    def test_sandbox_mem_limit_is_shown(self, isolated_config):
        assert any(row[0] == "sandbox_mem_limit" for row in config_show())

    def test_every_settable_key_is_offered_by_the_cli(self, isolated_config):
        """The CLI's choices list was hand-maintained and had silently dropped four keys."""
        import argparse

        from drydock.cli import _build_parser

        def find_key_choices(parser):
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for sub in action.choices.values():
                        found = find_key_choices(sub)
                        if found is not None:
                            return found
                elif action.dest == "key" and action.choices:
                    return set(action.choices)
            return None

        assert find_key_choices(_build_parser()) == set(settable_config_keys())

    def test_set_prompt_warn_tokens(self, isolated_config):
        config_set("prompt_warn_tokens", "75000")
        assert get_prompt_warn_tokens() == 75000

    def test_set_invalid_prompt_warn_tokens_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="positive integer"):
            config_set("prompt_warn_tokens", "fifty")

    def test_set_zero_prompt_warn_tokens_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="positive integer"):
            config_set("prompt_warn_tokens", "0")


class TestConfigShow:
    def test_show_covers_every_settable_key(self, isolated_config):
        # Derived, not a hardcoded count: a fixed number breaks on every added key and
        # says nothing about which key is missing.
        rows = config_show()
        assert {row[0] for row in rows} == set(settable_config_keys())
        assert "drydock_build_escalate_model" in {row[0] for row in rows}

    def test_show_includes_codex_sandbox(self, isolated_config):
        keys = {row[0] for row in config_show()}
        assert "codex_sandbox" in keys

    def test_show_defaults_when_empty(self, isolated_config, tmp_path, monkeypatch):
        default_build_root = tmp_path / "projects"
        default_build_root.mkdir()
        monkeypatch.setattr(config, "_default_build_directory", lambda: default_build_root)
        rows = config_show()
        by_name = {name: (value, source) for name, value, source in rows}
        assert by_name["drydock_build_directory"] == (str(default_build_root), "default")
        ws_value, ws_source = by_name["drydock_workspace"]
        assert ws_value != "(not set)"
        assert ws_source == "default"
        assert by_name["drydock_model"][0] == "sonnet"
        assert by_name["llm_provider"][0] == "claude"
        assert by_name["prompt_warn_tokens"][0] == "50000"
        assert by_name["prompt_error_tokens"][0] == "120000"
        assert by_name["quarterdeck_port"][0] == "8080"

    def test_show_reports_source_after_set(self, tmp_workspace, isolated_config):
        config_set("drydock_workspace", str(tmp_workspace))
        rows = config_show()
        ws_row = next(r for r in rows if r[0] == "drydock_workspace")
        assert str(tmp_workspace) in ws_row[1]
        assert "config file" in ws_row[2]


class TestWorkspaceResolution:
    def test_build_directory_from_config_file(self, tmp_path, isolated_config):
        build_root = tmp_path / "builds"
        build_root.mkdir()
        config_set("drydock_build_directory", str(build_root))
        assert get_build_directory() == build_root.resolve()

    def test_build_directory_env_overrides_file(self, tmp_path, isolated_config, monkeypatch):
        configured = tmp_path / "configured"
        configured.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        config_set("drydock_build_directory", str(configured))
        monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(other))
        assert get_build_directory() == other.resolve()

    def test_build_directory_defaults_to_workspace_build(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        assert get_build_directory() == (tmp_workspace / "build").resolve()

    def test_build_directory_env_is_created_when_missing(
        self, tmp_path, isolated_config, monkeypatch
    ):
        build_root = tmp_path / "new" / "builds"
        monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))
        assert get_build_directory() == build_root.resolve()
        assert build_root.is_dir()

    def test_build_dir_for_target(self, tmp_path, isolated_config, monkeypatch):
        build_root = tmp_path / "builds"
        build_root.mkdir()
        monkeypatch.setenv("DRYDOCK_BUILD_DIRECTORY", str(build_root))
        assert build_dir_for("Example") == build_root / "Example"

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

    def test_workspace_falls_back_to_git_toplevel(self, isolated_config, tmp_path, monkeypatch):
        # No DRYDOCK_WORKSPACE: falls back to the Git top-level of cwd.
        monkeypatch.setattr(config, "_git_toplevel", lambda _p: tmp_path)
        assert get_workspace() == tmp_path

    def test_workspace_unset_and_no_git_raises(self, isolated_config, tmp_path, monkeypatch):
        # No DRYDOCK_WORKSPACE and no Git repo: refuse rather than guess a directory.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(config, "_git_toplevel", lambda _p: None)
        with pytest.raises(ConfigurationError):
            get_workspace()

    def test_require_target_dir_returns_existing(self, tmp_workspace, isolated_config, monkeypatch):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        target_dir = tmp_workspace / "targets" / "Demo"
        target_dir.mkdir(parents=True)
        assert config.require_target_dir("Demo") == target_dir

    def test_require_target_dir_uninitialized_raises_run_init(
        self, tmp_workspace, isolated_config, monkeypatch
    ):
        monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_workspace))
        with pytest.raises(ConfigurationError, match="drydock init Demo"):
            config.require_target_dir("Demo")


class TestGetModel:
    def test_default_is_sonnet(self, isolated_config):
        assert get_model() == DEFAULT_MODEL
        assert get_model() == "sonnet"

    def test_cli_override_wins(self, isolated_config):
        assert get_model("opus") == "opus"

    def test_env_var_overrides_default(self, isolated_config, monkeypatch):
        monkeypatch.setenv("DRYDOCK_MODEL", "haiku")
        assert get_model() == "haiku"

    def test_cli_override_wins_over_env(self, isolated_config, monkeypatch):
        monkeypatch.setenv("DRYDOCK_MODEL", "haiku")
        assert get_model("opus") == "opus"

    def test_config_set_persists(self, isolated_config):
        config_set("drydock_model", "opus")
        assert get_model() == "opus"

    def test_config_set_empty_raises(self, isolated_config):
        from drydock.errors import ConfigurationError

        with pytest.raises(ConfigurationError, match="must not be empty"):
            config_set("drydock_model", "")


class TestEscalateModel:
    def test_defaults_to_none(self, isolated_config):
        assert get_escalate_model() is None

    def test_cli_override_wins(self, isolated_config):
        assert get_escalate_model("opus") == "opus"

    def test_empty_cli_override_is_none(self, isolated_config):
        assert get_escalate_model("") is None

    def test_config_set_persists_and_clears(self, isolated_config):
        config_set("drydock_build_escalate_model", "opus")
        assert get_escalate_model() == "opus"
        config_set("drydock_build_escalate_model", "")
        assert get_escalate_model() is None

    def test_environment_overrides_file(self, isolated_config, monkeypatch):
        config_set("drydock_build_escalate_model", "sonnet")
        monkeypatch.setenv("DRYDOCK_BUILD_ESCALATE_MODEL", "opus")
        assert get_escalate_model() == "opus"


class TestGetters:
    def test_llm_provider_defaults_to_claude(self, isolated_config):
        assert get_llm_provider() == "claude"

    def test_llm_provider_cli_override_wins(self, isolated_config):
        assert get_llm_provider("codex") == "codex"

    def test_llm_provider_environment_overrides_file(self, isolated_config, monkeypatch):
        config_set("llm_provider", "claude")
        monkeypatch.setenv("LLM_PROVIDER", "codex")
        assert get_llm_provider() == "codex"

    def test_llm_provider_cli_override_wins_over_environment(self, isolated_config, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "claude")
        assert get_llm_provider("codex") == "codex"

    def test_prompt_warn_tokens_defaults_to_50000(self, isolated_config):
        assert get_prompt_warn_tokens() == 50000

    def test_prompt_warn_tokens_environment_overrides_file(self, isolated_config, monkeypatch):
        config_set("prompt_warn_tokens", "75000")
        monkeypatch.setenv("PROMPT_WARN_TOKENS", "100000")
        assert get_prompt_warn_tokens() == 100000

    def test_prompt_warn_tokens_invalid_environment_raises(self, isolated_config, monkeypatch):
        monkeypatch.setenv("PROMPT_WARN_TOKENS", "-5")
        with pytest.raises(ConfigurationError, match="positive integer"):
            get_prompt_warn_tokens()

    def test_prompt_error_tokens_defaults_to_120000(self, isolated_config):
        """The red light sits well above the yellow one, which is tripped routinely."""
        assert get_prompt_error_tokens() == 120000
        assert get_prompt_error_tokens() > get_prompt_warn_tokens()

    def test_prompt_error_tokens_environment_overrides_file(self, isolated_config, monkeypatch):
        config_set("prompt_error_tokens", "150000")
        monkeypatch.setenv("PROMPT_ERROR_TOKENS", "200000")
        assert get_prompt_error_tokens() == 200000

    def test_prompt_error_tokens_invalid_environment_raises(self, isolated_config, monkeypatch):
        monkeypatch.setenv("PROMPT_ERROR_TOKENS", "-5")
        with pytest.raises(ConfigurationError, match="positive integer"):
            get_prompt_error_tokens()

    def test_set_invalid_prompt_error_tokens_raises(self, isolated_config):
        with pytest.raises(ConfigurationError, match="prompt_error_tokens"):
            config_set("prompt_error_tokens", "lots")

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


class TestConfigEnv:
    """``drydock config env`` — the path contract scripts consume instead of hardcoding."""

    def _run(self, *args: str) -> tuple[int, str]:
        import io
        from contextlib import redirect_stdout

        from drydock.cli import main

        out = io.StringIO()
        with redirect_stdout(out):
            try:
                main(["config", "env", *args])
            except SystemExit as exc:
                return int(exc.code or 0), out.getvalue()
        return 0, out.getvalue()

    def _parse(self, text: str) -> dict[str, str]:
        import shlex

        rows = {}
        for line in text.splitlines():
            key, _, value = line.partition("=")
            rows[key] = shlex.split(value)[0] if value else ""
        return rows

    def test_bare_env_reports_the_roots_and_no_target(self, tmp_workspace, isolated_config):
        config_set("drydock_workspace", str(tmp_workspace))

        rc, out = self._run()

        assert rc == 0
        rows = self._parse(out)
        assert rows["DRYDOCK_WORKSPACE"] == str(tmp_workspace)
        assert rows["DRYDOCK_TARGETS_ROOT"] == str(tmp_workspace / "targets")
        assert "DRYDOCK_TARGET_DIR" not in rows

    def test_naming_a_target_adds_its_directories(self, tmp_workspace, isolated_config):
        config_set("drydock_workspace", str(tmp_workspace))

        rc, out = self._run("Demo")

        assert rc == 0
        rows = self._parse(out)
        assert rows["DRYDOCK_TARGET"] == "Demo"
        assert rows["DRYDOCK_TARGET_DIR"] == str(tmp_workspace / "targets" / "Demo")
        assert rows["DRYDOCK_TARGET_BUILD_DIR"].endswith("Demo")

    def test_an_uninitialized_target_still_resolves(self, tmp_workspace, isolated_config):
        """A driver has to learn the paths before it can create the Target."""
        config_set("drydock_workspace", str(tmp_workspace))
        assert not (tmp_workspace / "targets" / "Fresh").exists()

        rc, out = self._run("Fresh")

        assert rc == 0
        assert "DRYDOCK_TARGET_DIR" in self._parse(out)

    def test_output_is_masthead_free_and_eval_safe(self, tmp_path, isolated_config):
        spaced = tmp_path / "work space"
        spaced.mkdir()
        config_set("drydock_workspace", str(spaced))

        rc, out = self._run("Demo")

        assert rc == 0
        # The masthead would be parsed as a stray command by eval.
        assert "Drydock " not in out
        assert all("=" in line for line in out.splitlines())
        assert self._parse(out)["DRYDOCK_WORKSPACE"] == str(spaced)


def test_max_consecutive_stalls_follows_the_uat_marker(monkeypatch):
    from drydock.config import is_uat_run, max_consecutive_stalls

    monkeypatch.delenv("DRYDOCK_UAT", raising=False)
    assert not is_uat_run()
    # Interactively the first flat pass ends the block.
    assert max_consecutive_stalls() == 1

    monkeypatch.setenv("DRYDOCK_UAT", "1")
    assert is_uat_run()
    # A UAT run tolerates one flat pass as noise; two in a row is a stall.
    assert max_consecutive_stalls() == 2

    # Marks one execution, never a persisted setting: an unrecognized value is not UAT mode.
    monkeypatch.setenv("DRYDOCK_UAT", "off")
    assert max_consecutive_stalls() == 1


def test_the_stall_count_is_the_only_uat_specific_repair_behavior():
    """UAT may pay for more passes; it may never suppress an error class that would gate.

    A leniency that hides a real failure makes the measurement worthless, so the marker is
    allowed exactly one consumer inside the repair path.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "drydock"
    callers = sorted(
        path.name
        for path in src.glob("*.py")
        if "is_uat_run" in path.read_text(encoding="utf-8") and path.name != "config.py"
    )
    assert callers == [], f"is_uat_run() consumed outside config.py: {callers}"
