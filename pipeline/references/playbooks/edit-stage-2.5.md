# Edit Stage 2.5 - Content audit - script gate: `content_audit`

PURPOSE: Recompute content integrity checks before assembly.

ENTRY: Edit Stage 2 is done and the content/provenance delta matches `edit_request.yaml`.

EXACT actions:

1. Freeze `bundle/content.md` for assembly.
2. Run the registered checker:

```sh
python pipeline/scripts/pipeline_ctl.py check <WS> content_audit
```

3. Correct inputs and rerun after rejection; never edit the verdict.

EXIT + gate: after a passing receipt, advance Stage 2.5 as `done`.

FAILURE: A missing or rejected checker receipt blocks reassembly.
