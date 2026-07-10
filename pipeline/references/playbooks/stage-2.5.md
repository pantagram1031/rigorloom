# Stage 2.5 — Cast-off / Layout plan (NEW, script gate)
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: Decide the whole layout BEFORE prose exists — copyfit-first, like
publishing. Produces `bundle/layout_plan.json`. Prevents post-assembly knob
accumulation: all later layout repair is ±1–2 line content deltas (§N/§P/§Q).

ENTRY: `pipeline_ctl resume` → stage 2.5. Stage 2 done (gate design ok),
Stage 0 form_profile.json has `page_metrics` (lines/page, chars/line).
Runs after design, BEFORE sim/write.

EXACT actions:
Writer-designer (high-capability worker) drafts `bundle/layout_plan.json` from the cast-off
numbers. Schema (CONTRACT §N):
```json
{
  "target_pages": [4, 6],
  "sections": [{"anchor": "Ⅰ. 서론", "line_budget": 14}, ...],
  "tables":  [{"id": "표1", "cols_pct": [10,16,12,9,10,43], "est_rows": 7, "pt": 9}],
  "figures": [{"id": "그림1", "width_mm": 110, "place_section": "Ⅳ."}],
  "equations": [{"id": "eq1", "mode": "inline"}],
  "abstract_plan": {"lines": 7, "bold_keys": true}
}
```
Budgeting rules:
- Σ section line_budget ≤ target_pages × page_metrics.lines_per_page, minus
  the line cost of tables/figures/equations. Leave no planned void.
- Table cols_pct sum ≈100; choose est_rows so rows land ≈1 line
  (rubric `table_proportion`). Known-good: 표1 `[10,16,12,9,10,43]%` → 1-line rows.
- Equations: mode "inline" by default (§O/S1); "display" only for large
  matrices/derivations.
- 요약/초록 = one sentence per line ×6–9, bold keys (operator convention;
  table_map from form_profile locates the box).
- Figures: all figures go to the form's 그림 section (운영자 convention:
  figures collected at the end, referenced in body as "[그림 n]과 같이").

VALIDATE (the Stage 2.5 SCRIPT GATE):
```
# cd <REPO_ROOT>/ (all paths below are relative to this, repository-root CWD)
python <HWP_MASTER_ROOT>/scripts/layout_plan_check.py \
  <WS>/bundle/layout_plan.json \
  --form-profile <WS>/form_profile.json
# exit 0 = pass (Σ budgets fit target_pages; table cols sane) → advance
# exit 1 = fail → adjust layout_plan.json, re-run
```

ROLE BINDINGS (§R): writer-designer = agent.worker/high (agents.yaml
role `writer-designer` — this is a design decision, max effort).
mech-worker = agent.worker/medium may run layout_plan_check.

EXIT + gate: `layout_plan_check.py` exit 0. **Script gate `layout`, not
human.** Resolve the gate with the script's exit code, THEN advance:
```
python pipeline/scripts/pipeline_ctl.py gate <WS> layout --script-exit 0
python pipeline/scripts/pipeline_ctl.py advance <WS> 2.5 --status done
```
(`--script-exit` lives on the `gate` subcommand — 0 → approved, nonzero →
rejected/blocked. `advance` takes only `--status`/`--reason`.)

FAILURE-side gate (symmetric to success): a `layout_plan_check.py` exit 1
records rejection via the SAME `gate` call with the nonzero code — do NOT
advance:
```
python pipeline/scripts/pipeline_ctl.py gate <WS> layout --script-exit 1
```
Fix `layout_plan.json`, re-run the checker, re-gate with the new exit code.

FAILURE table:
| Symptom | Cause | Fix |
|---|---|---|
| check exit 1: Σ budget > pages | over-planned | trim section budgets or raise target_pages (if within request) |
| check exit 1: cols sum ≠ ~100 | bad table plan | fix cols_pct |
| est_rows → multi-line rows | cols too narrow for content | widen the data col (e.g. last col 43%) |
| no page_metrics in profile | Stage 0 missing --base-pt | rerun form_inspect with --base-pt/--line-spacing |
| plan implies mid-page void | table/figure placement | flow next block up; plan pageBreak=CELL split for long tables |
| Σ budget < capacity_min (target_pages[0] × lines_per_page) | under-planned — 미달/계획된 공백 | raise section budgets/figure count, or lower the `target_pages` floor (if within request) |
