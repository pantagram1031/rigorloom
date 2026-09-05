# Checkpoint 18 — the two renderer siblings converge twice over, every corpus form goes page-exact under both policies, and cache line IoU clears 0.73

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-17` (this
branch, `claude/docs-checkpoint-18`, is cut from `claude/docs-checkpoint-17`
and stays unmerged). Covers #275 (`claude/engine-e2-cell-residuals`: a cell's
text column is never narrower than 1440 HWPUNIT — `column := max(box − inset,
1440)` — attributing 63 of the 66 non-column cell residuals #270 left open,
with the remaining 3 read as a paragraph-indent case; `cell_column_probe`
exact/near 322/1406 → 385/1470 of 1599, 0 regressions; rescores #272's
gridfirst column model from 94.9 % to 98.9 %, one point under its own 99 %
gate; not itself a shipped column model), #276 (`claude/engine-e2-table-
overflow`: `hp:sz@height` is a ceiling too — the excess comes off the last
row; read from Hancom's own PDF, since both overflow tables are anchored and
invisible to the cache oracle; fixes `clip_tracks`, recovering a third of
#273's stated computed-line-IoU cost on saeopja), #277 (`claude/engine-e2-
gridfirst`: **gridmax**, shipped — a cell's `cellSz@width` is a lower bound
and each column boundary takes the largest claim any cell makes for it; first
finds and fixes a probe-scoring bug in #270/#272's shift-based comparison
that had manufactured a false regression; 99.4 % of the cache grid, 0
regressions, PDF vertical-rule recall 263 → 303), #278 (`claude/engine-e2-
table-pagination`: exactly one corpus table is split by Hancom (kstartup
tbl9), read off the reference PDF; `pageBreak="CELL"` cuts through a cell,
`NONE` moves the table whole; kstartup's missing cache page was never that
split — an anchored table was being drawn off the page instead of moved
whole; fixing the move-whole arm brings **all ten corpus forms to the
reference's page count under both policies**), #279 (`claude/engine-e2-
hanging-indent`: `hh:intent` moves the text inside the paragraph box, not the
box itself — cached `horzpos == margin_left` on 3214/3214 lines; the first
line gets `+max(intent, 0)`, continuation lines `+max(−intent, 0)`, confirmed
13/13 first lines + 39/39 second lines against the PDF), #280 (mechanical
convergence of #277 + #278: three conflicts, all resolved keeping both
sides; cache page-count exact 10/10, line IoU 0.725) and #281 (convergence
of #280 + #279, **the renderer tip this window**: one text conflict,
resolved keeping both sides; cache ssim/ssim_inked/line IoU 0.8589/0.3739/
0.7372, pages 10/10; computed 0.8383/0.3372/0.6643, pages 10/10). Desktop
(#271) stays on renderer tip #268; a re-merge onto #281 is **in flight, not
landed this window**. Writer line (#224 → #235 → #238 → #239) and runtime
line (#204) did not move.

## What changed since checkpoint-17

| metric | checkpoint-17 | checkpoint-18 | moved in |
|---|---|---|---|
| renderer-line tip | **no single tip** — two open siblings off #270: #272 (diagnostic) and #273 (row-height compress fix), one-hop convergence owed | **single tip again, #281 (`8f0c399`)**, reached after five more research slices on the two sibling lines and two mechanical/textual convergence merges (#280 then #281) | #275, #276, #277, #278, #279, #280, #281 |
| non-column cell residuals (#270's 66) | unattributed | **63 attributed to a 1440-HWPUNIT text-column floor; 3 to a `margin_left`-only `horzpos` reading** (#275) | #275 |
| column-tiling model for shortfall-disagreeing tables | measured, not shipped: stretch 93.5 %, gridfirst 94.9 %, both below the 99 % gate | **shipped: gridmax, 99.4 % of the cache grid, 0 regressions** (#277); a probe-scoring bug that had manufactured a false "regression" on saeopja r3c6 is found and fixed in the same PR | #275, #277 |
| row-height rule | confirmed as a floor only (`max(declared, content+inset)`, #273) | **confirmed as a ceiling too**: excess comes off the last row, read from the PDF since the cache oracle cannot see either overflow table (#276) | #276 |
| table pagination / page counts | not modelled; kstartup cache short one page, cause unknown | **modelled and fixed**: exactly one corpus table splits (kstartup tbl9); the missing page was an anchored table drawn off-page, not the split; **all ten forms page-exact under both policies** (#278) | #278 |
| paragraph hanging indent (`hh:intent`) | not modelled | **modelled and fixed**: offset applies inside the paragraph box, not to the box; 3214/3214 lines confirmed on cache, 13/13 + 39/39 on the PDF (#279) | #279 |
| #272/#273 sibling convergence (owed since checkpoint-17) | not attempted | **done, in two hops**: #280 merges #277 (ex-#272 line) + #278 (ex-#273 line) mechanically; #281 merges #279 on top, textually | #280, #281 |
| corpus raster, 144 dpi, cache (ssim / ssim_inked / line IoU, pages exact) | 0.8421 / 0.3283 / 0.6730, 52/53 (#273's tip) | **0.8589 / 0.3739 / 0.7372, 10/10 forms** (#281's tip) | #275–#281 |
| corpus raster, 144 dpi, computed (ssim / ssim_inked / line IoU, pages exact) | 0.8334 / 0.3253 / 0.6562, 53/53 | **0.8383 / 0.3372 / 0.6643, 10/10 forms** | #275–#281 |
| desktop line | #271, one slice behind a renderer tip that itself had no single tip | **unchanged this window** — still #271 on #268; a re-merge onto #281 is **in flight, not landed** | — |
| writer line | unmoved since checkpoint-06 | still unmoved | — |
| runtime line | unmoved since checkpoint-06 | still unmoved | — |

For scale against a fixed point further back: #263 (checkpoint-15's renderer
tip) recorded cache 0.8311 / 0.2766 / 0.6453 with 9/10 forms page-exact. The
docs' earliest checkpoint on file, checkpoint-11, does not report this
ssim/ssim_inked/line-IoU triplet in any comparable form (the corpus-raster
aggregate table format was introduced later in this doc line), so no
"first checkpoint" figure exists to compare against — #263 is the earliest
baseline these checkpoints carry forward.

## 1. Branch DAG

Renderer line: **the two siblings forked at checkpoint-17 (#272, #273 off
#270) each extend once more, then converge in two hops.**

| PR | branch | base | slice |
|---|---|---|---|
| #272 | `claude/engine-e2-row-shortfall` | `claude/engine-e2-track-solve` (#270) | checkpoint-17's diagnostic sibling; `own_render.py` untouched |
| #273 | `claude/engine-e2-row-height` | `claude/engine-e2-track-solve` (#270) | checkpoint-17's fix sibling; row-height compress to floor-only |
| #275 | `claude/engine-e2-cell-residuals` | `claude/engine-e2-row-shortfall` (#272) | attributes the 66 non-column residuals to a 1440-HWPUNIT text-column floor (63) + a `margin_left`-only `horzpos` reading (3); rescores gridfirst to 98.9 % |
| #276 | `claude/engine-e2-table-overflow` | `claude/engine-e2-row-height` (#273) | `hp:sz@height` is a ceiling too; `clip_tracks` fix, read from the PDF |
| #277 | `claude/engine-e2-gridfirst` | `claude/engine-e2-cell-residuals` (#275) | **gridmax shipped** — largest-claim column grid, 99.4 % on the cache grid, 0 regressions; fixes the probe-scoring bug from #270/#272 |
| #278 | `claude/engine-e2-table-pagination` | `claude/engine-e2-table-overflow` (#276) | anchored-table move-whole fix; all ten forms page-exact under both policies |
| #279 | `claude/engine-e2-hanging-indent` | `claude/engine-e2-gridfirst` (#277) | `hh:intent` moves text inside the box, not the box; joins the #277+#278 convergence as one more hop |
| **#280** | `claude/engine-e2-converge-04` | `claude/engine-e2-table-pagination` (#278), merges in #277 | **mechanical convergence**: `own_render.py`, `own-render-notes.md`, `test_own_render.py` conflicts, all resolved keeping both sides; one renderer tip again |
| **#281** | `claude/engine-e2-converge-05` | `claude/engine-e2-converge-04` (#280), merges in #279 | **the renderer tip this window** (`8f0c399`); one text conflict in the notes file, resolved keeping both sides |

Desktop line: no new PR this window — #271 (`claude/desktop-on-renderer-268`)
is unchanged, still one slice behind the renderer's own tip. A re-merge onto
#281 is in flight (named in the STATUS-001 coordinator snapshot's
`next_action`) but has not landed as of this checkpoint.

| PR | branch | base | note |
|---|---|---|---|
| #271 | `claude/desktop-on-renderer-268` | `claude/desktop-on-renderer-265` (#266) | unchanged this window; still sits on renderer tip #268, five renderer slices behind #281; re-merge onto #281 **in flight, not landed** |

Docs line: no new docs PR this window besides this checkpoint document
itself.

Writer line, unchanged from checkpoint-17 — still #224 → #235 → #238 → #239.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` / `-16` / `-17` (each off its own window's
renderer state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #275 — a cell's text column is never narrower than 1440 HWPUNIT

**Path A oracle on the public corpus, 144 dpi; path C NOT RUN.**

**Attribution.** No residual cell carries a heading, bullet, tab, inline
object, vertical text or non-zero `cellSpacing`; two causes explain all 66:
(1) `column := max(box − inset, 1440)` — 63 cells: kstartup 60 (one table,
rows 2–6 × columns 1–12, cells 1566 wide, inset 141/141 → 1284, cache says
1440) and gianmun-1ho 3 (848 → 566 twice, 565 → 283); (2) `horzpos :=
margin_left only` — 3 cells (jumin +503/+502, saeopja +602), each a single
line with `margin_left` 500/500/600 and a negative first-line `intent` of
−1070/−1308/−2180.

**Rule.** A cell's text column is box − inset, never below **1440 HWPUNIT**
(0.2 in). Corpus-wide the smallest in-cell `horzsize` is exactly 1440, the
next 1696; 64 lines sit on it from four column widths and two text heights.
**Not a documented constant** — the corpus is its only witness.

**Fix.** `own_render.cell_text_width` / `MIN_CELL_TEXT_WIDTH`, called at both
content-width sites; 6 synthetic tests. The 3 indent cells: recorded, not
fixed.

**Measured, 144 dpi.** Scoreboard byte-identical both policies (cache
0.8420/0.3283/0.6729, 52/53; computed 0.8336/0.3246/0.6595, 53/53) — 61 of
64 lines are empty paragraphs, 3 hold one justified character, no ink moves.
`cell_column_probe` exact/near 322/1406 → **385/1470** of 1599, 0
regressions; residuals 66 → 3. `track_probe`: global 905 → 969 on grid,
**gridfirst 1518 → 1581 (94.9 % → 98.9 %)**, one point under its 99 % gate.

**Evidence.** `py_compile_sweep` 113/0; engine/tests 1503 passed/135
skipped; pins+package+cleanroom+floors 170; archive privacy HARD=0. **Full
gate, tip `3e0a170`:** `tests` 486/7/0 (5m46s) + `pipeline/tests` 1435/10/0
(8m56s), 0 failed overall.

**Not proven.** Floor on the column vs on the line box; 1440 has no public
citation; untested outside cells; the 3 indent cells; the "regression vs
global" it names on saeopja r3c6 (later shown by #277 not to exist at all —
a probe-scoring artifact); the corpus is the training set.

**Depends on:** #272.

### #276 — a table's declared height is a ceiling too; the last row pays

**Read from Hancom's PDF, since both overflow tables are anchored and the
cache oracle cannot see them.** Path A where it exists, the reference PDF
(scaled by its MediaBox ratio) where it does not; path C NOT RUN.

**The two kstartup overflows.** tbl5 (4 rows, declared 62482): rows declare
3682/19626/19626/19626 = 62560, the only table whose cell heights sum past
`sz@height`. tbl36 (2 rows, declared 66505): row 0 declares 58747 but holds
43 cached lines = 61680 + 280 inset = 61960; row 1 4827; Σ 66787. **The PDF
measures tbl5 at 62481 (declared 62482) and tbl36 at 66501 (declared
66505)**; uncompressed they would measure 62559/66717. tbl5's interior:
rows 0–2 measure 3690/19619/19631 (Δ+8/−7/+5) and row 3 measures 19541 —
"last row absorbs" predicts 19548 (Δ−7) against proportional's 19603
(Δ−62).

**Fix.** `own_render.clip_tracks`; `_table_tracks` clips on overflow only
(#273's floor arm untouched). 8 clips corpus-wide, each moving exactly one
row (tightest: saeopja 1040 off 1082). 3 tests.

**Paginated tables: the cache states nothing.** All 81 holders cache one
`hp:lineseg`; `repeatHeader="1"` on all 81; only kstartup tbl9 is split by
this render — the whole-table-lineseg pagination knot behind kstartup's
cache page count is untouched here (picked up by #278).

**Measured, 144 dpi.** cache 0.8421/0.3284/0.6730/0.8364, 52/53; computed
0.8335/0.3256/**0.6566**/0.8469, 53/53 — nothing falls; **saeopja line IoU
0.7268 → 0.7304, recovering a third of #273's stated cost.** `lineseg_vs_pdf`
411/411. Row probe: `max` 70/70; every non-natural solve now lands exactly
on `sz@height`. Roots: `table_row_heights` 64 → 64 with Σ|dy| 1387 → 1251 px;
classes 1395/118/302/243 unchanged.

**Evidence.** `py_compile_sweep` 114/0; engine/tests 1503 passed/135
skipped; pins170; privacy HARD=0. **Full gate, tip `fd148bd`:** `tests`
491/3/0 (6m55s) + `pipeline/tests` 1437/8/0 (8m46s), 0 failed overall.

**Not proven.** The last-row rule has one interior witness (tbl36's interior
boundary is `borderFill NONE`, only its total is measured); the shortfall
arm still has no witness; `repeatHeader` is unmeasurable (all "1"); the
whole-table-lineseg pagination knot remains.

**Depends on:** #273.

### #277 — a table's column grid takes the largest claim at every boundary

**Column model shipped: gridmax, 99.4 % on the cache grid, 0 regressions.**
Path A oracle; the reference PDF's vertical rules as the x oracle; path C
NOT RUN.

**A probe bug first.** #270/#272 scored models by shifting the rendered
residual; #275's 1440 floor is non-linear, so the shift lied on saturated
cells. Re-scoring through `cell_text_width` + `_line_box` gives gridfirst
1582 (not 1581) and **0 regressions vs the global solve** — the saeopja r3c6
"regression" never existed.

**The 18 misses (17 after the fix):** 5 are a paragraph `margin_left`
500/600 with a larger negative `indent` (+500/502/503/601/602, now
explained); 8 are saeopja's 47764-wide table, `x[17]`/`x[24]` off by 1
(row 22 sums exactly, claims 23736; row 20 is 739 short, claims 23735); 4
are saeopja's 48027 table rows 7/8, **still unexplained** (19 HWPUNIT, one
table).

| model | on grid / 1599 | regressions vs global | PDF vertical-rule recall / 1643 |
|---|---:|---:|---:|
| global solve (was) | 969 | 0 | 263 |
| stretch | 1559 | 0 | 305 |
| gridfirst | 1582 | 0 | 303 |
| gridlast / firstrow | 1561 | 0 | 305 |
| **gridmax** | **1590 (99.4 %)** | **0** | 303 |

**Rule.** One grid per table, ends pinned at 0 and `hp:sz@width`; every
interior boundary is the **largest** position any cell claims for it — no
tie-break. `own_render.column_grid` replaces `solve_tracks` on the column
axis only; rows untouched. 8 tests.

**Measured, 144 dpi.** cache 0.8420/0.3283/0.6729 → **0.8453/0.3359/0.6742**,
pages 52/53 unchanged; computed 0.8336/0.3246/0.6595 → **0.8366/0.3316/
0.6611**, 53/53. Only jumin (+0.018 ssim) and saeopja (+0.015) move, up on
all three metrics both policies; eight forms byte-identical. PDF rule recall
263 → 303. `cell_column_probe` exact/near 385/1470 → **401/1590** of 1599.

**Evidence.** `py_compile_sweep` 113/0; engine/tests 1511 passed/135
skipped; pins170; privacy HARD=0. **Full gate, tip `6d8aad1`:** `tests`
486/7/0 (5m39s) + `pipeline/tests` 1435/10/0 (11m59s), 0 failed overall.

**Not proven.** The 4 saeopja-48027 cells; gridmax was found on the 8 cells
it closes, so they are fitted; `stretch` still leads the x oracle by 2
strokes, both on saeopja page 6 in that same table; the overflow clamp is
untested; the corpus is the training set.

**Depends on:** #275.

### #278 — an anchored table that does not fit moves to the next page whole

**Every corpus form now has the reference's page count under both
policies; kstartup's lost cache page was never a table split.** Reference
PDF as oracle for where Hancom splits a table; path A for seats; path C NOT
RUN.

**How many tables Hancom splits: exactly one** (kstartup tbl9). PDF pages
6, 7, split row 2, boundary cut through the cell, no repeated header,
+146 continuation seat, fragments 70624/69543; cache before and after this
fix agree on the split geometry itself (row 3 = file row 2, at the row
boundary, +140 seat, fragments 70529/69505) — only the page numbers move,
from 5/6 to the correct 6/7. No form splits a table the renderer does not,
or vice versa.

**Rules.** `pageBreak="CELL"` cuts through a cell; `NONE` moves the table
whole. `repeatHeader="1"` repeated nothing, because `hp:tr@header` is
absent on all 514 corpus rows — the flag is a permission, not a selection.
The continuation seats at body top + `outMargin`, no re-drawn outer border.

**The fix.** kstartup's cache render was one page short not because of the
split but because an anchored table (69572 HWPUNIT tall) seated with 60
HWPUNIT of room was **drawn off the page** where Hancom moves it whole.
`_auto_anchor_overflow_action` gains the move-whole arm with a page rebase,
gated to `CELL` + anchored.

**Measured, 144 dpi.** **Page counts: all ten forms equal the reference
under both policies** (kstartup cache 21 → 22). cache means ssim
0.8421 → **0.8492**, ssim_inked 0.3284 → **0.3469**, line IoU 0.6730 →
**0.7232**, pair 0.8364 → 0.8510; nine forms byte-identical, kstartup
carries the whole move. computed byte-identical. Divergence agree
1395 → **1604**, class C 243 → 28; root `forced_break` 28 → 7.

**Evidence.** `py_compile_sweep` 115/0; engine/tests 1515 passed/135
skipped; pins170; privacy HARD=0. **Full gate, tip `c09df6a`:** `tests`
492/3/0 (7m24s) + `pipeline/tests` 1437/8/0 (9m46s), 0 failed overall.

**Not proven.** One witness for the split rule; `repeatHeader` untested with
a flagged row anywhere in the corpus; the move arm's continuation seat is
inferred from that one witness; the move is gated to `CELL` + anchored
because that is all the corpus shows.

**Depends on:** #276.

### #279 — `hh:intent` moves the text inside the box, not the box

**`hh:intent` is an offset inside the paragraph box — the cached line
starts at `margin_left` on 3214/3214 lines.** Path A oracle; the reference
PDF for the first-vs-second-line question; path C NOT RUN.

**Fit for the first line's `horzpos`** (paragraphs with `intent ≠ 0` / all):
**`left` 340/340 · 2995/2995**; `left + max(intent, 0)` 325/340; `max(0,
left + intent)` (the prior reading) 285/340. Over all 3214 cached lines
`horzpos == left` holds 3214/3214. Right edges are equal on 161/161
multi-line paragraphs — a negative intent does not widen the first line.

**Rule.** The cached line box is `margin_left` to column − left − right;
`hh:intent` is applied *inside* it: the first line's text starts at
`+max(intent, 0)`, continuation lines at `+max(−intent, 0)`. Basis: the
PDFs — **13/13** discriminating first lines and **39/39** second lines sit
at `left + |intent|`, the 내어쓰기 hanging indent as Hancom draws it.

**Fix.** `_line_box` plus a new `_line_indent`, used by the line breaker and
both draw paths. 6 tests.

**Measured, 144 dpi.** cache 0.8453/0.3359/0.6742 → **0.8516/0.3546/0.6866**,
52/53 pages (this branch predates #278's page fix); computed 0.8366/0.3316/
0.6611 → **0.8384/0.3361/0.6685**, 53/53. Cells exact/near 401/1590 → **404/
1605** of 1609 (the five indent cells from #277 close).

**Evidence.** `py_compile_sweep` 114/0; engine/tests 1516 passed/135
skipped; pins170; privacy HARD=0. **Full gate, tip `aa04358`:** `tests`
487/7/0 (7m43s) + `pipeline/tests` 1435/10/0 (10m28s), 0 failed overall.

**Not proven.** The corpus is the training set; the PDF half rests on 13+39
top-level LEFT/JUSTIFY lines; no intent paragraph carries a heading, bullet
or tab; lines ≥ 2 are barely observed; jumin line IoU and moel-2025
ssim_inked fell slightly on computed — both hang inside cells the
pre-gridmax track solve still mis-columns on this branch's base.

**Depends on:** #277 (joins the #277 + #278 convergence as one more hop).

### #280 — converge #277 and #278 into one tip

**One renderer tip again.** One merge commit, no fix commit. **Three
conflicts, all mechanical:** `own_render.py` — `clip_tracks` (#276) and
`column_grid` (#277) both inserted after `solve_tracks`; kept both, and in
`_table_tracks` kept the row-axis floor/ceiling from the #278 line and the
column axis from `column_grid`, dropping a leftover `xs` rebuild that
reproduced `column_grid`'s output byte for byte. `own-render-notes.md` —
six log entries reordered into PR order, each with its own trailer.
`test_own_render.py` — both test sections kept back to back. The probes
merged clean.

**Measured, 144 dpi.** cache page-count exact **10/10**, ssim 0.852,
ssim_inked 0.355, line IoU **0.725**; computed 10/10, 0.837/0.333/0.658.
`cell_column_probe` exact/near 401/1590 of 1599 (= #277). For scale: the
same cache means at #263 were 0.8311/0.2766/0.6453 with 9/10 pages.

**Evidence.** `py_compile_sweep` 115/0; engine/tests 1529 passed/135
skipped; pins170; privacy HARD=0. Full `pipeline/tests` gate: stated in the
PR body as "appended below" — **never posted as a separate comment on
#280; its gate is folded into #281's full gate instead** (see §6, §9).

**Depends on:** #278 and #277.

### #281 — converge #279 onto the #277 + #278 tip

**The renderer tip with every table and indent slice of this round.** One
merge commit, no fix commit; one text conflict in the notes (two sections
concatenated in PR order), code merged clean.

**Measured, 144 dpi, ten forms.** cache ssim **0.8589** / ssim_inked
**0.3739** / line IoU **0.7372** / pair 0.8510, pages **10/10** exact;
computed 0.8383/0.3372/0.6643/0.8474, pages 10/10. For scale: at #263 the
cache means were 0.8311/0.2766/0.6453 with 9/10 pages; the slices since —
cell inset (#268), the 1440 floor (#275), gridmax (#277), the row floor and
ceiling (#273/#276), the anchored-table move (#278), the indent inside the
box (#279) — carry the difference. `lineseg_vs_pdf` 411/411;
`cell_column_probe` 404 exact/1605 near of 1609; render-check-01 6·37·6·2 at
96 dpi, 14·31·4·2 at 144, 9/9.

**Full gate on this tip (`8f0c399`), all foreground, one suite at a time:**
`py_compile_sweep` 116/0; engine/tests 1534 passed/135 skipped; pins170;
`tests` 493 passed/3 skipped/0 failed; `pipeline/tests` 1437 passed/8
skipped/0 failed; archive privacy HARD=0.

Everything stays `own-uncertified`; path C (a licensed Hancom rendering of
an edit) NOT RUN anywhere; the corpus is the training set and the
development-validation document was not opened this round.

**Depends on:** #280 and #279.

## 3. The development-validation document, this window

**Not opened this round.** None of #275–#281 reports any aggregate against
the private, repeatedly-reused holdout document. A scoreboard on it is
reported as being run separately by the orchestrator — **pending**, not
part of any PR body or comment this window. The document's standing
residuals (the 5 one-line-shorter export paragraphs, the 40 ±1
character-split paragraphs and their untested font-resolution hypothesis,
the +1800 page-top drift) are unaddressed and untouched this window,
unchanged from checkpoint-17.

## 4. Regressions (with the PR's or commit's own explanation)

**None claimed this window; the one real cost carried from checkpoint-17 is
partly recovered, not fully.** #273's computed line IoU had fallen 0.6595 →
0.6562, stated there as a real, accepted cost. This window: #276 recovers a
third of it on saeopja specifically (line IoU 0.7268 → 0.7304, overall
computed line IoU 0.6562 → 0.6566); #277 lifts overall computed line IoU
further to 0.6611; #279 to 0.6685 on its own branch. By #281's merged tip
the aggregate stands at computed line IoU 0.6643 — up from #273's 0.6562
low point but not a simple sum of the per-PR gains, since #278's page-count
fix and the two convergence merges also move which lines are being
compared. Every other channel on #275–#279 holds or improves individually,
by each PR's own report; #280 and #281's convergence merges are stated as
introducing no new regression, only resolving textual/mechanical overlap.

**Integration conflicts, resolved.** #280's three mechanical conflicts
(`own_render.py`'s `clip_tracks`/`column_grid` insertion point, `own-
render-notes.md`'s log ordering, `test_own_render.py`'s two test sections)
and #281's one text conflict (the notes file, two sections concatenated in
PR order) were **all resolved keeping both sides** — no side was dropped,
and both PRs report the merged tip's measured numbers moving only upward or
unchanged from the pre-merge branches' own figures.

## 5. Unsupported / declared elements still open

Carried from checkpoint-17, with this window's closures and new items:

- **Closed this window:** the #272/#273 sibling convergence owed since
  checkpoint-17 — done in two hops (#280, #281). The row-tiling column
  model — shipped as gridmax (#277), 99.4 % on the cache grid, clearing the
  99 % gate that stretch (93.5 %) and gridfirst (94.9 %, later 98.9 %)
  missed. The row-height ceiling direction — confirmed and fixed (#276).
  Table pagination / kstartup's missing page — modelled and fixed (#278),
  all ten forms now page-exact under both policies. The paragraph hanging
  indent (`hh:intent`) — modelled and fixed (#279).
- **New, named and measured, still open:** the 4 saeopja-48027 cells
  (#277, 19 HWPUNIT, unexplained); the table-split rule has only one
  witness (kstartup tbl9, #278); `repeatHeader` remains unmeasurable — no
  corpus row has `hp:tr@header` set anywhere (#278); whether the move-whole
  arm generalizes beyond `CELL` + anchored is untested, since that is all
  the corpus shows (#278); the overflow clamp on gridmax is untested, no
  corpus row overflows its columns (#277).
- **Unchanged from checkpoint-17, still fully open:** the bundled-face
  advance rule (0.9536 for NanumMyeongjo standing in for 휴먼명조) and the
  1/600-inch Hangul-advance grid — measured by #267, not shipped, not
  touched this window; the page-bottom fit-rule candidate (`vertsize −
  spacing`, #256/#260) — still needs a Hancom round-trip and COM ownership
  agreement not yet in place; the development-validation document's 5
  line-count and 40 character-split discrepancies and their
  font-resolution hypothesis (#258/#260) — not opened this window (see
  §3); computed layout's own +1800 page-top drift against that document's
  PDF (#257) — not addressed; the desktop's build-from-merged-source GUI
  smoke evidence — still does not exist; the `LayoutSnapshot` contract and
  `x1` glossary (#253) — no response recorded; `layout_policy`/
  `layout_policy_reason` still not surfaced in the desktop UI; the
  acceptance harness's lexical-reader fix for header/footer text (#235's
  queued item); Codex-app-closed sessions moved; Cursor login.
- **New, owed:** the desktop line's re-merge onto #281 — in flight, not
  landed this window; #280's `pipeline/tests` gate — never posted as its
  own comment, folded into #281's full gate instead (recorded here so it
  is not mistaken for a missing result).

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #275 | engine/tests 1503/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 486/7/0 (5m46s) + `pipeline/tests` 1435/10/0 (8m56s), tip `3e0a170` — 0 failed overall** | `py_compile_sweep` 113/0; archive privacy HARD=0 |
| #276 | engine/tests 1503/135 skipped; pins170 | **`tests` 491/3/0 (6m55s) + `pipeline/tests` 1437/8/0 (8m46s), tip `fd148bd` — 0 failed overall** | `py_compile_sweep` 114/0; archive privacy HARD=0 |
| #277 | engine/tests 1511/135 skipped; pins170 | **`tests` 486/7/0 (5m39s) + `pipeline/tests` 1435/10/0 (11m59s), tip `6d8aad1` — 0 failed overall** | `py_compile_sweep` 113/0; archive privacy HARD=0 |
| #278 | engine/tests 1515/135 skipped; pins170 | **`tests` 492/3/0 (7m24s) + `pipeline/tests` 1437/8/0 (9m46s), tip `c09df6a` — 0 failed overall** | `py_compile_sweep` 115/0; archive privacy HARD=0 |
| #279 | engine/tests 1516/135 skipped; pins170 | **`tests` 487/7/0 (7m43s) + `pipeline/tests` 1435/10/0 (10m28s), tip `aa04358` — 0 failed overall** | `py_compile_sweep` 114/0; archive privacy HARD=0 |
| #280 | engine/tests 1529/135 skipped; pins170 | **stated in the PR body as "appended below" — never posted as its own comment; folded into #281's full gate instead** | `py_compile_sweep` 115/0; archive privacy HARD=0 |
| #281 | engine/tests 1534/135 skipped; pins170 | **`tests` 493/3/0 + `pipeline/tests` 1437/8/0, tip `8f0c399`, posted directly in the PR body — 0 failed overall** | `py_compile_sweep` 116/0; archive privacy HARD=0 |

#275–#279 each post their full gate as a follow-up comment, and all landed
green. #280's full gate was never posted as a separate comment — it is
recorded above as folded into #281's, and must not be read as an
independently-confirmed green result of its own. #281 posts its full gate
directly in the PR body, green, and is this window's renderer tip.

## 7. Integration conflicts expected when lines converge

**Both hops owed since checkpoint-17 happened this window.** #280 converges
the ex-#272 line (via #275, #277) and the ex-#273 line (via #276, #278)
with three mechanical conflicts, all resolved keeping both sides: the
insertion point of `clip_tracks` and `column_grid` after `solve_tracks` in
`own_render.py`, log-entry ordering in `own-render-notes.md`, and two test
sections kept back to back in `test_own_render.py`. #281 then converges
#279 onto that tip with one text conflict (notes file, two sections
concatenated in PR order), code merging clean.

**Desktop remains unconverged with this window's renderer state.** #271
still sits on #268, five renderer slices behind #281; a re-merge is in
flight per the STATUS-001 coordinator snapshot but has not landed, so
whether it will conflict with the accumulated table/column/pagination/
indent changes is **unmeasured**.

**Writer and renderer lines remain unconverged**, unchanged from
checkpoint-17.

**Runtime line is untouched and unconverged with anything**, unmoved since
#204 (checkpoint-06).

## 8. Next measurable research question

**In the order the open items themselves point to: the fallback/bundled-
face advance rule (in flight), and whether the desktop build can run a GUI
smoke once disk allows.** The bundled-face advance rule (#267's 0.9536 for
NanumMyeongjo standing in for 휴먼명조 on a 1/600-inch Hangul-advance grid)
is measured but not shipped and is the most immediate next slice named this
window. Second, the desktop's GUI smoke has never run under this line —
whether the re-merge onto #281, once landed, can be smoke-tested depends on
disk space that has been the recorded blocker since checkpoint-16.
Carried alongside these: the 4 saeopja-48027 cells gridmax leaves
unexplained; the table-split rule's single witness (kstartup tbl9) and
`repeatHeader`'s complete absence of a positive corpus case; and the
page-bottom fit-rule candidate's need for a Hancom round-trip, still
blocked on a COM ownership agreement not yet in place.

## 9. Certification status

Every result in this checkpoint — #275 (cell-residual attribution, mostly a
fix), #276 (row-height ceiling, fix), #277 (gridmax column model, shipped
fix), #278 (anchored-table pagination, fix), #279 (hanging-indent, fix),
#280 and #281 (convergence merges, no fix commits of their own) — remains
**own-uncertified**. `render_cert.py` still cannot certify this renderer
absent a PDF text layer, unchanged since checkpoint-01.

**What moved, restated plainly:** this window closed the sibling-convergence
debt checkpoint-17 opened and, in doing so, converted two of checkpoint-17's
open measurement-only questions into shipped fixes. On columns, the 1440
floor (#275) and the probe-scoring bug fix (#277) turned #272's "94.9 %,
below gate" into gridmax's "99.4 %, 0 regressions" — the shipping gate
finally cleared. On rows, the ceiling direction (#276) completes the floor
direction #273 had already fixed, recovering part of that PR's accepted
line-IoU cost along the way. Two findings that had no counterpart at
checkpoint-17 landed fully formed this window: table pagination (#278,
bringing every corpus form to the reference's exact page count under both
policies) and the hanging-indent rule (#279, 3214/3214 cache lines and
13/13 + 39/39 PDF lines). The two renderer siblings then converged twice —
mechanically in #280, textually in #281 — leaving a single renderer tip for
the first time since checkpoint-16. Corpus cache ssim/ssim_inked/line IoU
moved from 0.8421/0.3283/0.6730 at checkpoint-17's tip to 0.8589/0.3739/
0.7372 at #281, against 0.8311/0.2766/0.6453 at #263 three checkpoints back.
The desktop line did not move this window; a re-merge onto #281 is in
flight but unlanded, so its interaction with five accumulated renderer
slices is still unmeasured. One PR this window (#280) has a gate result
that was promised in its own body but never posted as a comment — recorded
here as folded into #281's full gate, not as an independent green result.

**Owed, carried forward from checkpoint-17, plus this window's additions:**

- The desktop re-merge onto #281 — in flight, not landed; its conflict
  surface against #275–#279's accumulated changes is unmeasured.
- The 4 saeopja-48027 cells gridmax leaves unexplained (#277).
- The table-split rule's single witness (kstartup tbl9, #278) and
  `repeatHeader`'s complete lack of a positive corpus case.
- The move-whole anchored-table arm's generalization beyond `CELL` +
  anchored — untested outside what the corpus already shows (#278).
- The bundled-face advance rule (0.9536 for NanumMyeongjo standing in for
  휴먼명조) and the 1/600-inch Hangul-advance grid — measured, not shipped
  (#267, unchanged this window).
- A public path-A witness for the `vertsize − spacing` page-bottom fit
  candidate (#260, #256) — needs a Hancom round-trip, needs COM ownership
  agreement not yet in place.
- The development-validation document's font-resolution hypothesis for its
  5 line-count and 40 character-split discrepancies (#260) — not opened
  this window; a scoreboard against it is reported as pending, run
  separately by the orchestrator (see §3).
- Computed layout's own +1800 page-top drift against the
  development-validation document's Hancom-exported PDF (#257) —
  unresolved, untouched this window.
- #280's full `pipeline/tests` gate — never posted as its own comment;
  folded into #281's full gate; not to be treated as an independent result.
- The desktop's build-from-merged-source smoke evidence (#248, #262, #266,
  #271) — does not exist yet.
- The `LayoutSnapshot` proposal (#253) — no response recorded this window;
  no level-C run exists anywhere (path C NOT RUN on every PR this window).
- `layout_policy`/`layout_policy_reason` surfaced in the desktop UI — still
  not a branch or PR.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.

## 10. Coordinator interaction this window

Two status requests arrived from a coordinator session during this window,
each finding its message pipe stale, so both replies were posted as
comments on #274 instead — **PR comments are the handoff channel** when the
live pipe is unavailable.

- **REG-001** (2026-09-05 23:47 KST): a role and worktree status report —
  session identity, the four active worktrees and their tips, the renderer
  research state (two sibling lines awaiting a one-hop convergence: #277
  via #275/#272/#270, #276 via #273/#270), owned processes, and the latest
  gate evidence at that point, including the corpus scoreboard at #277
  (cache ssim/ssim_inked/line IoU 0.8453/0.3359/0.6742, against 0.8311/
  0.2766/0.6453 at #263).
- **STATUS-001** (2026-09-06 00:51 KST): a progress snapshot — the
  convergence of #278 + #277 in progress as `claude/engine-e2-converge-04`,
  #279 gating in parallel, #278's own completed gate (492/3/0 + 1437/8/0,
  all ten forms page-count-exact under both policies) and #279's engine
  suite, with the stated `next_action`: land the convergence, push, gate,
  merge #279 in one more hop, re-merge the desktop line onto that tip, and
  write this checkpoint.

Both replies stated plainly that every render stays `own-uncertified`, path
C is not run anywhere, and nothing is merged to `main`.
