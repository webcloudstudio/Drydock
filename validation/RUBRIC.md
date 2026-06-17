# Validation Rubric

The validation harness uses a deterministic weighted score.

- `pass` = `1.0`
- `partial` = `0.5`
- `fail` = `0.0`

Each benchmark contract defines weighted assertions. The shared scorer computes:

```text
score = round(sum(weight * result_value) / sum(weight) * 100)
```

Bands:

- `SEAWORTHY` — 90+
- `SEA_TRIALS` — 75-89
- `TAKING_WATER` — 60-74
- `DRY_DOCK` — below 60

Canonical gap classes:

- `missing-artifact`
- `wrong-output`
- `behavior-mismatch`
- `missing-test`
- `missing-evidence`
- `runtime-failure`
- `contract-drift`
- `shortcut-or-fabrication`
