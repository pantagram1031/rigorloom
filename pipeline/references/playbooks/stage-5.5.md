# Stage 5.5 — Understanding gate (anti-slop) → understand (script)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Make sure a human could defend the report. Generate 5 substantive,
teacher-style questions. In supervised mode the operator records their own five
answers; autonomous/night deliberately leaves answers pending.

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

EXPECTED `output/QUESTIONS.md` FORMAT: exactly five numbered question blocks.
Each block must contain substantive interrogative text, including a question
mark; empty labels, TODO/TBD, placeholders, or bare `Question N` blocks fail
closed. Questions may wrap across lines. A supervised human answer is non-empty
text introduced inside each block by `Answer:`; the checker also accepts the
equivalent Korean answer labels. Example:

```
1. Why does the integer sample index matter?
   Answer: My explanation in my own words.
```

- supervised: the operator writes one non-empty answer under every question;
- autonomous/night: leave model answers absent. The script gate passes only
  when all five questions are well formed and records `answers_pending: true`
  in `.pipeline/understanding_check.json`.

Resolve the script gate through the controller. It runs the bound checker and
preserves both the generic gate receipt and the detailed understanding
provenance:

```
python pipeline/scripts/pipeline_ctl.py check <WS> understand
# checker exit 0 = auto_approved by script; exit 3 = rejected, repair QUESTIONS.md
```

ROLE BINDINGS (§R): question generation = main/high-capability worker. No subagent needed.

EXIT + gate: **understand** (script gate):
- supervised: five non-empty operator answers are required; missing answers
  reject the checker with exit 3.
- autonomous/night: five well-formed questions are required, while missing
  answers remain allowed under auto-approved semantics. The detailed provenance
  retains `answers_pending: true` until a later answered check replaces it.
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
