# Drydock Product Announcement Storyboard

## Visual Contract

- Format: 1920x1080 MP4, 24 fps.
- Style: clean 2D technical cartoon, professional free-software launch.
- Palette: white, steel blue, dark navy, bright green, amber command highlights.
- World: one continuous conveyor belt runs the full video. The camera dollies along the
  belt at belt speed, so riding cards hold their screen position while world-fixed
  structures sweep right-to-left past them.
- Timing: voice synthesis records the moment each command is spoken to
  `audio/narration_marks.json`; the renderer anchors every machine, headline, and wall
  panel to those marks. A machine reaches its center and converts its lead card as the
  command is named, so its outputs stream out while the narrator describes them, and the
  previous machine is still leaving frame as the next one enters — the machines overlap
  on screen rather than leaving dead belt between them.
- Card grammar: one paper-card style everywhere (title bar plus rule lines). Imported
  cards carry a check badge; Story cards carry green acceptance-criteria ticks; the
  Blueprints card lists its sections (Behavior, Acceptance, Guardrails).
- Machines: slim gates straddle the belt — two thin posts, a header beam carrying the
  command (`drydock import`, `analyze`, `plan`, `build`, `refit`, `build`) on a navy sign, a small
  scanner gear that spins up and glows, and a translucent light curtain between the posts.
  A card converts as it crosses the curtain, and the curtain flares white at that instant,
  so the conversion is covered by light rather than by a solid shroud. Outputs emerge at
  the same belt positions their inputs entered, so conversion is continuous — no dead time
  inside a machine.
- Closer: the belt ends at a delivery platform. Working Software crates tip off the end
  and stack while the camera eases to a stop under the call to action.
- Audio: female neural voice; each sentence is synthesized separately and joined with
  fixed silences (SENTENCE_GAP / PARAGRAPH_GAP in the renderer). A `(pause)` cue in the
  script adds 0.35 s wherever it appears; a `[pause N]` line sets an exact gap. Video
  length scales to the narration.

## Scenes

Machine, headline, and panel timing is anchored to the narration marks, not to fixed
times; the columns below describe the beats in order.

| Beat | Visual | Voice cue |
|---|---|---|
| Intro | Logo and title over the running belt. | Meet Drydock. |
| `import` | "Import your Project": Specification, Notes, and Material cards drop onto the belt and ride into the `drydock import` gantry; Imported cards emerge in place. | Drydock import brings in specifications, notes, and other material. |
| `analyze` | "Analyze is Agile Planning": the `drydock analyze` gantry converts the imported cards into Stories, Questions, Blockers, and Acceptance Criteria cards. | Drydock analyze proposes an Agile plan. |
| `plan` | The `drydock plan` gantry converts the plan cards into a Blueprints card (with section text) and a Manifest card. | Drydock plan converts your specifications into governed Blueprints. |
| Manifest | The Manifest wall panel pans past (no headline): Block 1 (Story 1) and Block 2 (Stories 2 and 3), story dependency arrows across blocks, Stack (Database, Web, Technology) and Rigging (Branding, Rules) on the left with light arrows feeding every block. | The Manifest is a graph database relating stories, stack, and branding. |
| QuarterDeck | The QuarterDeck workbench pans past (no headline): six named build blocks (Foundation, Persistence, Feature 1, Feature 2, User Interface, Documentation), each holding mini Blueprints with section text. Feature 1 and Feature 2 start nudged out beside their slots and the cursor slides each into build order. | Shape the build in the QuarterDeck web server. |
| `build` | The Blueprints and Manifest cards ride into the `drydock build` gantry; a Working Software crate emerges with a Tests Passing chip. | Drydock build walks the graph and produces working software. |
| `refit` | Change tickets drop in behind the Working Software crate; all ride into the `drydock refit` gate, which emits a conformed Blueprint and Manifest — the same pair `drydock plan` emits. | Change tickets are conformed with drydock refit. |
| `deliver` | The refit Blueprint and Manifest ride into a second `drydock build` gate; one Working Software crate emerges with its Tests Passing chip, exactly as the first build produced. | ...and delivered with drydock build. |
| Decompose | "Drydock decomposes big problems" (with the line "Big work splits into small, verifiable stories") holds over the Working Software crate running to the end of the line. | engineers decompose big problems. |
| Truths | "Built on engineering truths": the four engineering-truth chips fade in above the still-running line and hold until the closer banner rises. | Drydock is built on engineering truths. |
| Closer | The camera stops at the belt end; crates tip off and stack on the platform under the closer: logo, Take it for a sail., WebCloudStudio.com. | Take it for a sail. |

## Music Options

The renderer produces three generated beds in `audio/`:

- `music_option_1_clean_pulse.wav` - restrained technical pulse.
- `music_option_2_bright_ditty.wav` - more energetic product-announcement rhythm.
- `music_option_3_minimal_drive.wav` - steady understated forward motion.

The current preferred cut uses option 1 by default.
