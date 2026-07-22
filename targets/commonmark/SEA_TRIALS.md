# Sea Trials: CommonMark Parser

### About Sea Trials

Sea Trials are project-level acceptance: what this project must achieve to be declared
delivered. `drydock analyze` derives them from the COMPASS and the sources before the work is
decomposed. `drydock build score` judges every criterion at the end and reports the verdicts in
`SCORECARD.md`.

Sea Trials are fixed up front and are not approved. Advancing to the next stage accepts the risk
these criteria describe. Read them now; they are the terms the finished project is measured
against.

Stories carry an `accepts:` field naming the criteria they implement, so most criteria are also
checked during the build. A criterion needs no implementing story to be judged at the end.

### Guardrails

A guardrail is a permanent *never* — a thing the project may not do regardless of how well it
scores. Guardrails are reported as `HELD` or `BREACHED`. A breach fails the completion gate
outright, independent of every score. A guardrail whose evidence is missing is `INCONCLUSIVE`
and also fails the gate: an unproven *never* is not held.

Guardrails are exempt from `accepts:` coverage. No story builds a prohibition.

### Questions

A `QUESTIONS:` block lists measurement facts only a human can supply — unknown baselines,
targets, workloads, or business measures. Drydock projects these into a QuarterDeck
questionnaire and preserves the answers across reruns. An unanswered question leaves its
criterion `INCONCLUSIVE` at scoring time.

## st-001: Filter conversion
Type:      technical
Required:  yes
Criterion: When the parser receives Markdown on standard input, the parser shall write the corresponding HTML on standard output.
Verification: proof
Pattern:   event
Evidence:  sources/INSTRUCTIONS.md
## st-002: No execution errors
Type:      technical
Required:  yes
Criterion: When the supplied conformance harness executes the parser, the parser shall complete each selected example without an execution error.
Verification: proof
Pattern:   event
Evidence:  sources/spec_tests.py
## st-003: CommonMark conformance score
Type:      outcome
Required:  yes
Criterion: The parser shall maximize the number of passing CommonMark 0.31.2 conformance examples.
Verification: measurement
QUESTIONS:
- q-st-003-target: What passing-example threshold defines release acceptance for the CommonMark 0.31.2 corpus?

## st-004: No side effects
Type:      guardrail
Required:  yes
Criterion: If the parser runs, then the parser shall not read configuration or produce side effects.
Verification: proof
Pattern:   unwanted
Evidence:  sources/INSTRUCTIONS.md
## st-005: NUL replacement
Type:      technical
Required:  yes
Criterion: When the parser receives a NUL character, the parser shall replace it with U+FFFD before rendering.
Verification: proof
Pattern:   event
Evidence:  sources/spec.txt
