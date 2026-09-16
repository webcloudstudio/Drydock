#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Drydock import script — Marina
#
# Names the source material for one Target. It contains no import machinery:
# drydock_runner.sh defines the helpers below and sources this file, from this
# file's own directory, when the Target has no imported sources yet.
#
#   drydock_runner.sh Marina sonnet ./Import_Marina.sh
#
# To adapt it to another project, copy this file, point SOURCE_DIR at the
# source material, and edit the list below. Nothing else is required.
#
# Helpers provided by the runner. A relative path resolves against SOURCE_DIR;
# an absolute path is used as given. Any failure aborts the run.
#   import_compass   <file>            Project intent, normalized into COMPASS.md.
#   import_spec      <file> [format]   One specification document (default markdown).
#   import_directory <dir>  [format]   Every file under a directory, in one import.
#   import_code      <dir>             An existing source tree, imported as code.
#
# Formats: markdown, source, speckit, compass, intent, auto.
# ---------------------------------------------------------------------------

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
