---
title: Drydock vs the Practical Field
title_sub: Drydock, GitHub Spec Kit, Kiro, BMAD-METHOD, and a plain CLAUDE.md
eyebrow: Competitive Analysis
subtitle: Scored feature matrix with explicit winners
logo: drydock_logo.png
author: Ed Barlow
studio: Web Cloud Studio
year: August 5, 2026
nav_active: drydock.html
header_title: Product Comparison Matrix
copyright: Copyright © 2026 Web Cloud Studio. All rights reserved.
---

# Drydock vs Spec Kit vs Kiro vs BMAD vs a Plain CLAUDE.md

**Analysis date:** 2026-08-05
**Method:** Drydock scored against `docs/Drydock_Specification.md` as implemented. The other four
scored from published documentation and normal working use. No competitor was benchmarked
hands-on. Scores are engineering judgment, not measurements.
**Bias disclosure:** the row set is drawn from the problem Drydock solves — governed delivery of a
large system from an existing written specification. That biases the aggregate in Drydock's favor.
The honest read is Section 9 and the scenario table, not the grand total.

## What Each Product Actually Is

| Key | Product | What it is | Cost model |
|---|---|---|---|
| **DD** | **Drydock** | A build system for specifications. Compiles a Blueprint into a dependency graph and executes it under test gates. | Proprietary; runs on your LLM subscription |
| SK | GitHub Spec Kit | A prompt/template kit that turns an idea into spec → plan → tasks, then hands tasks to your agent. | Open source |
| KI | Kiro (AWS) | An IDE with a spec-first mode: requirements, design, tasks, agent hooks. | Proprietary IDE, paid tiers |
| BM | BMAD-METHOD | A multi-agent role framework (analyst, PM, architect, scrum master, dev, QA) driving elicitation and story delivery. | Open source |
| CM | Plain CLAUDE.md | One rules file plus an agent. The honest baseline everything must beat. | Free |

**The critical distinction.** Drydock does not write your specification. Authoring is an explicit
non-goal — `drydock import` assumes you arrive with source material. Spec Kit, Kiro, and BMAD are
all primarily *specification authoring* front-ends whose build side is "hand the tasks to an
agent." Drydock is the opposite shape: a weak front-end and an industrial back-end. Comparing them
as one category is the single most common error in this space.

## Scoring Legend

| Cell | Score | Meaning |
|:--:|:--:|---|
| 🟩 | 5 | Best in this comparison; deterministic and enforced |
| 🟢 | 4 | Strong first-class capability |
| 🟡 | 3 | Present and usable; advisory rather than enforced |
| 🟠 | 2 | Partial, manual, or emergent from adjacent features |
| 🔴 | 1 | Nominal or documentation-only |
| ⬛ | 0 | Absent |

---

## 1 — Specification Authoring and Ingestion

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 1.1 | Creates a specification from a blank page (elicitation, brainstorming, PRD) | ⬛0 | 🟢4 | 🟢4 | 🟩5 | 🟠2 | **BMAD** |
| 1.2 | Ingests arbitrary pre-existing source material as the input of record | 🟩5 | 🔴1 | 🟠2 | 🟡3 | 🟠2 | **Drydock** |
| 1.3 | Typed specification files with prescribed roles and validation | 🟩5 | 🟡3 | 🟡3 | 🟡3 | 🔴1 | **Drydock** |
| 1.4 | Specification quality audit against the raw sources | 🟢4 | ⬛0 | 🔴1 | 🟠2 | ⬛0 | **Drydock** |
| 1.5 | Specification remains authoritative after code exists | 🟩5 | 🟠2 | 🟡3 | 🟠2 | 🔴1 | **Drydock** |
| | **Section average** | **3.8** | 2.0 | 2.6 | 3.0 | 1.2 | |

**Read.** BMAD wins the row that matters to a team with nothing written down, and it wins it
outright — its analyst/PM/architect agent chain is genuinely better at getting a coherent product
definition out of a founder's head than anything Drydock has, because Drydock has nothing here at
all. Drydock's 3.8 average in a section it loses the headline row of is the pattern for this whole
document: it is strong everywhere downstream of "the specification exists."

## 2 — Planning and Decomposition

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 2.1 | Dependency-graph build plan with a computed runnable frontier | 🟩5 | 🔴1 | 🔴1 | 🟠2 | ⬛0 | **Drydock** |
| 2.2 | Story decomposition with stable IDs, states, and `depends:` edges | 🟩5 | 🟡3 | 🟢4 | 🟢4 | ⬛0 | **Drydock** |
| 2.3 | Effort estimate expressed as token cost, not vibes | 🟩5 | ⬛0 | ⬛0 | 🟠2 | ⬛0 | **Drydock** |
| 2.4 | Blocker gate that halts planning until the human answers | 🟩5 | 🔴1 | 🟠2 | 🟡3 | ⬛0 | **Drydock** |
| 2.5 | Human-editable plan: reorder, regroup, rename, split | 🟩5 | 🟠2 | 🟡3 | 🟠2 | 🔴1 | **Drydock** |
| | **Section average** | **5.0** | 1.4 | 2.0 | 2.6 | 0.2 | |

**Read.** Uncontested. `MANIFEST.md` is a graph database with build state, provenance hashes, and
grouping — the others produce an ordered task list. Row 2.3 is the one nobody else even attempts:
story points priced in tokens makes context an explicitly budgeted resource.

## 3 — Build Execution

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 3.1 | Executes the plan autonomously, block by block, to working software | 🟩5 | 🟡3 | 🟢4 | 🟢4 | 🟡3 | **Drydock** |
| 3.2 | Per-step context stacking — only the specs that step needs | 🟩5 | 🟠2 | 🟠2 | 🟢4 | 🔴1 | **Drydock** |
| 3.3 | Automatic repair loop on failure with progress-based continuation | 🟩5 | ⬛0 | 🔴1 | 🟠2 | 🔴1 | **Drydock** |
| 3.4 | Model escalation on the final repair attempt | 🟩5 | ⬛0 | ⬛0 | 🔴1 | ⬛0 | **Drydock** |
| 3.5 | Parallel or worktree-isolated execution of independent work | ⬛0 | ⬛0 | 🔴1 | 🟠2 | 🔴1 | **BMAD** |
| 3.6 | Resume in place after failure with partial work and failing checks intact | 🟩5 | 🔴1 | 🟠2 | 🟠2 | 🔴1 | **Drydock** |
| | **Section average** | **4.2** | 1.0 | 1.7 | 2.5 | 1.2 | |

**Read.** Row 3.3 is the feature Drydock is actually built around and nobody else implements as a
loop with a *termination condition*: repair continues only while the passing set grows without
regression, or a per-criterion case tally improves without another regressing. That is a
convergence rule, not a retry counter.

Row 3.5 is a real loss and worth stating plainly: Drydock computes the exact dependency graph that
makes safe parallelism trivial, then builds strictly serially anyway. BMAD wins a row by a margin
of 2 points on a 5-point scale — nobody in this comparison is good at it — but Drydock is the one
leaving free throughput on the table.

## 4 — Verification and Test Integrity

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 4.1 | Enforced TDD gate — acceptance criteria exist and fail before implementation | 🟢4 | 🔴1 | 🟠2 | 🟡3 | 🟠2 | **Drydock** |
| 4.2 | Acceptance verified deterministically by executing it, with no LLM in the loop | 🟩5 | ⬛0 | 🔴1 | 🔴1 | ⬛0 | **Drydock** |
| 4.3 | Proof integrity — vacuous or tautological proofs demoted to UNVERIFIED | 🟩5 | ⬛0 | ⬛0 | ⬛0 | ⬛0 | **Drydock** |
| 4.4 | EARS-notation project acceptance criteria with stable IDs | 🟩5 | ⬛0 | 🟡3 | ⬛0 | ⬛0 | **Drydock** |
| 4.5 | Guardrails as absolute prohibitions behind a hard gate | 🟩5 | 🔴1 | ⬛0 | 🔴1 | 🟠2 | **Drydock** |
| 4.6 | Release verdict with enumerated blockers | 🟩5 | ⬛0 | 🔴1 | 🟠2 | ⬛0 | **Drydock** |
| | **Section average** | **4.8** | 0.3 | 1.2 | 1.2 | 0.7 | |

**Read.** The widest margin in the document, and the least contestable. Every other product in this
comparison lets the same agent that wrote the code decide whether the code is correct. Drydock
separates the two: `score ac` runs the criterion as a process and reports PASS / FAIL / UNVERIFIED,
and static analysis demotes an empty body, a constant assertion, or a self-comparison rather than
counting it as proof. Row 4.3 is currently unique in the entire field, not just this comparison.

The honest deduction on 4.1: the RED→GREEN sequence is enforced at the gate and vacuous criteria
are demoted, but Drydock does not hash-lock the test artifact before implementation, so a
sufficiently determined agent can still shape the target. 4, not 5.

## 5 — Change Management

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 5.1 | Drift detection on applied specs via content hash plus commit provenance | 🟩5 | ⬛0 | 🔴1 | ⬛0 | ⬛0 | **Drydock** |
| 5.2 | Sealed foundational specifications requiring an explicit change ticket | 🟩5 | ⬛0 | ⬛0 | 🔴1 | ⬛0 | **Drydock** |
| 5.3 | Incremental replan scoped to impacted work only | 🟩5 | 🔴1 | 🟠2 | 🟠2 | ⬛0 | **Drydock** |
| 5.4 | Change the specification, then rebuild — as the normal path, not a restart | 🟩5 | 🟠2 | 🟡3 | 🟡3 | 🔴1 | **Drydock** |
| 5.5 | Regression reopens a previously verified sibling story | 🟢4 | ⬛0 | ⬛0 | ⬛0 | ⬛0 | **Drydock** |
| | **Section average** | **4.8** | 0.6 | 1.2 | 1.2 | 0.2 | |

**Read.** This is where the other four stop being comparable products. Spec Kit, Kiro, and BMAD are
all strongest on the first pass and weakest on the second; their answer to "the spec changed" is
largely "run it again and reconcile by hand." Drydock's `refit` closes the loop: it detects changed
Blueprints by checksum and commit, requires a ticket to touch `ARCHITECTURE.md` / `DATABASE.md` /
`UI-GENERAL.md`, remaps the Manifest, and resets exactly the work that must be rebuilt. A build
blocks outright when applied specs have drifted. That is change control, not iteration.

## 6 — Context and Cost Economics

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 6.1 | Compaction of rules and specs to a callable surface | 🟩5 | ⬛0 | ⬛0 | 🟡3 | 🔴1 | **Drydock** |
| 6.2 | Automatic full-vs-compact selection driven by the build graph | 🟩5 | ⬛0 | ⬛0 | ⬛0 | ⬛0 | **Drydock** |
| 6.3 | Runs on a subscription CLI with no per-token API spend | 🟩5 | 🟡3 | ⬛0 | 🟡3 | 🟩5 | **Tie: Drydock / CLAUDE.md** |
| 6.4 | Large project delivered with a cheaper model | 🟢4 | 🟠2 | 🟠2 | 🟡3 | 🔴1 | **Drydock** |
| | **Section average** | **4.8** | 1.3 | 0.5 | 2.3 | 1.8 | |

**Read.** Kiro's 0.5 here is structural: it is an IDE with metered inference, and the cost curve on
a large project is its main adoption objection. Drydock's position — compaction, graph-driven
context selection, token-priced stories, subscription-only execution — is the second differentiated
moat after verification. Note the tie on 6.3: a plain CLAUDE.md is exactly as cheap.

## 7 — Governance and Enterprise Standards

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 7.1 | Injected enterprise layer: business rules, stack rules, branding | 🟩5 | 🟠2 | 🟡3 | 🟠2 | 🟢4 | **Drydock** |
| 7.2 | Persistent intent injected at every process stage | 🟩5 | 🟡3 | 🟡3 | 🟡3 | 🟢4 | **Drydock** |
| 7.3 | Reviewable build evidence written per step | 🟩5 | 🔴1 | 🟠2 | 🟠2 | ⬛0 | **Drydock** |
| 7.4 | Dependency legitimacy guard on generated package changes | 🟢4 | ⬛0 | ⬛0 | ⬛0 | 🔴1 | **Drydock** |
| | **Section average** | **4.8** | 1.5 | 2.0 | 1.8 | 2.3 | |

**Read.** CLAUDE.md scores second here, and deservedly — rows 7.1 and 7.2 are literally what a
rules file does, and it does them for zero setup cost. Drydock's advantage is that Rigging is
portfolio-scoped, versioned, compacted, and injected by the build rather than hoped for, plus it
writes evidence a reviewer can audit afterward. If your only requirement is "follow our house
style," a CLAUDE.md gets you 80% of this section for 2% of the effort.

## 8 — Human Review Surface

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 8.1 | Dedicated review console for plan, evidence, and decisions | 🟩5 | ⬛0 | 🟢4 | 🔴1 | ⬛0 | **Drydock** |
| 8.2 | Questionnaires whose answers persist into later commands | 🟩5 | 🔴1 | 🟠2 | 🟡3 | ⬛0 | **Drydock** |
| 8.3 | Board / kanban view of plan state | 🟢4 | ⬛0 | 🟡3 | 🔴1 | ⬛0 | **Drydock** |
| 8.4 | Generated project documentation with publishable rendering | 🟩5 | 🔴1 | 🔴1 | 🟠2 | 🔴1 | **Drydock** |
| | **Section average** | **4.8** | 0.5 | 2.5 | 1.8 | 0.3 | |

**Read.** Drydock ships a web service — the QuarterDeck — as a first-class part of the methodology:
markdown pages, editable specs, a kanban of the Manifest, a Build Compass showing the costed work
graph with buildable-now / review / done / failed badges, and questionnaires that feed the next
command. Kiro's competing surface is genuinely good and better integrated with the editor, but it
reviews the *spec*, not per-step build evidence. The gap on 8.1 is narrower than the score implies
if your team lives in an IDE.

## 9 — Adoption Cost and Ecosystem

**This is the section where Drydock loses, and it loses badly.**

| # | Capability | **DD** | SK | KI | BM | CM | Winner |
|---|---|:--:|:--:|:--:|:--:|:--:|---|
| 9.1 | Time from zero to first working code | 🔴1 | 🟡3 | 🟢4 | 🟠2 | 🟩5 | **CLAUDE.md** |
| 9.2 | Right-sized for a small change or a one-file fix | 🔴1 | 🟠2 | 🟡3 | 🟡3 | 🟩5 | **CLAUDE.md** |
| 9.3 | Zero install, no new tooling, no workspace concept | 🔴1 | 🟡3 | 🔴1 | 🟠2 | 🟩5 | **CLAUDE.md** |
| 9.4 | Open source / no license cost | ⬛0 | 🟩5 | 🔴1 | 🟩5 | 🟩5 | **Tie: SK / BMAD / CLAUDE.md** |
| 9.5 | Language and stack coverage out of the box | 🟠2 | 🟢4 | 🟢4 | 🟢4 | 🟩5 | **CLAUDE.md** |
| 9.6 | Community, ecosystem, third-party extensions | 🔴1 | 🟩5 | 🟡3 | 🟢4 | 🟩5 | **Tie: Spec Kit / CLAUDE.md** |
| | **Section average** | **1.0** | 3.7 | 2.7 | 3.3 | **5.0** | |

**Read.** A plain CLAUDE.md sweeps this section 5.0 to Drydock's 1.0, and that is not a rounding
artifact — it is the strongest single result in the document. For anything under roughly a week of
work, the correct tool in this comparison is a rules file and an agent, and every ceremony Drydock
imposes is pure loss. Drydock ships Python Rigging only, is proprietary, and has effectively no
third-party ecosystem. Its `import → analyze → plan → build` chain is a long path to first running
software, which is precisely the critique the SDD literature levels at the whole category.

---

## Aggregate

| Product | Sections 1–8 (governed delivery) | Section 9 (adoption cost) | All 45 rows |
|---|:--:|:--:|:--:|
| **Drydock** | **🟩 4.6** | 🔴 1.0 | **4.11** |
| BMAD-METHOD | 🟠 2.0 | 🟡 3.3 | 2.20 |
| Kiro | 🔴 1.7 | 🟠 2.7 | 1.82 |
| Plain CLAUDE.md | 🔴 0.9 | 🟩 5.0 | 1.47 |
| GitHub Spec Kit | 🔴 1.0 | 🟡 3.7 | 1.40 |

Read the two columns, not the third. The result is a barbell: Drydock owns governed delivery by a
factor of two over the nearest product, and loses adoption cost by a factor of five to a text file.
Everything in the middle — Spec Kit, Kiro, BMAD — is better than both at neither and adequate at
some of each.

**Do not read 4.11 as market dominance.** Forty-five rows chosen from Drydock's feature space will
score Drydock highly by construction. Rerun this matrix with rows chosen by a two-person startup
shipping weekly and CLAUDE.md wins outright.

## Explicit Verdicts

| Question | Winner | Margin |
|---|---|---|
| Best at turning an idea into a written specification | **BMAD-METHOD** | Clear. Drydock scores 0; it is an explicit non-goal. |
| Best at building working software *from* a specification | **Drydock** | Decisive — 4.2 vs 2.5 next. |
| Best at proving the software is correct | **Drydock** | Decisive — 4.8 vs 1.2 next. Uniquely holds proof-integrity analysis. |
| Best at the second, third, and tenth change | **Drydock** | Decisive — 4.8 vs 1.2 next. Nobody else does drift detection with sealed specs. |
| Best at context and cost control | **Drydock** | Decisive on large work; ties CLAUDE.md on raw cost. |
| Best human review surface | **Drydock** | Narrow over Kiro; Kiro is better integrated, Drydock reviews more. |
| Best parallel throughput | **BMAD-METHOD** | Weak win. Drydock scores 0 and shouldn't. |
| Best editor-native experience | **Kiro** | Uncontested; Drydock is a CLI plus a local web console. |
| Best ecosystem and portability | **GitHub Spec Kit** | Clear; ubiquitous, free, agent-neutral. |
| Cheapest, fastest, least ceremony | **Plain CLAUDE.md** | Overwhelming. 5.0 across the section. |

## Which To Use

| Situation | Use | Why |
|---|---|---|
| One-file fix, small feature, exploratory hacking | **Plain CLAUDE.md** | Any process here costs more than the work. |
| Nothing written down; you need a product definition | **BMAD-METHOD** | Purpose-built elicitation; hand the output to a builder. |
| You want a free, agent-neutral team convention | **GitHub Spec Kit** | Lowest-friction shared vocabulary; accept that it drifts. |
| IDE-centric team, AWS shop, spec-first with editor hooks | **Kiro** | Best integrated authoring loop; watch metered inference cost. |
| Large system, specification already written, months of work | **Drydock** | Graph-ordered build, deterministic gates, evidence, refit. |
| Delivery that must be audited or defended | **Drydock** | Only product here producing per-step evidence and a release verdict with blockers. |
| Long-lived product where the spec keeps changing | **Drydock** | Only product here with drift detection, sealed specs, and scoped replan. |
| Maximum agent throughput on independent work | **None of these** | BMAD is least bad; the whole field is immature here. |

**The natural pairing is BMAD-or-Kiro upstream and Drydock downstream.** They are not the same
product and mostly do not compete. The one product Drydock genuinely must beat is the last row of
Section 9 — a rules file and a competent agent — and it only beats it when the work is large enough
that ordering, verification, and change control cost less than the chaos they replace. Below that
threshold, Drydock loses, and this document should say so.

## Where Drydock Must Improve

Ranked by the size of the honest loss.

1. **Right-sizing (9.1, 9.2).** No lightweight path. A small change pays the full pipeline. This is
   the category's most-cited failure mode and Drydock is among the heaviest examples of it.
2. **Parallel execution (3.5).** Scoring 0 while owning the dependency graph that makes parallelism
   safe is the clearest unforced loss in the matrix.
3. **Specification authoring (1.1).** Defensible as a non-goal, but it means Drydock cannot be
   anyone's only tool, and every evaluation starts with an apparent zero.
4. **Stack coverage (9.5).** Python Rigging only. Every non-Python team must author governance
   before they can evaluate the product.
5. **Test artifact locking (4.1).** RED→GREEN is gated and vacuous proofs are demoted, but the
   proof is not hash-locked before implementation. Closing this makes Section 4 unassailable.
