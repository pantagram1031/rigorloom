# Stage 5 — Assemble + two-phase fill/proof loop
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Assemble on a form COPY with typeset-first defaults, converge
(phase 1 = metrics), prove (phase 2 = composition rubric). Goal = no
voids, many figures, in target_pages, uniform density.

ENTRY: `pipeline_ctl resume` → stage 5. Stage 4 done (gate draft ok).
Always start from an UNTOUCHED `<WS>/output/form_copy.hwpx`
(§8/§T non-destructive).

SINGLE ASSEMBLY PATH: no manual assemble+tidy steps. The ONLY path is
`fill_report.py --loop`, chaining build_report → COM edit → blank tidy →
restore-formats → keep_with_next → typeset-defaults (in-process when
`--form-profile` is passed, §O) → convert → QA, then (with `--proof`) the
rubric phase. Do not call `build_report.py` / `tidy_hwpx.py` directly —
that duplicates/undoes the loop and can reassemble from a pristine form.

EXACT commands (verify flags against `fill_report.py --help` if drifted):
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python <HWP_MASTER_ROOT>/scripts/fill_report.py --loop \
  --form <WS>/output/form_copy.hwpx \
  --content <WS>/bundle/content.md \
  --out-dir <WS>/output \
  --build-yaml <WS>/build.yaml \
  --baseline <WS>/form_baseline.json \
  --form-profile <WS>/form_profile.json \
  --proof --max-proof-iters 3
```

PROOF-LOOP PROCEDURE (step-numbered, §P):
1. Run the command above: phase-1 convergence (≤4 iters, §H) first; once
   converged, `--proof` runs `contact_sheet.py` on the final PDF and
   returns `status: awaiting_judge` with `contact_sheets:[...]`, `rubric`
   fields null.
2. vision-judge fills the rubric per `rubric-composition.md` (keys:
   `mid_bottom_void`, `density_uniformity`, `table_proportion`,
   `heading_plus_void`; all four `true` to pass).
3. All-pass → EXIT below. Any FAIL → writer applies a ±1–2 line
   `content.md` delta per the flagged `needs`, then re-run the SAME
   command with `--proof-needs needs.json` added (schema below).
4. `proof_iter` > 3 → verdict `status: escalate_human`; advance
   `--status blocked` (FAILURE table).

NEEDS SCHEMA (`--proof-needs needs.json`, code-verified): a JSON array,
each item one of:
```json
{"type": "rewrite_para", "anchor": "Ⅲ. 본론", "delta_lines": -2, "reason": "..."}
{"type": "resize_table", "index": 1, "cols": "10,16,12,9,10,43"}
```
Schema violation → `fill_report.py` exits 1 (code never rewrites content.md
itself — always the writer's job). verdict: `{phase, converged, iterations,
page_count, fig_count, bottom_white_worst, gaps_worst, contact_sheets:[...],
rubric:{...4 keys}, needs:[...], proof_iter, reason}`.

ROLE BINDINGS (§R): mech-worker=agent.worker/medium (runs the loop
command). vision-judge=agent.worker/medium fresh (high-capability worker=fallback).
writer=agent.worker/high (applies needs deltas). escalation fires on
proof-exhaust (candidates: human).

EXIT + gate: verdict `converged:true` AND rubric all four keys `true`.
Stage 5 has NO pipeline_ctl gate (gate:null) — verdict is internal.
Advance → 5.5 (implemented order: 5 → 5.5 → 5.7 → 6):
```
python pipeline/scripts/pipeline_ctl.py advance <WS> 5 --status done
```

FAILURE table:
| Symptom | Cause | Action |
|---|---|---|
| mid_bottom_void FAIL | table left gap | resize_table need / flow next block up / pageBreak=CELL split (S2) |
| density_uniformity FAIL | budget mismatch | rewrite_para need, delta_lines ±1–2, on offending section |
| table_proportion FAIL | cols too narrow | resize_table need — widen the data col |
| heading_plus_void FAIL | keepWithNext missing | already set by typeset-defaults; if persists, rewrite_para above heading |
| heading alone at page bottom, NO void | — | NOT a defect (§P), do nothing |
| pre/post form-hash differ | edited original not copy | discard, rebuild on fresh form_copy.hwpx (§8) |
| tempted to add a format knob | — | forbidden post-assembly (§P/§Q); use a needs delta |
| phase-1 `converged:false` after ≤4 iters | content/layout mismatch | `advance --status blocked --reason "phase-1 not converged: <detail>"`; resolve phase-1 needs, re-run |
| `proof_skipped_reason: "phase-1 not converged"` | `--proof` set but phase-1 never converged | proof never ran; resolve phase-1 needs first, re-run |
| proof_iter > 3 exhausted | genuine layout conflict | status=blocked, escalate_human with reason |
