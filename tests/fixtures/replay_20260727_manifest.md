# MANIFEST: CommonMark Parser
updated:     2026-07-27T00:00:00
plan_hash:   commonmark0727v1

## feature 1: Foundation
id:      feature-foundation
summary: Runtime scaffold, harness staging, full-suite runner script, and the two mandatory preliminaries.
state:   pending

## story 1: Scaffold and entry point
id:           scaffold
parent:       feature-foundation
summary:      Establish mycommonmark.py's stdin/stdout entry point and module structure; stage the conformance harness.
implements:   ARCHITECTURE.md
covers:       PROG-001
stack:        python.md
context_roles: |
  spec_tests.py: conformance harness
  cmark.py: conformance harness
  normalize.py: conformance harness
  spec.txt: normative specification and conformance test suite
copy:         |
  sources/spec_tests.py -> sources/spec_tests.py
  sources/cmark.py -> sources/cmark.py
  sources/normalize.py -> sources/normalize.py
  sources/spec.txt -> sources/spec.txt
instructions: |
  Create mycommonmark.py implementing convert(md) and a __main__ block that reads all of
  sys.stdin and writes convert(md) to sys.stdout, with no CLI argument parsing and no config
  file reads. Establish the two-phase pipeline skeleton (block parser producing a block tree,
  inline parser walking raw text, renderer emitting HTML) described in ARCHITECTURE.md. A bare
  paragraph of plain text must already render correctly as <p>...</p>.
depends:
state:        pending
evidence:     commonmark/evidence/scaffold.md
scope:        both

## ac 1: mycommonmark.py runs as a stdin/stdout filter (smoke: echo "hello" | python3 mycommonmark.py)

## story 2: Full-suite runner script
id:           full-suite-runner
parent:       feature-foundation
summary:      Deliver full_test.sh invoking the unfiltered conformance harness.
implements:   FEATURE-Full-Suite-Runner.md
covers:       PROG-002
stack:        python.md
context:      ARCHITECTURE.md
instructions: |
  Write full_test.sh as a shell script with no required arguments that runs
  `python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py"`
  and reports its summary line. Do not invoke this script unbounded in this story's own
  acceptance; only FEATURE-Full-Conformance.md's terminal story runs the suite unfiltered.
depends:      scaffold
state:        pending
evidence:     commonmark/evidence/full-suite-runner.md
scope:        both

## ac 2: full_test.sh mechanics work on a bounded single-example run (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --number 1)

## story 3: Tab-stop handling
id:           tab-handling
parent:       feature-foundation
summary:      Expand tabs to 4-character tab stops in block-structure contexts while keeping internal tabs literal.
implements:   FEATURE-Tab-Handling.md
covers:       PRELIM-001
stack:        python.md
context:      ARCHITECTURE.md, spec.txt
instructions: |
  Implement tab-stop-aware indentation counting used by every block scanner, per the "Tabs"
  section of spec.txt. Internal tabs inside block content (e.g. code block lines) must remain
  literal tab characters, never converted to spaces.
depends:      scaffold
state:        pending
evidence:     commonmark/evidence/tab-handling.md
scope:        target

## ac 3: Tabs conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Tabs")

## story 4: Insecure character substitution
id:           insecure-characters
parent:       feature-foundation
summary:      Replace literal and numeric-reference U+0000 with U+FFFD before further parsing.
implements:   FEATURE-Insecure-Characters.md
covers:       PRELIM-002
accepts:      st-002
stack:        python.md
context:      ARCHITECTURE.md, spec.txt
instructions: |
  Implement the mandatory security substitution: any literal U+0000 in the raw input, and any
  U+0000 produced by resolving a decimal or hexadecimal numeric character reference, becomes
  U+FFFD before the character reaches rendering. This must never be bypassed or made
  conditional.
depends:      tab-handling
state:        pending
evidence:     commonmark/evidence/insecure-characters.md
scope:        target

## ac 4: Insecure-characters guardrail command passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Insecure characters")

## feature 2: Leaf Blocks
id:      feature-leaf-blocks
summary: The nine leaf block constructs, built in spec order.
state:   pending

## story 5: Thematic breaks
id:           thematic-breaks
parent:       feature-leaf-blocks
summary:      Recognize thematic break lines with correct precedence over setext/list interpretations.
implements:   FEATURE-Thematic-Breaks.md
covers:       LEAF-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement thematic break recognition per FEATURE-Thematic-Breaks.md: 3-space indent
  allowance, matching -/_/* run of 3+, optional intervening spaces/tabs, yielding to setext
  heading interpretation when applicable.
depends:      insecure-characters
state:        pending
evidence:     commonmark/evidence/thematic-breaks.md
scope:        target

## ac 5: Thematic breaks conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Thematic breaks")

## story 6: ATX headings
id:           atx-headings
parent:       feature-leaf-blocks
summary:      Recognize 1-6 level ATX headings with optional closing sequence.
implements:   FEATURE-ATX-Headings.md
covers:       LEAF-002
stack:        python.md
context:      spec.txt
instructions: |
  Implement ATX heading recognition per FEATURE-ATX-Headings.md: opening #-run of 1-6,
  required space/tab or end-of-line after it (unless heading empty), optional closing #-run,
  inline-parsed contents.
depends:      thematic-breaks
state:        pending
evidence:     commonmark/evidence/atx-headings.md
scope:        target

## ac 6: ATX headings conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "ATX headings")

## story 7: Setext headings
id:           setext-headings
parent:       feature-leaf-blocks
summary:      Recognize multi-line setext headings with laziness exceptions.
implements:   FEATURE-Setext-Headings.md
covers:       LEAF-003
stack:        python.md
context:      spec.txt
instructions: |
  Implement setext heading recognition per FEATURE-Setext-Headings.md: paragraph-like content
  followed by an =/- underline, laziness exceptions inside list items/block quotes, precedence
  over thematic break interpretation of the underline.
depends:      atx-headings
state:        pending
evidence:     commonmark/evidence/setext-headings.md
scope:        target

## ac 7: Setext headings conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Setext headings")

## story 8: Indented code blocks
id:           indented-code
parent:       feature-leaf-blocks
summary:      Recognize 4-space indented code blocks that cannot interrupt paragraphs.
implements:   FEATURE-Indented-Code-Blocks.md
covers:       LEAF-004
stack:        python.md
context:      spec.txt
instructions: |
  Implement indented code block recognition per FEATURE-Indented-Code-Blocks.md: 4+ space
  indented non-blank lines joined across blank lines, no-paragraph-interrupt rule.
depends:      setext-headings
state:        pending
evidence:     commonmark/evidence/indented-code.md
scope:        target

## ac 8: Indented code blocks conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Indented code blocks")

## story 9: Fenced code blocks
id:           fenced-code
parent:       feature-leaf-blocks
summary:      Recognize backtick/tilde fenced code blocks with info strings and bounded indentation stripping.
implements:   FEATURE-Fenced-Code-Blocks.md
covers:       LEAF-005
stack:        python.md
context:      spec.txt
instructions: |
  Implement fenced code block recognition per FEATURE-Fenced-Code-Blocks.md: matching
  backtick/tilde fences, info string capture, indentation stripping bounded strictly to the
  opening fence's own width, unterminated-fence closure at container end.
depends:      indented-code
state:        pending
evidence:     commonmark/evidence/fenced-code.md
scope:        target

## ac 9: Fenced code blocks conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Fenced code blocks")

## story 10: HTML blocks
id:           html-blocks
parent:       feature-leaf-blocks
summary:      Recognize all seven HTML block start/end condition types.
implements:   FEATURE-HTML-Blocks.md
covers:       LEAF-006
stack:        python.md
context:      spec.txt
instructions: |
  Implement all seven HTML block types per FEATURE-HTML-Blocks.md as independently
  distinguishable start/end condition cases: pre/script/style/textarea, comment, processing
  instruction, declaration, CDATA, known block-level tag, and standalone complete tag.
depends:      fenced-code
state:        pending
evidence:     commonmark/evidence/html-blocks.md
scope:        target

## ac 10: HTML blocks conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "HTML blocks")

## story 11: Link reference definitions
id:           link-ref-defs
parent:       feature-leaf-blocks
summary:      Parse link reference definitions into the label map used by reference links and images.
implements:   FEATURE-Link-Reference-Definitions.md
covers:       LEAF-007
stack:        python.md
context:      spec.txt
instructions: |
  Implement link reference definition parsing per FEATURE-Link-Reference-Definitions.md:
  label/destination/optional multi-line title, first-definition-wins when a label repeats.
depends:      html-blocks
state:        pending
evidence:     commonmark/evidence/link-ref-defs.md
scope:        target

## ac 11: Link reference definitions conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Link reference definitions")

## story 12: Paragraphs
id:           paragraphs
parent:       feature-leaf-blocks
summary:      Fallback paragraph recognition joining non-blank lines.
implements:   FEATURE-Paragraphs.md
covers:       LEAF-008
stack:        python.md
context:      spec.txt
instructions: |
  Implement paragraph recognition per FEATURE-Paragraphs.md as the fallback leaf block, joining
  lines and stripping leading/trailing space or tabs before inline parsing.
depends:      link-ref-defs
state:        pending
evidence:     commonmark/evidence/paragraphs.md
scope:        target

## ac 12: Paragraphs conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Paragraphs")

## story 13: Blank lines
id:           blank-lines
parent:       feature-leaf-blocks
summary:      Suppressblank lines between/around blocks while recording blank-line adjacency for list looseness.
implements:   FEATURE-Blank-Lines.md
covers:       LEAF-009
stack:        python.md
context:      spec.txt
instructions: |
  Implement blank-line handling per FEATURE-Blank-Lines.md: blank lines at document
  boundaries and between blocks produce no output; record blank-line adjacency between and
  within list items for FEATURE-Lists.md's tight/loose determination.
depends:      paragraphs
state:        pending
evidence:     commonmark/evidence/blank-lines.md
scope:        target

## ac 13: Blank lines conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Blank lines")

## feature 3: Container Blocks
id:      feature-container-blocks
summary: Block quotes, list items, and list grouping/looseness.
state:   pending

## story 14: Block quotes
id:           block-quotes
parent:       feature-container-blocks
summary:      Recognize block quote markers with laziness and consecutiveness rules.
implements:   FEATURE-Block-Quotes.md
covers:       CONT-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement block quote recognition per FEATURE-Block-Quotes.md: marker consumption,
  laziness on paragraph continuation lines, consecutiveness requiring a blank line between
  two block quotes, nested-marker omission via laziness.
depends:      blank-lines
state:        pending
evidence:     commonmark/evidence/block-quotes.md
scope:        target

## ac 14: Block quotes conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Block quotes")

## story 15: List items
id:           list-items
parent:       feature-container-blocks
summary:      Implement list item rules 1-6 with marker-width-based continuation indentation.
implements:   FEATURE-List-Items.md
covers:       CONT-002
stack:        python.md
context:      spec.txt
instructions: |
  Implement list item recognition per FEATURE-List-Items.md: basic case, indented-code start
  (one-space rule), blank-line start, up-to-3-space indentation, laziness, and the
  thematic-break exclusion. Continuation width is marker width plus following-space count,
  never a fixed column.
depends:      block-quotes
state:        pending
evidence:     commonmark/evidence/list-items.md
scope:        target

## ac 15: List items conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "List items")

## story 16: Lists
id:           lists
parent:       feature-container-blocks
summary:      Group list items into lists, compute ordered start numbers, and determine tight/loose.
implements:   FEATURE-Lists.md
covers:       CONT-003
stack:        python.md
context:      spec.txt
instructions: |
  Implement list grouping per FEATURE-Lists.md: same-type item grouping, ordered start-number
  derivation, and loose/tight determination including the case where a single item directly
  contains two block-level elements separated by a blank line.
depends:      list-items
state:        pending
evidence:     commonmark/evidence/lists.md
scope:        target

## ac 16: Lists conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "^Lists$")

## feature 4: Inline Basic Constructs
id:      feature-inline-basic
summary: Backslash escapes, entity references, code spans, hard/soft breaks, and textual fallback.
state:   pending

## story 17: Backslash escapes
id:           backslash-escapes
parent:       feature-inline-basic
summary:      Resolve backslash escapes of ASCII punctuation with literal-backslash fallback.
implements:   FEATURE-Backslash-Escapes.md
covers:       INLINE-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement backslash escape resolution per FEATURE-Backslash-Escapes.md: ASCII punctuation
  escaping, literal-backslash fallback for other characters, no effect inside code
  spans/blocks, autolinks, or raw HTML.
depends:      lists
state:        pending
evidence:     commonmark/evidence/backslash-escapes.md
scope:        target

## ac 17: Backslash escapes conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Backslash escapes")

## story 18: Entity and numeric character references
id:           entity-references
parent:       feature-inline-basic
summary:      Resolve named and numeric character references outside code, with invalid code points replaced.
implements:   FEATURE-Entity-References.md
covers:       INLINE-002
stack:        python.md
context:      spec.txt
instructions: |
  Implement entity/numeric reference resolution per FEATURE-Entity-References.md: named
  HTML5 entities, decimal and hex numeric references, invalid code points and U+0000 replaced
  with U+FFFD, no recognition inside code spans/blocks.
depends:      backslash-escapes
state:        pending
evidence:     commonmark/evidence/entity-references.md
scope:        target

## ac 18: Entity references conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Entity and numeric character references")

## story 19: Code spans
id:           code-spans
parent:       feature-inline-basic
summary:      Match backtick-string delimited code spans with line-ending and single-space normalization.
implements:   FEATURE-Code-Spans.md
covers:       INLINE-003
stack:        python.md
context:      spec.txt
instructions: |
  Implement code span recognition per FEATURE-Code-Spans.md: equal-length backtick-string
  matching, line-ending-to-space normalization, single-space stripping, precedence over
  emphasis.
depends:      entity-references
state:        pending
evidence:     commonmark/evidence/code-spans.md
scope:        target

## ac 19: Code spans conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Code spans")

## story 20: Hard line breaks
id:           hard-line-breaks
parent:       feature-inline-basic
summary:      Render <br /> for trailing double-space or backslash line endings, suppressed at block end.
implements:   FEATURE-Hard-Line-Breaks.md
covers:       INLINE-004
stack:        python.md
context:      spec.txt
instructions: |
  Implement hard line break recognition per FEATURE-Hard-Line-Breaks.md: 2+ trailing spaces
  or a trailing backslash before a line ending, suppressed at the end of a block.
depends:      code-spans
state:        pending
evidence:     commonmark/evidence/hard-line-breaks.md
scope:        target

## ac 20: Hard line breaks conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Hard line breaks")

## story 21: Soft line breaks
id:           soft-line-breaks
parent:       feature-inline-basic
summary:      Render ordinary line endings as softbreaks with surrounding space trimmed.
implements:   FEATURE-Soft-Line-Breaks.md
covers:       INLINE-005
stack:        python.md
context:      spec.txt
instructions: |
  Implement soft line break recognition per FEATURE-Soft-Line-Breaks.md: any non-hard line
  ending becomes a line ending in output, trimming surrounding spaces.
depends:      hard-line-breaks
state:        pending
evidence:     commonmark/evidence/soft-line-breaks.md
scope:        target

## ac 21: Soft line breaks conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Soft line breaks")

## story 22: Textual content
id:           textual-content
parent:       feature-inline-basic
summary:      Pass through uninterpreted characters verbatim, including internal spaces.
implements:   FEATURE-Textual-Content.md
covers:       INLINE-006
stack:        python.md
context:      spec.txt
instructions: |
  Implement the textual-content fallback per FEATURE-Textual-Content.md: any character not
  claimed by another inline rule passes through verbatim, internal spaces preserved.
depends:      soft-line-breaks
state:        pending
evidence:     commonmark/evidence/textual-content.md
scope:        target

## ac 22: Textual content conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Textual content")

## feature 5: Emphasis and Strong Emphasis
id:      feature-emphasis
summary: Delimiter run flanking classification and the process-emphasis resolution algorithm.
state:   pending

## story 23: Delimiter run and flanking detection
id:           delimiter-runs
parent:       feature-emphasis
summary:      Classify */_ delimiter runs as left-flanking, right-flanking, both, or neither.
implements:   FEATURE-Delimiter-Runs.md
covers:       EMPH-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement delimiter run identification and flanking classification per
  FEATURE-Delimiter-Runs.md, feeding a delimiter stack (type, count, active flag, can-open/
  can-close flags) for FEATURE-Emphasis-Resolution.md to consume. This story does not run a
  scoped suite pass of its own since no distinct spec.txt section covers flanking alone; its
  hand-picked assertions are bounded checks, not a suite-section proof.
depends:      textual-content
state:        pending
evidence:     commonmark/evidence/delimiter-runs.md
scope:        target

## ac 23: Delimiter run flanking behaves as specified (smoke: python3 -c "import subprocess,sys; r=subprocess.run(['python3','mycommonmark.py'],input='*foo bar*\n',capture_output=True,text=True); sys.exit(0 if '<em>foo bar</em>' in r.stdout else 1)")

## story 24: Emphasis and strong emphasis resolution
id:           emphasis-resolution
parent:       feature-emphasis
summary:      Implement the delimiter-stack process-emphasis algorithm including the multiple-of-3 rule and nesting preferences.
implements:   FEATURE-Emphasis-Resolution.md
covers:       EMPH-002
stack:        python.md
context:      spec.txt
instructions: |
  Implement the full process-emphasis algorithm per FEATURE-Emphasis-Resolution.md over the
  delimiter stack built by delimiter-runs: opener/closer matching across separate runs, the
  sum-of-lengths-multiple-of-3 exception, and the nesting/precedence rules (minimize nesting,
  prefer em-inside-strong, first-of-overlapping-spans, shorter-closer-wins).
depends:      delimiter-runs
state:        pending
evidence:     commonmark/evidence/emphasis-resolution.md
scope:        target

## ac 24: Emphasis and strong emphasis conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Emphasis and strong emphasis")

## feature 6: Links, Images, Autolinks, and Raw HTML
id:      feature-links
summary: Inline links, reference links, images, autolinks, and inline raw HTML.
state:   pending

## story 25: Inline links
id:           inline-links
parent:       feature-links
summary:      Parse inline link destination/title including balanced-parenthesis and angle-bracket forms.
implements:   FEATURE-Inline-Links.md
covers:       LINK-001
accepts:      st-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement inline link recognition per FEATURE-Inline-Links.md: destination in bare or
  angle-bracket form, optional title, percent-encoding of non-ASCII/reserved characters in
  rendered destinations exactly as the URL-escaping examples show.
depends:      emphasis-resolution
state:        pending
evidence:     commonmark/evidence/inline-links.md
scope:        target

## ac 25: Inline links conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "^Links$")

## story 26: Reference links
id:           reference-links
parent:       feature-links
summary:      Resolve full, collapsed, and shortcut reference links with normalized label matching.
implements:   FEATURE-Reference-Links.md
covers:       LINK-002
accepts:      st-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement reference link resolution per FEATURE-Reference-Links.md: full/collapsed/shortcut
  forms, label normalization (Unicode case-fold, whitespace collapse), precedence full >
  collapsed > shortcut, inline links take precedence over all three.
depends:      inline-links
state:        pending
evidence:     commonmark/evidence/reference-links.md
scope:        target

## ac 26: Links conformance section (reference forms) passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Links")

## story 27: Images
id:           images
parent:       feature-links
summary:      Parse image description syntax with alt-text flattening of nested inline content.
implements:   FEATURE-Images.md
covers:       LINK-003
accepts:      st-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement image recognition per FEATURE-Images.md: ![description](destination "title") and
  reference forms, flattening nested inline content (including nested images) to plain text
  for the alt attribute.
depends:      reference-links
state:        pending
evidence:     commonmark/evidence/images.md
scope:        target

## ac 27: Images conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Images")

## story 28: Autolinks
id:           autolinks
parent:       feature-links
summary:      Recognize URI-scheme and email-address autolinks.
implements:   FEATURE-Autolinks.md
covers:       LINK-004
accepts:      st-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement autolink recognition per FEATURE-Autolinks.md: <scheme:rest> URI form and email
  address form, both rendered as links with no backslash-escape effect inside.
depends:      images
state:        pending
evidence:     commonmark/evidence/autolinks.md
scope:        target

## ac 28: Autolinks conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Autolinks")

## story 29: Raw HTML inline tags
id:           raw-html-inline
parent:       feature-links
summary:      Recognize open/closing tags, comments, processing instructions, declarations, and CDATA inline.
implements:   FEATURE-Raw-HTML-Inline.md
covers:       LINK-005
accepts:      st-001
stack:        python.md
context:      spec.txt
instructions: |
  Implement inline raw HTML recognition per FEATURE-Raw-HTML-Inline.md: open tag, closing
  tag, comment, processing instruction, declaration, and CDATA grammars, rendered unescaped,
  same precedence tier as code spans and autolinks.
depends:      autolinks
state:        pending
evidence:     commonmark/evidence/raw-html-inline.md
scope:        target

## ac 29: Raw HTML conformance section passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py" --pattern "Raw HTML")

## feature 7: Conformance Verification
id:      feature-verification
summary: Terminal unfiltered full-suite proof.
state:   pending

## story 30: Full CommonMark conformance verification
id:           full-conformance
parent:       feature-verification
summary:      Run the unfiltered conformance suite against the completed parser and require a full pass.
implements:   FEATURE-Full-Conformance.md
covers:       VERIFY-001
accepts:      st-001
stack:        python.md
context:      spec.txt
instructions: |
  No new parser behavior is added here. Run the unfiltered
  `python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py"`
  and confirm 0 failed, 0 errored across the entire suite, per FEATURE-Full-Conformance.md's
  Suite: full assertion. If any example fails, fix the responsible earlier capability rather
  than special-casing the output here.
depends:      scaffold full-suite-runner tab-handling insecure-characters thematic-breaks atx-headings setext-headings indented-code fenced-code html-blocks link-ref-defs paragraphs blank-lines block-quotes list-items lists backslash-escapes entity-references code-spans hard-line-breaks soft-line-breaks textual-content delimiter-runs emphasis-resolution inline-links reference-links images autolinks raw-html-inline
state:        pending
evidence:     commonmark/evidence/full-conformance.md
scope:        target

## ac 30: Full unfiltered conformance suite passes (smoke: python3 sources/spec_tests.py --spec sources/spec.txt --program "python3 mycommonmark.py")
