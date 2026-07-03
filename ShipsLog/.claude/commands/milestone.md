---
description: Draft a monthly milestone article from the month's notes and CHANGELOG
---

You are operating the dev-blog framework in this repository. Produce one **monthly
milestone article** (`milestone`) for the public blog.

Steps:

1. Read `blog/GENERATION.md` and `blog/DISCLOSURE.md` in full.
2. Read every post in `blog/posts/` from the last ~30 days and the source project
   `CHANGELOG.md`. Synthesise the period's decisions into one thesis about
   architecture, methodology, or lessons learned — not a list of updates.
3. Write a 500–900 word `milestone` following the output format in `GENERATION.md`.
   A few subheadings are allowed for this type.
4. Save to `blog/drafts/<date>-<slug>.md`, run `python3 scripts/check_disclosure.py`
   on it, and report the result.
5. Show me the full draft and ask for approval. **Do not publish without approval.**
   On approval, run `scripts/publish.sh blog/drafts/<file>.md`.

Hard rules: no private implementation details, no code identifiers, no file paths.
$ARGUMENTS
