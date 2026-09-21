<!-- Compacted from Rigging/stack/bootstrap5.md sha256=e954809df83d6f2dbd420e053031b1ef1dee64bda409aa3c103488791b5c4020 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Bootstrap 5 Best Practices — Contract Surface

### config_key `Bootstrap CDN`
Loads Bootstrap 5.3.3 CSS and JavaScript bundle from CDN.

Constraints: Pin a specific Bootstrap version; include the JS bundle with Popper; use one project stylesheet at `static/css/style.css`; no Sass or build step.

### config_key `GAME_THEME`
Controls the rendered Bootstrap theme.

| Field | Default |
|---|---|
| `GAME_THEME` | `light` |

Constraints: Read with `os.environ.get('GAME_THEME', 'light')`; pass `theme` to every template; apply `data-bs-theme="dark"` only when `theme == 'dark'`; follow project-defined `UI-GENERAL.md` theme values and CSS variables.

### Rule: responsive-layout
Uses Bootstrap `container` or `container-fluid` layouts with responsive grid breakpoints.

Constraints: Use breakpoint classes such as `col-md-*` and `col-lg-*`; use Bootstrap spacing utilities such as `mt-4`, `mb-3`, and `p-3`.

### Rule: bootstrap-components
Uses Bootstrap built-in cards, tables, badges, buttons, and modals.

Constraints: Prefer Bootstrap utility classes before custom CSS.

### Rule: dynamic-dialogs
Uses Bootstrap modals for static dialogs and custom overlays for HTMX-loaded content.

Constraints: HTMX dynamic overlays must provide a close action and remain compatible with fetched content.

### Rule: custom-components
Defines reusable custom component classes in `static/css/style.css`.

Constraints: Use BEM-like names such as `.component--modifier`; define colors as CSS custom properties in `:root`; keep custom CSS minimal; document component classes in `BRANDING.md` or a style guide.

### Rule: htmx-integration
Uses HTMX attributes for dynamic behavior on Bootstrap-styled elements.

Constraints: HTMX controls may use attributes such as `hx-post`, `hx-swap`, and `hx-target`; no JavaScript framework is required.

### config_key `Financial theme tokens`
Defines optional financial-professional CSS variables in `static/css/style.css`.

| Variable | Default |
|---|---|
| `--sch-nav-bg` | `#33424c` |
| `--sch-nav-text` | `#ffffff` |
| `--sch-util-text` | `#98A4AE` |
| `--sch-accent` | `#009CDB` |
| `--sch-cta` | `#E05A00` |
| `--sch-cta-hover` | `#C04800` |
| `--sch-body-bg` | `#ffffff` |
| `--sch-text` | `#33424c` |

Constraints: Project-specific `UI-GENERAL.md` values override these defaults.

### Rule: financial-font
Loads Raleway from Google Fonts and uses it as the primary body font for the financial theme.

Constraints: Provide Helvetica and Arial fallbacks.

### Rule: financial-navigation
Provides `.sch-logo`, `.navbar-schwab`, and `.navbar-util` classes for financial-themed navigation.

Constraints: Primary navigation uses `--sch-nav-bg`; navigation links use `--sch-nav-text`; utility links use `--sch-util-text`.

### Rule: cta-buttons
Provides `.btn-cta` and overrides `.btn-primary` for financial-themed call-to-action buttons.

Constraints: CTA buttons use `--sch-cta`, hover state uses `--sch-cta-hover`, text is white, buttons have fully rounded pill corners, and primary buttons use font weight `600`.
