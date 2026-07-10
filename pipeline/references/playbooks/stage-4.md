# Stage 4 — Write to budget → human gate: `draft`

PURPOSE: Write the report to the approved section budgets while preserving
evidence, level, and provenance.

ENTRY: `pipeline_ctl resume` returns Stage 4; Stage 3 is done and
`bundle/layout_plan.json` exists.

EXACT actions:

1. Read `docs/style-rules.md`, the request, evidence pack, design, bundle spec,
   and layout plan.
2. Write `bundle/content.md` to the per-section line budgets. Use declared
   `[[EQ]]`, `[[FIG]]`, and `[[TABLE]]` tags only.
3. Write `bundle/provenance.json`, mapping paragraphs or claims to source ids.
4. Run an independent level-fit and logic review. Correct unsupported claims,
   unexplained terminology, repetitive prose, and budget violations.
5. Run a prose-fidelity check: numbers, source ids, equations, tags, anchors,
   uncertainty, and logical qualifications must remain unchanged.
6. Present the content—not document styling—for the human draft gate.

ROLE BINDINGS: writer = agent.worker/high or orchestrator; level/logic reviewer
= an independent high-reasoning pass. Optional prose tools may assist but are
never required and must pass the fidelity check.

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
| rewrite changed a number, tag, or qualifier | fidelity violation | reject that rewrite and restore the invariant |
