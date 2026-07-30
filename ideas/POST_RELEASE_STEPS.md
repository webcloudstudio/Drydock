# Post-Release Steps — Visibility and Adoption

**Status:** Working plan. Check items off in place.
**Date:** 2026-07-30
**Owner:** Ed Barlow
**Goal:** Move Drydock from "published" to "used by people who are not me."

---

## 0. Diagnosis

Several posts to r/SpecDrivenDevelopment produced few hard hits. Three causes, in order of
impact:

1. **Channel.** A small subreddit is a low-traffic venue, and repeated self-posts into one small
   venue is the lowest-yield distribution pattern available. The audience there already believes
   in specification-driven development; the people with the pain do not know the category name.
2. **Pitch.** "The missing process layer for specification-driven development" is a category
   claim. A reader needs a pain claim: their agent forgets, contradicts itself, and cannot prove
   what it built.
3. **Activation cliff.** The old README asked for four configuration commands and nine
   subcommands before anything happened, plus eight pieces of new vocabulary. Evaluation stops
   long before value appears.

**Governing rule:** fix the front door before spending another post. Traffic to a page that does
not convert is wasted twice — the post and the audience.

---

## 1. Phase 1 — Front Door

Nothing else in this plan may start until this phase is complete.

- [x] Benefit-first tagline replacing the category claim.
- [x] Whole-command-surface graphic (`docs/drydock_process.svg` / `.png`) at the top of the README.
- [x] Collapse the duplicated quickstart; hero install is two lines.
- [x] Link the Product Comparison Matrix from `Why It Is Different`.
- [ ] Put the process graphic on webcloudstudio.com in place of the autoplay video. Video below
      the fold, as a secondary option, never as the primary explanation.
- [ ] Record a 60–90 second asciinema or terminal GIF of one real run. Place it directly under
      the process graphic in the README. No music, no titles, no editing beyond trimming dead
      time.
- [ ] Read the README top-to-bottom as a stranger. Delete every sentence that does not earn its
      place before the reader has decided to try it.
- [ ] Move the vocabulary (Blueprint, QuarterDeck, Rigging, Soundings, Sea Trials, Commander)
      below the first call to action. The metaphor is an asset after commitment and a tax before
      it.
- [ ] Verify a clean install on a machine with no Drydock configuration:
      `uv tool install drydock-sdd && drydock init MyApp`. Every prompt, error, and missing
      prerequisite the new user hits gets fixed or documented. This is the highest-value
      engineering work in the plan.

**Exit criterion:** a stranger can state what Drydock does for them after ten seconds on the
README.

---

## 2. Phase 2 — Proof Assets

Drydock's structural advantage over every competitor is that it produces receipts. Nobody in
this space shows them. Show them.

- [ ] Choose the reference project. Small, real, comprehensible in one sitting, not a to-do app.
      The CommonMark work (`c3.sh`) or a scoped slice of Marina are candidates.
- [ ] Build it end to end with Drydock. Do not hand-correct; if it fails, fix Drydock.
- [ ] Publish as a public repository, `drydock-example-<name>`, containing the generated
      application **and** the Blueprint, `MANIFEST.md`, `SOUNDINGS.md`, `SCORECARD.md`, and the
      run logs.
- [ ] Write the `README` of that repo as a guided tour: here is the specification, here is the
      graph, here is the step that built this file, here is the evidence it was verified.
- [ ] Link it from the Drydock README hero. This is the single strongest asset in the plan.
- [ ] Optional and high-value: the **rework experiment**. Build the same small application three
      ways — unstructured agent prompting, Spec Kit, Drydock. Measure something honest: rework
      rate, steps to green tests, time to first correct build. Publish the numbers even where
      Drydock loses. Credibility from an unfavorable number exceeds any favorable claim.

---

## 3. Phase 3 — Content That Is Not An Announcement

"Check out my tool" is ignored. Artifacts are not. Each item below is a standalone piece of
value that mentions Drydock as a footnote.

- [ ] **Publish the comparison matrix publicly.** `docs/Product_Comparison_Matrix.md` is
      currently inert. Drydock vs. GitHub Spec Kit vs. Kiro vs. BMAD vs. a plain `CLAUDE.md`,
      explicit about where each one wins. Highest-traffic content type in this niche, ranks in
      search, gets linked by others, and does not read as promotion when it is honest.
- [ ] **"Roast my specification format."** Post the Typed Specification and ask for
      destruction. Asking for critique outperforms asking for adoption by roughly an order of
      magnitude, and the people who show up to criticize are the first real users.
- [ ] **"Why I made my agent write acceptance criteria before code."** Teachable post, tool as
      a footnote.
- [ ] **Convert the video assets to text.** The 10-minute overview and the tutorial become
      written posts with embedded stills. Text indexes in search; video does not, and nobody on
      Reddit or HN clicks a video from a stranger.
- [ ] **Cut 30–60 second vertical clips** from the existing videos for LinkedIn and X.
- [ ] **Syndicate** each written post: webcloudstudio.com canonical, then dev.to and Hashnode
      with canonical tags pointing home.

---

## 4. Phase 4 — Channels

Ordered by expected yield. Do not open a channel before Phase 1 is complete.

| Channel | Post type | Notes |
|---|---|---|
| **Hacker News (Show HN)** | Launch | One shot. Draft prepared in `ideas/SHOW_HN_POST.md`. Tue–Thu, 08:00–10:00 ET. Block the whole day. |
| **r/ClaudeAI, r/ChatGPTCoding** | Problem post | Far larger than r/SpecDrivenDevelopment and directly on the pain. Lead with the problem. |
| **r/ExperiencedDevs** | Teachable post | Hostile to promotion, receptive to hard-won process. Never link-drop. |
| **LinkedIn** | Case study, clips | Underused given your profile. Engineering leadership is the buyer persona and your credentials carry there. |
| **Lobste.rs** | Launch | Requires an invite. Worth acquiring. |
| **r/programming, r/LocalLLaMA** | Comparison, experiment | Data-driven posts only; announcements die. |
| **Discords/forums for agent tooling** | Participation | Contribute value for weeks before ever mentioning Drydock. |
| **r/SpecDrivenDevelopment** | Continued presence | Keep it, but it is a secondary venue, not the strategy. |

Rules for all channels:

- [ ] Never post the same text to two venues. Rewrite for each audience.
- [ ] Never respond to criticism with defense. Concede, ask a question, thank them.
- [ ] Never link-drop into a competitor's issue tracker or community. Answer the question that
      was asked; mention Drydock only if it is directly responsive.

---

## 5. Phase 5 — Cadence

One artifact per week for six weeks, each pointing back to the worked example. Sustained
presence beats any single launch.

- [ ] Week 1 — Comparison matrix published.
- [ ] Week 2 — Worked-example repository announced.
- [ ] Week 3 — "Roast my specification format."
- [ ] Week 4 — Show HN.
- [ ] Week 5 — Tutorial written up as text.
- [ ] Week 6 — Rework-rate experiment with numbers.
- [ ] Week 7 — Review the measurements below and decide whether to continue, change the pitch,
      or stop.

---

## 6. Measurement

Stars are vanity. Track these instead, weekly, in one place.

| Metric | Source | Meaning |
|---|---|---|
| PyPI downloads | `pypistats recent drydock-sdd` | Did anyone install it |
| Unique repo clones | GitHub Insights → Traffic | Did anyone look at the source |
| README referrers | GitHub Insights → Referring sites | Which channel actually works |
| Issues and discussions opened by strangers | GitHub | **The only metric that matters.** A stranger filing an issue used the tool. |
| Second-run rate | Manual, from issue and discussion content | Did anyone run `drydock build` twice |

- [ ] Set up the weekly measurement note. One file, one table, appended weekly.
- [ ] Decide on opt-in anonymous telemetry: implement, or explicitly decide against it and stop
      reconsidering.

---

## 7. Not Doing

Recorded so these do not get relitigated:

- Paid advertising. The audience is too small and too ad-blind for it to pay back.
- Renaming the nautical vocabulary. It is a genuine identity asset; the fix is sequencing, not
  removal.
- Chasing star counts.
- A Discord or community server before there are users. An empty server is negative signal.
- Changing the subscription-CLI-only stance to court a wider audience. It is a real
  differentiator and the economics behind it are sound.

---

## 8. The Uncomfortable Step

Cheaper and more informative than the next ten posts:

- [ ] Get **five senior engineers** to run the quickstart while you watch — screen share,
      silent, no help offered. Write down the exact second each one gets confused and the exact
      thing they were looking at.

If the confusion is consistently in the same place, that is the whole marketing problem and no
amount of distribution will route around it.
