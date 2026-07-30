# Show HN Draft — Drydock

**Status:** Draft. Not posted.
**Date:** 2026-07-30
**Prerequisite:** README hero and worked-example repo complete. Do not post before both are live.

---

## Title

Post one of these. Titles must contain no adjectives, no marketing verbs, and no exclamation.
HN readers downvote a title that sells.

**Preferred:**

```
Show HN: Drydock – a delivery process for Claude Code and Codex, not another prompt pack
```

**Alternates:**

```
Show HN: Drydock – spec-driven builds with a dependency graph and per-step evidence
Show HN: Drydock – I made my coding agent work from a typed specification
```

Length limit is 80 characters. The preferred title is 79. Verify before submitting.

## URL

`https://github.com/webcloudstudio/Drydock` — the repository, not the marketing site. HN
distrusts a landing page and trusts a README.

---

## Body text (first comment, posted by the author immediately after submission)

> Hi HN. I am Ed Barlow. I have spent 30 years in data engineering and architecture, and the
> last two building software with coding agents.
>
> The failure mode that pushed me into this: agents are excellent at any single step and
> unreliable across fifty of them. Context gets stale, earlier decisions get silently
> contradicted, working code gets rewritten, and there is no artifact that tells you what was
> actually built versus what you asked for. Every session starts from a slightly different
> understanding of the product.
>
> Drydock is my attempt at the missing layer. It is a Python CLI that treats the LLM as an
> Agile delivery team and you as the product owner. It imports source material — notes, an
> existing source tree, or a Spec Kit project — decomposes it into stories with acceptance
> criteria, makes you answer the open questions in a local web review surface before anything
> gets built, and emits a typed Markdown Blueprint plus a dependency graph. The build then
> executes one runnable frontier at a time, each step with a deliberately scoped context, and
> persists the prompt, the raw output, and the result for every step. Acceptance verification
> is deterministic Python, not a model judging its own work.
>
> Design decisions worth arguing with:
>
> - **Specifications are typed Markdown, not YAML or a DSL.** Humans have to read and edit them
>   under pressure, and every model already speaks Markdown well.
> - **It runs on your Claude or Codex subscription CLI as a subprocess.** No API keys, no
>   per-token billing. This constrains what is possible but the economics of API-billed
>   multi-step builds are hostile to iteration.
> - **The human review gate is mandatory, not optional.** The most expensive defects in
>   agent-built software are decisions nobody made on purpose.
> - **Change goes through the specification.** Fix the Blueprint and rebuild the affected
>   frontier; do not patch the code behind the specification's back.
>
> It is 0.1.x and honestly beta. The whole SAIL path works end to end and I use it on real
> projects, but the command surface and the specification contracts will move during 0.x.
>
> What I would most like feedback on: is the typed specification format actually workable for
> your projects, or does it break on the first thing you throw at it that is not a greenfield
> web app? Tell me where it fails. That is more useful to me than a star.
>
> Install is `uv tool install drydock-sdd`. The complete command surface is one screenshot in
> the README — there is no hidden surface.

Trim to fit if it runs long on preview. The first two paragraphs carry the post.

---

## Prepared answers

Have these ready. Reply within minutes; thread velocity in the first hour decides the outcome.

**"How is this different from GitHub Spec Kit / Kiro / BMAD?"**
> Spec Kit gets you a specification and hands it to the agent. Drydock is what happens after:
> ordering the work into a dependency graph, scoping context per step, requiring a human
> decision gate before build, and keeping evidence so a claim of "done" is checkable. Honest
> comparison including where the others win: <link to comparison matrix>. I borrowed the
> Spec Kit import format on purpose — you can bring an existing Spec Kit project straight in.

**"This is just a prompt wrapper."**
> Substantially, yes — with the interesting parts being what surrounds the prompt: the
> decomposition, the ordering, the context budget per step, the deterministic acceptance
> checker, and the evidence log. The prompts themselves are versioned files in `prompts/` with
> declared contracts; read them and tell me what is wrong with them.

**"Why not just use a CLAUDE.md and good habits?"**
> That works until the project is bigger than one person's memory, or until you come back to it
> in six weeks. The thing a CLAUDE.md cannot give you is an ordered graph of remaining work and
> an evidence trail for what was already built.

**"Markdown as a specification format will not scale."**
> Possibly. `drydock validate` type-checks it, which catches most of what I feared. If it
> breaks for you, that is the exact failure report I am asking for.

**"Vendor lock-in to Anthropic/OpenAI subscriptions."**
> The provider sits behind one adapter. Claude and Codex are implemented because they are the
> subscription CLIs I have. A local-model runner is a contained piece of work and I would take
> that patch.

**"Show me it built something real."**
> <link to worked-example repo> — the application, plus the Blueprint, Manifest, Soundings, and
> the full run logs that produced it.

**Hostile comments.** Answer the technical content, ignore the tone, never argue. One
concession-and-thanks reply beats three defenses.

---

## Mechanics

- Submit **Tuesday, Wednesday, or Thursday, 08:00–10:00 US Eastern**. Avoid Friday and weekends.
- Do not ask anyone to upvote. HN detects voting rings and it is unrecoverable.
- Block **the entire day**. An unattended Show HN dies regardless of quality.
- If it does not reach the front page, that is normal and it is not a verdict on the project.
  You may repost once after a substantive change, roughly a month later, per HN's own guidance.
- Read the thread for the pitch, not just the criticism: the phrasing commenters use to describe
  Drydock back to you is better copy than anything you will write yourself. Harvest it.
