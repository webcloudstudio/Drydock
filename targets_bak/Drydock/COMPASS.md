# COMPASS: Drydock

## Compass
Drydock appears to be a web application that publishes a portfolio of project documentation as a static site. The only concrete product evidence in the Blueprint is the Publisher — `bin/build_documentation.sh` / `publisher.py` — which renders a homepage (branding, contact, bio) and a grid of project cards. Beyond that, the Blueprint contains only unpopulated templates: modules, routes, data model, features, and screens are not yet specified. The full product intent must be confirmed via spike-intent before this Compass can be finalized. A developer joining today should treat the product definition as open and start by answering the four fixed spikes.

## Constraints
- Implied Python web stack (Rigging catalog is Python-centric; `publisher.py` indicates Python), but no stack is declared in the Blueprint.
- Static-site output is implied by the Publisher reference.
- No explicit technical, regulatory, scale, or operating constraints are stated in the spec.

## Success Criteria
- Cannot be derived from the spec; all `## Acceptance Criteria` sections read `- None.`.
- Pending spike-intent: define the primary goal, primary user, and a measurable success definition.
- Minimum viable signal (inferred from HOMEPAGE.md): the Publisher generates a static portfolio site with a branded homepage and one or more project cards.
