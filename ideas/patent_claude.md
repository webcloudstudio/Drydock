# Drydock — Patentable Subject Matter

**Status:** working analysis, not legal advice. Prepared for a patent-counsel intake conversation.
**Date:** 2026-08-24
**Scope:** mechanisms implemented in this repository as of `dd0f062`.

---

## 0. Read This First — Facts That Bound Everything Below

**Publishing code is publishing the invention.** The test in every jurisdiction is whether the
subject matter was *made available to the public*, not whether it was described, documented, or
read. Source code is a written description under EPC Art. 54(2) and a printed publication under
35 U.S.C. §102(a)(1). It is also the most enabling form of disclosure there is — it executes, so
the enablement requirement of T 206/83 is satisfied by construction, and no examiner has to
speculate about whether a skilled person could carry the teaching out. Nobody needs to have read
it; datable public accessibility is sufficient, and a GitHub commit and a PyPI release are both
datable to the second. **"We shipped the mechanism but never wrote it up" is not a defense, and
is the weaker position rather than the stronger one.** It is also, for this repository, factually
untrue: the wheel ships plain-text Python with every docstring intact, and those docstrings state
the design rationale in prose an examiner can read directly.

**Bar dates run per mechanism, from that mechanism's own first public commit** — not from the
first release. This is the useful form of the question and it materially helps:

| Mechanism | First public commit | First release | US bar |
|---|---|---|---|
| Compaction, plan graph, compass hierarchy (pre-July core) | ≤ 2026-07-08 | v0.1.1, 2026-07-08 | 2027-07-08 |
| Repair loop, repairable/terminal classification | 2026-07-23 | v0.1.5, 2026-07-29 | 2027-07-23 |
| Monotonic non-regression progress | 2026-07-28 | v0.1.5, 2026-07-29 | 2027-07-28 |
| Bounded child execution, configurable stall limit | 2026-08-15 | v0.2.0, 2026-08-23 | 2027-08-15 |

The earliest bar governs the filing, because one provisional must cover everything: **2027-07-08.**

| Jurisdiction | Grace period | Consequence for the pre-July core |
|---|---|---|
| United States | 12 months, §102(b)(1) | Alive until 2027-07-08 |
| Japan | 12 months, Art. 30(2) — procedural statement required at filing | Alive until 2027-07-08 |
| Korea | 12 months, Art. 30 — must be claimed | Alive until 2027-07-08 |
| Australia, Canada | 12 months | Alive until 2027-07-08 |
| EPO, UK | None applicable (Art. 55 covers abuse and official exhibitions only) | **Barred** |
| China | 6 months, narrow grounds only; a voluntary release does not qualify | **Barred** |
| India | Narrow exhibition/learned-society grounds only | Effectively barred |

Post-July mechanisms retain the same grace-period map measured from their own commit dates, so
Europe and China are barred for those too. **File one US provisional covering the whole system,
immediately**, and instruct counsel to preserve the JP/KR/AU/CA route via PCT if foreign rights
matter. A provisional is cheap, needs no claims, and converts within twelve months.

**The one argument that survives, and its limits.** Novelty destruction requires the claimed
subject matter to be *directly and unambiguously derivable* from the disclosure. A claim
limitation genuinely absent from the published code is therefore not anticipated by it — for
example, a limitation reciting operator-configurable budgets against a version that hardcoded
them. This is a limitation-by-limitation salvage operation yielding narrow claims, not a defense
of the invention as a whole, and EPC Art. 56 closes most of what it opens: an obvious modification
of published code is unpatentable even where it is not literally disclosed. Do not build a
strategy on it.

**Unverified fact that moves every date above.** I cannot determine from the repository when
`github.com/webcloudstudio/Drydock` became publicly visible. If it was private until some date
after a given commit, that commit's disclosure date is the later of the push and the
visibility change, and the PyPI release is then the operative disclosure for anything shipped in
a wheel. **Establish the repository's public-visibility date and give it to counsel.** Everything
in the tables above assumes the repository was public and contemporaneously pushed.

**MIT licensing does not forfeit patent rights.** MIT grants copyright permissions only and
contains no patent grant or estoppel clause (unlike Apache-2.0 §3). Existing users acquire no
license by implication beyond what their use already established. Note the converse: had Drydock
shipped under Apache-2.0, every contributor and user would hold a royalty-free patent license and
this exercise would be largely pointless. Do not relicense to Apache-2.0 before filing.

**§101 posture.** Every claim below is drafted against *Alice*. The pattern that survives is a
**specific technical control mechanism producing a determinate machine state**, never "use an LLM
to write software." The differentiator throughout is that Drydock's inventive matter is
*deterministic logic constraining a nondeterministic generator* — bounded loops, authorship-derived
authority, static decidability tests, graph verification. That framing is the strongest §101
argument available and it is the honest description of the system. Draft every independent claim so
that the novelty resides in the deterministic component, with the model as a black-box input.

**Scoring key.** Value 1–10 = commercial and defensive worth. Difficulty 1–10 = combined
prosecution risk (prior art, §101, claim-drafting) and enforcement difficulty (detectability of
infringement). Priority = the order to spend money in.

---

## 1. Provenance-Derived Acceptance Authority

**Value 9 · Difficulty 4 · Priority 1**

Implemented in `src/drydock/acceptance_contract.py`, `story_guidance.py`, `acceptance.py`
(`retyped_expectations`, `binding`), `proof_integrity.py`, `manifest.py` (state vocabulary).

This is the deepest first-principles result in the product and it is the one to lead with. The
observation is that when a generative model authors the implementation, the acceptance criterion,
the input, and the expected output in a single call, a failing criterion carries no recoverable
information about whether the criterion or the product is at fault, because both descend from one
author holding one set of assumptions. No amount of textual analysis recovers it. Drydock therefore
does not try: it derives verification authority from **authorship provenance**, a property external
to the artifact's content. Criteria whose expected values the model could not have invented — an
oracle command supplied by the human owner, a status code, a value read back from the input the
criterion itself supplied — are permitted to close a work item as `closed/verified`; criteria the
model authored close it only as `closed/implemented`, a syntactically distinct state that
propagates through every downstream report. The authorship test is itself deterministic and
decidable: `retyped_expectations` performs a static analysis over the criterion's source and
returns any expected value the author *re-typed by hand* rather than bound to an input, and a
criterion carrying one is marked non-binding — graded and reported, never charged against the
build. The complementary analyzer `proof_integrity.analyze_proof` demotes proofs with no effective
failure path to "no proof," and does so conservatively on the stated asymmetry that withholding
credit on a wrong guess costs a PASS while predicting failure on a wrong guess fails a correct
build.

> **Independent claim sketch.** A method of verifying machine-generated software, comprising:
> receiving a plurality of acceptance criteria each associated with a provenance attribute
> indicating whether the criterion was authored by the same generative process that authored the
> implementation under test; performing a static analysis on each criterion to determine whether
> each expected value asserted therein is derived from an input supplied by the criterion or is a
> re-typed literal; assigning to each criterion a binding attribute responsive to said analysis;
> executing the criteria; and assigning to the work item a first terminal state only when at least
> one criterion of external provenance passes, and a second, distinct terminal state otherwise,
> wherein the second state is not accepted as verification by a downstream release gate.

**Why it holds.** Prior art in test generation (EvoSuite, Diffblue, and the 2023–2025 LLM
test-generation literature) is concerned with *producing* tests and with oracle inference. It does
not, to my reading, condition the *state machine of the build* on the authorship provenance of the
oracle, nor supply a decidable static test for oracle self-authorship. §101 is comfortable: the
claim recites static analysis of source code and a determinate state transition.

**Enforcement.** Highly detectable. Any competitor distinguishing "verified" from "implemented" on
oracle provenance reads on this. Draft dependents covering: the whitelist formulation of legal
expected values; vacuity demotion; the `--override` waiver ledger and ungoverned stamp
(`override.py`).

---

## 2. Bounded Repair Loop With Quantitative Non-Regression Progress

**Value 9 · Difficulty 4 · Priority 2**

Implemented in `src/drydock/build_run.py` — `_is_repairable`, `_quantitative_acceptance_progress`,
`AttemptRecord`, `_settle_empty_selections`, `repair_attempts` / `repair_stall_limit` configuration.

The naive retry loop re-invokes the model on any failure until a fixed attempt count is exhausted,
which spends the budget on failures no further pass can address and terminates work that was
converging. Drydock's loop is governed by two orthogonal deterministic predicates. The first
partitions failure classifications into **repairable** and **terminal** on a principled criterion:
a failure is repairable exactly when the build tree holds partial work and the failing gate names
what remains — a red governed gate is therefore the *most* repairable signal in the system, while a
context-limit, provider error, dependency-gate rejection, staged-asset tamper, or sandbox
unavailability is terminal and never consumes a pass. The second measures progress
**quantitatively rather than boolean**: each attempt records per-criterion case tallies
`(criterion_id, passed, total)`, and a pass counts as progress only when the comparable criterion
set is identical, no criterion regresses, and at least one improves. Consecutive non-progressing
passes are counted against a stall limit independent of the attempt budget, so a loop that is
grinding stops without waiting for the budget to drain, and a loop that is moving from 40/512 cases
to 300/512 continues even though every criterion is still boolean-red. Two further elements belong
in the same claim family: an explicit escape token (`AC_BROKEN:`) by which the agent declares a
named criterion unsatisfiable, terminating the loop on a contract rather than on prose inference;
and zero-selection settlement, which demotes a criterion selecting no cases to UNVERIFIED rather
than letting it read as a false pass.

> **Independent claim sketch.** A method of iteratively repairing machine-generated code,
> comprising: executing a set of verification criteria and recording, for each, a count of passing
> sub-cases and a count of total sub-cases; classifying a failure into a repairable class or a
> terminal class according to whether the failure identifies remaining work within a persisted
> build state; responsive to the repairable classification, invoking a further generative pass
> bounded by a first budget; determining progress between consecutive passes by comparing recorded
> sub-case counts, wherein progress is determined only if the criterion sets are identical, no
> criterion's passing count decreases, and at least one increases; and terminating the iteration
> responsive to either exhaustion of the first budget or a count of consecutive non-progressing
> passes reaching a second budget independent of the first.

**Why it holds.** Automated program repair prior art (GenProg, Angelix, and LLM-APR work 2023–2025)
uses test-pass-count fitness, so the *idea* of quantitative fitness is old. The novelty to press is
the conjunction: failure-class-gated budget consumption, dual independent budgets with a stall
limit distinct from the attempt limit, and the strict non-regression-plus-improvement predicate
over a set-identity check that defeats the criterion-set-drift failure mode. Claim the conjunction,
not the fitness function.

---

## 3. Graph-Position-Dependent Context Compression

**Value 9 · Difficulty 6 · Priority 3**

Implemented in `src/drydock/rigging_compact.py` (role-typed derivation), `build.py`
(`assemble_step`, first-use tracking, `compact_stack`), `manifest.py` (applied registry),
`prompt_assembly.py` (per-part byte and token accounting, `PROMPT_WARN_TOKENS` ceiling).

Drydock's compression is not summarization and is not retrieval. Each governed input document is
compacted once, offline, through a **role-selected extraction contract** chosen by the document's
identity — contracts, architecture, or database API — where each role names precisely the surface a
consuming build step must satisfy and names what to discard; a document with no such surface is
classified as having no technical surface and is skipped rather than degraded. The second half is
the part I believe is genuinely novel: **which version a given build step receives is a function of
that step's position in the dependency graph.** The first step in build order to consume a given
document receives the full text, because that step is the one that must implement it; every
subsequent consumer receives the compact derivative, because those steps must only call it
correctly. First-use is tracked against the manifest's applied registry so the decision is stable
and replayable across resumed runs rather than recomputed by forward scan. Cost is accounted per
prompt part in the same token unit the ceiling is expressed in, and the console and the builder
sum the identical assembly so displayed cost and executed cost cannot diverge. Compass documents
are structurally exempt: they are human direction, carry no extractable contract, and are injected
whole every time.

> **Independent claim sketch.** A method of assembling a bounded context for a generative build
> step, comprising: deriving, for each of a plurality of specification documents, a compact
> derivative by applying an extraction contract selected according to a role attribute of the
> document, the extraction contract specifying a consumer-facing surface to preserve and an
> implementation surface to discard; determining a build order over a dependency graph of work
> items; and, for each work item in said order, including the full document for a document not
> previously consumed by an earlier work item in said order and including the compact derivative
> otherwise; and recording said determination in a persisted registry such that a resumed
> execution reproduces the same selection.

**Why it holds — and the risk.** This is the most commercially valuable claim and the one with the
worst prior-art neighbourhood. Context compression, hierarchical summarization, and retrieval
augmentation are heavily published and heavily patented (2023–2026). Do not claim compression.
Claim the **graph-position selection rule** — full to the implementer, compact to the caller,
decided by topological first-use and persisted for replay. I find no prior art on that specific
rule and it is the element a competitor would have to copy to get the benefit. Expect the examiner
to cite summarization art; the graph-position limitation is the distinguishing feature and must be
in the independent claim, not a dependent.

---

## 4. Stage-Scoped Guidance With a Machine-Owned Region in a Human-Editable Document

**Value 8 · Difficulty 3 · Priority 4**

Implemented in `src/drydock/compass_sources.py` (`COMPASS.md`, `PLAN_COMPASS.md`,
`ANALYZE_COMPASS.md`), `compass_guardrail.py` (marker-delimited managed section, strip/re-apply),
`analyze.py:185`, `planning_session.py:1393`.

Two separable inventions sharing one artifact, and both are clean. The first is the **hierarchy of
scoped direction**: a project-level constitution injected into every stage, plus per-stage guidance
files injected only into the stage that owns them, created once with a default prompt, never
overwritten, and never written by a model. This gives the operator a place to correct a specific
stage's behaviour without polluting the context of every other stage, and — critically — a stage's
accumulated corrections persist as a project asset across runs. The second is sharper and narrower:
a **machine-owned region inside an otherwise human- and model-editable document**, delimited by
sentinel comment markers, re-rendered deterministically at each run from resolved absolute paths so
its write-authorization statement can never go stale, *stripped before the document is handed to a
model for prose authoring and re-applied afterward*, with legacy markerless sections detected by
heading and replaced so duplicates cannot accumulate. That strip-and-reapply cycle is the whole
solution to a real problem — how to keep a security-relevant authorization statement authoritative
in a file you also want a model to edit — and I have not seen it claimed.

> **Independent claim sketch (second invention).** A method of maintaining machine-authoritative
> content within an operator-editable configuration document, comprising: rendering an
> authorization region delimited by start and end sentinels, the region enumerating resolved
> absolute filesystem paths within which a generative agent is authorized to write and enumerating
> protected paths within which it is not; prior to submitting the document to a generative process
> for modification, removing the delimited region; following said modification, re-rendering and
> re-inserting the region from current resolved paths; and detecting an undelimited prior instance
> of said region by a heading match and removing it, whereby exactly one authorization region
> persists.

**Enforcement.** Both are visible in any competitor's file format. Difficulty is low, value is
solid, cost is low. This is a good early continuation.

---

## 5. Asymmetric-Evidence Release Gate as a Replayable Pure Fold

**Value 8 · Difficulty 4 · Priority 5**

Implemented in `src/drydock/gate_policy.py`, consumed by `score.py` / `score_report.py`.

The scoring stage's inventive matter is an **evidentiary asymmetry applied to a model's judgments**.
A criterion may be graded MET by inference, because a competent reader can conclude a capability
exists from surrounding evidence; but NOT MET requires the grader to cite what it actually
observed, including citing the absence it found where something was required. A NOT MET citing
nothing is not a demonstration of failure — it is a demonstration that the grader could not
observe — and is therefore reclassified to MANUAL rather than being allowed to fail the product.
Deterministic evidence is input to the fold with precedence but is not an override selector: a
demonstrated failure bound to a criterion pins NOT MET unarguably, a command executed green at
grading time pins MET, and otherwise the grader's verdict stands. The three-verdict vocabulary
eliminates a waiting state on principle: an unsettleable criterion is MANUAL and terminal, an
unbuilt criterion is NOT MET, and conflating those two is precisely how finished projects came to
be reported as open. Execution error is computed before any product verdict, so a harness that
could not run claims nothing about the product. The whole fold is a **pure function of recorded
evidence with no filesystem, model, or network access**, which means a change to the release policy
can be replayed over the entire corpus of historical runs rather than validated against one fresh
run — a testable, technical, and claimable property.

> **Independent claim sketch.** A method of computing a release verdict, comprising: receiving,
> for each of a plurality of acceptance criteria, a machine-generated verdict and a set of cited
> evidence artifacts; reclassifying a negative verdict citing no evidence artifact to a
> human-determination verdict; overriding a verdict responsive to a deterministic execution result
> bound to the same criterion; folding the resulting verdicts into a terminal run verdict wherein
> human-determination verdicts are non-blocking and are separately attested; and computing an
> execution-error verdict prior to and in preference to any product verdict; the method being
> performed without filesystem or network access such that it is replayable over previously
> recorded evidence.

---

## 6. Truncation-Resilient Generation With a Declared-Count Ruler

**Value 7 · Difficulty 4 · Priority 6**

Implemented in `src/drydock/plan_score.py`, `plan_shape.py` (`OutputContract.leading`),
`planning_session.py` (bounded continuation batches).

A large generation fails when the output budget runs out mid-emission, and the failure is silent:
the response looks like a response. Drydock's answer is to require the generator to emit a
**count-bearing declaration first** — the topology, naming every artifact that must exist — so that
the census of what should exist structurally outlives the bodies that do not. Completion is then a
deterministic scalar computed from the declaration and the artifacts actually returned, and that
one scalar drives three consumers: console progress, the inverse rendered into the continuation
prompt as what remains missing, and the stall or failure message. Progress is measured on
**accepted count, strictly increasing**, never on a ratio against a declared total, because a
pending item that legitimately splits moves the denominator and breaks a ratio while leaving a
monotonic accepted count correct with no special case. Acceptance is irreversible and therefore
narrow: an artifact is accepted only if it was declared, is non-empty, and carries delimiter
evidence that it was not cut mid-emission.

> **Independent claim sketch.** A method of obtaining a complete multi-artifact generation from a
> length-bounded generative process, comprising: constraining the process to emit, prior to any
> artifact body, a declaration enumerating the identifiers of every artifact to be produced;
> accepting an emitted artifact only if its identifier appears in said declaration, its body is
> non-empty, and it carries a terminal delimiter indicating uninterrupted emission; computing a
> completion score as a count of accepted artifacts; issuing a continuation request whose content
> is derived from the complement of the accepted set with respect to the declaration; and
> terminating on either completion or a failure of the accepted count to strictly increase across
> consecutive continuation requests.

---

## 7. Authorship/Verification Split in Plan Construction

**Value 7 · Difficulty 5 · Priority 7**

Implemented in `src/drydock/plan_graph.py` (deterministic core), `plan_topology.py` (declaration
parsing and projection), `manifest.py` (serialization).

Ed's framing — "I cannot patent the decomposition methodology, but I can patent a simple version of
the build graph" — is correct, and the patentable line is exactly the division of labour. The model
declares only what requires judgment: what each work item is, what it provides, what it consumes,
what it depends on, its phase, and its acceptance. It emits that as a **transient declaration**, and
it never sorts, never groups, never assigns a position, and never checks its own consistency.
Deterministic code then verifies the declared graph for internal consistency, refuses it with a
precise defect message on contradiction, computes topological order and work grouping, assigns
stack modes, applies blocking, and serializes the executable manifest. The governing discriminator
for where each fact lives is stated and implemented: **does the fact describe the artifact or the
schedule?** Relationships describe the artifact and live in the specification header; type, phase,
and programmatic acceptance describe the schedule and live in the manifest. The consequence worth
claiming is that a model contradiction becomes a deterministic defect at a named location instead
of an unbuildable plan discovered at build time.

> **Independent claim sketch.** A method of constructing an executable build graph, comprising:
> obtaining from a generative process a transient declaration comprising, for each work item, a
> provided-interface set, a consumed-interface set, a dependency set, and a phase, said declaration
> being unordered and unpositioned; verifying by deterministic analysis that the declared
> consumed-interface sets are satisfied by declared provided-interface sets, that the dependency
> relation is acyclic, and that phase assignments are consistent with said relation; rejecting the
> declaration with a located defect identifier upon failure of said verification; and, upon
> success, computing a topological execution order and a grouping of work items and serializing the
> result as an executable manifest, wherein the generative process performs no ordering.

**Risk.** Build-graph and dependency-ordering art is ancient (make, Bazel, workflow engines). The
independent claim must be anchored on *declaration-by-generative-process plus deterministic refusal*
— the acyclicity check alone is unpatentable.

---

## 8. Append-Only Change Management Over Frozen Specifications

**Value 7 · Difficulty 6 · Priority 8**

Implemented in `src/drydock/change_ticket.py`, `lineage.py`, `lineage_route.py`, `refit.py`,
`lineage_impact.py`.

Specifications freeze at plan time and the graph thereafter only grows. A change arrives as a
**typed change ticket** that becomes a new work item whose `implements:` names the ticket, so the
effective specification of any item is its frozen original plus its ticket chain — no edit, no
rewrite, nothing to reconcile. The type is the load-bearing element: an `additive` ticket
supersedes nothing, while an `amending` ticket supersedes only the sections it names and those
sections are validated against the parent, so a single added sentence cannot silently overturn
every assertion already proven about that specification. Underneath sits a lineage record whose
unit is a **source version** — a `(content hash, commit)` pair — with no analysis performed at
import time; a version stays pending until a planning or refit pass consumes it, and consumption
appends the requirements found and the work items they became without ever rewriting an earlier
version. Requirements point at graph item identifiers and never at specification files, because the
items already carry the reverse mapping and a second copy can disagree with the first.

> **Independent claim sketch.** A method of propagating a specification change into a build graph
> without modifying frozen specifications, comprising: recording each imported source as a version
> identified by a content hash and a revision identifier; deferring semantic analysis of said
> version until consumption by a planning pass; upon consumption, appending to the version record
> the requirements identified and the work-item identifiers created therefrom; generating for a
> subsequent change a ticket record carrying a scope attribute selected from an additive scope
> that supersedes no prior assertion and an amending scope that supersedes only enumerated
> sections of a named parent specification; validating that each enumerated section exists in said
> parent; and appending a new work item whose effective specification is the frozen parent
> composed with its ordered ticket chain.

**Risk.** Requirements-traceability prior art is deep (DOORS, ReqIF, and a long patent tail).
Novelty must rest on the frozen-specification-plus-ticket-chain composition and on deferred
semantic analysis of a hash-identified source version, not on traceability as such.

---

## 9. Baseline-Differential Acceptance (PREPASSED)

**Value 6 · Difficulty 3 · Priority 9**

Implemented in `src/drydock/build_run.py` (baseline evaluation, `record_prepassed_acceptance`),
`acceptance.py`, `standard_artifacts.py` (`~ PREPASSED`).

Small, sharp, and cheap to claim. A criterion that is green *before* its work item builds has not
been shown to be satisfied by that item's work. Drydock evaluates each item's criteria against the
pre-build baseline, records the identifiers that were already green, and reports them under a third
vocabulary term distinct from both PASS and FAIL — weaker than PASS because attribution is absent,
not a defect because a criterion measuring a pre-existing deliverable reads identically. The
recorded set persists as evidence and the operator adjudicates. This is a genuine
attribution-of-causation mechanism and I see no equivalent in the LLM-build literature.

> **Independent claim sketch.** A method of attributing verification results to generated work,
> comprising: executing a work item's acceptance criteria against a build state captured prior to
> executing said work item; recording identifiers of criteria passing at said prior state;
> executing the work item; re-executing the criteria; and reporting a criterion passing at both
> states under a verdict distinct from a criterion passing only at the later state, whereby a
> passing result not attributable to the work item is not counted as verification thereof.

Pair with the regression sweep in the same family: a criterion proven by an earlier item that a
later item breaks is classified repairable *by construction*, since working code for it demonstrably
existed in the same tree one item earlier.

---

## 10. Dependency Legitimacy Gate

**Value 6 · Difficulty 6 · Priority 10**

Implemented in `src/drydock/dependency_gate.py`.

Generative builders hallucinate package names, and an attacker who registers a frequently
hallucinated name owns the build ("slopsquatting"). Drydock parses the generated dependency
manifest, canonicalizes each name to the registry's rules, checks registry existence, and checks
first-publication age against a threshold, defaulting to thirty days — a package that does not
exist, or that appeared last week, fails the build. Two elements make this more than a lookup: the
failure is classified **terminal and non-repairable**, so the repair loop cannot spend passes trying
to talk the model out of it; and the age threshold targets the attack's economics rather than the
package, since the squatter must register *after* the hallucination becomes observable.

**Risk.** Slopsquatting is well documented in 2024–2026 security literature and defensive tooling
exists. Claim the integration — a package-age threshold as a terminal, budget-exempt gate inside a
generative build loop — rather than registry validation. Value is real because the feature sells
into enterprise procurement review.

---

## 11. Cross-Stage Halt Condition

**Value 5 · Difficulty 3 · Priority 11**

Implemented in `src/drydock/stop_condition.py`.

A stage reaching terminal failure records the cause at the workspace root in an operator-readable
file naming the stage, the reason, and the time. Every later stage checks the condition before
spending anything. Two design points carry the claim: it is a **stop condition, not a stop flag** —
the halting stage need not know which stages follow, and a later stage need not reconstruct an
earlier verdict from an exit code it never observed, which matters precisely because several
commands exit non-zero as ordinary state signals; and **the first declaration wins and is never
overwritten**, so the causal failure is preserved rather than replaced by the incidental downstream
failure it caused. Best filed as a dependent claim on the lifecycle application rather than alone.

---

## 12. Verifiable Deterministic Run Receipt

**Value 5 · Difficulty 7 · Priority 12**

Implemented in `src/drydock/uat_report.py`, `score_report.py`, `execution.py`, `logs/*.jsonl`.

Every command invocation and every model execution is journalled with exit code, token accounting,
prompt hash, and transcript pointer; the reporter joins the two journals and renders a
self-contained page whose verdict is computed **only** from recorded exit codes and acceptance
results, with `SHA256SUMS` over the entire run tree making the kit checkable with `sha256sum -c`.
The contract worth claiming is negative: the reporter executes no proof, calls no model, and
re-measures nothing, so a stale board is reported as stale rather than silently refreshed — a
receipt that re-measures is documenting a different moment than the run it claims to describe.
Prior art is heavy (in-toto, SLSA, CI attestation, reproducible builds); file as a dependent claim.

---

## 13. The Umbrella Lifecycle Claim

**Value 8 as a wrapper · Difficulty 8 standing alone · File it, but not alone**

Ed's instinct is right that the process as a whole is the asset, and wrong only about where the
enforceable value sits. A claim to "analyze → plan → build → score with guardrails at each stage"
standing alone will draw an *Alice* §101 rejection as an abstract organizational method implemented
on a computer, and an obviousness rejection over the entire SDLC literature. The correct
construction is an **omnibus independent claim whose limitations are the specific mechanisms above**
— stage-scoped guidance injection (§4), a graph-position context selection rule (§3), a
provenance-derived state vocabulary (§1), a dual-budget non-regression repair loop (§2), and an
asymmetric-evidence release fold (§5) — so that the pipeline is claimed *as constituted by* those
deterministic mechanisms and not as a workflow. Drafted that way the umbrella is the broadest
enforceable claim in the portfolio, because a competitor building the same pipeline with the same
guardrails infringes it without needing to copy any single mechanism verbatim. Drafted the other
way it is worthless. Say this to counsel explicitly.

---

## Not Worth Filing

| Mechanism | Reason |
|---|---|
| Bounded child execution (`child_sandbox.py`) | `ulimit`, cgroups, and process-group kill are decades old. Keep as a dependent limitation only — the one non-obvious wrinkle is classifying a resource-limit failure as a product defect rather than a harness failure. |
| Compact-derivative file naming, manifest table formats, marker syntax | Expression, not invention. Copyright and trade dress already cover them. |
| Subscription-CLI adapter (`llm.py`) | Process management. The drain-grace and heartbeat handling is good engineering, not novel. |
| Blueprint front-matter schema | A data format. Unpatentable as such. |
| QuarterDeck console | UI. Consider a design patent only if the interface becomes a market identifier. |
| Nautical vocabulary | Trademark territory, not patent. **Separately: file word marks on DRYDOCK, QUARTERDECK, SEA TRIALS, RIGGING, BLUEPRINT-as-used, in class 9 and 42.** Cheap, immediate, and the naming system is a real commercial asset. |

---

## Recommended Filing Sequence

1. **Now, and in any case before 2027-07-08.** One US provisional, drafted broadly, covering §§1–13. A provisional
   requires no claims and its cost is dominated by the time spent writing a complete specification.
   Include every mechanism in this document, including the ones scored low — a provisional's
   disclosure is free breadth, and matter omitted here cannot be claimed in the non-provisional.
2. **Immediately after filing.** Add `Patent Pending` to `README.md` and the package metadata. Do
   not relicense to Apache-2.0. Continue publishing freely; the provisional's priority date is
   secured and further disclosure of the same matter no longer harms the US application.
3. **Within twelve months.** Convert to one non-provisional with §1, §2, and §3 as separate
   independent claims and the umbrella of §13 as a fourth, or split into two applications if
   counsel advises against restriction risk. Expect a restriction requirement; be prepared to
   prosecute §1 first as the strongest and file divisionals on the rest.
4. **Concurrent.** Keep a dated invention notebook. The design rationale already embedded in the
   module docstrings — `acceptance_contract.py`, `gate_policy.py`, `proof_integrity.py`,
   `plan_score.py` — is unusually good evidence of conception, reduction to practice, and the
   problem-solution narrative an examiner responds to. Give counsel those files verbatim; they are
   most of a specification's background section already written.

## Open Questions for Counsel

- Confirm the per-mechanism bar dates in §0. My reading is that each mechanism's clock starts at
  its own first public commit, not at the 2026-07-08 release, which makes 2027-07-08 the binding
  date only because the pre-July core is the earliest — everything else has more room.
- Is the JP/KR/AU/CA route worth preserving, given EPO and China are already barred? If yes, the
  PCT timing has to be planned into the provisional-to-non-provisional conversion now.
- Is §3 salvageable over the 2023–2026 context-compression patent tail, or should the budget move
  to §1 and §2?
- Restriction strategy: one omnibus application with four independents, or three applications
  filed together?
