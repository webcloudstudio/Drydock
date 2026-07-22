# MANIFEST: CommonMark
updated:     2026-07-22
plan_hash:   pending
applied_specs: |

## feature 1: Parser Foundation
id:      parser-foundation
summary: Establishes the executable filter and architecture boundary.
state:   pending

## story 1: Architecture Boundary
id:           architecture
parent:       parser-foundation
summary:      Establish the CommonMark executable boundary and conversion entry point.
implements:   ARCHITECTURE.md
accepts:      st-001
context:      COMPASS.md, SEA_TRIALS.md
instructions: |
  Build the standalone Python executable and importable conversion entry point described by ARCHITECTURE.md. Keep stdin/stdout behavior, argument handling, and side-effect boundaries explicit.
depends:
state:        pending
evidence:     commonmark/evidence/architecture.md
scope:        both

## ac 1: Architecture smoke
id:       architecture-smoke
parent:   architecture
summary:  Architecture entry point and subprocess contract work
kind:     smoke
check:    python3 -c "from mycommonmark import convert; assert '<h1>Heading</h1>' in convert('# Heading')"
state:    pending
evidence: commonmark/evidence/architecture-smoke.md

## feature 2: Filter Conversion
id:      filter-conversion
summary: Implements stdin-to-stdout conversion and input safety.
state:   pending

## story 2: Filter Execution
id:           filter-execution
parent:       filter-conversion
summary:      Implement Markdown filter execution and NUL replacement.
implements:   FEATURE-Filter-Execution.md
accepts:      st-001, st-005
context: COMPASS.md, SEA_TRIALS.md, ARCHITECTURE_compact.md
instructions: |
  Implement the filter contract in FEATURE-Filter-Execution.md. Read all stdin, replace NUL characters with U+FFFD, invoke the parser, and write only UTF-8 HTML to stdout. Reject unexpected arguments and avoid configuration or side effects.
depends:      architecture
state:        pending
evidence:     commonmark/evidence/filter-execution.md
scope:        target

## ac 2: Filter smoke
id:       filter-smoke
parent:   filter-execution
summary:  Filter converts stdin and replaces NUL characters
kind:     smoke
check:    python3 -c "import subprocess; p=subprocess.run(['python3','mycommonmark.py'],input=b'# H\\x00\\n',capture_output=True); assert p.returncode == 0; assert '�' in p.stdout.decode()"
state:    pending
evidence: commonmark/evidence/filter-smoke.md

## feature 3: Block Structure
id:      block-structure
summary: Implements CommonMark block parsing and reference collection.
state:   pending

## story 3: Block Parsing
id:           block-parsing
parent:       block-structure
summary:      Implement leaf blocks, containers, lists, code blocks, HTML blocks, and references.
implements:   FEATURE-Block-Parsing.md
accepts:      st-001
context: COMPASS.md, SEA_TRIALS.md, ARCHITECTURE_compact.md
instructions: |
  Implement the block phase described by FEATURE-Block-Parsing.md. Follow CommonMark 0.31.2 precedence, indentation, lazy continuation, list tightness, container boundaries, literal code handling, raw HTML block rules, and first-definition reference precedence.
depends:      filter-execution
state:        pending
evidence:     commonmark/evidence/block-parsing.md
scope:        target

## ac 3: Block smoke
id:       block-smoke
parent:   block-parsing
summary:  Block structures render correctly
kind:     smoke
check:    python3 -c "from mycommonmark import convert; h=convert('> q\\n\\n- a\\n'); assert '<blockquote>' in h and '<li>a</li>' in h"
state:    pending
evidence: commonmark/evidence/block-smoke.md

## feature 4: Inline Structure
id:      inline-structure
summary: Implements CommonMark inline parsing and rendering.
state:   pending

## story 4: Inline Parsing
id:           inline-parsing
parent:       inline-structure
summary:      Implement inline syntax, links, images, autolinks, and raw HTML.
implements:   FEATURE-Inline-Parsing.md
accepts:      st-001
context: COMPASS.md, SEA_TRIALS.md, ARCHITECTURE_compact.md
instructions: |
  Implement the inline phase described by FEATURE-Inline-Parsing.md. Apply delimiter-run processing and precedence rules for escapes, entities, code spans, emphasis, links, images, references, autolinks, HTML, and line breaks.
depends:      block-parsing
state:        pending
evidence:     commonmark/evidence/inline-parsing.md
scope:        target

## ac 4: Inline smoke
id:       inline-smoke
parent:   inline-parsing
summary:  Inline structures render correctly
kind:     smoke
check:    python3 -c "from mycommonmark import convert; h=convert('**bold** [x](u)\\n'); assert '<strong>bold</strong>' in h and '<a href=\"u\">x</a>' in h"
state:    pending
evidence: commonmark/evidence/inline-smoke.md

## feature 5: Conformance Verification
id:      feature-conformance-verification
summary: Verifies selected subprocess behavior using supplied assets.
state:   pending

## story 5: Conformance Verification
id:           story-conformance-verification
parent:       feature-conformance-verification
summary:      Integrate focused subprocess verification with the supplied harness assets.
implements:   FEATURE-Conformance-Verification.md
accepts:      st-002
context: COMPASS.md, SEA_TRIALS.md, spec.txt, spec_tests.py, normalize.py, ARCHITECTURE_compact.md
context_roles: |
  sources/spec.txt: context
  sources/spec_tests.py: context
  sources/normalize.py: context
instructions: |
  Preserve the supplied harness compatibility and add bounded verification for selected examples. Do not convert the complete corpus threshold into a story gate; final scoring measures the complete suite.
depends:      inline-parsing
state:        pending
evidence:     commonmark/evidence/conformance-verification.md
scope:        both

## ac 5: Focused conformance smoke
id:       focused-conformance-smoke
parent:   story-conformance-verification
summary:  A selected conformance example completes without execution error
kind:     smoke
check:    python3 blueprint/sources/spec_tests.py --spec blueprint/sources/spec.txt --program "python3 mycommonmark.py" --number 1
state:    pending
evidence: commonmark/evidence/focused-conformance-smoke.md
