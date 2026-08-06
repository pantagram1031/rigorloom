# Report pipeline — module reference (skill fragment companion)

## Workspace anatomy

```
workspaces/report-<slug>/
  PIPELINE.md            # YAML header = the state machine (stages, gates, statuses)
  APPROVALS.md           # human-gate ledger (pipeline_ctl gate reads this)
  request.yaml build.yaml
  bundle/content.md      # assembly source (bundle_spec contract: SECTION anchors,
                         #   [[EQ]]/[[FIG]]/[[TABLE]] tags, YAML meta)
  bundle/figures/        # the ONLY figure directory assembly scans (T20)
  .pipeline/             # artifacts.json, handoff.json, personalization.lock.json
```

## CLI contracts

| command | contract |
|---|---|
| `pipeline_ctl resume WS` | computes the resume point per CONTRACT §2; the only sanctioned "where was I" |
| `pipeline_ctl check WS STAGE` | script gate: runs the stages.yaml-bound checker, exit 0 → auto_approved; verdict + provenance recorded, never editable |
| `pipeline_ctl gate WS STAGE` | human gate: resolves from APPROVALS.md only — no approval text, no pass |
| `pipeline_ctl advance / invalidate / reopen / amend-close` | legal-transition enforcement; invalidate resets the stage and everything after |
| `compose.py` | resolves typed stage-contract modules into the stage graph; retains every registered gate stage inside the selected span (entering Stage 5 retains the full post-assembly floor 5.3/5.5/5.7/6) |
| `workflow-lint` | stage-graph lint; run after editing stages.yaml |
| `source-fetch` / `claims-ledger` / `organize-workspace` | research provenance + workspace hygiene CLIs (module `cli` contributions) |

## Assembly handoff (report → engine)

`build_report.py --content bundle/content.md --form FORM` emits ops JSON for
`com_backend edit` (or `xml_backend` offline). It refuses on any SECTION
anchor mismatch with the form — fix `content.md`; bypassing the check is a
defect. After assembly, the post-assembly floor applies: layout gate
(check_layout), residue gate (check_residue), format proofs
(charpr_check/style_diff), then content gates (content_audit and friends).

## Rules that bind the model (not the code)

- Prose is written by the writer stages, never by gate scripts; fill_report
  emits ordered `needs`, not text.
- A deterministic gate verdict is immutable once emitted; re-run the gate
  after fixing the input instead of arguing with the JSON.
- Night mode assumes zero human presence: any HUMAN gate in the span is a
  configuration error caught by workflow-lint, not a thing to auto-approve.
