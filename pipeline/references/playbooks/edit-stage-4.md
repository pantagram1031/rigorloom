# Edit Stage 4 - Accept - human gate: `edit_accept`

PURPOSE: Obtain operator acceptance of the verified revision against the frozen edit specification.

ENTRY: The `edit_verify` script gate passed and before/after artifacts are available.

EXACT actions:

1. Present the revised output with a concise requested-change checklist and before/after evidence.
2. Record remaining limitations or manual steps without hiding them.
3. Resolve the `edit_accept` human gate; never substitute an agent review for supervised approval.

EXIT + gate:

```sh
python pipeline/scripts/pipeline_ctl.py gate <WS> edit_accept --mode <mode>
python pipeline/scripts/pipeline_ctl.py advance <WS> 4 --status done
```

FAILURE: Rejection returns to the earliest affected edit stage through `pipeline_ctl invalidate`.
