--
Items in the paper that are not in notes_refit.md

Seven positions. Yours to place.

1. Cutover to blueprints. When the application is stable the blueprints become the source of truth and analyze and plan are never run again. The notes assert the opposite throughout: "the ticket chain is therefore a disposable convenience layer", "the reset is always available and cheap", and the guardrail "No design decision may exist only in a Blueprint or a refit ticket." Cutover ends that guardrail. The notes need a decision entry and the guardrail needs a scope qualifier — it holds until cutover, not forever.

2. The stop condition is a moved contract, not a changed foundation file. The notes fail hard on any changed Compass-owned source: "A Compass-owned source file that has changed causes import --update to fail with an actionable error naming the files and stating that a replan is required. This is a deterministic check with no LLM involvement." The paper says a foundation edit that moves no contract is an ordinary refit. That is a behavior change to import --update, not a wording change, and it reintroduces a judgment the notes deliberately made deterministic. Unresolved: what decides whether a contract moved.

3. Deletion is transitive. The notes stop at the owning blueprint: "A detected deletion is a blocking decision presented to the Commander: keep the feature, or remove it. The choice is recorded in the resulting refit ticket." The paper walks the graph and appends one removal ticket per dependent. This also breaks the notes' rule "One refit --sources run creates at most one ticket per affected Blueprint" — no, it does not break that one, but it does contradict "Nothing is invalidated under the ticket model" in the superseded-decisions section, since transitive removal is downstream propagation. It differs from the rejected V1 design in that the edges come from the graph rather than from a model, which is worth stating explicitly in the notes so the distinction survives.

4. Deletion is manually gated. Approval is required before the removal story is built, scoped to a service or route that has users and is not re-created elsewhere in the same specification. The notes have no approval gate anywhere — their guardrail is "Never make source refit require an additional approval gate before build." This gate is at build, not refit, so the guardrail survives, but the condition and the gate are both new.

5. Post-cutover change tickets. Written by a person, naming one blueprint, joining that chain, same node class and inherited edges. The notes explicitly exclude this: "Eliminating external Jira or other-system change tickets, which remain a separate free-form workflow and are not graph-inheriting." The paper makes them graph-inheriting. Directly contradicts a "Not in scope yet" line.

6. The ticket carries its tests, and the user can override a failure. Nothing in the notes covers what happens to tests that assert the old contract. The override is new and is a policy decision, not a detail — it says a red suite after a refit does not block.

7. The copy must be its own repository, verified. The notes have the mechanism ("drydock init creates the Target repository … but only after verifying that the workspace repository ignores targets/") but frame it as initialization hygiene. The paper makes it a precondition for change detection working at all.

Also worth a line: the notes' "Open Questions" section is empty. Two are now open — whether cutover is reversible, and what decides that a contract moved.

---------- NEXT STEPS ----------
- Trim §1.6 and §2.7 if you want the paper inside 250 lines.
- Resolve: is cutover reversible, and what decides a contract moved.

----------- REQUEST COMPLETED -----------
