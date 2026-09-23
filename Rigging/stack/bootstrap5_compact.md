<!-- Compacted from Rigging/stack/bootstrap5.md sha256=d8d79a9b0aac99209af08eb3df199f78cef3bda62cb0a35ab7344d36c3e1c342 on 2026-09-22 by Rigging maintenance — regenerate with: drydock rigging compact --include-file Rigging/stack/bootstrap5.md -->

# Bootstrap 5 — Consumer Rules

- Pin and load selected Bootstrap 5 assets once; the Blueprint chooses local or CDN delivery.
- Follow `UI-GENERAL.md` and branding for theme, colors, typography, navigation, and components.
  Do not invent product colors, fonts, or environment keys.
- Use responsive grid and components where appropriate; keep overrides in one project stylesheet.
- Preserve semantic HTML, labels, keyboard access, focus, and responsive navigation.
- If HTMX is selected, it owns requests while Bootstrap owns presentation; dynamic content
  preserves component initialization and accessible focus.
