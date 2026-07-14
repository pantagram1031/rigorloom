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

EXIT + script gate `final_panel`: write `output/scorecard.json`, including the
three explicit stop-line fields `SENSITIVE_FRAMING`,
`LOAD_BEARING_DISPUTE`, and `UNSUPPORTED_NOVELTY`, plus each panelist's
findings and `blocking` flag. A high average never overrides a true stop line
or blocking finding. Missing/malformed `output/scorecard*.json` fails closed.

Resolve the registered checker, then advance to Stage 6:

```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.7 --status awaiting_gate
python pipeline/scripts/pipeline_ctl.py check <WS> final_panel
# exit 0 -> auto_approved; exit 3 -> rejected, repair the owning stage/panel
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.7 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| score below threshold | owning-stage defect | targeted loopback (max 2) to that stage |
| loopback ×2 still fails | — | status=blocked + reason |
| independent reviewers disagree on a number | — | trust the immutable simulation verdict; flag prose |
| preferred reviewer unavailable | environment limitation | select an equivalent independent reviewer and record the substitution |
| any stop-line field true | submission veto independent of score | loop back to the owning stage; never average it away |
| any panelist finding has `blocking: true` | unresolved blocking defect | repair and regenerate the scorecard |
| scorecard missing/malformed | no auditable panel verdict | create valid `output/scorecard.json`, then rerun `check final_panel` |
