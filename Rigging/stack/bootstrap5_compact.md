<!-- Compacted from Rigging/stack/bootstrap5.md sha256=abb44dff6e8fdbad19828931b946e8ee12521a2c42a6ec8df7df5772ac932c88 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Bootstrap 5 Interface — Contract Surface

### Rule: asset-selection

Use Bootstrap 5 when selected by the Target.

Constraints: Pin the asset version, load each required CSS or JavaScript asset once, and use either local assets or a CDN according to the Blueprint.

### Rule: target-theme-contracts

Follow the Target’s `UI-GENERAL.md` and branding contracts for colors, typography, theme mode, navigation, and component behavior.

Constraints: Do not introduce a default product theme or environment key.

### Rule: responsive-interface

Use Bootstrap’s responsive grid, spacing utilities, and components where appropriate.

Constraints: Keep application overrides in one project stylesheet and avoid duplicating framework styles.

### Rule: accessibility

Use semantic HTML, visible labels, keyboard access, focus states, and responsive navigation.

Constraints: Use JavaScript only for behavior required by the selected components.

### Rule: htmx-integration

When HTMX is selected separately, Bootstrap owns presentation and HTMX owns request behavior.

Constraints: Dynamic content must preserve Bootstrap component initialization and accessible focus behavior.
