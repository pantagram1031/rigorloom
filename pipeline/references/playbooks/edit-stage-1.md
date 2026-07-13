# Edit Stage 1 - Edit specification - human gate: `edit_spec`

PURPOSE: Freeze the authorized edit scope before changing report content.

ENTRY: Edit Stage 0 is done and `edit_request.yaml` names the preserved baseline and requested deltas.

EXACT actions:

1. Review every requested delta, protected region, output format, and rerun instruction.
2. Resolve ambiguity in `edit_request.yaml`; do not broaden the request.
3. Present the frozen specification for the `edit_spec` human gate.

EXIT + gate:

```sh
python pipeline/scripts/pipeline_ctl.py gate <WS> edit_spec --mode <mode>
python pipeline/scripts/pipeline_ctl.py advance <WS> 1 --status done
```

FAILURE: A rejected or ambiguous specification stops the edit.
