The report distribution module is enabled: the staged report pipeline
(compose → resume → gates) is available. Heavy flows (night runs, full
assembly) are operator-triggered CLIs — never auto-start them.

**Pipeline entry** (one workspace per report; state lives in the
workspace's `PIPELINE.md` YAML header, machine-readable, resumable):

```
python scripts/new_report.py --slug S --subject SUBJ --topic T --form FORM.hwpx \
    [--mode supervised|autonomous|night] [--profile-root DIR]   # scaffold
python modules/report/scripts/pipeline_ctl.py resume WORKSPACE   # THE entry point after any break
python modules/report/scripts/compose.py ...                     # stage-contract resolution (v0.12 vocabulary)
```

`pipeline_ctl` subcommands print exactly one JSON object; exit 0 ok /
1 refusal / 2 usage. Always `resume` first — it computes the resume point
from recorded state; do not re-derive it by reading stage files.

**Gates are code, not prose**:

- SCRIPT gates: `pipeline_ctl check WS STAGE` runs the bound checker from
  stages.yaml — exit 0 → auto_approved, nonzero → rejected, provenance
  recorded. Verdicts are never post-edited.
- HUMAN gates: `pipeline_ctl gate` reads APPROVALS.md and **never fabricates
  approval** — a pending human gate stops the run. Deterministic
  (numeric-verification) gates emit their verdict from code; editing one
  after the fact is a contract violation.
- Run modes (probe `modules.run_modes`): `night` = stage_machine policy,
  gates from stages.yaml; `supervised-lean` = stateless with a mandatory
  canonical/FINAL pointer at delivery (check_canonical).

**Report-side trouble rows** (engine rows live in the base skill):
T2 — dataset downloads must assert size+header (a 14-byte "404: Not Found"
file passed silently once). T20 — the builder scans `bundle/figures/` only;
figures elsewhere are invisible to assembly.

Details: `references/report_pipeline.md` (this fragment's reference),
stage playbooks under `modules/report/references/playbooks/`.
