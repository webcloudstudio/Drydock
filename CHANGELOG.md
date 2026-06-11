# Changelog

All notable changes to Drydock are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Drydock follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version remains `0.x`, the
command surface and Typed Specification contract are unstable and may change between releases.

## [Unreleased]

### Added

- Project foundation: single-sourced version, packaging metadata and classifiers, `py.typed` marker.
- Continuous integration (GitHub Actions) across Python 3.11–3.13 on Linux and Windows, with a wheel
  build and installed-CLI smoke test.
- Static type checking (mypy) and coverage reporting (pytest-cov).
- `pre-commit` configuration, including a Rigging-mirror integrity hook.
- `nox` sessions for lint, type, tests, build, and Rigging verification.
- Contributor guide and this changelog.

## [0.1.0] — Unreleased

### Added

- Installable `drydock` CLI with `config`, `init`, and `validate` commands.
- Subscription-authenticated LLM execution foundation.
- Source-tree launchers and packaged Rigging resources.
