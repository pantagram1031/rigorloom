# Checkpoint 22 — the page-top space-before rule ships, the right-edge budget's admissible window moves under it while the constant stays, and the renderer forks and reconverges again

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-21` (this
branch, `claude/docs-checkpoint-22`, is cut from `origin/claude/docs-checkpoint-21`
and stays unmerged). All six PRs covered this window are **OPEN/DRAFT** —
nothing in this window has merged to `main`. Covers #304
(`claude/engine-e2-table-origin`, on #301: a table-origin probe fix
re-attributes the 64 unattributed paragraphs, drops `text_rebreak:width`
165 → 2 and names a new root `page_top:margin_prev` 88), #306
(`claude/engine-e2-page-top-margin`, on #304: the page-top space-before
rule ships), #307 (`claude/engine-e2-installed-residual`, on #303: the
trailing 자간 in `_line_fits` is counted, the right-edge window is
re-derived, 96 stays); convergence #303 (`claude/engine-e2-converge-10`,
on #299, merges #301) and #308 (`claude/engine-e2-converge-11`, on #303,
merges #304, #306, #307; one notes-only conflict; a privacy-scan HARD=248
was traced to an untracked build directory, zero in tracked content);
desktop #305 (`claude/desktop-on-renderer-303`, on #300, tip #303). **A
desktop re-merge onto #308 is in flight as this document is written; it
has no PR number yet and none is assigned here.** Writer line
(#224 → #235 → #238 → #239) and runtime line (#204) did not move. Docs
line: no new docs PR this window besides this checkpoint document itself.

**Two open decisions for the product/reviewer, stated plainly:**

1. **Whether #301's 96-HWPUNIT right-edge tolerance is acceptable as a
   declared error budget for the advance metrics**, rather than being read
   as (or mistaken for) a Hancom fit rule. **Updated this window:** #307
   re-derived the admissible window from [63.1, 111.8) to **[18.5, 26.3)**
   after decomposing the installed-face punctuation residual (#283's
   +197.76 is gone — it was the HFT share, now paid by the measured
   table). k = 2 is the only 4-HWPUNIT step inside the new window and was
   **not taken** (it loses jumin paragraph 139 below 8 on
   `lineseg_agreement` and paragraph 160 below 6 on `--standin table+cell`).
   **96 stays, now sitting outside its own admissible window** — stated by
   the PR, not hidden. #307's own comment restates the reviewer call is
   still open: "whether the 96-HWPUNIT budget belongs in the renderer at
   all, now that its admissible window is [18.5, 26.3)."
2. **The sidecar data-list line** in `desktop/sidecar/build.ps1` — adding
   `engine/references/fonts/hft-widths.measured.json` so a frozen desktop
   build does not silently fall back to the pre-#292 HFT metric. Still
   unowned this window; #305 states it "still stands for the product
   line." Ownership sits on the product side per #253.

## What changed since checkpoint-21

| metric | checkpoint-21 | checkpoint-22 | moved in |
|---|---|---|---|
| renderer-line tip | forked: #299 converges #295+#297 onto #294; #301 branches off #297 before that convergence, an unconverged sibling of #299 | **#303 converges #301 onto #299** (clean, one merge commit, full gates green); the renderer **forks again**: #304 (probe, based on #301's branch) → #306 (ships the page-top rule) is one unconverged chain, #307 (based directly on #303's branch) is a second; **#308 converges #304 + #306 + #307 onto #303** — tip is now #308 | #303, #304, #306, #307, #308 |
| page-fit public witness (§8 of checkpoint-21, blocked on COM ownership) | scanned to the end on the public corpus, bracket `vertsize` −31/+911, blocked on the Hancom round-trip | **untouched this window** — no PR in this batch runs `page_fit_probe`; still blocked on COM ownership | unchanged |
| HFT stand-in width rule | measured to its end (#297), nothing shipped, 21/47 held only after #301's tolerance | **unchanged this window**: #303 confirms "hft_width_table --standin all six variants 21/47"; #307's own tip (pre-#304/#306) reports the same six variants 21/47 | unchanged |
| right-edge line-fit tolerance | shipped, 96 HWPUNIT, admissible window [63.1, 111.8), declared error budget | **96 stays**, but the admissible window is re-derived to **[18.5, 26.3)** after #307 counts the trailing 자간 gap in `_line_fits`; 6 of 18 over-box lines close under the new rule, 0 rejected spans change hands, agreement 48/113 and 21/47 unchanged, 0 flips; k=2 (only step inside the window) considered and **not taken** | #307 |
| installed-face punctuation residual | #283's +197.76 named, unexplained | **decomposed, not fixed**: 545 punctuation advances sum +135.8 HWPUNIT; installed faces 487 = **+253.3** (+0.52 each), HFT-metered 58 = −117.4; #283's +197.76 is gone — it was the HFT share, now paid by the measured table (#292); the residual itself has "no mechanism yet" per #307 | #307 |
| `text_rebreak:width` / `table_origin_unattributed` roots | 41 / 64 (new bucket, unexplained) | **#304: 41 → 2, and 64 → 0** — the 64 was the probe's own blind spot (walk stopped one level above a nested table cell), re-attributed; new roots `page_top:margin_prev` 88 (new), `text_line_height` 19 (new), `page_top_unattributed` 3; **#306 then closes `page_top:margin_prev` 88 → gone** by shipping the seating rule, "other six roots unchanged" | #304, #306 |
| `layout_divergence` classes (agree/A/B/C) | 1713 / 94 / 219 / 28 (unchanged through #301) | **unchanged through #304** (probe-only) and through #307's own tip (based on #303, pre-#304/#306); **#306 moves it to 1801 / 94 / 131 / 28**; #308's merged tree confirms **1801 / 94 / 131 / 28** "matches expected exactly" | #306, confirmed #308 |
| corpus raster, 144 dpi, cache (ssim / ssim_inked / IoU) | byte-identical 0.861944 / 0.393719 / 0.736589 through #301 | **still byte-identical** through #303, #304, #306, #307, #308 (0.861944 / 0.393719 / 0.736589, 53 pages, 10/10 exact) — none of this window's rules touch cache-mode rendering | unchanged |
| corpus raster, 144 dpi, computed (ssim / ssim_inked / IoU) | 0.8451 / 0.358796 / 0.684881 (#301) | unchanged through #303 and #304; **#306 moves it to 0.848325 / 0.364894 / 0.692148** (entirely moel-2025 +0.0311/+0.0484/+0.0646 and kstartup +0.0012/+0.0125/+0.0081); #307's own tip (pre-#306) is unchanged at 0.845092/0.358796/0.684881 since it doesn't include #306; #308's merged tree reports 0.848325 / 0.364894 / 0.692148, "matches #306 exactly" — #307's trailing-자간 rule produced 0 flips on the corpus | #306 |
| `lineseg_vs_pdf` | 411/411 | **unchanged**: 411/411 lines confirmed by #303, #307 (also 8566/8566 characters), and #308 (411/411 lines, 8566/8566 characters, "matches expected exactly") | unchanged |
| desktop line | #298, #300 both one hop behind #301 | **#305 re-merges onto renderer tip #303**, clean, no conflicts; a further desktop re-merge onto #308 is in flight as this document is written (unnumbered) | #305 |
| writer line | unmoved since checkpoint-06 | still unmoved | — |
| runtime line | unmoved since checkpoint-06 | still unmoved | — |

## 1. Branch DAG

Renderer line: **#303 folds the unconverged #301 sibling from checkpoint-21
onto the #299 tip; the renderer then forks again — #304 → #306 as one
chain (based on #301's branch, ships the page-top rule) and #307 as a
second (based directly on #303's tip, ships the trailing-자간 rule) — and
#308 converges all three back onto #303.**

| PR | branch | base | slice |
|---|---|---|---|
| #303 | `claude/engine-e2-converge-10` | `claude/engine-e2-converge-09` (#299), merges #301 | folds checkpoint-21's unconverged sibling in: one merge commit, no conflicts; cache = #299 byte-identical, computed = #301 (IoU 0.684881); the 96-HWPUNIT constant carried in as a declared error budget awaiting reviewer sign-off |
| #304 | `claude/engine-e2-table-origin` | `claude/engine-e2-right-edge` (#301) | class_b_probe fix: the walk now recurses through nested tables and stops charging steps across page boundaries; the 64 `table_origin_unattributed` paragraphs are all cause (a) — displaced by an upstream reason the old walk stopped above; re-attributes to a new `page_top:margin_prev` 88 root; probe only, `own_render.py` untouched |
| #306 | `claude/engine-e2-page-top-margin` | `claude/engine-e2-table-origin` (#304) | ships `OwnRenderer._page_top_seat`: a whole-moved block is seated at its own `margin_prev` on a fresh page; closes the `page_top:margin_prev` 88 root; class B 219 → 131 |
| #307 | `claude/engine-e2-installed-residual` | `claude/engine-e2-converge-10` (#303) | decomposes the installed-face punctuation residual (+253.3), ships a trailing-자간 count in `_line_fits`, re-derives the right-edge admissible window to [18.5, 26.3); 96 stays, k=2 not taken |
| #308 | `claude/engine-e2-converge-11` | `claude/engine-e2-converge-10` (#303), merges #304, #306, #307 | converges the two unconverged chains onto #303's tip: #304 and #306 merge clean in order; #307 (based directly on #303) produces one conflict in a notes file, resolved by concatenation; `own_render.py` and its tests auto-merge cleanly — #307's `_line_fits` and #306's `_page_top_seat` touch disjoint code paths |

Desktop line: one re-merge this window, plus one more in flight unnumbered.

| PR | branch | base | note |
|---|---|---|---|
| #305 | `claude/desktop-on-renderer-303` | `claude/desktop-on-renderer-299` (#300), tip #303 | re-merge onto renderer tip #303; one merge commit, no conflicts, no fix needed; the 96-HWPUNIT tolerance changes computed line breaks and therefore caret geometry on re-laid-out documents, and the covering tests pass |

**A desktop re-merge onto #308 is in flight as this document is written.**
It has no PR number and none is assigned here.

Docs line: no new docs PR this window besides this checkpoint document
itself.

Writer line, unchanged from checkpoint-21 — still #224 → #235 → #238 →
#239.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` … `-21` (each off its own window's renderer
state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #303 — converge #301 onto the #299 tip

**One merge commit, no conflicts, full gates green.** Depends on #299 and
#301. Merge: Sonnet; orchestrator: Fable. No comments.

**Verified on the tip (144 dpi):** cache ssim 0.8619 / ssim_inked 0.3937 /
IoU 0.7366 (= #299, byte-identical — cache mode does not break lines),
pages 10/10; computed IoU **0.684881** / ssim 0.8451 / ssim_inked 0.3588
(= #301), 10/10; `lineseg_vs_pdf` 411/411; `hft_width_table --standin` all
six variants 21/47; roots `text_rebreak:width` 41, `table_origin_unattributed`
64; render-check-01 6·37·6·2 at 96 dpi, 14·31·4·2 at 144, 9/9. kstartup's
per-page `ssim_inked_min` verdict is `pass=false` under both policies —
stated as pre-existing since the scoreboard's min-channel was added
(identical to four decimals), not new.

**Full gate on this tip (`55e878f`), all foreground, unsplit:**
`py_compile_sweep` 119/0; engine/tests 1645 passed/135 skipped;
pins+package+cleanroom+floors 170 passed; `tests` 496 passed/3 skipped/0
failed; `pipeline/tests` 1437 passed/8 skipped/0 failed (the
order-dependent `test_claim_extraction` case passed in order); archive
privacy HARD=0.

Everything stays `own-uncertified`; path C NOT RUN anywhere; the corpus is
the training set; the 96-HWPUNIT right-edge constant is a declared error
budget awaiting the reviewer's call.

### #304 — the table-origin bucket was the probe's own blind spot

**Probe only; `own_render.py` untouched.** Depends on #301. Worker: Opus;
orchestrator: Fable.

**Classification of the 64:** 114 class-B paragraphs on moved table
origins, cause (a) — the table's holder paragraph is itself displaced for
an upstream reason the walk stopped at — **114/114**; positioning
attributes (b), row heights (c), column changes (d): 0. All six tables are
inline (`treatAsChar=1`, `vertRelTo=PARA`, `vertOffset=0`,
`textWrap=TOP_AND_BOTTOM`), `d_within_holder = 0`. By table: moel-2025
tbl7 20 / tbl8 32 / tbl9 32; nrf tbl1 27; kstartup tbl15 1 / tbl16 2. Two
named examples, moel-2025 **tbl8** (holder ¶251) and **tbl9** (holder
¶289), each carry **−1000 HWPUNIT** — both nested in cells of tbl7, whose
holder ¶233 (top-level, page 7, `margin_prev = 1000`) the cache seats at
1000 and the flow pass at 0.

**Two probe defects fixed:** the walk now recurses through nested tables
(it stopped one level above the cell before); it no longer charges steps
across page boundaries (¶74's root was a phantom ±1496 pair two pages
back; its carrier is ¶73 at −208, the whole drawn dy). Page tops are now
named by two checked equalities — paragraphs carried across the break, and
the head's space-before.

**Roots before → after** (classes unchanged at 1713/94/219/28):
`text_rebreak:width` 41 → **2**, `table_origin_unattributed` 64 → 0,
`table_row_heights` 63, `empty_paragraph` 29, `cell_valign` 15, new
`page_top:margin_prev` **88**, new `text_line_height` 19,
`page_top_unattributed` 3. The largest remaining class-B mechanism is
named as a page-top rule question: does `hh:margin@prev` apply when a
paragraph lands at the top of a page? The cache says yes (¶233 at 1000);
the flow pass says no — named as the next slice.

**Measurements unchanged:** cache 0.8619/0.3937/0.7366, computed
0.8451/0.3588/0.6849, 10/10 pages; `lineseg_vs_pdf` 411/411; render-check-01
6·37·6·2/14·31·4·2, 9/9.

**Not proven:** which policy is right at a page top — ¶233 is an object
paragraph, skipped by `lineseg_vs_pdf`, so its 1000 was never compared to
the export; causes (b)/(c)/(d) are absent on this corpus, not refuted (no
anchored table's origin moved); kstartup ¶759/¶794/¶797 (≈ −62.8k HWPUNIT,
the E2.7 anchor overflow) stay unattributed; recursion measured to two
nesting levels.

**Evidence:** `py_compile_sweep` 119/0; engine/tests 1635 passed/135
skipped; pins+package+cleanroom+floors 170 passed; archive privacy HARD=0.
**Full gate, tip `56c35bb`** (posted as a follow-up comment): `tests` 492
passed/7 skipped/0 failed (8m11s) + `pipeline/tests` 1435 passed/10
skipped/0 failed (10m59s), 0 failed overall. Comment states this PR is
probe-only; the page-top space-before rule it surfaced starts as the next
slice.

### #306 — a whole-moved block is seated at its space-before on a new page

**Shipped.** Depends on #304. Worker: Opus; orchestrator: Fable.

**Rule:** a block that moves whole to a fresh page is seated at its own
`hh:paraPr/hh:margin/hc:prev`; a continuation stays at 0; the previous
block's `margin_next` is not carried onto the new page; the seat is
dropped when it would leave no room (also the loop's termination guard).
One seam, `OwnRenderer._page_top_seat`, called from the explicit/column
break, the anchored whole move, keepLines/widowOrphan, and the row loop's
whole-block move. `_apply_keep_with_next` untouched (never fires on the
corpus).

**Probe (`class_b_probe.py --corpus --page-top`, path A cache read):** 53
page heads. Candidates exact/total: margin_prev 51, dropped **49**,
collapsed 51, pages-2+ 51, pushed-whole 51, uncollapsed 51. Only 2 heads
discriminate (moel-2025 ¶233 vertpos 1000 = margin_prev; kstartup ¶398
vertpos 300 = margin_prev), and both refute only "dropped". The 2
counter-examples common to every candidate are kstartup pages 5 and 7
(vertpos 69632/69785, margin_prev 0), the known anchor-overflow band.
**Five candidates tie on page tops.** The deciding evidence is the
container mirror: 86/86 cell-first paragraphs with a space-before are
cached at exactly margin_prev, 0 at zero; mid-page 534/539 consecutive
pairs sit exactly `prev margin_next + margin_prev` apart (all 5 exceptions
declare neither margin). Page-bottom mirror: 53 feet, 0 with a nonzero
margin_next. Bracket empty, #256 untouched.

**Before/after (public corpus, 144 dpi):** cache scoreboard byte-identical
(0.861944/0.393719/0.736589, 53 pages, 10/10 exact). Computed ssim
0.845092 → **0.848325**, inked 0.358796 → **0.364894**, IoU 0.684881 →
**0.692148**, 53 pages, 10/10 exact. Entirely moel-2025 (+0.0311/+0.0484/
+0.0646) and kstartup (+0.0012/+0.0125/+0.0081), page counts unchanged.
`layout_divergence` classes 1713/94/219/28 → **1801/94/131/28**; root
`page_top:margin_prev` 88 → gone, other six roots unchanged. `lineseg_vs_pdf`
411/411 lines, 8566/8566 chars (control). render-check-01 unchanged at
both dpi and both policies (no cached linesegs; none of its 7 flow heads
declares a space-before).

**Not proven:** the candidate choice rests on the cell-top evidence and
the OWPML reading, not on a page top that separates the five; "prev
margin_next falls off the foot" is reasoning; keepWithNext heads still
seat at 0; the fit guard is a tie-break. 131 class-B paragraphs remain
(`table_row_heights` 63, `empty_paragraph` 29 next). Dev-validation doc:
not re-measured in this slice.

**Gates (worker, foreground, one at a time):** `py_compile` 119/0;
engine/tests 1649 passed/135 skipped/0 failed; tests 170 passed; privacy
HARD=0 WARN=54. **Full gate, tip `831ee52`** (posted as a follow-up
comment): `pipeline/tests` in two halves, 579 passed/7 skipped and 856
passed/3 skipped, 0 failed (2m01s + 5m32s); with the worker's engine/tests
1649/135 and tests 170, 0 failed overall. One auto-backgrounded pytest
attempt was killed at 81% and replaced by the foreground halves, stated.

### #307 — the trailing 자간 in `_line_fits`; the right-edge window re-derived

**Shipped.** Depends on #303. Worker: Opus; orchestrator: Fable.

**Question:** #301 landed a 96-HWPUNIT right-edge budget over an
installed-face punctuation over-measure that #283 had put at +197.76.
Re-measure with the HFT table in place, decompose the 8+14 lines behind
the budget, and re-derive k.

**Residual now** (`advance_probe.py --corpus --punct --installed-only`,
new flag): 545 punctuation advances sum to +135.8 HWPUNIT; installed
faces 487 = **+253.3 (+0.52 each)**, HFT-metered 58 = −117.4. Largest: `-`
malgunbd +243.0, `.` malgunbd −189.1, `-` malgun +156.4, `◦` batang −69.0.
#283's +197.76 is gone; it was the HFT share, now paid by the measured
table (#292).

**The 8+14 decomposed:** all 8 over-box lines are ratio 100, not bold,
installed faces; the term is the **trailing 자간 on the last character** (7
of 8 carry a negative one). All 14 under-box lines are under-measures, so
punctuation has the wrong sign for them: 7 carry substituted or HFT faces,
3 are one 6-character line repeated, 2 are hyphen break-opportunity
artefacts, 2 (ratio 95/98) are 8 to 34 HWPUNIT per character.

**Rule shipped:** `_line_fits` counts the trailing 자간 gap of the last
character. Basis: `hh:charPr@spacing` is per-character in OWPML; the drawn
extent cannot see the final gap, the breaker can. 6 of 18 over-box lines
close; 0 rejected spans change hands; agreement 48/113 and 21/47
unchanged, 0 flips.

**k re-derived** (`right_edge_probe.py --corpus --breaks`): admissible
window moves from [63.1, 111.8) to **[18.5, 26.3)**. k = 2 is the only
4-HWPUNIT step inside it and is **not taken**: `lineseg_agreement` loses
jumin paragraph 139 below 8, `--standin table+cell` loses paragraph 160
below 6. **96 stays**, now outside its own window; stated, not hidden.

**Before/after identical:** cache 0.861944/0.393719/0.736589, computed
0.845092/0.358796/0.684881, 10/10 pages; `lineseg_vs_pdf` 411/411,
8566/8566; six stand-in variants 21/47; classes 1713/94/219/28; roots
64/63/41/29/15/7 (unlabeled list as posted); render-check 6·37·6·2 at 96,
14·31·4·2 at 144, 9/9. (This tip is based directly on #303, so it does not
carry #304's or #306's reclassification.)

**Not proven:** the trailing-gap reading is a reading of the breaker, not
documented; 3 independent observations only; jumin paragraph 34 (positive
자간) gets worse; the +253.3 installed-face residual has no mechanism yet;
gulim.ttc punctuation is never anchored by any public line.

**Gates (worker, foreground):** `py_compile` 119/0; engine/tests 1647
passed/135 skipped/0 failed; tests 170 passed; privacy HARD=0 WARN=54.
**Full gate, tip `c501dad`** (posted as a follow-up comment):
`pipeline/tests` in two halves, 581 passed/5 skipped and 856 passed/3
skipped, 0 failed (2m09s + 6m04s); with the worker's engine/tests 1647/135
and tests 170, 0 failed overall. Comment restates the reviewer decision
still open from #301: whether the 96-HWPUNIT budget belongs in the
renderer at all, now that its admissible window is [18.5, 26.3).

### #308 — converge #304, #306 and #307 onto the renderer tip

**Merges #304, #306 and #307 onto the renderer tip, branched from
`claude/engine-e2-converge-10` (55e878f).** Worker: Sonnet; orchestrator:
Fable. No comments.

**Branches merged in order:** (1) `origin/claude/engine-e2-table-origin`
(#304) — clean merge, no conflicts. (2)
`origin/claude/engine-e2-page-top-margin` (#306), on top of #304 — clean
merge, no conflicts. (3) `origin/claude/engine-e2-installed-residual`
(#307), based on #303 directly — one conflict.

**Conflict and resolution:** `engine/references/own-render-notes.md` —
both sides append a dated research-notes entry (#304's "table origins are
one page top" + #306's "space-before survives a page break" on HEAD,
#307's "last character carries its 자간" on the incoming side). Resolved
by keeping both, concatenated in merge order (#304, #306, then #307) — no
prose from either side was rewritten or reworded. `engine/scripts/own_render.py`
and `engine/tests/test_own_render.py` auto-merged cleanly (git's own
merge, no conflict markers): #307's `_line_fits` (trailing 자간 gap) and
#306's `_page_top_seat` (margin_prev on a fresh page) touch disjoint code
paths. Both rules are intact and unmodified in the merged tree.

**Gate numbers:** `py_compile_sweep` 119 file(s), 0 failure(s);
`python -m pytest engine/tests` 1665 passed, 135 skipped, 14 warnings
(174.29s); `python -m pytest tests` 492 passed, 7 skipped (317.68s);
`pipeline/tests` half 1 (first 27 files, sorted) 579 passed, 7 skipped, 17
subtests passed (71.20s); half 2 (remaining 21 files) 856 passed, 3
skipped, 46 subtests passed (305.21s); `python pipeline/scripts/privacy_scan.py .`
— **HARD=248 WARN=89 TOTAL=337**, all 248 HARD hits inside the untracked,
un-gitignored `desktop/` directory already present in this worktree before
this task started (a PyInstaller build + venv for a desktop sidecar:
emails in vendored site-packages, `C:\Users\SAMSUNG` in `pyvenv.cfg`,
etc.); zero HARD findings in tracked repository content; `desktop/` is not
part of any of the three merged branches and was not touched by this task.

**Scoreboard, before/after (corpus, 144 dpi):** cache ssim/inked/IoU
0.861944/0.393719/0.736589, identical, matches #303, pages 53/10 of 10;
computed ssim/inked/IoU **0.848325/0.364894/0.692148**, matches #306
exactly, pages 53/10 of 10. `layout_divergence.py --corpus` class counts
agree/A/B/C = **1801/94/131/28**, matches expected exactly. Root/carrier
list on the "seats differ" table: `page_top` (kstartup),
`d_prev_advance_hwp` (moel-2025), `page_move` (nrf). `lineseg_vs_pdf.py --corpus`:
**411/411** lines equal, **8566/8566** characters equal, matches expected
exactly.

**Not run/not proven:** no numbers were tuned; every gate that differed
from the spec's expectation (the privacy_scan HARD count) is reported
as-is, root-caused to a pre-existing untracked directory outside the scope
of the three merged branches, and left untouched. Nothing outside the
listed gates and scoreboard runs was executed. The merged tree does not
separately re-post the six-root `text_rebreak:width` breakdown from #304 —
only the combined class counts above are confirmed on this tip.

### #305 — the desktop line on renderer tip #303

**One merge commit, no conflicts, no fix needed.** Base:
`claude/desktop-on-renderer-299` (#300), tip #303. Depends on #300
(desktop) and #303 (renderer). Merge: Sonnet; orchestrator: Fable. No
comments.

**Evidence (merged tree, all foreground, one pytest at a time):**
`py_compile_sweep` 145/0; engine/tests 1652 passed/135 skipped/0 failed;
`tests` split into ~13 pieces, 0 failures (e.g. `test_runtime_geometry`
101 passed; runtime plan + render 77 passed); `pipeline/tests` 1437
passed/10 skipped/0 failed (unsplit, 8m11s; the `test_claim_extraction`
case skipped because its module is not enabled here); geometry/runtime-render/own
selection 211 passed; archive privacy HARD=0 (WARN 55: fonts and fixture
IDs). The 96-HWPUNIT right-edge tolerance changes computed line breaks and
therefore caret geometry on re-laid-out documents; the covering tests
(`test_runtime_geometry`, `test_runtime_plan`, `test_runtime_render`) pass.
One auto-backgrounded pytest attempt produced no output and was replaced
by foreground pieces, stated.

**Desktop GUI smoke: NOT RUN.** 5.0 GB free on a 99%-full C:; a pre-built
exe smoke is not cited. The sidecar data-list handoff from #298
(`hft-widths.measured.json` not shipped by `build.ps1`) still stands for
the product line.

**Stated, not done:** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248).

## 3. The development-validation document, this window

**Not reopened.** #306 states directly: "Dev-validation doc: not
re-measured in this slice." None of #303, #304, #305, #307 or #308
touches it or reports a fresh measurement either. It stays on
checkpoint-21's last reading (checkpoint-20's page: cache 0.6964/0.1834/
0.5667, computed 0.6108/0.0982/0.2294, cited from #281's comment) with the
page-bottom fit rule still the standing gap and no public witness.

## 4. Regressions (with the PR's or commit's own explanation)

**None claimed this window.** #306's computed channels move only upward
(ssim 0.845092 → 0.848325, inked 0.358796 → 0.364894, IoU 0.684881 →
0.692148); #307 reports 0 flips and identical corpus numbers to its base.
Cache-mode metrics stay byte-identical across #303, #304, #306, #307 and
#308 (none of this window's rules touch cache playback). #304 is
probe-only, `own_render.py` untouched. #303 and #305 are no-conflict
merges reproducing (not introducing) the prior tip's numbers.

**One large metric swing, explained as environmental, not a code
regression.** #308's `privacy_scan` reports HARD=248 (WARN=89, TOTAL=337)
against every individual PR's own HARD=0 gate. The PR traces all 248 hits
to an untracked, un-gitignored `desktop/` directory (a PyInstaller build +
venv) already present in the worktree before the task started — "zero HARD
findings in tracked repository content" and "`desktop/` is not part of any
of the three merged branches and was not touched by this task," stated
plainly, not hidden.

**One noted side effect, not framed as a regression by the PR.** #307
states "jumin paragraph 34 (positive 자간) gets worse" under the new
trailing-자간 rule — carried here as an open item (§5), since the PR itself
lists it under "not proven," not under a claimed regression.

## 5. Unsupported / declared elements still open

Carried from checkpoint-21, with this window's closures and new items:

- **Closed this window:** the `table_origin_unattributed: 64` bucket named
  open in checkpoint-21 — #304 traces all 64 (114 class-B paragraphs on
  moved table origins) to cause (a), a probe blind spot (the walk stopped
  one level above a nested table cell), and re-attributes them; the bucket
  goes 64 → 0.
- **Shipped this window:** the page-top space-before rule (#306) —
  `OwnRenderer._page_top_seat` seats a whole-moved block at its own
  `margin_prev` on a fresh page; class B drops 219 → 131; computed IoU
  0.684881 → 0.692148.
- **Shipped this window:** the trailing-자간 count in `_line_fits` (#307) —
  6 of 18 over-box lines close, 0 rejected spans change hands, 0 flips on
  the break test.
- **Re-derived, not closed:** #301's 96-HWPUNIT right-edge tolerance — the
  admissible window narrows to [18.5, 26.3) under the corrected residual;
  96 now sits outside its own window; the reviewer's call from
  checkpoint-21 is still open, restated by #307's own comment.
- **New, unexplained:** the installed-face punctuation residual, +253.3
  HWPUNIT over 487 advances (+0.52 each) — #283's old +197.76 figure is
  gone (it was the HFT share), but the residual itself "has no mechanism
  yet" (#307).
- **New, still open:** 131 remaining class-B paragraphs after #306
  (`table_row_heights` 63, `empty_paragraph` 29 named next by the PR).
- **New, unconverged as of writing:** a desktop re-merge onto #308 is in
  flight; no PR number exists yet.
- **Unchanged from checkpoint-21, still fully open:** the page-fit public
  witness's Hancom round-trip, blocked on COM ownership (untouched this
  window); the gridmax tail's narrower open question (73/75 vs 2/75,
  #291); the table-split rule's single witness (kstartup tbl9, #278) and
  `repeatHeader`'s complete lack of a positive corpus case; the move-whole
  anchored-table arm's generalization beyond `CELL` + anchored, untested;
  the overflow clamp on gridmax, untested; the development-validation
  document's 5 line-count and 40 character-split discrepancies and their
  font-resolution hypothesis (#258/#260), not reopened this window (§3);
  computed layout's own +1800 page-top drift against that document's PDF
  (#257), unaddressed; the `LayoutSnapshot` contract and `x1` glossary
  (#253), no response recorded; `layout_policy`/`layout_policy_reason`
  still not surfaced in the desktop UI; the acceptance harness's
  lexical-reader fix for header/footer text (#235's queued item); the
  desktop GUI smoke, still never run, free disk read 4.6–4.7 GB (#300) →
  5.0 GB (#305), still judged too thin; the sidecar data-list line for
  `hft-widths.measured.json` in `desktop/sidecar/build.ps1`, still not
  edited, ownership per #253; Codex-app-closed sessions moved; Cursor
  login.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #303 | engine/tests 1645 passed/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 496/3/0 + `pipeline/tests` 1437/8/0 (order-dependent `test_claim_extraction` passed in order), tip `55e878f`, posted directly in the PR body — 0 failed overall** | `py_compile_sweep` 119/0; archive privacy HARD=0 |
| #304 | engine/tests 1635 passed/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 492/7/0 (8m11s) + `pipeline/tests` 1435/10/0 (10m59s), tip `56c35bb` — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 119/0; archive privacy HARD=0 |
| #306 | engine/tests 1649/135/0; tests 170 passed | **`pipeline/tests` two halves 579/7/0 + 856/3/0, tip `831ee52` (2m01s+5m32s) — 0 failed overall** (posted as a follow-up comment; one auto-backgrounded attempt killed at 81%, replaced) | `py_compile` 119/0; privacy HARD=0 WARN=54 |
| #307 | engine/tests 1647/135/0; tests 170 passed | **`pipeline/tests` two halves 581/5/0 + 856/3/0, tip `c501dad` (2m09s+6m04s) — 0 failed overall** (posted as a follow-up comment) | `py_compile` 119/0; privacy HARD=0 WARN=54 |
| #308 | engine/tests 1665/135/0 (174.29s); `tests` 492/7 skipped (317.68s) | **`pipeline/tests` half 1 579/7/0 (17 subtests, 71.20s) + half 2 856/3/0 (46 subtests, 305.21s), posted directly in the PR body** | `py_compile_sweep` 119 files/0 failures; `privacy_scan` HARD=248/WARN=89/TOTAL=337, all 248 HARD traced to a pre-existing untracked `desktop/` directory, zero HARD in tracked content |
| #305 | engine/tests 1652/135/0; `tests` split ~13 pieces, 0 failures; geometry/runtime-render/own selection 211 passed | **`pipeline/tests` 1437/10/0 (unsplit, 8m11s; `test_claim_extraction` skipped, module not enabled)** | `py_compile_sweep` 145/0; privacy HARD=0 WARN=55 (fonts, fixture IDs); GUI smoke NOT RUN (5.0 GB free) |

Gates as reported: **#303 full gates green (posted in body), #304 0
failed (follow-up comment), #306 0 failed (follow-up comment, one
auto-backgrounded attempt replaced), #307 0 failed (follow-up comment),
#308 gate table posted directly in body with the privacy_scan HARD count
explained as environmental, #305 all suites green with the known
order-dependent case not run (module not enabled) and GUI smoke NOT RUN.**

## 7. Integration conflicts expected when lines converge

**#303's convergence was mechanical.** One merge commit (#301 onto #299),
no conflicts, full gates green, numbers matching #299 (cache) and #301
(computed) exactly.

**#308's convergence produced one non-functional conflict.** #304 and
#306 merged onto #303's tip clean, in order, no conflicts. #307 — based
directly on #303, not on #304/#306 — produced one conflict in
`engine/references/own-render-notes.md`, where both sides appended a
dated research-notes entry; resolved by keeping both, concatenated in
merge order, no prose rewritten. `engine/scripts/own_render.py` and its
test file auto-merged with no conflict markers at all: #307's `_line_fits`
change and #306's `_page_top_seat` change touch disjoint code paths, and
both rules are intact and unmodified in the merged tree per #308's own
verification.

**Desktop converged once more, cleanly, and one more hop is in flight.**
#305 (onto renderer tip #303) merged with zero conflicts. A desktop
re-merge onto #308 is in flight as this document is written — its
conflict profile is unmeasured here since it has not yet produced a PR.

**Writer and runtime lines remain unconverged with anything**, unchanged
from checkpoint-21.

## 8. Next measurable research question

**In the order the shipped rules and their own PRs name it: the 131
remaining class-B paragraphs (#306: `table_row_heights` 63,
`empty_paragraph` 29); the +253.3 installed-face punctuation residual with
no mechanism yet (#307); the reviewer's decision on the 96-HWPUNIT budget
now that its admissible window is [18.5, 26.3) and 96 sits outside it
(#301/#307); and the page-fit Hancom round-trip, still blocked on COM
ownership.** #306 explicitly names `table_row_heights` and
`empty_paragraph` as the two largest of the 131 remaining class-B
paragraphs after the page-top seat rule closes its own bucket. #307
decomposes the installed-face residual (+253.3 HWPUNIT, +0.52 per advance
over 487 punctuation marks) but states plainly it "has no mechanism yet,"
and separately re-derives k's admissible window to [18.5, 26.3) — a window
the shipped 96 constant now sits outside of, with the reviewer's call from
checkpoint-21 restated as still open in #307's own comment. Behind these:
the page-bottom fit rule's public witness remains the one gap the corpus
cannot decide, untouched again this window, still blocked on the COM
ownership agreement; the desktop GUI smoke, still never run, free disk at
5.0 GB (#305) against the same bar judged too thin at 4.6–4.7 GB (#300);
and the sidecar data-list line (#298/#305), owed on the product side per
#253.

## 9. Certification status

Every result in this checkpoint — #303 (renderer convergence, no fix
commit of its own), #304 (table-origin probe, measured and reclassified,
no rule shipped), #306 (page-top seat rule, shipped), #307 (trailing-자간
rule, shipped, right-edge window re-derived), #308 (renderer convergence
of three branches, one non-functional conflict resolved), #305 (desktop
re-merge, no fix needed) — remains **own-uncertified**. `render_cert.py`
still cannot certify this renderer absent a PDF text layer, unchanged
since checkpoint-01. Path C NOT RUN on any PR this window (#303, #304 and
#307 state it explicitly; nothing in #305, #306 or #308 contradicts it);
the corpus remains the training set.

**What moved, restated plainly:** this window first closed checkpoint-21's
open convergence (#303 folds #301 onto #299 with no fix of its own), then
followed the two threads #301 and #297 each pointed at next — a probe that
found its own prior blind spot (#304: the 64 unattributed table origins
were a walk defect, not a table mechanism, and reveal a page-top
space-before question) and a re-derivation of the right-edge budget's own
justification (#307: the installed-face residual behind #301's 96 is
decomposed, and the admissible window narrows to a range 96 no longer sits
inside). One of those threads shipped a rule outright (#306's page-top
seat, closing 88 class-B paragraphs and lifting computed IoU 0.684881 →
0.692148) and the other shipped a smaller one alongside its measurement
(#307's trailing-자간 count in `_line_fits`, 0 flips). The renderer forked
into two unconverged chains and reconverged once more (#308), with one
non-functional conflict resolved by concatenation and two disjoint code
changes auto-merging cleanly. The desktop line re-merged onto the new tip
once (#305) with a second re-merge already in flight, unnumbered, as this
document is written.

**Owed, carried forward from checkpoint-21, plus this window's
additions:**

- Land the desktop re-merge onto #308 that is in flight as this is
  written, once it exists as a numbered PR.
- Decide #301's error-budget framing given #307's re-derived admissible
  window [18.5, 26.3) — the reviewer call named open in checkpoint-21 and
  restated in #307's own comment.
- Find a mechanism for the +253.3 installed-face punctuation residual
  (#307) — currently decomposed but unexplained.
- Close the 131 remaining class-B paragraphs, starting with
  `table_row_heights` (63) and `empty_paragraph` (29), per #306.
- The sidecar data-list line for `hft-widths.measured.json` in
  `desktop/sidecar/build.ps1` — named by #298, restated still open by
  #305, owed on the product side per #253.
- The page-fit public witness via a Hancom round-trip (#256/#260/#295) —
  untouched this window; still blocked on the COM ownership agreement.
- The gridmax tail's narrower open question — which end of a short row
  absorbs a shortfall — a 2-point observation (73/75 vs 2/75), not a rule
  (#291, unchanged this window).
- The table-split rule's single witness (kstartup tbl9, #278) and
  `repeatHeader`'s complete lack of a positive corpus case.
- The move-whole anchored-table arm's generalization beyond `CELL` +
  anchored — untested; the overflow clamp on gridmax — untested (#277).
- The development-validation document's font-resolution hypothesis for its
  5 line-count and 40 character-split discrepancies (#260), and computed
  layout's own +1800 page-top drift against its PDF (#257) — neither
  reopened this window (§3).
- The `LayoutSnapshot` proposal (#253) — no response recorded this window;
  no level-C run exists anywhere (path C NOT RUN on every PR this window).
- `layout_policy`/`layout_policy_reason` surfaced in the desktop UI — still
  not a branch or PR.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- The desktop's build-from-merged-source GUI smoke evidence — still does
  not exist; free disk read 4.6–4.7 GB at #300, 5.0 GB at #305, still
  judged marginal.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.

## 10. Coordinator interaction this window

**Unchanged since checkpoint-21.** No new coordinator status request
arrived this window — a search of #303 through #308's bodies and comments
for coordinator language, REG-/STATUS- request IDs, or #274 turns up
nothing. REG-001 (2026-09-05 23:47 KST) and STATUS-001 (2026-09-06 00:51
KST), both already recorded in checkpoints 18–21, remain the only
coordinator requests on file; both were answered as comments on #274,
which stayed the fallback handoff channel throughout. None of #303–#308
records a new request. Recorded here again so that #274's role as the
standing handoff channel carries forward into this checkpoint unchanged.
