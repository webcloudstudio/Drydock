# DISCLOSURE.md — Safety rules for what may be published

These rules override the generation guidance. When in doubt about an item on the
"never publish" list, leave it out.

`scripts/check_disclosure.py` enforces the machine-checkable subset of these rules
on every draft before publication. It is a backstop, not a substitute for judgement.

---

## Always safe to publish — and expected

Drydock is Ed's own public project, published to demonstrate his work. Its product
vocabulary is not a secret; the log is worthless without it.

- The project name **Drydock** and its methodology terms: Blueprint, Typed
  Specification, QuarterDeck, Ship's Log, Rigging, Sea Trials, Soundings,
  Build Compass.
- Public command names: `drydock build`, `drydock refit`, `drydock plan create`,
  `drydock rigging compact`, `drydock build verify`, and the rest of the
  `drydock <verb>` surface, including user-facing flags such as `--step`.
- Decisions, rationale, and rejected alternatives as recorded in the Ship's Log.
- Dates of the recorded work.

## Never publish

- Source file paths, module names, function or class names, or directory layout
  of the implementation.
- Internal API shapes: signatures, parameter names, schemas, environment
  variables, private config keys.
- Credentials, tokens, keys, hostnames, internal URLs, IP addresses, or emails.
- Customer, partner, or third-party names tied to private arrangements.
- Client or employer project names that are not Ed's own public work.

## The test

Before publishing, ask: *"Does this line describe what Drydock does, or how the
private implementation source is laid out?"* Product behavior and command surface
are publishable; implementation source internals are not.

---

## Machine-checked patterns

`check_disclosure.py` blocks a draft that matches any built-in secret pattern
(API keys, AWS keys, private SSH keys, emails, IPv4, absolute filesystem paths,
`.py`/`.ts`/`.rs` filenames, `snake_case(` call shapes) and any extra regex listed
below. Add banned terms — internal names that must never appear — between the
markers, one Python regex per line.

```banned-regex
BLUEPRINT_DIRECTORY
blueprint_directory
RulesEngine
```

Note: terms on this list are internal code identifiers, not product vocabulary.
Product names such as Rigging or QuarterDeck are public and allowed.
