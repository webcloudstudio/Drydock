# Drydock Product Announcement Storyboard

## Visual Contract

- Format: 1920x1080 MP4, 24 fps.
- Style: clean 2D technical cartoon, professional free-software launch.
- Palette: white, steel blue, dark navy, bright green, amber command highlights.
- World: one continuous conveyor belt runs the full video. The camera dollies along the
  belt at belt speed, so riding cards hold their screen position while world-fixed
  structures sweep right-to-left past them.
- Card grammar: one paper-card style everywhere (title bar plus rule lines). Imported
  cards carry a check badge; Story cards carry green acceptance-criteria ticks.
- Machines: portal gantries straddle the belt. Each carries its command
  (`drydock import`, `analyze`, `plan`, `build`, `refit`) on a navy sign and a porthole
  gear that spins up, glows, and sparks while a card converts under the shroud. Cards
  enter one side and emerge transformed on the other.
- Closer: the belt ends at a delivery platform. Working Software crates tip off the end
  and stack while the camera eases to a stop under the call to action.
- Audio: female neural voice at natural rate, clean technical pulse beneath it. Video
  length scales to the narration.

## Scenes

Times are in base units; the render scales them to the narration length.

| Time | Visual | Voice |
|---:|---|---|
| 0-5 | Logo and title over the running belt. | Meet Drydock. |
| 5-17 | Specification, Notes, and Project Material cards drop onto the belt and ride into the `drydock import` gantry; Imported cards emerge. | Bring in specifications, notes, or project material. |
| 17-26 | The `drydock analyze` gantry converts the imported cards into Stories, Questions, Blockers, and Acceptance Criteria cards. | Analyze proposes an Agile plan. |
| 26-36 | The `drydock plan` gantry converts the plan cards into Blueprints and Manifest cards. | Specifications become governed Blueprints with TDD tests. |
| 36-46 | A Manifest wall panel pans past: Branding and Stack cards feed Story cards; stories link to each other with dependency arrows. | The Manifest is a graph database relating stories, stack, and branding. |
| 46-54 | A QuarterDeck workbench pans past: six named build blocks (Foundation, Persistence, Search, Reports, User Interface, Documentation) on two shelves, each holding mini Blueprints; a cursor drags two blocks into the correct order. | Shape the build in the QuarterDeck web server: group stories into blocks. |
| 54-61 | An overhead RIGGING bin drops Stack and Branding cards onto the belt; they ride with the Blueprint and Manifest cards. | Applications keep consistent look, behavior, and documentation. |
| 61-70 | All riding cards enter the `drydock build` gantry; a Working Software crate emerges with a Tests Passing chip. | Build verifies stories and produces working software. |
| 70-78 | Change tickets fall onto the belt and ride with the Working Software crate into the `drydock refit` gantry; more Working Software crates emerge. | Working software plus change tickets become more working software. |
| 78-82 | Engineering-truth chips fade in above the still-running line. | Drydock is built on engineering truths. |
| 82-end | The camera stops at the belt end; crates tip off and stack on the platform under the closer: logo, Take it for a sail., WebCloudStudio.com. | Take it for a sail. |

## Music Options

The renderer produces three generated beds in `audio/`:

- `music_option_1_clean_pulse.wav` - restrained technical pulse.
- `music_option_2_bright_ditty.wav` - more energetic product-announcement rhythm.
- `music_option_3_minimal_drive.wav` - steady understated forward motion.

The current preferred cut uses option 1 by default.
