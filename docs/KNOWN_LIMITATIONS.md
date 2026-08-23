# Known Limitations

Drydock is `0.x`, beta software. This page states what is not yet true, so a reader does not have
to discover it by hitting it. It is updated as limitations are resolved or found.

## Provider and model

- **Two providers wired in today: Claude and Codex subscription CLIs.**
  `SUPPORTED_PROVIDERS = ("claude", "codex")` in `src/drydock/llm.py` is a single tuple, and each
  provider is one branch in that same file (subprocess invocation, sandbox flags, model-name
  matching). No API-key-billed provider is supported, and none is planned — that's a deliberate
  constraint (`AGENTS.md`: "Never call an API-key-backed LLM provider"), not a gap. Adding another
  **subscription-authenticated CLI** (a Gemini CLI, a local-model CLI wrapper, etc.) is a contained
  change confined to `llm.py`'s provider branches and `SUPPORTED_PROVIDERS` — the adapter pattern
  was built for exactly this. Open to a PR from anyone who needs a specific one.
- **No cost tracking.** `result.stats.cost_usd` is not populated in `logs/llm.jsonl`. Economics
  claims rest on subscription flat-rate pricing and token/call counts, not on a computed dollar
  figure. Do not infer a $/token savings number from published receipts — it isn't measured yet.

## Encoding and platform

- **UTF-8 only.** Evidence artifacts, prompts, and subprocess I/O are read and written as UTF-8
  throughout `src/drydock/llm.py`. Source material or a terminal that isn't UTF-8-clean is not a
  supported path.
- **Linux/WSL is the tested platform.** `win32` is special-cased for the absence of POSIX process
  groups (`src/drydock/llm.py:1067`), not fully exercised. Native Windows (outside WSL) has not
  been part of any published run.

## Build scale and resources

- **Bounded repair and acceptance resources.** `repair_attempts` (default 6), `repair_stall_limit`
  (default 2), `sandbox_mem_limit` (default 4096 MB), and `capture_output_limit` (default 8 MB) are
  configurable but finite. An unusually large or loud story can exhaust them; the fix is to raise
  the bound for that run, not an automatic escalation.
- **Acceptance cost scales with corpus size — scope it deliberately.** Running the full acceptance
  suite is a token cost, not a correctness ceiling: nothing about the build loop breaks between 350
  cases and 3,500. A candidate corpus over a gigabyte (`sqllogictest`'s `random/` + `index/`) was
  excluded from the UAT target list on budget grounds, not because Drydock failed on it — it was
  never run. Scope a Blueprint's acceptance to what you're willing to spend tokens verifying.

## Process

- **One green receipt is evidence of one run, not a benchmark.** LLM output is non-deterministic
  run to run. A `PASSED` verdict shows what that run produced and how it was checked; it is not a
  general success rate, a security certification, or a guarantee of reproducibility on a re-run.

## Stack coverage

`Rigging/stack/` is a library of prescriptive, opinionated, standalone technology guides —
config-management patterns, code style, and copy-paste-ready examples for one language, framework,
or service each. `TECHNOLOGY_STACK.md` in a Target declares which files apply (`language: python`,
`framework: flask`, `database: postgres`, …), and Drydock injects the matching files into build
prompts as best-practice guardrails.

- **The catalog covers a fixed set today**: Python, Go, TypeScript, Flask, Django, Postgres,
  SQLite, Bootstrap 5, AWS (Lambda, S3, SQS, DynamoDB, API Gateway), Terraform, GitHub Actions,
  Alexa Skills Kit. A stack outside this list still builds — it proceeds without Drydock-authored
  guardrails for that stack, using only the model's own defaults.
- **Adding your own is meant to be easy, and doesn't require touching Drydock's code.** Write a new
  `Rigging/stack/<name>.md` in the same shape as the existing files (prescriptive rules, concrete
  code examples, no prose padding), add one row to `Rigging/stack/README.md`'s catalog table
  mapping it to a `TECHNOLOGY_STACK.md` key, then declare that key. A fast way to draft one: ask
  your LLM to write best-practice guidance for the stack you want, in the same format as
  `Rigging/stack/python_compact.md`, and drop the result in.

## Specification contract

- **The command surface and Typed Specification contract are unstable in `0.x`** and may change
  between releases without a backward-compatibility guarantee (`AGENTS.md`). A Blueprint authored
  against one Drydock version is not guaranteed to plan or build unchanged against a later one.
