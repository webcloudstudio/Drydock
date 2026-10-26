"""Static CLI dependency discovery never executes acceptance code."""

import pytest

from drydock.acceptance_order import cli_arguments


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ('cli_runner("summary", "log.jsonl")', (("summary", "log.jsonl"),)),
        ('drydock_go.cli_runner("summary", path)', (("summary", None),)),
        ('command = "summary"\ncli_runner(command, path)', (("summary", None),)),
        (
            "def run(lines, *args):\n with context():\n  return cli_runner(*args, path)\n"
            'run(records, "summary", "--target", target)',
            (("summary", "--target", None, None),),
        ),
        (
            "def run(command):\n return cli_runner(command, path)\n"
            'for report in ["summary", "targets"]:\n run(report)',
            (("summary", None), ("targets", None)),
        ),
        ('def unused():\n cli_runner("summary", path)\nassert True', ()),
        (
            "def recursive(command):\n recursive(command)\n cli_runner(command)\n"
            'recursive("summary")',
            (("summary",),),
        ),
        ('def run(command):\n return cli_runner(command)\nrun = other\nrun("summary")', ()),
        ('cli_runner = other\ncli_runner("summary")', ()),
        ("for command in unknown:\n cli_runner(command)", ((None,),)),
        (
            'command = "summary"\nif condition:\n command = runtime()\ncli_runner(command)',
            ((None,),),
        ),
        ("cli_runner(*unknown)", ()),
        ("cli_runner(", ()),
    ],
)
def test_cli_arguments(code, expected):
    assert cli_arguments(code) == expected


def test_discovery_does_not_execute_calls(tmp_path):
    marker = tmp_path / "must-not-exist"
    code = f'open({str(marker)!r}, "w").write("executed")\ncli_runner("summary")'
    assert cli_arguments(code) == (("summary",),)
    assert not marker.exists()


def test_loop_bindings_do_not_leak_a_stale_command():
    code = 'command = "summary"\nfor command in unknown:\n pass\ncli_runner(command)'
    assert cli_arguments(code) == ((None,),)


@pytest.mark.parametrize(
    "code",
    [
        'code, out, err = cli_runner("summary", "--invalid")\nassert code == 2',
        'assert cli_runner("summary", "--invalid")[0] == 2',
        "def run(*args):\n return cli_runner(*args)\n"
        'code, out, err = run("summary", "--invalid")\nassert code == 2',
    ],
)
def test_negative_cli_checks_do_not_require_the_report_implementation(code):
    assert cli_arguments(code) == ()
