# Checkpoint 15 — the two named-but-unfixed findings from checkpoint 14 both closed, and the residual that motivated a withdrawn hypothesis is explained

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-14`
(this branch, `claude/docs-checkpoint-15`, is cut from `claude/docs-
checkpoint-14` and stays unmerged). Covers #260
(`claude/engine-e2-textpos-cells`: the cache reader now counts the cells
`hp:lineseg@textpos` counts — char controls occupy 1 cell, extended
controls 8, `hp:lineBreak` pinned to 1 by the PDF oracle — closing the
control-cell mis-slicing bug named in checkpoint 14; the corpus's 25
mis-split paragraphs go to 0; the cache scoreboard moves toward the PDF
on exactly the five affected forms), #261
(`claude/engine-e2-empty-paragraph-height`: closes checkpoint 14's other
named-not-fixed finding — an empty paragraph with no cached lineseg is
now one line at its declared height, taken from a 101/101 corpus rule
and a synthetic probe that goes from 165/231 wrong seats to 0/231; the
corpus and render-check-01 scoreboards do not move, because no corpus or
render-check paragraph is both empty and uncached), and #263
(`claude/engine-e2-percent-residual`: Hancom quantises PERCENT leading to
a 4-HWPUNIT grid, rounding halves away from zero — 3214/3214 cached
linesegs now match exactly; the seat pass's class-B paragraph count
falls 538 → 320, and the ±1–3 HWPUNIT first-seat divergences named since
checkpoint 13 are gone; the cache scoreboard is byte-identical and the
computed raster is flat except `ssim_inked`, which falls slightly — a
measured, explained non-regression, stated as such). Desktop (#262) is a
re-merge onto the renderer tip *as of #261* (one slice behind this
checkpoint's own renderer tip, #263): no textual conflict, one semantic
clash between the desktop's OWPML `address` dict and the divergence
tool's flat paragraph index, fixed by giving the tool's index the slot
and renaming the desktop's dict to `owpml_address`; GUI smoke was **not
run** (disk too thin to build) and the pre-built-exe smoke from earlier
checkpoints is not cited as evidence here either. Writer line (#224 →
#235 → #238 → #239) and runtime line (#204) did not move this window.

## What changed since checkpoint-14

| metric | checkpoint-14 | checkpoint-15 | moved in |
|---|---|---|---|
| renderer-line tip | #258 (`8c35105`) | **#263** (`647e5f0`) — a linear three-PR extension: #260 → #261 → #263 | #260, #261, #263 |
| control-cell mis-slicing in our own cache reader | named, fix named, **not shipped** | **fixed**: `Paragraph` now builds a cell stream (`cell_start`, `cell_count`, `char_of_cell`, `cell_of_char`, `lineseg_spans`) counting the same cells `hp:lineseg@textpos` counts; corpus mis-split paragraphs 25 → 0 (21 char-control, 4 extended); the PDF-comparable subset 18/54 → 0/54 | #260 |
| empty paragraph with no cached lineseg | block height 0 from `_flow_lines`, found, not fixed | **fixed**: one line at its declared height (`vertsize` = tallest run `charPr@height`, advance from the paragraph's own `lineSpacing`), pinned 101/101 on the corpus's empty paragraphs, 0 counter-examples; public probe 165/231 → 0/231 wrong seats | #261 |
| PERCENT leading residual (±2 HWPUNIT, #247, unexplained since checkpoint-06-adjacent work) | shown, not explained | **explained and fixed**: Hancom quantises leading (not advance) to a 4-HWPUNIT grid, halves away from zero — `spacing = 4 × round(height × (value − 100) / 400)`; 3214/3214 cached linesegs now match exactly (previously 2146/3214 under every whole-HWPUNIT rounding tried) | #263 |
| seat-pass class-B paragraphs | not tracked at this resolution before #263 | **538 → 320** after the PERCENT fix; agree 1155 → 1371; the ±1–3 HWPUNIT first-seat divergences on kstartup/moel-2013/moel-2025 named since checkpoint 13 are **gone** | #263 |
| the "+566 kept line" withdrawn in checkpoint 14 | withdrawn as PDF evidence (the export never drew it) | **corrected, not reopened** (#260): it still stands as *path-A* (save-time seat) evidence — Hancom's editor did seat a line box 566 HWPUNIT past the body bottom at save time, independent of what it exported a minute later. The page-bottom fit question is reframed as a path B (computed) vs path A (cache) agreement question, not a PDF question; `vertsize − spacing` remains the only candidate fitting every corpus break plus this witness; still a costed, unapplied proposal | #260 |
| development-validation document's 5 one-line-shorter export paragraphs and 40 ±1 character-split paragraphs | named, cause unknown, flagged to re-examine after the control-cell fix | **re-examined, unchanged**: still 5 and 40 after #260's fix — the corpus's own mis-splits all closed, so these are **not** our reader. New candidate cause, consistent but not proven: the package declares HFT faces with `substFont` 한컴바탕 (the face the editor laid text out with) 13 times, but the exported PDF embeds only Batang / Gulim / HancomEQN — export-time font resolution to a different advance table | #260 |
| desktop line | unchanged, six renderer slices behind (#248 on #245) | **moved**: #262 re-merges onto the renderer state as of #261 — one slice behind this checkpoint's tip (#263); one semantic clash found and fixed (OWPML `address` dict vs the divergence tool's flat index); GUI smoke still **not run** | #262 |
| computed layout's own +1800 page-top drift vs the development-validation PDF (named in #257, still open at checkpoint 14) | open | **not addressed this window** — no PR in this checkpoint touches it | — |
| writer line | unmoved since checkpoint-06 | **still unmoved** | — |
| runtime line | unmoved since checkpoint-06 (#204) | **still unmoved** | — |

## 1. Branch DAG

Renderer line, still a straight chain off checkpoint-14's tip — no
siblings, no merge this window on the renderer side itself:

| PR | branch | base | slice |
|---|---|---|---|
| #258 | `claude/engine-e2-lineseg-vs-pdf` | `claude/engine-e2-usable-height` | renderer tip at checkpoint-14 (`8c35105`) |
| #260 | `claude/engine-e2-textpos-cells` | `claude/engine-e2-lineseg-vs-pdf` (#258) | counts the cells `lineseg@textpos` counts; fixes the control-cell mis-slicing bug named in #258; corrects the #257 "+566" record as path-A evidence, not PDF evidence |
| #261 | `claude/engine-e2-empty-paragraph-height` | `claude/engine-e2-textpos-cells` (#260) | closes the #255 finding: an empty paragraph without a cache is one line at its declared height |
| **#263** | `claude/engine-e2-percent-residual` | `claude/engine-e2-empty-paragraph-height` (#261) | **explains and fixes the PERCENT leading residual on a 4-HWPUNIT grid; this is the renderer tip (`647e5f0`).** |

Desktop line: one new PR this window, forked from #261 — one slice
behind the renderer's own tip (#263).

| PR | branch | base | note |
|---|---|---|---|
| #262 | `claude/desktop-on-renderer-261` | `claude/desktop-on-renderer-245` (#248) | re-merges the desktop onto the renderer chain through #261 (#250 → #252 → #255 → #256 → #257 → #258 → #260 → #261); fixes one semantic clash (OWPML `address` dict vs the divergence tool's flat index) found only on the merged tree; GUI smoke **not run** |

Docs line: no new docs PR this window (this checkpoint document itself
is the docs-line artifact).

Writer line, unchanged from checkpoint-14 — still #224 → #235 → #238 →
#239, no new PR this window.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` (each
off its own window's renderer tip).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #260 — the cache reader now counts the cells `lineseg@textpos` counts

**Path A rendering fix with a public basis** (the paragraph character
stream includes inline controls: char controls occupy 1 cell, extended
controls 8 — HWP 5.0 / OWPML), pinned on the corpus by two cache-only
constraints over 2995 lineseg-carrying paragraphs: *reach* (widths must
reach the largest textpos) and *boundary* (every textpos is some
element's first cell). Old model: 3 reach + 3 boundary failures —
exactly the three documented `textpos_past_end` cases. New model: 0 and
0.

**Element → cells, pinning basis:** `t` 1 per char; `lineBreak` 30 across
20 paragraphs → **1** (corpus admits 0–1, the PDF oracle admits only 1);
`fwSpace` 8/7 → 1 (admits 0–7); `colPr` 35/32 → **8** (7 would put 9
characters in a 7136 box); `fieldBegin`+`fieldEnd` 10+10/9 → 8+8 (pair
sums 14 and 15 refused; 16 pinned, the 8/8 split itself not); `tbl`
87/80 → 8 (corpus admits 4–8); `tab` 15/3, `secPr` 13/10,
`rect`/`pic`/`equation` 14/7, `header`/`footer`/`newNum`/`autoNum`/
`pageNum`/`footNote`/`endNote` 19/5 → 8, **no corpus constraint**;
`markpenBegin`/`End` → 0 (span markers); `nbSpace`, `hyphen`,
`titleMark`, `insert*`/`delete*`, `bookmark`, `indexmark`, `dutmal`,
`compose`, `hiddenComment`, `pageHiding` absent from the corpus,
**untested**.

**Fix.** `Paragraph` builds a cell stream beside `chars` (`cell_start`,
`cell_count`, `char_of_cell`, `cell_of_char`, `lineseg_spans`); drawing
itself is untouched. Converted: `_render_cached_lines`, `_line_rows`,
`_object_line`, `stale_cache_reason`, `lineseg_agreement`,
`page_fit_probe._has_text`, `layout_divergence.cached_line_metrics`;
`textpos_past_end` now compares against `cell_count`; `lineseg_vs_pdf`
reads the same map. 8 synthetic tests, no integer pins.

**Measured.** Mis-sliced paragraphs (of 161 with ≥ 2 seats): admrul
1→0, jeongbo 1→0, kstartup 3→0, moel-2013 1→0, moel-2025 17→0, saeopja
2→0 — **25 → 0** (21 char-control, 4 extended); on the PDF-comparable
set 18/54 → 0/54. `lineseg_vs_pdf --corpus` stays 411/411, 8566/8566.
Scoreboard 144 dpi, cache: IoU 0.6458 → 0.6453, ssim 0.8309 → 0.8311,
ssim_inked 0.2762 → 0.2766, pair 0.8362 → 0.8364, page-count exact 9/10
→ 9/10 — exactly the five forms holding a mis-sliced paragraph moved;
ssim and ssim_inked rose on 4 of 5, IoU fell on admrul / kstartup /
moel-2025 and rose on jeongbo / saeopja. At character level the moved
lines now match the export (e.g. the break before 연락처 lands where
Hancom put it). computed byte-identical (0.6339 / 0.8243 / 0.2774 /
0.8478, 10/10). render-check-01 unchanged (96 dpi 6·37·6·2; 144 dpi
14·31·4·2; 9/9).

**Development-validation document (private, reused; aggregate and font
names only), re-run on this tip.** Unchanged: 127 compared, 122 equal
line count, 5 with one more cached line than the PDF, 40 equal-count
paragraphs whose split differs, 33.4 % of characters in agreeing lines,
median |dy| 59. **The cell fix, which closed all 25 corpus mis-splits,
closes none of these** — they are not our reader.

**Where they come from, consistent with but not proven.** The
package's header declares HY신명조, 명조 and 한양신명조 (HFT faces)
for its body runs, with `hh:substFont` = 한컴바탕 declared 13 times —
the face Hancom's editor actually laid the text out with. The exported
PDF embeds only **Batang**, **Gulim** and **HancomEQN**; page 1's body
text (1062 characters at 9.95 pt) is all `Batang`. Editor layout in
한컴바탕, export in 바탕: two advance tables, so lines fill by ±1
character and five paragraphs need one line fewer. The corpus forms
never show this because their body faces (함초롬/맑은 고딕 family)
resolve to the same font in both passes.

**Correction to the record on #257.** The "+566 kept line" was
withdrawn as *PDF* evidence, rightly — the export never drew it. As
*path-A* evidence it stands: Hancom's editor, at save time, seated a
line box at 70430 whose extent (71430) crosses the body bottom (70864)
by 566, and the seat after it says so. The page-bottom fit question is
therefore a computed-vs-cache agreement question (path B vs A), not a
PDF question, and on that footing #256's `vertsize − spacing` candidate
("a line may hang by its own trailing leading") still fits every corpus
break and this one witness, while `baseline`, `vertsize` and
`vertsize // 2` do not. The corpus has no page that decides it; it
stays a costed proposal until a public witness exists.

**Privacy WARN 50 → 54:** all four are `korean_student_id_proximity`
hits on HWPUNIT numbers beside Korean words in the new notes tables
(`own-render-notes.md` lines 2082–2083, 4754–4756) — layout
coordinates, not identifiers.

**Evidence:** `py_compile_sweep` 108/0; engine/tests 1418 passed / 135
skipped; pins + package + cleanroom + floors 170 passed; archive privacy
HARD=0 (WARN 50 → 54, explained above). **Full gate on this tip
(`980880f`):** `tests` 485 passed / 3 skipped / 0 failed (10m45s);
`pipeline/tests` 1437 passed / 8 skipped / 0 failed (10m46s). 0 failed
overall.

**Not proven:** `tab`, `nbSpace`, `hyphen`, `secPr` and the non-`tbl`
objects have no corpus witness; `tbl` is bounded 4–8, not pinned; table
cells never reach the PDF oracle, so the 4 extended-width splits are
checked against the cache only; `--lineseg-agreement` matched breaks
moved 80 → 79 (`compute_lines` has no notion of a forced break, so some
old agreement was two errors cancelling); the IoU fall on three forms
has no per-line attribution yet; the font-resolution explanation for the
development-validation document's 5-line and 40-split differences is
consistent, not confirmed.

### #261 — the empty-paragraph-without-a-cache block-height finding, closed

**Path B fix; rule taken from path A on the public corpus; path C NOT
RUN.**

**The rule, from the cache.** An empty paragraph is one line: `vertsize`
= the tallest `hh:charPr@height` its runs declare; the advance follows
the paragraph's own `hh:lineSpacing` exactly like a text line. Corpus:
**101** empty top-level paragraphs, each with one lineseg and one empty
run — `vertsize` 101/101, `textheight == vertsize` 101/101, `baseline ==
round(0.85 × vertsize)` 101/101, `spacing` 91/101 with the 10 misses
inside ±2 HWPUNIT (the PERCENT residual #247, measured on 883 of 2370
text lines — still open at this point in the chain, closed later by
#263). No counter-example. All 101 are PERCENT (one is `PERCENT 0`,
reproduced: 400 / −400). Object-only paragraphs confirmed separately at
63/63 (`vertsize == height + outMargin top + bottom`), untouched.

**Public probe** (Rigorloom-written; path A absent): grid charPr 10 /
12 / 15 pt × PERCENT 160 / 180 / 200, FIXED 2400, BETWEEN_LINES 600.
Seats off the analytic expectation **165/231 → 0/231**; #255's constant
−1600 offset is gone.

**Fix.** `_flow_lines`: a paragraph with no characters and no lineseg
gets one row from `_line_metrics(para, 0, 0)`. Cached paragraphs
untouched (computed mode still reads the cache for empty paragraphs
that have one; changing that would cost ≤ 2 HWPUNIT on 10 of 101). 16
tests (five spacing types × three heights + cache-still-wins), no
integer pins.

**Measured — nothing moved, and the reason is measured:** every corpus
empty paragraph carries a cache and render-check-01 has **zero** empty
paragraphs (all 227 `hp:p` put a character down), so scoreboard (cache
0.6453 / 0.8311 / 0.2766 / 0.8364; computed 0.6339 / 0.8243 / 0.2774 /
0.8478, 144 dpi), page counts, seat pass and render-check verdicts (96
dpi 6·37·6·2; 144 dpi 14·31·4·2; 9/9) are identical before and after to
six decimals. The change acts only on documents Rigorloom writes or
edits — which is exactly where computed layout is the default since
#244.

**Evidence:** `py_compile_sweep` 108/0; engine/tests 1434 passed / 135
skipped; pins + package + cleanroom + floors 170 passed; archive privacy
HARD=0. **Full gate on this tip (`761998d`):** `tests` 481 passed / 7
skipped / 0 failed (6m17s); `pipeline/tests` 1435 passed / 10 skipped /
0 failed (10m11s). 0 failed overall.

**Not proven:** no reference render confirms the drawn height (the only
documents the new path runs on have no Hancom export); FIXED and
BETWEEN_LINES have no corpus witness for an empty paragraph; multi-run
empty paragraphs untested against Hancom; the ±2 PERCENT residual is
still unexplained at this PR (closed two PRs later, in #263).

### #262 — desktop re-merge onto the renderer tip #261

**The desktop line on the renderer tip #261** (#250 → #252 → #255 →
#256 → #257 → #258 → #260 → #261, on top of #248). One merge commit
plus one fix commit.

**No textual conflicts.** One semantic clash, named and fixed: the
desktop renderer stamps an OWPML `address` dict (kind / atPara / table /
row / col) on every line box; the renderer line's new
`layout_divergence.py` keys paragraphs by a flat document-order index
and its tracing subclass used `setdefault("address", …)`, so on the
merged tree the dict stayed, and grouping (`dict` unhashable) and
sorting failed — 3 failed + 21 errors, all in
`test_layout_divergence.py`, none present on either parent alone. The
tool's index now takes the slot and the desktop's dict moves to
`owpml_address`, unchanged. Both consumers keep what they read.

**Evidence (merged tree):** `py_compile_sweep` 134/0; engine/tests:
1417 passed **before** the fix with the 24 named failures (3 failed +
21 errors); the re-run after the fix was stated as "appended below" in
the PR body, but as of this checkpoint **no comment has landed on
#262** — that re-run is pending. `tests` 1095 passed / 7 skipped (three
pieces); `pipeline/tests` 1437 passed / 10 skipped (three pieces);
Python-side runtime tests (`test_runtime_child_python`,
`test_runtime_geometry`, `test_runtime_module_check`,
`test_runtime_render`) passed; archive privacy HARD=0 (WARN 55: fonts +
fixture IDs).

**Desktop GUI smoke: NOT RUN.** C: had 4.5 GB free — above the stop
line but too thin for a clean cargo release + NSIS + PyInstaller build,
and a smoke on the pre-built exe is not evidence for this source
combination (the #248 correction, carried from checkpoint 14). The
claim "the app built from this tree renders and edits" stays open until
a build from this sha runs the smoke.

**Stated, not done:** `layout_policy` / `layout_policy_reason` still
not surfaced in the desktop UI (owed since #248; ownership per #253).

**Depends on:** #248 (desktop) and #261 (renderer). Merge: Sonnet; fix:
Fable. **No comments on this PR as of this checkpoint.**

### #263 — PERCENT leading lives on a 4-HWPUNIT grid

**Hancom quantises PERCENT leading to a 4-HWPUNIT grid, rounding halves
away from zero. Computed now equals the cache on all 3214 cached
linesegs.** Path B arithmetic taken from path A on the public corpus;
path C NOT RUN.

**Candidates against the cache** (exact matches / 3214 cached linesegs
— 2376 text lines, 838 empty paragraphs, 80 objects, all PERCENT, 172
distinct (height, value) cells): **`q4_leading` 3214**; `q4_advance`
and `q4_leading_half_up` 3209 (5 misses, all `value < 100`);
`q4_leading_half_even` 2516; `q2_leading` 2300; `q4_leading_trunc`
2228; twips 2158; every whole-HWPUNIT rounding of the gap — the shipped
rule, half-up, floor, ceil, half-even, hundredth-pt, advance-half-away —
**2146**; `q8_leading` 1800. The unit was never the issue; the grid is:
all 3214 cached `spacing` values are multiples of 4, while cached
`vertsize` is a multiple of 4 on only 3161.

**Formula:** `spacing = 4 × round(height × (value − 100) / 400)`,
halves away from zero. It is the *leading* that is quantised, not the
advance. The tie rule is pinned by 5 lines, all with `value < 100`
(gianmun-1ho 1500 @ 90 and saeopja 300 @ 50 → −152; saeopja 900 @ 90 ×
3 → −92; both rivals give −148 / −88).

**Fix.** `_line_metrics` via `own_render.percent_leading` and
`LEADING_QUANTUM`; FIXED / BETWEEN_LINES / AT_LEAST untouched (no
corpus witness). The empty-paragraph branch from #261 inherits it: 91
→ **101 / 101**. Tests pin the arithmetic at the boundaries; one
existing test went vacuous *because* admrul stopped diverging and was
moved to another small form, with the reason recorded. Also corrected
in the notes: the long-standing fourth invariant (`vertsize + spacing
== round(textheight × value / 100)` on "every PERCENT paragraph") was
never true — 2146 / 3214 — and is struck through in place.

**Measured, 144 dpi.** cache **byte-identical** (10 / 10 JSONs; 0.6453
/ 0.8311 / 0.2766 / 0.8364). computed: IoU 0.633897 → 0.633875, ssim
0.824293 → 0.824261, **ssim_inked 0.277430 → 0.277281 (down)**, pair
unchanged; five forms moved (kstartup inked −0.0023 dominates,
moel-2025 +0.0009); page counts unchanged everywhere (kstartup 21 / 22
cache, 22 / 22 computed); verdicts unchanged. **Seat pass:** class B
paragraphs **538 → 320**, agree 1155 → 1371, A / C unchanged; admrul
fully agrees; first-seat divergences kstartup 139 → 119 seats on 20 →
18 pages (its first is now a page move on p4, not −2 on p1), moel-2013
109 → 24 on 4 → 2 pages, moel-2025 141 → 77 — **the ±1–3 HWPUNIT
first-seat divergences are gone**; nrf unchanged. render-check-01
byte-identical (6·37·6·2 / 14·31·4·2, 9 / 9); `--lineseg-agreement`
byte-identical (it compares horizontal fields only).

**Honest reading of the raster numbers:** the geometry channel moved
decisively toward the cache while the pixel channels barely moved and
`ssim_inked` fell a little — the rasteriser weight floor and the
remaining class-B mechanisms dominate those channels, not leading. This
is a measured, explained non-regression, not an unexamined dip.

**Evidence:** `py_compile_sweep` 109/0; engine/tests 1442 passed / 135
skipped; pins + package + cleanroom + floors 170 passed; archive privacy
HARD=0. The PR body states "Full pipeline/tests gate: appended below"
— as of this checkpoint **no comment has landed on #263**; the full
gate is not confirmed and must not be read as green.

**Not proven:** no reference render confirms the grid (path C not
run); why the quantum is 4 HWPUNIT (0.04 pt) is unexplained; the corpus
is the training set; FIXED / BETWEEN_LINES / AT_LEAST have no witness;
every corpus height is a whole point; class B is still 320.

## 3. The development-validation document arc, across #255 → #256 → #257 → #258 → #260

Aggregate-only, no name or text from the document quoted anywhere below
— this is the same private, repeatedly-reused holdout named in prior
checkpoints, not independent unseen data.

- **#255 → #256 → #257:** recapped in checkpoint 14 — the +566 kept-line
  overhang motivated a page-bottom fit-rule hypothesis, then was
  withdrawn as PDF evidence once the document's own Hancom-exported PDF
  was read directly (it drew the paragraph in 6 lines, not the cache's
  7, and never crossed the body bottom).
- **#258:** redirected the question to whether the cache matches what
  Hancom exported at all — 122/127 compared paragraphs agree on line
  count, 40 of those also differ in character split by ±1 (consistent
  with, not yet shown to close by, the reader's control-cell bug), 5
  disagree on line count outright (genuine save-vs-export difference,
  cause unknown).
- **#260, this window:** re-ran the same comparison after fixing the
  corpus's control-cell bug. **All 40 ±1-character splits and all 5
  one-line-shorter paragraphs are unchanged** — the fix that closed
  every one of the corpus's 25 mis-splits closes none of this
  document's discrepancies, settling that they are not an artifact of
  our reader. A new, consistent-but-unproven cause is named: the
  package's declared body faces resolve (via `hh:substFont`) to
  한컴바탕 at save time but the exported PDF embeds only Batang / Gulim
  / HancomEQN — two different advance tables for the same nominal font,
  which would explain both the ±1-character splits and the five
  one-line-shorter paragraphs without invoking re-flow logic at all.
  **Also this window:** the "+566" number itself is not reopened as PDF
  evidence, but is explicitly reclassified as valid *path-A* (save-time
  seat) evidence — the editor really did seat a line 566 HWPUNIT past
  the body bottom before export re-broke the paragraph — which keeps
  #256's `vertsize − spacing` candidate alive as the only reading
  consistent with every corpus break plus this witness, still with no
  public witness of its own.

Net effect on the standing research question: the development-
validation document's residual discrepancies (5 line-count, 40
character-split) have now survived the fix that was the leading
candidate to explain them, which is itself informative — they point at
export-time font resolution, a mechanism entirely outside the render
geometry this project controls, rather than at anything correctable in
`own_render`.

## 4. Regressions (with the PR's or commit's own explanation)

**None newly introduced this window, by the PRs' own accounting.** #260
reports its measured raster deltas as ssim and ssim_inked rising on 4
of 5 affected forms and IoU falling on 3 of them — explained as the
corrected line splits moving pixels toward the PDF, not toward the
raster's own prior score, and confirmed against the PDF text directly
(the 연락처 break example). #261 reports every corpus and render-check
metric identical to six decimals, explained by the fact that no corpus
or render-check paragraph is both empty and uncached — the change
provably cannot move those scoreboards, and doesn't. #262's 3
failed / 21 errors were confined to the merge step itself (a semantic
clash absent from both parent branches individually), fixed before the
PR's own evidence section, and are not a regression on either parent's
tree. #263 explicitly names its own `ssim_inked` fall (0.277430 →
0.277281) as a **measured, explained non-regression**: the geometry
channel (seat pass, page counts) moved decisively toward the cache, and
the PR attributes the small pixel-channel dip to the rasteriser's
weight floor and the remaining class-B mechanisms, not to the leading
fix itself.

## 5. Unsupported / declared elements still open

Carried from checkpoint-14, with this window's closures, redirections
and new items:

- **Closed since checkpoint-14:** the control-cell mis-slicing bug in
  our own cache reader (#260, fixed and tested, 25 → 0 mis-split
  paragraphs on the corpus); the empty-paragraph-with-no-cached-lineseg
  block-height-0 finding (#261, fixed and tested, 101/101 on the
  corpus, 165/231 → 0/231 on the public probe); the ±2 HWPUNIT PERCENT
  spacing residual (#247, open since checkpoint-06-adjacent work — now
  explained as a 4-HWPUNIT leading-quantisation grid and fixed, #263).
- **Reclassified, not closed:** the page-bottom fit-rule hypothesis
  (withdrawn as PDF evidence in #257) — its "+566" witness is restored
  as valid path-A evidence in #260, keeping `vertsize − spacing` as the
  sole surviving candidate; it remains a costed, unapplied proposal
  with no public witness.
- **Re-examined, still open:** the development-validation document's 5
  genuine save-vs-export line-count differences and 40 ±1
  character-split paragraphs (#258) survive the control-cell fix
  unchanged (#260) — a font-resolution explanation (declared
  `substFont` 한컴바탕 vs PDF-embedded Batang/Gulim/HancomEQN) is named
  as consistent, not proven.
- **New, found and fixed within the merge itself:** the desktop's
  OWPML `address` dict vs the divergence tool's flat paragraph index —
  a semantic clash present only on the merged tree, fixed by giving the
  tool's index the slot and renaming the desktop's dict to
  `owpml_address` (#262).
- **Unchanged from checkpoint-14, still fully open:** computed layout's
  own +1800 page-top drift against the development-validation
  document's Hancom-exported PDF (#257) — not addressed by any PR this
  window; the paragraph-before-the-drift "predecessor draws nothing"
  mechanism (#252) — one boundary case (nrf), not generalized; the
  desktop's build-from-merged-source smoke evidence — still does not
  exist (now blocked on disk space rather than an untried build); the
  `LayoutSnapshot` contract and `x1` glossary (#253) — no response
  recorded this window; `layout_policy` / `layout_policy_reason` still
  not surfaced in the desktop UI; the holdout's underlying
  computed-vs-cache line-IoU gap; the full-width-advance line-box fix
  #242 costed and refused; the acceptance harness's lexical-reader fix
  for header/footer text (#235's queued item); Codex-app-closed
  sessions moved; Cursor login; `hp:ole`/`hp:chart`/`hp:container`/
  shapes/undecodable EMF-WMF placeholders; `DOUBLE_SLIM` border
  limitation; `hp:parameters` family; `hp:autoNum` inside a footer
  draws nothing (`F51`); `hh:tabPr` stops inside the MCE switch never
  read; the tier-3 raster's own `own-uncertified` status; Hancom's
  first-column endnote placement in a two-column section;
  `textpos_past_end` — now closed on all three previously-documented
  corpus cases by #260's fix, confirmed above.
- **New, owed:** #262's engine/tests re-run after its merge fix, stated
  as "appended below" but not yet landed as a comment; #263's full
  `pipeline/tests` gate, stated as "appended below" but not yet landed
  as a comment — neither should be read as green until the comment
  appears.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #260 | engine/tests 1418/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 485/3/0 + `pipeline/tests` 1437/8/0 — 0 failed overall** | `py_compile_sweep` 108/0; archive privacy HARD=0 (WARN 50→54, explained) |
| #261 | engine/tests 1434/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 481/7/0 + `pipeline/tests` 1435/10/0 — 0 failed overall** | `py_compile_sweep` 108/0; archive privacy HARD=0 |
| #262 | engine/tests 1417/0 before fix (24 named failures on the merge only); `tests` 1095/7 skipped (3 pieces); `pipeline/tests` 1437/10 skipped (3 pieces); runtime tests passed | **re-run after the fix stated as "appended below" — not yet posted as a comment; PENDING** | `py_compile_sweep` 134/0; archive privacy HARD=0 (WARN 55: fonts + fixture IDs) |
| #263 | engine/tests 1442/135 skipped; pins+package+cleanroom+floors 170 | **stated as "appended below" — not yet posted as a comment; NOT CLAIMED GREEN** | `py_compile_sweep` 109/0; archive privacy HARD=0 |

#260 and #261 each report their own landed, zero-failure full-gate
comment on this checkpoint's chain. #262 and #263 are, at the time this
checkpoint was written, the first two PRs in this line whose full gate
is **not yet confirmed** by a posted comment — both bodies promise the
result "appended below," and neither PR carries any comment as of this
writing.

## 7. Integration conflicts expected when lines converge

**Renderer line did not converge siblings this window — it extended
linearly**, same shape as checkpoint-14: #260, #261 and #263 each
forked from the immediately preceding PR, so there was no renderer-side
merge to perform and no textual or semantic conflict between them.

**Desktop converged onto the renderer chain this window (#262)** —
the one integration event of this checkpoint. It surfaced exactly one
semantic clash (the OWPML `address` dict vs the divergence tool's flat
paragraph index), present only on the merged tree and absent from
either parent, fixed by a one-line rename. Desktop remains **one**
renderer slice behind the tip: it merged through #261, and #263 landed
after.

**Writer and renderer lines remain unconverged**, unchanged from
checkpoint-14.

**Runtime line is untouched and unconverged with anything**, unmoved
since #204 (checkpoint-06).

## 8. Next measurable research question

**What the remaining 320 class-B paragraphs are made of, and whether a
Hancom round-trip can manufacture a public path-A witness for the
page-bottom fit rule — in that order, as named by #263 and #260
themselves.** #263 closed the PERCENT-leading mechanism that accounted
for the largest share of class-B divergence (538 → 320) but leaves the
residual unattributed; the development-validation document's own
residual −10 / −6.7 / −20 px clusters (named in earlier work, moel-2025)
are the likely next place to look, since the leading fix removed the
±1–3 HWPUNIT first-seat noise that was previously confounding them.
Second, #260's font-resolution hypothesis for the development-
validation document's 5-line and 40-split discrepancies (한컴바탕
declared vs Batang/Gulim/HancomEQN exported) is named but not tested —
confirming it would need either a font-metrics comparison or a
Hancom round-trip of the same package under a controlled substitute
font. Third, #260's restored path-A "+566" witness for `vertsize −
spacing` still has no public counterpart; #260 states plainly that
manufacturing one would need a Hancom round-trip of the page-fit probe,
which needs COM ownership agreement not yet in place. None of the three
is measured yet. Separately, computed layout's own +1800 page-top drift
against the development-validation document's PDF (#257) remains open
and untouched this window.

## 9. Certification status

Every result in this checkpoint — #260 (control-cell fix + development-
validation re-run + #257 correction), #261 (empty-paragraph block-
height fix), #262 (desktop re-merge + merge-only fix), #263 (PERCENT
leading quantisation fix) — remains **own-uncertified**. #260, #261 and
#263 each change `own_render`'s behavior; none changes a certified
renderer surface. `render_cert.py` still cannot certify this renderer
absent a PDF text layer, unchanged since checkpoint-01.

**What moved, restated plainly:** this window closed both of checkpoint
14's named-but-unfixed findings (the control-cell reader bug and the
empty-paragraph block-height-0 case) and, in doing so, also explained
the PERCENT leading residual that had been open even longer — three
mechanisms closed in a single three-PR chain, each pinned by a public
corpus rule with zero counter-examples and confirmed on a synthetic
probe. The one number that did **not** move under the strongest of
these fixes — the development-validation document's 40 ±1-character
splits and 5 one-line-shorter paragraphs — is itself a result: it rules
out our own reader as the cause and points at export-time font
resolution instead, a mechanism outside this project's own render
geometry. The desktop line converged onto the renderer chain for the
first time since #248, surfacing and fixing one merge-only semantic
clash, but its GUI smoke evidence still does not exist, now for a
resource reason (disk space) rather than an untried build. Two PRs in
this window (#262, #263) have gate results promised in their own bodies
but not yet posted as comments; both are recorded here as pending, not
green.

**Owed, carried forward from checkpoint-14, plus this window's
additions:**

- The remaining 320 class-B paragraphs after the PERCENT-leading fix
  (#263) — unattributed, likely candidate: the development-validation
  document's residual px clusters.
- A public path-A witness for the `vertsize − spacing` page-bottom fit
  candidate (#260, #256) — needs a Hancom round-trip, needs COM
  ownership agreement not yet in place.
- The development-validation document's font-resolution hypothesis for
  its 5 line-count and 40 character-split discrepancies (#260) —
  consistent, not tested.
- Computed layout's own +1800 page-top drift against the development-
  validation document's Hancom-exported PDF (#257) — unresolved,
  untouched this window.
- #262's engine/tests re-run after its merge fix — stated "appended
  below," not yet posted.
- #263's full `pipeline/tests` gate — stated "appended below," not yet
  posted; not to be treated as green until it lands.
- The desktop's build-from-merged-source smoke evidence (#248, #262) —
  does not exist yet; now blocked on disk space.
- The `LayoutSnapshot` proposal (#253) — no response recorded this
  window; no level-C run exists anywhere.
- `layout_policy` / `layout_policy_reason` surfaced in the desktop UI —
  still not a branch or PR.
- The paragraph-before-the-drift "predecessor draws nothing" mechanism
  (#252) — one boundary case (nrf), not generalized.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.
