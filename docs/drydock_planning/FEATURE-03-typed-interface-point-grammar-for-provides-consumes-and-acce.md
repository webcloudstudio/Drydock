---
id: DDF-003
title: Typed interface-point grammar for Provides, Consumes, and acceptance
area: cross-cutting
impact: 9
complexity: 8
rank: 3
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-003: Typed interface-point grammar for Provides, Consumes, and acceptance

| Field | Value |
|---|---|
| Area | cross-cutting |
| Impact | 9/10 |
| Complexity | 8/10 |
| Rank | 3 |
| Project Types | Data pipeline / ETL, Event-driven and streaming systems, Library / SDK, CLI tools, GraphQL API service, Infrastructure-as-code, Multi-service systems |

## Problem

The dependency graph is route-shaped. `BLUEPRINTS_CONTRACT.md` computes `Provides` from route tables and matches SCREEN files to providing FEATURE files by route reference. The specification's own decomposition table promises the same fields carry commands, public API symbols, datasets, topics, and event types — but no grammar, no matching rule, and no acceptance obligation exists for any of them. Outside web and simple CLI work the graph therefore has only filename edges, the runnable frontier is authored guesswork, and plan_create's strongest coverage rules ('must literally call every route') are inexpressible.

## Intent

`Drydock_Specification.md` § Specification Decomposition Methodology ('This structure populates `Provides`, `Consumes`, and `Depends On`' with rows for CLI, library, data pipeline, and event-driven systems) and § Drydock Features ('Dependency-graph build plan with runnable frontier ensures correct build order').

## Evidence

`prompts/BLUEPRINTS_CONTRACT.md` § Dependency Declarations: '`FEATURE-*.md` providing routes → listed in `Provides` | Extracted from route tables in file' and '`SCREEN-*.md` using a route → depends on providing `FEATURE`' — the complete set of automatic conventions. `prompts/plan_create.md` step 6 and its Hard Rules speak only of routes: 'A SCREEN spec's Programmatic Acceptance must literally call every route in its `Provides` and `Consumes`'.

## Recommendation

Namespace every interface point: `route:GET /catalog`, `cmd:drydock plan`, `symbol:Database.items.get`, `dataset:orders_daily`, `topic:orders.created`, `event:OrderPlaced`, `job:nightly_rollup`, `resource:aws_s3_bucket.assets`, `config:DRYDOCK_WORKSPACE`. `drydock plan` matches `Consumes` to `Provides` on the exact namespaced token regardless of kind, so the graph is computed for every project shape. Each kind carries a coverage obligation the plan validator enforces, and a `CONTRACT-{Name}.md` typed file kind holds non-route interface contracts (dataset schema, event schema, public API surface, command surface).

## Stories

### Story 1: Define and parse the namespaced interface-point grammar

As the Commander, I want interface points declared with an explicit kind, so that the dependency graph is computed for projects that are not made of HTTP routes.

**Acceptance Criteria**

- A `Provides` value of `dataset:orders_daily` parses to kind `dataset` and identifier `orders_daily`.
- A bare value with no recognized prefix parses as kind `route` when it matches an HTTP method-and-path shape, and is a validation error otherwise.
- An unknown prefix (`widget:foo`) is a validation error naming the file and the offending token.
- A `Consumes` token matches a `Provides` token in another file only on exact kind-and-identifier equality.

**Tests (RED first)**

- test_parse_namespaced_provides_kinds
- test_bare_http_shape_defaults_to_route_kind
- test_unknown_prefix_is_validation_error_naming_file
- test_consumes_matches_provides_on_exact_kind_and_identifier

### Story 2: Compute the dependency graph from all interface kinds

As the Commander, I want a pipeline's dataset producers to be ordered before their consumers, so that build order is derived rather than guessed.

**Acceptance Criteria**

- A file consuming `dataset:orders_daily` receives a `Depends On` edge to the file providing it, without any route present in the Blueprint.
- A consumer of `topic:orders.created` is ordered after its producer in the emitted Manifest block order.
- A `Consumes` token with no provider anywhere in the Blueprint is a validation error naming both the consuming file and the token.
- A cycle across non-route kinds is reported with the participating files listed.

**Tests (RED first)**

- test_dataset_edge_computed_without_routes
- test_topic_producer_ordered_before_consumer
- test_unprovided_consumes_token_is_error
- test_non_route_cycle_reported_with_participants

### Story 3: Per-kind acceptance coverage obligations

As the Commander, I want each interface kind to carry an acceptance obligation appropriate to its shape, so that a proven story means something in a pipeline or a library, not only in a web app.

**Acceptance Criteria**

- A spec providing `cmd:` is rejected unless an assertion invokes that command and asserts both exit status and a stdout or stderr contract.
- A spec providing `dataset:` is rejected unless an assertion asserts the output schema and at least one row or partition invariant.
- A spec providing `topic:` is rejected unless assertions cover publish, consume, and redelivery without duplicate effect.
- A spec providing `symbol:` is rejected unless an assertion imports and calls that symbol by its declared name.

**Tests (RED first)**

- test_cmd_provider_without_exit_and_output_assertion_rejected
- test_dataset_provider_without_schema_assertion_rejected
- test_topic_provider_without_redelivery_assertion_rejected
- test_symbol_provider_without_import_and_call_rejected

### Story 4: Add the CONTRACT typed file kind

As the Commander, I want a typed home for a dataset schema, event schema, public API surface, or command surface, so that non-route contracts stop dissolving into feature prose.

**Acceptance Criteria**

- `CONTRACT` is accepted as a FileType by the typed-header validator and by `drydock validate`.
- A `CONTRACT-*.md` file may declare `Provides` of any kind and is required to end with the four terminal sections.
- `plan_create.md`'s decomposition table names `CONTRACT-*.md` for the `pipeline`, `event-driven`, `library`, and `api` shapes.
- A `CONTRACT-*.md` file participates in `Depends On` computation and receives a compact derivative from `drydock rigging compact`.

**Tests (RED first)**

- test_contract_filetype_accepted_by_validator
- test_contract_file_requires_terminal_sections
- test_decomposition_table_names_contract_for_non_web_shapes
- test_contract_file_gets_compact_derivative

## Definition of Done

- A pipeline fixture with three stages and no HTTP routes produces a correctly ordered Manifest with computed edges.
- An event-driven fixture rejects a consumer story lacking a redelivery assertion.
- `BLUEPRINTS_CONTRACT.md` § Dependency Declarations lists a convention row per interface kind.
- Existing route-only Blueprints validate unchanged with no edits to their headers.

## Implementation Plan

1. Extend the header parser in `validate_specification.py` with a kind-prefixed interface-point type and a strict prefix registry.
2. Rewrite `prompts/BLUEPRINTS_CONTRACT.md` § Dependency Declarations as a per-kind convention table and add the `CONTRACT` FileType to § Specification File Types and the FileType value list.
3. Update `prompts/plan_create.md` step 6, the decomposition table in step 2, and the route-specific Hard Rules to be kind-parameterized; mirror into `plan_create_speckit.md` and `plan_reuse.md`.
4. Implement graph computation over kinds in `planning_session.py` and `build_plan.py`, replacing route-only matching.
5. Implement per-kind coverage checks in `acceptance.py` and surface them through `validate_specification.py`.
6. Add fixtures: `tests/fixtures/blueprint_pipeline_datasets/`, `tests/fixtures/blueprint_event_topics/`, `tests/fixtures/blueprint_library_symbols/`, `tests/fixtures/blueprint_routes_legacy/`.

## Specification Impact

§ Specification Decomposition Methodology (the interface-point table gains explicit token grammar), § Specification File Format (Provides/Consumes/Depends On field description), and § SAIL Phase 2 output-file table (adds `CONTRACT-{Name}.md`). Requires the author's approval.

## Risks

- Existing Blueprints declare bare routes; the bare-route fallback must be permanent, not a migration window.
- Per-kind coverage obligations can be gamed by shallow assertions; DDF-005 and DDF-004 must bound that.
- A new FileType touches `document_generate.md`, `readme_generate.py`, `rigging_compact.py` selection, and QuarterDeck rendering.
