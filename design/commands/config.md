# MEMORY: drydock config

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Hold user-scoped defaults — workspace, build root, provider, model, and execution bounds — and expose resolved paths and token calibration to scripts. |
| Route | config |
| Modules | `config.py`, `model_config.py`, `calibration.py` |
| Prompts | — |
| Tests | `tests/test_config.py`, `tests/test_model_config.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Intent

Hold user-scoped defaults — workspace, build root, provider, model, and execution bounds — and
expose resolved paths and token calibration to scripts. Configuration never lives in the
repository.

## Guardrails

- None.

## Details

### Current contract

The repository-root `model_config.jsonl` owns the shipped model seed. Both the source
distribution and wheel include it; the wheel embeds it at
`drydock/resources/model_config.jsonl`. Release builds must build a wheel from the source
distribution without depending on checkout-only files. Packaging changes do not mutate the
operator's live configuration. Missing build inputs fail the build before upload; repair the
source distribution and rebuild. Proof: `tests/test_packaging.py` checks coverage of all forced
wheel resources, and a local sdist-to-wheel build checks the embedded seed against the source.

`2026-10-28` · Added the seed to the explicit sdist include list after TestPyPI's build failed
with `Forced include not found: .../model_config.jsonl`. The wheel mapping was already correct;
the sdist omitted its input. No command syntax or specification contract changed.

### Syntax

```text
drydock config show
drydock config set <key> <value>
drydock config env [<Target>]
drydock config calibrate [--probe] [--apply] [--model <model>]
```

Settable keys: `drydock_build_directory`, `drydock_workspace`, `change_ticket_directory`,
`drydock_model`, `drydock_effort`, `llm_provider`, `codex_sandbox`, `quarterdeck_port`,
`diagnose`, `sandbox_mem_limit`, `capture_output_limit`, `repair_attempts`, `repair_stall_limit`,
`max_output_tokens`, `haiku_thinking_tokens`, `block_min_savings`, `postgres_dsn`.

### Rules

`2026-10-19` · **`postgres_dsn` names the PostgreSQL server a `postgres.md` Target builds
against.** `config set` accepts only `postgresql://` or `postgres://` values; empty clears it.
`config show` masks the password. Build and score export it as `DATABASE_URL`. Cost when broken:
a PostgreSQL Target is built and tested against SQLite.

`2026-06-10` · **Environment overrides the user file; nothing is stored in the repository.**
Each key maps to an environment variable (`drydock_model` → `DRYDOCK_MODEL`, …). Resolution order
is the environment, then the user `.env` (`$XDG_CONFIG_HOME/drydock/.env`, or `%APPDATA%` on
Windows), then the default. `config show` prints each value with its source. Cost when broken: a
script and an interactive shell resolve different workspaces.

`2026-06-10` · **Values are validated on `set`.** Unknown keys are refused with the valid list;
numeric keys are checked against their lower bound (`repair_attempts` ≥ 0 with `0` disabling
repair, `repair_stall_limit` ≥ 1, memory and capture limits ≥ 0 with `0` disabling); every other
key is a directory. Cost when broken: a megabyte figure silently resolved as a relative directory.

`2026-06-10` · **Provider and model are configuration, not policy.** `llm_provider` is one of
`claude`, `codex`, `gemini`; a recognized `--model` selects its own provider. `gemini` is metered
and reads `GEMINI_API_KEY` from the environment only. Cost when broken: a vendor becomes a
requirement, or a key lands in a file.

`2026-10-23` · **`model_config.jsonl` names the models each provider accepts.** Its seed is the
repository-root `model_config.jsonl`, packaged as `drydock/resources/model_config.jsonl`. A
provider row's `models` lists full names and native aliases by hand. `catalog` names the provider
CLI's model cache (codex: `~/.codex/models_cache.json`, hidden entries excluded), which replaces
`models` when readable. `aliases` maps a short name to a `*` pattern that resolves to the
highest-versioned model it matches (`sol` → `gpt-6.1-sol`). Claude (`haiku`, `sonnet`, `opus`,
`fable`) and Gemini (`auto`, `pro`, `flash`, `flash-lite`) aliases pass through because their CLIs
resolve them to the newest model. A row without these fields restricts nothing. `get_model`
returns the resolved name. Cost when broken: a short name reaches a CLI that rejects it.

`2026-10-23` · **An invalid model is refused with the allowed list.** `config set drydock_model`
refuses a model its provider row does not allow, naming every allowed model; the provider is the
one the name selects, else the configured one. `config show` prints `<model> -> <resolved>` for an
alias, appends `INVALID:` for a disallowed model, and ends with each provider's allowed models and
their source file. Cost when broken: a bad model is found only when a run fails.

`2026-10-13` · **Scripts learn paths from `config env`.** It prints `DRYDOCK_WORKSPACE`,
`DRYDOCK_TARGETS_ROOT`, `DRYDOCK_BUILD_DIRECTORY`, and, with a Target, its directory and build
directory (honoring a `METADATA.md` redirect) as shell-quoted assignments for `eval`. The Target
need not exist. Cost when broken: drivers restate layout and break when it moves.

`2026-10-13` · **Calibration proposes; only `--apply` writes.** `config calibrate` compares
`logs/model_calibration.jsonl` against the live `model_config.jsonl` and lists proposals;
`--probe` first measures the CLI's fixed overhead; `--apply` writes. See [build](build.md) for how
the model rows drive cost and escalation. Cost when broken: estimates drift silently, or change
without consent.

### Mechanism

1. `show` — resolve every key and print value and source.
2. `set` — validate and write the key to the user `.env`.
3. `env` — resolve and print shell assignments.
4. `calibrate` — optionally probe, read observations, propose, optionally apply.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Success, including calibrate with nothing to propose. |
| `1` | Invalid value or I/O failure (`ConfigurationError`). |
| `2` | Unknown key or other usage error. |

### Spec divergence

- The specification's key table lists `prompt_warn_tokens`, `prompt_error_tokens`, and
  `drydock_build_escalate_model`; none is a configuration key. Prompt sizing and escalation live in
  `model_config.jsonl`.
- The specification omits `llm_provider`, `config env`, and `config calibrate`.

## Decisions

-

## Questions

1. **Metered provider cost is not declared.** AGENTS.md requires a per-token provider to declare
   its cost in `drydock config`; `config show` does not mark `gemini` as metered. Add it?

## Actions

-

## Working Notes

-
