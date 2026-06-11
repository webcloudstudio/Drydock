# Initial Drydock QuarterDeck Review

## Increment

This first cut replaces the copied sample fixture with a Drydock-specific development cockpit.

It provides:

- a concise current-state view;
- a simple capability plan with acceptance criteria;
- structured product-owner questions;
- QuarterDeck sign-off controls;
- a Ship's Log JSONL view that states the real implementation gap;
- direct access to Soundings, Sea Trials, and the authoritative Drydock specification.

## Test Procedure

1. Inspect every sidebar item and confirm the navigation is useful.
2. Open **Drydock Delivery Plan**, inspect tickets, and exercise acceptance checks.
3. Save answers in **Choose Next Slice**.
4. Record a decision below with specific feedback.
5. Restart QuarterDeck and confirm the saved answers and decisions persist.

## Review Decision

Approve this information architecture as the baseline, request revisions to it, or reject it with
the reason. This decision currently persists in QuarterDeck's SQLite state; automated write-back
to Drydock's future decision writer is explicitly a later plan item.
