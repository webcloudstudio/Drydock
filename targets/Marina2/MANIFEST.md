# MANIFEST: Marina
updated:     2026-06-21T12:00:00
plan_hash:   9f5cb6d84a1e2c73
state:       draft

## feature 1: Foundation
id:      feature-foundation
summary: Establish the repository skeleton, runtime platform, persistence contracts, and shared UI shell.
state:   pending

## story 2: Runtime Foundation
id:           runtime-foundation
parent:       feature-foundation
summary:      Build the architectural, persistence, runtime, and UI foundations for Marina.
implements:   COMPASS.md, ARCHITECTURE.md, DATABASE.md, FEATURE-RUNTIME-PLATFORM.md, FEATURE-MARINA-LIB.md, UI-GENERAL.md, README.md, METADATA.md
context:      sources/ARCHITECTURE.md, sources/DATABASE.md, sources/INTENT.md, sources/METADATA.md, sources/README.md
stack:        common.md, python.md, sqlite.md
instructions: |
  Establish the source tree, local app factory, SQLite repository boundary, shared Lambda helpers,
  runtime logging, and the packaged `marina` library boundary. Preserve the two-plane architecture and
  the no-raw-boto3 rule outside the library.
depends:
state:        pending
evidence:     Marina2/evidence/runtime-foundation.md
scope:        both

## ac 3: Runtime Foundation Contracts
id:       ac-runtime-foundation-contracts
parent:   runtime-foundation
summary:  Verify the startup gate, `/health`, SQLite initialization, and library boundary contracts.
kind:     assertion
depends:  runtime-foundation
state:    pending
evidence: Marina2/evidence/ac-runtime-foundation-contracts.md

## feature 4: Infrastructure
id:      feature-infrastructure
summary: Define the layered Terraform platform and delivery workflow for the private AWS surface.
state:   pending

## story 5: Terraform Platform
id:           terraform-platform
parent:       feature-infrastructure
summary:      Build the layered Terraform platform, reusable modules, and GitHub OIDC workflows.
implements:   FEATURE-INFRA.md
context:      ARCHITECTURE.md, DATABASE.md, sources/FEATURE-INFRA.md, sources/Archive/SPIKE_RESULTS.md
stack:        common.md, python.md, terraform.md
instructions: |
  Build real HCL for backend, foundation, services, and modules. Keep backend on local state, wire the
  remote backend for the other layers from first init, and emit `api_url` from services only.
depends:      runtime-foundation
state:        pending
evidence:     Marina2/evidence/terraform-platform.md
scope:        target

## ac 6: Terraform Validation
id:       ac-terraform-validation
parent:   terraform-platform
summary:  Verify fmt and validate pass across backend, foundation, and services.
kind:     smoke
check:    bash bin/test_infra.sh
depends:  terraform-platform
state:    pending
evidence: Marina2/evidence/ac-terraform-validation.md

## feature 7: Cloud Platform
id:      feature-cloud-platform
summary: Implement access control, catalog, reporting, and the published service inventory.
state:   pending

## story 8: Access Control
id:           access-control
parent:       feature-cloud-platform
summary:      Build the shared authorization gate, onboarding flow, and nightly grant re-sync.
implements:   FEATURE-ACCESS-CONTROL.md
context:      ARCHITECTURE.md, DATABASE.md, FEATURE-MARINA-LIB.md, sources/FEATURE-ACCESS-CONTROL.md
stack:        common.md, python.md, aws-dynamodb.md
instructions: |
  Implement the ACL gate, five-minute cache, admin-only onboarding, and scheduled grant re-sync. Keep
  GitHub API usage out of request paths.
depends:      runtime-foundation terraform-platform
state:        pending
evidence:     Marina2/evidence/access-control.md
scope:        target

## ac 9: Access Control Verification
id:       ac-access-control
parent:   access-control
summary:  Verify onboarding and grant enforcement behavior across readable and unreadable projects.
kind:     smoke
check:    bash bin/test_access_control.sh
depends:  access-control
state:    pending
evidence: Marina2/evidence/ac-access-control.md

## story 10: Catalog Services
id:           catalog-services
parent:       feature-cloud-platform
summary:      Build catalog publish and read routes for projects and capabilities.
implements:   FEATURE-CATALOG.md, AGENTS.md
context:      ARCHITECTURE.md, DATABASE.md, FEATURE-ACCESS-CONTROL.md, sources/FEATURE-CATALOG-PUBLISH.md, sources/FEATURE-CATALOG-READ.md
stack:        common.md, python.md, aws-dynamodb.md
instructions: |
  Implement publish, project-index read, project-detail read, capability read, and the service catalog
  declarations. Preserve full-projection publish semantics and readable-project filtering.
depends:      access-control
state:        pending
evidence:     Marina2/evidence/catalog-services.md
scope:        both

## ac 11: Catalog Publish Verification
id:       ac-catalog-publish
parent:   catalog-services
summary:  Verify publish writes, republish pruning, and write authorization behavior.
kind:     smoke
check:    bash bin/test_catalog_publish.sh
depends:  catalog-services
state:    pending
evidence: Marina2/evidence/ac-catalog-publish.md

## ac 12: Catalog Read Verification
id:       ac-catalog-read
parent:   catalog-services
summary:  Verify catalog index, project subtree, capability filtering, and unauthorized detail denial.
kind:     smoke
check:    bash bin/test_catalog_read.sh
depends:  catalog-services
state:    pending
evidence: Marina2/evidence/ac-catalog-read.md

## spike 13: Catalog Event Window
id:       spike-catalog-event-window
summary:  Decide the bounded recent-event window for `GET /catalog/{project}`.
context:  FEATURE-CATALOG.md
question: Should project-detail responses inline all recent events or cap them to a bounded count in V1?
parent:   feature-cloud-platform
depends:  catalog-services
state:    pending
evidence: Marina2/evidence/spike-catalog-event-window.md

## story 14: Reporting Services
id:           reporting-services
parent:       feature-cloud-platform
summary:      Build heartbeat ingest, event ingest, and read-time health aggregation.
implements:   FEATURE-REPORTING.md
context:      ARCHITECTURE.md, DATABASE.md, FEATURE-ACCESS-CONTROL.md, sources/FEATURE-REPORT-INGEST.md
stack:        common.md, python.md, aws-dynamodb.md
instructions: |
  Implement best-effort heartbeat and event ingestion, TTL-bounded event storage, and read-time health
  aggregation from latest heartbeats and recent events.
depends:      access-control
state:        pending
evidence:     Marina2/evidence/reporting-services.md
scope:        target

## ac 15: Reporting Verification
id:       ac-reporting
parent:   reporting-services
summary:  Verify latest-only heartbeat semantics, TTL event writes, and degraded health aggregation.
kind:     smoke
check:    bash bin/test_report_ingest.sh
depends:  reporting-services
state:    pending
evidence: Marina2/evidence/ac-reporting.md

## feature 16: Async And Share
id:      feature-async-share
summary: Implement S3 share, durable queue submission, and local drain behavior for project operations and voice work.
state:   pending

## story 17: Share Services
id:           share-services
parent:       feature-async-share
summary:      Build the S3-backed share path and DynamoDB share index surface.
implements:   FEATURE-SHARE.md
context:      ARCHITECTURE.md, DATABASE.md, FEATURE-ACCESS-CONTROL.md, sources/FEATURE-S3-SHARE.md
stack:        common.md, python.md, aws-s3.md
instructions: |
  Implement S3 direct upload and download through the library, share index writes and reads, and IAM-
  enforced per-user write prefixes.
depends:      access-control terraform-platform
state:        pending
evidence:     Marina2/evidence/share-services.md
scope:        target

## ac 18: Share Verification
id:       ac-share
parent:   share-services
summary:  Verify cross-company reads, prefix-scoped writes, and blocked public access.
kind:     smoke
check:    bash bin/test_s3_share.sh
depends:  share-services
state:    pending
evidence: Marina2/evidence/ac-share.md

## spike 19: Shared Prefix Decision
id:       spike-shared-prefix
summary:  Decide whether V1 needs a company-wide shared prefix in addition to per-user prefixes.
context:  FEATURE-SHARE.md
question: Should V1 add a `shared/` drop space or keep only per-user prefixes?
parent:   feature-async-share
depends:  share-services
state:    pending
evidence: Marina2/evidence/spike-shared-prefix.md

## story 20: Async Operations
id:           async-operations
parent:       feature-async-share
summary:      Build queue submit, local drain, guarded Prototyper operations, and local voice transcription.
implements:   FEATURE-ASYNC-OPERATIONS.md
context:      ARCHITECTURE.md, FEATURE-REPORTING.md, FEATURE-SHARE.md, sources/FEATURE-ASYNCQUEUE.md, sources/FEATURE-PROJECT-OPS.md, sources/FEATURE-VOICE-CAPTURE.md
stack:        common.md, python.md, aws-sqs.md
instructions: |
  Implement SQS-backed submit and local drain behavior, the fixed Prototyper allow-list, TTL expiry, DLQ
  handling, and local Whisper transcription backed by S3 objects and queued jobs.
depends:      share-services reporting-services
state:        pending
evidence:     Marina2/evidence/async-operations.md
scope:        target

## ac 21: Async Queue Verification
id:       ac-async-queue
parent:   async-operations
summary:  Verify submit, delete-on-success, retry, idempotent re-drain, and DLQ behavior.
kind:     smoke
check:    bash bin/test_asyncqueue.sh
depends:  async-operations
state:    pending
evidence: Marina2/evidence/ac-async-queue.md

## ac 22: Project Ops Verification
id:       ac-project-ops
parent:   async-operations
summary:  Verify allow-listed project operations, captured exit output, and rejection of unknown tools.
kind:     smoke
check:    bash bin/test_project_ops.sh
depends:  async-operations
state:    pending
evidence: Marina2/evidence/ac-project-ops.md

## ac 23: Voice Verification
id:       ac-voice
parent:   async-operations
summary:  Verify S3-backed voice job drain, local transcription, append semantics, and DLQ handling.
kind:     smoke
check:    bash bin/test_voice_capture.sh
depends:  async-operations
state:    pending
evidence: Marina2/evidence/ac-voice.md

## spike 24: Queue Cadence
id:       spike-queue-cadence
summary:  Decide the default drain cadence and whether SQS-native retry is sufficient for V1.
context:  FEATURE-ASYNC-OPERATIONS.md
question: Should the local agent rely on startup plus scheduled drain with SQS-native retry only, or add application-level backoff metadata?
parent:   feature-async-share
depends:  async-operations
state:    pending
evidence: Marina2/evidence/spike-queue-cadence.md

## spike 25: Project Ops Progress
id:       spike-project-ops-progress
summary:  Decide whether long-running local operations should emit incremental progress events.
context:  FEATURE-ASYNC-OPERATIONS.md
question: Should long-running Prototyper or voice jobs publish progress events in V1, or only terminal events?
parent:   feature-async-share
depends:  async-operations
state:    pending
evidence: Marina2/evidence/spike-project-ops-progress.md

## feature 26: Setup Experience
id:      feature-setup-experience
summary: Implement the local setup control plane and the eight Setup screens.
state:   pending

## story 27: Setup Control Plane
id:           setup-control-plane
parent:       feature-setup-experience
summary:      Build the local screen routes, backing APIs, SQLite persistence flows, scans, downloads, and conform actions.
implements:   FEATURE-SETUP-CONTROL-PLANE.md
context:      ARCHITECTURE.md, DATABASE.md, UI-GENERAL.md, FEATURE-INFRA.md, sources/SCREEN-SETUP-SUMMARY.md, sources/SCREEN-SETUP-AWS.md, sources/SCREEN-SETUP-TERRAFORM.md, sources/SCREEN-SETUP-GITHUB.md, sources/SCREEN-SETUP-SCAN.md, sources/SCREEN-SETUP-REPOSITORIES.md, sources/SCREEN-SETUP-PROJECTS.md, sources/SCREEN-SETUP-SETTINGS.md
stack:        common.md, python.md, flask.md, sqlite.md
instructions: |
  Implement the local Setup routes and fragment APIs, repository-backed persistence, subprocess-based AWS,
  Terraform, and GitHub checks, repo sync and clone flows, and project rescan plus conform actions. Keep
  Terraform apply out of the web server.
depends:      runtime-foundation terraform-platform
state:        pending
evidence:     Marina2/evidence/setup-control-plane.md
scope:        target

## ac 28: Setup Control Plane Contracts
id:       ac-setup-control-plane
parent:   setup-control-plane
summary:  Verify the local setup APIs persist and validate the documented state transitions and fragment contracts.
kind:     assertion
depends:  setup-control-plane
state:    pending
evidence: Marina2/evidence/ac-setup-control-plane.md

## story 29: Setup Summary And AWS Screens
id:           setup-summary-aws
parent:       feature-setup-experience
summary:      Build the Summary and AWS screens with inline config saves, readiness rules, and AWS checks.
implements:   SCREEN-SETUP-SUMMARY.md, SCREEN-SETUP-AWS.md
context:      UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md
stack:        ui-flask.bootstrap-client.md
instructions: |
  Implement the Summary and AWS templates and fragments, including the all-good indicator, critical banner,
  inline `PROJECTS_DIR` editing, AWS status light, and collapsible card behavior.
depends:      setup-control-plane
state:        pending
evidence:     Marina2/evidence/setup-summary-aws.md
scope:        target

## ac 30: Summary And AWS Screens
id:       ac-summary-aws
parent:   setup-summary-aws
summary:  Verify Summary row behavior, inline `PROJECTS_DIR` save, AWS card states, and AWS check fragments.
kind:     assertion
depends:  setup-summary-aws
state:    pending
evidence: Marina2/evidence/ac-summary-aws.md

## story 31: Setup Terraform And GitHub Screens
id:           setup-terraform-github
parent:       feature-setup-experience
summary:      Build the Terraform and GitHub screens with verification actions and persistent source management.
implements:   SCREEN-SETUP-TERRAFORM.md, SCREEN-SETUP-GITHUB.md
context:      UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md, FEATURE-INFRA.md
stack:        ui-flask.bootstrap-client.md
instructions: |
  Implement the Terraform and GitHub screens, including Terraform CLI status, auto-read `api_url`,
  endpoint verification, GitHub auth and SSH checks, and source-account CRUD.
depends:      setup-control-plane
state:        pending
evidence:     Marina2/evidence/setup-terraform-github.md
scope:        target

## ac 32: Terraform And GitHub Screens
id:       ac-terraform-github
parent:   setup-terraform-github
summary:  Verify CLI check behavior, `api_url` auto-read, endpoint verification, GitHub auth checks, and source-account persistence.
kind:     assertion
depends:  setup-terraform-github
state:    pending
evidence: Marina2/evidence/ac-terraform-github.md

## story 33: Setup Scan, Repositories, Projects, And Settings Screens
id:           setup-git-projects-settings
parent:       feature-setup-experience
summary:      Build the Git Scan, Repositories, Projects, and Settings screens over the local repository and filesystem state.
implements:   SCREEN-SETUP-SCAN.md, SCREEN-SETUP-REPOSITORIES.md, SCREEN-SETUP-PROJECTS.md, SCREEN-SETUP-SETTINGS.md
context:      UI-GENERAL.md, FEATURE-SETUP-CONTROL-PLANE.md
stack:        ui-flask.bootstrap-client.md
instructions: |
  Implement the scan results table with counting invariants, repo inventory and clone actions, the local
  project table with rescan and conform actions, and the save-on-blur Settings screen.
depends:      setup-control-plane setup-terraform-github
state:        pending
evidence:     Marina2/evidence/setup-git-projects-settings.md
scope:        target

## ac 34: Scan, Repo, Project, And Settings Screens
id:       ac-setup-git-projects-settings
parent:   setup-git-projects-settings
summary:  Verify Git scan counting invariants, repo clone state transitions, project qualification rules, and field-by-field settings saves.
kind:     assertion
depends:  setup-git-projects-settings
state:    pending
evidence: Marina2/evidence/ac-setup-git-projects-settings.md
