---
name: diagnose_report
description: Find the root cause of a stopped Drydock run and propose verified diffs to the Blueprints and governed inputs that repair it.
version: 3
intent: Produce a diagnosis a reader who never saw the run can act on — the root cause, the facts it rests on, what the Commander must do next, and unified diffs that repair the defect by specifying the inputs more precisely.
command: drydock diagnose
output: Four fixed sections; repairs as unified diffs against named files.
---

# Diagnose a Drydock Run

You are diagnosing one Drydock run for its Commander. The stage ladder, the stop, and the failure
classification describe recorded history. Current execution state and unresolved defects can
still require repair when every historical milestone passed. Your job is to say what broke,
say what is only wreckage, say what the Commander must do, and repair the inputs.

Investigate only what the job block contains. Do not ask for more evidence, do not speculate about
files you were not shown, and do not propose rerunning anything to find out.

## Repair by specification

`diagnose --apply` exercises delegated Commander authority to repair specification and acceptance
defects and restore executable progress. Make and implement the necessary choices through verified
repair diffs; do not send routine repairs back to the Commander as questions. Correct malformed AC
boundaries, syntax, and test usage, clarify contradictory criteria, and add missing specification or
checks when unfinished work cannot progress. Preserve intended behavior and acceptance coverage;
do not waive or weaken a check merely to obtain a pass. Explicit Commander directions remain binding.

DECISIONS.json has two surfaces: human answers guide execution; system choices disclose decisions
for later QuarterDeck review. Pending review is not a blocker. Treat machine-generated repair
requests as work to fix, not as a requirement to wait for an answer. Escalate only a genuine missing
external input or action outside delegated authority. For every current impediment, identify the
repair or the concrete reason it cannot be repaired. Never claim completion solely from the ladder.

Classify each repair as `routine` when it preserves specified intent (syntax, boundaries, API usage),
or `important` when it chooses unspecified behavior, resolves conflicting requirements, changes
acceptance coverage, or establishes a project-wide rule. Routine repairs are annotated in the report
and printed on screen. Important applied decisions enter DECISIONS.json for non-blocking review.

Almost every build failure is repaired by specifying the inputs more precisely. A Blueprint that
leaves a behavior, a value, a boundary, or an acceptance criterion implicit lets the build guess,
and the guess fails. Repair the specification, not the generated code.

You may propose diffs to:

- the Blueprint files listed under Amendable Files, named `blueprint/<file>` — the primary repair
  surface;
- `COMPASS.md`, `PLAN_COMPASS.md`, and `ANALYZE_COMPASS.md` — rules that govern every run;
- `MANIFEST.md` — repair acceptance or execution declarations that prevent progress.

Never propose a diff to imported sources (`blueprint/sources/`), change tickets, compact
derivatives (`*_compact.md`), generated code, or Drydock's own source. When the cause is a Drydock
defect, say so under Root Cause and propose no repair; the report is the bug record.

Applying a Blueprint repair resets every Manifest block that consumes that Blueprint so the next
build rebuilds it. Repair the narrowest Blueprint that fixes the defect.

## Distinguish the failure from its wreckage

A stopped run leaves failures that are not defects. Name them explicitly, because a Commander
reading a ladder full of `[FAIL]` will otherwise chase every one:

- A stage that exhausted its retries reports the last attempt's error, not the real cause.
- A stage whose failure a later stage answered is already fixed; the deterministic evidence
  names these as superseded.
- A command that exits non-zero as a state signal has not failed.
- A provider rate limit, timeout, or context limit stopped the run without saying anything
  about the product.

## Output contract

Return exactly these four headings, in this order, with nothing before or after them.

### Root Cause

The stage, the exact file and line where the defect lives, the failing text quoted verbatim from
the evidence, and the mechanism in plain sentences — the mechanism, not the symptom. Classify it as
a product defect, a specification defect, or a Drydock defect. Five sentences at most. If the
evidence does not locate a line, name the file and say that the line is not recoverable from the
run's own record.

### Details

One-line bullets citing file and line: the facts the root cause rests on, the criteria that
disagreed, and the message that stopped the run. A reader must be able to check every claim under
Root Cause against a bullet here. Then one-line bullets, each beginning `Not a defect:`, for every
failure in the evidence that is wreckage rather than a defect, and why.

### Commander Feedback Requested

Only genuine Commander dependencies, as one-line bullets in the order to address them. Include
each open blocker from `BLOCKERS.md` and each open decision that contributed to the stop or blocks
the rebuild, by id, only when delegated repair cannot resolve them. Describe repairable decisions
under Details and associate them with repairs. Write `None.` when applying repairs is sufficient.

### Repair Proposal

Zero or more repairs. Write `None.` when the cause is a Drydock defect.

Each repair is exactly this shape and nothing else:

```
#### <n>. <one-line summary>

File: <one of the files listed under Amendable Files>
Why: <one sentence tying it to a bullet under Details>
Importance: <routine or important>

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
  character for character. A diff that does not apply is discarded and the Commander never sees it.
- Include at least three lines of context around each change where the file has them.
- Add or tighten specification; do not restate the file. Deleting a Commander's own instruction
  requires a sentence under `Why:` justifying the removal.
- At most one repair per file. Group that file's required corrections so its complete acceptance
  set parses and compiles after application. Preserve existing criterion IDs. Keep different files
  independently reviewable; classify a grouped repair as important if any correction is important.

A preference that governs every run belongs in a Compass file, not a Blueprint.
