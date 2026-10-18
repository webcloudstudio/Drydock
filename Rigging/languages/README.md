# Language bundles

Each language directory owns its instruction file and compact, reusable persistence package,
acceptance execution helpers, and generation templates. The directory name is the language key;
the instruction basename remains selectable in `TECHNOLOGY_STACK.md` (for example `go.md`).

Instruction format: `**Type:** language`, existing Foundation/Tier fields, and the two mandatory
questions inside `## Foundation Contract`:

1. **How do we execute and measure Acceptance Criteria in this language?** State the AC format,
   command, criterion identity, results, observed values and measurement limitations.
2. **How does this language provide the shared persistence contract?** Name shipped libraries,
   engines, generated files, dependencies, calling/fixture instructions and verification status.

Compaction preserves this section verbatim. Engine instructions remain in `stack/sqlite.md` and
`stack/postgres.md`; shared persistence behavior remains in `stack/persistence.md`.

Drydock owns parsing, scheduling, timeouts, AC states, repairs and evidence storage. Bundles own
language execution details. The existing Python AC container can call a native Go test using the
shipped `drydock_go.run_test` helper. Each container supplies the criterion ID; its assertion
consumes the actual test result. A skipped or absent test never establishes acceptance.
