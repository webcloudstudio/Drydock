### drydock refit

`drydock refit <Target>` reconciles the previously applied Blueprint state with all current change inputs, writes normalized Drydock change tickets, updates `MANIFEST.md`, and marks affected built work for rebuild. It does not modify Blueprint content.

The change inputs are ticket files supplied by external systems, raw English ticket files, direct Blueprint edits, and Blueprint comments associated with Feature tickets. Refit compares direct Blueprint edits with the prior applied Blueprint snapshot recorded in the Manifest. Git history may provide provenance but is not required for change detection.

Refit reads ticket input from the Target-relative `change_ticket_directory` configuration value and writes normalized change tickets to the same directory. The default directory is `targets/<Target>/blueprint/changes/`. A source ticket or direct Blueprint edit may produce multiple normalized tickets. A Feature-ticket Blueprint comment produces one normalized ticket.

Before normalization, Refit matches each source ticket to the current Blueprint state or a detected direct Blueprint change. It uses an explicit target when supplied, applicable source metadata, the ticket text, and the current Blueprint content. Refit links inputs that describe the same change. Each normalized ticket has one best Blueprint home and amends exactly one Blueprint, section, story, or named database Access Pattern. A source ticket that cannot be matched, normalized, and incorporated into the resulting build is recorded under `Unincorporated Change Tickets` in `BLOCKERS.md`, reported to the Commander, and causes Refit to exit with code `1`.

Each normalized change ticket uses typed front matter followed by these Markdown sections:

```markdown
---
drydock_id: TICKET-...
drydock_subject: Create-order response includes order status
drydock_description: FEATURE-ORDER-001 returns status to its Feature caller.
drydock_create_dtm: 2026-09-12T14:32:18-04:00
drydock_source_dtm: 2026-09-12T14:30:00-04:00
drydock_parent: EXT-123
drydock_source: ticket-file
drydock_source_ref: EXT-123
drydock_amends: FEATURE-ORDER.md#Database-Interface
drydock_kind: database-access-pattern
drydock_operation: change
drydock_status: pending
drydock_compatibility: rebuild
---

## Change

## Contract Delta

## Source Evidence

## Acceptance Conditions

## Impact
```

`drydock_create_dtm` is the time Refit created the normalized ticket. `drydock_source_dtm` preserves the source ticket, file, comment, or Blueprint-change time. `drydock_parent` is optional and identifies the upstream ticket or related change group. Refit preserves non-`drydock_` source front matter unchanged.

`drydock_kind` is one of `blueprint`, `contract`, `database-private`, `database-access-pattern`, `database-data`, or `documentation`. `drydock_operation` is one of `add`, `change`, or `remove`. `drydock_compatibility` is required for `database-access-pattern` tickets and is one of `unchanged`, `data`, or `rebuild`.

`drydock_status` is `pending` until Refit incorporates the ticket into `MANIFEST.md`, then `incorporated`. Direct Blueprint-diff and Blueprint-comment tickets remain `pending` until their associated build consumes them.

`## Change` states the required end state. `## Contract Delta` states the exact added, changed, or removed behavior, field, interface, Access Pattern, schema element, or migration requirement. `## Source Evidence` contains the relevant source text or concise before-and-after Blueprint fragment. `## Acceptance Conditions` states the observable conditions the rebuilt work must satisfy. `## Impact` identifies the owner, directly impacted work, downstream impact, and explicitly unaffected work.

Refit leaves unbuilt work available for its first build using the current requirement. It resets only built work affected by a normalized ticket. The build receives the current Blueprint and the normalized tickets associated with the work it builds.

Refit applies Manifest and normalized-ticket updates atomically. Its finalization always attempts a Target Git commit for every artifact it writes, including `BLOCKERS.md` notifications written after an error. A failed reconciliation does not apply partial Manifest or normalized-ticket updates. A failure to commit is reported as an operational error.

On success, Refit optimizes pending work in a computed Manifest using the shared deterministic context-savings algorithm. It includes unbuilt REFIT tickets from earlier calls. A block containing any non-pending story retains its membership, number, state, and recorded fields; optimization does not reset work. Legacy Manifests without computed story types retain their existing grouping. An optimization failure rolls back the refit transaction.

For `DATABASE.md`, Refit compares the named Access Pattern contract with the applied Manifest snapshot. A Target without that snapshot may use its recorded applied file commit once to establish the public contract delta; Git history is not required thereafter. Changes to Persistence Interfaces, Schemas, or Migrations create `database-private` or `database-data` tickets and affect database implementation or migration work only. A change to a named Access Pattern affects only its owner, Features that cite that operation, and their dependent work when `compatibility: rebuild`. `compatibility: data` affects database migration and implementation work only. `compatibility: unchanged` records the change without resetting work. Each database change has a distinct normalized ticket and migration-change record.

**Exit codes.** `0` success or no-op; `1` an ambiguous, conflicting, unassignable, or unincorporated change, or a commit failure; `2` usage error.

### drydock refit add

`drydock refit add <Target> <Blueprint> <File>`

`drydock refit add` appends the next **REFIT ticket** for one **Blueprint** and adds its story to `MANIFEST.md`. A **REFIT ticket** is `blueprint/<Blueprint>_refit_<NNN>.md`. The number sets its order and its parent. Ticket `001` follows the **Blueprint**, and ticket `NNN` follows ticket `NNN-1`. The effective specification is the **Blueprint** read with its tickets in order. A later ticket governs an earlier ticket and the **Blueprint** where they conflict. Any authored **Blueprint** accepts **REFIT tickets**, including `DATABASE.md`. **CHANGE tickets** are raw input in `blueprint/changes/`.

The new story implements the ticket and has state `pending`. It depends on the previous ticket's story, or on every story that implements the **Blueprint** for ticket `001`. It inherits the **Blueprint** story's type, kind, stack, stack mode, context, and explicit Rigging rules, and adds the **Blueprint** and the earlier tickets to its context. A ticket that contains `=== AC` blocks sets `acceptance: yes`. The command optimizes pending work before saving the completed transaction, using the same grouping rules as `drydock refit`. Successive calls can place tickets in the same block while preserving their dependency order. Shared context and rules count once, with compact context preferred when available. Existing token, acceptance-count, phase, type, and work-kind constraints still apply. The command does not build. `drydock build <Target>` builds the new story.

Input files: `<File>`, or standard input when `<File>` is `-`. `blueprint/<Blueprint>.md` and `MANIFEST.md`.

Output files: `blueprint/<Blueprint>_refit_<NNN>.md` and `MANIFEST.md`. The command commits the Target repository and prints `Ticket <name> created` and `Manifest updated`.

**Exit codes.** `0` success; `1` a missing **Blueprint**, Manifest, or owning story, or empty ticket text; `2` usage error or missing `<File>`.

## Drydock Skills

Drydock ships agent skills in `Rigging/skills/`. Every `drydock init <Target>` copies each shipped skill into the workspace's `.claude/skills/` (Claude Code) and `.agents/skills/` (Codex and Gemini), replacing an installed copy with a lower `version`.

| Skill | Use |
|---|---|
| `/ddk-refit <Target> <change text>` | Matches each change to one **Blueprint**, writes the change as acceptance criteria in the **Blueprint's** own Programmatic Acceptance and User Acceptance form, and runs `drydock refit add` once per **Blueprint**. It prints only the command output. It shows no drafts and never builds. |
