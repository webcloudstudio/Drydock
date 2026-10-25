# MEMORY: drydock plan

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Turn imported sources into Blueprints and a Manifest Build can execute without further interpretation. |
| Route | plan |
| Modules | `planning_session.py`, `plan_verify.py`, `plan_repair.py`, `plan_graph.py`, `plan_topology.py`, `database_contract.py`, `manifest.py`, `lineage.py` |
| Prompts | `plan_create.md`, `plan_create_speckit.md`, `plan_continue.md`, `plan_conform.md`, `plan_reuse.md`, `plan_repair.md`, `plan_artifact_waiver.md`, `BLUEPRINTS_CONTRACT.md`, `MANIFEST_CONTRACT.md` |
| Tests | `tests/test_plan*.py`, `tests/test_planning_session.py`, `tests/test_database_*.py` |
| Topics | [foundations](../topics/foundations.md), [acceptance_criteria](../topics/acceptance_criteria.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Intent

Turn imported sources into Blueprints and a Manifest Build can execute without further
interpretation. Plan is the last place a defect is cheap. It never discards paid work, and it never
reports unbuildable work as buildable: the exit status says whether Build can execute what was
written.

## Guardrails

- None.

## Details

`2026-10-25` · Database operation heading validation names every malformed level-three heading
in `## Access Patterns`, including mixed-case IDs, even beside valid operations. Retry feedback
states the uppercase ID, three-digit suffix, and em-dash grammar rather than claiming the
operations are absent. Bare `AC` and `END AC` names are reserved by both artifact parsers;
id-less criterion closes remain in the Blueprint body for existing criterion validation and
reported boundary recovery. This extends `299b702`'s namespace guard for FxRates
`20261025.184822`; no identifier or criterion body is silently rewritten.

`2026-10-24` · `DATABASE.md` admission and `plan verify` reject a shared Output DTO name
with different ordered fields or emitted field types, including names that normalize to one
Python class. The emitter uses the same output-row registry and normalization helpers in
`database_row_types.py`; equivalent SQL/Python field spellings remain compatible. Diagnostics
name both pattern IDs, operations and shapes, and recommend a complete-operation-derived
Output name without changing the fields or callers' contracts. Stage 2 returns the rejected
draft and defect to its existing retry before the declaration freezes. `BLUEPRINTS_CONTRACT.md`
V35 states the naming rule. This extends `71d1533` for FxRates `20261025.014047` without changing
mutation returns or the master specification.

`2026-10-24` · `drydock plan` prints every warning's text before returning in normal and
debug modes. The obsolete removed-criterion marker import is removed from the debug path.
`BLUEPRINTS_CONTRACT.md` V34 directs valid CSV success fixtures through `csv.writer` with LF
terminators and padding inside quoted values, preserving the source parser contract; manually
malformed records belong only to rejection criteria. This is authoring guidance, not a new
semantic CSV validator. The CsvStat `20261025.011759` generated fixture remains preserved.

`2026-10-24` · `plan verify` recognizes a module-local, undecorated helper that directly
returns one `cli_runner` tuple, optionally inside `with`, when every caller asserts its exit.
Branching helpers, extra runner calls, escaped/rebound names, and unchecked callers retain
`unchecked-call`. Rebinding the returned exit before its assertion also retains the defect.
The analysis reuses the existing assertion checker without executing criterion code. This
extends `1fd07d0` for CsvStat `20261025.001433`, whose fifteen valid helper calls required repair.

`2026-10-24` · Staged corpus probes recognize section/selection options and options whose
parsed values feed `re.compile`, rather than treating the first option as a selector.
Program and corpus-path arguments remain in the probe's complete argv. A canonical,
unmodified `import os` permits syntactic resolution of `os.path.abspath("literal-path")`
against the criterion working directory, including argv bound to a module variable; no criterion
expression is evaluated and the proof text is unchanged. Other unresolved arguments fail as
`unresolved-probe-arguments`, naming their one-based runner-argument positions. `plan repair`
reports these unchanged without a model call: declaration edits cannot repair body expressions.
`Probe Count: json` counts JSON array items, including zero for `[]`; JSON arrays/objects are rejected under `lines`. Probe repair
receives only the implicated runner source, preserves non-probe metadata, code and assertions,
and changes listing flags/count formats for `probe-failed`; `empty-selection` retains scoped
selector repair. `BLUEPRINTS_CONTRACT.md` requires flags and protocols the supplied runner
implements. This revises `51a9c2b`; the master specification is unchanged.

`2026-10-24` · Ed defines repeated artifact filenames within one response as updates: the last
block replaces earlier drafts before validation. Both parser paths and output cleanup accept
closed repeated envelopes; unrelated files remain intact. The chosen body still passes every
normal admission check, and an unclosed final update is recovered or re-requested rather than
falling back to an older draft. Frozen artifacts accepted in earlier calls remain protected.
Original execution evidence retains every draft. This revises `40de6f7`'s conflicting-copy
rejection; `plan_create` V51 and `plan_continue` V6 document full replacements rather than patches.
Malformed-response retries also retain the parser's exact filename and reason.

`2026-10-24` · A fatal provider failure during Stage 2 propagates immediately to the CLI's
existing environmental-blocker path, including when the runner raises after recording the stop.
No continuation retry, generic empty-response progress, or generation-stall record follows it;
the original provider kind, message, and execution remain authoritative. Regression evidence:
`tests/test_planning_session.py::test_stage_two_provider_stop_never_becomes_a_generation_stall`.

### Syntax

```text
drydock plan <Target> [--overwrite] [--no-conform] [--override] [--continue-attempts <n>]
                      [--lineage-model <model>] [--model <model>] [--llm-provider <p>]
                      [--plan-override-model <model>]
drydock plan verify <Target>     deterministic, read-only, no LLM call
drydock plan repair <Target>     one LLM pass making unrunnable criteria runnable
```

Intended workflow: `drydock plan <Target> && { drydock plan verify <Target> || drydock plan repair <Target>; }`.

`--plan-override-model` replaces `--model` and the configured default for every `plan` form. It is
read before parsing, in any operand position, and refused with exit `2` by every command except
`plan` and `uat`.
`--lineage-model` is accepted only by `drydock plan <Target>`.

### Rules

`2026-10-24` · **Citation validation distinguishes binding expectations from re-typed literals.**
Every declared `Cite:` resolves inside `sources/`. Verbatim matching applies only when the
criterion has re-typed expectations; numeric exit codes and plain ASCII expectations already
bind and do not need literal derivation. This does not establish semantic support for an
already-binding expectation. Citation repair receives only its referenced source files with
one-based line numbers and changes only the existing `Cite:` declaration. Other proof and metadata
changes, removed citations, and still-invalid citations are rejected per criterion. Missing
source evidence yields `REPAIR_IMPOSSIBLE`. This revises `2af2661` alongside `b7ea20b`.
A criterion may cite several ranges, one `Cite:` line each. Every range must resolve, and the
cited text is their concatenation. The declaration is the run of consecutive `Cite:` lines, so
repair may rewrite, add, or drop ranges within it.
Cost when broken: DupFind `20261024.080843` rejects two runnable criteria even with correct
citation ranges, then asks a source-free repair prompt to infer missing source lines. FxRates
`20261024.155325` refuses two-line citations in verify, then rejects their correct repair.

`2026-10-24` · **An artifact closed inside its own body is damaged.** When content and then an
invariant `=== END ARTIFACT ===` follow an artifact's close with nothing open,
`pair_artifact_delimiters` reports that artifact in `premature_closes` and
`_unpaired_artifact_names` names it, so the Stage 2 pass drops it and re-requests it like a cut
artifact. A repeated close with nothing between damages nothing. *Broken:* FxRates
`20261024.183153` closed AC `load-rejected-file-is-atomic` with the artifact token;
`FEATURE-CLI-Load.md` was accepted without `## User Acceptance` and `## Guardrails`.

`2026-10-24` · **A final invariant artifact close missing only its trailing equals is repaired.**
For artifact-format calls, the shared adapter completes an exact `=== END ARTIFACT` on the final
nonblank line only when one artifact remains open and the resulting envelope sequence has no
nested, orphan or mismatched boundary. Body text is unchanged and all downstream
validation still applies. Original output and provider transcripts remain unchanged;
`logs/llm.jsonl` records `output_contract.repaired` and the normalized payload hash. Plan prints
successful repairs without `--debug`. Other incomplete envelopes retain rejection and bounded
retry; Stage 2 prints the damaged filename and required closing token and includes that reason
in the next batch, including after partial progress. This revises `a3d0e60`'s generic no-progress
feedback. Cost when broken: Quakes `20261024.054647` repeatedly discarded `VERIFICATION.md` for
this exact token omission and stalled at 10/11 after two identical retry prompts.

`2026-10-22` · Plan refuses recognized criterion DSN mutations, explicit fixture DSNs and schema calls (`acceptance-store` defects). Prompt guidance requires the shared-store lifecycle in [acceptance_criteria](../topics/acceptance_criteria.md). Cost when broken: a valid feature is graded against an unprovisioned database.

`2026-10-22` · **Structured model calls declare their output format to `llm.run_prompt`.**
The adapter strips only bounded plain narration around intact artifact envelopes or one complete
JSON object/array; it also removes a surrounding JSON code fence. It preserves artifact bodies,
JSON values, and original execution output. The execution record reports removed spans, cleanup
defects, and the normalized payload hash. Ambiguous output remains unchanged for the command's
validators and existing bounded recovery; the adapter does not add model calls. Format
cleanup does not replace the command's schema or semantic checks. *Broken:* wrapper narration
pollutes an artifact, or broad substring extraction silently hides malformed output.

`2026-10-19` · Planning requires a valid, Commander-approved TECHNOLOGY_STACK.md before model execution, including with --override. Language comes from selected Rigging guidance. The language initialization story occupies a separate computed block so its project files exist before persistence generation; prompt sizing includes the selected full or compact language file. Breaking this rule plans an undecided or incompatible stack.

`2026-10-21` · **A Stage 2 retry carries the reason the last batch was refused.** The ledger
appends `Previous attempt rejected — <reason>` after any whole-batch refusal (malformed
delimiters, no artifact blocks, a frozen/undeclared/deferred artifact, no complete Blueprint),
and clears it on an accepted batch. A response with no artifact blocks prints `[plan] response
without artifacts: "<excerpt>"`. `plan_continue.md` V2 forbids questions, tool requests, and
refusals in place of artifacts and routes open points to `## Questions`. *Broken:* LayersTesting
`20261021.173113` resent a byte-identical prompt three times after Haiku asked questions instead
of emitting, and plan stalled at 16 / 31 Blueprints.

`2026-10-24` · **An artifact-free reply receives an additive instruction correction.**
The continuation keeps the normal Current batch after a prose refusal; no automatic one-file
fallback exists. The existing context and contracts remain intact. The retry ledger appends the
rejected reply, failure count, execution id, and a correction that authoring acceptance criteria
does not require executing or inspecting the future product; supplied helper contracts establish
staging and invocation. Actual source conflicts and missing product requirements use
`BLUEPRINT_BLOCKED.txt`. Console progress names the instruction failure, remaining allowance,
and saved response path. Repeated failures stop within the existing consecutive-stall and total
pass limits. Progress clears the correction and retains accepted artifacts. This removes
`2e121e4`'s refusal-driven resizing. *Broken:* DrydockStats `20261024.145357` requests confirmation
of helper facts already supplied; changing prompt size does not establish a remedy for that
instruction failure.

`2026-10-22` · **A Blueprint a batch cannot author is reported, checked, and fed back.**
`plan_continue.md` V4 defines `BLUEPRINT_BLOCKED.txt`: one entry per Current-batch Blueprint with
`Blueprint:`, `Error type:` (`missing-input`, `conflict`, `insufficient-specification`, `other`),
`Cited input:`, `Details:`, and `Required action:`. The batch still emits the Blueprints it can.
`plan_blocked.check_blocked` refutes an entry that names a file outside the Current batch, uses an
unknown type, cites no file, has a `Required action` that names no decision ("None needed", "can
be authored"), rests on accepted Blueprints (names one, "accepted artifacts", "cannot verify"),
claims missing an input that is in the batch's prompt, or, under `DRYDOCK_UAT=1`, is typed
`insufficient-specification`: no Commander answers, so the batch chooses the narrowest behavior
consistent with its inputs. Every entry prints as `[plan-score][plan] blocked: <file> · <type> · cited
<input> · stands|refuted — <finding>`. The next batch's ledger carries `Prior run error type:` and
`Prior run error details:` with each entry and Drydock's finding. A prose reply without artifacts
is fed back as `unstructured-refusal` with up to 600 characters of the reply. A block does not
stop the loop. A block-only batch counts as a stalled pass and keeps the batch size. When the
retry allowance runs out with a standing `conflict` or `insufficient-specification` block, plan
records it as a deferred product decision and exits `2`. Any other standing block is listed in the
`plan generation stalled` record with the last rejection. *Broken:* LayersTesting
`20261022.121722` refused 14 of 27 batches in prose, mostly with false claims (no tools, sources
absent while present). At batch size 1 the retry could not change the ask, and plan stalled at
25 / 27. LayersTesting `20261022.165023` stood two unchecked Haiku blocks, an `other` that
asked for accepted Blueprints and an `insufficient-specification` whose Required action read
"None needed to unblock", and deferred at 11 / 28 with exit `2`.

`2026-10-21` · **Stray text is discarded, never fatal.** Up to three lines of plain narration
before, between, or after intact artifact blocks are dropped and printed as `[plan] stray text
<where> discarded: "<text>"`. Outside text shaped like content — a heading, list, table, fence,
JSON, markup, `===`, more than three lines or 500 characters — or beside an orphan close still fails
the parse. Plan discards it only when every artifact occurrence opens and closes; other bounded
outside text keeps the diagnostic waiver. *Broken:* a weak model's one-line preamble fails the run,
or a body that lost its opener is silently dropped.

**Governing**

`2026-09-17` · **Repair the unambiguous, record the rest, discard nothing paid for.** Stage 2 has no
cross-run memory, so a discarded plan is re-authored from batch 1. *Broken:* 39 accepted
Blueprints and 9 calls written nowhere.

`2026-09-17` · **Severity tracks whether Build would write wrong code.** An unreadable declaration,
or a citation contradicting one, blocks its story; an omission is `material` and gates nothing.
*Broken:* 22 stories parked behind questions none needed.

`2026-10-23` · **`plan` writes, `plan verify` judges, `plan repair` fixes.** The final
`plan verify` runs inside `plan`. When it is not clean, the artifacts are written for
`plan repair`, the Manifest is `draft` / `unbuildable` so Build refuses it, `ERRORS.md` records
the defects, and `plan` prints the report and `drydock plan verify <T> || drydock plan repair
<T>`, then exits `0` — no waiver, `--override` and unattended included. *Broken:* the
`2026-09-19` exit `1` for this case halted FxRates `20261024.015228` before the UAT's own
verify-and-repair stage, so six repairable criteria were never repaired. The earlier
`approved` false positive stays closed by the `draft` Manifest.

**Inputs and authority**

`2026-07-30` · **Plan refuses an undecided analysis.** `BLOCKERS.md`, `Quality: Blocked`, or an
unanswered required questionnaire stops Plan before any call. `2026-10-24` `--override` waives
the questionnaire and an `analyze`-owned decision-only `BLOCKERS.md` (with its `Quality:
Blocked`), recording one `analysis-blocker` waiver per decision; it never waives an environmental
blocker or a `Quality: Blocked` with no file ([process_stops](../topics/process_stops.md)). The only stack gate is Python relational persistence without its Rigging.

`2026-09-22` · **Analyze owns `COMPASS.md`; the Commander owns `PLAN_COMPASS.md`.** Plan never
appends sources to the Compass and never overwrites `PLAN_COMPASS.md`. *Broken:* stale pages
injected into every build step.

`2026-08-01` · **Plan decides and discloses.** Where sources are silent the crew chooses and records
the choice in `DECISIONS.json`, never in a Blueprint. A replan keeps only Commander-directed items.
Under `DRYDOCK_UAT=1` blocking questions become `material` decisions (`2026-08-22`).

`2026-07-31` · **Questions gate only their story.** Blueprints carry questions under `## Questions`;
an open one blocks its story and transitive dependents only. Answers are written to the owning
artifact, survive renames and replans by decision identity rather than filename, and Manifest
approval is never an answer.

`2026-07-30` · **A declared conflict is challenged once.** Only mutually exclusive authoritative
requirements qualify, and a surviving conflict must cite files and clauses; it defers the plan
(exit `2`).

**Stages**

`2026-09-13` · **Stage 1 defects are repaired before Stage 2 spends.** Coverage and the work graph
are checked against the declaration about to freeze.

`2026-10-13` · **A prose-only Stage 1 reply gets one corrective call.** The reply is quoted back
with a request for artifacts; a second prose reply fails with its text shown.

`2026-10-14` · **Stage 2 batches start fresh sessions.** Each batch gets the original context,
frozen topology and decisions, the five-Blueprint ledger, and `DATABASE_compact.md` once
`DATABASE.md` is accepted — no earlier conversation. *Broken:* a five-file request grows to hundreds of thousands of tokens.

`2026-08-02` · **A short plan is resumed, never discarded.** Truncated output gets up to
`--continue-attempts` (default 3) continuation passes against the frozen declaration.

`2026-09-21` · **A repair pass that clears its files earns budget for what it unmasked**, capped at
three times the configured repair count. `2026-09-18` A defect between two files re-emits both.

**Graph**

`2026-08-01` · **Drydock computes order; the model declares only `depends:`.** Blocks come from
`group_blocks`; every story is in exactly one block; `Ungrouped` is fatal.

`2026-10-23` · **Only assembled token cost bounds a block.** Within a partition (phase, type,
screen/non-screen, language initialization), a ready story merges while the block stays under
`prompt_target_tokens` and the merge saves at least `block_min_savings`. Acceptance criteria
count is not a bound. Cost when broken: the 5-criteria cap built ReadingList `20261023.144538`
as 14 single-story blocks of 3–11K tokens, one model call per story.

`2026-10-23` · **No planned block reaches the model's escalation limit.** The absolute ceiling
(`plan_stack.block_limit_tokens`) is `prompt_warning_tokens`, lowered to 90% of
`prompt_limit_tokens` less the row's build overhead when the row sets a limit (Haiku: 82,563
planned tokens, about a 90K request), and the target is clamped to it. A story over the ceiling
fails planning. Cost when broken: a block planned between 98K and 120K builds on `escalate_model`
(Sonnet) instead of the configured model.

`2026-08-02` · **A replan keeps built work whose build-relevant fingerprint is unchanged.**
Renumbering and `Depends On` refactors do not dirty a story; `--overwrite` discards provenance.

**Persistence (`DATABASE.md`)**

`2026-10-22` · **Every story carries a criterion, `DATABASE.md` included.** Stage 2 refuses a
response in which a story's implemented Blueprints declare no Programmatic Acceptance criterion
(`criteria-missing`, routed to artifact repair), and `plan verify` reports the same defect at the
terminal gate, leaving the Manifest `draft`. `- None.` is no exemption. Presence is the gate, not
a count. `DATABASE.md` criteria exercise each repository operation through `db_session()`; the
normalizer that replaced them with a `- None.` invariant statement is deleted, and a criterion
opening `sqlite3.connect(":memory:")` is an `acceptance-store` defect. `plan repair` leaves
`criteria-missing` unrepaired for `drydock plan`. *Broken:* ReadingList `20261022.231143` planned
`persistence-store` with no criteria; Build could only fail it on seven calls.

`2026-10-22` · **Every declared repository operation is called by a criterion.** `plan verify`
and Stage 2 refuse a `DATABASE.md` whose criteria never call a declared `<table>.<verb>`
(`operation-untested`): Python `db.<table>.<verb>(`, Go `db.<Table>.<Verb>(`. A story naming no
Blueprint, or a file outside `blueprint/` such as a Rigging stack file, is `criteria-missing`;
a story implementing a Refit ticket under `changes/` is counted from that ticket. `plan repair`
leaves `operation-untested` for `drydock plan`. The buildable `Rigging/spec_template/` files seed
a `Required.` acceptance note, never `- None.`. *Broken:* a declared operation ships untested
and a template teaches the refused `- None.`.

`2026-10-24` · **A criterion calls only declared repository operations.** `plan verify` and
Stage 2 refuse a criterion in any Blueprint that calls `<table>.<verb>(` on a table
`DATABASE.md` declares when that operation is not declared (`operation-undeclared`), in the
Python or Go spelling; the defect lists the table's declared operations, and Stage 2 routes it to
artifact repair. *Broken:* FxRates `20261024.145257` read back through an undeclared
`db.rates.get`, so the deterministic DATABASE step failed on `UnknownOperation`.

`2026-10-22` · **Database authoring preserves the source schema.** Before accepting the
database batch, Plan restores missing seeded tables, columns, and composite `UNIQUE`/`INDEX`
constraints. A changed seeded column type or constraint rejects the batch with the column named
in retry feedback. Comparison uses parsed column contracts, not Markdown spelling. *Broken:*
the database freezes with a schema different from its source and later Features cannot repair it.

`2026-09-17` · **Persistence is decided, never asked, and never forgiven.** A `DatabaseDefect`
goes to artifact repair; if the budget runs out the run fails and writes nothing. This is the one
exception to the governing rule, because only persistence is fully decidable from the artifacts.

`2026-10-21` · **`DATABASE.md` is authored in one step and frozen.** Every file a batch may emit is
named in its Current batch. `DATABASE.md` is the first authoring batch, regardless of topology
text order, and starts from the seed of the Rigging template plus every source-declared table. The
authored declaration is kept as written, and a seeded table it dropped is appended
(`merge_schema(body, seed)`). Once accepted it is frozen like every Blueprint; a later batch that
changes it is refused whole. Later batches receive `DATABASE_compact.md`: the declaration with
comments and examples removed (`compact_declaration`). *Broken:* LayersTesting `20261021.231950`
kept the seed outside every Current batch as a conditional "Open" aside under "nothing else"; no
batch added update or delete operations, and Haiku refused `FEATURE-TxnAmend.md` three times.

`2026-10-21` · **A batch whose `DATABASE.md` does not parse is refused whole at that batch.** The
merged declaration is checked with `database_contract_defects`. On a defect no artifact of the
batch is kept, the refusal prints on the always-shown score channel, and the next ledger lists
`DATABASE.md` as defective with the reason. *Broken:* LayersTesting
`20261021.034029` accepted a one-table `## Access Patterns` in batch 1, found it only after batch
7, and three repairs from the bare defect text failed. LayersTesting `20261021.213934` dropped the
defect because the seeded declaration is never in a tranche, accepted Features citing undeclared
operations, and stalled when later batches saw the bare template. `2026-10-24`: the retry also
receives the rejected merged draft as `DATABASE.md` in place of the seed, and the ledger tells
it to correct each listed defect in that draft and change nothing else. *Broken:* FxRates
`20261024.140521` re-authored the declaration from the defect text alone three times, trading a
duplicate `rates.list` for a composite PK for missing DTO tables, and stalled. `2026-10-24`: one
rejection names every defect the draft holds. A table's wrong PK count is reported beside the
pattern defects, not raised in their place; column checks run on every pattern that parses; the
name and synonym checks run on every pattern whose fields bind, and the key-dependent shape rules
on those whose table has one PK. A seed-merge failure carries the draft's other defects with it.
*Broken:* FxRates `20261024.143213` batch 1 held a composite PK, unbound history and statistics
fields, and a `rates.latest` synonym; one tier was reported per pass and three passes ran out.

`2026-10-24` · **A refused batch names what follows.** Its `Batch Result:` reads
`Retrying (<n> left): <reason>` while the no-progress allowance remains, `Retries exhausted:
<reason>` on the refusal that spends it, and `Failed: empty or failed model response` when the
call itself fails. No Stage 2 batch prints `Rejected`. *Broken:* FxRates `20261024.145257` printed
`Rejected: DATABASE.md does not parse`, which the operator read as fatal; batch 2 fixed it.

`2026-10-24` · **A plan stall states its cause first.** The `plan generation stalled` detail
prints each `last rejection` defect on its own line, then `blocked:`, then the score and missing
list, then execution ids. The detail is capped at 800 characters on line boundaries. *Broken:*
FxRates `20261024.140521` stderr listed 14 missing Blueprints and truncated the rejection away.

`2026-09-19` · **Only a Feature owns an access pattern; `DATABASE.md` owns shared ones.** A Screen is
never an `| Owner |`; an illegal owner is rewritten to `DATABASE.md` deterministically. Ownership is
read from the declaration, never from `stack:` (`2026-09-18`).

`2026-09-17` · **Four checks define agreement.** Owners cite what they own; a citation may narrow a
grant, never widen it; every table is reached by some pattern; every operation names a declared
table.

`2026-10-22` · **Every `Input:` field is a column of its operation's table.** The generated
repository binds each Input field as the column of that name, so `database_contract_defects`
refuses a field the table does not declare and names the table's columns. A placeholder row such
as `(none)` or `—` declares no field. *Broken:* ReadingList `20261022.180908` declared
`books.delete` with Input `book_id` against `books(id)`. SQLite read `"book_id" = ?` as a string
comparison, every delete removed nothing, and block-2 spent six repairs on a protected file.

`2026-10-23` · **Every `Output:` field is a field the verb returns.** `get`, `create`, and `update`
return one row and `list` returns a list of rows, so each of their Output fields is a column.
A `delete` Output is built from its key, so each field is one of its Input fields.
`output_column_defects` refuses the rest, and the stack guidance carries the per-verb return table.
*Broken:* ReadingList `20261023.200606` declared `books.list` Output `BookList { books: list[Book] }`
and `books.delete` Output `DeletedBook { id }`. Every list raised on an empty row and every
delete returned a count.

`2026-10-24` · **Every `Input:` and `Output:` names its DTO on the same line.** A bare label is
refused by `_parse_access_pattern`, and so by `database_contract_defects`. One DTO name declared
with two field sets is refused by `_row_classes` when `schema.py` is rendered, as the Go emitter
already refused it. *Broken:* FxRates `20261024.070101` wrote bare `Output:` lines. The next line's
table header became the name of all three patterns (`FieldType`), and `rates.delete`, whose Output
is its key, raised on upsert's four-field class. A label line holding fields (`Input: `date: str``,
any `:` in the name) is refused the same way, naming the line and the `| Field | Type |` grammar.
*Broken:* FxRates `20261024.162029` wrote fields inline, declared no Input fields, and was told
only that its Match fields were "not Input fields" for three passes.

`2026-10-24` · **No criterion imports `persistence` before the DATABASE step.** `plan verify` refuses (`persistence-order`, routed to `plan repair`) a criterion that imports `persistence` in a Blueprint implemented by a story whose `block:` precedes that of the story implementing `DATABASE.md`. A story in the DATABASE block is not earlier. *Broken:* FxRates `20261024.073528` put `architecture-boundary` (`open_database("").rates`) on `foundation`, block 1; its builder hand-wrote `schema.sql`, and block-1 failed unexecuted.

`2026-10-23` · **Foundational stories carry no `covers:` or `accepts:`.** `parse_topology` drops
both from a `type: foundational` story and from the story implementing `DATABASE.md`. The Feature
or Screen that delivers the behavior owns the analyzed story and its Sea Trials. A stated
foundation fact is honored in `TECHNOLOGY_STACK.md` and `DATABASE.md`, never as a story criterion.
An analyzed story left uncovered fails the coverage gate, whose repair message states this rule.
*Broken:* ReadingList `20261023.200606` attached `READING-002` and `st-002` to the store as well
as to Add Book.

`2026-10-23` · **An operation is a name with a Kind.** `Repository operation` is `<table>.<name>`;
the name is the method (`db.<table>.<name>`) and the caller contract. `| Kind |` (`get`, `list`,
`create`, `update`, `upsert`, `delete`) is how it runs; a name that is a Kind needs no Kind row,
and any other name without one, or a verb name with a different Kind, is refused. A table holds
several operations of one Kind under different names. Each name is declared once, and a second
name with the same Kind, Match, Sets, and Output is a refused synonym. Both runtimes look up
operations by name and dispatch on Kind. *Broken:* one method per verb meant a table could not
both update by `PK` and reprice by currency.

`2026-10-23` · **The generated surface is the operation contract.** `operation_surface` renders,
per operation: call, Kind, Rows, Match, Sets, Input and Output JSON in caller types, the SQL the
runtime executes (`operation_sql`, held byte-identical to the shipped `Driver` by test), and the
contract fingerprint. It closes `DATABASE_compact.md` from Plan and is spliced into
`drydock rigging compact`'s output. *Broken:* a builder inferred cardinality and return shape.

`2026-10-23` · **Every operation declares the rows it reaches.** An optional `| Match |` row names
the Input fields that select rows: equality, AND, every field required. `resolve_operation` makes
each choice explicit — `get` matches a unique key and its Input is the Match; `list` filters on
optional Input fields; `create` matches nothing; `update` matches the `PK` by default and sets the
rest; `upsert` matches exactly one declared unique key and inserts or replaces in one
`INSERT … ON CONFLICT` statement; `delete`'s Input is its Match. A Match covering the `PK` or a
declared `UNIQUE` reaches one row; any other reaches many, and a many-row `update`/`delete` returns
a count with an Output of no fields. A table grants each verb once. `operation_shape_defects`
refuses every breach with the rule named, after the column checks pass. `compact_declaration` and
`drydock rigging compact` append the generated `## Operation Surface` — per table, each call's
Match, Sets, Rows, and Returns — so builders never infer cardinality. *Broken:* FxRates
`20261023.234755` could not state "a stored (date, currency) is replaced": `update` matched only
the `PK` and no verb inserted-or-replaced, so `FEATURE-LoadReplace.md` stalled the plan at 8/26.

`2026-10-24` · **A range is Match comparison terms; a list's order is declared.** A Match term is a
bare Input field (equality with its own column) or `<column> <op> <field>`, op ∈ `=`, `<`, `<=`,
`>`, `>=`, binding an argument that is not a column. Comparison terms are refused on `get`,
`upsert`, and `create`, and a field may appear in one term only. On a `list` the Match states how
each filter compares and every filter, bound included, stays optional. `| Order | <column> [asc|desc], … |`
is `list`-only and names columns of the table. Only equality fields count toward a unique key, so
a comparison makes an `update`/`delete` reach many rows; a row-returning `update` reads back by its
equality fields. Terms and Order enter the fingerprint only when declared, so a pattern with
neither hashes as before. Both runtimes take `compare` and `order` from the generated schema,
whitelist operators and directions, and build the SQL the surface shows. *Broken:* FxRates
`20261024.145257` batch 1 bound `start_date`/`end_date` as columns of `rates` and was refused; the
retry dropped the range into Feature code.

`2026-09-19` · **One pattern is one `<table>.<verb>` operation**, verb ∈ `get`, `list`, `create`,
`update`, `upsert`, `delete`. A Blueprint's `## Database Interface` entry is one checked line
(`id — access, supplies:, returns:`) or `- None — <why>.`; a parse failure quotes the line and the
accepted form.

`2026-09-19` · **Every column token is executable.** Types are `INTEGER`, `TEXT`, `REAL`, `NUMERIC`,
`VARCHAR(n)` with `PK`, `NOT NULL`, `UNIQUE`, `DEFAULT <literal>`, `REFERENCES t(c)`; composites are
`- UNIQUE (a, b)` / `- INDEX (a, b)`. Anything else is refused by name; the closed `DEFAULT` set
also prevents DDL injection. Foreign keys order `CREATE TABLE`.

`2026-10-23` · **Every table declares exactly one `PK` column.** `sqlite_schema_tables` refuses a
table with none or with two, and the defect names the fix (`id | INTEGER PK`, natural key as a
`- UNIQUE (a, b)` bullet). A keyless table builds an update that can never run; a natural key is
reached through `| Match |` (`2026-10-23`). *Broken:* FxRates
`20261023.224908` declared `rates` with only `UNIQUE (date, currency)`, and `database-update`
raised "updates rates without supplying a key".

`2026-09-17` · **A spelling outside the vocabulary is normalized, never guessed**, and the rewrite
is reported.

**Criteria**

`2026-10-24` · **Acceptance observes the delivered application.** Planning prompts forbid
substitute implementations and standalone language expressions as the observed product value.
Go CLI criteria invoke the declared application through `drydock_go.cli_runner`, check the
exit code, parse CSV, and compare observed fields with fixture-derived expectations. Stage 2
also requires Programmatic Acceptance, User Acceptance, and Guardrails in that order, preserving
source constraints and using `- None.` only for empty non-programmatic sections. These are
authoring instructions, not new static gates; the existing empty-tree baseline detects checks
that pass without the product. Cost when broken: DrydockStats `20261024.155305` generates
formatting self-tests and omits Guardrails in six Features.

`2026-09-17` · **A criterion states one expectation.** A status set admitting `404` beside others,
or both a 2xx and a 5xx, is refused. See [acceptance_criteria](../topics/acceptance_criteria.md).

`2026-10-20` · **A criterion creates the state it depends on.** `plan_create.md` and
`BLUEPRINTS_CONTRACT.md` require each AC block to create every row, file, or record that its input
refers to and that a source rule requires to exist. The rule is enforced by the prompt only. No
deterministic check exists. *Broken:* a correct product fails an expected success, and an expected
rejection passes for the wrong reason (LayersTesting `20261020.161323`, `load-transactions-valid`).
Every setup call asserts the success its source declares; a setup call expecting failure creates
nothing (`plan_create.md` V40, `BLUEPRINTS_CONTRACT.md` V24, `2026-10-20`). *Broken:* LayersTesting
`20261020.183046` asserted `load categories sources/seed_categories.csv` exits `1`, and a correct
loader failed `transaction-post-read`.

`2026-10-20` · **A criterion never contradicts the staged harness on a staged file.** `plan verify`
(`harness_exits.py`) reads each `cli_runner(<literal args>)[0] == <int>` call that passes a staged
source file and compares the first call per command with every `sources/*.sh` line of the shape
`<int> [<program>] <args...>`, files compared by name. An exit no matching line expects is a
`harness-exit` defect; `plan_repair.md` V10 may change that expected exit to the harness value and
the assertions that followed from it. Calls addressing state are not compared: the harness rejects
`txn delete 1` at its point in the sequence, while a fresh criterion correctly expects `0` (run
`20261020.191708`). Unrecognized shapes are skipped, never guessed. *Broken:* LayersTesting
`20261020.183046` asserted `load categories sources/seed_categories.csv` exits `1` against
`run.sh:67` expecting `0`, and no build could pass five criteria.

`2026-10-21` · **Every `cli_runner` call asserts its exit status.** `plan verify` reports an
`unchecked-call` defect for a call whose result is discarded, whose exit is bound to `_`, or whose
exit name is rebound before an `assert` reads it. `plan_repair.md` V10 binds the call and adds
`assert code == 0` after it. *Broken:* LayersTesting `20261021.195808` ran two setup calls that
failed silently, then tested an account that did not exist.
`2026-10-24` · A `def` or `class` body is judged as its own scope, so a call inside a function
with its own `assert` is checked. *Broken:* DupFind `20261024.183232` rejected four asserted calls.

`2026-10-24` · **A criterion's code runs.** `plan verify` and Plan's criterion gate report an
`uncalled-function` defect for a criterion that defines a top-level function no top-level
statement reaches. Plan's gate also reports `fenced-criteria` for an emitted Blueprint whose
Programmatic Acceptance uses Markdown ```` ```python ```` fences instead of `=== AC <id> ===`
blocks, and returns both to artifact repair. `plan verify` and Build still read the fenced form.
*Broken:* DupFind `20261024.183232` repair wrote fenced `def test_*` modules that
`runpy.run_path` never calls, and `plan repair` could not address them.

`2026-10-24` · **Exit assertions may follow collection into a dictionary.** `plan verify`
recognizes an empty result dictionary filled by one `cli_runner` assignment per key of a
literal dictionary, followed immediately by a loop over every result's `.items()` that
unpacks `(code, out, err)` and asserts `code == <integer>`. Prints may precede the assertion.
The check preserves enclosing loop/branch scope and refuses intervening mutations, duplicate-key
sequences, filtered checks, and rebound exit variables. Other unsupported shapes retain
`unchecked-call`. This revises `b7ea20b`. Cost when broken: DrydockStats `20261024.143257`
rejects REM-007 despite its later assertion of every collected exit code.

`2026-10-21` · **A refusal about staged data requires loading it.** `plan verify` reports a
`staged-value` defect when the first `cli_runner` call that uses a key from the first column of a
staged `sources/*.csv` data row expects a non-zero exit, and the criterion never names that file.
A key the criterion creates (expected `0`) or a deliberately absent key is not reported.
`plan_repair.md` V10 creates the state inside the criterion under an identifier no staged file holds.
*Broken:* LayersTesting `20261021.195808` asserted `account delete DRAWER1` exits `3` (in use)
without loading `seed_accounts.csv`; the product correctly answered `4` (absent).

`2026-10-22` · **A criterion never launches the application through `go run`.** `plan verify`
(`harness_exits.go_run_calls`) reports a `go-run` defect for an argv list or shell string that
starts `go run` with a target other than a pinned tool (`tool@version`). The defect names
`drydock_go.cli_runner`, which runs the built executable, so the harness-exit, unchecked-call, and
staged-value rules apply to Go criteria unchanged. `plan_repair.md` V12 replaces the call with
`cli_runner` on the same arguments and keeps every expected value. *Broken:* CsvStat `20261022.203215` asserted
usage exit `2` through `go run`, which reports every non-zero exit as `1`; a correct parser failed
two criteria on every build, and an asserted exit `1` passed whatever the program did.

`2026-10-18` · Python and Go support DATABASE.md persistence. Stack validation requires exactly one language and permits at most one database engine; other exclusive foundations retain their constraints. Cost when broken: the selected stack and generated runtime disagree.

`2026-10-22` · `VERIFICATION.md` is a standard release-verification Blueprint filename, accepted by naming validation. Cost when broken: generated release gates produce spurious naming warnings.

`2026-10-24` · **Go CLI mechanics are checked before plan artifacts are written.** The
artifact repair gate and `plan verify` share `go-run` and `go-cli-args` checks. Go client calls
pass separate strings or an unpacked sequence; direct list/tuple arguments to an imported
`drydock_go.cli_runner` are refused. `plan repair` applies both checks before retaining a
criterion and includes the client signature and examples in its prompt. One Python fence
surrounding the complete returned proof is removed only when the resulting criterion parses and
compiles; embedded fences and text outside that wrapper remain unchanged. Every assertion is
preserved by fence normalization. *Broken:* DupFind `20261024.065948` emitted four `go run`
criteria, then four fenced repairs containing eight invalid list arguments.

`2026-10-24` · **A Go package path is never a subprocess executable.** The shared
`go_cli_defect` gate, for a Target selecting `go.md`, rejects direct `cmd/<name>` and `./cmd/<name>` launches as
`go-package-launch` during artifact repair, plan verification, and repair retention, including
literal argv bindings, subprocess aliases, and shell command strings. Build/test commands may
still name the package as an argument. `plan repair` uses `drydock_go.cli_runner` while preserving
arguments and assertions. Cost when broken: DupFind `20261024.073506` reaches build with five
criteria that execute a directory and raise `PermissionError`.

`2026-10-24` · **A store-isolation repair receives the selected fixtures.** When a batch holds an
`acceptance-store` defect, `plan repair` adds the `## Foundation Contract` section of each Rigging
file the Technology Stack selects, and `plan_repair.md` V17 replaces the process launch with that
contract's in-process fixture (`cli_runner` from its `fixture_source`, or `web_client()`) on the
same arguments, keeping every store read and expected value. Other defect kinds receive no
contracts. *Broken:* FxRates `20261024.183153` `load-rejected-file-is-atomic` ran `./fxrates load`
beside `db_session()` reads; repair, never told `from cli.testing import cli_runner`, answered
`REPAIR_IMPOSSIBLE` and the Manifest stayed `draft`.

`2026-10-24` · **Declared structured CLI output is observable state.** Planning parses CSV/JSON
stdout with the format's standard parser and compares columns, rows, values, ordering, filtering,
and empty results against declared contracts and fixture inputs. Printing output and asserting
only exit zero does not verify output behavior. Diagnostic text and runner tallies remain outside
the oracle. Cost when broken: output criteria accept any successful command with arbitrary CSV.

### Mechanism

0. **Preflight** — refuse on blockers or missing persistence Rigging; capture questionnaire
   decisions; create `PLAN_COMPASS.md` and `EXCLUDE_FILES`; conform reusable imported specs with
   empty acceptance unless `--no-conform`.
1. **Stage 1** — freeze `TOPOLOGY.md` after coverage and graph repair.
2. **Seed** `DATABASE.md` from Rigging plus `sources/DATABASE.md`; the seed is context for its
   own batch, not an accepted artifact.
3. **Stage 2** — author Blueprints in batches of 5 against an Accepted / Current / Deferred /
   Defective ledger. `DATABASE.md` is the first batch, accepted only when it parses and preserves
   the source schema, then frozen
   and supplied to later batches as `DATABASE_compact.md`. Accepted artifacts freeze.
4. **Normalize** — deterministic fixes in order: unterminated and fused AC blocks, access values,
   owners, database interfaces, standalone imports, factory bindings, foundation imports,
   published clients (see [foundations](../topics/foundations.md)). Each is taken only when
   unambiguous; anything else is left for step 8.
5. **Grade and repair** — weak criteria → warning and `material` decision; malformed criteria and
   database defects → artifact repair by defect kind.
6. **Integrity** — refuse only what makes the plan unbuildable.
7. **Write** — Blueprints, `DECISIONS.json`, `MANIFEST.md` with computed blocks and preserved
   provenance, lineage.
8. **Gate** — `plan verify`; clean → `approved`, exit `0`; else `draft`/`unbuildable`, exit `1`.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Plan written: Manifest `approved` when `plan verify` is clean, else `draft` with sub-state `unbuildable` and the verify report printed. `plan verify`: no defects. |
| `1` | No plan written: unrepaired `DatabaseDefect` or any operational failure. `plan verify`: defects found. `plan repair`: post-repair verification not clean. |
| `2` | Usage error, a declared conflict confirmed by its challenge, or a Stage 2 product block standing after the retry allowance (`PlanDeferredResult`): `ERRORS.md` records it and `PLAN CREATED` is recorded failed with detail `plan deferred`. |

Every run records the `PLAN CREATED` (or `PLAN REPAIRED`) rung in project status, pass or fail.
A failing `plan verify` condemns the standing plan rung without voiding anything.

### Spec divergence

- The approved-stack precondition and shared type-count policy are implemented here; the master specification is unchanged.

- The specification's syntax omits `verify`, `repair`, `--override`, `--continue-attempts`, and
  `--lineage-model`.
- The specification lists only Blueprints and `MANIFEST.md` as outputs. Plan also writes
  `TOPOLOGY.md`, `DECISIONS.json`, `PLAN_COMPASS.md` and `EXCLUDE_FILES` (when absent), source
  lineage, and `ERRORS.md` on failure.
- The specification does not state that an unbuildable plan exits `1` with its artifacts written,
  or that a confirmed conflict exits `2`.

## Decisions

-

## Questions

- `2026-10-24` · **Fenced criteria outside the plan gate.** `e4a2aad` rejects `fenced-criteria`
  only in plan's in-plan gate. Extending it to `plan verify` and Build fails 161 fenced test
  fixtures (about 15 test files). Should those fixtures migrate to `=== AC` blocks so verify and
  Build reject the fenced form too?

- `2026-10-23` · **Joins.** The surface has no read across tables. Options: (a) Drydock derives a
  read-only join from a declared `REFERENCES` edge — `positions.rate_id → rates.id` — named in the
  pattern (`| Join | rates |`) with Output fields from both tables; (b) builders compose `get` by
  foreign key. (a) keeps SQL inside the package and is the recommendation; it needs an Output
  naming rule for colliding column names.

1. **Compact scope** — does the applied registry and compact substitution rule cover only `stack:`
   files, or also `rules:` and `context:` files?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or
   both? (Lean: block + surface findings; PO decides whether to re-analyze or fix the spec.)
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Zone D review** — dependent and deferred. `conform_specs` is unreviewed and may rewrite
   authored content. Determine whether it stays, and what its firing rate says about Zone B, only
   after its dependency and actual behavior are understood. No implementation decision is made.
5. **Contract-sensitive downstream invalidation** — determine whether a dependent story becomes
   dirty from a change to the upstream surface it actually consumes. Do not propagate dirty state
   merely because any upstream specification byte or story changed. The likely discriminator is a
   changed consumed contract or compact projection. Until this is designed, replanning resets the
   changed story only and leaves previously verified dependents unchanged.

*Closed 2026-08-01:* `ac` as node or field (§Programmatic Acceptance is not a node); deterministic
and model phase grouping (§Plan command workflow); TDD phase placement (§Content and acceptance are
authored together). *Dropped:* the Marina stopping condition — it was a property of the plan
boundary being rewritten. *Removed:* the Compass setup verb — `BUILD_PLAN_COMPASS.md` does not
exist.


## Actions

- `2026-10-25` · FxRates `20261025.184822`: local regressions cover bare criterion closes,
  mixed-case and malformed operation headings, missing primary keys, and duplicate operations.
  Parser and retry-diagnostic fixes await Ed's later UAT evidence; provider authoring defects
  remain recorded separately in `design/skills/ddk-uat.md`. Close on clean affected-stage evidence.

- `2026-10-24` · CsvStat `20261025.011759`: local fixes address the five diagnosis ledger
  findings; Ed must verify a fresh run with valid CSV fixtures, post-build native checks,
  complete actionable repair feedback, visible planning warnings, and accurate receipt counts.
  Published evidence is unchanged; close on later clean stage evidence.

- `2026-10-24` · CommonMark `20261024.233753`: bounded literal-abspath resolution and
  unresolved-argument repair routing are verified locally in `test_acceptance.py` and
  `test_plan_repair.py`; Ed's later run must pass all scoped probes without the same failure.
  The earlier selector/JSON/runner-context defects are fixed in this run; delimiter generation
  remains open in `design/skills/ddk-uat.md`.

- `2026-10-24` · `5e9962e` implements Ed's final-draft update policy and exact parser-defect
  feedback for CsvStat `20261024.221659`; the matching ledger rows are `unverified` pending a
  later live run. Local proof: the 788-test regression run includes complete duplicates,
  invalid-first/corrected-last content, truncated final updates, and named retry feedback.
  Closes when Ed's later planning evidence uses final updates without losing unrelated files.


- `2026-10-24` · `1fd07d0` and `e4a2aad` are `unverified` in `design/skills/ddk-uat.md`. The next
  DupFind run must show no `unchecked-call` on SizeFilter or UnreadableFiles and no fenced
  criteria reaching `plan verify`. If artifact repair still writes fences, fix
  `_artifact_repair_assembly` (ledger row open) next.

- `2026-10-24` · A story before the DATABASE block may still declare `provides: persistence.*` (FxRates `20261024.073528` foundation `provides: persistence.open_database`), which tells its builder to deliver the generated package. `plan verify` does not check `provides:`; a MANIFEST.md defect has no repair route in `plan repair`, so the check belongs where topology assigns `provides:`.

- `2026-10-22` · *Closed locally:* optional adapter output-format cleanup is wired into planning calls;
  `OutputContract.forbid_outside_text` is enforced. Existing body validators remain authoritative. The proposed scope and test cases are persisted in
  [planner_step_validation.md](../topics/planner_step_validation.md#output-shape-follow-up--2026-10-22).

- `2026-10-22` · Implementation is committed in `48764ad`; 385 focused regressions pass.
  Validate the complete live plan command from saved inputs, then verify and build separately.
  Live execution is deferred: Ed instructed "do not transmit" on 2026-10-22. Do not send
  the saved inputs or retry the live sequence. Resume from
  [planner_step_validation.md](../topics/planner_step_validation.md), which records the
  conversation, implementation, evidence paths, and continuation checklist.

- `2026-10-21` · *Closed 2026-10-21:* the Stage 2 output contract is consistent. `DATABASE.md`
  is a named Current-batch member authored in one step, in full, then frozen; no batch emits
  additions. Tests cover the database batch, its refusal and retry, the seed merge, compact
  injection, and refusal of a later change. The `42252b1` early rejection is preserved.

- `2026-10-22` · The proposed single-batch live trial is superseded by command-level validation
  above. Keep the existing database compact; assess further context reduction from live evidence
  before changing which source requirements and contracts the planner receives.

- `2026-10-20` · Ed prefers declared expected exits to reading them from harness lines. If the
  `harness-exit` heuristic misses or misreads a harness, replace it with an explicit declaration
  (for example, an exit table the source names) rather than widening the line parser.

- `2026-10-21` · The Stage 2 stall block truncates the missing list (`… N more lines
  truncated`) (`planning_session.py`, `plan generation stalled`). *Partly closed 2026-10-22:* the
  record now names the last rejection and any standing blocked Blueprints.

## Working Notes

-
