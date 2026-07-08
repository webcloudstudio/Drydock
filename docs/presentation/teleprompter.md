# Drydock Launch — Teleprompter Script

**Read verbatim.** Every line is written to be spoken.
**`>> ADVANCE`** means press the next-slide key, then keep reading.
**`( pause )`** means one silent beat. Do not improvise between cues — the next line always tells you where you are.
Target: ~10 minutes at 145 words per minute. On-screen bullets are spoken as written on the slide, so if you look up, the slide is the script.

---

## SLIDE 1 — Title

Ahoy, Commanders

I am pleased to announce the release of Drydock.

Drydock is specification-driven delivery.

It repeatably builds working software from specifications.

( pause )

Drydock Features

    Built around The Agile methodology.

    Built around test-driven development.

    Engineering Process to Minimize Context and Deliver Reproducible Results.

For two years, AI has written code faster than anyone imagined.  Speed was never the problem.

    The problem is that you cannot reproduce the result.

    Drydock fixes that — with the same process used by ALL professional software enginnering organizations.

>> ADVANCE

## SLIDE 2 — The Gap

First, thirty seconds of background for anyone new to specification-driven design.

Instead of prompting an AI one request at a time, you write a specification —

That specification dfines what the software must do — and an agent builds the software from it.

There are many approaches to crating specifications including simply asking your llm to create one.

The spec is the source of truth. That is the whole idea.

It works and you can build applications . But the process has two gaps

The first is specification size.

    Spec Driven is related to prompt size and complexity.

If you hae a Small spec, great result. But if you have Big spec — software quality falls off a cliff.

The solution of course is to build the software in smaller chunks.

Gap two: the reproducibility problem.

Frontier Models producing code for large specifications are getting better but my experiments have shown
that larger specifications diverge - they drift

The solution to me was to use software development best practices

For 25 years - quality has been driven by Agile and test-driven development

Agile is a communication process whereby the team agrees on the steps to deliver the product owners vision

Test driven development is a process where we ask what does the software need to do exactly up front and test
all the conditions.  TDD is a HUGE quality gate for reproducabile builds...

These Two Well established  processes will enable your builds to  be reproducible

( pause )

Working software you cannot reproduce is not working software.

Drydock lets you reproduce working software from specifications

>> ADVANCE

## SLIDE 3 — The Insight

Welcome, Commander.

You are the Commander — the Agile Product Owner.  And the LLM is your Agile Best Practices Team.

Your team natively runs Agile and Test First Development methedologies

    Agile means - Discovery, decomposition, planning, Kanban, review.
    Agile means Stories, spikes, acceptance criteria, and a definition of done.
    Test Driven Development means pythonic assertions for each project story

Your team natively understands your business rules - your Branding, your standards, and your development preferences - these are your Rigging

Rigging is automatic and needs only be defined once for all your projects

You Are the Commander - You Decide - You guide but the team develops. That is the insight.

>> ADVANCE

## SLIDE 4 — Introducing Drydock

Drydock is governed, Blueprint-driven delivery — an installable Python CLI.

The process is called SAIL.

Set up. Analyze. Implement. Loop.

SAIL is an Agile-process, test-driven-development software development life cycle.

Set up your system and import your notes or LLM-created specifications.
Analyze decomposes the work into stories, spikes, and dependencies.
Implement builds working software with optimized context.
Loop and Refit with change tickets or specification edits.

drydock document can create your project documentation.
The ships log tracks milestones and decisions

Rigging builds every project with your common stack rules and branding.

Let me walk you through it.

>> ADVANCE

## SLIDE 5 — You Are the Commander

You are the Commander. The Commander steers the course.

These artifacts keep you in command.

The analyze phase surfaces questions such as stack preferences from the llm and surfaces
any blockers or mandatory feedback the Commander must apply

The Compass files define guardrails and intent.
    COMPASS.md holds the project's intent.
    BUILD COMPASS.md supports drydock analyze.
    PLAN COMPASS.md supports drydock plan.

The MANIFEST.md is the graph-database build plan — you edit it inside the QuarterDeck.

The QuarterDeck is your web interface to the team. You do not need to edit or read any markdown

You are not prompting a chatbot. You are directing a team.

>> ADVANCE

## SLIDE 6 — S · Set Up

Phase one: Set up. Laying the keel.

Three commands.
Pipx install drydock-S-D-D.
Drydock config set.
Drydock init MyApp.

Drydock runs on a subscription to an LLM service

No API keys. No per-token billing.

I use Claude Sonnet and Codex 5.4. Have not needed more advanced models for building.

Summary : All you need is a subscription and an idea.

>> ADVANCE

## SLIDE 7 — A · Analyze

Phase two: Analyze. Charting the course.

*** Follow the pipeline across the slide: sources, import, analyze, ANALYSIS, plan, MANIFEST.

Drydock import takes markdown, source code, Spec Kit projects, or loose notes.
Drydock analyze decomposes your Epic into stories, acceptance criteria, blockers, and questions.

And here is the governance: when the team hits a blocker, it stops and asks you.

ANALYSIS.md contains the proposed features, stories, and acceptance criteria — for your review. Nothing is committed until you approve.

Then drydock plan creates the Blueprints and MANIFEST.md.
The Manifest is the authoritative build graph.

>> ADVANCE

## SLIDE 8 — The QuarterDeck

This is the core differentiator.

The QuarterDeck is your web console — an optimized communication path between the Commander and the crew.

One command — drydock run quarterdeck — starts your local server.

It renders everything the team produced: the story hierarchy, the blockers, the open questions.
You approve, answer, or redirect — and your decisions are persisted and carried into every run.

( pause )

I will give you a live look at the QuarterDeck right after this deck — and full deep-dive videos are coming.

>> ADVANCE

## SLIDE 9 — The Manifest

The Manifest is the engine, and it is the part I am most proud of.

Drydock plan turns your analysis into typed Blueprints, plus the Manifest — a dependency graph of your entire build.

The LLM estimates story points — the real token cost — using that dependency graph.
Then Drydock stacks the correct, minimal context into every build prompt.
Your intent, the relevant spec slice, the task — and nothing else.

Context is engineered, not hoped for. That is what makes builds reproducible.

And drydock rigging compact reduces context even further, for builders and for users.

>> ADVANCE

## SLIDE 10 — I · Implement

Phase three: Implement. Sailing the frontier.

Manifest in. Working software out.

Drydock build walks the graph and builds the next runnable step.
Every step is verified against test-driven-development acceptance criteria — the tests that were written up front.
You run steps in sequence until the build is complete.

And drydock build score measures delivery health across seven dimensions — completeness, tests, drift, and more — so you always know how far the code has wandered from the spec.

>> ADVANCE

## SLIDE 11 — Rigging

For teams: Rigging.

Rigging is your branding, your stack rules, and your conventions — built into every project automatically.
All of your projects come out consistent.

And Rigging is smart about context.
A Builder needs the full specification to implement a feature.
A Consumer only needs the compacted manifest — how to call it, not how it works.

Drydock rigging compact produces that consumer version, and keeps context lean across a large codebase.

>> ADVANCE

## SLIDE 12 — L · Loop

Phase four: Loop. The Refit.

Software is never done, so Drydock gives you three ways to change it.

Option one: edit the specification files directly. Refit remaps your edits using git commits, and rebuilds only what changed.
Option two: refit ties change tickets to Blueprints.
Option three: the slash-refit skill brainstorms a change with you and creates the tickets. Slash-apply-refit applies them.

The summary line on the slide says it all: specifications are ordered. Minimal drift.

>> ADVANCE

## SLIDE 13 — Why Drydock

So why Drydock. The differentiator is process — and the process is Agile.

Vibe coding: no spec, no process. Speed, then drift.
Spec-driven design: a specification, but no process to reproduce the build.
Drydock: specification, plus test-driven development, plus Agile. The Commander decides; the team develops.

( pause )

The goal is the same goal Agile has always had:
working software you can reliably iterate — with an easy path to rebuild it, anytime.

>> ADVANCE

## SLIDE 14 — Get Started

Take it for a sail.

Pipx install drydock-S-D-D.
Drydock init MyApp — and chart your course.

The spec is open. The methodology is open. And I am looking for alpha Commanders.

( pause )

Now — let me show you the QuarterDeck.

>> SWITCH TO QUARTERDECK DEMO

---

## Demo hand-off cue card (not read aloud)

- Browser tab is already open at the QuarterDeck before recording.
- Show, in order: story hierarchy → a blocker/question → answer it → the Manifest view.
- Keep it under two minutes; the deep dives are separate videos.
- Close with: "That's the QuarterDeck. Deep-dive videos are on the way. Fair winds, Commander."
