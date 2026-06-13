# notes_analyze — how `drydock analyze` works (design discussion)

**Status:** Design notes, not specification. This is the agreed thinking for `drydock analyze`.
When we build the command, this file is the source — we will ignore `docs/Drydock_Specification.md`
for it until the design is stable. Material decisions here also belong in the Ship's Log.

---

## Goal

`drydock analyze` is a **pure, read-only analysis** step. It changes nothing. It reads the imported
Blueprint and produces artifacts that (a) give the user something to **review and approve** in the
console and (b) make `drydock plan create` better and cheaper.

Workflow:

```
import  →  analyze  →  review in console  →  plan create  →  build
```

## Why the step exists (the crux)

If an LLM could resolve everything, it would just plan in one shot and the step would be pointless.
The step earns its place **only where a human must decide**. So the heart of analyze is the
questionnaire. Each question splits two ways:

- the user **knows** → they answer it (e.g. "stack? Django");
- the user **doesn't know** → the unknown becomes a **spike**.

## What analyze writes (named artifacts)

- `<Target>/QuarterDeck/planning/ANALYSIS.md` — the **shape**: the project as a graph **grouped by
  component type** (screens, features, backend components, contracts, data) with depends-on edges.
  This is the structure the user approves. It carries a **summary at the top** so it reads cleanly
  in the console.
- `<Target>/QuarterDeck/questionnaires/planning.json` — the **questions**, produced by running a
  **checklist** over the spec (stack chosen? persistence defined? auth named? acceptance criteria
  present per feature? …). One unmet checklist item → one question.

## What analyze does NOT write (for contrast)

- `<Target>/blueprint/BUILD_CONFIGURATION.md` — durable product-owner answers, written by the
  **console review**, not by analyze. (Keeps analyze pure.)
- `<Target>/MANIFEST.md` — the plan, written by **plan create**, not analyze.

## Console review

The user opens the console and sees **"ANALYSIS DONE FOR TARGET X."** They read `ANALYSIS.md`
rendered in a template (summary on top, action buttons top-right — **Approve** / **Answer
Questions**), and answer `planning.json`. Their durable answers are written to
`BUILD_CONFIGURATION.md`. Then `drydock plan create` reads `ANALYSIS.md` + `BUILD_CONFIGURATION.md`
and produces `MANIFEST.md`.

## Design backbone

- **The checklist is the reusable contract.** Analyze = "run the checklist over the spec, emit the
  **shape** + the **unmet items**." This keeps it generic and model-robust: when models improve or
  the methodology changes, you edit the checklist, not the command.
- Division of labor: the **shape** is deterministic from the spec headers; the **checklist** drives
  the questions; the **LLM** only fills prose and judgment calls.
- **Templated fixed-format files.** All fixed-format outputs (starting with `ANALYSIS.md`) get a
  summary header and a template so the console can render them with action buttons.
- **Stacking markdown.** The process composes by stacking markdown — e.g. the answered
  `planning.json` can be injected into the next prompt (`plan create`).
- **Recommended build path.** The `ANALYSIS.md` summary states a recommendation, including a
  first-class **one-shot vs decompose** call when the spec is small/clear enough to build directly
  (threshold config-driven).

## Open items (TBD)

1. **Checklist location** — `Rigging/` (reusable, durable contract — current lean) vs `prompts/`.
2. **Shape ownership** — does the shape live in `ANALYSIS.md` (analyze-owned, redefined from prose
   to a typed grouped-graph), or does analyze produce `BUILD_PLAN_COMPASS.md` early? The latter
   already means "inputs + planning groups" but is currently owned by `plan create`. Pick one;
   avoid a duplicate concept.

## Not in scope yet

Building the `analyze` command. Editing the canonical specification.
