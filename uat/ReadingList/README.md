# Drydock Example — Reading List

A Drydock UAT kit, and the smallest one. A short prose brief describes a web application that keeps
a list of books; Drydock designs and builds it unattended, from `init` to a scored `build`.

This kit is the only one that exercises the update path: after the initial build succeeds,
`updates/reading-list.md` replaces the imported brief and drives
`import --update` → `refit --sources` → incremental rebuild. It is the fast check that Drydock
re-plans against a changed specification instead of rebuilding from scratch.

## Prerequisites

None beyond Drydock itself. The stack is not fixed, so `analyze` proposes one.

## Running

```bash
drydock uat ReadingList
```

The run lands in `runs/<run-id>/`; open its `README.md` for the verdict and `index.html` for the
linked evidence.

## Kit contents

| Path | Role |
|---|---|
| `uat.json` | Source bundle, updates, and the scoring command |
| `sources/reading-list.md` | The initial brief — the primary input |
| `updates/reading-list.md` | The revised brief that drives the incremental rebuild |

## What the build must produce

An application that adds a book with title and author, lists books in the order added, removes a
book, and rejects an empty title or author with a clear error. `bin/test.sh` at the application
root runs the complete automated suite and exits zero only when every test passes.

## Reading the evidence

`runs/<run-id>/README.md` states the verdict. When a build fails, the authoritative diagnosis is
`runs/<run-id>/workspace/targets/ReadingList/evidence/<block-id>.md`, which records every acceptance
criterion, its exit code, and its captured output.
