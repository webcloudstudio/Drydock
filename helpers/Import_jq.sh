#!/usr/bin/env bash
#
# Import_jq.sh — seed the jq Target and import its source bundle.
#
# Run from the Drydock repository root (the workspace), after `drydock init jq`.
# Inherits PROJECT, KIT, and OPTS from jq.sh; defaults are supplied so this script
# can also be run on its own.

export PROJECT=${PROJECT:-jq}
export KIT=${KIT:-uat/jq}

# ---------------------------------------------------------------------------
# 1. Lifecycle inputs
#
# `drydock uat` seeds these automatically; the interactive path does not.
# They land at targets/<Target>/, NOT in blueprint/.
# `analyze` never overwrites either file, so seeding now makes them the
# decisions of record. Delete a copy below to let `analyze` propose its own.
# ---------------------------------------------------------------------------

mkdir -p "targets/$PROJECT"

cp "$KIT/inputs/TECHNOLOGY_STACK.md" "targets/$PROJECT/TECHNOLOGY_STACK.md"
cp "$KIT/inputs/SEA_TRIALS.md"       "targets/$PROJECT/SEA_TRIALS.md"

# The governed acceptance contract. No LLM command can write this file, which is
# what makes it the exam. Mirrors the `acceptance` block of uat/jq/uat.json.
cat > "targets/$PROJECT/ACCEPTANCE.json" <<'JSON'
{
  "full": [
    "sh",
    "sources/full_test.sh"
  ]
}
JSON

# ---------------------------------------------------------------------------
# 2. Source bundle
#
# One directory import, which is exactly what `drydock uat` does: a single
# analysis pass over the whole bundle.
#
# The nine files imported, and why each is there:
#
#   INSTRUCTIONS.md     the build brief: interface contract, harness rules,
#                       Source Roles table, definition of done
#   jq-manual.txt       the jq 1.8.2 manual. THE normative specification.
#                       .txt, not .md, so it is staged onto disk and remains
#                       readable during the build
#   jq.test             the conformance corpus, verbatim from jq-1.8.2
#   exclusions.txt      the 13 module-loader cases this kit cannot run
#   parser.y            upstream grammar: precedence and syntactic forms
#   lexer.l             upstream lexer: tokens, interpolation, escapes
#   builtin.jq          builtins upstream defines in jq itself
#                       (REMOVE THIS if you judge it too large a giveaway --
#                        delete the file and its entry in uat/jq/uat.json)
#   run_conformance.py  the scoring instrument. Read-only, hash-verified
#   full_test.sh        the scoring entry point. Read-only, hash-verified
# ---------------------------------------------------------------------------

echo "Importing $KIT/sources"
drydock import "$PROJECT" "$KIT/sources" --format markdown ${OPTS:-}

# ---------------------------------------------------------------------------
# Alternative: per-file imports, if you want to stage the bundle in phases or
# see each file's analysis separately. Costs one LLM call per file instead of
# one for the lot. Comment out the directory import above before using these.
# ---------------------------------------------------------------------------
#
# import_source() {
#     echo "Importing $1"
#     drydock import "$PROJECT" "$KIT/sources/$1" --format "${2:-markdown}" ${OPTS:-}
# }
#
# import_source INTENT.md compass       # no INTENT.md in this kit; here for shape
#
# import_source INSTRUCTIONS.md
# import_source jq-manual.txt
# import_source jq.test
# import_source exclusions.txt
# import_source parser.y
# import_source lexer.l
# import_source builtin.jq
# import_source run_conformance.py
# import_source full_test.sh
