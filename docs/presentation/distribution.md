# Drydock — Launch Distribution Plan

**Strategy:** host the video once (YouTube), then seed it as *text-first, link-second* into communities that punish self-promotion. Lead with substance; the video is the supporting artifact, not the pitch.

## Host (the canonical home)
- **YouTube — unlisted → public.** Upload unlisted first, share with 2–3 people for a timing/audio pass, then flip public. Title: `Drydock: specification-driven software delivery that doesn't drift`. Put the install one-liner, repo link, and the Q&A from `talking_points.md` in the description and a pinned comment. Add chapters (timestamps from `script.md`) — they make it skimmable and rank well.
- **Mirror the deck:** publish `deck.html` to GitHub Pages so people can self-pace the slides without the video. Link it from the README.

## Seed (where the right people are)
Each platform has a different bar. Rank by signal, not reach.

| Venue | How to post cleanly | Notes |
|---|---|---|
| **Hacker News** (`Show HN`) | `Show HN: Drydock – governed, spec-driven builds on your Claude/Codex CLI`. Link the **repo**, not the video. First comment = you, plain-text: the problem, what's different, what's rough, what feedback you want. | HN distrusts polished video. The repo + an honest "here's what's half-built" comment outperforms a launch reel. Post 8–10am ET weekday. |
| **r/ExperiencedDevs, r/programming, r/devtools** | Text post framing the *idea* (context engineering + spec-as-truth), video as one link among several. | r/programming tolerates links; the others want discussion. Don't cross-post identically same-day. |
| **Lobsters** | Tag `practices` / `ai`. Link the repo or a write-up, not YouTube. | Invite-only, high signal, allergic to marketing. Strongest fit for the methodology crowd. |
| **GitHub Spec Kit discussions / issues** | Engage as a peer: "here's an alternative take on the build/governance loop; imports Spec Kit projects." | The literal spec-driven-design audience. Be complementary, not combative. |
| **Spec-driven / SDD communities** (e.g. the Spec Kit Discord, AI-eng Discords, `awesome-spec-driven-development` lists) | Drop in the relevant channel with a one-paragraph "what it is + link." Submit a PR to the awesome-list. | Durable backlinks; reaches exactly the searchers you want. |
| **dev.to / Hashnode** | Cross-post a written version of the script as a tutorial with the video embedded. | SEO + a citable URL to point everyone else at. |
| **X / Mastodon / LinkedIn** | A short thread: the problem, the one-idea insight, a 30s clip, link last. | Clips of your bold lines (Slides 2, 8, 9) are the shareable units. |

## The clean-launch playbook
1. **One write-up is the hub.** A single README or dev.to post is the source of truth; everything else links to it. Don't fragment the message across platforms.
2. **Lead with the problem, not the product.** "AI code drifts from its spec — here's a context-engineering answer" travels further than "I built a tool."
3. **Ship the honest state.** These forums reward "v0, here's what works and what doesn't" over a glossy reel. Your spec already carries `TODO:`s — say so.
4. **Be present for the first 48h.** The launch is the comment thread, not the upload. Answer every reply fast; that's what converts skeptics.
5. **Don't blast simultaneously.** Stagger: HN/Lobsters day 1, Reddit day 2–3, Discords/awesome-lists ongoing. Same-hour cross-posting reads as spam and gets throttled.
6. **Make the repo the destination.** Most of these audiences click code before video. README must have: the one-idea pitch, the install line, a 60-second example, and the deck/video links.

## Pre-publish checklist
- [ ] Repo public, README leads with the insight + install one-liner.
- [ ] `deck.html` on GitHub Pages; link in README and video description.
- [ ] YouTube chapters from `script.md` timings; pinned Q&A comment.
- [ ] A single canonical write-up (README or dev.to) all posts point to.
- [ ] Replace the `github.com/<your-handle>` placeholder on Slide 14 and in the YouTube description.
