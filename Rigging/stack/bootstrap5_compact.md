<!-- Compacted from RulesEngine/stack/bootstrap5.md on 2026-04-30 by prompts/compact_file.md — regenerate via bin/rulesengine_compact.sh -->

# Bootstrap 5 — Compact

## Setup

Load Bootstrap from CDN. Single `static/css/style.css` for all custom styles. No build step. Pin a specific version.

```html
<!-- <head> -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
      rel="stylesheet" integrity="sha384-..." crossorigin="anonymous">
<link rel="stylesheet" href="/static/css/style.css">
```

```html
<!-- before </body> -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
        integrity="sha384-..." crossorigin="anonymous"></script>
```

## Theme

Do NOT set `data-bs-theme` unconditionally. `UI-GENERAL.md` defines the exact theme, CSS variables, and color values — follow that file exactly. Theme is controlled by an env var (e.g. `GAME_THEME=light|dark`):

```html
<html lang="en" {% if theme == 'dark' %}data-bs-theme="dark"{% endif %}>
```

Route context must pass `theme` to every template (`os.environ.get('GAME_THEME', 'light')`). Do not invent CSS variables; use only ones defined in `UI-GENERAL.md`.

## Layout

```html
<body>
    <nav class="navbar navbar-expand-lg cc-topnav">
        <div class="container">
            <a class="navbar-brand" href="/">App Name</a>
        </div>
    </nav>
    <main class="container mt-4">
        {% block content %}{% endblock %}
    </main>
</body>
```

```html
<div class="row">
    <div class="col-md-8">Main content</div>
    <div class="col-md-4">Sidebar</div>
</div>
```

Use responsive breakpoints (`col-md-*`, `col-lg-*`). Use `mt-4`, `mb-3`, `p-3` for spacing.

## Components

```html
<!-- Card -->
<div class="card">
    <div class="card-header text-uppercase text-muted small">Section Title</div>
    <div class="card-body"><p class="card-text">Content here</p></div>
</div>

<!-- Table -->
<table class="table table-hover">
    <thead><tr><th>Name</th><th>Status</th></tr></thead>
    <tbody>
        {% for item in items %}
        <tr>
            <td>{{ item.name }}</td>
            <td><span class="badge bg-success">Active</span></td>
        </tr>
        {% endfor %}
    </tbody>
</table>

<!-- Badges -->
<span class="badge bg-primary">Primary</span>
<span class="badge bg-success">Active</span>
<span class="badge bg-danger">Error</span>
<span class="badge bg-warning text-dark">Warning</span>

<!-- Buttons -->
<button class="btn btn-sm btn-outline-primary">Action</button>
<button class="btn btn-sm btn-outline-danger">Delete</button>
```

## Modals

Use Bootstrap modals for static dialogs. Use custom overlays for HTMX-loaded content.

```html
<!-- Bootstrap modal -->
<div class="modal fade" id="confirmModal" tabindex="-1">
    <div class="modal-dialog"><div class="modal-content">
        <div class="modal-header">
            <h5 class="modal-title">Confirm</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body">Are you sure?</div>
        <div class="modal-footer">
            <button class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button class="btn btn-danger">Confirm</button>
        </div>
    </div></div>
</div>

<!-- Custom overlay for HTMX-fetched content -->
<div id="log-overlay" class="position-fixed top-0 start-0 w-100 h-100 d-none"
     style="background: rgba(0,0,0,0.6); z-index: 1050;">
    <div class="container mt-5">
        <pre id="log-content" class="p-3" style="font-family: monospace; background: #1e293b; color: #f1f5f9;"></pre>
        <button onclick="closeOverlay()" class="btn btn-outline-light mt-2">Close</button>
    </div>
</div>
```

## Custom Components

Define reusable classes in `static/css/style.css` using CSS custom properties. Use BEM-like naming (`.component--modifier`). Keep custom CSS minimal — Bootstrap utilities first.

```css
.op-btn {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.25rem 0.65rem;
    border-radius: 4px;
    white-space: nowrap;
}
.op-btn--local { background: var(--btn-local, #4fc3f7); color: #000; }
.op-btn--remote { background: var(--btn-remote, #81c784); color: #000; }
.op-btn--danger { background: var(--btn-danger, #ef5350); color: #fff; }

.cc-card-header {
    font-size: 0.85rem;
    text-transform: uppercase;
    color: var(--cc-text-muted, #888);
    letter-spacing: 0.05em;
}
```

## HTMX + Bootstrap

HTMX and Bootstrap coexist without conflict. Bootstrap handles layout/style; HTMX handles behavior.

```html
<button class="btn btn-sm btn-outline-primary op-btn op-btn--local"
        hx-post="/api/project/1/start"
        hx-swap="outerHTML"
        hx-target="closest tr">
    Start
</button>
```

## Financial Professional Theme

All values go in `static/css/style.css`. `UI-GENERAL.md` specifies exact values — these are defaults.

```css
/* static/css/style.css */
:root {
  --sch-nav-bg:      #33424c;
  --sch-nav-text:    #ffffff;
  --sch-util-text:   #98A4AE;
  --sch-accent:      #009CDB;
  --sch-cta:         #E05A00;
  --sch-cta-hover:   #C04800;
  --sch-body-bg:     #ffffff;
  --sch-text:        #33424c;
}
```

Load Raleway from Google Fonts in `base.html <head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;700&display=swap" rel="stylesheet">
```

```css
body { font-family: 'Raleway', Helvetica, Arial, sans-serif; }

.sch-logo {
  font-family: 'Raleway', Helvetica, Arial, sans-serif;
  font-size: 1.6rem; font-weight: 700;
  color: #ffffff !important;
  letter-spacing: -0.01em; text-decoration: none;
}

.navbar-schwab { background-color: var(--sch-nav-bg) !important; min-height: 5rem; }
.navbar-schwab .nav-link        { color: var(--sch-nav-text) !important; }
.navbar-schwab .nav-link:hover  { color: rgba(255,255,255,0.75) !important; }
.navbar-schwab .nav-link.active { color: #ffffff !important; font-weight: 600; }

.navbar-util { background-color: var(--sch-nav-bg); font-size: 0.75rem; }
.navbar-util a       { color: var(--sch-util-text); text-decoration: none; }
.navbar-util a:hover { color: var(--sch-nav-text); text-decoration: underline; }

.btn-cta {
  background-color: var(--sch-cta); border-color: var(--sch-cta);
  color: #ffffff; border-radius: 9999px;
  font-weight: 600; padding: 0.4rem 1.25rem;
  text-decoration: none; display: inline-block;
}
.btn-cta:hover { background-color: var(--sch-cta-hover); border-color: var(--sch-cta-hover); color: #ffffff; }

.btn-primary {
  --bs-btn-bg:                 var(--sch-cta);
  --bs-btn-border-color:       var(--sch-cta);
  --bs-btn-hover-bg:           var(--sch-cta-hover);
  --bs-btn-hover-border-color: var(--sch-cta-hover);
  border-radius: 9999px; font-weight: 600;
}
```
