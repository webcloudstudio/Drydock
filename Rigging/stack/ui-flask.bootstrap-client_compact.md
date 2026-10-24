<!-- Compacted from Rigging/stack/ui-flask.bootstrap-client.md sha256=9848c984013ee1f429087660bff957f6ef6009dbd33e099de986e4f2cc789158 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Flask + Bootstrap 5 — Screen Build Reference — Contract Surface

## Navigation

### function inject_nav
Provides navigation context to templates.

Returns:

| Field | Type | Default |
|---|---|---|
| `util_links` | list of `{label: str, url: str}` | `[]` |
| `nav_items` | list of `{label: str, url: str}` | `[]` |
| `cta_label` | `str \| None` | `None` |
| `cta_url` | `str` | `/` |

Constraints: Navigation text is injected through context; templates must not hardcode navigation labels.

## Flask Routes

### GET /section/path
Renders `section/view_name.html` with `items` and `title` context values.

### POST /section/path/<int:item_id>
Performs the item action, flashes a success message, and redirects to `section.view_name`.

Constraints: Register the section blueprint in the application with `app.register_blueprint(section_bp)`.

## Templates

### base.html
Provides the `title` and `content` blocks used by screen templates.

### HTMX partial response
Returns `section/_partial.html` with `items` when the request contains `HX-Request`; otherwise returns `section/view.html` with `items`.

### Rule: flash-message-rendering
Templates render flashed messages with their categories as Bootstrap alert classes.

## HTMX

### Rule: htmx-attributes
Supported request and response controls include:

| Attribute | Contract |
|---|---|
| `hx-get` | Issues a GET request to the specified path. |
| `hx-post` | Issues a POST request to the specified path. |
| `hx-target` | Selects the response insertion target. |
| `hx-swap` | Selects replacement behavior: `innerHTML` or `outerHTML`. |
| `hx-trigger` | Selects the triggering event, including `click` or `change`. |
| `hx-confirm` | Requires confirmation using the supplied message. |
| `hx-include` | Includes values from the specified form. |

Constraints: `innerHTML` is the default swap behavior.

## Styling Configuration

### config_key theme-css
Defines the required financial-professional theme variables and component styles in `static/css/style.css`.

Constraints: Define `--sch-nav-bg`, `--sch-nav-text`, `--sch-util-text`, `--sch-accent`, `--sch-cta`, and `--sch-cta-hover`; use the CTA variables for `.btn-cta` and Bootstrap `.btn-primary`.

### config_key raleway-font
Loads Raleway in `base.html` using Google Fonts preconnect and stylesheet links.

## Bootstrap Components

### Rule: bootstrap-component-contract
Screens may use Bootstrap 5 cards, tables, buttons, badges, forms, modals, and layout utilities.

Constraints: Forms submit with `method="post"`; destructive actions use `btn-danger`; primary actions use `btn-cta`; standard layout uses supported utilities including `container-fluid`, `d-flex`, `gap-*`, `row`, and `col-md-6`.
