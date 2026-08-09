# Drydock Project-Level UAT

`drydock uat` rebuilds known projects unattended, end to end, against a real model. It is the
full-suite acceptance capability: each fixture runs the complete `init` → `import` → `analyze` →
`plan` → `build` lifecycle in an isolated workspace, then scores the result and writes a
self-contained proof kit.

## Layout

| Path | Contents |
|---|---|
| `uat/source/<Project>/` | Committed fixture: source bundle, optional updates, `uat.json` |
| `uat/runs/<run-id>/` | Generated run output; not committed |

`uat/runs/` is ignored by Git. Nothing under it is an editable source.

## Running

```bash
drydock uat                      # every project under uat/source
drydock uat Toml                 # one project
drydock uat --report             # rebuild the proof kit for the latest run
drydock uat --report <run-id>    # rebuild the proof kit for one run
```

Useful flags:

| Flag | Effect |
|---|---|
| `--fixtures-root <path>` | Fixture root (default `<workspace>/uat/source`) |
| `--output-root <path>` | Run root (default `<workspace>/uat/runs`) |
| `--max-build-passes <n>` | Repair passes allowed per build before the fixture fails |
| `--llm-provider`, `--model`, `--effort` | Provider and model selection for the whole run |

A run is long and consumes subscription quota. The `Toml` fixture takes roughly thirty minutes and
eighteen LLM calls.

## Fixture definition

Each `uat/source/<Project>/uat.json` declares:

- `target` — the Target name created by `init`.
- `sources` — fixture-local files imported before the initial lifecycle. Required and nonempty.
  Filenames carry no ordering or positional meaning; the bundle is flattened to
  `sources/<basename>` in the build.
- `updates` — files that replace an imported basename to drive
  `import --update` → `refit --sources` → incremental build, once each, in order.
- `test_command` — argv run from the completed application root after the build. A nonzero exit
  fails the fixture.

A fixture may also ship `TECHNOLOGY_STACK.md`, seeded into the Target between `init` and `analyze`
to fix the implementation stack instead of letting `analyze` propose one. Its named Rigging files
are validated against the catalog at discovery.

## Reading a run

```text
uat/runs/<run-id>/
  SUMMARY.md            run verdict, elapsed time, token and cost accounting
  summary.json          the same data, machine-readable
  index.html            linked proof kit for the whole run
  SHA256SUMS            integrity manifest; verify with `sha256sum -c SHA256SUMS`
  <Project>/
    index.html          per-project proof kit
    result.json         every child command, argv, exit code, elapsed time
    SHA256SUMS
    sources/            the exact bundle imported for this run
    workspace/          the isolated Drydock workspace, including targets/<target>/
    build/<target>/     the delivered application
    evidence/
      commands/         stdout and stderr of every child command
      prompts/          the assembled prompt for every LLM call
      prompt_outputs/   the parsed model output
      provider_raw/     the unmodified provider transcript
      llm.jsonl         one record per call: tokens, elapsed time, execution id
      manifest.json     evidence index
```

Start at `SUMMARY.md` for the verdict, then `<Project>/index.html` for the linked kit. When a build
fails, the authoritative diagnosis is
`<Project>/workspace/targets/<target>/evidence/<block-id>.md`, which records the pre-build
acceptance observation, the stacked context, the build-directory changes, and the post-build
acceptance result for every criterion.

## Verifying integrity

```bash
cd uat/runs/<run-id> && sha256sum -c SHA256SUMS
```

The kit is portable: absolute paths are rewritten to run-relative paths when the kit is built.
