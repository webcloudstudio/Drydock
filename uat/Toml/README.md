# Drydock UAT Kits

A **kit** is one known project that Drydock rebuilds unattended, end to end, against a real model:
`init` → `import` → `analyze` → `plan` → `build`, then scored and sealed into a self-verifying
proof kit. Kits are Drydock's full-suite acceptance capability and its public worked examples.

Each kit directory is self-contained and self-runnable. `uat/Toml/` is published on its own as
`drydock-example-toml`; nothing outside it is needed to reproduce a run.

## Layout

```text
uat/
  README.md              this file
  <Kit>/                 one kit, publishable as its own repository
    README.md            what the kit builds and how to run it
    uat.json             source bundle, updates, and test command
    index.html           landing page linking every run
    inputs/              optional lifecycle decisions seeded before analysis
    sources/             Blueprint inputs and supplied build assets
    updates/             replacement sources that drive incremental rebuilds
    runs/<run-id>/       one complete unattended run
```

`runs/` is generated. It is ignored by Git in this repository and published deliberately in an
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
- `sea_trials` — optional kit-local Sea Trials path, seeded after `init` and before `analyze`.
- `technology_stack` — optional kit-local technology-stack path, seeded at the same point. Named
  Rigging files are validated against the catalog during discovery.
- `test_command` — argv run from the completed application root after the build. A nonzero exit
  fails the kit.

Both lifecycle inputs are explicit. Root-level magic filenames are ignored. When either key is
omitted, `analyze` creates that artifact inside the run Target.

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
  inputs/               exact declared lifecycle inputs for this run
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
