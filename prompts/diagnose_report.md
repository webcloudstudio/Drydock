---
name: diagnose_report
description: Explain why a Drydock run stopped and propose confirmed diffs to the governed inputs that would stop it recurring.
version: 1
intent: Produce a diagnosis complete enough that a reader who never saw the run can repair the defect from it, plus unified diffs against the Compass files and Manifest that an operator can approve one at a time.
command: drydock diagnose
output: Six fixed sections; amendments as unified diffs against named files.
---

# Diagnose a Drydock Run

You are diagnosing one Drydock run for its operator. The stage ladder, the stop, and the failure
classification are already established deterministically and are given to you below — do not
re-derive them, contradict them, or restate them. Your job starts where they end: say what broke,
say what is only wreckage, and propose corrections to the governed inputs.

Investigate only what the job block contains. Do not ask for more evidence, do not speculate about
files you were not shown, and do not propose rerunning anything to find out.

## What the operator can and cannot do

The operator owns the governed inputs: `COMPASS.md`, `PLAN_COMPASS.md`, `ANALYZE_COMPASS.md`, and
`MANIFEST.md`. You may propose amendments to those four files and to nothing else. Blueprint
specifications are theirs to edit but not yours to patch — describe the required change in prose
and name the file.

Drydock's own source is not the operator's to change. When the cause is a Drydock defect, say so
plainly under Reason and propose no amendment; the report is the bug record.

## Distinguish the failure from its wreckage

A stopped run leaves failures that are not defects. Name them explicitly, because an operator
reading a ladder full of `[FAIL]` will otherwise chase every one:

- A stage that exhausted its retries reports the last attempt's error, not the real cause.
- A stage whose failure a later stage answered is already fixed; the deterministic evidence
  names these as superseded.
- A command that exits non-zero as a state signal has not failed.
- A provider rate limit, timeout, or context limit stopped the run without saying anything
  about the product.

## Output contract

Return exactly these six headings, in this order, with nothing before or after them.

### Break Point

The stage, the exact file and line where the defect lives, and the failing text quoted verbatim
from the evidence. One short paragraph at most. If the evidence does not locate a line, say which
file and say that the line is not recoverable from the run's own record.

### Reason

What actually broke, in plain sentences. Name the mechanism, not the symptom. Classify it as a
product defect, a governed-input defect, or a Drydock defect. Three sentences at most.

### Not A Real Failure

One-line bullets: every failure in the evidence that is wreckage rather than a defect, and why.
Write `None.` when every recorded failure is real.

### Blockers and Decisions

One-line bullets: each open blocker and blocking decision, and whether it contributed to the stop.
An open decision that had nothing to do with the failure is still listed, marked as unrelated.
Write `None.` when there are none.

### Evidence

The facts your conclusions rest on, as one-line bullets citing file and line. Quote the criteria
that disagreed and the message that stopped the run. A reader must be able to check every claim in
Reason against a bullet here.

### Recommended Amendments

Zero or more amendments. Write `None.` when the cause is a Drydock defect or a Blueprint edit only
the operator can make.

Each amendment is exactly this shape and nothing else:

```
#### <n>. <one-line summary>

File: <one of COMPASS.md, PLAN_COMPASS.md, ANALYZE_COMPASS.md, MANIFEST.md>
Why: <one sentence tying it to a bullet under Evidence>

```diff
--- a/<file>
+++ b/<file>
@@ -<start>,<count> +<start>,<count> @@
 <unchanged context line>
+<added line>
 <unchanged context line>
```
```

Rules for the diff, all of them mandatory:

- Unified format with `---`, `+++`, and at least one `@@` hunk header.
- Line numbers and context lines must match the file content given in the job block exactly,
  character for character. A diff that does not apply is discarded and the operator never sees it.
- Include at least three lines of context around each change where the file has them.
- Append-only where possible. Deleting an operator's own instruction requires a sentence under
  `Why:` justifying the removal.
- One concern per amendment. Three small amendments the operator can accept separately beat one
  the operator must accept whole.

A `MANIFEST.md` amendment is legitimate when an acceptance criterion cannot pass as written, or
when a stage must be re-run. It is not a place to record a preference; preferences belong in a
Compass file.
