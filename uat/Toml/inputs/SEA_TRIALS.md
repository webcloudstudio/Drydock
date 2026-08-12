# Sea Trials: Toml

## Policy

| Consequence | On FAIL | On INCONCLUSIVE |
|---|---|---|
| blocks  | fail   | attest |
| scores  | score  | score  |
| attests | report | report |

## st-001: The supplied conformance suite passes
Type: technical
Required: yes
Criterion: The complete supplied toml-test suite shall pass with no case failed, errored, or skipped.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous

## st-002: Invalid documents are rejected
Type: behavioral
Required: yes
Criterion: If a document violates TOML v1.0.0, then the parser shall reject it with a non-zero exit status.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: unwanted

## st-003: Valid documents decode to the declared value model
Type: behavioral
Required: yes
Criterion: When given a valid TOML document, the parser shall emit the toml-test JSON encoding of its value model.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: event

## st-004: The parser terminates on every supplied case
Type: technical
Required: yes
Criterion: The parser shall terminate for every case the installed suite supplies.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous

## st-005: The implementation follows the stack decision
Type: technical
Required: no
Criterion: The parser shall be implemented in the language named by TECHNOLOGY_STACK.md.
Testability: deterministic
Consequence: scores
Verification: proof
Pattern: ubiquitous

## st-006: No case count is asserted
Type: guardrail
Required: yes
Criterion: No acceptance criterion shall assert a fixed number of conformance cases, because the suite's size is a property of the installed version.
Testability: judgeable
Consequence: blocks
Verification: evidence
Pattern: ubiquitous
