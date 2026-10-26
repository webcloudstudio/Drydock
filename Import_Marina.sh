#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Drydock import list — Marina
#
# Names the source material for one Target and starts or continues its build:
#
#   ./Import_Marina.sh --model sonnet
#
# Each entry becomes one --infile argument to `drydock run builder`, which
# imports them in order only while the Target has no imported sources, then
# runs the lifecycle through to a complete build. Extra arguments pass through.
#
# To adapt it to another project, copy this file, point SOURCE_DIR at the
# source material, and edit the list below. Nothing else is required.
#
# A relative path resolves against SOURCE_DIR; an absolute path is used as given.
#   import_compass   <file>            Project intent, normalized into COMPASS.md.
#   import_spec      <file> [format]   One specification document (default markdown).
#   import_directory <dir>  [format]   Every file under a directory (default markdown).
#   import_code      <dir>             An existing source tree, imported as code.
#
# Formats: markdown, source, speckit, compass, intent, auto.
# ---------------------------------------------------------------------------
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

INPUTS=()
source_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *) printf '%s' "${SOURCE_DIR:?SOURCE_DIR must be set}/$1" ;;
  esac
}
import_compass() { INPUTS+=(--infile "compass=$(source_path "$1")"); }
import_spec() { INPUTS+=(--infile "${2:-markdown}=$(source_path "$1")"); }
import_directory() { INPUTS+=(--indir "${2:-markdown}=$(source_path "$1")"); }
import_code() { import_directory "$1" source; }

# Relative to this script's directory.
SOURCE_DIR=../Specifications/Marina

# Intent first: it establishes the Target's COMPASS.md.
import_compass INTENT.md

# Phase 1 — foundation, setup screens, and first features.
import_spec METADATA.md
import_spec README.md
import_spec ARCHITECTURE.md
import_spec FUNCTIONALITY.md
import_spec DATABASE.md
import_spec UI-GENERAL.md
import_spec FEATURE-CONFIGURATION.md
import_spec FEATURE-DIRECTORY-PICKER.md
import_spec FEATURE-PROJECT-REGISTRATION.md
import_spec FEATURE-SCANNER.md
import_spec FEATURE-SETUP-NAVIGATION.md
import_spec SCREEN-SETUP-SUMMARY.md
import_spec SCREEN-SETUP-WORKSPACE.md
import_spec SCREEN-SETUP-WORKSPACE-ADD.md
import_spec SCREEN-SETUP-SOURCES.md
import_spec SCREEN-SETUP-SOURCES-ADD.md
import_spec SCREEN-SETUP-AWS.md
import_spec SCREEN-SETUP-TERRAFORM.md
import_spec SCREEN-SETUP-GITHUB.md
import_spec SCREEN-SETUP-REPOSITORIES.md
import_spec SCREEN-SETUP-PROJECTS.md
import_spec SCREEN-SETUP-SETTINGS.md

# Phase 2 — project dashboard and service catalog.
import_spec FEATURE-CAPABILITY-DISCOVERY.md
import_spec FEATURE-PROJECT-ORGANIZATION.md
import_spec FEATURE-SERVICE-CATALOG.md
import_spec FEATURE-WORKFLOW-SERVICE.md
import_spec SCREEN-PROJECTS-DASHBOARD.md
import_spec SCREEN-PROJECTS-DETAIL.md
import_spec SCREEN-PROJECTS-CAPABILITIES.md
import_spec SCREEN-PROJECTS-CONFIGURATION.md
import_spec SCREEN-PROJECTS-MAINTENANCE.md
import_spec SCREEN-PROJECTS-VALIDATION.md
import_spec SCREEN-PROJECTS-WORKFLOW.md

# Phases 3 and later are deferred. Uncomment a block to bring it into scope.
#
# Phase 3 — monitoring.
# import_spec FEATURE-MARINA-MONITORING.md
# import_spec FEATURE-HEALTHCHECK.md
# import_spec SCREEN-MONITORING-MONITORING.md
# import_spec SCREEN-MONITORING-SCHEDULER.md
# import_spec SCREEN-MONITORING-PROCESSES.md
#
# Phase 5 — shared library, infrastructure, and catalog services.
# import_spec FEATURE-MARINA-LIB.md
# import_spec FEATURE-INFRA.md
# import_spec FEATURE-ACCESS-CONTROL.md
# import_spec FEATURE-CATALOG-PUBLISH.md
# import_spec FEATURE-CATALOG-READ.md
# import_spec FEATURE-REPORT-INGEST.md
#
# Phase 6 — asynchronous and capture services.
# import_spec FEATURE-ASYNCQUEUE.md
# import_spec FEATURE-S3-SHARE.md
# import_spec FEATURE-VOICE-CAPTURE.md
# import_spec FEATURE-BATCH-RUNNER.md
# import_spec FEATURE-CLI-GATEWAY.md
#
# No phase assigned.
# import_spec FEATURE-PROJECT-OPS.md

exec drydock run builder Marina "${INPUTS[@]}" "$@"
