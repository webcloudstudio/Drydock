# Drydock Validation Harness

`validation/` is a repo-local benchmark harness for proving Drydock against a
small set of deterministic applications.

## Layout

- `specs/` — benchmark contracts in Markdown
- `bin/test_*.sh` — case executors that produce standardized evidence
- `bin/score_case.py` — shared scorer for one case
- `bin/score_all.py` — run-level aggregator
- `fixtures/` — golden sample implementations used to prove the harness
- `reports/` — generated evidence and score reports
- `schemas/` — JSON schema references for contracts and result payloads

## Run

```bash
bash validation/bin/run_validation.sh
```

Run one case:

```bash
bash validation/bin/run_validation.sh hello-cli
```

Generated reports land under `validation/reports/<run-id>/`.
