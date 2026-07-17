---
title: Spec-Driven Development Competitive Feature Matrix
title_sub: Where Drydock Stands Against the 2026 SDD Field
eyebrow: Competitive Analysis
subtitle: Feature-level benchmark of eleven spec-driven delivery systems
logo: drydock_logo.png
author: Ed Barlow
studio: Web Cloud Studio
year: July 17, 2026
nav_active: drydock.html
header_title: Product Comparison Matrix
copyright: Copyright © 2026 Web Cloud Studio. All rights reserved.
---

# Spec-Driven Development Competitive Feature Matrix

**Analysis date:** 2026-07-17
**Analyst:** Principal Developer review
**Subject:** Drydock benchmarked against ten current spec-driven development systems
**Method:** Documentation review of primary sources (vendor docs, repositories, published
benchmarks) plus independent analyses. Scores are documentation-derived judgment, not hands-on
execution benchmarks. No tool below was run as part of this analysis.
**Validation refresh:** 2026-07-17 against the currently published public documentation for
OpenSpec, BMAD-METHOD, Spec Kitty, Walden, Superpowers, GSD, Traycer, Tessl intent-integrity-kit,
spec-compare, Böckeler's Fowler article, and the 2026 arXiv SDD taxonomy paper.

## Scoring Legend

| Score | Meaning |
|---|---|
| 5 | Best in field; deterministic, enforced, and the tool's defining strength |
| 4 | Strong first-class capability |
| 3 | Present and usable; incomplete or advisory rather than enforced |
| 2 | Partial, manual, or emergent from adjacent features |
| 1 | Nominal or documentation-only |
| 0 | Absent |

## Products Benchmarked

| Key | Product | License | Maturity level |
|---|---|---|---|
| **DD** | **Drydock** | Proprietary | Spec-anchored |
| SK | GitHub Spec Kit | Open source | Spec-first |
| KI | Kiro (AWS) | Proprietary IDE | Spec-first |
| TS | Tessl Framework + intent-integrity-kit | Proprietary | Spec-as-source |
| OS | OpenSpec | Open source | Spec-anchored |
| BM | BMAD-METHOD | Open source | Spec-first |
| KT | Spec Kitty | Open source | Spec-anchored |
| WA | Walden | Open source | Spec-anchored |
| SP | Superpowers | Open source | Spec-first |
| GS | GSD (Get Shit Done) | Open source | Spec-anchored |
| TR | Traycer | Proprietary | Spec-first |

**Maturity levels** follow the taxonomy shared by Böckeler (martinfowler.com) and *Spec-Driven
Development: From Code to Contract* (arXiv 2602.00180): **spec-first** (spec guides initial build,
then drifts), **spec-anchored** (spec and code co-evolve, enforced by tests), **spec-as-source**
(humans edit only specs; code regenerates).

---

## Matrix A — Drydock Core Features

These are the capabilities Drydock is built on. The field is scored against Drydock's own ground.

| # | Feature | **DD** | SK | KI | TS | OS | BM | KT | WA | SP | GS | TR |
|---|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| A1 | Typed Specification files with prescribed roles | **5** | 3 | 3 | 4 | 3 | 3 | 3 | 3 | 1 | 3 | 2 |
| A2 | Dependency-graph build plan with runnable frontier | **5** | 1 | 1 | 1 | 1 | 2 | 2 | 2 | 2 | 4 | 2 |
| A3 | Context-size-aware prompt stacking (token budget per step) | **5** | 1 | 1 | 2 | 2 | 4 | 2 | 1 | 3 | 4 | 3 |
| A4 | LLM-estimated story points as token cost | **5** | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 |
| A5 | EARS-notation acceptance criteria, grammar-validated | **5** | 0 | 2 | 0 | 0 | 0 | 0 | **5** | 0 | 0 | 0 |
| A6 | Guardrails as absolute prohibitions with a hard gate | **5** | 2 | 0 | 2 | 0 | 0 | 1 | 3 | 0 | 2 | 0 |
| A7 | Evidence-bound scoring against Git HEAD + content hashes | **5** | 0 | 0 | 3 | 0 | 0 | 1 | 4 | 1 | 2 | 0 |
| A8 | Discount for model-judged (non-deterministic) verification | **5** | 0 | 0 | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| A9 | Blueprint drift detection via applied-spec hashing | **4** | 0 | 0 | 4 | 2 | 0 | 1 | **5** | 0 | 2 | 1 |
| A10 | Sealed foundational specs requiring a change ticket | **5** | 1 | 0 | 2 | 3 | 0 | 1 | 3 | 0 | 1 | 0 |
| A11 | Human review console for plan, evidence, and decisions | **4** | 1 | 4 | 2 | 3 | 2 | 4 | 2 | 1 | 1 | **5** |
| A12 | Persistent intent injected into every prompt (Compass) | **5** | 4 | 3 | 3 | 3 | 3 | 3 | 4 | 2 | 3 | 2 |
| A13 | Enterprise branding / stack rules injection (Rigging) | **5** | 2 | 3 | 1 | 1 | 2 | 1 | 2 | 1 | 1 | 1 |
| A14 | Builder/user spec compaction to cut context cost | **5** | 0 | 0 | 2 | 1 | 3 | 0 | 0 | 1 | 2 | 1 |
| A15 | Blocker/questionnaire loop that halts planning | **5** | 1 | 2 | 1 | 2 | 3 | 2 | 3 | 3 | 3 | 2 |
| A16 | Brownfield reverse-engineering into specs | **3** | 1 | 2 | 2 | 4 | 3 | 2 | 1 | 1 | 2 | 3 |
| A17 | Documentation generation and publishable rendering | **5** | 1 | 1 | 2 | 1 | 2 | 1 | 1 | 0 | 1 | 1 |
| A18 | Subscription-CLI-only execution (no API-key spend) | **5** | 3 | 0 | 0 | 3 | 3 | 3 | 4 | 4 | 3 | 0 |
| A19 | Provider/IDE neutrality | **4** | **5** | 0 | 2 | 4 | 4 | **5** | **5** | 2 | 2 | 3 |

**Reading.** Drydock leads or ties on 16 of 19 of its own core dimensions. The genuinely contested
ground is A5 (Walden matches Drydock's EARS grammar validation), A9 (Walden's staleness chain is
stricter), A11 (Traycer's review UX is more mature), and A19 (several open-source tools are more
portable). A4, A8, A14, and A17 are effectively uncontested — nobody else prices stories in tokens,
discounts model judgment, compacts specs by audience, or ships a documentation pipeline.

---

## Matrix B — Field Features Drydock Lacks or Underserves

This is where the gaps live. Drydock's scores here are the input to the NEXT_STEPS backlog.

| # | Feature | **DD** | SK | KI | TS | OS | BM | KT | WA | SP | GS | TR |
|---|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| B1 | Git worktree isolation for parallel agent execution | **0** | 0 | 0 | 0 | 1 | 2 | **5** | 0 | **5** | 4 | 3 |
| B2 | Parallel/wave execution of independent work | **0** | 0 | 0 | 0 | 1 | 3 | **5** | 0 | 4 | **5** | 3 |
| B3 | Enforced TDD RED→GREEN cycle | **1** | 1 | 2 | 3 | 1 | 3 | 2 | 3 | **5** | 3 | 1 |
| B4 | Test artifacts hash-locked before implementation | **0** | 0 | 0 | **5** | 0 | 0 | 0 | 2 | 1 | 0 | 0 |
| B5 | Test-quality analysis (empty/tautological assertions) | **0** | 0 | 0 | **5** | 0 | 0 | 0 | 1 | 2 | 2 | 0 |
| B6 | Delta change format (ADDED/MODIFIED/REMOVED) + archive | **2** | 1 | 1 | 2 | **5** | 1 | 2 | 2 | 0 | 2 | 1 |
| B7 | CI-portable release gate with exit-code enforcement | **1** | 1 | 0 | 2 | 2 | 0 | 2 | **5** | 0 | 2 | 0 |
| B8 | Semantic diff + downstream impact warning on spec edit | **1** | 0 | 0 | **5** | 3 | 0 | 1 | 4 | 0 | 2 | 1 |
| B9 | Retrospectives / cross-project lessons capture | **1** | 0 | 0 | 1 | 1 | 2 | **5** | 4 | 2 | 2 | 1 |
| B10 | Adaptive rigor — workflow right-sized to problem size | **1** | 1 | 1 | 2 | 4 | **5** | 2 | 1 | 3 | 4 | 4 |
| B11 | Explore/spike phase before committing to a plan | **2** | 2 | 1 | 3 | **5** | 4 | 2 | 2 | **5** | **5** | 4 |
| B12 | Cross-feature conflict / systems analysis | **1** | 1 | 1 | 2 | 2 | 3 | 1 | 2 | 1 | 2 | 2 |
| B13 | Decision-coverage gate (decisions reach shipped code) | **1** | 0 | 0 | 3 | 1 | 1 | 1 | 2 | 1 | **5** | 1 |
| B14 | Hallucinated/malicious package detection | **0** | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **5** | 0 |
| B15 | Dynamic model routing / cost tiering | **1** | 0 | 0 | 1 | 0 | 2 | 1 | 0 | 2 | **5** | 3 |
| B16 | Gherkin/.feature executable behavioral specs | **0** | 1 | 2 | 4 | 3 | 2 | 2 | 2 | 1 | 1 | 1 |
| B17 | Spec bloat / human-reviewability control | **2** | 1 | 1 | 2 | 3 | 1 | 2 | 3 | 2 | 2 | 2 |
| B18 | Cross-repository spec sharing | **0** | 0 | 0 | 4 | 3 | 1 | 0 | 0 | 0 | 0 | 0 |
| B19 | Bidirectional sync (fix spec first, then regenerate code) | **2** | 1 | 1 | **5** | 3 | 1 | 2 | 3 | 1 | 2 | 1 |
| B20 | Multi-agent role specialization | **1** | 2 | 2 | 2 | 1 | **5** | 4 | 1 | 4 | 4 | 3 |

**Reading.** Drydock's average in Matrix B is roughly 0.85 against a field average near 1.8. The
concentrated damage is in three clusters:

1. **Parallelism (B1, B2, B20).** Drydock builds strictly serially down the frontier. Spec Kitty,
   Superpowers, and GSD all execute independent work concurrently in isolated worktrees. Drydock
   already computes the dependency graph that makes this safe — it simply does not exploit it.
2. **Test integrity (B3, B4, B5).** Drydock scores acceptance coverage and discounts model
   judgment, but nothing stops an agent from writing a tautological test and passing its own gate.
   Tessl's intent-integrity-kit is the state of the art here and directly complements A8.
3. **Right-sizing (B10, B11, B17).** Every critical source — Böckeler, the arXiv paper, and the
   Zenn skepticism piece — converges on the same complaint: SDD tools impose one heavyweight
   workflow regardless of problem size. Drydock is among the heaviest in the field. This is the
   most-cited failure mode in the literature and Drydock has no answer to it.

---

## Aggregate Position

| Product | Matrix A avg (Drydock's ground) | Matrix B avg (field's ground) | Combined |
|---|:--:|:--:|:--:|
| **Drydock** | **4.74** | **0.85** | **2.79** |
| GSD | 1.95 | 2.85 | 2.40 |
| Walden | 2.63 | 1.85 | 2.24 |
| Tessl + IIKit | 1.84 | 2.55 | 2.20 |
| BMAD | 1.89 | 1.80 | 1.85 |
| OpenSpec | 1.74 | 1.95 | 1.84 |
| Spec Kitty | 1.68 | 1.95 | 1.82 |
| Superpowers | 1.16 | 1.95 | 1.55 |
| Traycer | 1.37 | 1.55 | 1.46 |
| GitHub Spec Kit | 1.37 | 0.60 | 0.98 |
| Kiro | 1.16 | 0.60 | 0.88 |

**Caveat on the aggregate.** Matrix A is selected on Drydock's own feature set, so Drydock's 4.74
there is partly definitional and should not be read as market dominance. The honest signal is the
delta: Drydock is far ahead on governance, context economics, and evidence, and well behind the
field's better tools on execution mechanics and test integrity.

## Strategic Read

**Drydock's defensible moat** is the combination nobody else has: token-priced story planning
(A4) + context-aware stacking (A3) + audience-based compaction (A14) + evidence-bound scoring
that penalizes model judgment (A7, A8). That is a genuinely differentiated position — Drydock is
the only tool in the field that treats *context as an economic resource* and *model judgment as a
liability to be discounted*. Nothing in the backlog should compromise that.

**Drydock's nearest competitor is Walden**, not Spec Kit or Kiro. Walden independently arrived at
EARS validation, staleness chains, proof-based completion, and the same core thesis — that
deterministic enforcement must be separated from non-deterministic drafting. Walden's advantages
are portability (single Go binary, zero dependencies) and the CI release gate. Its disadvantages
are no context economics, no story-point pricing, no compaction, and no review console.

**The most dangerous critique** is not a competitor — it is the shared conclusion of Böckeler and
the Zenn piece that heavyweight SDD reintroduces waterfall by delaying feedback. Drydock's
`import → analyze → quarterdeck → plan → build` chain is a long path to first working software.
B10 and B11 are not nice-to-haves; they are the answer to the field's central objection.

## Sources

- Böckeler, *Understanding Spec-Driven Development: Kiro, spec-kit, and Tessl* — https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html
- Fowler, *Structured-Prompt-Driven Development* — https://martinfowler.com/articles/structured-prompt-driven/
- *Spec-Driven Development: From Code to Contract* — https://arxiv.org/html/2602.00180v1
- cameronsjo/spec-compare, 13-tool feature matrix — https://github.com/cameronsjo/spec-compare
- specs.md compare — https://specs.md/compare/overview
- *The Spec: Living Specifications for Agentic Development* — https://asdlc.io/patterns/the-spec/
- intent-driven.dev best practices — https://intent-driven.dev/knowledge/best-practices/
- *Skepticism Toward Specification-Driven Development* — https://zenn.dev/cbmrham/articles/202601-spec-driven-development-skepticism
- OpenSpec — https://github.com/Fission-AI/OpenSpec
- BMAD-METHOD — https://docs.bmad-method.org/
- Spec Kitty — https://github.com/Priivacy-ai/spec-kitty
- Walden — https://andrearaponi.github.io/walden/
- Superpowers — https://github.com/obra/superpowers
- GSD — https://github.com/gsd-build/get-shit-done
- Traycer — https://docs.traycer.ai/quickstart
- Tessl intent-integrity-kit — https://tessl.io/registry/tessl-labs/intent-integrity-kit/2.7.5
