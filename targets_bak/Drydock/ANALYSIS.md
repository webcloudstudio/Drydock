# Blueprint Analysis: Drydock
generated: 2026-06-14
blueprint: /mnt/c/Users/barlo/projects/Drydock/targets/Drydock/blueprint

## Analysis Summary

Quality: Blocked
  blockers: 3
  questions: 3
  stories: 0
  stack: not declared
  screens: 0

## Open Questions

- [DATABASE.md] Does Drydock persist data? The file is the unedited template (`table_name`, `SECRET_KEY` only); persistence model is undefined.
- [deployment] No deployment target is stated anywhere in the Blueprint. Where does Drydock run (self-hosted Docker, static host, CLI)?
- [auth] No auth model is named. Are there user accounts or protected resources, or is the Publisher output fully public?

## Story List

Cannot derive a story list. Every Blueprint file is the unmodified template/example:

| File | State | Evidence |
|---|---|---|
| ARCHITECTURE.md | Empty template | Modules table blank; Routes table = `GET /` placeholder; Directory Layout = `Drydock/` only |
| DATABASE.md | Empty template | `table_name` placeholder; example `SECRET_KEY` config; no real stores |
| FEATURE-Example.md | Example stub | Header says "Delete this template after creating real feature files" |
| SCREEN-Example.md | Example stub | Route `GET /example`; "Delete this template after creating real screen files" |
| UI-Component-Example.md | Example stub | Empty Structure/Variants/Behavior |
| UI.md | Empty template | Theme/Navigation/Shared Components blank |
| HOMEPAGE.md | Empty template | Branding partially filled (`Drydock`) but Contact/Bio blank |

No populated modules, routes, tables, features, screens, or acceptance criteria exist. There is nothing to decompose into atomic stories. 0 stories.

### Tuning Options

Once the Blueprint is populated, decomposition can proceed by:
- **By screen/feature** (recommended for web): one story per SCREEN-*.md and FEATURE-*.md scope, plus shared UI stories.
- **By layer**: persistence stories, then route/handler stories, then template/UI stories.
- **By capability vertical**: group Publisher (homepage + static-site generation) as one slice, each subsequent feature as its own slice.

## Blockers

- **Blueprint is uninitialized.** All seven spec files contain only template/example content. The team cannot determine what Drydock does, what it builds, or what "done" means. Human must populate the specs (or answer spike-intent) before decomposition.
- **No product goal / COMPASS.** No COMPASS.md exists and no feature file describes what the product does or who it serves. The only product signal is the Publisher reference in HOMEPAGE.md (`bin/build_documentation.sh` / `publisher.py`).
- **Stack not declared.** No METADATA.md is present in the Blueprint; `stack:` is unknown. Framework, database, and frontend must be chosen (see spike-stack).

## Notes

- Project type signals are mixed but lean **web**: SCREEN-*.md present, an HTTP route in ARCHITECTURE (`GET /`), UI.md, and a HOMEPAGE.md/Publisher. All are template-stage, so the classification is provisional.
- HOMEPAGE.md is the only file with any real value entered (Branding `logo/name/copyright = Drydock`).
- All `## Acceptance Criteria` sections read `- None.`, so SOUNDINGS.md has no rows to populate.
