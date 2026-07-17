# Changelog

All notable changes to Drydock are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Drydock follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version remains `0.x`, the
command surface and Typed Specification contract are unstable and may change between releases.

## [Unreleased]

### Changed

- 2026-07-17: retired the Ship's Log feature, removed the `drydock shipslog` command and related
  repository tooling, and made `CHANGELOG.md` the only maintained high-level project history.
- `drydock import --format compass` now normalizes the intent document into the canonical
  COMPASS.md format with an LLM pass at import time (prompt contract
  `prompts/import_compass.md`), preserving the Commander's vocabulary. It is the only import form
  that runs an LLM and honors `--llm-provider` and `--model`. The written COMPASS.md is final and
  Commander-owned; an existing COMPASS.md is preserved unless `--force` is given, and
  `drydock analyze` no longer performs deferred normalization for compass imports.

## [0.1.1] — 2026-07-08

### Added

- Drydock Blueprint Methodology vocabulary across the product specification, documentation, and CLI.
- Sole authoritative product specification at `docs/Drydock_Specification.md`.
- Authoritative implementation acceptance/readiness checklist at `docs/SOUNDINGS.md`.
- Project foundation: single-sourced version, packaging metadata and classifiers, `py.typed` marker.
- Continuous integration (GitHub Actions) across Python 3.11–3.13 on Linux and Windows, with a wheel
  build and installed-CLI smoke test.
- Static type checking (mypy) and coverage reporting (pytest-cov).
- `pre-commit` configuration (whitespace, YAML/TOML, and ruff hooks).
- `nox` sessions for lint, type, tests, and build.
- Contributor guide and this changelog.
- `drydock rigging compact` — the first LLM-assisted command and general compaction entry point —
  with a versioned prompt contract (`prompts/<command>_<subcommand>.md` + required YAML frontmatter).
- Canonical product specification packaged in the wheel at
  `drydock/resources/docs/Drydock_Specification.md`.

### Changed

- Renamed the `INTENT.md` Typed Specification file and `INTENT` FileType to `COMPASS.md` /
  `COMPASS`, the `## Intent` body section to `## Compass`, and the `BUILD_PLAN_INTENT.md` planning
  inventory to `BUILD_PLAN_COMPASS.md`. "Compass" is the nautical term for the product's
  direction-setting document.
- Renamed the `drydock iterate` command to `drydock refit`, aligning the verb with the canonical
  SAIL Loop "Refit" concept. The `<BOTH|BLUEPRINT|TGT>` modes are unchanged.
- Replaced the public `drydock log` commands and shared target-project capture rules with the
  Drydock-only agent process in `AGENTS.md` and repository-local `bin/ships_log.py`.
- Renamed the public Blueprint root contract to `BLUEPRINT_DIRECTORY` and `blueprint_directory`;
  legacy specification-directory names remain accepted as deprecated migration aliases.
- Renamed the public CLI project argument from `<Spec>` to `<Blueprint>` and the iterate-side mode
  from `SPEC` to `BLUEPRINT`; `SPEC` remains accepted as a deprecated migration alias.

### Known Limitations

- This is an alpha release. Command contracts and Typed Specification contracts may change during
  the `0.x` series.
- LLM-assisted commands require an authenticated local `claude` or `codex` CLI.

## [0.1.0] — Unreleased

### Added

- Installable `drydock` CLI with `config`, `init`, and `validate` commands.
- Subscription-authenticated LLM execution foundation.
- Source-tree launchers and packaged Rigging resources.
