"""Tests for .env materialization from the built project's .env.example."""

from __future__ import annotations

from pathlib import Path

from drydock.build_environment import declared_keys, is_secret_name, materialize_env_file


def _example(build_dir: Path, text: str) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / ".env.example").write_text(text, encoding="utf-8")


def _values(env_path: Path) -> dict[str, str]:
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_generates_a_secret_for_a_placeholder_value(tmp_path: Path):
    _example(tmp_path, "SECRET_KEY=change-me\nAPP_PORT=5001\n")

    result = materialize_env_file(tmp_path)

    assert result.created is True
    assert result.generated_keys == ("SECRET_KEY",)
    values = _values(tmp_path / ".env")
    assert values["SECRET_KEY"] not in {"change-me", ""}
    assert len(values["SECRET_KEY"]) >= 40
    assert values["APP_PORT"] == "5001"


def test_each_build_directory_gets_its_own_secret(tmp_path: Path):
    _example(tmp_path / "a", "SECRET_KEY=change-me\n")
    _example(tmp_path / "b", "SECRET_KEY=change-me\n")

    materialize_env_file(tmp_path / "a")
    materialize_env_file(tmp_path / "b")

    first = _values(tmp_path / "a" / ".env")["SECRET_KEY"]
    second = _values(tmp_path / "b" / ".env")["SECRET_KEY"]
    assert first != second


def test_existing_env_is_never_rewritten(tmp_path: Path):
    """A rebuild must not rotate the signing key live sessions and data depend on."""
    _example(tmp_path, "SECRET_KEY=change-me\n")
    (tmp_path / ".env").write_text("SECRET_KEY=operator-chosen\n", encoding="utf-8")

    result = materialize_env_file(tmp_path)

    assert result.created is False
    assert result.detail == "existing .env preserved"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "SECRET_KEY=operator-chosen\n"


def test_no_example_is_a_no_op(tmp_path: Path):
    tmp_path.joinpath("pyproject.toml").write_text("", encoding="utf-8")

    result = materialize_env_file(tmp_path)

    assert result.created is False
    assert result.path is None
    assert result.detail == "no .env.example"
    assert not (tmp_path / ".env").exists()


def test_comments_blanks_and_key_order_are_preserved(tmp_path: Path):
    _example(
        tmp_path,
        "# Application\nAPP_PORT=5001\n\n# Security\nSECRET_KEY=change-me\nAPP_DEBUG=0\n",
    )

    materialize_env_file(tmp_path)

    lines = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Application"
    assert lines[1] == "APP_PORT=5001"
    assert lines[2] == ""
    assert lines[3] == "# Security"
    assert lines[4].startswith("SECRET_KEY=")
    assert lines[5] == "APP_DEBUG=0"


def test_operator_placeholder_is_reported_not_invented(tmp_path: Path):
    """Drydock can generate a signing key; it cannot generate a third-party credential."""
    _example(tmp_path, "SECRET_KEY=change-me\nSMTP_PASSWORD=<your-smtp-password>\n")

    result = materialize_env_file(tmp_path)

    assert result.generated_keys == ("SECRET_KEY",)
    assert result.needs_operator_value == ("SMTP_PASSWORD",)
    assert _values(tmp_path / ".env")["SMTP_PASSWORD"] == "<your-smtp-password>"


def test_deliberate_secret_value_is_copied_through(tmp_path: Path):
    _example(tmp_path, "API_KEY=sk-fixture-000\n")

    result = materialize_env_file(tmp_path)

    assert result.generated_keys == ()
    assert _values(tmp_path / ".env")["API_KEY"] == "sk-fixture-000"


def test_empty_secret_value_counts_as_a_placeholder(tmp_path: Path):
    _example(tmp_path, "SESSION_TOKEN=\n")

    result = materialize_env_file(tmp_path)

    assert result.generated_keys == ("SESSION_TOKEN",)
    assert _values(tmp_path / ".env")["SESSION_TOKEN"]


def test_non_secret_placeholder_is_left_alone(tmp_path: Path):
    _example(tmp_path, "DATABASE_PATH=change-me\n")

    result = materialize_env_file(tmp_path)

    assert result.generated_keys == ()
    assert _values(tmp_path / ".env")["DATABASE_PATH"] == "change-me"


def test_declared_keys_reads_the_configuration_surface(tmp_path: Path):
    _example(tmp_path, "# c\nSECRET_KEY=change-me\n\nexport APP_PORT=5001\nnot a line\n")

    assert declared_keys(tmp_path) == ("SECRET_KEY", "APP_PORT")


def test_declared_keys_without_example(tmp_path: Path):
    assert declared_keys(tmp_path) == ()


def test_secret_name_detection():
    assert is_secret_name("SECRET_KEY")
    assert is_secret_name("secret_key")
    assert is_secret_name("SMTP_PASSWORD")
    assert is_secret_name("SESSION_TOKEN")
    assert is_secret_name("SIGNING_SALT")
    assert not is_secret_name("APP_PORT")
    assert not is_secret_name("DATABASE_PATH")


def test_summary_names_the_generated_key(tmp_path: Path):
    _example(tmp_path, "SECRET_KEY=change-me\n")

    summary = materialize_env_file(tmp_path).summary()

    assert "SECRET_KEY generated" in summary
    assert str(tmp_path / ".env") in summary
