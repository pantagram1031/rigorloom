# Edit Stage 0 - Intake

PURPOSE: Preserve the delivered report and turn the operator's requested changes into a bounded edit contract.

ENTRY: `pipeline_ctl resume` returns Edit Stage 0 and the existing canonical output is available.

EXACT actions:

1. Copy the existing canonical output without modifying it into `<WS>/archive/edit/before/`, preserving its filename and metadata where possible.
2. Record the source path, preserved-copy path, requested changes, protected content, and any requested simulation rerun in `<WS>/edit_request.yaml`.
3. Confirm the preserved copy opens and the request identifies every intended change.

EXIT + gate: advance Stage 0 as `done`. No gate.

FAILURE: If the source output or change request is missing, block the stage; never infer edits or overwrite the source.
