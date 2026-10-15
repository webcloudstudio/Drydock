# DESIGN: drydock config

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | config |
| Modules | `config.py`, `model_config.py`, `calibration.py` |
| Prompts | — |
| Tests | `tests/test_config.py`, `tests/test_model_config.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Hold user-scoped defaults — workspace, build root, provider, model, and execution bounds — and
expose resolved paths and token calibration to scripts. Configuration never lives in the
repository.

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
`max_output_tokens`, `haiku_thinking_tokens`, `block_min_savings`.

### Rules

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

## Open Questions

1. **Metered provider cost is not declared.** AGENTS.md requires a per-token provider to declare
   its cost in `drydock config`; `config show` does not mark `gemini` as metered. Add it?

## Working Notes

-
