# Stage 6 — Return and knowledge distillation

PURPOSE: Deliver the canonical file and preserve reusable, non-personal lessons.

ENTRY: `pipeline_ctl resume` returns Stage 6 and Stage 5.7 is complete.

EXACT actions:

1. Confirm `canonical_output`, proof verdict, scorecard, sources, and provenance.
2. Fill `pipeline/references/wiki_entry_template.md` as a local knowledge record
   under `<WS>/archive/knowledge/`.
3. Promote reusable troubleshooting patterns and public sources into that local
   record. Do not copy private report prose or identity data.
4. Report the canonical output path, gate history, and any remaining manual work
   to the operator.
5. Close the workflow:

```sh
python pipeline/scripts/pipeline_ctl.py advance <WS> 6 --status done
```

The automatic organizer regenerates `NEXT_TASK.md`, writes the final handoff,
and preserves safe transient files under `<WS>/archive/stages/`.

ROLE BINDINGS: archive/knowledge = agent.worker/low or the orchestrator.

CORPUS HYGIENE: generated report prose is not evidence for a private person's
style. Only explicitly public or operator-approved reusable facts and process
lessons enter shared documentation.

EXIT + gate: canonical output delivered, knowledge record written, Stage 6 done.

FAILURE table:

| Symptom | Cause | Action |
|---|---|---|
| external knowledge store unavailable | optional service offline | local record is sufficient |
| private text about to enter public knowledge | hygiene violation | keep it in the ignored workspace |
| `canonical_output` null | Stage 5 incomplete | return to Stage 5; do not close |
