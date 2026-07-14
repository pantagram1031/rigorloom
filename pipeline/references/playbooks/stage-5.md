# Stage 5 — Assemble (backend-conditional) + two-phase fill/proof loop
<!-- <WS> = <REPO_ROOT>/workspaces/report-<slug> (절대경로 — CWD는 <REPO_ROOT>라 상대경로 report-<slug>는 실패) -->

PURPOSE: turn the approved bundle into a deliverable. The document backend is
chosen in `build.yaml` (`doc_backend:`) and dispatched by
`python pipeline/scripts/doc_backend.py <WS> [--backend ...]`. Four tiers:

| backend | dependency | deliverable | this playbook |
|---|---|---|---|
| `bundle` (default) | none (stdlib) | frozen bundle + `preview.html` | §BUNDLE |
| `docx` | `pip install python-docx` | `output/out.docx` | §DOCX |
| `hwpx` | hwp-master XML engine (any OS) | `output/out.hwpx` | §HWPX (advisory proof) |
| `hwp` | Windows + Hancom + hwp-master | `out.hwpx`/PDF | §HWP (full loop) |

Backend resolution: `--backend` flag > `build.yaml` `doc_backend:` > default
`bundle`. ENTRY REQUIREMENT IS THE SAME FOR ALL BACKENDS: Stage 4 done (gate
draft ok) and Stage 4.5 `content_audit` approved via
`python pipeline/scripts/pipeline_ctl.py check <WS> content_audit`. Stage 5 has
no gate of its own (`gate:null`); every backend exits through the Stage 5.3
`format_check` script gate after assembly.

STAGE 5 ENTRY SNAPSHOT (ALL BACKENDS): after the Stage 4.5 audit is approved
and before the first assembly command, create the rotating restore point:

```
python pipeline/scripts/ws_snapshot.py snapshot <WS>
```

This captures `bundle/`, `output/`, `PIPELINE.md`, and `.pipeline/` (when
present) under `<WS>/.snapshots/` before the risky assembly step. If assembly
damages the workspace, recover the latest snapshot with
`python pipeline/scripts/ws_snapshot.py restore <WS>` after emptying the
current `bundle/` and `output/`, or add `--force` to preserve those current
trees under `<WS>/.pre-restore-<UTCstamp>/` before recovery.

POST-FREEZE CONTENT RULE (ALL BACKENDS): after Stage 4.5 passes, ANY delta to
`bundle/content.md` invalidates that audit and every downstream artifact. This
includes the small proof-loop rewrites below. Before reassembly, always run the
real CLI sequence (the invalidate option is named `--from`):

```
python pipeline/scripts/pipeline_ctl.py invalidate <WS> --from 4.5 --reason "post-freeze content delta"
python pipeline/scripts/pipeline_ctl.py check <WS> content_audit
python pipeline/scripts/pipeline_ctl.py advance <WS> 4.5 --status done
# Re-enter Stage 5 and rebuild every canonical output/proof from audited content.
```

STAGE 5.3 FORMAT GATE (ALL BACKENDS): once the selected backend has produced
its canonical deliverable, complete Stage 5 and run the registered checker:

```
python pipeline/scripts/pipeline_ctl.py advance <WS> 5 --status done
python pipeline/scripts/pipeline_ctl.py check <WS> format_check
python pipeline/scripts/pipeline_ctl.py advance <WS> 5.3 --status done
```

`format_check` runs `verify_format.py <WS> --require-output`. Because this is a
post-assembly gate, missing `output/out.hwpx` is HARD
(`output_missing`, exit 3); only standalone/advisory calls that omit
`--require-output` retain the legacy skipped result. The gate hard-enforces
declared body font, line spacing, red-marker leakage, margins, and PDF page
bounds. When page bounds are declared but PyMuPDF is unavailable, it fails HARD
with `page_count_unverifiable`; a declared bound may not pass unchecked. A
graded build with no declared margin or page-bound expectation emits an
explicit WARN naming exactly which expectation is unverifiable. Exit 2 means
the checker could not parse its inputs; exit 3 means missing assembly output or
a real format violation. Do not advance 5.3 after either nonzero exit. A
successful 5.3 advance resumes at Stage 5.5.

---

## §HWPX — COM-free form fill (any OS; advisory proof only)

Selected when `doc_backend: hwpx`. Set `HWP_MASTER_SCRIPTS` to the external
hwp-master `scripts/` directory, then run:

```
python pipeline/scripts/doc_backend.py <WS> --backend hwpx
```

The dispatcher invokes `fill_report.py --engine xml` with the workspace form,
content bundle, and output directory. This tier fills `output/out.hwpx` without
Hancom or COM on any OS. A PDF made on Linux with headless LibreOffice plus the
H2Orestart extension is advisory render evidence only; it is not print-grade
proof. Use the `hwp`/Hancom tier below for the full convergence and print-grade
proof loop.

---

## §HWP — assemble on a form copy (Windows + Hancom + hwp-master)

Selected when `doc_backend: hwp`. Semantics unchanged from prior versions.

PURPOSE: Assemble on a form COPY with typeset-first defaults, converge
(phase 1 = metrics), prove (phase 2 = composition rubric). Goal = no
voids, many figures, in target_pages, uniform density.

When `.pipeline/personalization.lock.json` exists, use its form conditions and
layout conventions as input constraints. Do not edit the lock during assembly.

ENTRY: `pipeline_ctl resume` → stage 5. Stage 4 done (gate draft ok) and
Stage 4.5 `content_audit` approved via
`python pipeline/scripts/pipeline_ctl.py check <WS> content_audit`. Always start
from an UNTOUCHED `<WS>/output/form_copy.hwpx` (§8/§T non-destructive).

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
   `content.md` delta per the flagged `needs`, then runs the mandatory
   POST-FREEZE CONTENT RULE above (invalidate 4.5, re-check, advance 4.5),
   re-enters Stage 5, and runs the SAME command with
   `--proof-needs needs.json` added (schema below).
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
Then run the common Stage 5.3 format-gate sequence above. Do not proceed to
Stage 5.5 until `format_check` passes and Stage 5.3 is done.

Any proof rewrite that changes `content.md` without the invalidate/re-check
sequence is a freeze bypass; do not reuse its assembled outputs.

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

---

## §BUNDLE — package + render preview (zero-dependency, the any-machine floor)

Selected when `doc_backend:` is absent or `bundle`. No HWP, no Hancom, no
network — this tier produces the frozen bundle plus an honest stdlib HTML
preview. There is no form copy or proof loop. The 4.5 content_audit gate is
unchanged and still required, but the registered Stage 5.3 gate now requires
`output/out.hwpx`; therefore a bundle-only build is an advisory artifact and
cannot complete the post-assembly format gate.

COMMAND (CWD = `<REPO_ROOT>`):
```
python pipeline/scripts/doc_backend.py <WS> --backend bundle
```
Writes to `<WS>/output/deliverable/`: `content.md` (verbatim), `figures/`,
`provenance.json` (if present), `preview.html` (SECTION→h2, paragraphs,
`[[FIG]]`→`<img>`+caption, `[[EQ]]`→literal source in `<code class=eq>` — NOT
typeset, an honest preview, `[[TABLE]]`→`<table>`), and `manifest.json`
(file list + sha256 + `generated_at`; preview/copies carry no timestamp so they
are byte-stable).

EXIT + gate: exit 0 = deliverable written. There is no proof rubric. A direct
standalone `verify_format.py <WS>` call may record a skipped advisory result,
but the registered Stage 5.3 checker passes `--require-output` and fails HARD
until an assembled `output/out.hwpx` exists.
Exit 2 = `bundle/content.md` missing (Stage 4 not really complete) — do not
advance; return to Stage 4.

## §DOCX — optional styled DOCX (pure-python, `pip install python-docx`)

Selected when `doc_backend: docx`. Same entry gate (4.5 approved). Optional
extra; PDF conversion is left to the user (LibreOffice:
`soffice --headless --convert-to pdf out.docx`).

COMMAND (CWD = `<REPO_ROOT>`):
```
python pipeline/scripts/doc_backend.py <WS> --backend docx
```
Writes `<WS>/output/out.docx` (title from `build.yaml` `title:`, SECTION→
Heading 1, figures embedded at `[[FIG width=NNmm]]` or 110mm, tables). DOCUMENTED
v1 LIMITATION: equations render as inline italic text (the literal source), not
OMML. Exit 5 = python-docx not installed (`pip install python-docx`); exit 2 =
`bundle/content.md` missing. Like §BUNDLE, DOCX-only output cannot satisfy the
registered Stage 5.3 `--require-output` gate; assemble `output/out.hwpx` before
advancing.
