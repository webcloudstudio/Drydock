# Sea Trials: CommonMark

## Policy

| Consequence | On FAIL | On INCONCLUSIVE |
|---|---|---|
| blocks  | fail   | attest |
| scores  | score  | score  |
| attests | report | report |

## st-001: The complete conformance suite passes
Type: technical
Required: yes
Criterion: The completed parser shall pass every test run by sh full_test.sh.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous
