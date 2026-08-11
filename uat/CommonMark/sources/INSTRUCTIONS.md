# Build Instructions: CommonMark Parser

Build a CommonMark 0.31.2 parser from the supplied specification. Read Markdown from standard
input and write HTML to standard output. Do not use a public Markdown implementation.

The sole definition of product success is `sh full_test.sh` returning exit code `0`.
`full_test.sh` runs the complete, unfiltered supplied CommonMark suite. Treat the suite runner's
exit status as the verdict; do not parse or hardcode its printed tally.

`sources/INSTRUCTIONS.md` is imported specification prose. It is not staged into the completed
application. The runtime conformance assets are only `spec.txt`, `spec_tests.py`, `cmark.py`, and
`normalize.py`.

Do not create acceptance checks asserting that imported or staged files merely exist. Do not
create a scoped check by invoking `full_test.sh`; it is intentionally full-suite only. Parser
implementation stories may run the supplied harness with explicit section selectors that cover
the whole story scope.

The final verification story depends on all parser stories, creates `full_test.sh`, and has
exactly one terminal `Suite: full` acceptance check. The check prints captured standard output
and standard error and asserts only `result.returncode == 0`. It carries `Sea Trials: st-001`.

Do not add separate verification stories for script presence, focused verification, staged
assets, or complete verification.

Deliver a concise project `README.md` documenting the standard-input/standard-output interface
and the `sh full_test.sh` command.
