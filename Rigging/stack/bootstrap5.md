# Bootstrap 5 Interface

**Type:** guidance
**Version:** 20260922 V2
**Tier:** interface
**Category:** Frontend
**Description:** Bootstrap 5 asset, theme, and responsive interface boundaries

Prerequisite: `stack/common.md`

## Rules

- Use Bootstrap 5 when selected by the Target. Pin the asset version and load each required CSS or
  JavaScript asset once. The Blueprint chooses local assets or a CDN; do not assume either.
- Follow the Target's `UI-GENERAL.md` and branding contracts for colors, typography, theme mode,
  navigation, and component behavior. Do not introduce a default product theme or environment key.
- Use Bootstrap's responsive grid, spacing utilities, and components where they fit the screen.
  Keep application overrides in one project stylesheet and avoid duplicating framework styles.
- Keep semantic HTML, visible labels, keyboard access, focus states, and responsive navigation.
  Use JavaScript only for behavior the selected components require.
- When HTMX is selected separately, Bootstrap owns presentation and HTMX owns request behavior.
  Dynamic content must preserve Bootstrap component initialization and accessible focus behavior.
