# Drydock Patent Opportunity Memo

**Purpose:** invention-capture and filing-priority memo for Drydock. This is not a patentability opinion or a freedom-to-operate opinion. It identifies claimable *technical mechanisms* visible in the repository, not the general idea of using an LLM to develop software.

**Recommendation:** file one provisional application promptly around the first three families below, with the context-assembly/compaction mechanism as the lead invention. Treat the remaining families as disclosed embodiments and continuations unless a focused prior-art search distinguishes them. Claim the deterministic data structures, state transitions, prompt-selection rules, acceptance measurements, and resource effects. Do not lead with “Agile decomposition,” “analyze → plan → build → score,” or an LLM performing a task; those are vulnerable as abstract workflow or conventional tool use.

## What Drydock has that is technically claim-shaped

Drydock is not merely a prompt sequence. It implements a computer-controlled build system in which typed specifications become a dependency graph, graph nodes become context-bounded build units, each unit is executed against deterministic acceptance gates, and failure diagnostics drive a bounded repair state machine. It further preserves a non-compressed governing intent document and permits phase-specific governing overlays. The implementation produces measurable technical effects: reduced prompt context, bounded execution cost, deterministic build ordering, earlier regression attribution, and auditable incremental rebuilds.

The strongest claims should recite an executable system and its concrete artifacts: `MANIFEST.md`/graph nodes, role-tagged context files, compact derivatives with content-hash provenance, acceptance observations, repair-state counters, and lineage records. A method claim, system claim, and non-transitory computer-readable-medium claim should be drafted for each viable family.

## Priority scorecard

Scores are relative, 10 is highest. Value combines product defensibility, commercial relevance, and breadth. Difficulty combines expected prior art, §101/abstract-idea risk, enablement burden, and claim-drafting complexity; higher means harder.

| Priority | Invention family | Value | Difficulty | Filing recommendation |
|---:|---|---:|---:|---|
| 1 | Provenance-verified, role-aware context compaction and reuse | 10 | 7 | Lead independent claim family |
| 2 | Acceptance-progress-controlled autonomous repair loop with regression gates | 10 | 8 | Lead independent claim family |
| 3 | Hierarchical, non-compressible and phase-specific governance injection | 9 | 7 | Lead independent claim family; combine selectively with 1/2 |
| 4 | Typed Manifest graph that derives atomic/grouped build units and runnable frontiers | 9 | 8 | Strong separate family; provisional disclosure now |
| 5 | Source-version lineage routing and dependency-cascade incremental rebuild | 9 | 8 | Separate family or continuation candidate |
| 6 | Specification-owned executable acceptance and pre/post-build integrity classification | 8 | 7 | Include as dependent claims and a distinct embodiment |
| 7 | Deterministic plan conformance/repair for runnable acceptance before construction | 7 | 6 | Include in provisional; search before separate filing |
| 8 | Immutable evidence receipt binding model attempts, prompts, acceptance, and changed files | 6 | 6 | Supporting claims; rarely a lead case |

## 1. Provenance-verified, role-aware context compaction and reuse

**Core invention.** A build-prompt assembler classifies input documents into semantic roles, selects full or compact representations according to role and prior use, validates each compact representation against a hash of its source, and records/reuses generated compacts across later build units. A step receives the full authoritative specification it implements, but receives a compact sibling for supporting specifications when the compact is fresh and is appropriate for that step. Certain governing documents are excluded from compaction entirely. The result is not generic summarization: it is a deterministic context-selection protocol that maintains source equivalence/provenance while reducing the token load of repeated dependency context.

**Why it matters.** This is a direct technical answer to limited-context, high-cost agent execution. It makes build cost measurable in a single derived unit (`ceil(bytes / 4)`), prevents stale summaries from silently governing a build, avoids duplicate context, and allows a later build step to consume only the exposed surface of a previously injected dependency. That is materially more specific than “compress prompts.”

**Claim nucleus.** Receive a dependency graph whose executable node names implementation and context files; assign each named file a role; for a context file, locate a compact derivative; verify a provenance digest embedded in the derivative against the current source digest; choose the compact derivative only when current and allowed by a role policy; inject the selected collection in a fixed role order; calculate the assembled cost; execute the resulting build instruction; retain a compact-result registry for subsequent nodes. Useful dependent limitations: first use gets the full file; later uses get the compact file; architecture/database support is automatically injected for feature work; a missing compact falls back to full content; a compact whose provenance mismatches is rejected/regenerated.

**Evidence to preserve.** `src/drydock/build.py` (role order, `StepAssembly`, source hash freshness, compact sibling selection, deterministic cost), `src/drydock/build_run.py` (reusable compact source registry and persistence), `tests/test_build.py` (freshness, first-use, and compass exclusions). Collect benchmarks on a representative graph: full-context tokens versus selected-context tokens, stale-compact detection rate, and outcome/acceptance parity.

## 2. Acceptance-progress-controlled autonomous repair loop with regression gates

**Core invention.** A build controller runs an agent against a selected graph unit, executes deterministic acceptance criteria after *every* attempt, converts failures into structured repair feedback, and continues only within a call budget and a progress-based stall policy. It separately re-runs previously proven criteria after each later build unit, so a regression is assigned to the last unit that changed the artifact rather than discovered only at release time. The loop distinguishes initial build, resumed repair, repairable versus terminal failures, malformed criteria, pre-existing green criteria, and accepted-but-unverified conditions.

**Why it matters.** Ordinary retry loops spend a fixed number of attempts or stop on process success. Drydock’s continuation signal is measured acceptance progress, not agent text, token usage, or exit code. Its regression gate turns a long multi-agent build into attributable incremental verification. This has a credible technical effect: bounded resource consumption and an earlier, localized detection of destructive modifications to previously verified software.

**Claim nucleus.** For an executable graph unit: obtain a baseline acceptance observation; invoke an autonomous code-modification process; snapshot resulting filesystem state; run owned acceptance and a retained set of previously passed acceptance criteria; calculate a progress metric from the deterministic observation; form the next prompt from failed criteria, regressions, agent report, and changed-file data; repeat when failure is repairable, progress has not exceeded a consecutive-stall threshold, and an attempt budget remains; otherwise commit a terminal unit state and evidence. Dependent limitations: model escalation on the final permitted attempt; resume seeded with current failure observations; policy-controlled sandbox/output limits; classification of a malformed acceptance criterion as unverified rather than as application failure.

**Evidence to preserve.** `src/drydock/build_run.py` (baseline, `proven_green`, per-attempt gates, repair feedback, stall counter and evidence); `src/drydock/config.py` (`repair_attempts`, `repair_stall_limit`); `tests/test_build_report.py` and build tests. Preserve run records showing that one failed test becomes green, a flat repair stops before burning the full budget, and a later unit’s regression gate identifies a prior deliverable it broke.

## 3. Hierarchical, non-compressible and phase-specific governance injection

**Core invention.** Drydock separates project intent/governance from technical context, designates the governance document as a role that is injected whole into every build prompt, prevents it from being compacted or duplicated through ordinary context fields, and applies distinct persistent directives at analysis and planning stages. A deterministic precedence rule resolves the stage directive, recorded human decisions, technology stack, general compass, and imported sources. The phase-specific directives can alter decomposition and ordering without allowing a low-priority source to override product governance.

**Why it matters.** This is a mechanism for enforcing operator policy across a multi-stage autonomous build pipeline. It prevents compression loss from changing a safety or product constraint and prevents an agent from receiving inconsistent governing instruction at different stages. The patentable center is the typed-policy selection and enforcement mechanism, not “a constitution file.”

**Claim nucleus.** Store a base governance artifact and stage-scoped governance artifacts; classify the base artifact as non-compressible; construct each stage request by selecting directives according to a precedence lattice; inject selected artifacts at defined locations; prohibit duplicate injection through context resolution; validate the governing artifact against the project/build identity; and reject or quarantine outputs that conflict with the selected governance. Dependent limitations: `ANALYZE_COMPASS.md` governs decomposition, `PLAN_COMPASS.md` governs blueprint scope/order, and `COMPASS.md` is injected into every build step in full.

**Evidence to preserve.** `src/drydock/compass_sources.py`, `src/drydock/compass_guardrail.py`, `src/drydock/build.py`, `prompts/analyze.md`, `prompts/plan_create.md`, and `tests/test_compass_guardrail.py`/`tests/test_build.py`. Capture a worked case where stage-specific direction changes the plan but cannot bypass base verification/guardrail clauses.

## 4. Typed Manifest graph that derives atomic/grouped build units and runnable frontiers

**Core invention.** A human-readable typed Manifest represents stories, spikes, features, acceptance nodes, dependencies, phases, state, implementation files, context, stack guidance, rules, and instructions. The executor deterministically derives a build frontier from verified dependencies, groups a feature’s internally dependent stories into one build unit when safe, splits a feature group when a child is question-blocked, and applies layer-band and work-kind constraints before prompt construction. The graph is therefore not merely a task list; it is an execution-control data structure that determines what an autonomous agent can change in one bounded invocation.

**Why it matters.** This is the simplest “build graph/manifest” family worth pursuing, as requested. The novel case is not a generic DAG or generic project-management board. The technical claim is the specific node schema plus graph-to-prompt compilation: accepted state gates the frontier, a feature can compile into an atomic multi-story build unit, and per-node role-resolved files form the executable context.

**Claim nucleus.** Persist graph nodes with typed state and file-role fields; identify pending nodes whose external dependencies are verified; group sibling implementation nodes under a feature when all outside dependencies are verified; split a group on a question-blocked child; enforce a coarse dependency band and a work-kind compatibility rule; compile the resulting atomic unit into an ordered role-based build input; after acceptance, transition only appropriate node and parent states. Dependent claims can cover automatic context insertion and inherited acceptance ownership.

**Evidence to preserve.** `src/drydock/manifest.py` (`computed_groups`, runnable frontier, reset cascade), `src/drydock/build.py` (bands/work kinds/assembly), `src/drydock/build_run.py`, `prompts/MANIFEST_CONTRACT.md`, and manifest tests. Include diagrams of one Manifest before/after grouping and a blocked-question split.

## 5. Source-version lineage routing and dependency-cascade incremental rebuild

**Core invention.** Imported source material is versioned by content hash and source-control commit. Later planning/refit converts a source delta into named requirements, maps those requirements to existing Manifest stories, records that attribution against the precise source version, and either appends a controlled graph change or refuses it when the delta cannot be seated without changing graph shape. When an applied specification changes, Drydock identifies consumer nodes and transitive dependents, resets their execution state, drops stale applied-spec provenance, and rebuilds only the resulting graph closure.

**Why it matters.** This gives specification-driven development an auditable, incremental rebuild mechanism rather than a full re-run or free-form agent interpretation. It is potentially valuable in regulated or enterprise settings because it ties a deployed behavior to a particular source version and tells an operator why a node is rebuilt.

**Claim nucleus.** On import, record a source content digest and commit identifier; on a later source version, generate a delta; route requirements in the delta to existing implementation graph nodes; reject a route that requires unapproved graph-shape change; record requirements and target nodes against the source version; detect content drift of applied specs; compute the transitive dependent closure; reset only that closure; and execute the resulting runnable frontier. Dependent limitations: source deletion is retained as a source state; compact forms are supplied for routing while canonical headings are preserved for amendment validation; backfill reconstructs lineage from source-control history.

**Evidence to preserve.** `src/drydock/lineage.py`, `src/drydock/lineage_route.py`, `src/drydock/lineage_backfill.py`, `src/drydock/refit.py`, `src/drydock/build_plan.py`, and their tests. Capture a changed-source example showing the source-version → requirement → story map and exact reset closure.

## 6. Specification-owned executable acceptance and integrity classification

**Core invention.** Each typed specification carries programmatic acceptance assertions that are extracted, validated, associated with a story, executed in a controlled target environment, and classified beyond pass/fail. Drydock detects malformed checks, pre-passed/vacuous checks, missing authorized prerequisites, and checks that become unverified; it distinguishes these conditions from a failed implementation and carries the valid failed observations into repair prompts. Project-level Sea Trials remain outside per-story acceptance, avoiding a build unit “passing” by measuring only an end-state criterion it cannot truthfully own.

**Why it matters.** The technical contribution is the schema and controller that make acceptance an executable part of specification graph compilation, rather than an unstructured test prompt. It reduces false-green builds and allows deterministic feedback to control the repair loop.

**Claim nucleus.** Parse executable assertions from a specification associated with a graph node; execute them in the target workspace; classify observation integrity separately from pass/fail; retain ownership and baseline state; prevent a project-level release criterion from being attributed to a local node; use only valid failed local observations as repair input; and record an evidence object per attempt. This is strongest as dependent matter to family 2 or 4 unless prior-art search shows a clean distinction.

**Evidence to preserve.** `src/drydock/build_run.py`, `src/drydock/validation_harness.py`, `prompts/BLUEPRINTS_CONTRACT.md`, `prompts/plan_create.md`, and score/acceptance tests.

## 7. Pre-construction plan conformance and repair of non-runnable acceptance

**Core invention.** Before autonomous implementation, a planner verifies whether each story’s acceptance criterion can execute in the proposed target environment, reports criteria that cannot run, and performs a constrained repair pass that changes the plan/specification rather than creating code to satisfy an impossible test. The resulting separation between “plan correctness” and “implementation correctness” prevents a code agent from fabricating test kits, tooling, or acceptance semantics merely to get green.

**Why it matters.** It is narrower, but it has a sensible technical distinction: acceptance readiness is verified at plan time and repair is confined to making the criterion runnable. It may be valuable as a dependent claim or a continuation around high-assurance build pipelines.

**Evidence to preserve.** `README.md` (`plan verify`, `plan repair`), `src/drydock/plan_*.py`, prompt contracts, and tests for deferred/non-runnable criteria. Confirm the exact current modules before a filing draft because the public documentation is known to lag implementation.

## 8. Evidence receipt for governed autonomous build attempts

**Core invention.** For each graph unit and repair attempt, record the exact assembled prompt identity, model/provider invocation, attempt classification, acceptance observations, changed files, resource consumption, stop reason, and final state in a linked evidence record. The receipt represents the causal path from a typed specification and governance stack to a verified/rejected artifact.

**Why it matters.** Useful commercially and as support for the other families, but logging/evidence alone is likely crowded. Keep it as a dependent limitation that establishes reproducibility and provides a hard-to-copy enterprise feature.

## Non-lead ideas: disclose, but do not build the case around them

| Idea | Reason not to lead |
|---|---|
| Analyze → plan → build → score sequence | Broad workflow/decomposition language; high abstract-idea and prior-art exposure. |
| “Use an LLM to write software” | Conventional and overbroad. |
| Agile stories/typed blueprints alone | Methodology and document format are weak without the executable graph/controller. |
| Generic retry loop | Common; only the acceptance-progress, structured-feedback, regression-gate combination is worth claiming. |
| Generic prompt compression | Common; emphasize role rules, hash freshness, first-use/reuse behavior, and graph-driven selection. |
| Graph database/task DAG alone | Common; claim the Drydock node semantics and graph-to-bounded-agent-unit compiler. |

## Filing package: what counsel needs

1. **One provisional, not eight vague ideas.** Title it around governed context-bounded autonomous software construction. Put families 1–5 in the disclosure with detailed alternatives; draft separate independent claims for 1, 2, 3, 4, and 5 only where they can stand alone.
2. **Technical figures.** Prepare: (a) graph-to-context-selection flow; (b) full/compact provenance and reuse state; (c) repair-loop state diagram; (d) governance precedence/injection pipeline; (e) source-version-to-story lineage and reset closure. Each figure should label inputs, hashes, state fields, rejection paths, and persisted evidence.
3. **Concrete examples and measurements.** For every lead family, preserve at least two executable examples from real targets. Record prompt bytes/tokens saved, graph nodes selected, acceptance score per attempt, stall decisions, regression detections, reset closures, and evidence locations. The specification should explain how the mechanism improves context capacity, processor/network invocation budget, determinism, and error localization.
4. **Inventorship record.** Create dated disclosure notes identifying every person who contributed to each claimed mechanism, including the specific contribution. Do not infer inventorship from commit authorship alone.
5. **Prior-art search matrix.** Search combinations, not labels: role-aware prompt compaction + source-hash validation; acceptance-score retry + consecutive stall threshold; graph-derived multi-story agent build units; non-compressible policy injection + phase overlays; source-version requirement-to-story lineage + graph reset closure. Search patents, published applications, papers, agent frameworks, build systems, and public GitHub repositories.
6. **Public-disclosure audit.** Identify the first public availability of the GitHub repository, PyPI releases, README claims, demonstrations, papers, videos, and target repositories for each mechanism. Preserve dated copies and commit hashes. The repository’s MIT license is a material commercialization and claim-strategy issue for counsel; do not assume a later patent changes rights already granted under that license.

## Legal and timing constraints

This memo is an engineering inventory, not legal advice. U.S. filings are first-inventor-to-file; the USPTO states that public disclosure more than one year before the effective filing date can bar a U.S. application, and many non-U.S. jurisdictions do not preserve rights after pre-filing public disclosure. A provisional can establish a filing date only for subject matter adequately described in the application. See the USPTO’s [first-inventor-to-file guidance](https://www.uspto.gov/patents/laws/america-invents-act-aia/patents-examination), [provisional application guidance](https://www.uspto.gov/patents/basics/apply/provisional-application), and [subject-matter eligibility guidance](https://www.uspto.gov/patents/laws/examination-policy/subject-matter-eligibility). For computer-implemented claims, frame the invention as a specific improvement to computer operation or a technical field, with an implementation explanation and measurable technical effect; the USPTO emphasizes that simply applying an abstract idea on generic computing is insufficient. See [MPEP §2106](https://www.uspto.gov/web/offices/pac/mpep/s2106.html).

**Immediate action:** have patent counsel perform a confidentiality-preserving novelty search and file a fully enabling provisional before further public technical disclosures of any unfiled mechanism. Do not publish this memo or new implementation details outside the intended filing strategy until that review is complete.
