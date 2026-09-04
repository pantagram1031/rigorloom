# Checkpoint 07 — editing on our own pages, the document that was wrong, and equations that size themselves

Non-merging checkpoint. Written from `origin/claude/engine-e2-eq-extent`
(this branch, `docs/checkpoint-07`, is cut from that tip and stays
unmerged). Covers #221 (desktop: gap 34 closed — seats, a caret and the
ambiguity chooser now work on a page this repo drew itself, no Hancom PDF
required; 473 corpus seats, renderer-address-vs-scan disagreement 0; smoke
551/0), #222 (the render-check document's two-column section, F49, was our
own malformed test document — Hancom ignores `hp:colPr` when a header or
footer control precedes it in the section head; fixed the builder, not the
renderer; tally 3/37/9/2 → **3/38/8/2**), and #223, the eq-extent PR
(`claude/engine-e2-eq-extent`, PR **#223**, base `claude/engine-e2-pagination`):
an inline `hp:equation` reserves the layout height Hancom's own script
engine computes, not the declared `hp:sz@height` — render-check pages
**11 → 10** against Hancom's 9, page agreement 47 → **49/51**. Also in this
window, #224 (`claude/engine-e3-writer-colpr-order`, base
`claude/engine-e3-hancom-accept`): the writer-line consequence of #222,
recorded as a standalone read-only lint (`hwpx_lint.py --section-order`)
rather than a silent reorder, since the lexical writer has no section-head
assembly helper to fix. Checkpoint-06 (`docs/checkpoint-06`, off #219) carries
forward as the record of the pagination/metrics line and the state before
this window.

**Operating notes this window, stated honestly.** #223's own body reports
"engine/tests green per the agent" rather than a numbered pass/fail count —
looser than #221's, #222's and #224's numbered evidence, and named here
rather than smoothed over. The full-suite gate deferral carried since
checkpoint-05/06 across #205–#218 is now **#205–eq-extent (#223)**: one
gate is reported running in background on the #222 tip as of this writing,
but no PR body in this window records a completed run.

## What changed since checkpoint-06

| metric | checkpoint-06 | checkpoint-07 | moved in |
|---|---|---|---|
| renderer-line shape | #218 → #219 (pagination, tip) | #219 forks into **two siblings**, both based on `claude/engine-e2-pagination`: **#222** (F49 corpus fix) and **#223** (equation extent, this branch's tip) — neither includes the other | #222, #223 (diverged, not yet reconverged) |
| desktop line | #214 → **#217** (renders with the converged renderer) | #217 → **#221** (gap 34 closed: seats/caret/chooser on an own-rendered page) | #221 |
| writer line | #177 → #180 → #189, unmoved this window | **#189 → #224** (section-head control order Hancom needs, recorded and linted) | #224 |
| runtime line | unmoved (…→#185→#204) | **still unmoved** — no PR in #221–#224 touches it | — |
| render-check tally (51 features) | 3 · 37 · 9 · 2 (post-#219) | **3 · 38 · 8 · 2** (post-#222: F49 `differs`→`close`, IoU 0.141→0.355) | #222 |
| render-check page agreement | 47/51 (post-#219) | **49/51** (post-#223) | #223 |
| render-check page count (synthetic doc) | 11 vs Hancom's 9, two named mechanisms (equations, two-column) | **10 vs 9** — the equation mechanism is fixed (#223); the two-column mechanism turned out not to be a renderer bug at all (#222); one page of drift remains, now unnamed | #222 (diagnosis reversed), #223 (page moved) |
| gap 34 (own-render has line boxes, not text/addresses/seats/caret) | named at checkpoint-05, unchanged through checkpoint-06 | **closed** — sidecar line boxes now carry `text`, `char_x`, `size_pt` and the OWPML address at draw time; renderer address vs form-scan agree 393/disagree 0 over 2,271 spans; 473 seats produced | #221 |
| desktop smoke | 499/0 (#217) | **551/0** across 14 phases (#221) | #221 |
| equation extent rule | not measured | **adopted**: reserve = `min(declared, max(nominal, ink))` off the renderer's own equation layout tree at a pinned extent dpi, n=18 (4 render-check + 14 holdout), worst residual 19% vs 84% for the declared height | #223 |
| F49 diagnosis | "Hancom appears to require a column break or section restart before `hp:colPr` takes effect" (guess, unchanged since checkpoint-05) | **reversed**: Hancom ignores `hp:colPr` only when a header/footer control *precedes* it in the section-head paragraph — ten probe variants, no attribute exception. The render-check document itself emitted the wrong order; the renderer was already right | #222 |
| corpus (10–12 forms) | ssim/IoU deltas from #218/#219 | **unaffected by #222 or #223** — no corpus form has `colCount>1` or an equation; all forms byte-identical under both PRs | #222, #223 |
| holdout (14 documents) | not separately re-run this window at checkpoint-06 | **18/18 pages** (4 render-check + 14 holdout), line IoU 0.5847 → 0.5861, pair rate flat, floors pass | #223 |

## 1. Branch DAG

Renderer line, tip at #219 (checkpoint-06), now **forks** rather than
extends:

| PR | branch | base | slice |
|---|---|---|---|
| #219 | `claude/engine-e2-pagination` | `claude/engine-e2-line-metrics` | inline-object line box (checkpoint-06 tip) |
| **#222** | `claude/engine-e2-columns-f49` | `claude/engine-e2-pagination` | **F49 was the render-check document's own bug, not the renderer — fixes `build_render_check.py`'s section-head control order** |
| **#223** | `claude/engine-e2-eq-extent` | `claude/engine-e2-pagination` | **an inline equation reserves its own layout extent, not `hp:sz@height`** |

`#222` and `#223` are named siblings in #223's own PR body ("Depends on:
#219 … sibling of #222"). Both branch from #219 directly and neither
contains the other's commits: this worktree (`docs/checkpoint-07`, cut
from #223's tip) does not carry #222's F49 builder fix, and #222's tip
does not carry #223's equation-extent fix. **A small convergence PR —
merging #222 into #223 or vice versa — is needed before the next renderer
slice**, or the two fixes' combined effect on render-check (F49 `close`
*and* pages 10 vs 9 together) is never measured as one state.

Desktop line, tip at #217 (checkpoint-06), now extends by one PR:

| PR | branch | base | slice |
|---|---|---|---|
| #217 | `claude/desktop-own-render-converged` | `claude/desktop-own-render` | renders with the converged renderer (checkpoint-06 tip) |
| **#221** | `claude/desktop-own-render-edit` | `claude/desktop-own-render-converged` | **seats, a caret and the ambiguity chooser on a page this repo drew itself (gap 34) — new desktop-line tip, and the last big editor-threshold item: a fresh install with no Hancom PDF can now be typed in** |

Writer line, unmoved at checkpoint-06 (#177 → #180 → #189), now extends:

| PR | branch | base | slice |
|---|---|---|---|
| #189 | `claude/engine-e3-hancom-accept` | `claude/engine-e3-writer-routing` | Hancom acceptance harness (writer-line tip through checkpoint-06) |
| **#224** | `claude/engine-e3-writer-colpr-order` | `claude/engine-e3-hancom-accept` | **the section-head control order Hancom needs (#222's finding), recorded in `owpml-writer-notes.md` §9 and enforced by a standalone read-only lint — new writer-line tip** |

Sibling docs branch:

| PR | branch | base | note |
|---|---|---|---|
| #220 | `docs/checkpoint-06` | `claude/engine-e2-pagination` | prior checkpoint (this doc's predecessor) |

### Runtime line

Unmoved this window: …→ #185 → #204. No PR in #221–#224 touches it.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #221 — editing on our own pages (gap 34)

The own renderer's sidecar line boxes now record what they drew: `text`,
`char_x` (per-character left edges, kerning preserved), `size_pt`, and the
OWPML `address` (paragraph index or containing cell, read at draw time so
an inline table cannot clobber it); new `cell_boxes` carry each drawn
cell's `hp:cellAddr`. The runtime reshapes tier-3 boxes into the tier-1
span shape and runs them through the same `map_spans` + form-scan
discipline the Hancom-PDF path uses; the renderer's own address may only
*confirm or demote* the scan's answer (`cross_check_own`), never override
it.

Measured, corpus (10 forms, 2,271 spans): renderer address vs form scan —
**agree 393 · disagree 0** · among candidates 1,205 · not among 3
(spot-checked legitimate) · renderer-only 670 (left unmapped,
deliberately). **473 seats.** `char_x` on 2,270/2,271 lines.

Smoke page (tier 3, gianmun p1): 30 spans with `charX`; 9 seats, all
`own_cell`, 9 drawn == 9 returned; 5 unique / 21 ambiguous / 4 unmapped;
caret → `set_run` at `atPara 3`; seat click → plan naming `0-0-14`.

Two defects found pre-commit: comparing full address keys read 256/393
scan-unique lines as contradictions when both sides carried the same
`atPara` (a numbering artefact, not a disagreement); the first
cross-check counted every scan-ambiguous span as a disagreement.

Evidence: engine 204; runtime 305 + 311 sweep; `tsc` 0; sidecar 0 with a
new addressability role check (`own_cell` advertised); `tauri build` 0;
**smoke 551/0** across 14 phases; archive privacy gate HARD=0.

Not proven: the tier-3 raster stays `own-uncertified` (gap 35); the
README evidence table still cites WARN=45 vs today's 51 (pre-existing,
follow-up).

### #222 — F49 was our document, not the renderer

Hancom ignores an `hp:colPr` that a header or footer control *precedes*
in the section-head paragraph; no attribute matters. Ten probe variants
exported through official Automation: any order with header/footer
before `colPr` → 1 column; `secPr, colPr, …` or `colPr` in the next
paragraph → 2 columns. `render-check-01` emitted the wrong order, so
Hancom rightly rendered F49 single-column while `own_render` (which
honours `colCount` regardless of position) drew two.

Fix: `build_render_check.sec_pr` now emits `secPr, colPr, furniture`; the
document and its Hancom reference re-authored, re-exported and re-pinned;
`own_render` untouched. The corpus has no `colCount>1` form; all 12 forms
byte-identical.

Numbers: F49 `differs` (IoU 0.141) → `close` (0.355); tally 3/37/9/2 →
**3/38/8/2** — F49 is the only row that moved. Pages still 11 vs 9 and
agreement 47/51 at this PR's own tip: the two-column section was **not**
the second extra page; the remaining drift is the equation over-reserve
(#223, in flight as a sibling) plus an unexplained residual.

Writer-side fact recorded for the writer line: any HWPX writer must place
`hp:colPr` before header/footer controls in the section head or Hancom
silently drops the columns — this is what #224 turns into a lint.

Evidence: engine/tests 1213 passed; `py_compile_sweep` 0 failures;
archive privacy gate HARD=0 (re-pinned reference admitted by the
manifest).

Not proven: the 11-vs-9 drift (at this PR's own tip, before #223); the
`convert` document=10/pdf=9 page warning (reproduces on pre-fix bytes);
two pre-existing `test_cleanroom_evals` failures on the base branch
(follow-up, not this PR's).

### #223 — an inline equation reserves its own extent (this branch's tip)

Hancom re-lays an `hp:equation`'s script out on open and reserves its own
layout height — the declared `hp:sz` is a cache Hancom refreshes, not an
instruction (two blocks declaring the same 2400 reserve 2252 and 1304).
No "size to content" attribute distinguishes the disagreeing cases:
`heightRelTo`, `protect`, `lineMode`, `version` are identical.

Adopted reserve = `min(declared, max(nominal, ink))` from the renderer's
own equation layout tree at a pinned extent dpi — n=18 (4 render-check +
14 holdout), worst residual +256 HWPUNIT (19%), mean 178, vs +1492 (84%) /
mean 910 for the declared height.

| script | declared | Hancom | ours nominal / ink |
|---|---|---|---|
| `a over b` | 2400 | 2252 | 2352 / 1868 |
| `sqrt{x²+y²}` | 2400 | 1304 | 1526 / 1556 |
| `sum … over 6` | 3600 | 2696 | 2592 / 2202 |
| `[matrix]` | 3600 | 2108 | 2364 / 2364 |

Render-check: pages **11 → 10** (Hancom 9); page agreement **47 →
49/51**; IoU 0.4139 → 0.4176; ssim_inked 0.1726 → 0.1761; tally unchanged
at 3/38/8/2 (measured on top of #222's F49 fix — F37–F39 IoU each up;
F46/F47 rejoin Hancom's page). Corpus: zero equations, all ten renders
byte-identical. Holdout: 18/18 pages, line IoU 0.5847 → 0.5861, pair rate
flat, floors pass; nominal/declared mean 0.993 across its 14 equations.
One coupled drawing fix: the mask's 1 px antialias margin no longer
counts against the box (it had fired a 13% shrink at 96 dpi).

Evidence: "engine/tests green per the agent" (not a numbered count, in
contrast to #221/#222/#224); `py_compile_sweep`; archive privacy gate
HARD=0.

Not proven: n=4 on the PDF side; the ≤19% residual is our own equation
layout, unexplained; `lineMode`/`heightRelTo` never vary in any available
document. **The last extra page (10 vs 9) is now unnamed** — the PR notes
`convert`'s own document=10 / pdf=9 warning on the reference export
(Hancom may drop a page on export) as the next question. Two pre-existing
`test_cleanroom_evals` failures on the base branch (follow-up).

### #224 — the section-head control order, recorded and linted

Writer-side consequence of #222. `hwpx_write.py` has no section-head
assembly helper (its blank package is a static template, no header/footer
ever emitted), so the guard is a standalone read-only lint:
`engine/scripts/hwpx_lint.py --section-order` — it WARNS, never reorders
(a lexical writer must not silently change documents); exit 0 clean / 1
warned / 2 no check. Recorded as §9 of `owpml-writer-notes.md` with the
probe table.

Tests (14): six probe orders including the next-paragraph case and
header-subList non-descent; a synthetic bad/good pair on
`blank_package()` (library + CLI); the corpus (12 forms) → 0 warnings;
the F49 document pre-fix flagged / post-fix clean via read-only
`git show` of #222's commits.

Evidence: engine/tests 1138 passed / 135 skipped; `py_compile_sweep`
104/0; archive privacy gate HARD=0.

## 3. Regressions (with the PR's or commit's own explanation)

None of #221, #222, #223 or #224 reports a numeric regression in its own
body — a change from checkpoint-06, where #218's page-agreement drop and
#219's `kstartup` p5 ssim drop were both stated trade-offs. The one item
worth flagging as a *quality* regression rather than a numeric one: #223's
evidence line ("engine/tests green per the agent") is looser than every
other PR in this window and than #219's "engine/tests 1209 passed" — no
count is given, so a partial run cannot be distinguished from a full one
by reading the PR body alone.

## 4. Unsupported / declared elements still open

Carried from checkpoint-06, with items this window's PRs closed, refined,
or reversed:

- **Closed since checkpoint-06:** gap 34, own-render geometry had line
  boxes but no text/addresses/seats/caret (#221 — closed, 473 seats,
  0 disagreements against the form scan); the equation half of the
  render-check page-count residual (#223 — measured and fixed, pages
  11 → 10).
- **Reversed, not closed as expected:** F49 (다단 2단 구역) was catalogued
  since checkpoint-05 as "Hancom requires a column break or section
  restart before `hp:colPr` takes effect" — measurement in #222 finds
  this is wrong. The real rule is header/footer-before-`colPr` ordering,
  and the render-check document itself violated it. The renderer's
  `hp:colPr` handling was never broken.
- **Still open, unnamed:** the last render-check page (10 vs Hancom's 9).
  With both the equation mechanism (#223) and the F49 misdiagnosis (#222)
  resolved, no named mechanism remains for the residual page — see §7.
- **Still `differs`, current state (post-#222, tally 3/38/8/2), with
  mechanism:**
  - `F06`–`F08` (줄간격 PERCENT 130/160/200%) — bands now agree with
    Hancom to the pixel (121/121, 140/140, 94/94); the `differs` verdict
    is `ssim`/`ink Δ` alone, attributed to rasteriser/hinting
    differences, not layout.
  - `F13` (자간), `F15` (상대 크기 relSz) — same: the underlying metric bug
    is fixed (line-and-character-metrics.md §3/§6); both miss `close` by a
    small ssim/ink margin, not a position error.
  - `F35` (그림 — 어울림, TOP_AND_BOTTOM) — declared limit: `hp:pic@pos`
    places the anchored image at its declared offset without wrapping
    text around it.
  - `F48` (구역 나누기 — 가로 용지) — reference-side limit, not a renderer
    limit: Hancom's PDF export flattens every page to 595×841 pt portrait
    even when the section declares landscape A4; cannot be improved from
    the renderer side.
  - `F50` (머리말) — drawn, but positioned right of Hancom's; mechanism
    guess unchanged since checkpoint-05/06: centring against the page box
    rather than the header `hp:subList`'s own declared `textWidth`.
- **Unchanged from checkpoint-06:** whole-document computed layout's
  page-count/line-IoU failure (#199); the writer line's default
  header/meta elements on a blank package save (unrelated to #224's
  lint, which only warns and never assembles); `hp:ole`/`hp:chart`/
  `hp:container`/shapes/undecodable EMF-WMF placeholders;
  `DOUBLE_SLIM` border limitation; `hp:parameters` family;
  `hp:autoNum` field inside a footer draws nothing (`F51`); `hh:tabPr`
  stops inside the MCE switch never read; the tier-3 raster's own
  `own-uncertified` status (gap 35, named again by #221 as not closed by
  the addressability work).

## 5. Tests actually run per PR (from PR bodies)

| PR | orchestrator / engine suite | full suite | notes |
|---|---|---|---|
| #221 | engine 204; runtime 305 + 311 sweep; **smoke 551/0** across 14 phases | not applicable (desktop smoke/geometry, not the engine full suite) | `tsc` 0; sidecar 0 (+ addressability role check); `tauri build` 0; archive privacy gate HARD=0 |
| #222 | engine/tests 1213 passed | deferred | `py_compile_sweep` 0 failures; archive privacy gate HARD=0; two pre-existing `test_cleanroom_evals` failures on the base branch, named as follow-up not this PR's |
| #223 | "engine/tests green per the agent" — **no count given** | deferred | `py_compile_sweep`; archive privacy gate HARD=0; same two pre-existing `test_cleanroom_evals` failures named again |
| #224 | engine/tests 1138 passed / 135 skipped | deferred | `py_compile_sweep` 104/0; archive privacy gate HARD=0 |

Full-suite gate deferral is now a streak spanning **#205 through eq-extent
(#223)** with no appended run recorded in any PR body through this
checkpoint. One gate is reported running in the background on the #222
tip as of this writing, but its result is not yet in any PR and is not
claimed here — still owed, exactly as checkpoint-05 and checkpoint-06
flagged it.

## 6. Integration conflicts expected when lines converge

**Named this window: #222 and #223 need a small convergence before the
next renderer slice.** Both fork from #219 (`claude/engine-e2-pagination`)
independently; #223's own body calls #222 a sibling. Neither branch
contains the other's fix. The render-check document and its Hancom
reference (`render-check-01.hwpx` / `.pdf`) are touched by both PRs —
#222 re-authors and re-pins them for the column-order fix, #223 re-pins
the equation-extent measurement on top of the pre-#222 bytes — so a
merge is not just a code convergence but a **re-pin** of shared reference
files. Until that lands, no single tree carries both "F49 `close`" and
"pages 10 vs 9" at once, and the true combined page count (does it reach
9/9, or does a residual remain even with both fixes?) is unmeasured.

Desktop and writer lines integrated cleanly this window: #221 stacks
linearly on #217 with no sibling to reconcile; #224 stacks linearly on
#189 (through #189's own base `claude/engine-e3-hancom-accept`) and reads
#222's commits only via read-only `git show`, not a merge, so it carries
no dependency conflict of its own — though it does depend on #222's
finding being correct, and #222 and #224 have not yet been measured
together as one tree either (#224's corpus/lint tests run against the
writer line's own state, not against #222's re-pinned render-check
document).

## 7. Next measurable research question

**Does Hancom drop a page on PDF export, or do we still over-reserve
somewhere?** With the equation mechanism fixed (#223) and the F49
mechanism reclassified as a document bug rather than a renderer bug
(#222), render-check runs 10 pages against Hancom's 9 — one page closer,
but the reference PDF itself is not a clean 9. #223's own body names it:
Hancom's automation reports `PageCount` 10 for a document whose exported
PDF has 9 pages (`convert`'s own document=10 / pdf=9 warning). Two
possibilities, not yet distinguished:

1. Hancom's PDF exporter silently drops or merges a page that its own
   internal layout still counts as 10 — in which case our renderer's 10
   would already match Hancom's *true* internal layout, and the "9"
   target is an export-path artifact, not a rendering target.
2. Our renderer still over-reserves somewhere the equation/object-line
   fixes did not reach, and 10 is a coincidence that happens to equal
   Hancom's own pre-export count rather than evidence of correctness.

Distinguishing these needs a probe on the reference export path itself
(does `com_backend.py convert`'s document/PDF page-count mismatch
reproduce on documents with no equations and no columns at all?) rather
than another renderer-side measurement — a different subsystem from the
line/object/equation metrics this and the prior two checkpoints closed.
Once #222 and #223 converge (§6), the same question should be re-asked on
the merged tree, since the merge itself may shift the count again.

## 8. Certification status

Every own-render result in this checkpoint — the section-head lint that
protects the writer line (#224), the F49 corpus correction (#222), the
equation-extent fix (#223), and the newly-editable own-rendered page
(#221) — remains **own-uncertified**. None of the four PRs' own bodies
claims certification; `pipeline/scripts/render_cert.py` still cannot
certify this renderer absent a PDF text layer, unchanged since
checkpoint-01.

#221 extends the user-visible consequence checkpoint-05/06 tracked: a
fresh install with **no Hancom PDF at all** (tier 3) can now be typed in
through the same `OperationPlan` path a certified install uses — seats,
caret and the ambiguity chooser all work on a page only this repo has
ever rendered. The tier-3 raster underneath that editing surface stays
`own-uncertified` (gap 35, explicitly not claimed closed by #221's own
body), so the gap this checkpoint closes is editing-on-uncertified-pages,
not certification of those pages themselves.
