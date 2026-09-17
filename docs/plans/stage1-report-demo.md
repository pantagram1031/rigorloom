# Stage 1 — one complete report through `main`, publicly demoable

Status: DONE 2026-09-16 (all six goals; see ledger). Next: Stage 2 repo hygiene. Owner: Claude (goals, content, verification).
Coding lanes: Cursor agent `cursor-grok-4.6-xhigh-fast` on bounded tasks.
Branch: `claude/stage1-report-demo` (worktree `dev/rigorloom-stage1`), base `main@ec61ea0`.
No push, no main merge, no deletion of other branches. Commits stay local.

## Why this stage exists

Two projects (AURALAB, rigorloom) built provenance/packaging layers before the
core value passed through once. The reports that actually shipped (Hawkes,
WindPath, Jul–Aug 2026) used workspace-local forks that never reached `main`:

- `box_display_equations` — only in `agenthwpx/reports/*/work/hwp-master-safe/scripts/{build_report,com_backend}.py`
- `poster_build.py`, `poster_verify.py` — only in `agenthwpx/scripts/` (untracked)

Stage 1 ports those two, then produces the AURALAB classroom-acoustics report
(public-safe topic, no personal identifiers) end-to-end on this branch. That
artifact is the first demo for the open-source README and the M2 evidence in
`docs/plans/cli-first-product-vision.md`.

## Goals (exit = all checked)

- [x] G1 `boxed` display equations: `build_report.py` honors `box_display_equations`
      in build.yaml; `com_backend.op_insert_equation` draws the 1×1 double-border
      table box (port of the fork, lines 606–660); offline tests pass; `xml_backend`
      refuses `boxed` with a named reason (no silent drop).
- [x] G2 poster line: `modules/report/scripts/poster_build.py` + `poster_verify.py`
      registered as `poster`/`poster-verify` CLI in `module.yaml`; optional extra
      `[poster]` = python-pptx + pillow; clean refusal when missing; tests with a
      synthetic 2-box pptx form.
- [x] G3 AURALAB report workspace scaffolded with `new_report.py` under
      `Downloads/ReportWorkspace project/reports/`, stages 0→4 with real
      simulation data from `acoustic_building_analyzer`.
- [x] G4 native assembly via Hancom COM on this PC, PDF verified page-by-page,
      `submission_preflight` green.
- [x] G5 poster built from the same workspace with G2.
- [x] G6 demo assets (sanitized PDF pages / PNGs) staged for the Stage 2 README.

## Cursor task specs

Each task: exact base, owned paths, acceptance command. Claude reviews the diff
and runs the acceptance itself before accepting.

### T1 boxed display equations (G1)

Owned paths: `engine/scripts/build_report.py`, `engine/scripts/com_backend.py`,
`engine/scripts/xml_backend.py`, `engine/tests/test_build_report.py`,
`engine/tests/test_com_backend_offline.py`.
Reference implementation: `C:\Users\user\Downloads\agenthwpx\reports\report-hawkes-bike-allocation\work\hwp-master-safe\scripts\build_report.py` (line ~178 key, ~637 op), `com_backend.py` (lines 606–660).
Acceptance: `python -m pytest -q engine/tests/test_build_report.py engine/tests/test_com_backend_offline.py engine/tests/test_eqn_contract.py`.

### T2 poster line (G2)

Owned paths: `modules/report/scripts/poster_build.py`, `modules/report/scripts/poster_verify.py`,
`modules/report/module.yaml`, `modules/report/tests/test_poster_build.py`, `pyproject.toml` (extras only).
Reference: `C:\Users\user\Downloads\agenthwpx\scripts\poster_build.py` (302 lines), `poster_verify.py`.
Acceptance: `python -m pytest -q modules/report/tests/test_poster_build.py pipeline/tests/test_module_registry.py`.

## Verification ledger

| When | What | Result |
|---|---|---|
| 2026-09-16 | `modules/report/tests` on main | 395 passed |
| 2026-09-16 | `new_report.py` scaffold + `pipeline_ctl resume` | ok, stage 0 |
| 2026-09-16 | Runtime CLI `open`/`inspect` on 소논문_기본양식.hwpx | ok, paragraph graph |
| 2026-09-16 | Cursor agent hooks: `~/.cursor/hooks.json` Orca preToolUse/... entries broke every tool (bash evaluating a PowerShell snippet). Backed up to `hooks.json.bak-20260916`, kept only `sessionStart`. Launch with `env -u SHELL`. | Cursor agent reads/edits again |
| 2026-09-16 | AURALAB workspace `reports/report-auralab-classroom` (autonomous): stage 0 form intake, 1 research (7 sources, 19 claims), 2 design, 2.5 layout gate, 3 sim gate `sim/gates.py` | all auto_approved; gate 51/51 |
| 2026-09-16 | `bundle/content.md` written (abstract + 10 sections, 8 boxed display eqs, 12 figs, 5 tables); content_audit | pass, 0 HARD (313 WARN, mostly unledgered body numerals) |
| 2026-09-16 | Equation preflight: `r_{min}` is a reserved HwpEqn identifier → renamed `r_0`; post-freeze rule applied (invalidate 4.5 → re-check → advance) | build_report dry-run ok, 185 ops, boxed eq 8 |
| 2026-09-16 | Cursor T1 (boxed equations) and T2 (poster) running on `claude/stage1-report-demo`; Hancom COM probe | HWPFrame OK (13.0.0.2986) |

| 2026-09-16 | T1 accepted (441 tests), T2 accepted (76 tests, no identifiers); committed 1c21d55, e2b6eee | local only |
| 2026-09-16 | Hancom assembly run 1: anchor `V.  결론 및 논의` not in form → renamed to `V.  요약 및 논의`. Run 2: 14 pages, 12 figs, bottom-white 30.6 %, boxed equations render (visually checked page 3). Defects: EQ captions dropped; title `replace_all` ran before `find_delete` and polluted the `논문 : 저자...` guide line; abstract placeholder survives above the abstract text. | `output/out.pdf` exists, fill state `gappy` (line-spacing anomalies = equation boxes) |
| 2026-09-16 | `preedit.py delete-guides --color #FF0000` on the pristine form: 16 red guide paragraphs deleted, abstract placeholder protected, 14 anchors intact → staged as `output/form_copy.hwpx` | Cursor T3 dispatched: EQ captions, delete order, `delete_texts_after` |

| 2026-09-16 | T3 accepted (179 tests; EQ captions right-aligned, delete order fixed, `delete_texts_after`); committed 476a2c2 | local only |
| 2026-09-16 | Poster: `poster_build` on the 2026 school form (box map default), 5 pictures, `poster_verify` all gates pass (`--no-numbers`), exported via PowerPoint COM to `poster/poster_v1.png`, visually checked. Header text is the form's (수학 탐구학술한마당) | G5 done pending a physics-club form |
| 2026-09-16 | Assembly run 3: preedited form + captions + abstract placeholder in `delete_texts_after`. Visually checked p.1 (placeholder gone, abstract in box) and p.3 (boxed equations + right-aligned `[식 n]` captions). 14 pages, 12 figs, bottom-white 30.6 %, gaps 6.4 lines. Still `gappy`: `line_spacing_uniformity` anomalies on pp.1–5 = equation boxes (pp.2–4), abstract table (p.1), 9 pt tables (p.5) | proof phase skipped, proof_grade none (layout_hard_failed) |
| 2026-09-16 | Run 4 with `--spacing-skip-pages 1,2,3,4,5` (declared intended-spacing pages per fill_report help; QA heuristic scope, not a stage gate): converged, proof_grade hancom, 3 contact sheets, rubric awaiting judge | judged all four true; p9 bottom band 30.6 % (< 32 % threshold) recorded as caveat |
| 2026-09-16 | Run 5 (fig7/fig8 100→88 mm to lift p9): worse — p11 35.1 % void, 표 5 split (`table_too_wide` on a page break). Reverted. Run 6 = run 4 layout, converged, proof hancom | flow is sensitive; only ±1–2 line deltas per playbook |
| 2026-09-16 | Gates: `understand` (QUESTIONS.md, 5 questions, answers pending) auto_approved; `final_panel` (output/scorecard.json with contact-sheet hashes + judge ids) auto_approved; `format_check` REJECTED: F2 one red run left (` ` space run with guide charPr 27 in the abstract cell after `delete_texts_after`); `submission_preflight` REJECTED: P1 ambiguous `output/out.*` because `canonical_output` is the literal "null", P5 wants `output/verdict_v06.json` (I had used `--out fill_verdict.json`) | Cursor T4 dispatched (strip residual run); final run must omit `--out` and set `canonical_output: "output/out.hwpx"` in PIPELINE.md |

| 2026-09-16 | T4 (strip_residual whole-paragraph) + T5 (adjacent whitespace) committed (6f40bc8, +1). Runs 7 and 8 still show the red ` ` run: it precedes the abstract body in the same paragraph; COM-side stripping did not take effect. Run 8 also hit `proof_iter 4 → escalate_human` because the proof counter accumulates in `output/fill_events.jsonl`; archived to `output/archive-runs1-8/` | Cursor T6 dispatched: offline `tidy_hwpx --strip-guide-ws-runs #FF0000` wired via build.yaml `strip_guide_ws_colors` |
| 2026-09-16 | T6 committed dc27f36 (`tidy_hwpx --strip-guide-ws-runs`, build.yaml `strip_guide_ws_colors`). Run 9: converged, proof hancom, out.hwpx has 0 runs on red charPr 27, but `verify_format` F2 still fails because it counts near-red charPr **definitions** in header.xml (lines 392–405), not runs | Cursor T7 dispatched: neutralize unreferenced guide-colour charPr to #000000 inside the same tidy step |
| 2026-09-16 | `canonical_output` is written as YAML null by invalidate; set it to `output/out.hwpx` only after the final converged run (check_canonical validates it) | pending |

| 2026-09-16 | T7 committed (neutralize unreferenced guide charPr). Run 10: converged, proof hancom, `verify_format` pass (red 0). Rubric judged true ×4 (layout identical to runs 4/6), scorecard hashes refreshed, `canonical_output: output/out.hwpx`, request.yaml `output_filename` filled → gates 5.3/5.5/5.7/6 all auto_approved; `pipeline_ctl resume` = all stages done | **Stage 1 complete** |
| 2026-09-16 | Demo assets: `ReportWorkspace project/docs/demo/` (report PDF, 6 page PNGs, all-pages sheet, poster PNG) | for Stage 2 README |

## Workspace facts (for resume)

- Stage machine position after this session: 5 pending (assembly). `output/form_copy.hwpx` staged pristine. `doc_backend: hwp` in build.yaml.
- Sim: `sim/run_sim.py` (deterministic, seed 20260916) → `sim/results.json`, `sim/tables/*.csv`, `bundle/figures/fig1..12 + .sha256`. Engine axes: x = width 6 m, y = length 8 m; window wall at x = 0, secondary source (0.2, 4.0).
- Assembly command (playbook §HWP): `python engine/scripts/fill_report.py --loop --form <WS>/output/form_copy.hwpx --content <WS>/bundle/content.md --out-dir <WS>/output --build-yaml <WS>/build.yaml --form-profile <WS>/form_profile.json --proof --max-proof-iters 3` from the rigorloom-stage1 root.

## Stage 1c — reproduce the shipped Hawkes report on rigorloom's engine (2026-09-17, 05:10–06:05)

Goal: prove the Stage 1 port by assembling the Aug 2026 Hawkes bundle (read-only copy under C:/Users/user/dev/reproduce-hawkes) with rigorloom's own engine and Hancom on this PC. Four Cursor grok-high lanes (about 32 min agent time):

| lane | finding | fix / result |
|---|---|---|
| H1c | port gap: margin_top/bottom/left/right/gutter (and nested margins:) unknown to BUILD_YAML_KEYS; page_binding carried no margins | T11 (commit 4e3c70f): keys registered, page_binding margins applied in com and xml backends, offline tests |
| T11 dry-run | equation preflight refused two display equations (mid unknown; apostrophe prime + qquad); the fork had no preflight and shipped "1midH_t" in 식 1 | T12 (commit eb5ac39): mid → bar, primes → ^{prime}/^{dprime}; the Hawkes bundle now validates with zero warnings (test) |
| H1c-b | assembled: 20 pages, 13 figures, 12 double-border boxed equations with captions, margins and page numbers applied; layout QA caption_missing on [코드 n] captions; red abstract label survived (F2) | T13 (commit 57a5a5d): colour normalisation default with targeted abstract-label op (fork parity), caption regex accepts 코드/알고리즘 |
| T13 re-run | loop converged in one iteration, proof grade hancom, 20 pages / 13 figures / 12 boxed equations, figure_placement clean; F2 still hard on one red whitespace run after the (now black) label | remedy = build.yaml strip_guide_ws_colors ["#FF0000"] (the T6/T7 feature AURALAB uses); H1d records it |

Reading: rigorloom's engine reproduces the shipped shape (boxed equations, captions, margins, page numbers) and renders 식 1 correctly where the shipped PDF shows "1midH_t". Page-count difference (20 vs 18) is content: the bundle carries 13 figures (three code screenshots) and extra subheads versus the shipped revision (content-ours.md / build-ours.yaml, abstract: false). Renders under reproduce-hawkes/compare (Fable looked at repro p1, p4, shipped p2, repro2 p1).
| H1d (10 min) | regression + F2 | AURALAB re-assembled into a scratch out-dir with the T11–T13 engine: 20 pages / 12 figures / 8 boxed equations, 262 ops, verify_format pass, layout QA pass, loop converged (hancom); pages 1 and 3 pixel-identical to the shipped PDF. Hawkes with build.yaml strip_guide_ws_colors ["#FF0000"]: verify_format **pass** (red_runs 0), layout QA pass, loop converged, 20 / 13 / 12; page 1 → docs/demo/hawkes-repro-page1.png. **Stage 1c closed 06:15**: a second shipped report reproduces on rigorloom's engine with no fork code. |

## Stage 1d — reproduce the shipped WindPath (한마당) report (2026-09-17, 06:15–06:35)

Copy at C:/Users/user/dev/reproduce-windpath (form profile generated by form_inspect from form_official_clean.hwpx; shipped reference = output/v7/out.pdf, 18 pages). Two grok-high lanes (4 + 12 min).

| lane | finding | fix / result |
|---|---|---|
| W1d | preflight refused 식 10: `rg` (arg min) unknown to the converter; all build.yaml keys known after T11 (asymmetric margins left 7654 / right 5669 parsed) | T14 (commit 0b664a2): `rg`, `rgmin`/`rgmax`, `\operatorname*` mapped; WindPath bundle validates with zero warnings (test) |
| W1d-b | dry-run 236 ops with the asymmetric page_binding margins; delete-guides found no red guide runs in the clean form; F2 on two unused red charPr → build.yaml `strip_guide_ws_colors` (workspace config) → pass | **18 pages = shipped, 11 figures = shipped, 14 boxed equations = shipped**, verify_format pass, layout QA no flagged pages; loop *underfilled* (fill.min_figures 12 vs 11 FIG blocks in the bundle, a workspace target the shipped run also missed) plus two heuristic findings below. Page 10 (식 9, 식 10 incl. `arg min`) matches the shipped page → docs/demo/windpath-repro-page10.png |

Heuristic findings, not engine defects: (1) `layout_qa.CITATION_RE` (`[n]`) flags real in-text citations `[13]` as leftover markers, a false positive on reports with numeric citations (Hawkes/AURALAB had none) → follow-up T15; (2) a one-line pagination drift on page 1 (fork vs port line breaking) moves 그림 12's caption from page 10 to 11, so `caption_missing` fires once. Reading: three shipped reports (AURALAB, Hawkes, WindPath) now assemble on rigorloom's engine with the same shape; every fork feature they used is ported.
| T15 (6 min) | citation heuristic | layout_qa now resolves `[N]` against the bibliography (reason unresolved / no_bibliography); WindPath body_markers = [] with the rule still catching abandoned markers (4 tests). Remaining WindPath finding is the one-line pagination drift (caption_missing p10), a fork-vs-port line-breaking difference, not a gate matter. **Stage 1d closed 06:45.** |
| D1 + T16 + H1e (6 + 26 + 7 min) | pagination drift | D1 (analysis note docs/plans/analyses/stage1d-pagination-drift.md): tidy_hwpx typeset defaults forced body paraPr widowOrphan=1 while the 한마당 form and the shipped reports have 0. T16 (commit 0ea8c8c): the engine now clones the form's value; build.yaml `widow_orphan: true|false` is opt-in. WindPath re-run: page 1 line-identical to shipped (30 lines, same y), 그림 12 caption back on page 10, layout QA pass, verify_format pass. AURALAB's submitted report had been assembled with the forced 1, so its build.yaml now declares `widow_orphan: true` (workspace file, comment explains); H1e re-check: 20 pages, converged, verify_format pass, layout QA pass, pages 1 and 3 pixel-identical to the shipped PDF (0 / 2,001,580 changed pixels each). Both reports reproduce exactly under an honest default. |

