# Checkpoint 17 — the row-tiling models plateau below the shipping gate, the row-height rule confirmed and its compress corrected to a floor, and the renderer tip splits into two unconverged siblings

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-16` (this
branch, `claude/docs-checkpoint-17`, is cut from `claude/docs-checkpoint-16`
and stays unmerged). Covers #270 (`claude/engine-e2-track-solve`: measures
four models for how Hancom tiles a table row whose cells disagree with the
table width, against the cached `horzsize` + inset — the best, "stretch"
(literal cell widths, last listed cell closes to `hp:sz@width`), reaches
93.5 % of 1599 measurable cells on the grid with 0 regressions against
today's global solve, still short of the 99 % shipping gate; not shipped;
finds cell x is not observable from the cache — `horzpos` is cell-relative
on 2482/2519 in-cell linesegs, so literal and addr cannot be told apart
there; no renderer change), #272 (`claude/engine-e2-row-shortfall`: shows
the "+26/+98 split" #270 left unexplained is not a shortfall allocation at
all but two column boundaries written by an earlier cell in document order
— the "gridfirst" model reaches 94.9 %, still under the gate, with every
rule that *distributes* a shortfall losing to "the last cell absorbs it";
not shipped; also runs the first row-height histogram (500/514 rows all
`rowSpan = 1` at one declared height; only 50/81 tables sum to
`hp:sz@height`); no renderer change) and, as a **sibling of #272 on the
same base #270**, #273 (`claude/engine-e2-row-height`: confirms the row
rule `max(declared, content + inset)` exactly on 70/70 tables, then finds
the bug downstream of that rule — the renderer was rescaling solved rows to
the declared table height in *both* directions, but the cache shows the
declared height is a floor, never a ceiling; fixes the compress to
floor-only; `table_row_heights` root 109 → 64, class B 350 → 302, cache IoU
0.6729 → 0.6730, but **computed line IoU 0.6595 → 0.6562**, stated plainly
as a real cost taken because the removed compress had no evidence behind
it, not a channel the fix was tuned against; notes its own one-hop
convergence with #272 is still owed). Desktop (#271) re-merges onto the
renderer tip *as of #268* — one slice behind this checkpoint's own renderer
state, which has no single tip this window (see DAG below): no conflict,
no fix needed; every reported suite 0 failed; GUI smoke was **not run**
(5.5 GB free on a 99 %-full C: with an empty Cargo target cache — a
from-scratch Tauri release build does not fit safely). Writer line
(#224 → #235 → #238 → #239) and runtime line (#204) did not move this
window.

## What changed since checkpoint-16

| metric | checkpoint-16 | checkpoint-17 | moved in |
|---|---|---|---|
| renderer-line tip | #268 (`0241864`), single linear tip | **no single tip** — two open siblings off #270 (`claude/engine-e2-track-solve`): #272 (diagnostic, `own_render.py` untouched) and **#273** (the only PR this window that changes `own_render`'s behavior, fixing the row-height compress); one-hop convergence between #272 and #273 is owed and not yet done | #270, #272, #273 |
| row-tiling model for shortfall-disagreeing tables | not modelled | **measured, not shipped**: "stretch" 93.5 % (#270, 0 regressions vs global solve) and "gridfirst" 94.9 % (#272, 1 regression vs stretch) both fall short of the 99 % gate; every shortfall-*distributing* rule loses to "the last/boundary-writing cell absorbs it"; cell x itself is not observable from the cache | #270, #272 |
| row-height rule | inherited from `_table_tracks`, unaudited against the cache this line | **confirmed**: `max(declared cellSz@height, content + top/bottom inset)`, content excluding the last line's spacing, is exact on 70/70 tables — matches what `_table_tracks` already computed | #273 |
| post-solve row-height compress | rescaled solved rows toward the declared table height in both directions | **found wrong and fixed**: the declared height is a floor only — never a ceiling on this corpus (70/70 Hancom saves sum exactly); compress now floor-only | #273 |
| `table_row_heights` root count (class-B histogram) | 109 (per checkpoint-16, up from 82 under #268) | **109 → 64** | #273 |
| seat-pass class-B paragraphs | 350 (checkpoint-16, up from 320 under #268) | **350 → 302** | #273 |
| corpus raster, 144 dpi (cache: ssim / ssim_inked / IoU, pages exact) | 0.8420 / 0.3283 / 0.6729, 52 | cache **0.8421 / 0.3283 / 0.6730**, 52 (#273 only; #270/#272 report the channel identical to checkpoint-16) | #273 |
| corpus raster, computed (ssim / ssim_inked / IoU, pages exact) | 0.8336 / 0.3246 / 0.6595, 53 | computed **0.8334 / 0.3253 / 0.6562**, 53 — line IoU falls (saeopja, moel-2013 lose; kstartup gains); stated as a real, accepted cost, not a regression the PR denies | #273 |
| first row-height histogram | did not exist | **run**: 500/514 rows are single-`rowSpan` cells at one declared height; 202/212 spanning cells equal the sum of covered rows; only 50/81 tables sum to `hp:sz@height` (the 31 remainder feeds the row-height slice #273 then closes) | #272 |
| desktop line | #266, one slice behind renderer tip #268 | **#271** re-merges onto the renderer state as of #268 — one slice behind this checkpoint's own renderer branching (#270/#272/#273 land after); no conflict, no fix needed; GUI smoke still **not run**, now blocked on an empty Cargo target cache rather than a shrinking disk | #271 |
| writer line | unmoved since checkpoint-06 | still unmoved | — |
| runtime line | unmoved since checkpoint-06 (#204) | still unmoved | — |

## 1. Branch DAG

Renderer line: a straight chain to #268 (checkpoint-16's tip), then **branches
into two unconverged siblings** at #270 — the first time this line has
forked rather than extended linearly.

| PR | branch | base | slice |
|---|---|---|---|
| #268 | `claude/engine-e2-cell-column` | `claude/engine-e2-advance-width` (#267) | renderer tip at checkpoint-16 (`0241864`) |
| #270 | `claude/engine-e2-track-solve` | `claude/engine-e2-cell-column` (#268) | measures four row-tiling models against cached `horzsize` + inset; best ("stretch") 93.5 %, 0 regressions vs today's global solve, below the 99 % gate; `own_render.py` untouched |
| #272 | `claude/engine-e2-row-shortfall` | `claude/engine-e2-track-solve` (#270) | shows the "+26/+98 split" is two column boundaries, not an allocation; "gridfirst" 94.9 %, still below gate, 1 regression vs stretch; runs the first row-height histogram; `own_render.py` untouched |
| **#273** | `claude/engine-e2-row-height` | `claude/engine-e2-track-solve` (#270) | **sibling of #272 on the same base.** Confirms `max(declared, content + inset)` 70/70; fixes the post-solve compress to floor-only — the one PR this window that changes `own_render`'s behavior; notes its own one-hop convergence with #272 is owed |

Desktop line: one new PR this window, forked from #266 — one slice behind
the renderer's own state, which itself has no single tip this window.

| PR | branch | base | note |
|---|---|---|---|
| #271 | `claude/desktop-on-renderer-268` | `claude/desktop-on-renderer-265` (#266) | re-merges the desktop onto the renderer chain through #268 (#267 → #268, on top of #266); no textual conflict, **no fix needed**; GUI smoke **not run** |

Docs line: no new docs PR this window (this checkpoint document itself is
the docs-line artifact).

Writer line, unchanged from checkpoint-16 — still #224 → #235 → #238 →
#239, no new PR this window.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` / `-16` (each off its own window's renderer
state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #270 — how a row that disagrees with its table is tiled

**Path A oracle on the public corpus, 144 dpi; path C NOT RUN. `own_render.py` untouched.**

**Models against cached `horzsize` + inset** (1609 cells, 1599 measurable,
10 ragged; "grid" = the 4-HWPUNIT grid the cache lives on): global solve
(today's `solve_tracks`) 165 exact / 905 grid (56.6 %) / 1102 within 8;
literal (each cell its own `cellSz@width`) and addr (same widths, x from
`cellAddr`) both 322 / 1401 / 1406; **stretch** (literal, last listed cell
closes to `hp:sz@width`) **324 / 1495 (93.5 %) / 1502**. On the 771
contested cells: global 143, literal/addr 639, stretch 733, with **0
regressions** against global (literal/addr regress 40). Per form (global →
stretch on grid): jumin 40 → 81 of 84, saeopja 192 → 741 of 779, the other
eight unchanged.

**jumin table 1 attributed** (39×5, `sz@width` 50897; rows 0–30 total
50897, rows 31–38 total 48067): rows 4–20 col 2 −683×19, rows 27–30 col 1
−407×4, rows 33/34/38 +1729/−1726 — the cache breaks the first cell at
exactly 29386 and the second at 21511 = 50897 − 29386: **not a
proportional rescale; the last cell absorbs the shortfall.**

**Cell x is not observable from the cache:** 2482 of 2519 in-cell
linesegs match paragraph-relative `horzpos`, 0 match any absolute
placement, so literal and addr cannot be told apart there. PDF
vertical-rule recall (1643 strokes, 50 HWPUNIT): global 263, addr 283,
literal 305, stretch 305.

**Rule stated, not shipped:** each row tiles from its own cells'
`cellSz@width` (rowSpan carried), the last listed cell closing to
`hp:sz@width`. **Why not shipped:** 93.5 % (97.5 % excluding the 66 cells
every model places identically) is below the 99 % gate; 38 contested cells
remain (37 on saeopja, where a 128-unit row shortfall splits +26/+98
between two cells by no rule measured yet — resolved by #272).

**Before/after identical:** cache 0.8420/0.3283/0.6729, 52/53 pages exact;
computed 0.8336/0.3246/0.6595, 53/53; `lineseg_vs_pdf` 411/411; cell exact
322/near 1406 of 1599; divergence 1350/118/350/243; render-check-01
6·37·6·2/14·31·4·2, 9/9.

**Evidence.** `py_compile_sweep` 113/0; engine/tests 1497 passed/135
skipped; pins+package+cleanroom+floors 170 passed; archive privacy
HARD=0. **Full gate, tip `93e0716`:** `tests` 490 passed/3 skipped/0
failed (8m00s); `pipeline/tests` 1437 passed/8 skipped/0 failed (9m12s). 0
failed overall.

**Not proven.** Which cell absorbs the residual when it is not the last (7
jumin rows + 1 moel-2013 pair); row overflow vs underflow; the 66
non-column residuals (kstartup −156×60, gianmun-1ho −874×2/−1157, jumin
+503/+502, saeopja +602); **the corpus is the training set.**

### #272 — the shortfall is two boundaries, not an allocation

**Path A oracle on the public corpus, 144 dpi; path C NOT RUN. `own_render.py` untouched.**

**Candidates against cached `horzsize` + inset** (1599 measurable cells,
771 contested; exact %, regressions vs global/vs stretch): global 905 on
grid (56.6 %) · literal/addr 1401 (87.6 %, 40/99) · **stretch** 1495 (93.5
%, 0/0) · proportional-to-grid 1218 (76.2 %, 7/277) · proportional-round/
-widest 1144 (71.5 %) · 4-unit quanta 1130 (70.7 %, 42/365) ·
colSpan-absorbs 1395 (87.2 %, 2/102) · first-row tracks 1497 (93.6 %, 0/0)
· **gridfirst 1518 (94.9 %, 0/1)** · gridlast 1497. Every rule that
*distributes* a shortfall loses to "the last cell absorbs it"; the best
model computes no shortfall at all.

**gridfirst.** One column grid per table: `x[0]=0`, `x[colCnt]=hp:sz@width`,
every interior boundary written by the **first** cell in document order
whose declared width reaches it; a later cell reaching a written boundary
stretches to it. In saeopja's 47996-wide table, row 8's three-column cell
runs `x[10]`=26433 → `x[13]`=33393 — a boundary written by row 7's
seven-column cell — giving 6960 against a declared 6932 (**+28**, cache
+26); its last cell runs 44144 → 47996 = 3852 vs 3752 (**+100**, cache
+98). Held-out check: saeopja's 47757 table, row 14, pays its 131 to its
*first* cell from a boundary row 4 wrote — gridfirst right, stretch/
first-row/gridlast wrong.

**Why not shipped:** 94.9 % < 99 %; one regression vs stretch; 12 of 15
contested misses unexplained; on the only absolute-x evidence, PDF
vertical-rule recall, gridfirst scores 303/1643 vs stretch's 305 — it wins
width and loses x while moving every table rule. Recorded as a costed
proposal beside stretch.

**Row heights, first histogram** (`--heights`, 81 tables/514 rows): 500/514
rows have all `rowSpan=1` cells at one declared height; 202/212 spanning
cells equal the sum of covered rows; only 50/81 tables sum to
`hp:sz@height`. Max-of-unit-cells is the supported reading; the 31 tables
are unexplained — taken up by #273's row-height slice.

**Channels identical to #270:** cache 0.8420/0.3283/0.6729, 52/53 pages;
computed 0.8336/0.3246/0.6595, 53/53; `lineseg_vs_pdf` 411/411; cells exact
322/near 1406; divergence 1350/118/350/243; render-check-01
6·37·6·2/14·31·4·2, 9/9.

**Evidence.** `py_compile_sweep` 113/0; engine/tests 1497 passed/135
skipped; pins+package+cleanroom+floors 170 passed; archive privacy
HARD=0. **Full gate, tip `97f0079`:** `tests` 486 passed/7 skipped/0
failed (5m46s); `pipeline/tests` 1435 passed/10 skipped/0 failed (9m08s). 0
failed overall.

**Not proven.** Whether "first writer wins" is document order or "widest
span wins" (correlated on this corpus); the 48027-table counter-example;
overflow rows untested; **20 of the 21 gains sit in the table the model was
found in.**

### #273 — a table's declared height is a floor for its rows, not a ceiling

**Path A oracle on the public corpus, 144 dpi; path C NOT RUN. Sibling of
#272 on the same base (#270); one-hop convergence follows, not yet done.**

**Probe.** `row_height_probe.py --corpus [--pdf]` derives Hancom's table
height from the cache (the holder lineseg's `vertsize` minus vertical
`outMargin` equals `hp:sz@height` on 65/65 non-paginated tables) and scores
candidate row rules over 81 tables, 1610 cached cells, 501 rows:

| candidate | rows on declared | tables whose rows sum to the stated height |
|---|---:|---:|
| declared `cellSz@height` only | 501 (circular) | 44/70 |
| content + inset only | 87 | 16/70 |
| **max(declared, content + inset)** | 437 | **70/70** |
| max + last line's spacing | 329 | 22/70 |
| max without inset | 456 | 44/70 |
| rowSpan equal / to last / ignored | 359/359/437 | 58/51/70 |

Per form, `max` is 70/70 across all ten; PDF horizontal-rule recall ranks
it first everywhere but admrul and kstartup. **Rule:** row =
max(`cellSz@height`, content + top inset + bottom inset), content
excluding the last line's spacing, rowSpan as a span constraint — what
`_table_tracks` already computed.

**The fix is downstream of the rule.** After solving rows, the renderer
rescaled them to the declared table height in both directions; the cache
shows the declared height is a floor (rows never sum below it) and never a
ceiling. The compress never fires on a Hancom save (70/70 sum exactly) but
under computed layout it turned 8 differing cells into 50 changed rows of
515. Now: floor only. 5 synthetic tests; the floor test fails on the base
(363 ≠ 1000).

**Measured, 144 dpi.** cache ssim 0.8420 → 0.8421, ssim_inked 0.3283 →
0.3283, IoU 0.6729 → **0.6730**, 52/53 pages exact (only kstartup moves,
upward). computed ssim 0.8336 → 0.8334, ssim_inked 0.3246 → **0.3253**, IoU
0.6595 → **0.6562**, 53/53 — saeopja and moel-2013 lose line IoU, kstartup
gains; stated plainly: **the computed line-IoU cost is real, taken because
the compress had no evidence behind it, not because the channel approved.**
`lineseg_vs_pdf` byte-identical 411/411. Root histogram: `table_row_heights`
**109 → 64**, `cell_valign` 17 → 14, others unmoved. Classes
1350/118/350/243 → **1395/118/302/243**. render-check-01 unchanged
(6·37·6·2/14·31·4·2, 9/9).

**Evidence.** `py_compile_sweep` 114/0; engine/tests 1502 passed/135
skipped; pins+package+cleanroom+floors 170 passed; archive privacy HARD=0.
**Full `pipeline/tests` gate: stated in the PR body as "appended below" —
as of this checkpoint no comment has landed on #273. Do not read as
green.** (An early engine run showed 47 CLI-subprocess failures that
reproduced on neither the base nor a rerun — noted as transient.)

**Not proven.** The rowSpan and margin-next arms have no corpus witness
(no corpus row is set by a spanning cell, all margin-next are 0); no
table's rows fall short, so the floor arm is inherited from the cache
reading, not exercised; **two kstartup tables overflow by 78/282 even
under the cache (unexplained)**; **the corpus is the training set.**

### #271 — desktop re-merge onto the renderer tip #268

**The desktop line on the renderer tip #268** (#267 advance probe, #268
cell inset from `inMargin`, on top of #266). One merge commit, no
conflicts, no fix needed.

**Evidence (merged tree, one suite at a time).** `py_compile_sweep` 138/0;
engine/tests 1504 passed/135 skipped/0 failed; `tests` 1092 passed/7
skipped/0 failed (three batches); `pipeline/tests` 1437 passed/10
skipped/0 failed (three batches); geometry/runtime-render/own selection
211 passed; archive privacy HARD=0 (WARN 55: fixture IDs). Reported
directly in the PR body — no separate comment needed. The cell-inset
change moves table text in the desktop's own render path; no desktop or
runtime test pins cell coordinates (only the two diagnostic scripts
`rt_geometry.py`/`rt_own.py` read `cell_boxes`), and the covering tests
under `tests/` are green.

**Desktop GUI smoke: NOT RUN.** 5.5 GB free on a 99 %-full C: with an
empty Cargo target cache; a from-scratch Tauri release build does not fit
safely. The claim "the app built from this tree renders and edits" stays
open until a build from this sha runs the smoke; a pre-built exe smoke is
not cited.

**Stated, not done.** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248; ownership per #253).

**Depends on:** #266 (desktop) and #268 (renderer). Merge: Sonnet;
orchestrator: Fable. No comments on this PR as of this checkpoint.

## 3. The development-validation document, this window

**Not opened this round.** None of #270, #271, #272 or #273 reports any
aggregate against the private, repeatedly-reused holdout document — #270
and #272 are corpus-only diagnostics with `own_render.py` untouched, #273's
own body reports only public-corpus figures, and #271 is a merge commit
with no render re-run of its own. The document's standing residuals — the
5 one-line-shorter export paragraphs, the 40 ±1 character-split paragraphs
(#258, font-resolution hypothesis still untested), the +1800 page-top drift
(#257) — are unaddressed and untouched this window, unchanged from
checkpoint-16.

## 4. Regressions (with the PR's or commit's own explanation)

**One real, explained cost this window, no others claimed.** #273's
computed line IoU falls 0.6595 → 0.6562 (saeopja and moel-2013 lose,
kstartup gains) as a direct, stated consequence of removing the
unsupported ceiling-direction compress — the PR calls this "a real cost
taken because the compress had no evidence behind it, not because the
channel approved," not a hidden regression. Every other channel on #273
holds or improves (cache ssim_inked unchanged at 0.3283, cache IoU 0.6729 →
0.6730, `table_row_heights` root 109 → 64, class B 350 → 302). #270 and
#272 report zero raster or page-count movement by construction
(measurement-only PRs, `own_render.py` untouched) and #270's stretch model
carries 0 regressions against today's global solve on the contested-cell
population; #272's gridfirst carries exactly 1 regression against
stretch, named and left unresolved. #271's merge had no conflicts and no
fix was needed, so nothing to regress on the merge step itself.

## 5. Unsupported / declared elements still open

Carried from checkpoint-16, with this window's closures, redirections and
new items:

- **Measured further, still not shipped:** the track-solve residual on
  tables whose row totals contradict their own column sums — #270's
  "stretch" model reaches 93.5 % (0 regressions vs global), #272's
  "gridfirst" reaches 94.9 % (1 regression vs stretch); both remain below
  the 99 % shipping gate and neither is a merged renderer change.
- **Confirmed and fixed this window:** the row-height rule
  `max(declared, content + inset)`, exact on 70/70 tables, and the
  post-solve compress bug that had been rescaling rows toward the
  declared table height in both directions instead of floor-only (#273).
- **New, named and measured, still open:** the 66 non-column cell
  residuals #270 leaves unattributed (kstartup −156×60, gianmun-1ho
  −874×2/−1157, jumin +503/+502, saeopja +602); the two kstartup tables
  that overflow their cached height by 78/282 even under the cache
  (#273, unexplained); whether "first writer wins" is document order or
  "widest span wins" on #272's gridfirst rule (correlated on this
  corpus, not separated).
- **New, owed:** the one-hop convergence between #272 and #273, both
  siblings off #270 — named explicitly in #273's own PR body and not yet
  attempted; #273's full `pipeline/tests` gate, stated as "appended
  below" but not yet posted as of this checkpoint — must not be read as
  green.
- **Unchanged from checkpoint-16, still fully open:** the bundled-face
  advance rule (0.9536 for NanumMyeongjo standing in for 휴먼명조) and the
  1/600-inch Hangul-advance grid — measured by #267, not shipped, not
  touched this window; the page-bottom fit-rule candidate
  (`vertsize − spacing`, #256/#260) — still needs a Hancom round-trip and
  COM ownership agreement not yet in place; the development-validation
  document's 5 line-count and 40 character-split discrepancies and their
  font-resolution hypothesis (#258/#260) — not opened this window (see
  §3); computed layout's own +1800 page-top drift against that document's
  PDF (#257) — not addressed; the desktop's build-from-merged-source GUI
  smoke evidence — still does not exist, still blocked on disk/Cargo-cache
  space; the `LayoutSnapshot` contract and `x1` glossary (#253) — no
  response recorded; `layout_policy`/`layout_policy_reason` still not
  surfaced in the desktop UI; the acceptance harness's lexical-reader fix
  for header/footer text (#235's queued item); Codex-app-closed sessions
  moved; Cursor login.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #270 | engine/tests 1497/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 490/3/0 (8m00s) + `pipeline/tests` 1437/8/0 (9m12s), tip `93e0716` — 0 failed overall** | `py_compile_sweep` 113/0; archive privacy HARD=0 |
| #271 | engine/tests 1504/135 skipped/0 failed; `tests` 1092/7/0 (three batches); `pipeline/tests` 1437/10/0 (three batches); geometry/runtime-render/own selection 211 — reported directly in the PR body | **same figures, 0 failed** — no separate comment needed | `py_compile_sweep` 138/0; archive privacy HARD=0 (WARN 55: fixture IDs); GUI smoke NOT RUN |
| #272 | engine/tests 1497/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 486/7/0 (5m46s) + `pipeline/tests` 1435/10/0 (9m08s), tip `97f0079` — 0 failed overall** | `py_compile_sweep` 113/0; archive privacy HARD=0 |
| #273 | engine/tests 1502/135 skipped; pins+package+cleanroom+floors 170 | **stated in the PR body as "appended below" — not yet posted as a comment; NOT CLAIMED GREEN** | `py_compile_sweep` 114/0; archive privacy HARD=0; one early transient CLI-subprocess run (47 failures, reproduced on neither base nor rerun) noted and discounted |

#270 and #272 both post their full gate as a follow-up comment, and both
landed green. #271 reports its full gate directly in the PR body with no
separate comment needed, and it is green. #273 is, at the time this
checkpoint was written, the one PR in this window whose full gate is
**not yet confirmed** by a posted comment.

## 7. Integration conflicts expected when lines converge

**Renderer line forked, not extended, this window** — the first fork since
checkpoint-14/15/16's linear chains. #270 forked from #268; #272 and #273
both fork from #270 as **unconverged siblings**, and no merge between them
has been attempted. #273's own body names the one-hop convergence as owed;
until it happens, whether #272's gridfirst boundary model and #273's
floor-only compress touch the same code paths without conflict is
**unmeasured**, not merely unmentioned.

**Desktop converged onto the renderer chain again this window (#271)** —
one integration event, no conflict, no fix needed: the cell-inset change's
effect on table text passes through code no desktop or runtime test pins
by coordinate, and the covering tests are green. Desktop remains one
renderer slice behind the tip: it merged through #268, and #270/#272/#273
landed after.

**Writer and renderer lines remain unconverged**, unchanged from
checkpoint-16.

**Runtime line is untouched and unconverged with anything**, unmoved since
#204 (checkpoint-06).

## 8. Next measurable research question

**In the order named by #270, #272 and #273 themselves: the 66 non-column
cell residuals (in flight), the two kstartup tables overflowing by 78/282
even under the cache, the bundled-face advance rule, and the page-fit
witness via a Hancom round-trip.** #270 leaves 66 non-column cell residuals
unattributed (kstartup −156×60, gianmun-1ho −874×2/−1157, jumin +503/+502,
saeopja +602) — bounded, already isolated, and the most immediate next
slice given #272 and #273 both build on #270's probe. Second, #273's two
kstartup tables that overflow their own cached height by 78 and 282
HWPUNIT even under Hancom's own layout are unexplained and untouched by
the floor-only fix. Third, #267's per-face advance ratios (bundled
NanumMyeongjo 0.9536 vs installed faces 1.0000, Hancom's own Hangul advance
on a 1/600-inch grid) remain measured but not shipped, carried unchanged
from checkpoint-16. Fourth, #260's restored path-A "+566" witness for
`vertsize − spacing` and the renderer line's own remaining class-B
paragraphs both still point at the same unresolved need: a Hancom
round-trip of the same package, which requires COM ownership agreement not
yet in place. **Separately and structurally**, the #272/#273 sibling
convergence itself is now a measurable question this checkpoint adds:
neither PR has been run against the other's change, and #273's own body
says so.

## 9. Certification status

Every result in this checkpoint — #270 (row-tiling probe, measurement
only), #272 (row-shortfall probe, measurement only), #273 (row-height
compress fix), #271 (desktop re-merge, no fix) — remains **own-uncertified**.
Of this window's four PRs, only #273 changes `own_render`'s behavior; #270
and #272 are diagnostics with `own_render.py` untouched, and #271 is a
merge with no fix commit. None changes a certified renderer surface.
`render_cert.py` still cannot certify this renderer absent a PDF text
layer, unchanged since checkpoint-01.

**What moved, restated plainly:** this window took checkpoint-16's newly
class-B-attributed remainder further on two fronts at once — table-column
tiling and table-row height — and got a different shape of result from
each. On columns, two increasingly specific models (#270's stretch at
93.5 %, #272's gridfirst at 94.9 %) both plateaued below the 99 % shipping
gate; neither shipped, and the renderer is unchanged there. On rows, the
existing rule was confirmed exact (70/70 tables) and a real downstream bug
was found and fixed — the post-solve compress had been treating the
declared table height as a ceiling as well as a floor, with no cache
evidence for the ceiling direction; removing it cost 0.0033 of computed
line IoU on two forms while gaining slightly on the cache channel and
shrinking the class-B remainder from 350 to 302 paragraphs. That row-height
PR (#273) and the row-shortfall PR (#272) both fork from the same base
(#270) and have not been run against each other — an owed one-hop
convergence, named by #273 itself, that this checkpoint carries forward
rather than resolves. The desktop line converged onto the renderer chain a
second consecutive time (#271) with, again, no conflict and no fix
required, but its GUI smoke evidence still does not exist, now blocked by
an empty Cargo target cache rather than a shrinking disk. One PR in this
window (#273) has a gate result promised in its own body but not yet
posted; it is recorded here as pending, not green.

**Owed, carried forward from checkpoint-16, plus this window's additions:**

- The #272/#273 sibling convergence — both fork from #270, neither has run
  against the other's change; named by #273's own body, not yet attempted.
- #270's 66 non-column cell residuals (kstartup −156×60, gianmun-1ho
  −874×2/−1157, jumin +503/+502, saeopja +602) — unattributed, in flight.
- #273's two kstartup tables overflowing by 78/282 even under the cache —
  unexplained.
- Neither row-tiling model (stretch 93.5 %, gridfirst 94.9 %) clears the
  99 % shipping gate — both recorded as costed proposals, not shipped.
- The bundled-face advance rule (0.9536 for NanumMyeongjo standing in for
  휴먼명조) and the 1/600-inch Hangul-advance grid — measured, not shipped
  (#267, unchanged this window).
- A public path-A witness for the `vertsize − spacing` page-bottom fit
  candidate (#260, #256) — needs a Hancom round-trip, needs COM ownership
  agreement not yet in place.
- The development-validation document's font-resolution hypothesis for its
  5 line-count and 40 character-split discrepancies (#260) — not opened
  this window (see §3).
- Computed layout's own +1800 page-top drift against the
  development-validation document's Hancom-exported PDF (#257) —
  unresolved, untouched this window.
- #273's full `pipeline/tests` gate — stated as "appended below," not yet
  posted; not to be treated as green until it lands.
- The desktop's build-from-merged-source smoke evidence (#248, #262, #266,
  #271) — does not exist yet; blocked this window on an empty Cargo
  target cache rather than raw disk space, still unsafe to attempt.
- The `LayoutSnapshot` proposal (#253) — no response recorded this window;
  no level-C run exists anywhere (path C NOT RUN on every PR this window).
- `layout_policy`/`layout_policy_reason` surfaced in the desktop UI — still
  not a branch or PR.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.
