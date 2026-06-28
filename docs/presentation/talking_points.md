# Drydock — Talking-Points Outline

Compressed cue cards. One block per slide. Use if you'd rather speak extemporaneously than read the script.

## Act 1 — The setup (0:00–2:15)
1. **Title** — Build software from specs *with a real process* so you can reproduce it. Speed was never the issue.
2. **The gap** — SDD today ships specs but threw away 20 years of software practice. *To a financial engineer: a result you can't reproduce isn't a result.* Refine the spec all you want — no process, no reproducible build. Bottleneck = missing process.
3. **Insight** — Reproducible builds need a process, and it already exists: **Agile.** 15 yrs of best practice / Agile Manifesto, how devs ship at major companies. Drydock = Agile applied to AI delivery. About system *behavior*, not sub-agents. Spec = single source of truth.

## Act 2 — The product (2:15–3:40)
4. **Drydock + SAIL** — Governed, Blueprint-driven CLI. SAIL is an *agile process*: **S**et up, **A**nalyze, **I**mplement, **L**oop.
5. **The Product Owner** — Your role changed: not developer/designer → **product owner**. PO decides; the LLM **Agile Best Practices Team** develops. Behavior, not sub-agents. Compass = intent, Ship's Log = decisions, QuarterDeck = your agile interface.

## Act 3 — Walk the phases (3:40–9:00)
6. **S / Set up** — `pip install`, `config`, `init`. Runs on Claude/Codex subscription. No API keys.
7. **A / Analyze** — Import md/source/Spec Kit/notes → `analyze` decomposes into stories, milestones, blockers, questions. *Blocker → stops and asks.* Loop until ready.
8. **QuarterDeck** *(core differentiator)* — The custom **Agile interface** between Commander and the LLM Agile Best Practices Team. Renders analysis/stories/blockers/questionnaires for review; approve/answer/redirect → written to spec → carried forward. *Instead of guessing, an optimized communication path the Agile Manifesto already worked out.* Commander controls → best output.
9. **Manifest** *(engine)* — `plan` → typed Blueprints + dependency graph. Exact token cost per story. Context-budgeted file stacking. *Context engineered, not hoped for.*
10. **I / Implement** — `build` walks the frontier; evidence per step; verify → unlock dependents. `build score` = 7-dimension delivery health (completeness, tests, drift…).
11. **Rigging** — Branding + stack rules injected everywhere. Builder gets full spec; consumer gets compacted how-to. Keeps context lean at scale.
12. **L / Loop** — `refit` changes the app, keeps Blueprint + code aligned. Tracks git commit per file → rebuilds only what changed. Docs regenerate. Nothing drifts.

## Act 4 — The close (9:00–10:00)
13. **Why different** — Vibe = no spec, no process. SDD = spec, no process. **Drydock = spec + a real Agile process.** PO decides, team develops, every decision logged. Goal = working software you can reliably iterate, within the specification.
14. **CTA** — `pipx install drydock-sdd`. Open spec, open methodology, recruiting Commanders. Link.

## Anticipated Q&A (for the description / pinned comment)
- **vs. GitHub Spec Kit?** Spec Kit authors specs; Drydock adds the missing *process* — an Agile delivery loop with a product-owner role, the QuarterDeck review interface, a dependency-graph Manifest, context-budgeted build stacking, and drift scoring/refit. It governs the *whole* loop and can import Spec Kit projects.
- **Which models?** Any subscription-authenticated CLI agent — Claude or Codex today. No raw API keys.
- **Does it lock me in?** Outputs are plain Markdown Blueprints + standard source in your own git repo. Uninstalling removes the CLI, not your work.
- **Determinism?** The scoring/state math is deterministic and lives in the command; the LLM judges and drafts, the command computes and writes.
