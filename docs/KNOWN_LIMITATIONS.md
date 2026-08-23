# Known Limitations

Drydock is `0.x`, beta software. This page states what is not yet true, so a reader does not have
to discover it by hitting it. It is updated as limitations are resolved or found.

## Provider and model

- **Two providers only: Claude and Codex subscription CLIs.** `SUPPORTED_PROVIDERS = ("claude",
  "codex")` (`src/drydock/llm.py`). No API-key-billed provider, no local/open-weight model runner.
  A local-model adapter is a contained, unclaimed piece of work.
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
- **Very large, unscoped acceptance corpora do not terminate reliably.** Evaluated directly:
  `sqllogictest`'s `random/` + `index/` corpus (over 1 GB) was rejected as a UAT target for this
  reason (`ideas/UAT.md`, "Do not. Loop never terminates."). A Blueprint must scope acceptance to a
  bounded, story-sized slice; Drydock does not currently decompose an unbounded corpus on its own.

## Process

- **The human review gate is mandatory, not optional.** Drydock is not a fire-and-forget
  autonomous builder — unresolved Commander decisions block build by design. This is a deliberate
  choice (`ideas/SHOW_HN_POST.md`), not a missing feature, but it means unattended end-to-end runs
  are not the intended mode.
- **One green receipt is evidence of one run, not a benchmark.** LLM output is non-deterministic
  run to run. A `PASSED` verdict shows what that run produced and how it was checked; it is not a
  general success rate, a security certification, or a guarantee of reproducibility on a re-run.

## Stack coverage

- **Curated stack guidance (`Rigging/stack/`) covers a fixed set**: Python, Flask, FastAPI, Django,
  TypeScript, Bootstrap 5, Postgres, SQLite, AWS (Lambda, S3, SQS, DynamoDB, API Gateway),
  Terraform, GitHub Actions, Alexa Skills Kit, Go. A stack outside this set still builds — it just
  proceeds without Drydock-authored best-practice and guardrail injection for that stack.

## Specification contract

- **The command surface and Typed Specification contract are unstable in `0.x`** and may change
  between releases without a backward-compatibility guarantee (`AGENTS.md`). A Blueprint authored
  against one Drydock version is not guaranteed to plan or build unchanged against a later one.
