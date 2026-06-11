"""Cross-platform task runner for Drydock.

Run from any OS with uv installed:

    uv run nox -l            # list sessions
    uv run nox               # default sessions: lint, type, tests
    uv run nox -s build      # build wheel + sdist and verify embedded Rigging

Sessions use the uv backend so dependency resolution matches CI.
"""

from __future__ import annotations

import nox

nox.options.default_venv_backend = "uv"
nox.options.sessions = ["lint", "type", "tests"]

PYTHONS = ["3.11", "3.12", "3.13"]
LINT_PATHS = ["src/", "tests/", "scripts/", "noxfile.py"]


@nox.session
def lint(session: nox.Session) -> None:
    """Ruff lint and format check."""
    session.install("ruff>=0.4")
    session.run("ruff", "check", *LINT_PATHS)
    session.run("ruff", "format", "--check", *LINT_PATHS)


@nox.session
def type(session: nox.Session) -> None:
    """Static type check with mypy."""
    session.install("-e", ".[dev]")
    session.run("mypy")


@nox.session(python=PYTHONS)
def tests(session: nox.Session) -> None:
    """Run the test suite with coverage on each supported Python."""
    session.install("-e", ".[dev]")
    session.run("pytest", "--cov=drydock", "--cov-report=term-missing", *session.posargs)


@nox.session
def build(session: nox.Session) -> None:
    """Build the wheel and sdist, then verify the embedded Rigging copy."""
    session.install("hatchling", "build")
    session.run("python", "-m", "build")
    session.run("python", "scripts/check_wheel_rigging.py")
