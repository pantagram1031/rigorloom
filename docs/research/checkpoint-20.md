# Checkpoint 20 — the gridmax tail is four cells not a tie, a measured HFT width table becomes the metric for HFT-declared runs, and the renderer converges to one tip again

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-19` (this
branch, `claude/docs-checkpoint-20`, is cut from `origin/claude/docs-checkpoint-19`
and stays unmerged). Covers #290 (`claude/engine-e2-converge-07`: convergence
of checkpoint-19's two open renderer siblings, #286 + #288 — one clash the
merged tree alone could show, a two-line `cell_hwp` fix in `pdf_face_probe.py`
after #283's schema rename; full gates green), #291 (`claude/engine-e2-gridmax-tail`:
the gridmax tail is four cells in one saeopja table, not a tie — 5 contested
boundaries corpus-wide, `max` wins all five; the PDF backs the cache 3/3; no
fix ships; open question — which end of a short row absorbs its shortfall,
73/75 corpus rows say the last), #292 (`claude/engine-e2-hft-widths`: a
**measured** HFT width table — 5 faces × 226 (face, code point) pairs, 0
conflicting widths, declared measured from Hancom's own public PDF output —
becomes the metric for `hh:font@type="HFT"` runs via `_hft_advance_hwp`;
`text_rebreak:width` 165 → 100, moel-2013's contribution 22 → 0; punctuation
over-measure +15013 → +136; computed IoU 0.6651 → 0.6842, cache ssim_inked
0.3881 → 0.3937, cache IoU −0.0009 stated against every other channel rising;
a three-way score — table alone / #283's full-width rule alone / both — has
"both" better on widths but the table alone winning the break test, 21 vs
19, and shipping) and #294 (`claude/engine-e2-converge-08`: convergence of
#291 and #292 onto the #290 tip — one advance seam, `_hft_advance_hwp`
consulted first for HFT-declared runs, `_metric_font_for_pt` with #285's
bold rule as the fallback; full gates green, cache 0.8619/0.3937/0.7366,
computed 0.8447/0.3589/0.6842, 10/10 pages). Desktop #293
(`claude/desktop-on-renderer-290`, on renderer tip #290) re-merged cleanly;
a further re-merge onto #294 is **in flight** — a local, unpushed branch
`claude/desktop-on-renderer-294` (tip `16b31b7`) exists in this worktree with
no PR opened yet, so it must not be read as a landed or reviewed result.
Writer line (#224 → #235 → #238 → #239) and runtime line (#204) did not move.

## What changed since checkpoint-19

| metric | checkpoint-19 | checkpoint-20 | moved in |
|---|---|---|---|
| renderer-line tip | **forked** — #286 and #288, unconverged | **converged, then re-forked, then converged again**: #290 folds #288 into #286 (`cell_hwp` fix); #291 and #292 branch off #290 as research slices; #294 converges both back onto #290 — **single tip, #294**, mod the in-flight desktop hop | #290, #291, #292, #294 |
| the gridmax tail (4 saeopja-48027 cells, #277) | unexplained, fully open | **measured to the end, still no fix**: 4 cells in one table (rows 7/8 of saeopja table 3), not a tie — the two rows' edge sets are disjoint from every other row's; corpus-wide only 5 of 256 interior boundaries are contested and `max` wins all five; the PDF's row-band strokes back the cache 3/3; open — which end of a short row absorbs the shortfall (73/75 rows say the last cell, 2 say the first) | #291 |
| the PDFs' HFT faces (#288: identified, not shipped, 93.0 % cap) | identified, no fix — no installed/bundled face reproduces them, one-width-per-class tops at 93.0 % against the 99 % gate | **a measured per-face width table ships as the metric** for HFT-declared runs: 226 (face, code point) pairs across 5 faces, 0 conflicting widths, verified to median \|Δ\| 0.0021 em on 206 anchored segments; 494 Type-3 code points still unattributable (in-cell); 8 of 13 declared HFT faces have no attributed code point at all | #292 |
| advance computation | one seam, `_advance_hwp` (#286) | **duplicated once more, then re-unified**: #292 grew its own pre-#283 `_advance_hwp` on its own branch; #294 resolves it back to one seam, with `_hft_advance_hwp` consulted first for HFT-declared runs and the bold/metric fallback (#285) behind it | #292, #294 |
| `text_rebreak:width` root | 165 | **100** (moel-2013's share 22 → 0) | #292 |
| punctuation over-measure | +15013 | **+136** | #292 |
| corpus raster, 144 dpi, cache (ssim / ssim_inked / line IoU, pages exact) | 0.8607 / 0.3881 / 0.7375, 10/10 | **0.8619 / 0.3937 / 0.7366, 10/10** (#294 tip; #290's own tip, before #292, still read 0.8607/0.3881/0.7375 on 10/10, and #291 recorded the same triple on the full 53/53-page corpus set it now scores against) | #292, #294 |
| corpus raster, 144 dpi, computed | 0.8402 / 0.3515 / 0.6651, 10/10 | **0.8447 / 0.3589 / 0.6842, 10/10** | #292, #294 |
| desktop line | #284 on #281, #287 on #286 | **re-merged again**: #293 onto renderer tip #290 (no conflicts, all suites green, GUI smoke still NOT RUN — 5.6–5.7 GB free); a further hop onto #294 is **in flight, unpushed, no PR** (`claude/desktop-on-renderer-294`, tip `16b31b7`) | #293 |
| writer line | unmoved since checkpoint-06 | still unmoved | — |
| runtime line | unmoved since checkpoint-06 | still unmoved | — |

Cache/computed pages read 10/10 in every PR's own before/after pair this
window; #291's own measurement pass separately confirms the same triple
holds at 53/53 on the wider cell-boundary corpus it scores cells against
(404 exact / 1605 near of 1609 cells) — the two counts are not in tension,
they are different denominators (reference-PDF pages vs. cell-boundary
corpus rows).

## 1. Branch DAG

Renderer line: **the #286/#288 fork checkpoint-19 left open closes in #290;
#291 and #292 branch off that new single tip as independent research slices;
#294 converges both back onto it, restoring a single tip.**

| PR | branch | base | slice |
|---|---|---|---|
| #290 | `claude/engine-e2-converge-07` | `claude/engine-e2-converge-06` (#286), merges in #288 | convergence: `pdf_face_probe.py` (written on #288's pre-#283 schema) crashed on the merged tree — `declared` was renamed to `cell_hwp` for the numeric cell field and reused for the face-name string; fixed by reading `cell_hwp` at the two numeric sites; full gates green |
| #291 | `claude/engine-e2-gridmax-tail` | `claude/engine-e2-converge-07` (#290) | measurement-only: the gridmax tail is 4 cells in one table, not a tie rule; no candidate rule beats what ships; `own_render.py` untouched |
| #292 | `claude/engine-e2-hft-widths` | `claude/engine-e2-type3-faces` (#288, branched **before** #290's `cell_hwp` fix and before #283's seam) | ships a measured per-face HFT width table as the metric for HFT-declared runs; its own body names the reconciliation the next hop owes |
| #294 | `claude/engine-e2-converge-08` | `claude/engine-e2-converge-07` (#290), merges in #291 and #292 | convergence: one advance seam, HFT table consulted first; `pdf_face_probe.py` merged clean, already reading `cell_hwp` — the schema recurrence #292's stale base risked did not happen |

Desktop line: one re-merge landed as a PR, one more in flight unreviewed.

| PR | branch | base | note |
|---|---|---|---|
| #293 | `claude/desktop-on-renderer-290` | `claude/desktop-on-renderer-286` (#287) | re-merge onto renderer tip #290; **no conflicts**, `own_render.py` unchanged by this hop; all suites green; GUI smoke **NOT RUN** (5.6–5.7 GB free, judged too thin) |
| — | `claude/desktop-on-renderer-294` (local, unpushed, **no PR opened**) | `claude/desktop-on-renderer-290` (#293), merges in #294 | **in flight**: tip `16b31b7` exists in this worktree only; touches `own_render.py`, `track_probe.py`, the HFT table and script, and their tests; not evidenced by any gate run recorded in a PR — must not be read as a landed or reviewed result |

Docs line: no new docs PR this window besides this checkpoint document itself.

Writer line, unchanged from checkpoint-19 — still #224 → #235 → #238 → #239.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` / `-16` / `-17` / `-18` / `-19` (each off its own
window's renderer state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #290 — converge #288 onto the #286 tip: the `cell_hwp` schema fix

**One merge commit plus one fix commit; full gates green.** No textual
conflict in the merge itself — the clash only showed once the merged tree
ran `pdf_face_probe.py`: `TypeError: can't multiply sequence by non-int of
type 'float'`, because #283 had renamed `OurMetrics.run()`'s numeric cell
field `declared` → `cell_hwp` and reused `declared` for the face-name
string. Not pre-existing: #288 alone runs clean and #286 carries no such
script. Fixed minimally, reading `run["cell_hwp"]` at the two numeric sites.
**Noted for the next hop:** the HFT width-table slice in flight (this became
#292) branched from #288 before this fix and will need the same two-line
change when it joins.

**Verified on the tip, all equal to #286 (144 dpi):** cache 0.8607/0.3881/
0.7375, pages 10/10; computed 0.8402/0.3515/0.6651, 10/10; `lineseg_vs_pdf`
411/411; `pdf_face_probe --no-identify` runs clean (844 code points, 785 on
a one-width-per-class reading, 93.0 %); render-check-01 6·37·6·2 at 96 dpi,
14·31·4·2 at 144, 9/9.

**Evidence, tip `5a2fa49`, posted directly in the PR body:** `py_compile_
sweep` 117/0; engine/tests 1561 passed/135 skipped; pins+package+cleanroom+
floors 170; `tests` 490 passed/7 skipped/0 failed; `pipeline/tests` 1435
passed/10 skipped/0 failed; archive privacy HARD=0.

Everything stays `own-uncertified`; path C NOT RUN anywhere; the corpus is
the training set.

**Depends on:** #286 and #288. No comments.

### #291 — the gridmax tail is four cells in one table, not a tie

**Measured to the end, no renderer change.** Path A oracle (cached
`horzsize` + inset) with the PDF's vertical rules as the x oracle; path C
NOT RUN; `own_render.py` untouched.

**The tail is 4, not 9:** #279 already closed the 47764 table's `x[17]`/
`x[24]` cells. What remains is saeopja table 3 (48027 wide, 12 columns,
every row declares 48008 — 19 short), rows 7/8: `c0+3` box 12002 vs cached
12018 (−16) and `c10+2` 12021 vs 12002 (+19).

**Not a tie.** Boundaries x3/x6/x10 are written by rows 7/8 and no other
row — the row shapes' edge sets are disjoint (r4 → 2,5,9; r7/8 → 3,6,10;
r11–21 → 1,4,7,8,11). Corpus-wide there are 256 interior boundaries and only
**5 contested**; `max` wins all five. Declared attributes are uniform
(`cellSpacing` 0, `hasMargin` 0, margins 141/141, no `rowSpan`). Cache
intervals vs ours: x3 [12018, 12021]/12002, x6 [24020, 24023]/24004, x10
[36022, 36025]/36006; every other boundary agrees. **PDF page 4** strokes
by row band: r7/8 at 12012, 24006, 36000; registration-free gaps x3−x2 PDF
107 (ours 81, cache 97–101), x6−x5 180 (162, 178–182), x10−x9 264 (243,
259–263) — **the PDF backs the cache 3/3**.

**Candidates scored (exact / on grid of 1609 / regressions vs global / vs
stretch / PDF rules at 50 HWPUNIT):** gridmax 404/**1605**/0/0/364 ·
gridexact 404/1605/0/0/364 · gridwide 395/1597/8/1 · gridfirst 393/1597/8/1
· gridmin 388/1559/46/27 · gridback 362/1427/182/153 · gridsnap 276/1236/
369/365 · stretch 391/1574/31/0/366. Nothing beats what ships. The narrower
open question: **which end of a short row absorbs its shortfall** — 73 of
75 corpus rows say the last cell, 2 say the first; a 2-point fit is not a
rule. Recorded, not resolved.

**Measurements unchanged:** cache 0.8607/0.3881/0.7375, 53/53 pages;
computed 0.8402/0.3515/0.6651, 53/53; `lineseg_vs_pdf` 411/411; cells 404
exact/1605 near of 1609; classes 1635/111/279/28; render-check-01 6·37·6·2/
14·31·4·2, 9/9.

**Not proven:** the four cells' mechanism; PDF absolute registration drifts
−13…−27 HWPUNIT, unexplained; `stretch` still leads the rule oracle by 2
strokes.

**Evidence:** `py_compile_sweep` 117/0; engine/tests 1561 passed/135
skipped; pins+package+cleanroom+floors 170; archive privacy HARD=0. **Full
gate, tip `d969f7f`** (posted as a follow-up comment): `tests` 490 passed/7
skipped/0 failed (6m55s) + `pipeline/tests` 1435 passed/10 skipped/0 failed
(12m32s), 0 failed overall. Comment states this PR is probe-only and joins
the renderer tip at the next convergence hop together with #292.

**Depends on:** #290. Worker: Opus; orchestrator: Fable.

### #292 — a measured HFT width table becomes the metric for HFT-declared runs

**Shipped.** PDF glyph positions as the oracle (#258); path C NOT RUN.
**Legal framing, stated explicitly:** widths only, measured from Hancom's
own public PDF output, declared as measured with coverage — no font data,
no outlines.

**The table** (`engine/references/fonts/hft-widths.measured.json`): 5 faces
× **226 (face, code point) pairs** from 2301 characters, **0 code points
with two widths**; 한양중고딕 160, HCI Poppy 22, 고딕 38, 한양신명조 5, 명조 1.
Verified against anchored pen distances on 206 segments: median |Δ| 0.0021
em, all within 0.02. 494 Type-3 code points remain unattributable (in-cell).
The two carriers named in checkpoint-19 (¶118, ¶141) are fully covered —
but only after rebuilding on the **metric slot**: both name 한양신명조 for
`symbol` and HCI Poppy for `latin`, and the first build had filed widths
under a name the renderer never asks for.

**Three-way score (exact widths installed/substituted; break matches
installed/other paragraphs; proven over-measures/2272):** current 23/103,
2/308; 48/113, 12/47; 49. **table alone 24/103, 0/308; 48/113, 21/47; 30.**
#283's full-width rule alone 23, 0; 48, 2; 92. Both together: 24, 7; 48, 19;
33. Carriers (ours − Hancom, HWPUNIT): ¶118 line 0 +1255 → table −1850/cell
+2977/**both −128**; line 1 +2 → −1659/+1684/**+23**; ¶141 +1148 → −1068/
+2302/**+85**. **"Both" is the better tree on widths, but the break test
picks the table alone (21 > 19), and the table alone ships.** The
substituted per-line median goes −120 → −382 until #283's rule is revisited
on top of this — stated as open, not fixed.

**Fix:** `_hft_advance_hwp` behind the `_advance_hwp` seam, gated on
`hh:font@type="HFT"` at `hwp_metric_slot`; uncovered code points fall
through to the previous metric. 5 tests, no integer pins. Three
pre-existing agreement pins updated with reasons, all upward; one
trailing-space hang value whose line re-broke; `_bold_metric_probe` now
forces TTF types, its own premise.

**Measured, 144 dpi.** cache IoU 0.7375 → 0.7366, ssim 0.8607 → 0.8619,
ssim_inked 0.3881 → **0.3937**, pair unchanged; computed IoU 0.6651 →
**0.6842**, ssim 0.8402 → 0.8447, ssim_inked 0.3515 → 0.3589, pair 0.8474 →
0.8460; pages 10/10 both. `lineseg_vs_pdf` 411/411. Classes 1635/111/279/28
→ **1713/98/214/28**; `text_rebreak:width` **165 → 100** (moel-2013's share
22 → 0); other roots unmoved. Punctuation over-measure +15013 →
**+136**. render-check-01 unchanged (6·37·6·2/14·31·4·2, 9/9) — declares 21
TTF faces and no HFT, a pure control.

**Not proven.** 226 pairs are an inventory of this corpus, not a rule; 8 of
13 declared HFT faces have no attributed code point (all in-cell);
metric-slot attribution extends #288's 22-character measurement rather than
re-measuring it; verification rests on 206 unstretched segments; **the
cache IoU dipped 0.0009 while every other channel rose** — stated plainly,
not hidden inside the aggregate.

**Evidence:** `py_compile_sweep` 118/0; engine/tests 1558 passed/135
skipped; pins+package+cleanroom+floors 170; archive privacy HARD=0. **Full
gate, tip `45c8ced`** (posted as a follow-up comment): `tests` 495 passed/3
skipped/0 failed (9m06s) + `pipeline/tests` 1437 passed/8 skipped/0 failed
(9m22s), 0 failed overall. Comment states the convergence hop onto #290
(single advance seam, `cell_hwp` fix) is in flight.

**Depends on:** #288 — branched before #283's seam; its own body states the
hop onto #290 must reconcile the seam and apply the `cell_hwp` fix. Worker:
Opus; orchestrator: Fable.

### #293 — the desktop line on renderer tip #290

**One merge commit, no conflicts, no fix needed.** Base:
`claude/desktop-on-renderer-286` (#287). `own_render.py` unchanged by this
hop (#290 is a schema fix plus a convergence merge, not a rendering change).

**Evidence (merged tree, one suite at a time, all foreground):**
`py_compile_sweep` 143/0; engine/tests 1568 passed/135 skipped/0 failed;
`tests` 1097 passed/7 skipped/0 failed (three chunks); `pipeline/tests` 1437
passed/10 skipped/0 failed (four chunks); geometry/runtime-render/own
selection 211 passed; archive privacy HARD=0 (WARN 55: fonts and fixture
IDs). A first background pytest attempt was discarded as unreliable on this
bench and rerun foreground — stated in the PR body.

**Desktop GUI smoke: NOT RUN.** 5.6–5.7 GB free on a 99 %-full C:, below
what a clean Tauri release build needs; a pre-built exe smoke is not cited.
The claim "the app built from this tree renders and edits" stays open until
a build from this sha runs the smoke.

**Stated, not done:** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248; ownership per #253).

**Depends on:** #287 (desktop) and #290 (renderer). No comments.

### #294 — converge #291 and #292 onto the #290 tip; one advance seam

**Two merge commits, no fix commit; full gates green.** Depends on #290,
#291 and #292.

**Conflicts:** `own_render.py` — #292 had grown its own pre-#283
`_advance_hwp` on its stale base; resolved to **one method**: the #283/#286
seam stays the single exit for every advance, `_hft_advance_hwp` is
consulted first for HFT-declared runs, and `_metric_font_for_pt` (carrying
#285's bold rule) is the fallback; the call site now passes `rel_sz`.
`own-render-notes.md` — two log sections collided, both kept in PR order.
`pdf_face_probe.py` merged clean and already reads `cell_hwp` (#290's fix)
— the schema recurrence #292's stale base risked did not happen.

**Verified on the tip (144 dpi), all equal to #292:** cache ssim 0.8619/
ssim_inked 0.3937/IoU 0.7366, pages 10/10; computed 0.8447/0.3589/0.6842,
10/10; `lineseg_vs_pdf` 411/411; `hft_width_table --score` installed median
8.72, median |Δ| 10.56; punctuation over-measure +136; `text_rebreak:width`
100; `pdf_face_probe` runs clean; render-check-01 6·37·6·2 at 96 dpi,
14·31·4·2 at 144, 9/9. For scale: at #263 the cache means were
0.8311/0.2766/0.6453 with 9/10 pages.

**Full gate on this tip (`2cb6a13`), posted directly in the PR body, all
foreground, one suite at a time:** `py_compile_sweep` 118/0; engine/tests
1566 passed/135 skipped; pins+package+cleanroom+floors 170; `tests` 491
passed/7 skipped/0 failed; `pipeline/tests` 1435 passed/10 skipped/0 failed;
archive privacy HARD=0.

Everything stays `own-uncertified`; path C NOT RUN anywhere; the corpus is
the training set; the HFT table is declared as measured widths only.

**Depends on:** #290, #291, #292. No comments.

## 3. The development-validation document, this window

**Not reopened.** None of #290–#294 touches it or reports a fresh
measurement; it stayed on checkpoint-19's last reading (#281's tip, six
decimals identical to #244/#268: cache 0.6964/0.1834/0.5667, computed
0.6108/0.0982/0.2294) with the page-bottom fit rule still the standing gap
and no public witness. The gridmax-tail probe (#291) and the HFT width
table (#292) both work exclusively from the ten reference PDFs, not this
document.

## 4. Regressions (with the PR's or commit's own explanation)

**None claimed this window.** #292's shipped HFT width table reports the
cache line IoU dipping 0.0009 (0.7375 → 0.7366) while cache ssim,
ssim_inked, and every computed-side channel rise — stated by the PR itself
as the one channel that moved the wrong way, not hidden, and not treated as
disqualifying given the size and direction of the other gains. #290
converges without changing any rendering behaviour (only the `cell_hwp`
schema fix); #291 is measurement-only, `own_render.py` untouched; #293 is a
no-conflict desktop re-merge. #294's convergence reports its post-merge
numbers matching #292's pre-merge branch exactly.

**Unsupported, still open from checkpoint-19, now partially covered.** HFT-
declared PDF fonts have no TrueType metric on any machine without Hancom's
own HFT set installed — #292 now covers 226 of an unknown larger set of
(face, code point) pairs actually used, but **8 of 13 declared HFT faces
still have zero attributed code points** (all in-cell), and 494 Type-3 code
points remain unattributable. Stated as a documented, partially-closed
limit, not a regression.

**Integration conflicts, resolved.** #290's clash was not textual — it
surfaced only when the merged tree ran `pdf_face_probe.py` against #283's
renamed `cell_hwp` field; fixed by reading the new field name at the two
numeric sites. #294's real conflict: #292 had independently grown its own
pre-#283 `_advance_hwp` because it branched from a stale base; resolved by
folding HFT metric lookup into the existing single seam (HFT first, then
the bold/metric fallback) rather than keeping two advance paths. Its other
two conflicts (`own-render-notes.md`'s log ordering, and the `cell_hwp`
recurrence #292's stale base risked in `pdf_face_probe.py`, which did not
in fact recur) were non-events or purely additive. #293 merged with no
conflicts at all.

## 5. Unsupported / declared elements still open

Carried from checkpoint-19, with this window's closures and new items:

- **Closed this window:** the #286/#288 renderer convergence hop (#290) —
  landed, mechanical as expected, `cell_hwp` the only fix needed.
- **Measured to its end, still not a shipped rule:** the gridmax tail (#277)
  — now conclusively 4 cells in one table with a disjoint-edge-set
  explanation and a corpus-wide contested-boundary count of 5/256 where
  `max` wins all five; no candidate rule beats what ships; the narrower
  open question (which end of a short row absorbs a shortfall) stays a
  2-point observation, not a rule (#291).
- **Substantially advanced, still open:** the HFT-face gap named in
  checkpoint-19 — a measured, legally-framed per-face width table now ships
  as the metric for HFT-declared runs, closing `text_rebreak:width`'s
  moel-2013 share (22 → 0) and the punctuation over-measure (+15013 →
  +136); still open — 8 of 13 declared HFT faces and 494 Type-3 code points
  remain unattributed, the 226 pairs are stated as a corpus inventory rather
  than a general rule, and #283's full-width rule needs revisiting on top
  of the table since the substituted per-line median moved the wrong way
  (−120 → −382) until that happens (#292).
- **New, owed:** the re-merge of the desktop line onto #294 is in flight as
  an unpushed local branch (`claude/desktop-on-renderer-294`, tip
  `16b31b7`) with no PR opened and no gate run recorded against it — must
  not be read as landed; revisiting #283's full-width advance rule on top
  of #292's HFT table, in flight; the page-fit public witness scan (still
  blocked on the COM ownership agreement, in flight per the standing plan);
  the desktop GUI smoke, still never run, free disk moved 5.0–5.4 GB
  (checkpoint-19's #284) → 6.6 GB (#287) → 5.6–5.7 GB (#293) and remains
  judged marginal.
- **Unchanged from checkpoint-19, still fully open:** the table-split rule's
  single witness (kstartup tbl9, #278) and `repeatHeader`'s complete lack of
  a positive corpus case; the move-whole anchored-table arm's generalization
  beyond `CELL` + anchored, untested; the overflow clamp on gridmax,
  untested; the development-validation document's 5 line-count and 40
  character-split discrepancies and their font-resolution hypothesis
  (#258/#260), not reopened this window (see §3); computed layout's own
  +1800 page-top drift against that document's PDF (#257), unaddressed; the
  `LayoutSnapshot` contract and `x1` glossary (#253), no response recorded;
  `layout_policy`/`layout_policy_reason` still not surfaced in the desktop
  UI; the acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item); Codex-app-closed sessions moved; Cursor login.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #290 | engine/tests 1561/135 skipped; pins170 | **`tests` 490/7/0 + `pipeline/tests` 1435/10/0, tip `5a2fa49`, posted directly in the PR body — 0 failed overall** | `py_compile_sweep` 117/0; archive privacy HARD=0 |
| #291 | engine/tests 1561/135 skipped; pins170 | **`tests` 490/7/0 (6m55s) + `pipeline/tests` 1435/10/0 (12m32s), tip `d969f7f` — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 117/0; archive privacy HARD=0 |
| #292 | engine/tests 1558/135 skipped; pins170 | **`tests` 495/3/0 (9m06s) + `pipeline/tests` 1437/8/0 (9m22s), tip `45c8ced` — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 118/0; archive privacy HARD=0 |
| #293 | engine/tests 1568/135/0; `tests` 1097/7/0 (three chunks); `pipeline/tests` 1437/10/0 (four chunks); geometry/runtime-render/own selection 211 passed | **posted directly in the PR body, all green, 0 failed** (a discarded background run rerun foreground) | `py_compile_sweep` 143/0; privacy HARD=0 (WARN 55: fonts, fixture IDs); GUI smoke NOT RUN (5.6–5.7 GB free) |
| #294 | engine/tests 1566/135 skipped; pins170 | **`tests` 491/7/0 + `pipeline/tests` 1435/10/0, tip `2cb6a13`, posted directly in the PR body — 0 failed overall** | `py_compile_sweep` 118/0; archive privacy HARD=0 |

#291 and #292 each post their full gate as a follow-up comment, both green.
#290, #293 and #294 post their full gate directly in the PR body, all
green. Gates as reported: #291 0 failed, #292 0 failed, #294 full gates
green, #293 all suites green; the desktop's GUI smoke stays NOT RUN
throughout.

## 7. Integration conflicts expected when lines converge

**#290's clash was not textual — it only showed once the merged tree ran.**
#288's `pdf_face_probe.py` predates #283's rename of `OurMetrics.run()`'s
numeric cell field (`declared` → `cell_hwp`, with `declared` reused for the
face-name string); the merge itself produced no conflict marker, but the
script crashed on the merged tree with a `TypeError`. Fixed by reading
`cell_hwp` at the two numeric sites — a reminder that a clean merge diff
does not guarantee a working merged tree when a schema rename and an
unconverged sibling touch the same data shape from different sides.

**#294's one real conflict: two advance seams.** #292 branched from a base
that predated #283/#286's unification and had grown its own pre-#283
`_advance_hwp`. Resolved by keeping one seam and ordering it — HFT metric
lookup first for HFT-declared runs, the existing bold/metric fallback
(#285) behind it — rather than keeping two paths that could silently
diverge. Its other two touches (`own-render-notes.md`'s log ordering, and
`pdf_face_probe.py`'s expected `cell_hwp` recurrence, which did not in fact
recur because #292's branch point was still on the pre-fix schema but the
merge picked up #290's fix cleanly) were non-events.

**Desktop converged once, cleanly, and once more in flight.** #293 merged
onto #290 with no conflicts at all. The further hop onto #294 exists only
as an unpushed local branch in this worktree (`claude/desktop-on-renderer-294`,
tip `16b31b7`) — no PR, no gate run recorded against it; its conflict
profile, if any, is unmeasured.

**Writer and runtime lines remain unconverged with anything**, unchanged
from checkpoint-19.

## 8. Next measurable research question

**In the order the open items point to: revisit #283's full-width advance
rule on top of #292's HFT table; the page-fit public witness scan; the
desktop GUI smoke once disk allows.** #292 names the first directly — with
the HFT table now covering the two named carriers, the substituted-line
median moved the wrong way (−120 → −382) until #283's rule is measured
again in this table's presence, since "both" beats the table alone on raw
width error even though the table alone still wins the break test. Second,
the page-bottom fit-rule candidate (`vertsize − spacing`, #256/#260)
remains blocked on the COM ownership agreement not yet in place — this
window's PRs did not reopen the development-validation document (§3), so
this is still the one gap the public corpus cannot decide, in flight per
the standing plan. Structurally alongside: the desktop's re-merge onto
#294, currently an unreviewed local branch with no PR; whether the desktop
GUI smoke can finally run — free disk has moved 5.0–5.4 → 6.6 → 5.6–5.7 GB
across #284/#287/#293 without clearing the bar. Carried further behind
these: the table-split rule's single witness (kstartup tbl9, #278) and
`repeatHeader`'s complete absence of a positive corpus case.

## 9. Certification status

Every result in this checkpoint — #290 (renderer convergence, schema fix
only), #291 (gridmax tail, measured to its end, not shipped), #292 (HFT
width table, shipped fix, one channel down against several up), #293
(desktop re-merge onto #290, no fix needed), #294 (renderer convergence,
one advance seam, no fix commit of its own) — remains **own-uncertified**.
`render_cert.py` still cannot certify this renderer absent a PDF text
layer, unchanged since checkpoint-01. Path C NOT RUN on every PR this
window; the corpus remains the training set, including for #292's width
table, which is itself declared as an inventory of that same corpus, not a
general rule.

**What moved, restated plainly:** this window closed the renderer fork
checkpoint-19 left open (#290: #286+#288 unified behind one schema),
then measured the gridmax tail conclusively without shipping a fix (#291:
4 cells, a disjoint-edge-set explanation, 5/256 corpus-wide contested
boundaries, `max` wins all five), then turned checkpoint-19's HFT-face
identification into a shipped metric (#292: a measured, legally-framed
226-pair width table cuts `text_rebreak:width`'s moel-2013 share to zero
and the punctuation over-measure by two orders of magnitude, at the cost of
one small dip in cache line IoU), and finally re-unified the advance path a
second time after #292's stale branch point had re-forked it (#294). The
renderer, forked at checkpoint-19's close, is **single-tipped again** at
#294 — mod the desktop line, which is one hop behind on a re-merge that
exists only as an unreviewed local branch. Legal framing was made explicit
this window for the first time: the HFT table is public black-box PDF
output, widths only, no font data, declared as measured with stated
coverage — a documented decision, not an assumption.

**Owed, carried forward from checkpoint-19, plus this window's additions:**

- The desktop re-merge onto #294 — exists only as a local, unpushed branch
  (`claude/desktop-on-renderer-294`, tip `16b31b7`); no PR, no gate run
  recorded; must not be treated as landed.
- Revisiting #283's full-width advance rule on top of #292's HFT table —
  named by #292 itself as owed, since the substituted-line median moved the
  wrong way until that happens.
- The page-fit public witness scan via a Hancom round-trip (#256/#260) —
  still blocked on the COM ownership agreement; not reopened this window.
- 8 of 13 declared HFT faces and 494 Type-3 code points still unattributed
  by #292's table (#288, #292).
- The gridmax tail's narrower open question — which end of a short row
  absorbs a shortfall — a 2-point observation (73/75 vs 2/75), not a rule
  (#291).
- The table-split rule's single witness (kstartup tbl9, #278) and
  `repeatHeader`'s complete lack of a positive corpus case.
- The move-whole anchored-table arm's generalization beyond `CELL` +
  anchored — untested; the overflow clamp on gridmax — untested (#277).
- The development-validation document's font-resolution hypothesis for its
  5 line-count and 40 character-split discrepancies (#260), and computed
  layout's own +1800 page-top drift against its PDF (#257) — neither
  reopened this window.
- The `LayoutSnapshot` proposal (#253) — no response recorded this window;
  no level-C run exists anywhere (path C NOT RUN on every PR this window).
- `layout_policy`/`layout_policy_reason` surfaced in the desktop UI — still
  not a branch or PR.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- The desktop's build-from-merged-source GUI smoke evidence — still does
  not exist; free disk read 5.6–5.7 GB at #293, still judged marginal.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.

## 10. Coordinator interaction this window

**Unchanged since checkpoint-19.** No new coordinator status request
arrived this window. REG-001 (2026-09-05 23:47 KST) and STATUS-001
(2026-09-06 00:51 KST), both already recorded in checkpoint-18 and again in
checkpoint-19, remain the only coordinator requests on file; both were
answered as comments on #274, which stayed the fallback handoff channel
throughout. None of #290–#294 records a new request. Recorded here again so
that #274's role as the standing handoff channel carries forward into this
checkpoint unchanged.
