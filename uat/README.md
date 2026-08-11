# Drydock Build Evidence

drydock uat <projects> does not write in the normal manner to the output directory and logs.  It runs
encapsulated and stores all its artifacts under uat/<Target>

Each Uat kit has an index.html page for naviation . 

## Layout

```text
uat/
  README.md              this file
  <Kit>/                 one kit, publishable as its own repository
    README.md            what the kit builds and how to run it
    uat.json             source bundle, updates, and test command
    index.html           landing page linking every run
    sources/             the input bundle, flat — no subdirectories
    updates/             replacement sources that drive incremental rebuilds
    runs/<run-id>/       one complete unattended run
```

This repo should be ignored by the master Git repository and is published deliberately in an
example repository.

## Running

```bash
drydock uat                      # every kit under uat/
drydock uat Toml                 # one kit
drydock uat --report             # rebuild proof kits from completed runs
drydock uat --report Toml        # rebuild one kit's proof kits
```

| Flag | Effect |
|---|---|
| `--uat-root <path>` | Directory holding the kits (default `<workspace>/uat`) |
| `--max-build-passes <n>` | Repair passes allowed per build before the kit fails |
| `--llm-provider`, `--model`, `--effort` | Provider and model selection for the whole run |

A run is long and consumes subscription quota. The `Toml` kit takes roughly thirty minutes and
eighteen LLM calls.

## Kit definition

`uat.json` declares:

- `target` — the Target name created by `init`.
- `sources` — kit-local files imported before the initial lifecycle. Required and nonempty.
  Paths are relative to the kit root; the bundle is flattened to `sources/<basename>` in the
  build, so basenames must be unique.
- `updates` — files that replace an imported basename to drive
  `import --update` → `refit --sources` → incremental build, once each, in order.
- `test_command` — argv run from the completed application root after the build. A nonzero exit
  fails the kit.

A kit may also ship `TECHNOLOGY_STACK.md`, seeded into the Target between `init` and `analyze` to
fix the implementation stack instead of letting `analyze` propose one. Its named Rigging files are
validated against the catalog at discovery.

Every non-Markdown source is an artifact for the build to use — a test harness, a fixture corpus,
a tool — and is staged verbatim into the build directory's `sources/`. Markdown is specification
prose and becomes Blueprint input instead.

## Reading a run

```text
runs/<run-id>/
  README.md             run verdict, elapsed time, token and cost accounting
  index.html            linked proof kit
  result.json           every child command, argv, exit code, elapsed time
  SHA256SUMS            integrity manifest
  sources/              the exact bundle imported for this run
  workspace/            the isolated Drydock workspace, including targets/<target>/
  build/<target>/       the delivered application
  evidence/
    commands/           stdout and stderr of every child command
    prompts/            the assembled prompt for every LLM call
    prompt_outputs/     the parsed model output
    provider_raw/       the unmodified provider transcript
    llm.jsonl           one record per call: tokens, elapsed time, execution id
    manifest.json       evidence index
```

When a build fails, the authoritative diagnosis is
`workspace/targets/<target>/evidence/<block-id>.md`: the pre-build acceptance observation, the
stacked context, the build-directory changes, and the post-build result for every criterion.

Verify a kit with:

```bash
cd runs/<run-id> && sha256sum -c SHA256SUMS
```

Absolute paths are rewritten to run-relative paths when the kit is sealed, so a run stays readable
on any machine.
