# Drydock — Talking-Points Outline

Compressed cue cards. One block per slide. Use if you'd rather speak extemporaneously than read the script.

## Act 1 — The setup (0:00–2:15)
1. **Title** — Builds software from specs; keeps it honest as it grows. Speed was never the issue; governance is.
2. **Problem** — Vibe coding: 1,000 lines from a prompt → spec drifts, wrong context, forgotten decisions. Demo-good, product-bad. *Bottleneck = context + governance + drift.*
3. **Insight** — Control what the model sees, in what order, under what intent → reproducible builds. Spec is the single source of truth; code is downstream.

## Act 2 — The product (2:15–3:40)
4. **Drydock + SAIL** — Governed, Blueprint-driven CLI. Four phases: **S**et up, **A**nalyze, **I**mplement, **L**oop.
5. **The Commander** — You're the product owner; LLM is your agile team. Compass = intent, Ship's Log = decisions, QuarterDeck = command. Directing a build, not chatting.

## Act 3 — Walk the phases (3:40–9:00)
6. **S / Set up** — `pip install`, `config`, `init`. Runs on Claude/Codex subscription. No API keys.
7. **A / Analyze** — Import md/source/Spec Kit/notes → `analyze` decomposes into stories, milestones, blockers, questions. *Blocker → stops and asks.* Loop until ready.
8. **QuarterDeck** *(differentiator)* — Local web console renders LLM output for review. Approve/answer/redirect → written back to spec → carried forward. The human gate vibe coding lacks.
9. **Manifest** *(engine)* — `plan` → typed Blueprints + dependency graph. Exact token cost per story. Context-budgeted file stacking. *Context engineered, not hoped for.*
10. **I / Implement** — `build` walks the frontier; evidence per step; verify → unlock dependents. `build score` = 7-dimension delivery health (completeness, tests, drift…).
11. **Rigging** — Branding + stack rules injected everywhere. Builder gets full spec; consumer gets compacted how-to. Keeps context lean at scale.
12. **L / Loop** — `refit` changes the app, keeps Blueprint + code aligned. Tracks git commit per file → rebuilds only what changed. Docs regenerate. Nothing drifts.

## Act 4 — The close (9:00–10:00)
13. **Why different** — Vibe = speed, no governance. Heavy process = governance, no speed. **Drydock = both.** Canonical spec · engineered context · logged decisions · human sign-off per gate.
14. **CTA** — `pipx install drydock-sdd`. Open spec, open methodology, recruiting Commanders. Link.

## Anticipated Q&A (for the description / pinned comment)
- **vs. GitHub Spec Kit?** Drydock adds the dependency-graph Manifest, context-budgeted build stacking, the QuarterDeck review gate, and drift scoring/refit — it governs the *whole* loop, not just spec authoring. It can also import Spec Kit projects.
- **Which models?** Any subscription-authenticated CLI agent — Claude or Codex today. No raw API keys.
- **Does it lock me in?** Outputs are plain Markdown Blueprints + standard source in your own git repo. Uninstalling removes the CLI, not your work.
- **Determinism?** The scoring/state math is deterministic and lives in the command; the LLM judges and drafts, the command computes and writes.
