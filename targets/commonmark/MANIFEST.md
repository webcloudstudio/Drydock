# MANIFEST: CommonMark
updated:     2026-07-22T12:00:00
plan_hash:   7b7898b1a29b
applied_specs: |

## feature 1: Foundation
id:      foundation
summary: Establish the project identity, intent, and implementation boundaries.
state:   pending

## story 1: Establish project metadata
id:           metadata
parent:       foundation
summary:      Define the project identity and code root.
implements:   METADATA.md
instructions: |
  Preserve the project identity for the CommonMark parser, keep the Python stack selection, and
  anchor the implementation under src/commonmark.
state:        pending
evidence:     commonmark/evidence/metadata.md
scope:        blueprint

## ac 1: Metadata spec is present (smoke: test -f blueprint/METADATA.md && grep -q '^name: commonmark$' blueprint/METADATA.md && grep -q '^code_root: src/commonmark$' blueprint/METADATA.md)

## story 2: Define project readme
id:           readme
parent:       foundation
summary:      State the user-facing project intent.
implements:   README.md
instructions: |
  Keep the README concise and make the stdin-to-stdout filter purpose explicit.
depends:      metadata
state:        pending
evidence:     commonmark/evidence/readme.md
scope:        blueprint

## ac 2: README describes filter intent (smoke: test -f blueprint/README.md && grep -q '^# CommonMark$' blueprint/README.md && grep -q 'stdin-to-stdout parser' blueprint/README.md)

## story 3: Define product compass
id:           compass
parent:       foundation
summary:      Capture the execution constraints and permanent guardrails.
implements:   COMPASS.md
instructions: |
  Keep the CommonMark filter contract, no-side-effect guardrails, and raw-HTML and NUL handling
  requirements authoritative.
depends:      metadata
state:        pending
evidence:     commonmark/evidence/compass.md
scope:        blueprint

## ac 3: Compass preserves guardrails (smoke: test -f blueprint/COMPASS.md && grep -q 'replaces NUL characters' blueprint/COMPASS.md && grep -q 'does not create side effects' blueprint/COMPASS.md)

## story 4: Define parser architecture
id:           architecture
parent:       foundation
summary:      Specify the package boundaries, conversion flow, and module ownership.
implements:   ARCHITECTURE.md
context:      COMPASS.md
instructions: |
  Define the Python package boundaries for the CLI entry point, conversion API, block parser,
  inline parser, renderer, syntax tree, and verification strategy.
depends:      compass readme
state:        pending
evidence:     commonmark/evidence/architecture.md
scope:        both

## ac 4: Architecture tests exist (smoke: python -m pytest tests/test_architecture.py)

## feature 2: Parser Core
id:      parser-core
summary: Deliver the executable filter and the CommonMark parsing pipeline.
state:   pending

## story 5: Implement filter execution contract
id:           filter-execution
parent:       parser-core
summary:      Build the stdin-to-stdout executable contract and conversion entry point.
implements:   FEATURE-Filter-Execution.md
accepts:      st-001, st-005
context:      COMPASS.md ARCHITECTURE.md
instructions: |
  Build the Python module entry point, expose commonmark.api.convert, reject unexpected CLI
  arguments, and normalize NUL characters to U+FFFD before parsing.
depends:      architecture
state:        pending
evidence:     commonmark/evidence/filter-execution.md
scope:        target

## ac 5: Filter execution tests pass (smoke: python -m pytest tests/test_filter_execution.py)

## story 6: Implement block parsing
id:           block-parsing
parent:       parser-core
summary:      Build phase-one block parsing and reference-definition collection.
implements:   FEATURE-Block-Parsing.md
context:      ARCHITECTURE.md FEATURE-Filter-Execution.md
instructions: |
  Implement CommonMark leaf and container block parsing, list tightness, HTML blocks, and
  document-wide first-definition reference resolution.
depends:      filter-execution
state:        pending
evidence:     commonmark/evidence/block-parsing.md
scope:        target

## ac 6: Block parsing tests pass (smoke: python -m pytest tests/test_block_parsing.py)

## story 7: Implement inline parsing
id:           inline-parsing
parent:       parser-core
summary:      Build phase-two inline parsing and HTML inline rendering.
implements:   FEATURE-Inline-Parsing.md
context:      ARCHITECTURE.md FEATURE-Block-Parsing.md
instructions: |
  Implement escapes, entities, code spans, emphasis, links, images, autolinks, raw HTML, and
  hard and soft line-break behavior using the CommonMark delimiter-stack strategy.
depends:      block-parsing
state:        pending
evidence:     commonmark/evidence/inline-parsing.md
scope:        target

## ac 7: Inline parsing tests pass (smoke: python -m pytest tests/test_inline_parsing.py)

## feature 3: Verification
id:      verification
summary: Stage the imported conformance assets and prove clean subprocess harness execution.
state:   pending

## story 8: Stage conformance verification
id:           conformance-verification
parent:       verification
summary:      Stage the imported corpus and harness and add focused subprocess verification.
implements:   FEATURE-Conformance-Verification.md
accepts:      st-002
context:      FEATURE-Filter-Execution.md FEATURE-Block-Parsing.md FEATURE-Inline-Parsing.md
instructions: |
  Stage spec.txt, spec_tests.py, and normalize.py into tests/conformance, add focused harness
  integration tests, and prove that subprocess execution completes without errors. Do not turn the
  full-corpus threshold or final summary score into a story-level gate.
depends:      inline-parsing
state:        pending
evidence:     commonmark/evidence/conformance-verification.md
scope:        target

## ac 8: Focused conformance verification passes (smoke: python -m pytest tests/test_conformance_harness.py)
