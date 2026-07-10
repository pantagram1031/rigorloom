# Stage 5.7 — Final evaluation panel (fresh contexts)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Independent multi-lens scorecard before hand-off. Implemented order
(stages.yaml): runs AFTER understanding (5.5), BEFORE return (6).

ENTRY: `pipeline_ctl resume` → stage 5.7. Stage 5.5 done (understand gate).

EXACT actions → `output/scorecard.json`:
- **vision-judge** (agent.worker/medium, fresh): form fidelity ("does
  it look like a human filled THIS form"), figure human-ness/accuracy,
  table cleanliness, residual visual anomalies + composition rubric
  (`mid_bottom_void` / `density_uniformity` / `table_proportion` /
  `heading_plus_void` — §P, all four must be true to pass). Consumes the
  **contact sheet** + hi-res only for flagged pages (§S vision economy).
- **reviewer-logic** (agent.worker/high): rigor, logic, numbers vs
  sim/gate_result.json, citation coverage via provenance sidecar. **Pair
  with a second independent high-reasoning pass for the numeric check**.
- **judge (value/fit)** (high-capability worker, fresh): inquiry value, subject/curriculum
  fit, human-writing feel, 수준 정합 vs concept budget (K2).
- **code**: pages/figures/must_include/scope compliance.

Weighted score below threshold → targeted loopback to the OWNING stage
(max 2), else blocked. studio renders the scorecard.

ROLE BINDINGS (§R): vision-judge=agent.worker/medium (registered
candidate; agent.worker/high is the fallback per agents.yaml);
reviewer-logic=agent.worker/high + agent.worker/high (numbers); judge=agent.worker/high;
code=deterministic script. All fresh contexts.

EXIT + gate: scorecard.json written, weighted score ≥ threshold. No
pipeline_ctl gate (gate:null) — panel verdict is internal. Advance → stage 6:
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.7 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| score below threshold | owning-stage defect | targeted loopback (max 2) to that stage |
| loopback ×2 still fails | — | status=blocked + reason |
| independent reviewers disagree on a number | — | trust the immutable simulation verdict; flag prose |
| preferred reviewer unavailable | environment limitation | select an equivalent independent reviewer and record the substitution |
