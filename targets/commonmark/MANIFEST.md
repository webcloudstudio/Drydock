# MANIFEST: CommonMark
updated:     2026-07-22T00:00:00
plan_hash:   draft
applied_specs: |

## feature 1: Parser Foundation
id:      parser-foundation
summary: Defines parser module boundaries and execution interfaces.
state:   pending

## story 1: Architecture
id:           architecture
parent:       parser-foundation
summary:      Establish the parser package boundaries and conversion interfaces.
implements:   ARCHITECTURE.md
accepts:      st-001
context:      COMPASS.md, METADATA.md
stack:        python.md
instructions: |
  Implement the documented CommonMark package entry points, module boundaries, and stdin-to-stdout execution flow.
depends:
state:        pending
evidence:     commonmark/evidence/architecture.md
scope:        target

## ac 1: Architecture modules (smoke: python -c "import commonmark.__main__, commonmark.api, commonmark.blocks, commonmark.inlines, commonmark.render")
id:       architecture-modules
parent:   architecture
summary:  Architecture modules are importable.
kind:     smoke
check:    python -c "import commonmark.__main__, commonmark.api, commonmark.blocks, commonmark.inlines, commonmark.render"
state:    pending
evidence: commonmark/evidence/architecture-modules.md

## feature 2: Filter Execution
id:      feature-filter-execution
summary: Provides the standalone stdin-to-stdout parser filter.
state:   pending

## story 2: Filter Execution
id:           story-filter-execution
parent:       feature-filter-execution
summary:      Implement the argument-free CommonMark stdin-to-stdout filter.
implements:   FEATURE-Filter-Execution.md
accepts:      st-001, st-005
context: COMPASS.md, ARCHITECTURE_compact.md
stack:        python.md
instructions: |
  Implement the executable filter and conversion orchestration. Read UTF-8 standard input, replace NUL characters with U+FFFD, convert Markdown to HTML, write only HTML to standard output, reject unexpected arguments, and avoid configuration, filesystem side effects, and external services.
depends:      architecture
state:        pending
evidence:     commonmark/evidence/filter-execution.md
scope:        target

## ac 2: Filter contract (smoke: python -m commonmark <<< '# Title' | python -c "import sys; assert sys.stdin.read() == '<h1>Title</h1>\\n'")
id:       filter-contract
parent:   story-filter-execution
summary:  The parser converts standard input to standard output.
kind:     smoke
check:    python -m commonmark <<< '# Title' | python -c "import sys; assert sys.stdin.read() == '<h1>Title</h1>\\n'"
state:    pending
evidence: commonmark/evidence/filter-contract.md

## feature 3: Block Parsing
id:      feature-block-parsing
summary: Parses CommonMark block structure and reference definitions.
state:   pending

## story 3: Block Parsing
id:           story-block-parsing
parent:       feature-block-parsing
summary:      Implement CommonMark leaf blocks, containers, lists, and reference definitions.
implements:   FEATURE-Block-Parsing.md
accepts:      st-001
context: FEATURE-Filter-Execution.md, spec.txt, ARCHITECTURE_compact.md
stack:        python.md
instructions: |
  Implement phase-one block parsing, including headings, thematic breaks, paragraphs, indented and fenced code, HTML blocks, block quotes, lists, lazy continuation, tight and loose rendering metadata, and document-wide first-wins reference-definition collection.
depends:      story-filter-execution
state:        pending
evidence:     commonmark/evidence/block-parsing.md
scope:        target

## ac 3: Block parsing tests (smoke: python -m pytest -q tests -k 'block')
id:       block-parsing-tests
parent:   story-block-parsing
summary:  Focused block parsing tests pass.
kind:     smoke
check:    python -m pytest -q tests -k 'block'
state:    pending
evidence: commonmark/evidence/block-parsing-tests.md

## feature 4: Inline Parsing
id:      feature-inline-parsing
summary: Parses CommonMark inline structure and renders inline HTML.
state:   pending

## story 4: Inline Parsing
id:           story-inline-parsing
parent:       feature-inline-parsing
summary:      Implement CommonMark inline parsing and rendering.
implements:   FEATURE-Inline-Parsing.md
accepts:      st-001
context: FEATURE-Block-Parsing.md, spec.txt, ARCHITECTURE_compact.md
stack:        python.md
instructions: |
  Implement phase-two inline parsing and HTML rendering for escapes, entities, code spans, emphasis, strong emphasis, links, images, autolinks, raw HTML, hard breaks, and soft breaks, using the completed document-wide reference map.
depends:      story-block-parsing
state:        pending
evidence:     commonmark/evidence/inline-parsing.md
scope:        target

## ac 4: Inline parsing tests (smoke: python -m pytest -q tests -k 'inline')
id:       inline-parsing-tests
parent:   story-inline-parsing
summary:  Focused inline parsing tests pass.
kind:     smoke
check:    python -m pytest -q tests -k 'inline'
state:    pending
evidence: commonmark/evidence/inline-parsing-tests.md

## feature 5: Conformance Verification
id:      feature-conformance-verification
summary: Stages and executes the supplied CommonMark conformance harness.
state:   pending

## story 5: Conformance Verification
id:           story-conformance-verification
parent:       feature-conformance-verification
summary:      Stage the imported corpus and verify clean subprocess harness execution.
implements:   FEATURE-Conformance-Verification.md
accepts:      st-002, st-003
context: FEATURE-Filter-Execution.md, FEATURE-Block-Parsing.md, FEATURE-Inline-Parsing.md, spec.txt, spec_tests.py, normalize.py, ARCHITECTURE_compact.md
stack:        python.md
copy:         sources/spec.txt -> tests/conformance/spec.txt
copy:         sources/spec_tests.py -> tests/conformance/spec_tests.py
copy:         sources/normalize.py -> tests/conformance/normalize.py
instructions: |
  Stage the supplied conformance corpus and helpers under tests/conformance. Add integration coverage for subprocess execution and run focused harness verification without requiring network access or API credentials. Preserve the full-corpus command for final Sea Trials scoring at the answered 100% threshold.
depends:      story-inline-parsing
state:        pending
evidence:     commonmark/evidence/conformance-verification.md
scope:        both

## ac 5: Conformance harness (smoke: test -f tests/conformance/spec.txt && test -f tests/conformance/spec_tests.py && test -f tests/conformance/normalize.py && python tests/conformance/spec_tests.py --spec tests/conformance/spec.txt --program 'python -m commonmark' --pattern 'ATX headings')
id:       conformance-harness
parent:   story-conformance-verification
summary:  The staged conformance harness executes without errors.
kind:     smoke
check:    test -f tests/conformance/spec.txt && test -f tests/conformance/spec_tests.py && test -f tests/conformance/normalize.py && python tests/conformance/spec_tests.py --spec tests/conformance/spec.txt --program 'python -m commonmark' --pattern 'ATX headings'
state:    pending
evidence: commonmark/evidence/conformance-harness.md
