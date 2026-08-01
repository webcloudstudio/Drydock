#!/usr/bin/env bash

export PROJECT=Marina
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export SOURCE=$PROJECT_DIR/Specifications/Marina

import_source() {
    local source_file=$1
    local format=${2:-markdown}

    drydock import "$PROJECT" "$SOURCE/$source_file" --format "$format" ${OPTS:-}
}

# PHASE 1

import_source METADATA.md
import_source README.md
import_source INTENT.md compass
import_source ARCHITECTURE.md
import_source FUNCTIONALITY.md
import_source DATABASE.md
import_source UI-GENERAL.md
import_source FEATURE-CONFIGURATION.md
import_source FEATURE-PROJECT-REGISTRATION.md
import_source FEATURE-SCANNER.md
import_source SCREEN-SETUP-SUMMARY.md
import_source SCREEN-SETUP-DIRECTORIES.md
import_source SCREEN-SETUP-GITHUB.md
import_source SCREEN-SETUP-SCAN.md
import_source SCREEN-SETUP-REPOSITORIES.md
import_source SCREEN-SETUP-PROJECTS.md
import_source SCREEN-SETUP-SETTINGS.md

# PHASE 2

import_source FEATURE-CAPABILITY-DISCOVERY.md
import_source FEATURE-PROJECT-ORGANIZATION.md
import_source FEATURE-SERVICE-CATALOG.md
import_source FEATURE-WORKFLOW-SERVICE.md
import_source SCREEN-PROJECTS-DASHBOARD.md
import_source SCREEN-PROJECTS-DETAIL.md
import_source SCREEN-PROJECTS-CAPABILITIES.md
import_source SCREEN-PROJECTS-CONFIGURATION.md
import_source SCREEN-PROJECTS-MAINTENANCE.md
import_source SCREEN-PROJECTS-VALIDATION.md
import_source SCREEN-PROJECTS-WORKFLOW.md

# PHASE 3 - DEFERRED

import_source FEATURE-MARINA-MONITORING.md
import_source FEATURE-HEALTHCHECK.md
import_source SCREEN-MONITORING-MONITORING.md
import_source SCREEN-MONITORING-SCHEDULER.md
import_source SCREEN-MONITORING-PROCESSES.md

# PHASE 4 - DEFERRED

# No dedicated files.

# PHASE 5 - DEFERRED

import_source FEATURE-MARINA-LIB.md
import_source FEATURE-INFRA.md
import_source FEATURE-ACCESS-CONTROL.md
import_source FEATURE-CATALOG-PUBLISH.md
import_source FEATURE-CATALOG-READ.md
import_source FEATURE-REPORT-INGEST.md
import_source SCREEN-SETUP-AWS.md
import_source SCREEN-SETUP-TERRAFORM.md

# PHASE 6 - DEFERRED

import_source FEATURE-ASYNCQUEUE.md
import_source FEATURE-S3-SHARE.md
import_source FEATURE-VOICE-CAPTURE.md
import_source FEATURE-BATCH-RUNNER.md
import_source FEATURE-CLI-GATEWAY.md

# PHASE 7 - DEFERRED

# No dedicated files.

# DEFERRED - NO PHASE ASSIGNED

import_source FEATURE-PROJECT-OPS.md
