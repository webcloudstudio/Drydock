# Marina

A local-first developer control plane that broadcasts project state to a private, pay-per-call AWS plane.

name: Marina
display_name: Marina
short_description: A local-first developer control plane with a private 24x7 AWS broadcast surface for project catalog, capabilities, and state.
status: PROTOTYPE
type: oneshot
base_branch:
version: 2026-06-21.1
updated: 20260621
image_description: A single sailboat moored in a calm harbour at dawn, clean flat-vector style, deep navy and teal palette, lots of negative space.
stack: Python/aws-dynamodb/aws-lambda/aws-api-gateway/aws-sqs/aws-s3/terraform/github-actions/marina-library
tags: framework, cloud, control-plane, aws
namespace: development
desired_state: on-demand
specification_directory: ../Specifications
prototyper_directory: ../Prototyper

## Agent Instructions

When working on this specification, add unresolved questions to the `## Open Questions` section at the
bottom of the relevant spec file. Marina is built in minimal, dependency-ordered phases. Phase 3
(Dockerization and Fargate) and later work (AgentCore, browser UI, and other deferred items) are
documented outside the Phase 1 and Phase 2 build scope and remain out of scope until explicitly promoted.
