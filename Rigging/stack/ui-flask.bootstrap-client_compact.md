<!-- Compacted from Rigging/stack/ui-flask.bootstrap-client.md sha256=89f834ef9f99ba3337caffc67abb1886b408c8576271a3e7c59da67a458b1ac2 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Flask + Bootstrap 5 — Screen Build Reference — Contract Surface

## Navigation

### inject_nav

Provides navigation context values to templates.

| Field | Type | Required |
|---|---|---|
| `util_links` | list of `{label: str, url: str}` | Yes |
| `nav_items` | list of `{label: str, url: str}` | Yes |
| `cta_label` | `str` or `None` | Yes |
| `cta_url` | `str` | Yes |

Constraints: Navigation content is injected through the context processor; navigation text is not hardcoded in templates.

### Rule: navigation-zones

The interface supports utility links, an application name, primary navigation links, and an optional CTA button.

Constraints: Utility links are desktop-only; the CTA is optional.

## Flask Routes

### GET /section/path

Renders `section/view_name.html` with `items` and `title` template values.

### POST /section/path/<int:item_id>

Processes an action for the integer `item_id`, flashes a success message, and redirects to the section view.

### Rule: blueprint-registration

The section blueprint is registered with the application under the `/section` URL prefix.

## Templates and Responses

### Rule: base-template

Screen templates extend `base.html` and provide `title` and `content` blocks.

### Rule: collection-rendering

Item collections render one row per item and display a no-items row when empty.

### Rule: flash-messages

Flash messages expose a category and message and render as Bootstrap alerts.

### Rule: htmx-partial-response

HTMX requests return a partial template; non-HTMX requests return the full page template.

Constraints: Detect HTMX requests using the `HX-Request` header.

## HTMX

### Rule: htmx-request-contract

Interactive elements may declare request behavior with `hx-get`, `hx-post`, `hx-target`, `hx-swap`, `hx-trigger`, `hx-confirm`, and `hx-include`.

Constraints: `hx-target` identifies the response destination; `hx-swap` controls replacement behavior.

## Configuration

### Rule: theme-configuration

The screen foundation uses the defined financial-professional theme variables and Bootstrap CTA styling.

### Rule: bootstrap-components

Screens may use Bootstrap 5 cards, tables, buttons, badges, forms, modals, and layout utilities.
