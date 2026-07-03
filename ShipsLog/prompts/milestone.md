# Codex prompt: milestone
#
# Copy to ~/.codex/prompts/milestone.md to invoke as /milestone inside Codex,
# or paste the body into a Codex session from this package's root (Drydock/ShipsLog).

Operate the dev-blog framework in this repository to produce one monthly milestone
article (milestone).

1. Read `blog/GENERATION.md` and `blog/DISCLOSURE.md` in full.
2. Run `python3 scripts/run.py --all --period-days 30 --type milestone`
   if you are executing the pipeline directly. Source defaults to the Ship's Log
   path configured in `blog.config.sh`.
3. Otherwise, read every post in `blog/posts/` from the last ~30 days and `blog/material/<today>.md`.
   Synthesise the period into one thesis about architecture, methodology, or lessons
   — not a list of updates.
4. Write a 500–900 word milestone following the output format in GENERATION.md.
   A few subheadings are allowed for this type.
5. Save to `blog/posts/<date>-<slug>.md`, run
   `python3 scripts/check_disclosure.py <that file>`, and report the result.
6. Show me the full draft and wait for approval. Do not publish without it.
   On approval, run `scripts/publish.sh blog/posts/<file>.md`.

Hard rules: no implementation details, no code identifiers, no file paths.
