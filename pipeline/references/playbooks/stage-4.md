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
   - run the AI-tell prompt and save `bundle/ai_tell_review.json`;
   - ask the selected humanizer for paragraph-level changes only;
   - save changes under `work/stage-4/scratch/` and run
     `humanization_ctl.py apply <WS> --changes <changes.json>`.
6. Require `bundle/prose_fidelity.json` to pass. A failed apply automatically
   restores `bundle/content.raw.md`; repair the proposal, never the report facts.
7. Present the accepted content and humanization reports—not document styling—
   for the human draft gate.

ROLE BINDINGS: writer = agent.worker/high or orchestrator; level/logic reviewer
= an independent high-reasoning pass. humanizer-chain = optional Pantadex MCP,
another high-reasoning worker, or the interactive agent, all using the same JSON
contract. Optional services are never required and cannot bypass local fidelity.

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
