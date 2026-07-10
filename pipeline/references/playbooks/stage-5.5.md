# Stage 5.5 — Understanding gate (anti-slop) → 🚪 understand (human-type)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Make sure a human could defend the report. Generate 5 teacher-style
questions; no model answers provided.

ENTRY: `pipeline_ctl resume` → stage 5.5. Stage 5 done (assemble converged +
rubric pass). Implemented stage order (stages.yaml): …5 → **5.5 → 5.7** → 6
(understanding gate comes BEFORE the eval panel).

EXACT actions:
- Generate 5 questions a teacher would ask, priority order:
  1. 핵심식 유도 (derive the key equation)
  2. 검증게이트 의미 (what the verification gate proves)
  3. 변인·통제 근거 (why these variables/controls)
  4. 한계 이유 (why the stated limitations)
  5. 후속탐구 (next inquiry)
- Present WITHOUT model answers.

ROLE BINDINGS (§R): question generation = main/high-capability worker. No subagent needed.

EXIT + gate: **understand** (human-type gate):
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python pipeline/scripts/pipeline_ctl.py gate <WS> understand --mode <mode>
```
- supervised: operator answers; if they can't self-answer ≥3, record
  "제출 전 복습 필요" and still gate per operator decision.
- autonomous/night: generate + record questions, auto_approved (mark: human
  did not review).
Advance → stage 5.7 (eval panel):
```
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.5 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| operator can't answer ≥3 | report over level / not understood | record "복습 필요"; consider K2 level-fit loopback |
| questions trivially answerable | too shallow | regenerate at higher priority (derivation, gate meaning) |
| supervised: operator absent | — | do not auto-approve in supervised; wait |
