# Sea Trials: Toml

## Policy

| Consequence | On FAIL | On INCONCLUSIVE |
|---|---|---|
| blocks  | fail   | attest |
| scores  | score  | score  |
| attests | report | report |

## st-001: The supplied scoring script passes
Type: technical
Required: yes
Criterion: The completed parser shall make sh sources/full_test.sh exit zero; that script's exit status is the sole acceptance verdict.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous
