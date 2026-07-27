---
id: DDF-011
title: Generalize interface-point integrity beyond HTTP routes
area: drydock plan
impact: 7
complexity: 5
rank: 13
generated_at: 2026-07-26T20:31:43-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-011: Generalize interface-point integrity beyond HTTP routes

| Field | Value |
|---|---|
| Area | drydock plan |
| Impact | 7/10 |
| Complexity | 5/10 |
| Rank | 13 |
| Project Types | Data pipeline / ETL, Library / SDK, Event-driven / streaming, CLI tool, Multi-service system |

## Problem

The Specification names five kinds of interface points that populate `Provides`, `Consumes`, and `Depends On` — routes, commands, API symbols, datasets, topics — but every enforced rule is route-shaped. A SCREEN referencing an unprovided route is an error; a pipeline stage consuming an unproduced dataset, a library consuming an undeclared symbol, or a handler subscribing to a topic nobody publishes are all silently accepted, and acceptance coverage is only required to name literal route paths.

## Intent

Specification `Specification Decomposition Methodology` — the table mapping system shape to `Interface points named in Provides / Consumes`.

## Evidence

Specification: `A SCREEN file referencing a route not listed in any FEATURE Provides field is an error.` `prompts/plan_create.md` step 5: `naming each literal route path in at least one assertion`; `prompts/BLUEPRINTS_CONTRACT.md` Dependency Declarations table lists route extraction conventions only.

## Recommendation

Interface points become typed: each `Provides`/`Consumes` entry carries a kind prefix (`route:`, `cmd:`, `symbol:`, `dataset:`, `topic:`), defaulted from `SYSTEM_SHAPE` for backward compatibility. `validate_specification.py` enforces that every consumed or depended-on interface point resolves to some declared provider. The acceptance-coverage rule generalizes from routes to every declared interface point of any kind: a spec's proofs must reference each point it provides at least once.

## Stories

### Story 1: Typed interface-point grammar

As the Commander, I want interface points to declare what kind of thing they are, so that non-web projects get the same integrity checks web projects get.

**Acceptance Criteria**

- `Provides: symbol:Database.items.get, dataset:warehouse.orders` parses into two typed points with the correct kinds.
- An unprefixed entry is assigned the default kind for the Target's `SYSTEM_SHAPE` and existing route-only Blueprints parse unchanged.
- An unknown prefix is a validation error naming the entry.

**Tests (RED first)**

- tests/test_validate_specification.py::test_typed_interface_points_parse
- tests/test_validate_specification.py::test_unprefixed_entry_uses_shape_default
- tests/test_validate_specification.py::test_unknown_prefix_is_error

### Story 2: Provider resolution for every kind

As the Commander, I want a consumed interface point with no provider to be an error regardless of kind, so that dangling dependencies are caught at plan time.

**Acceptance Criteria**

- A spec consuming `topic:orders.created` that no spec provides yields error `interface-point-unprovided` naming the point and the consuming file.
- The same for `dataset:`, `symbol:`, `cmd:`, and `route:` kinds.
- A fully resolved Blueprint produces no such error.

**Tests (RED first)**

- tests/test_validate_specification.py::test_unprovided_topic_is_error
- tests/test_validate_specification.py::test_unprovided_dataset_is_error
- tests/test_validate_specification.py::test_unprovided_symbol_is_error
- tests/test_validate_specification.py::test_resolved_blueprint_has_no_errors

### Story 3: Acceptance coverage for every provided point

As the Commander, I want every declared capability exercised by at least one proof, so that a library or pipeline cannot ship unproven surface.

**Acceptance Criteria**

- A FEATURE declaring `symbol:parse_block` whose proofs never reference that identifier yields admission defect `interface-point-unexercised`.
- The route-coverage rule is expressed through the same generalized check with identical behavior on existing web fixtures.
- A spec whose proofs reference every provided point passes.

**Tests (RED first)**

- tests/test_plan_admission.py::test_unexercised_symbol_is_defect
- tests/test_plan_admission.py::test_route_coverage_behavior_unchanged_on_web_fixture
- tests/test_plan_admission.py::test_fully_exercised_spec_passes

## Definition of Done

- Every one of the five interface-point kinds in the Specification's decomposition table has provider resolution and acceptance coverage enforced.
- Existing route-only Blueprints validate and plan with identical results.
- `plan_create.md`'s route-specific acceptance rules are restated generically.

## Implementation Plan

1. Add `drydock/interface_points.py` with `parse_point(entry, default_kind) -> Point(kind, name)` and a resolver over a Blueprint's declared points.
2. Wire the resolver into `validate_specification.py` for provider resolution and into `plan_admission.py` for acceptance coverage.
3. Update `prompts/BLUEPRINTS_CONTRACT.md` Dependency Declarations table with the kind prefixes and the per-shape defaults.
4. Rewrite the route-specific coverage rules in `prompts/plan_create.md` step 5 and `prompts/plan_conform.md` as generic interface-point rules, keeping route wording as the worked example.
5. Extend `prompts/analyze.md` Relationship Model guidance so analyze names interface points with kinds.
6. Add fixtures per kind in `tests/test_validate_specification.py` and `tests/test_plan_admission.py`.

## Specification Impact

The `Specification File Format` header description of `Depends On`/`Provides`/`Consumes` and the sentence `A SCREEN file referencing a route not listed in any FEATURE Provides field is an error` would need the author's approval to generalize.

## Risks

- Symbol-level coverage by textual reference is weak — a proof that merely mentions a symbol name in a comment would satisfy it; the check must require the identifier in a call or attribute position for `python` runtime proofs.
- GraphQL and similar single-route surfaces still need a schema-field kind; this feature makes that extension possible but does not deliver it.
