# DONE: quarterdeck

## Acceptance — deterministic Python tests, self-contained, out of ordering — 2026-07-03
`2026-07-03` · `spec:applied` · `impl:implemented`

**What an `ac` is.** A small, self-contained test that the just-built story works — a few port
pings, a guard grep, or a scripted checkout of a page. Deterministic, independently runnable.

- **Deterministic, never agentic.** An `ac`'s `check:` is a Python test invocation (e.g.
  `pytest tests/test_marlib.py`) run as a **post hook** after the story builds. No model in the
  verify loop — verification costs zero context and cannot self-report. This is the context-tight
  design: the LLM spends tokens building; the tests just run.
- **Two kinds.** *Smoke* — shallow "does it run" check (`service starts, answers /health`).
  *Assertion / guard* — a precise invariant (`no DynamoDB Scan`, `idempotent write uses SK not PK`).
  Distinguished by `kind:`.
- **Self-only-depends (hard guard).** An `ac` may depend on its own parent story only. The planner
  and compass must never emit or accept an `ac`→other-story edge. `ac-marlib-1: depends infra` is
  the defect that started this; drop it and Marina2 is cleanly ordered.
- **Programmatic vs User Acceptance.** Programmatic Acceptance (the Python `check:`) runs
  automatically and gates the build. User Acceptance is a Commander eyeball signal and does not
  block downstream build.

**Guard against out-of-order generation.** Whatever emits `ac` blocks (plan create) must enforce
self-only-depends at generation time, so an invalid edge can never enter the manifest.

## Story and its tests built in one step; blueprint owns "done" — 2026-07-03
`2026-07-03` · `spec:applied` · `impl:implemented`

**One act.** The story and its deterministic Python tests are written in the **same LLM build
step** — the model wears the TDD-master hat and writes the tests as it builds ("if you were a TDD
master, what tests would you write"). Not a separate phase; simultaneous, no extra context. All
best practices applied at once inside one generation.

**Ownership: the blueprint owns "done"; the build authors the test that proves it.** Each `ac` in
the blueprint states the intent in human terms (the contract for what must be true). The build step
writes the concrete Python test that satisfies that contract and may add finer tests for coverage,
but it **cannot remove or weaken a declared `ac`**. "Done" is defined before the build, human-owned
and stable, so the model cannot move the goalposts by inventing softer criteria. Blueprint = the
assertion; build = its executable realization plus extra.
