# Checkpoint 21 — the page-fit corpus witness closes without a rule, the stand-in break test comes down to one sentence, and a declared error-budget tolerance ships behind a renderer seam

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-20` (this
branch, `claude/docs-checkpoint-21`, is cut from `origin/claude/docs-checkpoint-20`
and stays unmerged). All six PRs covered this window are **OPEN/DRAFT** —
nothing in this window has merged to `main`. Covers #295
(`claude/engine-e2-fit-witness`, based on #292's branch: a page-fit public
witness scan over all 3209 cached linesegs, cells and anchors included — no
public text line crosses the body bottom; the 14 crossers are all
NONE-table cells, whole-table linesegs, or empty lines, drawn at the cache
seat by the PDF; the public bracket tightens to `vertsize` −31 / +911; the
private +566 witness (development-validation page) still has no public
sibling — the fit rule needs a Hancom round-trip, blocked on COM
ownership), #297 (`claude/engine-e2-standin-rule`, on #294: five stand-in
width variants on the HFT table; none holds the 21/47 break test the
shipped table alone holds; the two flipping paragraphs are one 78-character
sentence set twice in moel-2025, over-measured 15–86 HWPUNIT by every
corrected variant; nothing ships; `advance_probe --fallback-rules` repaired
along the way), #299 (`claude/engine-e2-converge-09`, on #294, merges in
#295 and #297: convergence, probes only, full gates green, numbers equal
#294), and #301 (`claude/engine-e2-right-edge`, on #297 — **branched before
#299's convergence merge, so it is an unconverged sibling of #299, not yet
folded in**: no fit candidate at the right edge is consistent — 14 rejected
spans measure under the box, so the metric is what those lines test;
**SHIPPED** a 96-HWPUNIT right-edge tolerance behind a new `_line_fits`
seam, **declared as an error budget for our advance metrics, not a Hancom
rule**, window [63.1, 111.8) derived from 8 kept lines and the tightest
rejected span; 0 break regressions; all six #297 stand-in variants now hold
21/47; cache byte-identical; computed IoU 0.684242 → 0.684881;
`text_rebreak:width` 100 → 41 with a new unexplained bucket
`table_origin_unattributed` 64; the PR states this is the reviewer's call).
Desktop #298 (`claude/desktop-on-renderer-294`, on #293, tip #294)
reproduced the one `pipeline/tests` failure also present on `origin/main`
in isolation — order-dependent, report-only — and named the sidecar
data-list handoff (`desktop/sidecar/build.ps1` does not ship
`hft-widths.measured.json`, so a frozen sidecar falls back to the
pre-#292 metric on HFT runs). #300 (`claude/desktop-on-renderer-299`, on
#298, tip #299) re-merged clean, rechecked the same order-dependent case
unchanged, and is — like #299 — one hop behind #301. Writer line
(#224 → #235 → #238 → #239) and runtime line (#204) did not move.

**Two open decisions for the product/reviewer, stated plainly:**

1. **Whether #301's 96-HWPUNIT right-edge tolerance is acceptable as a
   declared error budget for the advance metrics**, rather than being read
   as (or mistaken for) a Hancom fit rule. The PR itself asks for this call
   and notes k would need re-measuring if #285/#297's remaining +197.76
   punctuation over-measure on installed faces lands.
2. **The sidecar data-list line** in `desktop/sidecar/build.ps1` — adding
   `engine/references/fonts/hft-widths.measured.json` so a frozen desktop
   build does not silently fall back to the pre-#292 HFT metric. Named by
   #298, still unowned; ownership sits on the product side per #253.

## What changed since checkpoint-20

| metric | checkpoint-20 | checkpoint-21 | moved in |
|---|---|---|---|
| renderer-line tip | single tip, #294 (mod an in-flight desktop hop) | **forked again**: #299 converges #295 + #297 back onto #294, but #301 branches off #297 *before* that convergence and ships a fix of its own — #301 is an unconverged sibling of #299 | #295, #297, #299, #301 |
| page-fit public witness (§8 of checkpoint-20, blocked on COM ownership) | fully open, no public witness at all | **scanned to the end on the public corpus: no public text line crosses the body bottom.** Bracket tightens `top` (refuted) / `vertsize−spacing` −720/+395 / `vertsize` **−31/+911** / `vertsize+spacing` (refuted); the only crossing witness remains the private development-validation page (+566/+626); still blocked on the Hancom round-trip | #295 |
| HFT stand-in width rule (owed by #292: "revisit #283's full-width rule on top of the table") | open — substituted-line median moved the wrong way (−120 → −382) | **measured to the end, nothing ships**: 5 variants all fix the substituted-width median (−382 → −2 to +25) but none holds the 21/47 break test; the whole gap is one 78-character sentence (moel-2025 ¶64/¶160) over-measured 15–86 HWPUNIT by every corrected variant | #297 |
| right-edge line-fit tolerance | did not exist as a concept | **shipped**, 96 HWPUNIT, declared as an error budget behind `_line_fits`; break test 0 regressions; all six #297 stand-ins now hold 21/47 (were 19–20) | #301 |
| `text_rebreak:width` root | 100 | unchanged through #295/#297/#299, then **100 → 41** at #301, with a new unexplained bucket `table_origin_unattributed` 64 | #301 |
| corpus raster, 144 dpi, cache (ssim / ssim_inked / IoU, pages exact) | 0.8619 / 0.3937 / 0.7366, 10/10 | **byte-identical** through #295/#297/#299/#301 — right-edge tolerance does not change cache-mode rendering | unchanged |
| corpus raster, 144 dpi, computed | 0.8447 / 0.3589 / 0.6842, 10/10 | unchanged through #299; **0.684242 → 0.684881** (IoU), 0.8447 → 0.8451 (ssim), 0.358878 → 0.358796 (ssim_inked) at #301, 10/10 | #301 |
| desktop line | #293 on #290, a further hop in flight unpushed, no PR | **that in-flight hop is now a PR**: #298 on #293 → renderer tip #294; #300 re-merges #298 onto renderer tip #299 — both are one hop behind #301, same as #299 is | #298, #300 |
| writer line | unmoved since checkpoint-06 | still unmoved | — |
| runtime line | unmoved since checkpoint-06 | still unmoved | — |

## 1. Branch DAG

Renderer line: **the single tip #294 forks into a probe pair (#295 off #292,
#297 off #294); #299 converges both back onto #294; but #301 branches off
#297 before that convergence and ships a fix, leaving #301 an unconverged
sibling of #299.**

| PR | branch | base | slice |
|---|---|---|---|
| #295 | `claude/engine-e2-fit-witness` | `claude/engine-e2-hft-widths` (#292) | page-fit witness scan over all 3209 cached linesegs incl. cells and anchors; no public line crosses the body bottom; bracket tightens to `vertsize` −31/+911; probe only, `own_render.py` untouched; joins the tip at the next hop |
| #297 | `claude/engine-e2-standin-rule` | `claude/engine-e2-converge-08` (#294) | five stand-in HFT width variants scored against the break test; none beats the shipped table; repairs `advance_probe --fallback-rules`, dead since #294; names the right-edge line-fit rule as the next slice |
| #299 | `claude/engine-e2-converge-09` | `claude/engine-e2-converge-08` (#294), merges in #295 and #297 | convergence: two merge commits, one notes-only conflict, `own_render.py` unchanged by either slice; full gates green; numbers equal #294 |
| #301 | `claude/engine-e2-right-edge` | `claude/engine-e2-standin-rule` (#297) | ships a 96-HWPUNIT right-edge tolerance behind a new `_line_fits` seam; **branched before #299's convergence merge — does not yet include #295's fit-witness scan and has not itself been folded onto #299**; a hop is owed |

Desktop line: two re-merges, both one hop behind #301.

| PR | branch | base | note |
|---|---|---|---|
| #298 | `claude/desktop-on-renderer-294` | `claude/desktop-on-renderer-290` (#293) | re-merge onto renderer tip #294; no conflicts; reproduces one `pipeline/tests` order-dependent failure, also present on `origin/main` in isolation; names the sidecar data-list gap for `hft-widths.measured.json` |
| #300 | `claude/desktop-on-renderer-299` | `claude/desktop-on-renderer-294` (#298) | re-merge onto renderer tip #299; no conflicts; rechecks the same order-dependent case, unchanged; still one hop behind #301 the way #299 is |

Docs line: no new docs PR this window besides this checkpoint document itself.

Writer line, unchanged from checkpoint-20 — still #224 → #235 → #238 → #239.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` … `-20` (each off its own window's renderer
state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #295 — the page-fit public witness scan: no public line crosses the body bottom

**Probe only; `own_render.py` untouched.** Path A oracle (cached geometry)
with the PDF as confirmation; path C NOT RUN.

**Scan** (`page_fit_probe.py --corpus --scan-all`): 3209 cached linesegs
(2552 in-cell), of which 629 are fit-test evidence. Excluded on stated
grounds: 1691 cells of `pageBreak="NONE"` tables (the table moves whole, so
its cells cannot witness a line-fit test), 842 empty lines, 3 lines taller
than a page, 44 off-sheet lines (kstartup tbl36's `vertOffset="4294967083"`
— an unsigned wrap, recorded).

**The top tail (overhang > −300 under `vertsize`): 21 lines.** Fourteen
cross the body bottom and none is evidence: 7 cells of `NONE` tables
(moel-2013 +4323/+3422/+2422/+1321/+422/+221, saeopja +1021), 3
whole-inline-table linesegs taller than the page (+4747/+3846/+1303), 4
empty lines (nrf +1794 × 2, moel +3523/+1422). The only evidence lines in
the tail are whole-table linesegs at **−31** (jeongbo), −296 (kstartup),
−299 (saeopja). **Near misses** (would-be overhang < +300): 9, all deeply
negative (closest −193, moel-2025 p2) — nothing new on the rejected side.

**Public bracket after the scan (kept max / rejected min):** `top` −1368 /
−445 (refuted); `vertsize − spacing` −720 / +395; `vertsize // 2` −868 /
+255; `baseline` −518 / +731; **`vertsize` −31 / +911** (text-only kept max
−396); `vertsize + spacing` +1521 / +1427 (refuted). kstartup tbl9's first
fragment — the one place Hancom cut through a cell (#278) — clears the
bottom by ≥ 5069 under every measure and decides nothing.

**PDF confirmation:** 7 tail lines with matchable text are drawn at the
cache seat (Δtop −5…−98), with ink up to **+4229 below the body bottom** —
the export draws what the cache seats; nothing moved.

**Conclusion.** The corpus cannot decide the fit measure between
`vertsize − spacing` and `vertsize` (and the fractions between); the only
witness that a line may cross the body bottom is the private
development-validation page (+566 kept / +626 rejected, path A). A public
witness requires a Hancom round-trip of the page-fit probe, still waiting
on the COM ownership agreement.

**Not proven:** cell seats come from the renderer's table geometry, not raw
cached coordinates (the PDF confirms only the 8 lines with matchable text);
`CENTER`/`BOTTOM` cells use our computed block extent; the `NONE` exclusion
removes exactly the population with ink past the bottom; `vertsize ==
textheight` corpus-wide; still no intra-paragraph page break anywhere in
the corpus.

**Evidence:** `py_compile_sweep` 118/0; engine/tests 1572 passed/135
skipped; pins + package 85 passed; archive privacy HARD=0. **Full gate, tip
`1e280f6`** (posted as a follow-up comment): `tests` 495 passed/3
skipped/0 failed (8m18s) + `pipeline/tests` 1437 passed/8 skipped/0 failed
(10m49s), 0 failed overall. Comment states this PR is probe-only and joins
the renderer tip at the next convergence hop with the stand-in rule slice.

**Depends on:** #292 (joins the tip at the next hop). Worker: Opus;
orchestrator: Fable.

### #297 — the stand-in rule is decided by one sentence, twice

**Five stand-in variants on top of the HFT table; nothing ships.** Path A
oracle + PDF glyph positions; path C NOT RUN; `own_render.py` untouched.

| variant on the table | exact widths installed/substituted | break matches installed/other | proven over-measures |
|---|---:|---:|---:|
| table alone (a, shipped in #292) | 24/103 · 0/308 | 48/113 · **21/47** | 30/2272 |
| + full-width = declared size (b) | 24 · 7 | 48 · 19 | 33 |
| + (b) gated to bundled faces | identical to (b) | | |
| + (b) on Hangul and full-width punctuation only (e) | identical to (b) | | |
| + (b) with cumulative pen rounding to 12 HWPUNIT (d) | 24 · **35** | 48 · 20 | 31 |
| + per-face measured scale (c) | 24 · 23 | 48 · 20 | 31 |

Substituted per-line median |Δ| −381.90 → +24.83 (b) / **−2.83** (d) /
−2.19 (c). Carriers (ours − Hancom): ¶118 line 0 −1850 → −128/−234/−229;
line 1 −1659 → +23/−81/−76; ¶141 −1068 → +85/**+14**/+18. The measured
scale for 휴먼명조 is 1.0494 (n = 3529) = 1/0.9529 — the stand-in ratio from
#267/#283, confirmed from the other side.

**The flips.** Only moel-2025 ¶64 and ¶160 change, and they are the same
78-character preamble in a 48190-wide column: our width for the cached
64-character line goes 47020/47083 under (a) → 48205/48276 (b) →
48132/48202 (d) → 48135/48206 (c) — over the box by 15–86 HWPUNIT. (a)
matches the cached break while under-measuring by 1170; the corrected
variants measure right and break wrong. That is the whole difference
between 21 and 19–20, and it is one sentence.

**Decision:** nothing shipped; the variants stay in the probe
(`hft_width_table.py --standin`). The break test with the current line-fit
rule cannot tell a 15-HWPUNIT over-measure from a real one, so the next
witness has to be the line-fit rule at the *right* edge, not another
advance rule.

**Fixed on the way:** `advance_probe --fallback-rules` was dead on #294
(`RuleRenderer._advance_hwp` missing #292's `rel_sz`, and it bypassed the
table); it now agrees with the table probe (21/19/20).

**Corpus unchanged (= #294):** cache 0.8619/0.3937/0.7366, computed
0.8447/0.3589/0.6842, 10/10 pages; `lineseg_vs_pdf` 411/411; classes
1713/98/214/28; `text_rebreak:width` 100. render-check-01 6·37·6·2/14·31·4·2,
9/9 — its 16 faces are all installed, 0 stand-ins, so it cannot test this.

**Not proven:** pen rounding is per chunk, not per line; the scale is one
ratio per face and only 휴먼명조 is off 1; the two flips are one sentence
twice.

**Evidence:** engine/tests 1616 passed/135 skipped; pins + package +
cleanroom + floors 170 passed; `test_hft_width_table` 50; archive privacy
HARD=0. **Full gate, tip `0f96b71`** (posted as a follow-up comment):
`tests` 491 passed/7 skipped/0 failed (7m32s) + `pipeline/tests` 1435
passed/10 skipped/0 failed (8m44s), 0 failed overall. Comment states this
PR is probe-only, joining the renderer tip in the convergence hop then
running, and that the right-edge line-fit question starts as the next
slice.

**Depends on:** #294. Worker: Opus; orchestrator: Fable.

### #299 — converge #295 and #297 onto the #294 tip

**Two merge commits, one notes-only conflict, full gates green;
`own_render.py` unchanged by either slice.**

**Verified on the tip (144 dpi), all equal to #294:** cache ssim
0.8619/ssim_inked 0.3937/IoU 0.7366, pages 10/10; computed
0.8447/0.3589/0.6842, 10/10; `lineseg_vs_pdf` 411/411; `hft_width_table
--standin` baseline 21/47; `page_fit_probe --scan-all` bracket `vertsize`
−31/+911; render-check-01 6·37·6·2 at 96 dpi, 14·31·4·2 at 144, 9/9.

**Full gate on this tip (`a75c330`), all foreground, one suite at a time:**
`py_compile_sweep` 118/0; engine/tests 1630 passed/135 skipped; pins +
package + cleanroom + floors 170 passed; `tests` 495 passed/3 skipped/0
failed; `pipeline/tests` 1437 passed/8 skipped/0 failed; archive privacy
HARD=0.

Everything stays `own-uncertified`; path C NOT RUN anywhere; the corpus is
the training set.

**Depends on:** #294, #295, #297. Merge: Sonnet; orchestrator: Fable. No
comments.

### #301 — a 96-HWPUNIT right-edge tolerance, declared as an error budget

**Shipped, but branched off #297 before #299's convergence — an
unconverged sibling of #299.** Path A oracle (cached `horzsize` vs our
width of the cached characters); path C NOT RUN. The PR states the
reviewer decides whether an error budget belongs in the renderer; it is
isolated in one constant behind one seam.

**Kept excess** (ours − (horzsize − indent), HWPUNIT, over 2272 cached
lines: p50/max/count > 0): all −3237/+2870/33; lines ending in a space
−2987/+1126/9; ending in punctuation −6586/+170/2; other −2956/+2870/22.
Only 1 of the 33 overflows is a multiple of 12.

**Candidate bracket (kept max/rejected min/kept-violations/rejected-violations):**
strict ≤ 2870/−3454/62/13 · trailing space hangs 2870/−3454/33/13 ·
trailing punctuation hangs 2870/−3454/31/14 · `condense` 1370/−3454/18/14 ·
pen-grid rounding 1372/−3456/17/14. **No candidate is consistent:** 14
spans Hancom broke are ones we measure as *under* the box — our metric, not
the fit rule, is what those lines test.

**¶64/¶160 (moel-2025, the #297 flips), line 0:** shipped widths
−1168/−1105 under the box; under the corrected `table + cell` metric
**+16.8/+88.1**; under `table + pen` −56.4/+14.4; their rejected spans are
all > 3100 over. Eight cached lines sit ≤ 63.1 over the box and the
tightest rejected span is +111.8, so any tolerance in [63.1, 111.8) is
consistent with the cache; k = 8 cells = 96 is the joint optimum under the
corrected widths — chosen with ¶64/¶160 in view, stated.

**Shipped.** `RIGHT_EDGE_TOLERANCE_HWP = 96` behind a new `_line_fits`
seam. Break test: installed 48/113, other 21/47, **0 regressions**; the
gain is exactly ¶64/¶160 under `--standin`, and **all six stand-in variants
from #297 now hold 21/47** (were 19–20) — the stand-in rule is no longer
blocked by the fit test.

**Measured, 144 dpi.** cache scoreboard **byte-identical**
(0.8619/0.3937/0.7366) — cache mode does not break lines; computed IoU
0.684242 → **0.684881**, ssim 0.8447 → 0.8451, ssim_inked 0.358878 →
0.358796, pair 0.8460 → 0.8462; pages 10/10 both. `lineseg_vs_pdf` 411/411.
Classes 1713/94/219/28; roots `text_rebreak:width` **100 → 41**, with a new
bucket `table_origin_unattributed` 64 (reclassified, not explained).
render-check-01 unchanged (6·37·6·2/14·31·4·2, 9/9).

**Not proven:** the tolerance is an error budget, not a Hancom rule —
#285/#297's remaining +197.76 punctuation over-measure on installed faces
would explain the same window, and k must be re-measured if that lands; the
two decisive paragraphs are one sentence twice; the new 64-paragraph root
is unexplained.

**Evidence:** `py_compile_sweep` 119/0; engine/tests 1631 passed/135
skipped; pins + package + cleanroom + floors 170 passed; archive privacy
HARD=0. Full `pipeline/tests` gate: **running at time of writing; to be
appended to #301 — not yet posted, so it must not be read as green.**

**Depends on:** #297. Worker: Opus; orchestrator: Fable. No comments yet.

### #298 — the desktop line on renderer tip #294

**One merge commit, no conflicts, no fix needed.** Base:
`claude/desktop-on-renderer-290` (#293).

**Evidence (merged tree, one suite at a time, all foreground):**
`py_compile_sweep` 144/0; engine/tests 1573 passed/135 skipped/0 failed;
`tests` 1098 passed/7 skipped/0 failed (six batches, collection count
matched); `pipeline/tests` 1437 passed/9 skipped/**1 failed** (five
batches); geometry/runtime-render/own selection 211 passed; archive privacy
HARD=0 (WARN 55: fonts and fixture IDs). The covering tests for caret
geometry (`test_runtime_geometry`, `test_runtime_plan`,
`test_runtime_render`) pass.

**The one failure, verified by the orchestrator, is not this merge's.**
`pipeline/tests/test_claim_extraction.py::test_union_only_korean_tag_does_not_widen_saeteuk_comparison`
fails with `AttributeError: 'NoneType' object has no attribute '__dict__'`
from `dataclasses.py:712` when run **alone**, identically on this tip and
on `origin/main` (checked in a throwaway worktree, Python 3.11.9). The same
test passed inside the full `pipeline/tests` run on #293 (1437/0), so it is
order-dependent — a module-lookup path in `dataclasses` that only breaks in
isolation. Report-only; the pipeline line owns it.

**Handoff, not edited (ownership per #253):** `desktop/sidecar/build.ps1`'s
data list adds only `engine\references\fonts\family-map`; the new
`engine/references/fonts/hft-widths.measured.json` (resolved relative to
the engine root like `family-map`) would **not ship in the frozen
sidecar**, so a built app would silently fall back to the pre-#292 metric
on HFT runs. One `$addData` line is owed on the product side; no test
guards that list today.

**Desktop GUI smoke: NOT RUN.** 5.7 GB free on a 99 %-full C:, below what a
clean Tauri release build needs; a pre-built exe smoke is not cited.

**Stated, not done:** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248).

**Depends on:** #293 (desktop) and #294 (renderer). Merge: Sonnet;
verification: Fable. No comments.

### #300 — the desktop line on renderer tip #299

**One merge commit, no conflicts, no fix needed.** Base:
`claude/desktop-on-renderer-294` (#298).

**Evidence (merged tree, all foreground):** `py_compile_sweep` 144/0;
engine/tests 1637 passed/135 skipped/0 failed; `tests` 1098 passed/7
skipped/0 failed (three groups); `pipeline/tests` 1437 passed/10 skipped/0
failed (unsplit); geometry/runtime-render/own selection 211 passed; archive
privacy HARD=0 (WARN 55: fixture IDs). The known order-dependent
`test_claim_extraction` case was checked both ways again: fails alone or
with its file neighbours, passes inside the full `pipeline/tests` ordering
— unchanged from `origin/main`, report-only.

**Desktop GUI smoke: NOT RUN.** 4.6–4.7 GB free on a 99 %-full C:; a
pre-built exe smoke is not cited. The sidecar data-list handoff from #298
(`hft-widths.measured.json` not shipped by `build.ps1`) still stands for
the product line.

**Stated, not done:** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248).

**Depends on:** #298 (desktop) and #299 (renderer). Merge: Sonnet;
orchestrator: Fable. No comments.

## 3. The development-validation document, this window

**Not reopened.** None of #295–#301 touches it or reports a fresh
measurement; it stays on checkpoint-20's last reading (#281's tip, six
decimals identical to #244/#268/checkpoint-19: cache 0.6964/0.1834/0.5667,
computed 0.6108/0.0982/0.2294 — cited from #281's comment) with the
page-bottom fit rule still the standing gap and no public witness. #295's
scan works exclusively from the public corpus and states explicitly that
the private development-validation page's +566/+626 witness remains its
own, without a sibling; #297 and #301 both work from the ten reference PDFs
only.

## 4. Regressions (with the PR's or commit's own explanation)

**None claimed this window.** #301 states computed ssim_inked moving
0.358878 → 0.358796 (a −0.00008 change) alongside every other computed
channel rising or holding — noted plainly, not treated as a regression
given its size against the IoU and ssim gains. Cache-mode metrics are
byte-identical across #295, #297, #299 and #301 (right-edge tolerance only
touches how `own_render.py`'s computed path breaks lines, not cache
playback). #295 and #297 are probe-only, `own_render.py` untouched by
either. #298 and #300 are no-conflict desktop re-merges; both reproduce
(not introduce) the same order-dependent `pipeline/tests` failure that is
also present on `origin/main` in isolation.

**Unsupported, carried forward, now partially covered.** The page-fit
public witness gap named across checkpoints 19–20 is now measured to its
end on the public side (#295: 3209 linesegs scanned, bracket tightened to
`vertsize` −31/+911) but not closed — the corpus still cannot decide
between `vertsize − spacing` and `vertsize`, and the one witness that a
line may cross the body bottom remains private, unreproduced publicly.
#292's HFT-face gap similarly saw its "revisit #283's full-width rule"
follow-up run to exhaustion (#297: 5 variants, none beats the shipped
table) without closing.

**Integration conflicts, resolved or pending.** #299's convergence of #295
and #297 produced one notes-only conflict (non-functional) and no
`own_render.py` conflict. #298 and #300 both merged with no conflicts at
all. **Pending:** #301 branched off #297 before #299's convergence merge
and has not itself been folded onto #299 — its conflict profile against
#295's fit-witness scan is unmeasured; likewise #300 (on #298, tip #299)
does not yet include #301's right-edge tolerance.

## 5. Unsupported / declared elements still open

Carried from checkpoint-20, with this window's closures and new items:

- **Measured to its end this window, still not closed:** the page-fit
  public witness scan (#256/#260/#295) — no public text line crosses the
  body bottom across all 3209 cached linesegs; the bracket tightens to
  `vertsize` −31/+911 but the corpus cannot pick between that and
  `vertsize − spacing`; still blocked on the Hancom round-trip and the COM
  ownership agreement.
- **Measured to its end this window, nothing shipped:** revisiting #283's
  full-width advance rule on top of #292's HFT table (#297) — five stand-in
  variants all fix the substituted-width median but none holds the break
  test; the entire 21-vs-19/20 gap traces to one 78-character sentence
  (moel-2025 ¶64/¶160) over-measured 15–86 HWPUNIT by every corrected
  variant.
- **New, shipped, reviewer's call owed:** #301's 96-HWPUNIT right-edge
  tolerance — a declared error budget for the advance metrics, not a
  Hancom rule; 0 break regressions, closes the #297 stand-in gap (21/47 on
  all six variants), but is explicitly not proven to be the true fit rule,
  and a new unexplained `table_origin_unattributed: 64` bucket appears in
  `text_rebreak:width`'s 100 → 41 drop.
- **New, unconverged:** #301 branched off #297 before #299's convergence
  hop landed — the renderer tip is #299 for the fit-witness-and-stand-in
  round but #301's right-edge fix sits one hop away, unmerged onto it; the
  desktop's #300 (on #299) is therefore also one hop behind #301.
- **New, owed on the product side:** the sidecar data-list gap named by
  #298 — `desktop/sidecar/build.ps1` does not add
  `engine/references/fonts/hft-widths.measured.json`, so a frozen desktop
  build silently falls back to the pre-#292 HFT metric; ownership per #253,
  unedited this window.
- **Unchanged from checkpoint-20, still fully open:** the gridmax tail's
  narrower open question (which end of a short row absorbs a shortfall,
  73/75 vs 2/75, #291); the table-split rule's single witness (kstartup
  tbl9, #278) and `repeatHeader`'s complete lack of a positive corpus case;
  the move-whole anchored-table arm's generalization beyond `CELL` +
  anchored, untested; the overflow clamp on gridmax, untested; the
  development-validation document's 5 line-count and 40 character-split
  discrepancies and their font-resolution hypothesis (#258/#260), not
  reopened this window (see §3); computed layout's own +1800 page-top drift
  against that document's PDF (#257), unaddressed; the `LayoutSnapshot`
  contract and `x1` glossary (#253), no response recorded;
  `layout_policy`/`layout_policy_reason` still not surfaced in the desktop
  UI; the acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item); the desktop GUI smoke, still never run, free disk
  read 5.6–5.7 GB (#293) → 5.7 GB (#298) → 4.6–4.7 GB (#300), still judged
  too thin; Codex-app-closed sessions moved; Cursor login.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #295 | engine/tests 1572/135 skipped; pins+package 85 | **`tests` 495/3/0 (8m18s) + `pipeline/tests` 1437/8/0 (10m49s), tip `1e280f6` — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 118/0; archive privacy HARD=0 |
| #297 | engine/tests 1616/135 skipped; pins+package+cleanroom+floors 170; `test_hft_width_table` 50 | **`tests` 491/7/0 (7m32s) + `pipeline/tests` 1435/10/0 (8m44s), tip `0f96b71` — 0 failed overall** (posted as a follow-up comment) | archive privacy HARD=0 |
| #299 | engine/tests 1630/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 495/3/0 + `pipeline/tests` 1437/8/0, tip `a75c330`, posted directly in the PR body — 0 failed overall** | `py_compile_sweep` 118/0; archive privacy HARD=0 |
| #301 | engine/tests 1631/135 skipped; pins+package+cleanroom+floors 170 | **NOT YET POSTED — stated in the PR body as "running at time of writing," to be appended to #301; do not read as green** | `py_compile_sweep` 119/0; archive privacy HARD=0 |
| #298 | engine/tests 1573/135/0; `tests` 1098/7/0 (six batches); geometry/runtime-render/own selection 211 passed | **`pipeline/tests` 1437 passed/9 skipped/1 failed (five batches) — the one failure verified order-dependent and reproduced on `origin/main` in isolation, report-only** | `py_compile_sweep` 144/0; privacy HARD=0 (WARN 55: fonts, fixture IDs); GUI smoke NOT RUN (5.7 GB free) |
| #300 | engine/tests 1637/135/0; `tests` 1098/7/0 (three groups); geometry/runtime-render/own selection 211 passed | **`pipeline/tests` 1437 passed/10 skipped/0 failed (unsplit), all suites green** — the same order-dependent case rechecked both ways, unchanged from `origin/main`, report-only | `py_compile_sweep` 144/0; privacy HARD=0 (WARN 55: fixture IDs); GUI smoke NOT RUN (4.6–4.7 GB free) |

Gates as reported: **#295 0 failed, #297 0 failed, #299 full gates green,
#298 and #300 all suites green with the one documented order-dependent
case, #301 "running at time of writing; appended to #301" — #301's gate
must not be claimed green until that comment lands.**

## 7. Integration conflicts expected when lines converge

**#299's convergence was mechanical.** Two merge commits (#295, then #297)
onto #294's tip produced one notes-only conflict (log ordering in a notes
file, non-functional) and no conflict at all in `own_render.py`, since
neither #295 nor #297 changes it. Full gates green, numbers identical to
#294 on every rendering channel.

**#301 is not yet converged onto #299 — an open integration surface.**
#301 branched from #297's tip before #299's merge landed, so it carries
none of #295's fit-witness-scan changes (which touch only
`page_fit_probe.py` and docs, not `own_render.py`) and has not itself been
tested against the merged #299 tree. Given #295 does not touch
`own_render.py` and #301's change is isolated behind one new `_line_fits`
seam, a clean merge is likely but **unmeasured** — the next hop should
verify it explicitly rather than assume it.

**Desktop converged twice, cleanly, and is now one hop behind #301 as
well.** #298 (onto renderer tip #294) and #300 (onto renderer tip #299)
both merged with zero conflicts. Neither includes #301's right-edge
tolerance yet, so the desktop line's next re-merge is gated on the same
renderer convergence #301 is waiting on.

**Writer and runtime lines remain unconverged with anything**, unchanged
from checkpoint-20.

## 8. Next measurable research question

**In the order the open items point to: fold #301 onto #299 (and #300 onto
that result); decide #301's error-budget framing; explain the new
`table_origin_unattributed: 64` bucket; then the page-fit Hancom
round-trip once COM ownership allows it.** The renderer forked again this
window the same way it did between checkpoints 19 and 20 — a converged tip
(#299) with an unmerged sibling slice (#301) sitting one hop away — so the
immediate mechanical step is the same convergence pattern #294 already
executed once. Substantively, #301 names its own open question: if
#285/#297's remaining +197.76 punctuation over-measure on installed faces
is fixed, k (currently 96 = 8 cells) would need remeasuring, so that fix
should land, or be explicitly deferred, before #301's constant is treated
as settled. The `table_origin_unattributed` bucket (64 paragraphs,
newly split out of `text_rebreak:width`'s 100 → 41 drop) is reclassified
but not explained — the next probe should attribute it before more rules
are layered on the same seam. Behind these: the page-bottom fit rule itself
remains the one gap the public corpus cannot decide (#295 closed out every
public angle it could reach), still blocked on the COM ownership agreement;
the desktop GUI smoke, still never run, free disk moving 5.6–5.7 → 5.7 →
4.6–4.7 GB across #293/#298/#300 without clearing the bar; and the sidecar
data-list line (#298), owed on the product side per #253.

## 9. Certification status

Every result in this checkpoint — #295 (page-fit witness scan, measured to
its end, no fix), #297 (stand-in rule variants, measured to its end,
nothing shipped), #299 (renderer convergence, probes only, no fix commit of
its own), #301 (right-edge tolerance, shipped, declared as an error budget
pending reviewer sign-off), #298 and #300 (desktop re-merges, no fix
needed, one reproduced pre-existing order-dependent test failure) — remains
**own-uncertified**. `render_cert.py` still cannot certify this renderer
absent a PDF text layer, unchanged since checkpoint-01. Path C NOT RUN on
every PR this window; the corpus remains the training set, including for
#295's and #297's exhaustive scans, both explicitly scoped to the public
ten-document corpus.

**What moved, restated plainly:** this window ran the two probes checkpoint-20
left open to their ends without either shipping a rule on its own — the
page-fit bracket tightened to `vertsize` −31/+911 with no public line ever
crossing the body bottom (#295), and the HFT stand-in rule's entire
remaining gap was traced to one sentence appearing twice (#297) — then
converged both probes cleanly onto the renderer tip (#299), and finally
shipped a fix that came out of the *second* probe's own named next step:
a 96-HWPUNIT right-edge tolerance, explicitly framed as an error budget
rather than a discovered Hancom rule, that closes the stand-in break test
for all six variants at zero regressions while opening a new unexplained
paragraph-count bucket (#301). The renderer is **forked again** — #299
converged, #301 one hop away — the same shape checkpoint-19 left checkpoint-20
to close. The desktop line reproduced one real (if not new) test-ordering
fragility on `origin/main` itself and surfaced a concrete, unowned build
gap (the HFT table missing from the frozen sidecar's data list).

**Owed, carried forward from checkpoint-20, plus this window's additions:**

- Fold #301 onto #299 (and #300 onto that result) — the renderer's
  unconverged sibling from this window, mirroring #291/#292's pattern
  before #294.
- Decide #301's error-budget framing — the PR itself defers this to the
  reviewer; re-measure k if #285/#297's punctuation over-measure fix lands.
- Explain the new `table_origin_unattributed: 64` bucket #301 introduced.
- The sidecar data-list line for `hft-widths.measured.json` in
  `desktop/sidecar/build.ps1` — named by #298, owed on the product side per
  #253, still not edited.
- The page-fit public witness via a Hancom round-trip (#256/#260/#295) —
  the public-corpus side is now exhausted; still blocked on the COM
  ownership agreement.
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
  not exist; free disk read 5.7 GB at #298, 4.6–4.7 GB at #300, still
  judged marginal.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.

## 10. Coordinator interaction this window

**Unchanged since checkpoint-20.** No new coordinator status request
arrived this window. REG-001 (2026-09-05 23:47 KST) and STATUS-001
(2026-09-06 00:51 KST), both already recorded in checkpoints 18–20, remain
the only coordinator requests on file; both were answered as comments on
#274, which stayed the fallback handoff channel throughout. None of
#295–#301 records a new request. Recorded here again so that #274's role
as the standing handoff channel carries forward into this checkpoint
unchanged.
