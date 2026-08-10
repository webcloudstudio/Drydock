# Sea Trials: CommonMark

## Policy

| Consequence | On FAIL | On INCONCLUSIVE |
|---|---|---|
| blocks  | fail   | attest |
| scores  | score  | score  |
| attests | report | report |

## st-001: The supplied conformance suite passes
Type: technical
Required: yes
Criterion: The complete supplied conformance suite shall pass with no failed example.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous

## st-002: The filter contract holds
Type: behavioral
Required: yes
Criterion: When invoked with no arguments, the parser shall read Markdown from stdin and write HTML to stdout.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: event

## st-003: The parser terminates on every supplied input
Type: technical
Required: yes
Criterion: The parser shall terminate for every example in the supplied suite.
Testability: deterministic
Consequence: blocks
Verification: proof
Pattern: ubiquitous

## st-004: Conversion is deterministic
Type: technical
Required: no
Criterion: The parser shall produce identical output for identical input on repeated runs.
Testability: deterministic
Consequence: scores
Verification: proof
Pattern: ubiquitous

## st-005: The implementation is readable
Type: qualitative
Required: no
Criterion: The parser's structure follows the specification's own block and inline phases closely enough to be reviewed against it.
Testability: judgeable
Consequence: scores
Verification: llm

## st-006: The supplied suite is not modified
Type: guardrail
Required: yes
Criterion: The build shall never edit, filter, or reinterpret the supplied conformance suite or its harness.
Testability: judgeable
Consequence: blocks
Verification: evidence
Pattern: ubiquitous
