# UI-GENERAL: Marina Setup Shell

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina setup screens share a desktop-first HTMX and Bootstrap 5 shell with a dark header, two-tier navigation, and consistent status semantics. |
| Depends On  | FEATURE-RUNTIME-PLATFORM.md |
| Provides    | marina-setup-ui-patterns |
| Phase       | 2 |

## Theme

Marina uses a light body with dark navigation and dark page-header variants.

Core variables:
- `--mn-nav-bg: #0f172a`
- `--mn-nav-text: #f1f5f9`
- `--mn-subnav-bg: #f1f5f9`
- `--mn-subnav-text: #334155`
- `--mn-accent: #0d9488`
- `--mn-border: #e2e8f0`
- `--mn-muted: #64748b`
- `--mn-btn-primary-bg: #0d9488`
- `--mn-btn-danger-bg: #dc2626`
- `--mn-btn-caution-bg: #d97706`
- `--mn-btn-action-bg: #3b82f6`

The default theme is `light`. Theme state is controlled by `app_theme` and not hardcoded in templates.

## Navigation

### Top navigation

Always present:
- brand: `Marina`
- active top tab: `SETUP`

### Sub-navigation

Rendered for the Setup section with these tabs in order:
1. Summary
2. AWS
3. Terraform
4. GitHub
5. Git Scan
6. Repositories
7. Projects
8. Settings

Disabled tabs remain visible, muted, and non-navigable with a prerequisite tooltip.

## Page Header

Every Setup screen renders:
- a left KPI block
- a centered `Marina` title with anchor icon
- a right help-text block

Header backgrounds:
- `mn-hdr-bg--summary`
- `mn-hdr-bg--cloud`
- `mn-hdr-bg--git`
- `mn-hdr-bg--settings`

KPI components allowed:
- status light
- count block
- all-good indicator
- header action button
- empty spacer

## Shared Components

### Cards

Standard card pattern:
- 1px border using `--mn-border`
- 8px radius
- white body surface
- uppercase or strong section header label

### Buttons

Only these semantic button classes are allowed:
- `btn-mn-primary`
- `btn-mn-danger`
- `btn-mn-caution`
- `btn-mn-action`
- `btn-mn-secondary`

### Badges and status signals

Lifecycle badge palette:
- `IDEA` slate
- `PROTOTYPE` amber
- `ACTIVE` teal
- `PRODUCTION` green
- `ARCHIVED` gray
- `UNKNOWN` muted

Checklist icons:
- `✅`
- `⚠️`
- `❌`
- `📌`

### Inline editable fields

Settings-backed inputs are always visible.
- blur or tab-out triggers `POST /api/setup/config`
- success and failure return toast fragments
- restart-required fields show a persistent inline note after successful save

## HTMX Conventions

- `hx-get` loads fragments
- `hx-post` triggers state-changing actions
- `hx-target` names the smallest replaceable container
- `hx-swap` is normally `innerHTML` or `outerHTML`

Server responses are HTML fragments for partial updates and full HTML for initial route loads.

## Responsive Rules

- desktop-first layout
- minimum supported width: 1024px
- horizontal scroll is acceptable on the nav bar below that width
- screen tables remain single-row per entity and do not expand into nested detail panels

## Screen Contract

All Setup screens:
- extend the shared base template
- set `active_section="setup"`
- set `active_page` to the tab slug
- render the shared top nav, sub nav, and page header
- use HTMX fragments for local refreshes instead of full-page reloads where practical

## Acceptance Criteria

- Every Setup screen uses the shared top nav, sub nav, header, button semantics, and status vocabulary.
- Disabled tabs remain visible and explain the missing prerequisite.
- Local screen interactions update specific fragments instead of forcing full-page reloads.

## Guardrails

- Do not use ad hoc Bootstrap color classes in place of the Marina semantic button classes.
- Do not hide disabled tabs.
- Do not hardcode dark mode on the root HTML element.

## Open Questions

- None.
