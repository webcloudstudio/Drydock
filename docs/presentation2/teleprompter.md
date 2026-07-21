# Drydock Detailed Walkthrough — Bullet Runbook

**Format:** speaking prompts; not verbatim narration

**Recording:** one numbered segment per clip

**Target runtime:** 18–24 minutes after editing

**Clip ceiling:** 90 seconds; split any longer take

**Story:** specification → governed plan → working software → controlled change

**Audience:** launch viewers, new technical evaluators, prospective contributors

## Recording Contract

- Bullet fragments only
- One claim per beat
- One visible proof per claim
- Real artifacts over feature lists
- Command start and completed result as separate takes
- LLM wait time removed in edit
- No secrets, home-directory details, tokens, or private repository tabs
- No unrehearsed mutation of the prepared demo Target
- Canonical terms throughout:
  - Commander — product owner
  - Crew — LLM delivery team
  - Target — governed project workspace
  - Blueprint — authoritative Typed Specifications
  - Manifest — executable dependency graph
  - Frontier — runnable Manifest work
  - QuarterDeck — Commander review console
  - Compass — persistent Commander guidance
  - Soundings — criterion-level verification
  - Sea Trials — project-level release objectives
  - Refit — controlled change loop

## Demo Variables

- `<Target>` — prepared Drydock Target
- `<Source>` — prepared Markdown/specification source directory
- `<Build>` — generated application directory
- `<App URL>` — running generated application
- `<QuarterDeck URL>` — URL printed by `drydock run quarterdeck <Target>`
- `<Feature>` — one visually demonstrable feature
- `<Ticket>` — one prepared change ticket; already tested before filming

## Preflight — Do Not Record

- Repository state
  - Known commit captured
  - `drydock --version` confirmed
  - Demo Target backed up or reproducible
  - Generated application at known-good revision
- Browser windows
  - Slide deck: `docs/presentation2/deck.html`
  - Web Cloud Studio: <https://webcloudstudio.com/>
  - GitHub: <https://github.com/webcloudstudio/Drydock>
  - QuarterDeck: `<QuarterDeck URL>`
  - Generated application: `<App URL>`
- Editor tabs
  - Source specification
  - `ANALYSIS.md`
  - `SEA_TRIALS.md`
  - one Compass file
  - one typed Blueprint file
  - `MANIFEST.md`
  - `SOUNDINGS.md`
  - prepared change ticket
- Terminal tabs
  - Drydock repository
  - Target workspace
  - generated application
- Presentation mode
  - Browser notifications off
  - Editor minimap off
  - Font large enough for 1080p playback
  - Terminal history cleared of private paths
  - Deck fullscreen key: `F`
- Proof rehearsal
  - Tests pass
  - QuarterDeck pages load
  - Application starts
  - Chosen feature works
  - Refit result available even if live command fails

## Clip 01 — Opener: From Claim to Proof

- **Length:** 35–50 seconds
- **Scene:** deck slide 1; optional talking-head inset
- **Opener beats:**
  - Follow-up to the Drydock launch overview
  - Previous video — why the process exists
  - This video — how the process works on a real project
  - Starting point — human-readable specifications
  - Ending point — running, tested software
  - Harder proof — controlled change after the first build
- **Visual beats:**
  - Trace slide pipeline left to right
  - Pause on “Commander review”
  - Pause on “Working software”
- **Anchor line:**
  - “This time, the product does the talking.”
- **Cut:** clean pause; advance to slide 2

## Clip 02 — Agenda and SAIL Route

- **Length:** 30–45 seconds
- **Scene:** deck slide 2
- **Talking points:**
  - Intro
    - Specification-driven development gap
    - Drydock operating model
  - Walkthrough
    - Set Up
    - Analyze
    - Implement
    - Loop
  - Status
    - Implemented alpha path
    - Unstable 0.x contracts
    - Where to install, inspect, and contribute
- **Expectation setting:**
  - Minimal slides
  - Real terminal, files, QuarterDeck, and application
  - Long-running model calls shown as start/result cuts
- **Transition:**
  - “First, the one-minute mental model.”
- **Cut:** switch from deck to Web Cloud Studio

## Clip 03 — Context: What Drydock Adds

- **Length:** 55–75 seconds
- **Scene:** Web Cloud Studio Drydock documentation or project page
- **Talking points:**
  - SDD strength
    - Behavior defined before implementation
    - Specification as durable product authority
  - SDD gap
    - Large specification ≠ executable build order
    - Model context limits
    - Non-deterministic generation
    - Maintenance after initial generation
  - Drydock addition
    - Agile decomposition
    - TDD acceptance
    - human review
    - dependency graph
    - context-managed execution
    - persisted evidence
- **Avoid:**
  - Long history of Agile
  - Competitive teardown
  - “One prompt builds everything” implication
- **Visible proof:** SAIL documentation headings
- **Transition:**
  - “The process has four phases: Set Up, Analyze, Implement, Loop.”

## Clip 04 — Project Orientation and Honest Status

- **Length:** 55–75 seconds
- **Scene:** GitHub repository landing page
- **Talking points:**
  - Installable Python CLI
  - Open source; MIT licensed
  - Subscription-authenticated Claude or Codex CLI
  - No API-key-backed model path
  - Current release: `0.1.4` alpha
  - Primary SAIL path implemented
  - Command surface and Typed Specification contracts unstable during `0.x`
- **Screen actions:**
  - Show badges and install command
  - Show “60-Second Example” command sequence
  - Show “Current Release Status” heading
  - Brief repository tree: `src/`, `Rigging/`, `prompts/`, `tests/`, `docs/`
- **Follow-up announcement pattern:**
  - Continuity — earlier launch
  - Proof — deeper live workflow
  - Progress — current alpha state
  - Invitation — users and contributors
- **Transition:**
  - “Now I will run that command sequence against one prepared Target.”

## Clip 05 — S: Installation and Configuration

- **Length:** 60–80 seconds
- **Scene:** terminal
- **Commands:**

  ```bash
  drydock --version
  drydock config show
  drydock status
  ```

- **Talking points:**
  - Package name — `drydock-sdd`
  - Installed command — `drydock`
  - Python 3.11+
  - Two configured roots
    - Drydock workspace — Targets, Blueprints, plans, evidence
    - Build directory — generated applications
  - Provider CLI already authenticated
  - Orientation before mutation — `drydock status`
- **Optional install visual only:**

  ```bash
  uv tool install drydock-sdd
  # or: pipx install drydock-sdd
  ```

- **Do not:** reinstall during the take
- **Visible proof:** version + sanitized configuration + Target list
- **Cut point:** command output stable on screen

## Clip 06 — S: Initialize the Target

- **Length:** 40–60 seconds
- **Scene:** terminal, then editor file tree
- **Command shape:**

  ```bash
  drydock init <Target> --display-name "<Display Name>" --description "<Description>"
  drydock status <Target>
  ```

- **Talking points:**
  - Target — governed workspace for one project
  - Lifecycle begins at `init`
  - Target artifacts separate from generated application
  - QuarterDeck configuration created with the Target
- **Screen actions:**
  - Prefer prepared Target
  - Show equivalent command; do not recreate live
  - Expand Target root
  - Show `METADATA.md`, Compass files, `blueprint/`, `QuarterDeck/`
- **Recovery:**
  - Duplicate Target error — cut to prepared Target
- **Transition:**
  - “A Target is empty governance; source material gives it intent.”

## Clip 07 — A: Import Source Material

- **Length:** 55–75 seconds
- **Scene:** editor, then terminal
- **Command shape:**

  ```bash
  drydock import <Target> <Source> --format markdown
  ```

- **Talking points:**
  - Input can begin as Markdown, source, Spec Kit, Compass, or intent material
  - Imported source preserved under Drydock control
  - Imported text not yet a conformed Blueprint
  - Specification creation outside Drydock’s core scope
  - Drydock begins at intake and delivery governance
- **Screen actions:**
  - Open one concise source specification
  - Show intent, behavior, constraint, acceptance idea
  - Show preserved `blueprint/sources/` material
- **Visible proof:** source before analysis
- **Transition:**
  - “Import preserves the material; analyze turns it into a planning session.”

## Clip 08 — A: Analyze Into Agile Work

- **Length:** 70–90 seconds
- **Scene:** terminal invocation; hard cut; editor result
- **Command:**

  ```bash
  drydock analyze <Target>
  ```

- **Before-command points:**
  - Crew receives source + persistent Commander guidance
  - Expected outputs
    - stories
    - acceptance milestones
    - blockers
    - questions
    - release objectives
- **After-command screen actions:**
  - Open `ANALYSIS.md`
  - Show quality signal: Blocked / Questions / Ready
  - Show story decomposition
  - Open `SEA_TRIALS.md`
  - Show stable project-level success criteria
- **Core claim:**
  - Missing decision surfaced; not silently invented
- **Blocker behavior:**
  - `BLOCKERS.md` present — answer and rerun analyze
  - No `BLOCKERS.md` — planning may proceed
- **Edit:** remove model wait; retain command start and completion summary

## Clip 09 — A: Commander Review in QuarterDeck

- **Length:** 75–90 seconds
- **Scene:** QuarterDeck browser
- **Command:**

  ```bash
  drydock run quarterdeck <Target>
  ```

- **Talking points:**
  - Commander — product owner
  - Crew output — proposal, not invisible authority
  - QuarterDeck — review and decision surface
  - Running next phase — approval signal
- **Screen route:**
  - Commander’s Chair
    - mission
    - lifecycle state
    - recommended next command
  - Analysis
    - story hierarchy
    - questions
    - blockers
  - Questionnaires
    - intent
    - stack
    - gaps and acceptance
    - guardrails
  - Compass
    - project guidance
    - analyze guidance
    - plan guidance
- **Visible proof:** edit or show one persisted Commander answer
- **Avoid:** touring every sidebar item
- **Transition:**
  - “Review resolves the decisions; plan turns them into authority and execution order.”

## Clip 10 — A: Plan the Blueprint

- **Length:** 65–85 seconds
- **Scene:** terminal invocation; hard cut; editor file tree
- **Command:**

  ```bash
  drydock plan <Target>
  ```

- **Talking points:**
  - Reviewed analysis as planning input
  - Typed Specification output
    - `ARCHITECTURE.md`
    - `DATABASE.md`
    - `FEATURE-*.md`
    - `SCREEN-*.md`
    - `UI-GENERAL.md`
  - Blueprint — authoritative product definition
  - Each file — prescribed role and terminal contract
    - Programmatic Acceptance
    - User Acceptance
    - Guardrails
    - Open Questions
- **Screen actions:**
  - Open one feature Blueprint
  - Show header metadata
  - Show `Provides`, `Consumes`, or `Depends On`
  - Show one Programmatic Acceptance assertion
- **Core distinction:**
  - Blueprint — what the product is
  - Manifest — how the build proceeds

## Clip 11 — A: Read the Manifest as a Graph

- **Length:** 75–90 seconds
- **Scene:** QuarterDeck Build Compass or editor `MANIFEST.md`
- **Talking points:**
  - Manifest — executable dependency graph; not flat task list
  - Block types
    - story
    - spike
    - change
    - legacy acceptance block
  - Graph fields
    - identity
    - dependency
    - implementation scope
    - context
    - state
  - Frontier — work runnable now
  - Grouping — related work sharing context
  - Ordering — Commander priority within dependency legitimacy
- **Screen actions:**
  - Show one foundational block
  - Show one dependent block
  - Trace `depends:` edge
  - Show pending / buildable / verified state
  - Show grouping or cost signal in QuarterDeck
- **Anchor:**
  - “The Blueprint is authority; the Manifest is execution.”
- **Transition:**
  - “Implement walks only the runnable frontier.”

## Clip 12 — I: Preview the Build Context

- **Length:** 55–75 seconds
- **Scene:** terminal
- **Commands:**

  ```bash
  drydock build status <Target>
  drydock build <Target> --dry-run --show-prompt
  ```

- **Talking points:**
  - Status before execution
  - Current runnable frontier
  - One focused graph step
  - Prompt assembly from
    - implementing Blueprint slice
    - applicable dependencies
    - Rigging
    - Compass guidance
    - acceptance contract
  - Context engineered per step
- **Screen actions:**
  - Show frontier IDs
  - Show prompt headings; avoid scrolling full prompt
  - Point out included and omitted context
- **Security check:** no private prompt material visible
- **Transition:**
  - “The preview explains the work; the next command executes it.”

## Clip 13 — I: Build One Frontier

- **Length:** 65–90 seconds
- **Scene:** terminal invocation; hard cut; editor and terminal result
- **Command:**

  ```bash
  drydock build <Target>
  ```

- **Before-command points:**
  - One runnable step or grouped block
  - Provider CLI performs real implementation work
  - Module writes controlled outputs
  - Evidence persists outside the model response
- **After-command proof:**
  - Manifest state transition
  - generated or changed application files
  - matching test file
  - execution evidence directory
  - updated build status
- **Commands after completion:**

  ```bash
  drydock build status <Target>
  ```

- **Avoid:** terminal progress as the proof
- **Core proof:** code + test + Manifest state + evidence
- **Recovery:** live provider failure — show previously completed block and recorded evidence; state “completed run”

## Clip 14 — I: Verify Acceptance and Evidence

- **Length:** 65–85 seconds
- **Scene:** terminal, then QuarterDeck or editor
- **Commands:**

  ```bash
  drydock score ac <Target>
  drydock score release <Target>
  ```

- **Talking points:**
  - Story acceptance — deterministic Programmatic Acceptance
  - Soundings — per-criterion state and evidence
  - Sea Trials — product-level objectives
  - Release score — release-readiness evaluation
  - Proof integrity — passing test must actually prove behavior
- **Screen actions:**
  - Run or show completed `score ac`
  - Open `SOUNDINGS.md`
  - Trace one criterion to evidence
  - Open `SCORECARD.md`
  - Show pass / fail / unverified distinctions
- **Avoid:** claiming an alpha score equals production certification
- **Transition:**
  - “Artifacts prove the process; the application proves the result.”

## Clip 15 — I: Run the Working Application

- **Length:** 75–90 seconds
- **Scene:** application browser; optional terminal inset
- **Talking points:**
  - Same Target
  - Same Blueprint
  - Same Manifest execution
  - Working behavior, not generated text
- **Screen route:**
  - Health endpoint or startup proof
  - Primary application screen
  - One feature from the demonstrated Blueprint
  - One edge case or validation path
- **Traceability beat:**
  - Feature behavior on screen
  - Corresponding Blueprint criterion
  - Corresponding automated test
- **Visual priority:** application full screen
- **Avoid:** broad product tour of the demo application
- **Cut point:** successful feature result held for two beats

## Clip 16 — Cross-Cutting: Rigging and Context Control

- **Length:** 55–75 seconds
- **Scene:** editor split view
- **Talking points:**
  - Rigging — portfolio governance
  - Business rules
  - stack guidance
  - branding
  - standard templates
  - Full context for a builder
  - Compact interface context for a consumer
  - Less irrelevant context in downstream work
- **Screen actions:**
  - Show `Rigging/` categories
  - Show one full file beside compact derivative
  - Highlight interfaces retained; rationale removed
- **Optional command:**

  ```bash
  drydock rigging compact <Target>
  drydock rigging verify <Target>
  ```

- **Anchor:**
  - “Context is selected by role, not accumulated by habit.”

## Clip 17 — L: Refit a Controlled Change

- **Length:** 75–90 seconds
- **Scene:** editor, QuarterDeck, terminal
- **Talking points:**
  - First build — beginning of ownership
  - Two governed change inputs
    - changed Blueprint
    - change ticket under `blueprint/changes/`
  - Ticket `Amends:` — parent Blueprint relationship
  - Refit — dependency impact + Manifest reset
  - Normal build path reused
- **Screen actions:**
  - Open prepared `<Ticket>`
  - Show intent
  - Show `Amends:` target
  - Show changed or reset Manifest block
- **Commands:**

  ```bash
  drydock refit <Target>
  drydock build status <Target>
  drydock build <Target>
  ```

- **Do not:** author an untested ticket live
- **Core claim:** change enters the graph; change does not bypass the process
- **Transition:**
  - “The same acceptance path now proves the changed product.”

## Clip 18 — L: Prove the Change

- **Length:** 55–80 seconds
- **Scene:** tests, application, and Manifest state
- **Talking points:**
  - Changed behavior visible
  - Existing behavior still verified
  - Ticket tied to specification authority
  - Impacted graph path rebuilt
  - Unaffected work preserved
- **Proof sequence:**
  - Focused test
  - full project test summary
  - changed application behavior
  - Manifest verified state
  - updated Soundings or evidence
- **Avoid:** code-diff deep dive
- **Anchor:**
  - “This is the maintenance loop: specify, map, rebuild, verify.”

## Clip 19 — Status: What Exists Now

- **Length:** 60–80 seconds
- **Scene:** GitHub README “Current Release Status”
- **Implemented alpha path:**
  - configuration and Target initialization
  - source import
  - analysis and planning
  - QuarterDeck review
  - typed Blueprint generation
  - Manifest-frontier build
  - evidence capture
  - acceptance and release scoring
  - Refit change handling
  - Rigging
  - project documentation
- **Current boundaries:**
  - `0.x` command contracts unstable
  - Typed Specification contracts unstable
  - Alpha evaluation expected
  - Commander review still mandatory
  - Generated software still requires normal security, testing, and operational review
- **Invitation:**
  - Install
  - build a small real Target
  - report issues with reproducible artifacts
  - contribute Rigging for tested stacks
- **Transition:** return to deck slide 3

## Clip 20 — Closer: Take It for a Sail

- **Length:** 35–55 seconds
- **Scene:** deck slide 3; optional talking-head inset
- **Closer beats:**
  - Drydock claim — process layer for SDD
  - Proof shown
    - source material
    - Commander review
    - Blueprint authority
    - Manifest execution
    - working software
    - verified change
  - Current truth — implemented alpha, evolving contracts
  - Single ask — try one real project; report the voyage
- **Links on screen:**
  - <https://webcloudstudio.com/>
  - <https://github.com/webcloudstudio/Drydock>
- **Closing line:**
  - “Own the specification. Steer the build. Take it for a sail.”
- **End:** two silent beats on links; no extra sign-off

## Edit Assembly

- 01–02 — 1:15 maximum
- 03–04 — 2:30 maximum
- 05–07 — Set Up and intake — 3:00 maximum
- 08–11 — Analyze and plan — 5:00 maximum
- 12–16 — Implement and proof — 6:30 maximum
- 17–18 — Loop and changed proof — 3:00 maximum
- 19–20 — Status and close — 2:00 maximum
- Final target — 18–24 minutes

## Required Cutaways

- SAIL section in public documentation
- GitHub install example
- imported source specification
- `ANALYSIS.md`
- QuarterDeck Commander’s Chair
- one answered questionnaire or Compass decision
- typed Blueprint file
- Manifest dependency edge
- build status frontier
- generated implementation and matching test
- build evidence
- `SOUNDINGS.md`
- working application feature
- full/compact Rigging comparison
- change ticket and reset Manifest work
- changed application behavior
- alpha status and public links

## Recovery Lines

- Long model run
  - “I will cut from invocation to the completed artifacts.”
- Existing prepared Target
  - “This Target is prepared so the walkthrough can focus on the artifacts.”
- Command already completed
  - “Here is the persisted result from that run.”
- Live provider failure
  - “The provider run failed; Drydock preserved the failure evidence and left the work reviewable.”
- Application startup delay
  - “The application is already running in the prepared browser session.”
- Unexpected UI state
  - “The underlying Markdown artifact remains the record; I will show it directly.”

## Claims to Avoid

- Deterministic model output
- Fully autonomous software delivery
- Production readiness from a passing build alone
- Universal stack support
- Stable command contracts before `1.0`
- Zero human review
- Zero drift
- Guaranteed lower total cost
- Reproducible bytes from non-deterministic generation

## Short Follow-Up Announcement Copy

- Drydock follow-up walkthrough
- Less deck; more working system
- Full SAIL path
  - import
  - analyze
  - Commander review
  - plan
  - build
  - verify
  - refit
- Real Target
- Real artifacts
- Real running application
- Current alpha status
- Watch: `<video URL>`
- Project: <https://github.com/webcloudstudio/Drydock>
- Documentation: <https://webcloudstudio.com/>
