"""``drydock diagnose`` CLI contract: syntax, help, flag conflicts, and exit codes."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

from drydock.cli import main


def run_cli(*args: str) -> tuple[int, str, str]:
    """Run main() in-process, capturing stdout/stderr and exit code."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            main(list(args))
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
        else:
            rc = 0
    return rc, out.getvalue(), err.getvalue()


def test_diagnose_appears_in_top_level_help():
    _, out, _ = run_cli("--help")
    assert "diagnose" in out


def test_help_documents_every_form():
    rc, out, _ = run_cli("diagnose", "--help")
    assert rc == 0
    assert "drydock diagnose <Target> --apply" in out
    assert "--no-apply" in out
    assert "One LLM call" in out


def test_help_names_the_amendable_files():
    _, out, _ = run_cli("diagnose", "--help")
    for name in ("COMPASS.md", "PLAN_COMPASS.md", "ANALYZE_COMPASS.md", "MANIFEST.md"):
        assert name in out


def test_target_is_optional():
    parser_out = run_cli("diagnose", "--help")[1]
    assert "[<Target>]" in parser_out


def test_apply_and_no_apply_together_is_a_usage_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    rc, _, err = run_cli("diagnose", "Demo", "--apply", "--no-apply")
    assert rc == 2
    assert "--apply and --no-apply" in err


def test_an_unknown_flag_is_a_usage_error():
    rc, _, _ = run_cli("diagnose", "Demo", "--nonsense")
    assert rc == 2


def test_run_stamp_is_accepted():
    from drydock.cli import _build_parser

    args = _build_parser().parse_args(["diagnose", "Demo", "--run", "20260822.020100.000Z"])
    assert args.run_stamp == "20260822.020100.000Z"
    assert args.apply_all is False
    assert args.no_apply is False


def test_llm_override_flags_are_accepted():
    from drydock.cli import _build_parser

    args = _build_parser().parse_args([
        "diagnose",
        "Demo",
        "--model",
        "x",
        "--llm-provider",
        "codex",
    ])
    assert args.model == "x"
    assert args.llm_provider == "codex"


def test_a_missing_target_directory_exits_two_and_says_what_to_run(monkeypatch, tmp_path):
    (tmp_path / "targets").mkdir()
    monkeypatch.setenv("DRYDOCK_WORKSPACE", str(tmp_path))
    rc, out, _ = run_cli("diagnose", "Nope")
    assert rc == 2
    assert "drydock init Nope" in out
