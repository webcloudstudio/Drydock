# Branding — Papers

**Version:** 20260804 V2
**Category:** Branding
**Description:** The author's voice and structure for the Drydock white paper series — what a paper
is, how it is organized, and how it is written.

Inherits the visual standard from `BRANDING_WHITEPAPERS.md`: page layout, header, copyright,
frontmatter fields, and the mermaid `classDef` block. This file covers the writing.

Reference implementations: `docs/papers/Managing_Changes_in_SDD.md` and
`docs/papers/Improving_Step_Accuracy_in_SDD.md`. When this file and those papers disagree, the
papers win.

---

## What a Paper Is

A paper is a record of an investigation. The author tried things, some failed, and the paper reports
what was learned and what to do instead. It is not documentation, not a product description, and not
an argument for a product.

The reader is an experienced developer who has never used Drydock and never will. They came for the
method. They keep the paper if it gives them something they can apply on Monday.

**A paper is thrown away when the reader cannot decode a sentence.** Every term that is not general
industry vocabulary costs the reader something. Most are not worth it.

---

## The Two Shapes

Every paper takes one of two shapes. Pick one and hold it for the whole paper.

### The notebook

Numbered attempts in the order they were tried. Used when the paper reports an investigation.
Reference: `Managing_Changes_in_SDD.md`.

```markdown
## Concept #1 — Use LLM Transaction Log

I am a database guy, so my first instinct was to simply create a transaction log of changes...

Concept #1 failed on signal-to-noise. A working session contains exploration, dead ends, and
thinking...

> **Lesson:** Mining change tickets out of the LLM is hard, and the specs will diverge from the code.
```

Sections are `## Concept #N — <name>`, then `## Solution #N — <name>` for the parts that worked,
then a final `## Solution` of one or two lines. First person throughout. Failures are reported
plainly, including the author's reasoning at the time.

### The derivation

Numbered sections that build one argument from a stated problem. Used when the paper explains a
method rather than a search. Reference: `Improving_Step_Accuracy_in_SDD.md`.

Sections are `## 1. The <Problem>`, `## 2. Simplification #1: <name>`, ending in `## N. Conclusion`.
Third person. Sections cross-reference as `§3`.

---

## Voice

**Short sentences. One fact each.** Two facts become two sentences.

> Stories are not a list; they are a graph. Features and stories are nodes; dependencies are edges;
> the graph is stored as plain text alongside the specification.

**Common words.** Write the shortest word that is accurate. `Use`, not `utilize`. `Splits`, not
`partitions`. `Frozen`, not `immutable`, unless the paper defines the term and needs it after.

**Concrete nouns.** A sentence names a file, a command, a number, or a thing the reader can picture.
A sentence whose subject is a property ("supersession", "containment", "the approval boundary") is
rewritten until its subject is a thing.

**Numbers beat adjectives.** Cost, size, and benefit claims carry arithmetic or a worked example.

> 30 stories, each prompt 20,000 tokens, half of it shared stack rules and architecture. Built one
> at a time, the shared material is injected 30 times: 600,000 tokens total. Group the stories three
> per step and the shared material is injected 10 times: 400,000 tokens.

**Say what failed.** A rejected approach gets the reason it was rejected, in the same sentence.
"Concept #1 failed on signal-to-noise." Not "was found to be suboptimal."

**One takeaway per section.** In a notebook paper it is a `> **Lesson:**` blockquote. In a
derivation it is a bold claim followed by bullets. Never more than one per section, and never a
paragraph that restates the section.

**No sentence justifies another sentence.** If a fact needs a reason, the reason is a clause in
the same sentence, not a sentence of its own. `Consequence:`, `This ensures`, `That is the entire
mechanism`, `which is what keeps it cheap enough` are signals the sentence should be cut, not
tightened.

**Say it flat at the end.** The last line of an argument is a plain restatement, not a flourish.
"Error stops compounding, context stops confusing, and the build repeats."

---

## Vocabulary

Use words the reader already owns: specification, story, feature, build, test, graph, dependency,
contract, change ticket, blueprint, context, token, rebuild.

**Product-internal names are prohibited** — file paths, artifact filenames, command flags, prompt
filenames, and named roles that exist only inside Drydock. A paper may name a `drydock` command when
the paper is describing that command's method, and may name Drydock once as the reference
implementation with a citation:

> Drydock [1] is the reference implementation of this method.

Any other term must be defined in one sentence at first use, or cut. Prefer cut.

---

## Length and Density

| Element | Rule |
|---|---|
| Whole paper | 150–250 lines of markdown |
| Section | 3–10 lines of prose, plus at most one table, list, or diagram |
| Paragraph | 2–5 sentences |
| Abstract | One paragraph of problem, one of what the paper does, then `**Keywords:**` |
| Diagrams | 2–3 per paper, 4–7 nodes each, per `BRANDING_WHITEPAPERS.md` |
| Conclusion | Bullets, one line each, then one closing sentence |

Tables carry structured facts. Prose never enumerates what a table can hold.

The paper is printed. No element takes a whole page.

---

## Prohibited

- Essay headings. Sections are `Concept #N`, `Solution #N`, or `N. <Noun phrase>`. Never
  "The Rules That Keep It Honest" or "Boundaries That Make It Safe".
- Abstract subjects: "supersession", "the approval boundary", "atomicity", "the invariant".
- Internal file paths, artifact names, JSON block names, and invented vocabulary.
- Naming a mechanism before explaining it.
- Long words chosen for register: utilize, leverage, facilitate, orchestrate, encapsulate as a verb.
- Restating a section in a summary paragraph at its end.
- Marketing register: powerful, seamless, robust, simply, just, easy.
- Instructional scaffolding: "Let's", "Now we", "As you can see", "Note that", "It is important to".
- Product advocacy. The paper reports a method; the reader decides.
- Cleaning up the author's typing. Double spaces, occasional typos, and informal asides are the
  voice. Do not normalize them in an unrelated edit.
- Substituting a project-specific term for a more generic one because it reads better. A word that
  looks like it might be a defined artifact name (`manifest`, `blueprint`, a command name) is
  verified against the codebase before it is changed, never swapped on style instinct.
- An invented section title standing in for the argument itself — "Three Places the Ticket Model
  Stops" is an essay heading wearing a number. See Prohibited, above.

---

## Editing Protocol

The author writes the paper. An agent drafts structure, diagrams, tables, and mechanical
corrections.

**An agent must read this file in full before making any edit to a paper.** Rules here are not
recovered from context; they are checked against, every time.

**An agent may, without asking:** fix a broken mermaid block, correct a factual detail about a
command, add a table the author asked for, and render the HTML and PDF.

**An agent must obtain approval for** any new section, any rewritten paragraph, and any change of
shape. Approval for one section is not approval for the next.

**An agent must never** replace author-written prose with its own draft of the same content, reflow
paragraphs it was not asked to touch, add sections the author did not request, or rewrite the whole
file to make a change that touches one line. Edit the specific line or paragraph named. When a
draft is rejected, rewrite one section and stop, rather than delivering another full draft.

**A correction is not scoped to where it was given.** If the author cuts a justification sentence
in one section, that pattern is cut everywhere in the document and in every document after it —
not regenerated the next time a different section is touched.

**The document was iterated before the agent arrived.** Every rewrite the agent makes is a
high-risk action on judgment the agent cannot see. Default to the smallest edit that satisfies the
request; ask before doing more.
