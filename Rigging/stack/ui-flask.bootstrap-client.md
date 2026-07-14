# Flask + Bootstrap 5 — Screen Build Reference

**Category:** Web Server

Condensed patterns for building screens on an already-running Flask/Bootstrap server.
Applies when phases include SCREEN-*.md (with or without FEATURE-*.md).
Full source detail: `stack/flask.md`, `stack/bootstrap5.md`.

---

## Theme Setup (Financial Professional)

In `static/css/style.css`:

```css
:root {
  --sch-nav-bg:    #33424c;
  --sch-nav-text:  #ffffff;
  --sch-util-text: #98A4AE;
  --sch-accent:    #009CDB;
  --sch-cta:       #E05A00;
  --sch-cta-hover: #C04800;
}

body { font-family: 'Raleway', Helvetica, Arial, sans-serif; }

/* Logo */
.sch-logo {
  font-family: 'Raleway', Helvetica, Arial, sans-serif;
  font-size: 1.6rem; font-weight: 700;
  color: #ffffff !important; letter-spacing: -0.01em; text-decoration: none;
}

/* Primary navbar */
.navbar-schwab { background-color: var(--sch-nav-bg) !important; min-height: 5rem; }
.navbar-schwab .nav-link        { color: var(--sch-nav-text) !important; }
.navbar-schwab .nav-link:hover  { color: rgba(255,255,255,0.75) !important; }
.navbar-schwab .nav-link.active { color: #ffffff !important; font-weight: 600; }

/* Utility bar */
.navbar-util { background-color: var(--sch-nav-bg); font-size: 0.75rem; }
.navbar-util a       { color: var(--sch-util-text); text-decoration: none; }
.navbar-util a:hover { color: var(--sch-nav-text); text-decoration: underline; }

/* CTA pill button */
.btn-cta {
  background-color: var(--sch-cta); border-color: var(--sch-cta);
  color: #ffffff; border-radius: 9999px; font-weight: 600;
  padding: 0.4rem 1.25rem; text-decoration: none; display: inline-block;
}
.btn-cta:hover { background-color: var(--sch-cta-hover); border-color: var(--sch-cta-hover); color: #ffffff; }

.btn-primary {
  --bs-btn-bg: var(--sch-cta); --bs-btn-border-color: var(--sch-cta);
  --bs-btn-hover-bg: var(--sch-cta-hover); --bs-btn-hover-border-color: var(--sch-cta-hover);
  border-radius: 9999px; font-weight: 600;
}
```

In `base.html <head>`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;700&display=swap" rel="stylesheet">
```

---

## Two-Tier Navigation

Four zones — no hardcoded text. Content injected via context processor per project spec.

| Zone | Tier | Position | Variable |
|------|------|----------|----------|
| Utility links | 1 — top strip, desktop only | Right | `util_links` list |
| Logo | 2 — primary nav | Left | `app_name` (styled text) |
| Nav links | 2 — primary nav | Center-left | `nav_items` list |
| CTA button | 2 — primary nav | Right, optional | `cta_label` / `cta_url` |

`app/templates/_nav.html`:
```html
{% if util_links %}
<div class="navbar-util py-1 d-none d-lg-block">
  <div class="container-fluid">
    <div class="d-flex justify-content-end gap-4">
      {% for link in util_links %}<a href="{{ link.url }}">{{ link.label }}</a>{% endfor %}
    </div>
  </div>
</div>
{% endif %}

<nav class="navbar navbar-expand-lg navbar-schwab">
  <div class="container-fluid">
    <a class="navbar-brand sch-logo" href="/">{{ app_name }}</a>
    <button class="navbar-toggler border-0" type="button"
            data-bs-toggle="collapse" data-bs-target="#primaryNav"
            aria-label="Toggle navigation">
      <span class="navbar-toggler-icon" style="filter: invert(1)"></span>
    </button>
    <div class="collapse navbar-collapse" id="primaryNav">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
        {% for item in nav_items %}
        <li class="nav-item">
          <a class="nav-link {% if request.path == item.url %}active{% endif %}"
             href="{{ item.url }}">{{ item.label }}</a>
        </li>
        {% endfor %}
      </ul>
      {% if cta_label %}<a href="{{ cta_url }}" class="btn btn-cta ms-3">{{ cta_label }}</a>{% endif %}
    </div>
  </div>
</nav>
```

Context processor skeleton (populate from project UI-GENERAL.md):
```python
@app.context_processor
def inject_nav():
    return {
        'util_links': [],   # [{'label': str, 'url': str}, ...]
        'nav_items':  [],   # [{'label': str, 'url': str}, ...]
        'cta_label':  None, # str or None
        'cta_url':    '/',
    }
```

---

## Flask Route Boilerplate

```python
from flask import Blueprint, render_template, request, redirect, url_for, flash

bp = Blueprint("section", __name__, url_prefix="/section")

@bp.route("/path")
def view_name():
    return render_template("section/view_name.html", items=items, title="Page Title")

@bp.route("/path/<int:item_id>", methods=["POST"])
def action_name(item_id):
    flash("Done.", "success")
    return redirect(url_for("section.view_name"))
```

Register in `app/__init__.py`:
```python
from app.section import bp as section_bp
app.register_blueprint(section_bp)
```

---

## Jinja2 Template Structure

```html
{% extends "base.html" %}
{% block title %}Page Title{% endblock %}
{% block content %}
<div class="container-fluid">
  <h1>{{ title }}</h1>
</div>
{% endblock %}
```

Loop / conditional:
```html
{% for item in items %}
  <tr><td>{{ item.name }}</td></tr>
{% else %}
  <tr><td>No items.</td></tr>
{% endfor %}
{% if condition %}...{% endif %}
```

Flash messages:
```html
{% with messages = get_flashed_messages(with_categories=true) %}
  {% for category, msg in messages %}
    <div class="alert alert-{{ category }} alert-dismissible fade show">{{ msg }}</div>
  {% endfor %}
{% endwith %}
```

HTMX partial response:
```python
if request.headers.get("HX-Request"):
    return render_template("section/_partial.html", items=items)
return render_template("section/view.html", items=items)
```

---

## HTMX Essentials

| Attribute | Use |
|-----------|-----|
| `hx-get="/path"` | GET on trigger |
| `hx-post="/path"` | POST on trigger |
| `hx-target="#id"` | Where to insert response |
| `hx-swap="innerHTML"` | Replace inner HTML (default) |
| `hx-swap="outerHTML"` | Replace element itself |
| `hx-trigger="click"` | Trigger event |
| `hx-trigger="change"` | On input change |
| `hx-confirm="Sure?"` | Confirmation dialog |
| `hx-include="#form-id"` | Include another form's values |

---

## Bootstrap 5 Components

**Cards:**
```html
<div class="card">
  <div class="card-header">Title</div>
  <div class="card-body"><p class="card-text">Content</p></div>
</div>
```

**Tables:**
```html
<table class="table table-striped table-hover">
  <thead><tr><th>Column</th></tr></thead>
  <tbody><tr><td>Value</td></tr></tbody>
</table>
```

**Buttons:**
```html
<button class="btn btn-cta">Primary CTA</button>
<button class="btn btn-secondary">Cancel</button>
<button class="btn btn-danger">Delete</button>
<button class="btn btn-sm btn-outline-secondary">Small</button>
```

**Badges:**
```html
<span class="badge bg-success">Active</span>
<span class="badge bg-danger">Error</span>
<span class="badge bg-warning text-dark">Warning</span>
<span class="badge bg-secondary">Inactive</span>
```

**Forms:**
```html
<form method="post">
  <div class="mb-3">
    <label class="form-label">Field</label>
    <input type="text" class="form-control" name="field" value="{{ value }}">
  </div>
  <button type="submit" class="btn btn-cta">Submit</button>
</form>
```

**Modal:**
```html
<button class="btn btn-cta" data-bs-toggle="modal" data-bs-target="#myModal">Open</button>
<div class="modal fade" id="myModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header">
      <h5 class="modal-title">Title</h5>
      <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body">Content</div>
    <div class="modal-footer">
      <button class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
      <button class="btn btn-cta">Confirm</button>
    </div>
  </div></div>
</div>
```

**Layout utilities:** `container-fluid`, `d-flex`, `flex-column`, `gap-2`/`gap-3`, `mb-3`/`mt-3`, `row`/`col`/`col-md-6`
