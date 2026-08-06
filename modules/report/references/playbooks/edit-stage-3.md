# Edit Stage 3 - Reassemble

PURPOSE: Rebuild the requested output from the audited content without modifying the preserved baseline.

ENTRY: The `content_audit` script gate passed.

EXACT actions:

1. Run the backend declared in `build.yaml` against the audited bundle.
2. Write the revised artifact under `output/`; never assemble over `<WS>/archive/edit/before/`.
3. Preserve assembly logs and proof artifacts in their declared workspace paths.

EXIT + gate: advance Stage 3 as `done`. No gate.

FAILURE: Backend or assembly failure blocks the stage; repair declared inputs and rebuild.
