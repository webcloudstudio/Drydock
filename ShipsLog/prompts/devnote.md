# Codex prompt: devnote
#
# Copy to ~/.codex/prompts/devnote.md to invoke as /devnote inside Codex,
# or paste the body into a Codex session from this package's root (Drydock/ShipsLog).

Operate the dev-blog framework in this repository to produce one short development
note (devnote).

1. Run `python3 scripts/run.py --period-days 0 --limit 1 --type devnote`
   if you are executing the pipeline directly. Source defaults to the Ship's Log
   path configured in `blog.config.sh`.
2. Otherwise, read `blog/GENERATION.md` and `blog/DISCLOSURE.md` in full — they
   are the rules — then read `blog/material/<today>.md`.
3. Pick the single most blog-worthy completed decision and write it as a devnote
   following the five-part shape and output format in GENERATION.md.
4. Save to `blog/posts/<date>-<slug>.md`, then run
   `python3 scripts/check_disclosure.py <that file>` and report the result.
5. Show me the full draft and wait for approval. Do not publish without it.
   On approval, run `scripts/publish.sh blog/posts/<file>.md`.

Hard rules: no implementation details, no code identifiers, no file paths. Teach a
transferable principle or do not publish.
