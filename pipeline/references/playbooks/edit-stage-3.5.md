# Edit Stage 3.5 - Verify output - script gate: `edit_verify`

PURPOSE: Verify that the revised output satisfies the format contract.

ENTRY: Edit Stage 3 produced the revised canonical-format artifact.

EXACT actions:

1. Run the registered format checker:

```sh
python pipeline/scripts/pipeline_ctl.py check <WS> edit_verify
```

2. Inspect the checker receipt and proof artifacts.
3. On rejection, repair assembly inputs, invalidate from Stage 3, and rebuild.

EXIT + gate: after a passing receipt, advance Stage 3.5 as `done`.

FAILURE: A missing or rejected format receipt blocks acceptance.
