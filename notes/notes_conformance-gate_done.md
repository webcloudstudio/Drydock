# DONE: conformance-gate

### The block is the test unit; failures report a Block → Story → AC chain
`2026-07-23` · `spec:applied` · `impl:implemented`

Multiple stories build together in one step (the block). After the block builds, the block's
entire AC set runs once. Because every AC maps to its story, a failure is attributed per story
and reported as a chain: **"Block failed → Story X failed → AC abc failed"**, naming the story,
its stated intent, and the concrete assertion (e.g. "must add two numbers, but a+b≠c"). No
per-story execution; per-story attribution.
