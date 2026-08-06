# Edit Stage 2 - Apply edits

PURPOSE: Apply only the approved content deltas while preserving reproducible evidence.

ENTRY: The `edit_spec` gate is resolved and the approved `edit_request.yaml` is unchanged.

EXACT actions:

1. Edit only `bundle/content.md` and its directly corresponding provenance deltas.
2. Treat all existing `sim/` results as immutable unless `edit_request.yaml` explicitly requests a rerun.
3. When a rerun is authorized, use `pipeline_ctl invalidate` from the affected edit stage before changing simulation inputs or results, then record the new evidence.
4. Compare the content delta with the approved request and remove unrelated changes.

EXIT + gate: advance Stage 2 as `done`. No gate.

FAILURE: If a requested edit requires unapproved simulation work or wider scope, block and return to the specification gate.
