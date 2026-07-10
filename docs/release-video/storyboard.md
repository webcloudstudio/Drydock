# Drydock Product Announcement Storyboard

## Visual Contract

- Format: 1920x1080 MP4, 24 fps.
- Style: clean 2D technical cartoon, professional free-software launch.
- Palette: white, steel blue, dark navy, bright green, amber command highlights.
- World: one continuous conveyor belt runs the full video. The camera dollies along the
  belt at belt speed, so riding cards hold their screen position while world-fixed
  structures sweep right-to-left past them.
- Card grammar: one paper-card style everywhere (title bar plus rule lines). Imported
  cards carry a check badge; Story cards carry green acceptance-criteria ticks; the
  Blueprints card lists its sections (Behavior, Acceptance, Guardrails).
- Machines: portal gantries straddle the belt. Each carries its command
  (`drydock import`, `analyze`, `plan`, `build`, `refit`) on a navy sign and a porthole
  gear that spins up, glows, and sparks while a card converts under the shroud. Outputs
  emerge at the same belt positions their inputs entered, so conversion is continuous —
  no dead time inside a machine.
- Closer: the belt ends at a delivery platform. Working Software crates tip off the end
  and stack while the camera eases to a stop under the call to action.
- Audio: female neural voice; each sentence is synthesized separately and joined with
  fixed silences (SENTENCE_GAP / PARAGRAPH_GAP in the renderer; `[pause N]` lines in
  the script override a paragraph gap). Video length scales to the narration.

## Scenes

Times are in base units; the render scales them to the narration length.

| Time | Visual | Voice |
|---:|---|---|
| 0-5 | Logo and title over the running belt. | Meet Drydock. |
| 5-17 | "Import your Project": Specification, Notes, and Material cards drop onto the belt and ride into the `drydock import` gantry; Imported cards emerge in place. | Drydock import brings in specifications, notes, and other material. |
| 17-26 | "Analyze is Agile Planning": the `drydock analyze` gantry converts the imported cards into Stories, Questions, Blockers, and Acceptance Criteria cards. | Drydock analyze proposes an Agile plan. |
| 26-36 | The `drydock plan` gantry converts the plan cards into a Blueprints card (with section text) and a Manifest card. | Drydock plan converts your specifications into governed Blueprints. |
| 36-46 | The Manifest wall panel pans past (no headline): Block 1 (Story 1) and Block 2 (Stories 2 and 3), story dependency arrows across blocks, Stack (Database, Web, Technology) and Rigging (Branding, Rules) on the left with light arrows feeding every block. | The Manifest is a graph database relating stories, stack, and branding. |
| 46-56 | The QuarterDeck workbench pans past (no headline): six named build blocks holding mini Blueprints with section text; a cursor drags two blocks into build order. | Shape the build in the QuarterDeck web server. |
| 56-70 | The Blueprints and Manifest cards ride into the `drydock build` gantry; a Working Software crate emerges with a Tests Passing chip. | Drydock build walks the graph and produces working software. |
| 70-78 | Change tickets drop in behind the Working Software crate; all ride into `drydock refit`; more Working Software crates emerge. | Working software plus change tickets become more working software. |
| 78-82 | Engineering-truth chips fade in above the still-running line. | Drydock is built on engineering truths. |
| 82-end | The camera stops at the belt end; crates tip off and stack on the platform under the closer: logo, Take it for a sail., WebCloudStudio.com. | Take it for a sail. |

## Music Options

The renderer produces three generated beds in `audio/`:

- `music_option_1_clean_pulse.wav` - restrained technical pulse.
- `music_option_2_bright_ditty.wav` - more energetic product-announcement rhythm.
- `music_option_3_minimal_drive.wav` - steady understated forward motion.

The current preferred cut uses option 1 by default.
