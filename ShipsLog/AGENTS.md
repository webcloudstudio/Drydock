# AGENTS.md — Dev-blog framework (Codex)

This repository turns private development work into a public, disclosure-safe
developer blog for edbarlow.net. Claude and Codex operate it identically; both
defer to the same spec so the output does not depend on which tool ran.

## The contract

The rules for every post live in two files. Read them before writing anything:

- `blog/GENERATION.md` — what to read, the five-part shape of a note, cadence,
  and the exact output format.
- `blog/DISCLOSURE.md` — the hard safety rules. These override everything.

Do not restate or fork these rules here. If a rule must change, change it there.

## Workflows

There are only two persistent working surfaces:

- `blog/material/` — assembled source material from Ship's Log
- `blog/posts/` — rewritten Markdown posts plus optional sibling `.html` previews

**Short development note** (default, 1–3 per week) — see `prompts/devnote.md`:

1. Preferred path: run `python3 scripts/run.py`. It defaults to a weekly batch from the
   Ship's Log path configured in `blog.config.sh`, resumes from the saved cursor, makes
   one subscription-backed rewrite call, writes one post into `blog/posts/`, and rebuilds
   the local preview index.
2. Manual path: run `python3 scripts/create.py` to persist `blog/material/<label>.md`,
   then run `python3 scripts/format.py blog/material/<label>.md`, then
   `python3 scripts/render.py blog/posts/<file>.md`.
3. Run `python3 scripts/check_disclosure.py blog/posts/<file>.md` and report.
4. Present the post for approval. **Never publish externally without explicit approval.**
   On approval, use whatever higher-level deployment process the host project owns.

**Monthly milestone** — see `prompts/milestone.md`. Same gate.

## Source of material

`SHIPS_LOG` in `blog.config.sh` points at the Drydock ship's log (`../logs/ships_log.jsonl`
relative to this package). The material
already contains rationale; mine the *why* of a decision, never the *how* of the
implementation.

## Non-negotiable

No source file paths, code identifiers, API shapes, config keys, secrets, or
internal names. A post must teach a transferable engineering principle or it is
not published. No cryptic status reports.
