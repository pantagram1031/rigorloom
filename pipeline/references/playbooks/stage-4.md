# Stage 4 — Write to budget → human gate: `draft`

PURPOSE: Write the report to the approved section budgets while preserving
evidence, level, and provenance.

ENTRY: `pipeline_ctl resume` returns Stage 4; Stage 3 is done and
`bundle/layout_plan.json` exists. If present, read the resolved local
`.pipeline/personalization.lock.json`; apply only its resolved rules and never
use generated report prose as style evidence.

EXACT actions:

1. Read `docs/style-rules.md`, the request, evidence pack, design, bundle spec,
   and layout plan.
2. Write `bundle/content.md` to the per-section line budgets. Use declared
   `[[EQ]]`, `[[FIG]]`, and `[[TABLE]]` tags only.
3. Write `bundle/provenance.json`, mapping paragraphs or claims to source ids.
4. Run an independent level-fit and logic review. Correct unsupported claims,
   unexplained terminology and budget violations.
5. Follow `humanization_contract.md` in its fixed order:
   - run `humanization_ctl.py prepare <WS>`;
   - spawn an independent local prose-pattern reviewer and save
     `bundle/ai_tell_review.json`; scores are advisory and never select targets;
   - PASS means an empty v2 proposal with `gate.skipped=true`;
   - REWORK means spawn a separate local `humanizer-rewriter`, give it every
     prose paragraph, and request paragraph-level changes only;
   - run an independent fidelity/naturalness review, then save the annotated
     proposal under `work/stage-4/scratch/`;
   - run `humanization_ctl.py apply <WS> --changes <changes.json>`.
6. Require `bundle/prose_fidelity.json` to pass. The controller keeps safe
   edits, restores unsafe paragraphs, and returns `retry_paragraph_ids`. Retry
   only those ids with a fresh worker, for at most three rounds. Never repair
   facts to make a style proposal pass.
7. Present the accepted content and humanization reports—not document styling—
   for the human draft gate.

ROLE BINDINGS: writer = agent.worker/high or orchestrator; level/logic reviewer
= an independent high-reasoning pass; reviewer-ai-tell = a local high-reasoning
worker; humanizer-rewriter = a different local high-reasoning worker;
reviewer-fidelity/reviewer-naturalness = workers independent from the rewriter.
Pantadex is an optional adapter or comparison judge. Optional services are never
required and cannot bypass local fidelity.

EXIT + gate:

```sh
python pipeline/scripts/pipeline_ctl.py gate <WS> draft --mode <mode>
python pipeline/scripts/pipeline_ctl.py advance <WS> 4 --status done
```

FAILURE table:

| Symptom | Cause | Action |
|---|---|---|
| body contains raw URLs or footnote clutter | clean-body violation | move source details to provenance |
| level is too high | missing level-fit review | explain functional meaning or remove the concept |
| prose tool unavailable | optional adapter missing | continue with an independent manual/agent review |
| rewrite changed a number, tag, or qualifier | fidelity violation | controller rolls back; correct the change proposal |
| stale paragraph text | draft changed after prepare | rerun prepare and review against the new baseline |
| scorer marks formal prose REWORK | register false positive | treat score as advisory; use independent review |
| retry ids remain after round 3 | no safe convergence | keep protected originals and hold/report |
