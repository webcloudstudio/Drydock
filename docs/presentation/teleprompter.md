# Drydock Launch — Teleprompter Script

## **Read verbatim.** Every line is written to be spoken.
## **Headers** starting with # are not read nor are --- separators
## **`## >> ADVANCE`** means press the next-slide key, then keep reading.
## **`(pause)`** means one silent beat. Do not improvise between cues — the next line always tells you where you are.
## **Target**: ~10 minutes at 145 words per minute. On-screen bullets are spoken as written on the slide, so if you look up, the slide is the script.

---

(pause)
(pause)

## SLIDE 1 — Title

Welcome Commanders,

I am happy to announce the release of the Drydock process for specification-driven software delivery.

Drydock can repeatably deliver working software from specifications.

Drydock is enterprise-ready and uses your branding and business rules.
(pause)
(pause)
(pause)
AI can write code faster and better than anyone imagined. Speed is not the problem.

The problem is that you can't reproduce results and therefore can't maintain your systems.

Drydock reproduces using THE process used at professional software organizations.

(pause)

That process is Agile plus Test-Driven development plus a dev-ops process that minimizes token use and delivers reproducible results.

## >> ADVANCE
(pause)
(pause)
(pause)
## SLIDE 2 — The SDD

First, thirty seconds of background for anyone new to specification-driven development.

(pause)
Instead of interactively prompting an AI, you write specifications defining software behavior. Agents build software from the specifications.

There are many approaches to creating specifications, including simply asking your LLM to create one.
(pause)
Drydock is focused on larger applications built from specifications.
(pause)
(pause)
The promise is that your software can get better as you update the specifications, but there are two gaps.

## >> ADVANCE
# ThE Gap
(pause)
(pause)
(pause)
The first gap comes from specification size. Output quality is related to prompt size and complexity.

With a small spec you get great results.

But with a big spec, software quality falls off a cliff.
(pause)
Better results occur when you divide the software into small units of work.

(pause)
(pause)
Gap two is reproducibility.

The LLM is not deterministic. Large specifications drift.
That means you can't reproduce.

## >> ADVANCE
# Best Practices Mean
(pause)
(pause)
(pause)
The solution, unsurprisingly, is to use software development best practices.
(pause)

In Drydock, you are the Commander — the Agile Product Owner — and the LLM is your crew.  Your crew specializes in Agile and Test Driven Development.
(pause)

For 25 years, software engineers have been decomposing large projects using Agile. Agile is a communication process whereby the team agrees on small steps or stories that will deliver the product owner's vision.
(pause)

Agile means Discovery, decomposition, planning, Kanban, and review. Agile also means Stories, spikes, acceptance criteria, and definition of done.
(pause)
(pause)
Test-driven development means programatic assertions are defined for each story before you build. Test-driven development focuses on build quality. Testable assertions define exact software behavior and edge cases.

(pause)
TDD is a huge quality win for Specification delivery.
(pause)

These two well-established processes enable reproducible builds and allow specifications to serve as the source of truth for your projects.
(pause)
(pause)

Working software you cannot reproduce is not maintainable

Drydock lets you reproduce working software from specifications.

## >> ADVANCE
(pause)
(pause)
(pause)

## SLIDE 4 — Sail

SAIL is the governed Blueprint-driven delivery process.

Set up.
Analyze.
Implement.
Loop.
(pause)

Set up installs the CLI and imports notes or LLM-created specifications.
(pause)
Analyze decomposes stories using Agile, creates Tests, and plans the build.
(pause)
Implement builds working software with optimized context.
(pause)
Loop iterates using change tickets or specification edits.
(pause)

Rigging builds every project with your common standards and branding.

## >> ADVANCE
(pause)
(pause)
(pause)
## SLIDE 5 — You Are the Commander

You are the commander and the Commander steers the course.

The QuarterDeck is your web interface to the team. It renders Markdown cleanly.
(pause)
(pause)
Three Compass files define guardrails and intent.
(pause)
The first is the project COMPASS which is always injected

ANALYZE_COMPASS and PLAN_COMPASS are injected into the analyze and plan steps
(pause)
(pause)

The QuarterDeck is a web interface that lets you answer questions such as stack preferences and lets you address blockers identified by the crew.
The MANIFEST is the graph-database build plan, which you can steer in the QuarterDeck.

## >> ADVANCE
(pause)
(pause)
(pause)

## SLIDE 6 — S · Set Up

In the setup phase we lay the keel.

(pause)

Three commands.
First install drydock
(pause)
then run drydock config to define your variables.
(pause)
finally run drydock init to initialize a workspace for your project
(pause)
(pause)
Drydock runs on a subscription to an LLM service.

No A-P-I keys or token based billing is used

## >> ADVANCE
(pause)
(pause)
(pause)
## SLIDE 7 — A · Analyze

Phase two is Analyze, or charting the course.
(pause)

Import ingests Markdown, source code, specifications, and notes into your project workspace.

Analyze decomposes your epic into stories, acceptance criteria, blockers, and questions from the team

The Commander answers these in the QuarterDeck.

Finally, the plan step creates the Blueprints and the MANIFEST or authoritative build graph

## >> ADVANCE
(pause)
(pause)
(pause)
## SLIDE 8 — The QuarterDeck

The QuarterDeck is your web console — an optimized communication path between the Commander and the crew.
(pause)

The command — drydock run quarterdeck — starts your local server.
(pause)
It renders crew output such as the story hierarchy, blockers, and questionaires.

You answer or redirect — decisions are persisted and carried forward.

The Quarterdeck also lets the commander organize the Manifest based on your testing and delivery priorities.
(pause)
I will give you a live look at the QuarterDeck shortly — and full deep-dive videos are coming.

## SLIDE 9 — The Manifest
## >> ADVANCE
(pause)
(pause)
(pause)

The Manifest is the engine of the system, and it is the part of Drydock which I am most proud
(pause)
drydock plan turns your analysis into typed Blueprints plus a Manifest or dependency graph. The Manifest relates stories both to their underlying stack and to other stories. It uses token cost for story points and optimizes context using compression. The Manifest is how we optimize the build.

Context is engineered, not hoped for. That's what makes builds reproducible.

## >> ADVANCE
(pause)
(pause)
(pause)
## SLIDE 10 — I · Implement

In the Implement Phase drydock build will read both your Blueprints and your Manifest and will output working software.
(pause)
It builds one block of work at a time. Blocks of similar stories save context.
After each build block, programatic tests are run to verify story quality. These are the tests defined during planning.

Blocks are built until the build is complete.
(pause)
drydock build score measures delivery health.
(pause)

drydock document builds project documentation.
## >> ADVANCE
(pause)
(pause)
(pause)

## SLIDE 11 — Rigging

Rigging is branding, stack rules, and conventions. Rigging is built into every project so the project is maintainable and consistent.

(pause)
Appropriate rigging is injected into each story. Rigging is smart about context compression.
(pause)
(pause)

Service Builders need the full specification to implement a feature.
(pause)
But Service Consumers only need a compacted version — how to call it, not how it works.

(pause)
A web page does not need to understand rest call details - just its contract.

Drydock rigging compact produces that consumer version and keeps context lean across a large codebase.

## >> ADVANCE
(pause)
(pause)
(pause)
## SLIDE 12 — L · Loop
Loop. Software is never done, so Drydock gives you three ways to Refit your software.
(pause)
Option one: edit the specification files directly. Refit remaps your edits using git commits, and rebuilds only what changed.
(pause)
(pause)
Option two: drydock Refit will tie your change tickets into your manifest.
(pause)
(pause)

Option three: you can use skills to brainstorm and create tickets.
(pause)

With all three options, you build normally with drydock build.

Specifications are ordered. Minimal drift.

## >> ADVANCE
(pause)
(pause)
(pause)

## SLIDE 13 — Why Drydock

So why Drydock? The differentiator is process — and the process is Agile and Test Driven Development.
(pause)
(pause)

Vibe coding has no spec, no process. You get Speed, then drift.
(pause)
Spec-driven design has a specification, but no process to reproduce the build.
(pause)
Drydock has specifications, plus test-driven development, plus Agile and it uses a clean process that minimizes drift. The Commander decides; the team develops.

(pause)

The goal is the same goal Agile has always had: working software you can reliably iterate — with an easy path to make it better.

## >> ADVANCE
(pause)
(pause)
(pause)

## SLIDE 14 — Get Started

Take it for a sail.

(pause)

Drydock is Open Source - Mit Licensed - We are looking for new Commanders.

(pause)
Now — let me show you the QuarterDeck.
(pause)
(pause)
(pause)

# >> SWITCH TO QUARTERDECK DEMO

The quarterdeck is your dedicated Agile console.  Here we see the captains chair which shows project status.
(pause)
(pause)
In the quarterdeck you can review and edit your compass files.
(pause)
(pause)
You can answer questions surfaced by the llm
(pause)
(pause)
You can see your project kanban board and also can steer the manifest -
(pause)
(pause)
(pause)
The Quarterdeck manifest lets you group your stories into blocks. Blocks are implemented together in one step.  Grouping enables you to save context.
(pause)
(pause)
(pause)
THis concludes our overview of the Drydock.  THe web site at webcloudstudio.com has the complete documentation for drydock but the true test is when you install the project.

(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
(pause)
