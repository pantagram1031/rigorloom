# Checkpoint 16 — the class-B remainder traced to nine paragraphs, the advance residual measured per face, and a cell-inset bug closed with the biggest raster gain this line has recorded

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-15` (this
branch, `claude/docs-checkpoint-16`, is cut from `claude/docs-checkpoint-15`
and stays unmerged). Covers #265 (`claude/engine-e2-class-b-remainder`:
decomposes checkpoint 15's 320 class-B paragraphs — 232 of them inside a
table cell where the seat pass has no seat — into `d_container_y +
d_block_offset + d_seat + d_first_offset`, holding 320/320; own 0, inherited
through a seat 101, through a container 219; a root histogram attributes 224
of 320 to nine carrier paragraphs — `text_rebreak:width` 167 (seven carrier
paragraphs, Σ|dy| 7355 px across jumin/moel-2013/moel-2025/saeopja),
`forced_break` 28 (kstartup, 4687 px), `empty_paragraph` 29 (nrf, 2970 px),
`table_row_heights` 82 (moel-2025/saeopja, 519 px), `cell_valign` 14
(saeopja, 60 px); names the advance-width residual on `text_rebreak:width`'s
seven carriers as the largest single root, with no OWPML/KS X 6101 clause
defining glyph advance to check it against — no fix, costed proposal), #267
(`claude/engine-e2-advance-width`: measures our own advances against
Hancom's glyph positions in its own PDF, per face, not per class or size —
the bundled NanumMyeongjo standing in for 휴먼명조 sits at ratio 0.9536
(n=2312, −60 HWPUNIT/char), every installed face at 1.0000; Hancom's own
Hangul advance is the declared point size rounded to a 1/600-inch grid;
finds two of #265's seven "advance" carriers, jumin and saeopja, are not
advance failures at all but cell-geometry failures — the text column is 631
HWPUNIT narrower (jumin) / 803 wider (saeopja) than the cache's `horzsize` —
reclassifying 3 of #265's 320 class-B paragraphs; measurement only, no
renderer change), and #268 (`claude/engine-e2-cell-column`: fixes the bug
#267's reclassification pointed at — a cell's text inset is the table's
`hp:inMargin` unless the cell itself declares `hasMargin="1"`; 1553 of the
corpus's 1609 cells declare `hasMargin="0"` and were being read through their
own `hp:cellMargin` instead; cells exact against cached `horzsize` 63 → 322
of 1599, within 8 HWPUNIT 716 → 1406; corpus cache `ssim_inked` 0.2766 →
0.3283, line IoU 0.6453 → 0.6729, computed 0.2773 → 0.3246 / 0.6339 →
0.6595 — the biggest raster gain this renderer line has recorded — page
counts and `lineseg_vs_pdf` 411/411 unchanged; class-B rises 320 → 350,
explained as re-breaking inside the now-correctly-narrower column that an
over-wide column had been absorbing; track-solve residuals on tables whose
rows declare contradictory totals, and a 4-HWPUNIT grid on `horzsize`, both
recorded as bands, not fixed; this is the renderer tip). Desktop (#266)
re-merges onto the renderer tip *as of #265* (one slice behind this
checkpoint's own renderer tip, #268): no textual conflict and no fix
needed — `class_b_probe.py` consumes paragraph addresses through the tracing
path #262 already fixed, so the merge-only clash from checkpoint 15 does not
recur; every reported suite 0 failed; GUI smoke was **not run** (C: fell
from 4.5 to 3.6 GB during the gates on a 99 %-full disk, and a Tauri release
build plus NSIS bundling stages scratch files on C regardless of the
cargo/npm redirection to F:, so building was judged unsafe). Two gates left
pending at checkpoint 15 — #262's post-fix `engine/tests` re-run and #263's
full `pipeline/tests` gate — both landed this window, both green. Writer
line (#224 → #235 → #238 → #239) and runtime line (#204) did not move this
window.

## What changed since checkpoint-15

| metric | checkpoint-15 | checkpoint-16 | moved in |
|---|---|---|---|
| renderer-line tip | #263 (`647e5f0`) | **#268** (`0241864`) — a linear three-PR extension: #265 → #267 → #268 | #265, #267, #268 |
| the 320 class-B paragraphs left after the PERCENT fix | unattributed | **attributed**: own 0, inherited through a seat 101 / through a container 219; nine carrier paragraphs explain 224 of 320 (`text_rebreak:width` 167, `forced_break` 28, `empty_paragraph` 29, `table_row_heights` 82, `cell_valign` 14); the largest root, `text_rebreak:width`, is named as an advance-width residual with no fix | #265 |
| the advance-width residual named by #265 | named, unmeasured | **measured per face**: bundled NanumMyeongjo standing in for 휴먼명조 at 0.9536 vs installed faces at 1.0000 (8377 anchored advances); Hancom's own Hangul advance = declared point size rounded to a 1/600-inch grid (contradicted once, 28 pt); 2 of #265's 7 "advance" carriers (jumin, saeopja) reclassified as cell-geometry failures, not advance — 3 of 320 class-B paragraphs mislabelled by #265 accordingly; still no fix, a costed proposal | #267 |
| cell text inset | not modelled as its own bug | **found and fixed**: 1553/1609 corpus cells declare `hasMargin="0"` and were read through their own `hp:cellMargin` where the table's `hp:inMargin` should apply; cells exact vs cached `horzsize` 63 → 322 (of 1599), within 8 HWPUNIT 716 → 1406 | #268 |
| corpus raster, 144 dpi (cache: ssim / ssim_inked / IoU / pair, pages exact) | 0.8311 / 0.2766 / 0.6453 / 0.8364, 52 | **0.8420 / 0.3283 / 0.6729 / (pair unchanged)**, 52 — largest raster gain this line has recorded; computed 0.8243 / 0.2773 / 0.6339 → 0.8336 / 0.3246 / 0.6595 | #268 |
| seat-pass class-B paragraphs | 320 | **320 → 350** — rose, explained: the now-correct narrower cell column re-breaks text an over-wide column had been absorbing (`table_row_heights` 82 → 109, `cell_valign` 14 → 17, concentrated on moel-2013 as moel-2025 falls); `text_rebreak:width` unchanged at 167 | #268 |
| desktop line | #262, one slice behind renderer tip #263 | **#266** re-merges onto the renderer state as of #265 — one slice behind this checkpoint's tip (#268); no conflict, no fix needed (the #262 address-dict fix already covers the new tracing consumer); GUI smoke still **not run**, now blocked on disk falling to 3.6 GB during the gate run itself | #266 |
| #262's post-fix `engine/tests` re-run (pending at checkpoint-15) | promised "appended below," not posted | **landed and green**: 1441 passed / 135 skipped / 0 failed; the 3 failed + 21 errors from the merge are gone; `tests` 1095/0 and `pipeline/tests` 1437/0 from the merge commit stand; GUI smoke still not run | — (comment on #262) |
| #263's full `pipeline/tests` gate (pending at checkpoint-15) | promised "appended below," not posted | **landed and green**: `tests` 486 passed / 3 skipped / 0 failed; `pipeline/tests` 1437 passed / 8 skipped / 0 failed; 0 failed overall | — (comment on #263) |
| development-validation document, aggregate only, under #268 | — | **byte-identical, both policies** vs the #267 tip: cache 0.6964 / 0.1834 / 0.5667 / 0.9150, computed 0.6108 / 0.0982 / 0.2294 / 0.7793 — the corpus's cell-inset gain does not transfer, because that document's tables either declare `hasMargin="1"` or carry margins equal to the table's own; read as consistent with an attribute-handling correction, not a tuning | #268 |
| writer line | unmoved since checkpoint-06 | **still unmoved** | — |
| runtime line | unmoved since checkpoint-06 (#204) | **still unmoved** | — |

## 1. Branch DAG

Renderer line, still a straight chain off checkpoint-15's tip — no siblings,
no merge this window on the renderer side itself:

| PR | branch | base | slice |
|---|---|---|---|
| #263 | `claude/engine-e2-percent-residual` | `claude/engine-e2-empty-paragraph-height` | renderer tip at checkpoint-15 (`647e5f0`) |
| #265 | `claude/engine-e2-class-b-remainder` | `claude/engine-e2-percent-residual` (#263) | decomposes the 320 class-B paragraphs into a root histogram over nine carrier paragraphs; own 0, inherited seat 101 + container 219; names the advance-width residual on `text_rebreak:width`'s seven carriers, no fix |
| #267 | `claude/engine-e2-advance-width` | `claude/engine-e2-class-b-remainder` (#265) | measures own advances against Hancom's PDF glyph positions per face; reclassifies 2 of #265's 7 "advance" carriers (jumin, saeopja) as cell geometry; measurement only, `own_render.py` byte-identical |
| **#268** | `claude/engine-e2-cell-column` | `claude/engine-e2-advance-width` (#267) | **fixes the cell-inset bug #267's reclassification pointed at: text inset = table `inMargin` unless the cell declares `hasMargin="1"`; this is the renderer tip (`0241864`).** |

Desktop line: one new PR this window, forked from #265 — one slice behind
the renderer's own tip (#268).

| PR | branch | base | note |
|---|---|---|---|
| #266 | `claude/desktop-on-renderer-265` | `claude/desktop-on-renderer-261` (#262) | re-merges the desktop onto the renderer chain through #265 (#263 → #265, on top of #262); no textual conflict, **no fix needed** — `class_b_probe.py` consumes paragraph addresses through the tracing path #262 already fixed; GUI smoke **not run** |

Docs line: no new docs PR this window (this checkpoint document itself is
the docs-line artifact).

Writer line, unchanged from checkpoint-15 — still #224 → #235 → #238 →
#239, no new PR this window.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` (each off its own window's renderer tip).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #265 — the remaining class-B paragraphs descend from nine carrier paragraphs

**Path B vs path A on the public corpus, 144 dpi; path C NOT RUN. No
renderer change.**

**New instrument.** 232 of the 320 class-B paragraphs sit inside a table
cell, where the seat pass has no seat of its own.
`engine/scripts/class_b_probe.py` splits each paragraph's first-line `dy`
into `d_container_y + d_block_offset + d_seat + d_first_offset`, read off
the arguments the renderer passed under each policy; the identity holds
320/320.

**Inheritance vs own.** Inherited through a seat: 101. Through a container:
219. **Own: 0** — no class-B paragraph mis-seats its own first line; class B
is entirely downstream of something else.

**Root histogram (paragraphs, Σ|dy| px).** `text_rebreak:width` **167**,
7355 px (jumin 1 / moel-2013 22 / moel-2025 142 / saeopja 2) ·
`forced_break` 28, 4687 px (kstartup) · `empty_paragraph` 29, 2970 px (nrf)
· `table_row_heights` 82, 519 px (moel-2025 28 / saeopja 54) · `cell_valign`
14, 60 px (saeopja). **224 of 320 descend from nine paragraphs.**

**Top mechanism.** A text paragraph whose computed line breaker gives a
different line count than Hancom's; seven carrier paragraphs hold all 167.
Six break earlier, one later. Three of the seven resolve every run to the
declared, installed face (96 of 135 class-A lines are installed-only), so
font substitution is not the cause — it is the advance width itself: the
measured glyph advances differ from Hancom's by enough to move a break. No
OWPML / KS X 6101 clause defines glyph advance and `hp:lineseg` cannot score
one. **No fix — costed proposal.** Also costed: nrf's unattributed +102.40
px is 2 × 2560, two empty paragraphs the cache seats at vertpos 71630
against a 71436 body box that the flow pass pages.

**Measured — nothing moved.** cache 0.6453 / 0.8311 / 0.2766 / 0.8364,
computed 0.6339 / 0.8243 / 0.2773 / 0.8478; page counts unchanged (cache
kstartup 21/22, computed 22/22); divergence classes 1371 / 135 / 320 / 233
before and after; render-check-01 6·37·6·2 at 96 dpi, 14·31·4·2 at 144, 9/9.

**Evidence.** probe tests 18 passed; engine/tests 1460 passed / 135 skipped;
pins + package + cleanroom + floors 170 passed; `py_compile_sweep` 110/0;
archive privacy HARD=0. **Full gate on this tip (`59c9ab9`):** `tests` 483
passed / 7 skipped / 0 failed (6m15s); `pipeline/tests` 1435 passed / 10
skipped / 0 failed (10m35s). 0 failed overall.

**Not proven.** The advance-width residual is named, not solved;
`text_rebreak:tab` has no witness; table-origin recursion goes one level
deep; the root is the largest step, not the only one; class C and
page-moved paragraphs are outside this population.

### #267 — our advances against the glyphs Hancom actually drew

**Measurement only; `own_render.py` byte-identical. Path A + reference PDF
as oracle (#258 established the export reproduces the save); path C NOT
RUN.**

**Method correction first.** Hancom does not draw every character — 4013 of
ours reach the PDF only as pen moves between text-showing runs, so the
comparison is anchor-to-anchor over the same characters
(`engine/scripts/advance_probe.py`).

**Ratio ours/Hancom (8377 anchored advances, top rows).** NanumMyeongjo
(bundled) standing in for 휴먼명조, 13 pt Hangul, n=2312: **0.9536** (p10
0.9449 / p90 0.9536; −60 HWPUNIT/char) · H2MJSM → 휴먼명조 13 pt space,
864: 1.0036 · batang.ttc → Batang 12 pt Hangul, 282: **1.0000** · H2GPRM →
H2gprM, 108: 1.0000 · malgun → MalgunGothic space, 90: 1.0000 · fallback →
T2 13 pt digit, 101: 1.1056. Per line: installed-only faces, 103 lines,
median |Δwidth| **56.57** HWPUNIT (20 within 2); substituted faces, 308
lines, **256.69** (2 within). The residual is per face — the bundled
fallback's narrower Hangul, exactly the nrf mechanism #242 costed.

**Rounding hypotheses (411 comparable lines, exact width matches).** none 22
· 1 HWPUNIT 22 · 4 HWPUNIT 22 · 1/64 pt 16 · 96-dpi px 5 · 144-dpi px 9 ·
**600-dpi px = 12 HWPUNIT: 31** · 1/600 in cell + truncate 16 (worst).
Hancom's own advances sit on the 12-HWPUNIT grid 30.86 % of the time vs
0.83 % by chance; its Hangul advance is the declared size rounded to 1/600
in (13 pt → 1296, 14 pt → 1404, 20 pt → 2004), its space that value halved
and truncated (15 pt → 744). Contradicted once at 28 pt (234 vs predicted
233, n=5).

**The seven carriers, attributed.** jumin 46 and saeopja 166 are **not**
advance failures — every cached line fits our own measurement (0.9906 /
0.9942 of the cell); the text column is **631 HWPUNIT narrower** (jumin)
and **803 wider** (saeopja) than the cache's `horzsize`. That is cell
geometry, and #265 mislabelled 3 of its 320 accordingly. moel-2013 118/141
over-measure by 1165/815, driven by punctuation (`fw_punct` +2469, `punct`
+1768). moel-2025 6/37 over by 180 (the grid would fix it); moel-2025 241
over by 27 (the grid worsens it).

**Rule stated, not shipped.** A cache-only score now exists: 51 of 2272
cached lines exceed their own `horzsize` under our measurement (proven
over-measurement). The 12-HWPUNIT grid closes 4 of them and opens 2 — not
enough to ship on; recorded as a costed proposal beside the full-width-
advance rule from #242.

**Before/after identical (nothing changed).** cache 0.6453 / 0.8311 /
0.2766 / 0.8364, 9/10 page-exact; computed 0.6339 / 0.8243 / 0.2773 /
0.8478, 10/10; divergence 1371 / 135 / 320 / 233; `lineseg_vs_pdf` 411/411;
render-check-01 6·37·6·2 at 96 dpi, 14·31·4·2 at 144, 9/9.

**Evidence.** `py_compile_sweep` 111/0; engine/tests 1490 passed / 135
skipped; pins + package + cleanroom + floors 170 passed; archive privacy
HARD=0. **Full gate on this tip (`c9e608f`):** `tests` 488 passed / 3
skipped / 0 failed (6m54s); `pipeline/tests` 1437 passed / 8 skipped / 0
failed (8m28s). 0 failed overall.

**Not proven.** 66 of 477 lines excluded as justified-stretched and
"JUSTIFY does not stretch a last line" is assumed; advances are read
through MuPDF's reconstruction; Latin/Hanja/other total 47 characters; one
moel-2025 match is a text search returning a line wider than its box; this
machine's font set drives the substitution numbers.

### #268 — a cell's inset is the table's `inMargin` unless the cell overrides it

**Path A oracle (cached `horzsize`) on the public corpus; path C NOT RUN.
The biggest raster gain this line has recorded.**

**Probe.** `engine/scripts/cell_column_probe.py` compares, for every `hp:tc`
with cached linesegs, the text-column width against the cache's `horzsize`,
and fits the delta against cell margin, `inMargin`, borders, `cellSpacing`,
colSpan and the track solve. Corpus: 1609 cells; **1553 declare
`hasMargin="0"`**, and for those the renderer was reading the cell's own
`hp:cellMargin` (e.g. 510/510) where the table's `hp:inMargin` (283/510)
was in force. Basis: the HWP 5.0 table record's default cell margin plus
the per-cell override flag.

**Fix.** `own_render.cell_inset`, all four sides; 7 synthetic-table tests.
Cells exact against `horzsize`: **63 → 322**; within 8 HWPUNIT **716 →
1406** of 1599. Per form (compared / exact / off, dominant residual):
admrul 16/5/11 (+1 grid) · gianmun-1ho 34/6/28 (+2) · gianmun-2ho 51/13/38
(+1) · jeongbo 70/16/54 (+1) · jumin 85/10/75 (**−683 track solve**) ·
kstartup 366/50/316 (+3; −156 × 60 track) · moel-2013 69/13/56 (+1) ·
moel-2025 102/7/95 (+1) · nrf 32/12/20 (+3) · saeopja 784/9/775 (+2).

**The two named cells.** jumin p46 −631 = −227 (the margin bug) − 407
(track solve: the row declares 43561 for tracks summing 43968) + 3 (grid);
now −404. **saeopja p166 was never cell geometry**: its cell is right to 3
HWPUNIT; #267's +803 is that paragraph's own `margin_left` 400 +
`margin_right` 400 + 3, with only line 0 disagreeing (+403) through
`_line_box`'s negative-intent reading — recorded.

**Measured, 144 dpi, corpus means (ssim / ssim_inked / IoU, pages exact).**
cache 0.8311 / 0.2766 / 0.6453, 52 → **0.8420 / 0.3283 / 0.6729**, 52;
computed 0.8243 / 0.2773 / 0.6339, 53 → **0.8336 / 0.3246 / 0.6595**, 53.
Every form improved or held; no page count moved; largest mover
gianmun-2ho inked 0.0563 → 0.3621. `lineseg_vs_pdf --corpus` 411/411 before
and after. Divergence classes 1371 / 135 / 320 / 233 → 1350 / 118 / **350**
/ 243 — class B rose because the now-correct narrower column re-breaks text
an over-wide column was absorbing (`table_row_heights` 82 → 109,
`cell_valign` 14 → 17, concentrated on moel-2013 as moel-2025 falls);
`text_rebreak:width` 167 → 167 unchanged. render-check-01 unchanged
(6·37·6·2 / 14·31·4·2, 9/9).

**Not fixed, recorded as bands.** The track model (`solve_tracks` forces
one column set on tables whose rows declare contradictory totals — jumin
table 1 declares 50897 and 48067 for the same five columns; residuals
jumin −683 × 19, kstartup −156 × 60, gianmun-1ho −874 × 2, saeopja
+13…+20 × 132) and the 4-HWPUNIT grid on `horzsize` (3164/3177 cached
values are multiples of 4; ≤ 3 units).

**Development-validation document (private, reused; aggregate only), 96
dpi, #267 tip vs this tip, both policies: byte-identical.** cache ssim
0.6964 / ssim_inked 0.1834 / line IoU 0.5667 / pair 0.9150; computed 0.6108
/ 0.0982 / 0.2294 / 0.7793 — unchanged to six decimals. The corpus gain
does not transfer there: that document's cells do not take the `inMargin`
default (its tables either declare `hasMargin="1"` or carry margins equal
to the table's own), consistent with the fix being an attribute-handling
correction rather than a tuning.

**Evidence.** `py_compile_sweep` 112/0; engine/tests 1497 passed / 135
skipped; pins + package + cleanroom + floors 170 passed; archive privacy
HARD=0. **Full `pipeline/tests` gate: stated in the dev-validation comment
as "running at time of writing" and "appended when done" — as of this
checkpoint no further comment has landed on #268. Do not read as green.**

**Not proven.** `cellSpacing`/border insets (the corpus declares 0
everywhere); 10 ragged cells excluded from the fit; the `hasMargin="1"` arm
rests on 56 cells; no reference render confirms the inset directly (the
raster gain is the indirect witness).

### #266 — desktop re-merge onto the renderer tip #265

**The desktop line on the renderer tip #265** (#263 PERCENT leading grid,
#265 class-B probe, on top of #262). One merge commit, no conflicts, no fix
needed: `class_b_probe.py` consumes paragraph addresses through the tracing
path #262 already fixed, so the address-dict clash named in checkpoint 15
does not recur.

**Evidence (merged tree, one suite at a time).** `py_compile_sweep` 136/0;
engine/tests 1467 passed / 135 skipped / 0 failed; `tests` 1090 passed / 7
skipped / 0 failed; `pipeline/tests` 1437 passed / 10 skipped / 0 failed;
archive privacy HARD=0 (WARN 55: fonts + fixture IDs). Reported directly in
the PR body — no separate "appended below" comment was needed this time.

**Desktop GUI smoke: NOT RUN.** C: fell from 4.5 to 3.6 GB during the gates
on a 99 %-full disk; a Tauri release build plus NSIS bundling stages
scratch files in `%TEMP%` on C regardless of the cargo/npm redirection to
F:, so building was judged unsafe. The claim "the app built from this tree
renders and edits" stays open until a build from this sha runs the smoke. A
pre-built exe smoke is not cited.

**Stated, not done.** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248; ownership per #253).

**Depends on:** #262 (desktop) and #265 (renderer). Merge: Sonnet;
orchestrator: Fable. No comments on this PR as of this checkpoint.

## 3. The development-validation document, this window

Aggregate-only, no name or text from the document quoted anywhere below —
this is the same private, repeatedly-reused holdout named in prior
checkpoints, not independent unseen data. Only #268 touched it this window
(#265 and #267 are measurement-only diagnostics with no renderer change to
re-run against it).

**#268:** byte-identical to six decimals against the #267 tip, both
policies — cache ssim 0.6964 / ssim_inked 0.1834 / IoU 0.5667 / pair 0.9150;
computed 0.6108 / 0.0982 / 0.2294 / 0.7793, unchanged. The corpus's
cell-inset gain (ssim_inked 0.2766 → 0.3283) does not transfer to this
document because its own tables either declare `hasMargin="1"` explicitly
or carry cell margins already equal to the table's own — cases the
`inMargin`-default fix does not touch by construction. Read as supporting
evidence that #268 is an attribute-handling correction, not a fit tuned to
the corpus: a tuning would have been expected to move this document too,
and it did not move at all.

This window did not re-open the document's own long-standing residuals —
the 5 one-line-shorter export paragraphs, the 40 ±1 character-split
paragraphs (#258, survived #260 unchanged, font-resolution hypothesis
still untested), or the +1800 page-top drift (#257) — none of #265, #267
or #268 touches those mechanisms.

## 4. Regressions (with the PR's or commit's own explanation)

**None newly introduced this window, by the PRs' own accounting.** #268's
class-B count rising 320 → 350 is the one number that moves against the
grain of "the fix improved things," and the PR states its own explanation:
the corrected, narrower cell column now forces re-breaks that the old,
over-wide column had been silently absorbing — `table_row_heights` 82 →
109 and `cell_valign` 14 → 17, concentrated on moel-2013 as moel-2025
falls, while every raster and page-count metric moved toward the cache or
held. #265 and #267 report zero raster or page-count movement by
construction (measurement-only PRs). #266's merge had no conflicts and no
fix was needed, so nothing to regress on the merge step itself.

## 5. Unsupported / declared elements still open

Carried from checkpoint-15, with this window's closures, redirections and
new items:

- **Closed since checkpoint-15:** #262's post-fix `engine/tests` re-run,
  promised "appended below" — now landed, green (1441 passed / 135 skipped
  / 0 failed, the merge's 3 failed + 21 errors gone). #263's full
  `pipeline/tests` gate, promised "appended below" — now landed, green
  (`tests` 486/3/0, `pipeline/tests` 1437/8/0). Neither is a change to this
  window's own renderer line, but both were open items at checkpoint-15 and
  are now closed.
- **Found and fixed this window:** the cell-inset bug (#268) — cell text
  inset was being read from the cell's own `hp:cellMargin` instead of the
  table's `hp:inMargin` on 1553 of 1609 corpus cells; fixed, 63 → 322 cells
  exact against `horzsize`.
- **Reclassified, not closed:** 2 of #265's seven "advance-width" carrier
  paragraphs (jumin, saeopja), 3 of its 320 class-B paragraphs — #267 shows
  these are cell-geometry failures, not advance, redirecting to and
  motivating #268's fix.
- **New, named and measured, still open:** the advance-width residual
  itself (#265, measured per face by #267) — the bundled NanumMyeongjo
  fallback's Hangul advance sits at 0.9536 of Hancom's own, every installed
  face at 1.0000; Hancom's own Hangul advance appears to be the declared
  point size rounded to a 1/600-inch grid (one contradiction at 28 pt); no
  fix, a costed proposal, and the seven `text_rebreak:width` carrier
  paragraphs (167 of the 320 class-B paragraphs) remain the largest
  unattributed root.
- **New, recorded as bands, not fixed:** the track-solve model on tables
  whose rows declare contradictory totals (jumin −683 × 19, kstartup
  −156 × 60, gianmun-1ho −874 × 2, saeopja +13…+20 × 132); the 4-HWPUNIT
  grid on cached `horzsize` (3164/3177 values, ≤ 3-unit residual).
- **New, explained not fixed:** class-B rising 320 → 350 under #268 (see
  §4) — the composition of the remainder has changed, not just its size,
  and is itself the likely next place to decompose.
- **Unchanged from checkpoint-15, still fully open:** the page-bottom
  fit-rule candidate (`vertsize − spacing`, #256/#260) — still a costed
  proposal with no public witness, still needs a Hancom round-trip and COM
  ownership agreement not yet in place; the development-validation
  document's 5 line-count and 40 character-split discrepancies and their
  font-resolution hypothesis (#258/#260) — not touched this window;
  computed layout's own +1800 page-top drift against that document's PDF
  (#257) — not addressed this window; the paragraph-before-the-drift
  "predecessor draws nothing" mechanism (#252) — one boundary case (nrf),
  not generalized; the desktop's build-from-merged-source GUI smoke
  evidence — still does not exist, still blocked on disk space (now worse:
  4.5 → 3.6 GB during #266's own gate run); the `LayoutSnapshot` contract
  and `x1` glossary (#253) — no response recorded this window;
  `layout_policy`/`layout_policy_reason` still not surfaced in the desktop
  UI; the acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item); Codex-app-closed sessions moved; Cursor login.
- **New, owed:** #268's full `pipeline/tests` gate — stated as running at
  time of writing and "appended when done," not yet landed as a comment as
  of this checkpoint; must not be read as green.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #265 | probe tests 18 passed; engine/tests 1460/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 483/7/0 + `pipeline/tests` 1435/10/0 — 0 failed overall** | `py_compile_sweep` 110/0; archive privacy HARD=0 |
| #266 | engine/tests 1467/135/0; `tests` 1090/7/0; `pipeline/tests` 1437/10/0 — reported directly in the PR body (merged tree, one suite at a time) | **same figures, 0 failed** — no separate comment needed | `py_compile_sweep` 136/0; archive privacy HARD=0 (WARN 55: fonts + fixture IDs); GUI smoke NOT RUN |
| #267 | engine/tests 1490/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 488/3/0 + `pipeline/tests` 1437/8/0 — 0 failed overall** | `py_compile_sweep` 111/0; archive privacy HARD=0 |
| #268 | engine/tests 1497/135 skipped; pins+package+cleanroom+floors 170 | **stated as running at time of writing, "appended when done" — not yet posted as a further comment; NOT CLAIMED GREEN** | `py_compile_sweep` 112/0; archive privacy HARD=0 |

Two gates left pending at checkpoint-15 landed this window as comments, both
green: #262's post-fix `engine/tests` re-run (1441/135/0) and #263's full
`pipeline/tests` gate (`tests` 486/3/0, `pipeline/tests` 1437/8/0). #268 is,
at the time this checkpoint was written, the one PR in this line whose full
gate is **not yet confirmed** by a posted comment.

## 7. Integration conflicts expected when lines converge

**Renderer line did not converge siblings this window — it extended
linearly**, same shape as checkpoint-14 and -15: #265, #267 and #268 each
forked from the immediately preceding PR, so there was no renderer-side
merge to perform and no textual or semantic conflict between them.

**Desktop converged onto the renderer chain again this window (#266)** —
the one integration event of this checkpoint, and unlike #262 it surfaced
**no** conflict and needed **no** fix: `class_b_probe.py`'s paragraph
addressing goes through the same tracing path #262 already repaired, so the
clash named in checkpoint-15 did not recur. Desktop remains **one**
renderer slice behind the tip: it merged through #265, and #267/#268
landed after.

**Writer and renderer lines remain unconverged**, unchanged from
checkpoint-15.

**Runtime line is untouched and unconverged with anything**, unmoved since
#204 (checkpoint-06).

## 8. Next measurable research question

**The track solve on tables whose rows declare contradictory totals, the
bundled-face advance rule as a costed proposal, and the page-fit rule
witness via a Hancom round-trip — in that order, as named by #268, #267 and
#260/#265 themselves.** #268 leaves the track-solve residual unattributed
on the tables whose row declarations disagree with their own column sums
(jumin −683 × 19, kstartup −156 × 60, gianmun-1ho −874 × 2, saeopja
+13…+20 × 132) — the next concrete fix candidate, since it is bounded and
already isolated by form. Second, #267's per-face advance ratios (bundled
NanumMyeongjo 0.9536 vs installed faces 1.0000, Hancom's own Hangul advance
on a 1/600-inch grid) are measured but not shipped as a rule — confirming
or rejecting the grid rule against more of the corpus, and deciding whether
to apply the bundled-fallback ratio, are both open. Third, #260's restored
path-A "+566" witness for `vertsize − spacing` and #265/#268's own class-B
remainder both still point at the same unresolved need: a Hancom round-trip
of the same package, which requires COM ownership agreement not yet in
place. None of the three is measured yet this window. Separately, computed
layout's own +1800 page-top drift against the development-validation
document's PDF (#257) and its 5-line/40-split font-resolution hypothesis
(#260) remain open and untouched.

## 9. Certification status

Every result in this checkpoint — #265 (class-B decomposition, measurement
only), #267 (advance probe, measurement only), #268 (cell-inset fix), #266
(desktop re-merge, no fix) — remains **own-uncertified**. Of this window's
four PRs, only #268 changes `own_render`'s behavior; #265 and #267 are
diagnostics with `own_render.py` byte-identical, and #266 is a merge with
no fix commit. None changes a certified renderer surface. `render_cert.py`
still cannot certify this renderer absent a PDF text layer, unchanged since
checkpoint-01.

**What moved, restated plainly:** this window took the 320 unattributed
class-B paragraphs left after checkpoint-15's PERCENT fix, decomposed them
to nine carrier paragraphs (#265), measured the largest of those roots —
advance width — directly against Hancom's own PDF glyph positions per face
(#267), and in doing so found and fixed a real bug: 1553 of 1609 corpus
cells were reading the wrong margin source for their text inset (#268),
producing the single largest raster gain this renderer line has recorded
(`ssim_inked` 0.2766 → 0.3283, IoU 0.6453 → 0.6729) while explicitly
reporting and explaining the one number that moved the wrong way (class B
320 → 350, re-breaking inside a now-correctly-narrower column). Two gates
left pending at checkpoint-15 landed this window, both green, closing two
items that had been sitting unconfirmed. The desktop line converged onto
the renderer chain a second time (#266) with, this time, no conflict and no
fix required — a sign the #262 fix was durable — but its GUI smoke evidence
still does not exist, and the reason has gotten worse (disk fell further
during the gate run itself). One PR in this window (#268) has a gate result
promised in its own comment thread but not yet posted in full; it is
recorded here as pending, not green.

**Owed, carried forward from checkpoint-15, plus this window's additions:**

- The track-solve residual on tables whose row totals contradict their own
  column sums (jumin −683 × 19, kstartup −156 × 60, gianmun-1ho −874 × 2,
  saeopja +13…+20 × 132) — named, costed, not fixed (#268).
- The bundled-face advance rule (0.9536 for NanumMyeongjo standing in for
  휴먼명조) and the 1/600-inch Hangul-advance grid — measured, not shipped
  (#267).
- Class B's new composition after #268 (320 → 350) — explained, not yet
  decomposed the way #265 decomposed the prior 320.
- A public path-A witness for the `vertsize − spacing` page-bottom fit
  candidate (#260, #256) — needs a Hancom round-trip, needs COM ownership
  agreement not yet in place.
- The development-validation document's font-resolution hypothesis for its
  5 line-count and 40 character-split discrepancies (#260) — consistent,
  not tested; not touched this window.
- Computed layout's own +1800 page-top drift against the development-
  validation document's Hancom-exported PDF (#257) — unresolved, untouched
  this window.
- #268's full `pipeline/tests` gate — stated as running at time of writing,
  not yet posted in full; not to be treated as green until it lands.
- The desktop's build-from-merged-source smoke evidence (#248, #262, #266)
  — does not exist yet; blocked on disk space, which worsened this window.
- The `LayoutSnapshot` proposal (#253) — no response recorded this window;
  no level-C run exists anywhere.
- `layout_policy`/`layout_policy_reason` surfaced in the desktop UI — still
  not a branch or PR.
- The paragraph-before-the-drift "predecessor draws nothing" mechanism
  (#252) — one boundary case (nrf), not generalized.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.
