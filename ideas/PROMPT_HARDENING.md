# Prompt Hardening — Watertight Prompts

**Status:** Proposal. Not implemented. No specification change has been approved.
**Date:** 2026-07-30
**Scope:** `src/drydock/prompts.py`, a new `src/drydock/warrant.py`, `prompts/`, `src/drydock/llm.py`
(logging only), every LLM-assisted capability module.

---

## 1. Problem Statement

A Drydock command that calls an LLM depends on the model emitting a specific structure: named
artifact blocks, a JSON object with a fixed key set, a verdict drawn from a closed vocabulary. The
model is non-deterministic. Today the expectation is expressed twice and enforced once:

- **Expressed** as prose in `prompts/<name>.md` ("Return exactly one JSON object and no prose").
- **Enforced** in the capability module by whatever the caller happened to pass to
  `artifact_blocks.parse_artifact_blocks(...)` or to `json.loads(...)`.

Three defects follow:

1. **Drift.** The prose contract and the parser's allow-list are independent edits. Nothing detects
   divergence. A prompt can promise a `RISKS` block the parser rejects, or a parser can accept a
   block the prompt never asked for.
2. **No second chance.** A structural violation is usually the model's cheapest, most recoverable
   error. Most call sites raise immediately, discarding a run that one informed retry would fix.
   `build_run` is the exception and holds the correct precedent.
3. **Opaque failure.** When output is rejected, the operator sees a parse error, not the contract
   that was violated, the attempt that violated it, or the artifact holding the offending text.

A prompt cannot be made deterministic. The **pipeline** can be made deterministic: for a given
input it either produces contract-conformant output or fails with a named, logged, actionable
defect. Nothing in between, and never a malformed artifact on disk.

---

## 2. Naming

**Recommended term: a *Watertight Prompt*.** A prompt is Watertight when it carries all three of:

| Element | Name | Definition |
|---|---|---|
| The machine-readable output contract | **Warrant** | Declares exactly what conformant output is. One file, consumed by both the prompt renderer and the checker. |
| The deterministic post-checker | **Hull Check** | Parses and validates model output against the Warrant. Produces a list of typed Violations. Never calls an LLM. |
| The bounded feedback loop | **Second Pass** | Exactly one re-prompt, carrying the Hull Check's literal violations. A Second Pass that also fails is a terminal, reported error. |

A prompt without a Warrant is a **Plain Prompt** and keeps today's behavior. The two coexist
indefinitely; migration is per-prompt.

Alternates considered and rejected, in case the author prefers one: *Sealed Prompt* (implies
immutability, which is wrong — prompts are versioned and edited), *Certified Prompt* (implies an
external authority), *Bonded Prompt* (financial connotation). "Watertight" carries the exact
meaning intended: the failure it prevents is leakage of malformed model output into artifacts, and
it is verified by test rather than asserted.

Vocabulary note: the Sea Trials domain already uses `BREACHED` for a violated guardrail. Warrant
failures therefore use **VIOLATION**, never "breach", to keep the two vocabularies disjoint.

---

## 3. Design Principles

1. **The Warrant is the single source of truth.** The prompt's human-readable output-contract
   section is *rendered from* the Warrant at assembly time. The checker validates *against* the
   same Warrant. Drift becomes structurally impossible rather than merely discouraged.
2. **The checker is the guarantee. The prompt wording is yield optimization.** Write the Warrant
   and the checker first; the prompt text is generated from them.
3. **Validate before writing.** No capability writes any file until the Hull Check passes on the
   full output. A partially conformant response produces zero artifacts, not some artifacts.
4. **Exactly one retry.** Two attempts, then stop. Beyond attempt two, per-attempt success
   probability does not improve materially, and the cost is real. The bound is configurable per
   Warrant but defaults to 2 and is capped at 3.
5. **Feed back the literal error.** The Second Pass receives the checker's exact violation text and
   the offending excerpt — never a paraphrase, never a summary.
6. **Fail closed and loud.** A failed Second Pass raises a typed error, prints a violation block
   naming both execution IDs and both output artifacts, and exits 1.
7. **No new dependencies.** No YAML library, no `jsonschema`. Stdlib `json` and `re` only, matching
   the existing constraint in `AGENTS.md`.

---

## 4. File Layout

```text
prompts/
  survey_import.md                  # prompt body + frontmatter (existing)
  warrants/
    survey_import.json              # NEW: the Warrant for that prompt
src/drydock/
  warrant.py                        # NEW: load, render, check, run-with-second-pass
  prompts.py                        # extended: Prompt.warrant property
  artifact_blocks.py                # unchanged; the block checker delegates to it
```

Warrants live in `prompts/warrants/<prompt-name>.json`. The name matches the prompt's `name:`
frontmatter field, not the filename, so a renamed file cannot orphan its Warrant.

`prompts/` is already packaged by Hatchling `force-include` to `drydock/resources/prompts/`;
`warrants/` rides along as a subdirectory with no packaging change. Resolution goes through
`paths.get_prompts_root()`. **Both source-tree and installed paths must be tested.**

### Why JSON sidecar rather than frontmatter

`prompts.parse_frontmatter` is deliberately a scalar `key: value` parser with no nesting and no
YAML dependency. A Warrant is inherently nested. Three options were considered:

| Option | Verdict |
|---|---|
| Extend the frontmatter parser to nested YAML | Rejected. Either a YAML dependency (needs approval, contradicts the existing design note) or a hand-rolled nested parser (new bug surface in a load-bearing path). |
| Fenced JSON block inside the prompt body | Rejected. Puts machine data in the region the model reads; the model will attempt to satisfy the schema literal as well as the rendered instructions. |
| **JSON sidecar, referenced by a scalar frontmatter key** | **Selected.** Zero parser change, stdlib `json`, independently lintable, diffable, and testable. |

---

## 5. Frontmatter Format

One new **optional** scalar field. Absent ⇒ Plain Prompt, current behavior, no change.

```yaml
---
name: build_score
description: Evidence-bound technical quality and project acceptance assessment.
version: 20260730 V5
intent: Judge the completed project only from supplied deterministic facts and evidence.
command: drydock build score
model: opus
effort: high
inputs: SEA_TRIALS.md, MANIFEST.md, TYPED_SPEC, EVIDENCE
output: JSON assessment consumed by Drydock
warrant: build_score
---
```

| Field | Required | Meaning |
|---|---|---|
| `warrant` | No | Basename of the Warrant under `prompts/warrants/`. Conventionally equal to `name`. Presence makes the prompt Watertight. |

Rules:

- `warrant:` naming a missing file is a **prompt defect**, raised at `load_prompt` time as
  `DrydockError`, reported against the prompt file — not a runtime failure mid-command.
- The existing free-text `output:` field is retained for human readers and becomes advisory. When a
  Warrant is present, the Warrant is normative. A future cleanup may drop `output:` from Watertight
  prompts; do not do it in the same change.
- Changing a Warrant **requires** bumping the prompt's `version`. Enforced by a repository guard
  test (§12), because a silent contract change with a stable version makes the evidence log
  uninterpretable.

---

## 6. Warrant Format

A Warrant is a single JSON object. Unknown top-level keys are a hard error — a typo must not
silently disable a constraint.

### 6.1 Common envelope

```json
{
  "warrant_version": 1,
  "prompt": "build_score",
  "format": "json",
  "max_attempts": 2,
  "on_violation": "second_pass",
  "notes": "Free text for maintainers. Never rendered into the prompt."
}
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `warrant_version` | int | — | Required. Schema version of the Warrant format itself. Currently `1`. |
| `prompt` | string | — | Required. Must equal the prompt's `name:`. Mismatch is a load-time defect. |
| `format` | `"blocks" \| "json" \| "lines"` | — | Required. Selects the checker family. |
| `max_attempts` | int | `2` | Total attempts including the first. Range 1–3. `1` disables the Second Pass. |
| `on_violation` | `"second_pass" \| "fail"` | `"second_pass"` | `"fail"` raises on the first violation with no retry. |
| `notes` | string | `""` | Maintainer commentary. Never sent to the model. |

### 6.2 `format: "blocks"`

Governs output parsed by `artifact_blocks.parse_artifact_blocks`.

```json
{
  "warrant_version": 1,
  "prompt": "survey_import",
  "format": "blocks",
  "max_attempts": 2,
  "forbid_text_outside_blocks": true,
  "forbid_duplicate_names": true,
  "min_total_blocks": 1,
  "max_total_blocks": 60,
  "blocks": [
    {
      "name": "SUMMARY",
      "required": true,
      "cardinality": "one",
      "min_chars": 1,
      "max_words": 80,
      "description": "One paragraph stating what was imported."
    },
    {
      "name": "FINDINGS",
      "required": true,
      "cardinality": "one",
      "empty_sentinel": "NONE",
      "line_pattern": "^(BLOCKER|MAJOR|MINOR) \\| [^|]+ \\| .+$",
      "max_lines": 200,
      "description": "One line per finding: SEVERITY | FILE:LINE | CLAIM."
    },
    {
      "name": "VERDICT",
      "required": true,
      "cardinality": "one",
      "enum": ["ACCEPT", "REJECT", "INCONCLUSIVE"],
      "description": "The single overall verdict."
    },
    {
      "name_pattern": "^spec/[A-Za-z0-9_.\\-]+\\.md$",
      "required": true,
      "cardinality": "many",
      "min_count": 1,
      "max_count": 40,
      "min_chars": 20,
      "description": "One block per generated specification file, named by its repository path."
    }
  ]
}
```

**Block descriptor keys**

| Key | Type | Applies to | Meaning |
|---|---|---|---|
| `name` | string | fixed blocks | Exact block name. Mutually exclusive with `name_pattern`. |
| `name_pattern` | regex | variable blocks | Names matching this regex are accepted. Mutually exclusive with `name`. |
| `required` | bool | both | Absence is a violation. Default `true`. |
| `cardinality` | `"one" \| "many"` | both | `"one"` forbids repeats; `"many"` permits them. Default `"one"`. |
| `min_count` / `max_count` | int | `cardinality: many` | Inclusive bounds on matching-block count. |
| `min_chars` / `max_chars` | int | both | Body length bounds after stripping. |
| `max_words` | int | both | Word-count bound after stripping. |
| `max_lines` | int | both | Non-empty line-count bound. |
| `enum` | string[] | both | Stripped body must equal one member exactly. |
| `line_pattern` | regex | both | Every non-empty line must match. |
| `body_pattern` | regex | both | The whole body must match (`re.DOTALL`). |
| `empty_sentinel` | string | both | The literal that legally means "nothing to report". Exempt from `line_pattern`, `min_chars`, `enum`. |
| `description` | string | both | Rendered into the prompt's contract section. **Required** — it is the human contract. |

Any block name present in the output but matching no descriptor is `UNKNOWN_BLOCK`. This subsumes
today's `allowed_names` / `allowed_prefixes` / `allowed_suffixes` / `allowed_patterns` arguments;
`parse_artifact_blocks` keeps that signature and the Warrant checker derives the arguments from the
descriptors, so no existing caller breaks.

### 6.3 `format: "json"`

Governs output that must be exactly one JSON object (`build_score`, `score_release`, `analyze`
discoveries). The schema subset is deliberately tiny — enough for real Drydock payloads, small
enough to implement in ~120 lines with no dependency.

```json
{
  "warrant_version": 1,
  "prompt": "build_score",
  "format": "json",
  "max_attempts": 2,
  "allow_fenced": true,
  "allow_leading_prose": false,
  "schema": {
    "type": "object",
    "additional_keys": "forbid",
    "properties": {
      "dimensions": {
        "type": "object",
        "required": true,
        "additional_keys": "forbid",
        "properties": {
          "specification_completeness": { "type": "integer", "minimum": 0, "maximum": 100 },
          "implementation_coverage":    { "type": "integer", "minimum": 0, "maximum": 100 },
          "test_coverage":              { "type": "integer", "minimum": 0, "maximum": 100 },
          "documentation_coverage":     { "type": "integer", "minimum": 0, "maximum": 100 },
          "blueprint_drift":            { "type": "integer", "minimum": 0, "maximum": 100 },
          "build_quality":              { "type": "integer", "minimum": 0, "maximum": 100 },
          "acceptance_criteria_coverage":{ "type": "integer", "minimum": 0, "maximum": 100 }
        }
      },
      "sea_trials": {
        "type": "array",
        "required": true,
        "min_items": 0,
        "max_items": 500,
        "items": {
          "type": "object",
          "additional_keys": "forbid",
          "properties": {
            "id":       { "type": "string", "pattern": "^[A-Z]+-[0-9]+$" },
            "verdict":  { "type": "string", "enum": ["PASS", "FAIL", "INCONCLUSIVE"] },
            "rationale":{ "type": "string", "max_length": 400 }
          }
        }
      },
      "recommendations": {
        "type": "array",
        "required": true,
        "max_items": 20,
        "items": { "type": "string", "max_length": 300 }
      }
    }
  },
  "cross_checks": [
    {
      "check": "array_covers_input_ids",
      "array": "sea_trials",
      "id_key": "id",
      "input_parameter": "sea_trial_ids",
      "mode": "exactly_once"
    }
  ]
}
```

**Supported schema keywords** (exhaustive; anything else is a Warrant defect):

`type` (`object|array|string|integer|number|boolean`), `required`, `properties`,
`additional_keys` (`forbid|allow`), `items`, `min_items`, `max_items`, `enum`, `pattern`,
`minimum`, `maximum`, `min_length`, `max_length`, `nullable`.

**Envelope keys**

| Key | Default | Meaning |
|---|---|---|
| `allow_fenced` | `true` | Strip a single wrapping ```` ```json ```` fence before parsing. Pragmatic: models emit fences at high rate and the fence is losslessly removable. |
| `allow_leading_prose` | `false` | When `false`, any non-whitespace outside the JSON value is `TEXT_OUTSIDE_JSON`. |

**`cross_checks`** are semantic checks the schema cannot express, referencing values the caller
supplied. Initial set — extend only when a real prompt needs it:

| Check | Parameters | Asserts |
|---|---|---|
| `array_covers_input_ids` | `array`, `id_key`, `input_parameter`, `mode` (`exactly_once`\|`subset`) | The emitted array covers the caller-supplied ID set with the given multiplicity. This is what enforces "Judge every supplied Sea Trial exactly once" mechanically instead of by request. |
| `sum_within` | `path`, `minimum`, `maximum` | A numeric aggregate falls in range. |

Cross-check inputs arrive via `run_warranted(..., warrant_inputs={"sea_trial_ids": [...]})`.

### 6.4 `format: "lines"`

For simple record output (one item per line). Same envelope, plus:

```json
{
  "format": "lines",
  "line_pattern": "^[A-Z]{2,10} \\| .+$",
  "min_lines": 1,
  "max_lines": 500,
  "empty_sentinel": "NONE",
  "forbid_blank_lines": true
}
```

---

## 7. Rendered Contract Section

`warrant.render_contract_section(warrant)` produces the human-readable contract appended to the
prompt body at assembly time — **last**, after all injected inputs, because recency dominates
format adherence. Prompt authors delete any hand-written output-contract section when adopting a
Warrant; a guard test (§12) fails a Watertight prompt whose body still contains one.

For the §6.2 example the renderer emits exactly:

```markdown
## Output contract

Emit only the blocks specified below, in the order listed, and nothing else. Every block opens
with a line `=== NAME ===` and closes with a line `=== END NAME ===`. No text may appear before
the first block, between blocks, or after the last block: no preamble, no commentary, no code
fences, no tool calls, no closing remarks.

1. `SUMMARY` — exactly one block. One paragraph stating what was imported. At most 80 words.
2. `FINDINGS` — exactly one block. One line per finding: SEVERITY | FILE:LINE | CLAIM.
   Every line matches `^(BLOCKER|MAJOR|MINOR) \| [^|]+ \| .+$`. At most 200 lines.
   Emit the single line `NONE` when there is nothing to report. Never omit the block.
3. `VERDICT` — exactly one block. The single overall verdict. The body is exactly one of:
   `ACCEPT`, `REJECT`, `INCONCLUSIVE`.
4. `spec/<name>.md` — one block per generated specification file, named by its repository path.
   Each name matches `^spec/[A-Za-z0-9_.\-]+\.md$`. At least 1, at most 40. At least 20 characters each.

Example of the required shape. The values are placeholders, not content to reproduce:

=== SUMMARY ===
<one paragraph>
=== END SUMMARY ===
=== FINDINGS ===
NONE
=== END FINDINGS ===
=== VERDICT ===
ACCEPT
=== END VERDICT ===
```

Renderer rules — these are the wording best practices, mechanized:

1. Present-tense imperative. No `please`, `try to`, `if possible`, `should`, `may`.
2. Every block appears in the list. **No conditional sections ever** — optionality is expressed by
   `empty_sentinel`, never by omission, because "include it if relevant" is the single largest
   source of structural non-determinism.
3. Every constraint in the descriptor is stated in the rendered text. Nothing is checked that the
   model was not told, and nothing is stated that is not checked.
4. Closed vocabularies are rendered as an explicit literal list.
5. Cardinality is stated in words ("exactly one block", "at least 1, at most 40").
6. The skeleton example is complete, valid, and uses unmistakable placeholders.
7. The prohibition list is fixed and short, covering only observed failure modes (preamble,
   commentary, fences, tool calls, trailing remarks). It is not extended speculatively; each added
   prohibition dilutes the rest.

For `format: "json"` the renderer emits the same structure, ending with a pretty-printed skeleton
of the schema with typed placeholders (`0`, `"<string>"`, `["<string>"]`) and the line: *"Return
exactly one JSON object. No prose before or after it."*

---

## 8. Checker API

New module `src/drydock/warrant.py`. Pure and synchronous; no filesystem writes, no process
execution, in the checking path.

```python
@dataclass(frozen=True)
class Violation:
    code: str                 # from the closed taxonomy below
    locus: str                # block name, JSON path, or "" for whole-output faults
    detail: str               # one sentence, imperative, states what conformant output requires
    excerpt: str = ""         # <= 200 chars of the offending text, for the operator and the retry

@dataclass(frozen=True)
class HullCheck:
    warrant: Warrant
    violations: tuple[Violation, ...]
    payload: Any | None       # dict[str, str] of blocks, or the parsed JSON, or tuple of lines
    @property
    def ok(self) -> bool: ...
    def feedback(self, *, cap: int = 4000) -> str: ...   # rendered for the Second Pass
    def report(self) -> list[str]:                       # rendered for the console/log

def load_warrant(name: str) -> Warrant: ...
def render_contract_section(warrant: Warrant) -> str: ...
def check_output(text: str, warrant: Warrant, *, inputs: Mapping[str, Any] | None = None) -> HullCheck: ...
```

### Violation taxonomy

Closed set. Each code is classified `repairable` or `terminal`, mirroring `build_run._is_repairable`.

| Code | Repairable | Meaning |
|---|---|---|
| `EMPTY_OUTPUT` | no | Model returned nothing. Provider-side; a retry is not informed by feedback. |
| `TRUNCATED_OUTPUT` | no | Unterminated final block or JSON. Indicates a length limit; the same prompt truncates again. |
| `REFUSAL` | no | Output matches a refusal shape. Retrying is wasted spend. |
| `TEXT_OUTSIDE_BLOCKS` | yes | Prose outside the block structure. |
| `TEXT_OUTSIDE_JSON` | yes | Prose around the JSON value. |
| `MISSING_BLOCK` | yes | A required block was not emitted. |
| `UNKNOWN_BLOCK` | yes | A block matched no descriptor. |
| `DUPLICATE_BLOCK` | yes | `cardinality: one` emitted more than once. |
| `CARDINALITY_VIOLATION` | yes | `min_count`/`max_count` breached. |
| `EMPTY_BLOCK` | yes | Body empty and no `empty_sentinel` defined. |
| `ENUM_VIOLATION` | yes | Body/value outside the closed vocabulary. |
| `PATTERN_VIOLATION` | yes | `line_pattern` / `body_pattern` / `pattern` failed. |
| `LENGTH_VIOLATION` | yes | Any min/max chars, words, lines, items, length bound. |
| `MALFORMED_JSON` | yes | `json.loads` failed. |
| `SCHEMA_VIOLATION` | yes | Type, required key, or `additional_keys: forbid` failure. |
| `CROSS_CHECK_VIOLATION` | yes | A `cross_checks` entry failed. |

A HullCheck containing **any** terminal violation skips the Second Pass and fails immediately.
Retrying a terminal fault burns a full model run to reproduce the same result.

`Violation.detail` is written as the corrective instruction, not the complaint. Not
"VERDICT was invalid" but "`VERDICT` must be exactly one of `ACCEPT`, `REJECT`, `INCONCLUSIVE`;
found `Accept (with reservations)`." The detail string is what the model reads on the Second Pass,
so its quality is the loop's yield.

---

## 9. The Second Pass

`warrant.run_warranted(...)` wraps `llm.run_prompt` and owns the entire loop. Capability modules
call it instead of `run_prompt` and receive already-validated payload — they never see raw text.

```python
def run_warranted(
    prompt_body: str,
    warrant: Warrant,
    working_directory: Path,
    *,
    runner: Runner = run_prompt,        # injected; tests substitute a fake
    warrant_inputs: Mapping[str, Any] | None = None,
    **run_prompt_kwargs,
) -> WarrantedResult: ...

@dataclass(frozen=True)
class WarrantedResult:
    payload: Any                        # validated blocks / JSON / lines
    attempts: tuple[AttemptRecord, ...] # one per pass, index 0 is the first
    result: LlmResult                   # the accepted attempt's LlmResult
    @property
    def second_pass_used(self) -> bool: ...
```

Algorithm:

```text
attempt = 0
while attempt < warrant.max_attempts:
    text   = runner(prompt if attempt == 0 else prompt + second_pass_block, ...)
    check  = check_output(text, warrant, inputs=warrant_inputs)
    record attempt (execution_id, violation codes, ok)
    write <stem>.violations.txt when not check.ok
    append drydock.warrant JSONL record
    if check.ok:
        if attempt > 0: print the recovery notice (§10)
        return WarrantedResult(...)
    if any violation is terminal or on_violation == "fail":
        break
    attempt += 1
raise PromptContractError(rendered failure block)
```

Invariants:

- The Second Pass re-sends the **entire original prompt** including all injected inputs, plus the
  feedback block. It is a fresh execution, not a continuation — the provider CLI is stateless here
  and a delta-only retry loses the inputs.
- The Second Pass demands a **complete** re-emission, never a patch. Merging a partial correction
  into a prior attempt's output is forbidden; it manufactures an artifact no single model pass ever
  produced.
- Each attempt is its own `run_prompt` execution with its own `execution_id` and its own
  prompt/raw/output artifacts. Evidence stays reproducible.
- `max_attempts` is hard-capped at 3 in code regardless of the Warrant value.

### Second-Pass feedback block

Appended verbatim to the end of the original prompt. Fixed wording:

```markdown
## Contract violation — re-emit required

Your previous response did not satisfy the output contract above. The violations found by
Drydock's deterministic checker are listed below. They are facts about your previous output, not
opinions.

<VIOLATIONS>

Re-emit the complete output now, satisfying every requirement in the output contract. Emit all
required blocks, not only the ones named above. Do not explain the previous failure, do not
apologize, and do not comment on this instruction. Emit only the contracted output.
```

`<VIOLATIONS>` is `HullCheck.feedback()`:

```text
1. [MISSING_BLOCK] VERDICT — emit a `=== VERDICT ===` block containing exactly one of
   `ACCEPT`, `REJECT`, `INCONCLUSIVE`.
2. [TEXT_OUTSIDE_BLOCKS] — 3 lines appeared outside any block. Emit no text outside blocks.
   Offending text: "I'll now generate the specification files for the import…"
3. [PATTERN_VIOLATION] FINDINGS line 4 — every line must match
   `^(BLOCKER|MAJOR|MINOR) \| [^|]+ \| .+$`.
   Offending text: "* critical: missing auth check in login.py"
```

Rules: capped at 4000 characters (matching `_REPAIR_FEEDBACK_CAP` in `build_run`); truncation is
by whole violations with an explicit `… and N further violations of the same kind` tail; excerpts
capped at 200 characters each; violations ordered structural-first (missing/unknown/outside-text
before per-field pattern faults), because fixing structure often resolves the rest.

---

## 10. Logging and Operator Surfacing

The existing evidence path is retained in full: `run_prompt` already writes `logs/llm.jsonl`, the
per-run `.prompt.md`, `.raw.jsonl`, `.output.txt`, `.stderr.log`, and an `ExecutionArtifacts`
record per attempt. Both attempts appear there already. Three additions:

### 10.1 New JSONL record — `drydock.warrant`

Appended to the same `logs/llm.jsonl` after each Hull Check, keyed to the attempt's
`execution_id` so the pair joins cleanly. Distinguished from the existing execution record by its
`schema` field, so existing readers that filter on `schema_version` alone must be checked.

```json
{
  "schema": "drydock.warrant",
  "schema_version": 1,
  "timestamp": "2026-07-30T14:22:31.512Z",
  "execution_id": "20260730-142201-3f9ac1b2",
  "command_name": "survey import",
  "target": "MARINA",
  "prompt": "survey_import",
  "prompt_version": "20260730 V5",
  "warrant_version": 1,
  "attempt": 0,
  "max_attempts": 2,
  "status": "violated",
  "terminal": false,
  "violation_codes": ["MISSING_BLOCK", "TEXT_OUTSIDE_BLOCKS"],
  "violations": [
    {"code": "MISSING_BLOCK", "locus": "VERDICT", "detail": "…", "excerpt": ""},
    {"code": "TEXT_OUTSIDE_BLOCKS", "locus": "", "detail": "…", "excerpt": "I'll now generate…"}
  ],
  "violations_file": "logs/20260730.142201.MARINA.survey-import.claude.violations.txt"
}
```

`status` ∈ `conformant | violated`. Recording a conformant attempt too is deliberate: the
first-pass conformance rate per `prompt` + `prompt_version` is the metric that makes prompt
hardening measurable rather than anecdotal. Without it, a `version` bump is an opinion; with it,
it is an A/B with an outcome.

### 10.2 New per-attempt artifact — `<stem>.violations.txt`

Written beside the attempt's `.output.txt` using the same stem, only when the attempt violated.
Contains the full uncapped violation report plus the Warrant name and version. This is what the
operator opens; the JSONL record is what tooling reads.

### 10.3 Console output

**Second Pass triggered** (warning, single line plus the violation list, always shown — a silent
retry hides a real quality signal and doubles cost invisibly):

```text
⚠ survey import: output contract violated (attempt 1/2) — retrying with feedback
    [MISSING_BLOCK] VERDICT
    [TEXT_OUTSIDE_BLOCKS] 3 lines outside blocks
    evidence: logs/20260730.142201.MARINA.survey-import.claude.violations.txt
```

**Second Pass recovered** (informational, so the operator knows the run cost two passes):

```text
✓ survey import: output contract satisfied on attempt 2/2
```

**Second Pass failed** (terminal, modeled on `llm.render_fatal_provider_error_block`, exit 1):

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT CONTRACT NOT SATISFIED — survey import
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Prompt   : survey_import (version 20260730 V5)
Warrant  : prompts/warrants/survey_import.json (warrant_version 1)
Attempts : 2 of 2

Attempt 1  execution 20260730-142201-3f9ac1b2  VIOLATED
  [MISSING_BLOCK] VERDICT — emit a `=== VERDICT ===` block containing exactly one of
    `ACCEPT`, `REJECT`, `INCONCLUSIVE`.
  [TEXT_OUTSIDE_BLOCKS] — 3 lines appeared outside any block.
    Offending text: "I'll now generate the specification files for the import…"
  output     : logs/20260730.142201.MARINA.survey-import.claude.output.txt
  violations : logs/20260730.142201.MARINA.survey-import.claude.violations.txt

Attempt 2  execution 20260730-142644-b71e0d55  VIOLATED
  [ENUM_VIOLATION] VERDICT — body must be exactly one of `ACCEPT`, `REJECT`,
    `INCONCLUSIVE`. Offending text: "ACCEPT (with reservations)"
  output     : logs/20260730.142644.MARINA.survey-import.claude.output.txt
  violations : logs/20260730.142644.MARINA.survey-import.claude.violations.txt

No files were written. Re-run the command to try again. If this recurs, the prompt or its
Warrant is defective: prompts/survey_import.md, prompts/warrants/survey_import.json.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Both attempts' violations are shown. A second-attempt-only report hides whether the model failed
the same way twice (prompt defect) or differently (model variance) — the single most useful
diagnostic signal in the whole feature.

### 10.4 Errors and exit codes

```python
class PromptContractError(LlmError):
    """Model output did not satisfy its prompt Warrant within the attempt budget."""
```

Exit code **1** (operational failure), consistent with `AGENTS.md`. A malformed *Warrant* or a
missing Warrant file is a different class — a repository defect surfaced at load time as
`DrydockError`, also exit 1, but raised before any model spend.

### 10.5 Reporting hook

`WarrantedResult.attempts` is exposed so `build_report`-style summaries can carry a
"contract retries" line. Not required for the first implementation; do not build it speculatively.

---

## 11. Migration Plan

Phased, each phase independently shippable, each with tests green and lint clean.

| Phase | Deliverable | Definition of done |
|---|---|---|
| **1** | `warrant.py`: `Warrant` dataclass, `load_warrant`, Warrant-file validation, `format: "blocks"` checker over `parse_artifact_blocks`, Violation taxonomy. | Unit tests for every violation code. No prompt uses it yet. |
| **2** | `render_contract_section` for `blocks`. Golden-file tests of rendered output. | Rendered text byte-stable; a Warrant change moves the golden file. |
| **3** | `run_warranted` + Second Pass + `PromptContractError` + logging (§10.1–10.4), with an injected fake runner. | Loop tests: pass-first, recover-on-second, fail-both, terminal-skips-retry, `max_attempts: 1`. |
| **4** | Convert **one** prompt end to end. Recommend `survey_import` or `target_documentation` — block-shaped, moderate blast radius, existing tests. | Command behavior unchanged on conformant output; new behavior on violation; hand-written contract section deleted from the prompt body; `version` bumped. |
| **5** | `format: "json"` checker + schema subset + `cross_checks`. Convert `build_score`. | `build_score` "judge every Sea Trial exactly once" enforced by `array_covers_input_ids` rather than by request. |
| **6** | `format: "lines"` if a real prompt needs it. Otherwise drop it from the design. | Do not build speculatively. |
| **7** | Convert remaining LLM-assisted prompts one at a time. | Each conversion is its own commit with its own tests. |
| **8** | Specification update in `docs/Drydock_Specification.md`. | **Requires the author's explicit block-by-block approval. Do not draft it as part of implementation.** |

Sequencing rule: no phase converts more than one prompt. A conversion that changes both the
mechanism and several prompts makes a regression un-bisectable.

---

## 12. Test Matrix

| Layer | Tests |
|---|---|
| Warrant loading | Missing file; `prompt` mismatch with frontmatter `name`; unknown top-level key; unknown schema keyword; `name` and `name_pattern` both set; `max_attempts` out of range; missing `description` on a descriptor; invalid regex. |
| Blocks checker | One test per violation code; `empty_sentinel` accepted; `empty_sentinel` exempt from `line_pattern`; `cardinality: many` count bounds; `name_pattern` matching and non-matching; unknown block rejected; text outside blocks rejected; interaction with `_repair_missing_leading_delimiter`. |
| JSON checker | Fenced and unfenced; leading prose rejected when `allow_leading_prose: false`; every schema keyword's pass and fail case; `additional_keys: forbid`; nested arrays of objects; both `cross_checks` in pass and fail form. |
| Renderer | Golden files per format; assert rendered text contains every constraint the checker enforces (**bidirectional coverage test** — the strongest guard against drift). |
| Loop | Conformant first pass makes exactly one runner call; violated-then-conformant makes exactly two and returns attempt 2's payload; violated twice raises `PromptContractError` naming both execution IDs; terminal violation makes exactly one call; `max_attempts: 1` never retries; `on_violation: "fail"` never retries. |
| Logging | A `drydock.warrant` record per attempt with correct `attempt`, `status`, `violation_codes`; `violations.txt` written only on violation; conformant attempts recorded. |
| Console | Retry warning shown; recovery notice shown; failure block contains both attempts, both output paths, both violations files. |
| Repository guards | Every prompt whose frontmatter names a `warrant:` has that file; every Warrant's `prompt` matches a real prompt; no Watertight prompt body contains a hand-written `## Output contract`; a Warrant content hash change without a `version` bump fails (hash manifest committed alongside). |
| Packaging | `load_warrant` resolves in the source tree and from the installed wheel (`drydock/resources/prompts/warrants/`). |
| Cost | Every test uses the injected fake runner. **No test spends credits or touches the network.** |

---

## 13. Explicit Non-Goals

- **Not** constrained decoding, forced tool calls, or `response_format`. The subscription-
  authenticated `claude` CLI path does not expose them; assume L0 absent.
- **Not** a general JSON Schema implementation. The subset in §6.3 is deliberately closed. If a
  prompt needs more, extend the subset in a reviewed change rather than adding a dependency.
- **Not** semantic validation of content quality. The Hull Check verifies shape and closed
  vocabularies. Whether a verdict is *correct* is the domain of Sea Trials and scoring.
- **Not** more than one retry by default. Three or more attempts is spend without a matching
  yield curve.
- **Not** automatic prompt rewriting from observed failures. Prompt text is a versioned human
  artifact.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Over-tight Warrant rejects acceptable output, doubling cost on every run. | The conformance metric in §10.1 makes this visible immediately. Start each Warrant loose (structure only) and tighten field constraints once first-pass yield is observed. |
| Rendered contract section grows long and dilutes the task instructions. | Renderer stays terse; `description` fields are one line; `notes` never reaches the model. |
| `drydock.warrant` records in `logs/llm.jsonl` break an existing reader. | Audit every reader of `llm.jsonl` in Phase 3 and filter on `schema`. If any reader cannot be made tolerant, use `logs/warrant.jsonl` instead — decide in Phase 3, not now. |
| Cross-check inputs drift from what the capability actually supplied. | `warrant_inputs` keys are validated against the Warrant's declared `input_parameter` names at load time; an undeclared or missing key is an error before the model runs. |
| Two attempts double latency on the failure path. | Accepted. The alternative is a failed command, which costs a full re-run plus operator time. |

---

## 15. Open Decisions for the Author

1. **Name.** "Watertight Prompt" / "Warrant" / "Hull Check" / "Second Pass" as proposed, or an
   alternate set. Naming is fixed before Phase 1 because it lands in module names, JSONL schema
   strings, and operator-facing text.
2. **First conversion target** (Phase 4): `survey_import`, `target_documentation`, or another.
3. **Retry budget default.** `2` is recommended. `3` is permitted by the format.
4. **Log stream.** `drydock.warrant` records in `logs/llm.jsonl` (recommended, joins on
   `execution_id`) versus a separate `logs/warrant.jsonl`.
5. **Whether `build_run`'s existing repair loop is refactored onto this mechanism.** Recommendation:
   **no**. That loop repairs *code against failing checks*, not *output against a format contract*.
   They are different failures with different feedback and must stay separate.
