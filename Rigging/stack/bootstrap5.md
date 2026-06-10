# Bootstrap 5 Best Practices

**Version:** 20260320 V1  
**Description:** Bootstrap 5 frontend patterns: layout, components, and form conventions

Technology reference for Bootstrap 5 frontend styling. This file does not change between projects.

Prerequisites: `stack/common.md`

---

## 1. Setup

**Rule**: Load Bootstrap from CDN. Use a single project stylesheet for overrides and custom components.

```html
<!-- In base.html <head> -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
      rel="stylesheet"
      integrity="sha384-..."
      crossorigin="anonymous">
<link rel="stylesheet" href="/static/css/style.css">
```

```html
<!-- Before </body> -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
        integrity="sha384-..."
        crossorigin="anonymous"></script>
```

Rules:
- CDN for Bootstrap CSS and JS bundle (includes Popper)
- Single `static/css/style.css` for all custom styles
- No build step required — no Sass compilation
- Pin a specific Bootstrap version via CDN URL

**Why**: CDN avoids bundling complexity. Single custom stylesheet keeps overrides organized.

---

## 2. Theme — Project-Defined and Configurable

**Rule**: Do NOT set `data-bs-theme` unconditionally. Bootstrap defaults to light mode. The project's `UI-GENERAL.md` defines the exact theme, CSS variables, and color values. Follow that file exactly.

Theme is controlled by an environment variable (e.g. `GAME_THEME=light|dark`). `base.html` reads this at render time and conditionally sets the attribute:

```html
<!-- correct: theme is conditional, not hardcoded -->
<html lang="en" {% if theme == 'dark' %}data-bs-theme="dark"{% endif %}>
```

The route context must pass `theme` to every template (read from `os.environ.get('GAME_THEME', 'light')`).

CSS custom properties are defined in `static/css/style.css` as specified in `UI-GENERAL.md`. Do not invent CSS variables; use only the ones defined there.

**Why**: Dark mode is not appropriate for all applications. The project spec defines the visual design; the stack rule must not override it.

---

## 3. Layout

**Rule**: Use Bootstrap's container and grid system. Stick to `container` or `container-fluid`.

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

### Grid

```html
<div class="row">
    <div class="col-md-8">Main content</div>
    <div class="col-md-4">Sidebar</div>
</div>
```

Rules:
- Use responsive breakpoints (`col-md-*`, `col-lg-*`)
- `mt-4`, `mb-3`, `p-3` for spacing (Bootstrap utility classes)
- Don't fight the grid — use it or skip it, don't half-use it

---

## 4. Components

**Rule**: Use Bootstrap's built-in components. Style with utility classes first, custom CSS second.

### Cards

```html
<div class="card">
    <div class="card-header text-uppercase text-muted small">Section Title</div>
    <div class="card-body">
        <p class="card-text">Content here</p>
    </div>
</div>
```

### Tables

```html
<table class="table table-hover">
    <thead>
        <tr>
            <th>Name</th>
            <th>Status</th>
        </tr>
    </thead>
    <tbody>
        {% for item in items %}
        <tr>
            <td>{{ item.name }}</td>
            <td><span class="badge bg-success">Active</span></td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

### Badges

```html
<span class="badge bg-primary">Primary</span>
<span class="badge bg-success">Active</span>
<span class="badge bg-danger">Error</span>
<span class="badge bg-warning text-dark">Warning</span>
```

### Buttons

```html
<button class="btn btn-sm btn-outline-primary">Action</button>
<button class="btn btn-sm btn-outline-danger">Delete</button>
```

---

## 5. Modals

**Rule**: Use Bootstrap modals for dialogs. For HTMX-loaded content, use custom overlays.

```html
<!-- Bootstrap modal -->
<div class="modal fade" id="confirmModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">Confirm</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">Are you sure?</div>
            <div class="modal-footer">
                <button class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                <button class="btn btn-danger">Confirm</button>
            </div>
        </div>
    </div>
</div>
```

```html
<!-- Custom overlay for dynamic content (HTMX-friendly) -->
<div id="log-overlay" class="position-fixed top-0 start-0 w-100 h-100 d-none"
     style="background: rgba(0,0,0,0.6); z-index: 1050;">
    <div class="container mt-5">
        <pre id="log-content" class="p-3" style="font-family: monospace; background: #1e293b; color: #f1f5f9;"></pre>
        <button onclick="closeOverlay()" class="btn btn-outline-light mt-2">Close</button>
    </div>
</div>
```

**Why**: Bootstrap modals work for static dialogs. Custom overlays are simpler for HTMX-fetched content.

---

## 6. Custom Component Patterns

**Rule**: Define reusable component classes in your stylesheet using CSS custom properties.

```css
/* Operation buttons — consistent sizing */
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

/* Card headers */
.cc-card-header {
    font-size: 0.85rem;
    text-transform: uppercase;
    color: var(--cc-text-muted, #888);
    letter-spacing: 0.05em;
}
```

Rules:
- Use BEM-like naming: `.component--modifier`
- Define colors as CSS custom properties in `:root`
- Keep custom CSS minimal — use Bootstrap utilities first
- Document component classes in a BRANDING.md or style guide

**Why**: Custom properties make theming consistent. BEM naming prevents class collision.

---

## 7. HTMX + Bootstrap Integration

**Rule**: HTMX and Bootstrap coexist without conflict. Use Bootstrap for layout/style, HTMX for behavior.

```html
<!-- HTMX button with Bootstrap styling -->
<button class="btn btn-sm btn-outline-primary op-btn op-btn--local"
        hx-post="/api/project/1/start"
        hx-swap="outerHTML"
        hx-target="closest tr">
    Start
</button>

<!-- HTMX form inside Bootstrap card -->
<div class="card">
    <div class="card-body">
        <form hx-post="/api/project/1/update" hx-swap="outerHTML">
            <input type="text" class="form-control form-control-sm"
                   name="title" value="{{ project.title }}">
        </form>
    </div>
</div>
```

**Why**: Bootstrap handles visual structure. HTMX handles dynamic behavior. No JavaScript framework needed.

---

## 8. Financial Professional Theme

Design token system for a financial-services look (Schwab-inspired). All values go in `static/css/style.css`. The project's `UI-GENERAL.md` specifies the exact values — these are the defaults.

### Color tokens

```css
/* static/css/style.css */
:root {
  --sch-nav-bg:      #33424c;  /* primary nav + utility bar background */
  --sch-nav-text:    #ffffff;  /* nav link text */
  --sch-util-text:   #98A4AE;  /* utility bar secondary link color */
  --sch-accent:      #009CDB;  /* secondary link / accent blue */
  --sch-cta:         #E05A00;  /* CTA button fill (tangerine) */
  --sch-cta-hover:   #C04800;  /* CTA button hover */
  --sch-body-bg:     #ffffff;
  --sch-text:        #33424c;
}
```

### Font

Load Raleway from Google Fonts in `base.html <head>` (substitute for proprietary CharlesModern):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;700&display=swap" rel="stylesheet">
```

```css
body { font-family: 'Raleway', Helvetica, Arial, sans-serif; }
```

### Logo, navbar, utility bar

```css
/* Logo: app_name as bold text — adjust font-size/weight to taste */
.sch-logo {
  font-family: 'Raleway', Helvetica, Arial, sans-serif;
  font-size: 1.6rem;
  font-weight: 700;
  color: #ffffff !important;
  letter-spacing: -0.01em;
  text-decoration: none;
}

/* Primary navbar */
.navbar-schwab {
  background-color: var(--sch-nav-bg) !important;
  min-height: 5rem;
}
.navbar-schwab .nav-link        { color: var(--sch-nav-text) !important; }
.navbar-schwab .nav-link:hover  { color: rgba(255,255,255,0.75) !important; }
.navbar-schwab .nav-link.active { color: #ffffff !important; font-weight: 600; }

/* Utility bar (Tier 1) */
.navbar-util {
  background-color: var(--sch-nav-bg);
  font-size: 0.75rem;
}
.navbar-util a       { color: var(--sch-util-text); text-decoration: none; }
.navbar-util a:hover { color: var(--sch-nav-text); text-decoration: underline; }
```

### CTA pill button

```css
/* Full-radius pill button — use class="btn btn-cta" in templates */
.btn-cta {
  background-color: var(--sch-cta);
  border-color:     var(--sch-cta);
  color:            #ffffff;
  border-radius:    9999px;
  font-weight:      600;
  padding:          0.4rem 1.25rem;
  text-decoration:  none;
  display:          inline-block;
}
.btn-cta:hover {
  background-color: var(--sch-cta-hover);
  border-color:     var(--sch-cta-hover);
  color:            #ffffff;
}

/* Override Bootstrap btn-primary to match theme */
.btn-primary {
  --bs-btn-bg:                 var(--sch-cta);
  --bs-btn-border-color:       var(--sch-cta);
  --bs-btn-hover-bg:           var(--sch-cta-hover);
  --bs-btn-hover-border-color: var(--sch-cta-hover);
  border-radius: 9999px;
  font-weight: 600;
}
```

---

## Summary Checklist

- [ ] Bootstrap 5.3+ loaded from CDN (CSS + JS bundle)
- [ ] Single `static/css/style.css` for custom styles
- [ ] Theme set via `GAME_THEME` env var (default: light); `data-bs-theme` applied conditionally in `base.html`
- [ ] Container-based layout with responsive grid
- [ ] Standard Bootstrap components (cards, tables, badges, buttons)
- [ ] Custom component classes with BEM naming and CSS variables
- [ ] HTMX attributes on Bootstrap-styled elements
