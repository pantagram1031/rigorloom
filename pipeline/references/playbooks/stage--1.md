# Stage -1 — Setup / Studio boot

PURPOSE: Create a complete job ticket and register a workspace before report
work begins.

ENTRY: A topic and form are available. Any interactive agent or human may
orchestrate; headless tools are bounded workers rather than the state owner.

EXACT commands:

```sh
# Run from <REPO_ROOT>.
python scripts/new_report.py --slug <slug> --subject <subject> \
  --topic "<topic>" --form <ABSOLUTE_FORM_PATH> \
  --mode <supervised|autonomous|night>

# Optional read-only viewer on http://127.0.0.1:8000
python studio/main.py
```

ROLE BINDINGS: orchestrator = current interactive session. No worker required.

EXIT + gate: `request.yaml`, `build.yaml`, and kernel-generated `PIPELINE.md`
exist. No human gate. The scaffolder generates `NEXT_TASK.md`; follow it or run:

```sh
python pipeline/scripts/pipeline_ctl.py resume <WS>
```

FAILURE table:

| Symptom | Cause | Action |
|---|---|---|
| Studio will not start | port/dependency issue | Studio is optional; continue and log it |
| init refuses | workspace already exists | use `resume`; do not overwrite |
| required field missing in supervised mode | operator input needed | ask only for the missing required value |
| required field missing unattended | no operator available | choose a conservative default and record the assumption |
