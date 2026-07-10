# Stage 2 — Design → 🚪 gate: design (human-type)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Inquiry question, hypothesis, variables, and the RESULT
VERIFICATION GATE design (≥2 independent criteria). Concept budget for
level-fit.

ENTRY: `pipeline_ctl resume` → stage 2. Stage 1 done.

EXACT actions:
- Write `01_design.md`: 탐구문제·가설·변인(독립/종속/통제)·방법 + verification
  gate design (≥2 independent criteria: 해석해 대조 / 보존량 일치 / 공개데이터
  교차검증). The gate's *measured* side MUST be independent of its *expected*
  side (§7 — never compare injected noise to itself). scope constraints =
  declared inputs to the gate code.
- curriculum/domain mapping and an explicit boundary for optional extensions.
- **개념 예산 (K2)**: allowed concepts (textbook naming) / forbidden college
  jargon (with HS substitute). Feeds Stage 4 level-fit + Stage 5.7.
- Methodology 3-option panel → main synthesizes (max effort).

ROLE BINDINGS (§R): judge-panelist ×2 = agent.worker/medium +
agent.worker/high (independent proposals). designer/main = high-capability worker (high, synthesis).

EXIT + gate: `01_design.md` complete. **Gate design** (CONTRACT §A):
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python pipeline/scripts/pipeline_ctl.py gate <WS> design --mode <mode>
# supervised → STOP, request approval (chat "approve design" → transcribe
#   to APPROVALS.md then gate). autonomous/night → auto_approved (logged).
python pipeline/scripts/pipeline_ctl.py advance <WS> 2 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| gate criteria not independent | measured==expected side | redesign; §7 forbids self-comparison |
| supervised gate: no approval line | operator absent | STOP; do not self-approve; wait or switch night |
| concept budget empty | K2 skipped | add before advancing (Stage 4 needs it) |
| panel proposals identical | not independent backends | re-run one via agent.worker/high for a true 2nd source |
