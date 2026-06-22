<!-- Compacted from flask.md on 2026-06-22 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Flask Best Practices — Usage Surface

## Application Factory

### create_app

Creates and returns a configured Flask application instance.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| config | str \| object | no | Config class or dotted import string; defaults to `'config.DevConfig'` |

`Returns: Flask — configured application instance with blueprints and error handlers registered`

### register_error_handlers

Registers 404, 500, and unhandled-exception error handlers on a Flask app.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| app | Flask | yes | Application instance to register handlers on |

`Returns: None`

## Health Check

### GET /health

Checks service health by verifying database connectivity.

`Returns: JSON — {"status": "ok"} with HTTP 200, or {"status": "error", "detail": str} with HTTP 500`

## Navigation Configuration

### util_links

Context processor variable injected into all templates; list of utility links rendered in the top strip (desktop only).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| util_links | list[{label: str, url: str}] | no | Links rendered right-justified in tier-1 utility bar; omit or pass `[]` to hide the bar |

`Returns: dict key injected into Jinja2 template context`

### nav_items

Context processor variable for primary nav links rendered center-left with mobile hamburger collapse.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| nav_items | list[{label: str, url: str}] | no | Links rendered in tier-2 primary nav; active state set automatically by matching `request.path` |

`Returns: dict key injected into Jinja2 template context`

### cta_label

Context processor variable controlling the optional CTA button in the primary nav.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| cta_label | str \| None | no | Button text; pass `None` to hide the button entirely |
| cta_url | str | no | Button destination URL; defaults to `'/'` |

`Returns: dict keys injected into Jinja2 template context`
