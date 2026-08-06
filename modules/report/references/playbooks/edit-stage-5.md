# Edit Stage 5 - Deliver

PURPOSE: Deliver the accepted revision with an auditable record of what changed.

ENTRY: The `edit_accept` gate is resolved and the accepted canonical output is fixed.

EXACT actions:

1. Generate a before/after diff appropriate to the artifact type and archive it under `<WS>/archive/edit/diff/`.
2. Preserve the original, accepted revision, edit request, gate receipts, and diff together in the edit archive.
3. Run `workflow_lint.py <WS> --json`; stop and reconcile every HARD finding.
4. Report the accepted output path and archived diff, then advance Stage 5 as `done`.

EXIT + gate: accepted revision delivered and before/after diff archived. No gate.

FAILURE: Missing baseline, diff, receipt, or canonical output blocks delivery.
