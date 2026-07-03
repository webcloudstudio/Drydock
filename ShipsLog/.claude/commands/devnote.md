---
description: Draft a disclosure-safe short development note from recent source-repo work
---

You are operating the dev-blog framework in this repository. Produce one **short
development note** (`devnote`) for the public blog.

Steps:

1. Run `scripts/collect.sh` to refresh the private daily log and gather material.
2. Read `blog/GENERATION.md` and `blog/DISCLOSURE.md` in full. They are the rules.
3. Read the source project `CHANGELOG.md` `[Unreleased]` section and the commits
   since the most recent file in `blog/posts/` (use the `date:` of the newest post
   as the `--since` bound). The source repo path is `SOURCE_REPO` in `blog.config.sh`.
4. Choose the single most blog-worthy completed decision. Write it as a `devnote`
   following the five-part shape and the output format in `GENERATION.md`.
5. Save it to `blog/drafts/<date>-<slug>.md`.
6. Run `python3 scripts/check_disclosure.py` on the new draft and report the result.
7. Show me the full draft and ask for approval. **Do not publish without approval.**
   On approval, run `scripts/publish.sh blog/drafts/<file>.md`.

Hard rules: no private implementation details, no code identifiers, no file paths.
Teach a transferable principle or do not publish. $ARGUMENTS
