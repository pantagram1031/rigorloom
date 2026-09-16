# Stage 1 — one complete report through `main`, publicly demoable

Status: ACTIVE 2026-09-16. Owner: Claude (goals, content, verification).
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

- [ ] G1 `boxed` display equations: `build_report.py` honors `box_display_equations`
      in build.yaml; `com_backend.op_insert_equation` draws the 1×1 double-border
      table box (port of the fork, lines 606–660); offline tests pass; `xml_backend`
      refuses `boxed` with a named reason (no silent drop).
- [ ] G2 poster line: `modules/report/scripts/poster_build.py` + `poster_verify.py`
      registered as `poster`/`poster-verify` CLI in `module.yaml`; optional extra
      `[poster]` = python-pptx + pillow; clean refusal when missing; tests with a
      synthetic 2-box pptx form.
- [ ] G3 AURALAB report workspace scaffolded with `new_report.py` under
      `Downloads/ReportWorkspace project/reports/`, stages 0→4 with real
      simulation data from `acoustic_building_analyzer`.
- [ ] G4 native assembly via Hancom COM on this PC, PDF verified page-by-page,
      `submission_preflight` green.
- [ ] G5 poster built from the same workspace with G2.
- [ ] G6 demo assets (sanitized PDF pages / PNGs) staged for the Stage 2 README.

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

## Workspace facts (for resume)

- Stage machine position after this session: 5 pending (assembly). `output/form_copy.hwpx` staged pristine. `doc_backend: hwp` in build.yaml.
- Sim: `sim/run_sim.py` (deterministic, seed 20260916) → `sim/results.json`, `sim/tables/*.csv`, `bundle/figures/fig1..12 + .sha256`. Engine axes: x = width 6 m, y = length 8 m; window wall at x = 0, secondary source (0.2, 4.0).
- Assembly command (playbook §HWP): `python engine/scripts/fill_report.py --loop --form <WS>/output/form_copy.hwpx --content <WS>/bundle/content.md --out-dir <WS>/output --build-yaml <WS>/build.yaml --form-profile <WS>/form_profile.json --proof --max-proof-iters 3` from the rigorloom-stage1 root.
