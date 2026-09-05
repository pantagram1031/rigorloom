# Checkpoint 19 — bold ships (drawn with the bold cut, advanced with the regular one), the fallback-face rule closes Hangul but breaks worse and stays unshipped, the PDFs' anonymous fonts turn out to be HWP's own HFT faces, and the renderer forks into two open siblings again

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-18` (this
branch, `claude/docs-checkpoint-19`, is cut from `claude/docs-checkpoint-18`
and stays unmerged). Covers #283 (`claude/engine-e2-fallback-advance`: the
bundled/fallback-face advance rule measured to its end — the embedded face in
nrf/moel is the real 휴먼명조 at 1.000 em/advance, not a Hancom substitute for
it, and the 1/600-inch grid #267 read on the advance is actually on the pen
position; every candidate rule closes the substituted-Hangul residual
−60.04 → +0.64 HWPUNIT but drops the break test from 12/47 to 2/47
paragraphs; **not shipped**, only an `_advance_hwp` / `_face_source` seam
lands), #285 (`claude/engine-e2-punct-advance`: the punctuation hypotheses —
half-em closing punctuation, bracket trim, quarter-em auto-spacing — all
measure at or near zero; the probe instead finds that a bold run is *drawn*
with the bold cut but *advanced* with the regular one, **shipped** for
installed faces — installed-line width median |Δ| 56.57 → 10.56 HWPUNIT,
cache ssim_inked 0.3739 → 0.3881, 0 break regressions, shipped below the 99 %
break gate on a stated criterion), #286 (mechanical + one real convergence of
#285 + #283: every advance computation now comes out of one seam,
`_advance_hwp`; full gates green, cache 0.8607/0.3881/0.7375, computed
0.8402/0.3515/0.6651, 10/10 pages both), #288 (`claude/engine-e2-type3-faces`:
the ten reference PDFs' 37 anonymous Type-3 fonts are identified as HWP's own
HFT faces — 한양신명조, 한양중고딕, HCI Poppy and others — predicted 8566/8566
anchored characters by `hh:font@type="HFT"`; 0 of 492 installed/bundled faces
reproduce any of them; a one-width-per-class model reaches 93.0 % of 844 code
points against the 99 % gate; **not shipped**; the two moel-2013 carriers
turn out to be HFT punctuation over-measure exactly cancelling the 휴먼명조
stand-in's Hangul under-measure) and #284 / #287 (the desktop line re-merged
twice — onto renderer tip #281, then onto #286 — one real conflict the first
time, none the second, all suites green both times, GUI smoke still **not
run**, blocked on disk). Writer line (#224 → #235 → #238 → #239) and runtime
line (#204) did not move. The renderer, single-tipped at #281 when
checkpoint-18 closed, **forks again this window**: #286 converges #283 onto
#285, but #288 — also built off #285 — has not converged with #286, so two
open siblings again await a hop, the same shape as the #272/#273 fork
checkpoint-17 carried into checkpoint-18.

## What changed since checkpoint-18

| metric | checkpoint-18 | checkpoint-19 | moved in |
|---|---|---|---|
| renderer-line tip | **single tip, #281** (`8f0c399`) | **forked again — two open siblings**: #286 (`0422903`, converges #283 onto #285) and #288 (own_render.py byte-identical to #285, HFT-face measurement), **not converged with each other this window** | #283, #285, #286, #288 |
| fallback/bundled-face advance rule | measured (#267), not shipped: 0.9536 NanumMyeongjo standing in for 휴먼명조; a 1/600-inch grid claimed on the advance | **measured to its end (#283), still not shipped**: the embedded face IS 휴먼명조 itself at 1.000 em/advance, not a Hancom substitute; the grid is on the pen position, not the advance; every candidate rule closes the substituted-Hangul residual (−60.04 → +0.64) but the break test falls 12/47 → 2/47 paragraphs | #283 |
| punctuation / bold advance | not modelled | **half-em / bracket-trim / auto-space hypotheses all measure ≈0; shipped instead: bold is drawn with the bold cut and advanced with the regular one** — installed-line width median \|Δ\| 56.57 → 10.56 HWPUNIT, proven over-measure 51 → 49/2272, breaks unchanged (0 regressions), shipped below the 99 % break gate on a stated criterion | #285 |
| the PDFs' anonymous Type-3 fonts | unidentified | **identified as HWP's own HFT faces** (한양신명조 / 한양중고딕 / HCI Poppy / …), predicted 8566/8566 anchored characters by `hh:font@type="HFT"`; 0/492 installed or bundled faces reproduce any of them; a one-width-per-class model reaches 93.0 % against the 99 % gate; **not shipped** — the two moel-2013 carriers are HFT punctuation over-measure exactly cancelling the 휴먼명조 stand-in's Hangul under-measure | #288 |
| advance computation | scattered call sites | **converged onto one seam, `_advance_hwp`** (`_metric_font_for_pt` helper), so #283's rule renderer and #285's bold behaviour share it without a further change | #286 |
| corpus raster, 144 dpi, cache (ssim / ssim_inked / line IoU, pages exact) | 0.8589 / 0.3739 / 0.7372, 10/10 (#281's tip) | **0.8607 / 0.3881 / 0.7375, 10/10** (#285/#286 tip; #288 byte-identical, measurement-only) | #285, #286 |
| corpus raster, 144 dpi, computed | 0.8383 / 0.3372 / 0.6643, 10/10 | **0.8402 / 0.3515 / 0.6651, 10/10** | #285, #286 |
| development-validation document | not opened since checkpoint-16 | **measured on #281's tip** (a comment there, this window): byte-identical to six decimals with #244/#268 — cache 0.6964/0.1834/0.5667, computed 0.6108/0.0982/0.2294; none of this round's rules fire there; the gap is still the page-bottom fit rule, no public witness | #281 (comment) |
| desktop line | #271 on renderer #268; re-merge onto #281 in flight, not landed | **re-merged twice**: #284 onto renderer #281 (one real conflict, both sides kept), #287 onto renderer #286 (no conflicts); all suites green both times; GUI smoke still **NOT RUN** (5.0–5.4 GB free, then 6.6 GB on a 99 %-full C:) | #284, #287 |
| writer line | unmoved since checkpoint-06 | still unmoved | — |
| runtime line | unmoved since checkpoint-06 | still unmoved | — |

For scale against the same fixed point checkpoint-18 used: #263
(checkpoint-15's renderer tip) recorded cache 0.8311/0.2766/0.6453 with 9/10
forms page-exact.

## 1. Branch DAG

Renderer line: **#281's tip forks into two research slices (#283, #285);
#285 gets a convergence partner (#283 → #286), but a third slice off #285
(#288) has not converged with either — the fork checkpoint-17 opened and
checkpoint-18 closed reopens here, on the advance/font-identity axis instead
of columns and rows.**

| PR | branch | base | slice |
|---|---|---|---|
| #283 | `claude/engine-e2-fallback-advance` | `claude/engine-e2-hanging-indent` (#279) | fallback/bundled-face advance rule measured to its end: the embedded face is 휴먼명조 itself, not a substitute; the grid is on the pen position; the substituted-Hangul residual closes but the break test worsens; **not shipped**, only a seam (`_advance_hwp`, `_face_source`) lands |
| #285 | `claude/engine-e2-punct-advance` | `claude/engine-e2-converge-05` (#281) | punctuation hypotheses all measure ≈0; **shipped instead**: bold is drawn with the bold cut, advanced with the regular one |
| #286 | `claude/engine-e2-converge-06` | `claude/engine-e2-punct-advance` (#285), merges in #283 | **convergence, one real integration**: every advance now comes out of one seam, `_advance_hwp`; full gates green |
| #288 | `claude/engine-e2-type3-faces` | `claude/engine-e2-punct-advance` (#285) | measurement-only: the anonymous Type-3 PDF fonts are HWP's own HFT faces; no installed/bundled TrueType face reproduces them; **not shipped**; per its own body "joins #286 as one more hop" — **not landed this window** |

Desktop line: two re-merges, one per renderer advance this window.

| PR | branch | base | note |
|---|---|---|---|
| #284 | `claude/desktop-on-renderer-281` | `claude/desktop-on-renderer-268` (#271) | re-merge onto renderer tip #281; one conflict in `_render_computed_lines` (desktop's inline-table re-entrancy reset vs #279's `indent` read), both sides kept; all suites green; GUI smoke **NOT RUN** (5.0–5.4 GB free, judged too thin for a clean Tauri release build) |
| #287 | `claude/desktop-on-renderer-286` | `claude/desktop-on-renderer-281` (#284) | re-merge onto renderer tip #286; **no conflicts**; all suites green; GUI smoke **NOT RUN** (6.6 GB free on a 99 %-full C:, still judged marginal) |

Desktop sits on #286, not on #288 — no gap in practice, since #288 changes
no renderer behaviour (`own_render.py` byte-identical to #285's).

Docs line: no new docs PR this window besides this checkpoint document
itself.

Writer line, unchanged from checkpoint-18 — still #224 → #235 → #238 → #239.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` / `-16` / `-17` / `-18` (each off its own
window's renderer state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #283 — the fallback-face advance rule, measured to its end: not shipped

**PDF glyph positions as the oracle (the export reproduces the save, #258);
path C NOT RUN.** Only a seam landed (`_advance_hwp`, `_face_source`);
`_measure` itself is untouched.

**Finding 1 — the embedded face is 휴먼명조 itself, not a Hancom
substitute.** nrf and moel embed `INPILL+휴먼명조` (the declared name in
CP949): 512 units per em, advances 0.2031 / 0.500 / **1.000** em, `name`
table stripped; its Hangul outlines match no face installed here (0/400
against every candidate, including 휴먼둥근헤드라인). The PDF's Hangul
advance of exactly 1 em is the *real* face's own metric — bundled
NanumMyeongjo at 0.9536 is the substitution, not the target.

**Finding 2 — #267's grid claim corrected.** The 13 pt advances are
108 units × 1515 and 109 × 797: mean = the declared 1300, mode = 1296.
Mean/cell is 0.9994–1.0006 on every face and size. The 1/600-inch grid is on
the **pen position**, not on the advance.

**Rules scored** (exact line widths/308 substituted lines · median |Δ|
HWPUNIT; installed faces stay 20/103 · 56.57 under all): current 2 · 256.69;
full-width = declared cell 0 · 303.59; cell + grid (round/floor/ceil)
10 · 235.57 / 240.45 / 247.57; + space floor 10 · 235.57; + Latin oracle
10 · 171.13. Per-character substituted-Hangul residual −60.04 → **+0.64**
(1758/3580 within 2 HWPUNIT); digits +68.37 → +60.35 (−1.99 with the
oracle).

**Break test (substituted multi-line paragraphs), the deciding channel:**
current 329/368 lines, **12/47 paragraphs** → every rule 291/368, **2/47**;
installed 1623/1697 · 48/113 unchanged under all. Per form: moel-2013
4/11 → 0/11, moel-2025 6/30 → 0/30, nrf 1/3 → 1/3. Proven over-measurements
51 → 90/2272; **all 39 newly overflowing lines carry ASCII punctuation**,
which an installed face meters +197.76 HWPUNIT too wide — twenty times the
term the rule fixed, opposite sign. A punctuation oracle alone: 76/2272,
333/368, 12/47 (costs 23 installed paragraphs). **Not shipped** — the
punctuation slice in flight (this became #285) owns that next term.

**Before/after identical:** cache 0.8516/0.3546/0.6866 (this branch predates
#278's page fix: 9/10), computed 0.8384/0.3361/0.6685, 10/10;
`lineseg_vs_pdf` 411/411; divergence 1353/113/349/243; `text_rebreak:width`
165; render-check-01 6·37·6·2/14·31·4·2, 9/9.

**Evidence:** `py_compile_sweep` 114/0; engine/tests 1524 passed/135
skipped; pins+package+cleanroom+floors 170; archive privacy HARD=0. **Full
gate, tip `cf4ff80`** (posted as a follow-up comment): `tests` 487/7/0
(6m54s) + `pipeline/tests` 1435/10/0 (10m24s), 0 failed overall.

**Not proven.** No substituted space was ever compared (the symbol slot
resolves to an installed face everywhere here); substituted Latin is 131
characters, 123 of one face and class; the embedded face is identified by
exclusion, not by name; `is_full_width` misses 40 ambiguous-width
characters; the substituted flag is per paragraph.

**Depends on:** #279.

### #284 — the desktop line on renderer tip #281

**One merge commit, no fix needed.** Base: `claude/desktop-on-renderer-268`
(#271). Depends on #271 (desktop) and #281 (renderer).

**One conflict, both sides kept:** `_render_computed_lines` in
`own_render.py` — the desktop's per-iteration `self._line_para = para` reset
(inline-table re-entrancy) plus the renderer's `indent = line.get("indent",
0)` from #279, the same pattern already present in the sibling
`_render_cached_lines`.

**Evidence (merged tree, one suite at a time):** `py_compile_sweep` 142/0;
engine/tests 1541 passed/135 skipped/0 failed; `tests` 1096 passed/7
skipped/0 failed (two halves); `pipeline/tests` 1437 passed/10 skipped/0
failed (three pieces); geometry/runtime-render/own selection 211 passed;
archive privacy HARD=0 (WARN 55: fixture IDs and font assets). The table,
row and indent changes move text and caret positions in the desktop's own
render path; the covering tests (`test_runtime_geometry`, `test_runtime_
plan`, `test_runtime_render`) pass.

**Desktop GUI smoke: NOT RUN.** 5.0–5.4 GB free on C: is below what a clean
Tauri release build needs; a pre-built exe smoke is not cited. The claim
"the app built from this tree renders and edits" stays open until a build
from this sha runs the smoke.

**Stated, not done:** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248; ownership per #253).

**Depends on:** #271 (desktop) and #281 (renderer). No comments.

### #285 — bold is drawn with the bold cut and advanced with the regular one

**Punctuation hypotheses all fail on measurement; what shipped instead came
from the other side of the same probe.** PDF glyph positions as the oracle
(#258); path C NOT RUN.

**Per code point, installed faces (545 advances, Σ over-measure +19431 →
+15013 HWPUNIT after the fix):** `(` n=24, Hancom 0.2835 em vs ours 0.4035
(×1.42, our H2GTRM vs the PDF's anonymous T6/T19); `" "` n=8, 0.3925 vs 1.03
(×2.62); `)` n=13, 0.3321 vs 0.4950 (×1.51, H2MJSM → T2); `-` n=178 on
맑은 고딕 Bold 0.3903 vs 0.3937 (×1.009, was ×1.018); `(` n=10 on 맑은 고딕
Bold **×1.0002** (was ×1.177); Batang's `, ○ · (` n=61 at ~1.00, Σ −39.
**Inter-class gaps** Hangul→space/punct/full-width punct/digit and
digit→Hangul, Latin→Hangul: **0.0000 em** on 921 pairs; `autoSpaceEAsianEng`/
`Num` appear on **no** `hp:paraPr` in the corpus (774 elements carry only
id/tabPrIDRef/condense/fontLineHeight/snapToGrid/suppressLineNumbers/
checked/textDir).

**Rules scored, none shipped:** (i) half-em closing punctuation — no such
code point in the corpus, and `『』○□·` match hmtx within 1.4 % on
name-matched faces; (ii) bracket trim — `『』` 0.5035 vs 0.5072, nothing
trimmed; (iii) 1/4-em auto-space — 0.0000; (iv) hmtx — correct, *given the
right face*.

**What shipped.** `(` measures 0.3047 em regular/0.3579 bold/**Hancom
0.3046**: bold is applied as a `charPr` attribute over a regular face, and
the advance is the regular cut's. `_installed_regular_cut` +
`_metric_font_for` consult `font_index` only, so substituted faces are
untouched (their median |Δ| stays 256.69 exactly). Bold installed advances
Σ|err| 8785 → 1894. 6 tests; two pinned agreement rows updated with rationale
(kstartup 452 → 454, 433 → 435; corpus 2119 → 2121, 2037 → 2039 — gains
only).

**moel-2013's carriers 118/141 did not move** — their Hangul slot is
*bundled* Nanum Myeongjo, not installed; the +1165/+815 is `( ) : ,` at
0.495 vs T2's 0.332 (~+1330 on 141) and `" "` at 1 em vs 648 (+2469 on 118
line 0). The anonymous Type-3 faces there stayed an open question — #288
resolves what they are.

**Measured, 144 dpi.** Installed-line width median |Δ| 56.57 → **10.56**;
exact 20/103 → 23/103; proven over-measure 51 → **49**/2272; breaks 48/113
and 12/47 **unchanged, 0 regressions**. cache ssim 0.8589 → 0.8607,
ssim_inked 0.3739 → **0.3881**, IoU 0.7372 → 0.7375; computed 0.8383 →
0.8402, 0.3372 → **0.3515**, 0.6643 → 0.6651; pages 10/10 both.
`lineseg_vs_pdf` 411/411. Divergence 1612/113/300/28 → **1635/111/279/28**;
roots `text_rebreak:width` 165 → 165, `table_row_heights` 81 → 63,
`cell_valign` 18 → 15. render-check-01 unchanged (6·37·6·2/14·31·4·2, 9/9).

**Why shipped below the 99 % break gate:** the gate is unreachable by any
advance rule (baseline 42.5 % on installed multi-line paragraphs); the
change was taken on 0 regressions, 51 → 49 over-measures and every raster
channel up — stated as the criterion actually used.

**Evidence:** `py_compile_sweep` 116/0; engine/tests 1540 passed/135
skipped; pins+package+cleanroom+floors 170; archive privacy HARD=0. **Full
gate, tip `0f3ba46`** (posted as a follow-up comment): `tests` 493/3/0
(7m04s) + `pipeline/tests` 1437/8/0 (8m51s), 0 failed overall.

**Not proven.** The bold rule rests on one family (맑은 고딕); a file that
*names* a bold face is untested; `"` at half the 1/600-in cell is one
observation; `text_rebreak:width` untouched.

**Depends on:** #281.

### #286 — converge #283 onto the #285 tip; one advance seam

**One merge commit, no fix commit; full gates green.** Depends on #285 and
#283.

**Three conflicts, one of them a real integration:** `own_render.py` —
#285's inline bold-metric substitution vs #283's `_advance_hwp` seam;
resolved by moving the metric-font substitution *inside* the seam (a
`_metric_font_for_pt` helper so the seam, which already has the point size,
does not re-derive it). **Every advance now comes out of one function,
`_advance_hwp`**, and `advance_probe.py`'s rule renderer (from #283)
inherits #285's bold behaviour without a change. `advance_probe.py` — two
independent flag groups (`--punct`; `--fallback-rules`/`--no-break-test`)
added at the same point, both kept. `own-render-notes.md` — entries
reordered into PR order (#283 before #285).

**Verified on the tip, all exact matches to #285 (144 dpi):** cache ssim
0.8607/ssim_inked 0.3881/IoU 0.7375, pages 10/10; computed 0.8402/0.3515/
0.6651, 10/10; `lineseg_vs_pdf` 411/411; `advance_probe --punct` installed
median |Δ| 10.56, substituted 256.69 (same under `--fallback-rules`);
render-check-01 6·37·6·2 at 96 dpi, 14·31·4·2 at 144, 9/9. For scale: at
#263 the cache means were 0.8311/0.2766/0.6453 with 9/10 pages.

**Full gate on this tip (`0422903`), posted directly in the PR body, all
foreground, one suite at a time:** `py_compile_sweep` 116/0; engine/tests
1548 passed/135 skipped; pins+package+cleanroom+floors 170; `tests` 489
passed/7 skipped/0 failed; `pipeline/tests` 1435 passed/10 skipped/0 failed;
archive privacy HARD=0.

Everything stays `own-uncertified`; path C NOT RUN anywhere; the corpus is
the training set.

**Depends on:** #285 and #283. No comments.

### #287 — the desktop line on renderer tip #286

**One merge commit, no conflicts, no fix needed.** Base:
`claude/desktop-on-renderer-281` (#284). Depends on #284 (desktop) and #286
(renderer).

**Evidence (merged tree, one suite at a time):** `py_compile_sweep` 142/0;
engine/tests 1555 passed/135 skipped/0 failed; `tests` 1096 passed/7
skipped/0 failed (two halves); `pipeline/tests` 1437 passed/10 skipped/0
failed (three pieces); geometry/runtime-render/own selection 211 passed;
archive privacy HARD=0 (WARN 55: fixture IDs). The bold-advance rule moves
caret x on bold runs in the desktop's own render path; the covering tests
(`test_runtime_geometry`, `test_runtime_plan`, `test_runtime_render`) pass.

**Desktop GUI smoke: NOT RUN.** 6.6 GB free on a 99 %-full C:, only
marginally above the level judged too thin for a clean Tauri release build;
a pre-built exe smoke is not cited. The claim "the app built from this tree
renders and edits" stays open until a build from this sha runs the smoke.

**Stated, not done:** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248; ownership per #253).

**Depends on:** #284 (desktop) and #286 (renderer). No comments.

### #288 — the anonymous Type-3 fonts are HWP's own HFT faces

**Measurement only; `own_render.py` byte-identical.** PDF as oracle; path C
NOT RUN.

**Fonts across the ten reference PDFs:** 41 sfnt objects (all embedded,
`INPILL+…`) + **37 Type 3** fonts (`FontMatrix .001`, real vector
`CharProcs`), 844 code points, 772 inked. `engine/scripts/pdf_face_probe.py`
enumerates, attributes and tries to identify them.

**What T2/T6/T19 are.** Their `Encoding/Differences` name glyphs literally
`HFT1 … HFT70`; the HWPX header declares 148 `hh:font@type="HFT"` entries
over 13 faces (한양신명조, 한양중고딕, 명조, 고딕, HCI Poppy …). T2 ⇒
한양신명조 + HCI Poppy; T3/T19 ⇒ 한양중고딕; T6 is T2's outlines stroked
`20 w B` — synthetic bold — and 47/47 such pairs carry the same advance (the
#285 rule, seen from the other side). On 8566 anchored characters,
`@type="HFT"` on the slot HWP uses predicts Type-3 usage **8566/8566**; the
slot HWP uses for ASCII punctuation is `latin`, not our `symbol` (22
characters separate them). Identity search: 21 of 37 fonts have **0 of 492**
installed/bundled faces reproducing every width; best outline IoU 0.782 —
these faces are not on this machine in any TrueType form.

**The carriers reconciled.** ¶141 (+815 over its box): T2 punctuation
`(` +655, `)` +649, `-` +642, `:` +271, `,` +53 = +2276, against the
휴먼명조 stand-in's Hangul −1128; net +1148. ¶118 line 0: T2 +3078/휴먼명조
−1823 = +1255; line 1: +1660/−1658 = **+2**. The two errors cancel today;
fixing either alone opens the other.

**Fixed fractions: no.** One width per class within a font covers **93.0 %**
of 844 code points (punctuation 52.2 %, Latin 27.8 %) against the 99 % gate;
명조/고딕 are 0.5 em flat, but 한양중고딕 has `(` 0.2880 ≠ `)` 0.2810. A
per-(face, code point) table is 350/350 — that is a corpus inventory, not a
rule. **Not shipped.** What a correct fix needs is the HFT advance tables
themselves, which are Hancom's; the legal line here allows public documents
and black-box output only, so the road is a measured per-face width table
from the PDFs, declared as such.

**Measurements unchanged:** cache 0.8607/0.3881/0.7375, computed
0.8402/0.3515/0.6651, pages 10/10; `lineseg_vs_pdf` 411/411; classes
1635/111/279/28; roots `text_rebreak:width` 165, `table_row_heights` 63,
`empty_paragraph` 29, `cell_valign` 15, `forced_break` 7; render-check-01
6·37·6·2/14·31·4·2, 9/9.

**Evidence:** `py_compile_sweep` 117/0; engine/tests 1553 passed/135
skipped; pins+package+cleanroom+floors 170; 13 mechanism tests for the
probe, no inventory pins; archive privacy HARD=0. **Full `pipeline/tests`
gate: the PR body states "appended below" — no follow-up comment has been
posted (verified: #288 carries zero comments as of this checkpoint). This
must not be read as a confirmed green result; treat it as pending, the same
way checkpoint-18 treated #280's unposted gate.**

**Not proven.** Attribution reaches 350 of 844 code points (cells sit
outside the pairing); `HFT` is trusted from the attribute, never verified
against an HFT file; the latin-slot rule rests on 22 observations; a machine
with the HFT set installed could export differently; the two carriers are
further from closing than they look, because today's two errors cancel.

**Depends on:** #285 (its own body: "joins #286 as one more hop" — **not
landed this window**).

## 3. The development-validation document, this window

**Measured once, on #281's tip, in a comment posted there (not in any of
#283–#288).** 96 dpi: cache ssim 0.6964/ssim_inked 0.1834/line IoU
0.5667/pair 0.9150; computed 0.6108/0.0982/0.2294/0.7793 — **identical to
six decimals with the numbers recorded at #268 and #244.** None of this
round's rules fires there: its cells declare their own margins (#268/#275/
#277 default paths untouched), its tables are not what drifts, and it uses
no `hh:intent`. Its computed-vs-cache gap is still the one #255/#256/#257
traced — the page-bottom fit test at the first page boundary, where
Hancom's editor keeps a line box that crosses the body bottom by 566
HWPUNIT and computed does not — and the public corpus contains no page that
decides that rule. Stated as the standing limit, not a regression. A public
witness (a Hancom round-trip of the page-fit probe) needs the COM ownership
agreement before it can run. Neither #283, #285, #286 nor #288 opened this
document again; its 5 one-line-shorter export paragraphs, the 40 ±1
character-split paragraphs and their untested font-resolution hypothesis
remain untouched, unchanged from checkpoint-18.

## 4. Regressions (with the PR's or commit's own explanation)

**None claimed this window.** #285's shipped bold-advance fix reports 0
break regressions and every raster channel up (installed-line median |Δ|
56.57 → 10.56, cache/computed ssim, ssim_inked and line IoU all rising, page
counts unchanged 10/10 both). #283 and #288 change no rendering behaviour —
#283 lands only the `_advance_hwp`/`_face_source` seam with its fallback
rule left unshipped, and #288 is measurement-only, `own_render.py`
byte-identical — so neither can regress anything by construction. #286's
convergence and #284/#287's desktop re-merges each report their post-merge
numbers matching the pre-merge branches exactly or improving, with no new
regression claimed.

**Unsupported, newly named this window.** HFT-declared PDF fonts have no
TrueType metric on any machine without the Hancom HFT set installed (#288)
— stated as a documented limit of own-render for HFT-declared runs, not a
regression to fix here.

**Integration conflicts, resolved.** #286's real integration: #285's inline
bold-metric substitution and #283's `_advance_hwp` seam both touched
`own_render.py`'s advance path; resolved by moving the substitution inside
the seam via a new `_metric_font_for_pt` helper, so every advance now comes
from one function. Its other two conflicts (`advance_probe.py`'s two
independent flag groups, `own-render-notes.md`'s log ordering) were purely
additive, both kept. #284's one conflict (`_render_computed_lines`'s
per-iteration reset vs #279's `indent` read) was resolved keeping both
sides, mirroring a pattern already present in the sibling function. #287
merged with no conflicts at all.

## 5. Unsupported / declared elements still open

Carried from checkpoint-18, with this window's closures and new items:

- **Closed this window:** none of checkpoint-18's fully-open items closed.
  The bundled-face advance rule moved from "measured (#267), not shipped"
  to **"measured to its end (#283), still not shipped, with two of #267's
  own claims corrected"** — a conclusive measurement, not a closure, since
  no advance rule clears both the residual and the break test at once.
- **New, named and measured, still open:** the fallback-face advance rule
  itself — every candidate closes the substituted-Hangul residual but drops
  the break test 12/47 → 2/47, so none ships (#283); the punctuation
  hypotheses (half-em closing punctuation, bracket trim, quarter-em
  auto-spacing) all measure at or near zero and none ships, though the bold
  finding from the same probe does (#285); the PDFs' 37 anonymous Type-3
  fonts are now identified as HFT faces but no fix ships — 0/492 installed
  or bundled faces reproduce them, and a one-width-per-class model tops out
  at 93.0 % against the 99 % gate (#288); the two moel-2013 carriers'
  errors cancel today, so fixing either alone would open the other (#288);
  the renderer's two open siblings, #286 and #288, have not converged this
  window — #288's own body names the hop as owed; the desktop GUI smoke has
  still never run, across two more re-merges, though free disk moved from
  5.0–5.4 GB to 6.6 GB (#284, #287) and is still judged marginal.
- **Unchanged from checkpoint-18, still fully open:** the 4
  saeopja-48027 cells gridmax leaves unexplained (#277); the table-split
  rule's single witness (kstartup tbl9, #278) and `repeatHeader`'s complete
  lack of a positive corpus case; the move-whole anchored-table arm's
  generalization beyond `CELL` + anchored, untested; the overflow clamp on
  gridmax, untested; the page-bottom fit-rule candidate (`vertsize −
  spacing`, #256/#260), still needing a Hancom round-trip and a COM
  ownership agreement not yet in place; the development-validation
  document's 5 line-count and 40 character-split discrepancies and their
  font-resolution hypothesis (#258/#260), not reopened this window beyond
  the aggregate re-measurement on #281 (see §3); computed layout's own
  +1800 page-top drift against that document's PDF (#257), unaddressed; the
  `LayoutSnapshot` contract and `x1` glossary (#253), no response recorded;
  `layout_policy`/`layout_policy_reason` still not surfaced in the desktop
  UI; the acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item); Codex-app-closed sessions moved; Cursor login.
- **New, owed:** the #286/#288 convergence hop, unlanded — #288 changes no
  renderer behaviour, so the merge is expected to be mechanical, but that is
  unmeasured until it happens; #288's full `pipeline/tests` gate — never
  posted as its own comment, must not be treated as a confirmed green
  result (mirrors checkpoint-18's treatment of #280); a legal, measured
  per-face HFT width table from the public PDFs, named by #288 as the road
  to closing the two moel-2013 carriers.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #283 | engine/tests 1524/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 487/7/0 (6m54s) + `pipeline/tests` 1435/10/0 (10m24s), tip `cf4ff80` — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 114/0; archive privacy HARD=0 |
| #284 | engine/tests 1541/135/0; `tests` 1096/7/0 (two halves); `pipeline/tests` 1437/10/0 (three pieces); geometry/runtime-render/own selection 211 passed | **posted directly in the PR body, all green, 0 failed** | `py_compile_sweep` 142/0; privacy HARD=0 (WARN 55: fixture IDs, font assets); GUI smoke NOT RUN (5.0–5.4 GB free) |
| #285 | engine/tests 1540/135 skipped; pins170 | **`tests` 493/3/0 (7m04s) + `pipeline/tests` 1437/8/0 (8m51s), tip `0f3ba46` — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 116/0; archive privacy HARD=0 |
| #286 | engine/tests 1548/135 skipped; pins170 | **`tests` 489/7/0 + `pipeline/tests` 1435/10/0, tip `0422903`, posted directly in the PR body — 0 failed overall** | `py_compile_sweep` 116/0; archive privacy HARD=0 |
| #287 | engine/tests 1555/135/0; `tests` 1096/7/0 (two halves); `pipeline/tests` 1437/10/0 (three pieces); geometry/runtime-render/own selection 211 passed | **posted directly in the PR body, all green, 0 failed** | `py_compile_sweep` 142/0; privacy HARD=0 (WARN 55: fixture IDs); GUI smoke NOT RUN (6.6 GB free, 99 % full) |
| #288 | engine/tests 1553/135 skipped; pins170; 13 mechanism tests for the probe, no inventory pins | **stated in the PR body as "appended below" — never posted as its own comment; treat as pending, not green** | `py_compile_sweep` 117/0; archive privacy HARD=0 |

#283 and #285 each post their full gate as a follow-up comment, both green.
#284, #286 and #287 post their full gate directly in the PR body, all
green. #288's promised gate has not appeared as a comment as of this
checkpoint and must not be read as an independently-confirmed green result.

## 7. Integration conflicts expected when lines converge

**One real integration landed this window, in #286.** #285's inline
bold-metric substitution and #283's `_advance_hwp` seam both touched
`own_render.py`'s advance path; resolved by moving the substitution inside
the seam through a new `_metric_font_for_pt` helper, unifying every advance
computation behind one function. Two more conflicts in the same merge
(`advance_probe.py`'s two independent flag groups, `own-render-notes.md`'s
log reordering) were purely additive.

**Desktop converged twice, cleanly.** #284's one conflict
(`_render_computed_lines`'s per-iteration reset vs #279's `indent` read) was
resolved keeping both sides, the same pattern already used in the sibling
`_render_cached_lines`. #287 merged with no conflicts at all.

**The renderer's two current siblings remain unconverged.** #288 is
measurement-only and byte-identical to #285 in `own_render.py`, so its merge
with #286 is expected to be mechanical or trivial — but that is
**unmeasured** until the hop actually lands; #288's own body only states it
"joins #286 as one more hop."

**Writer and runtime lines remain unconverged with anything**, unchanged
from checkpoint-18.

## 8. Next measurable research question

**In the order the open items point to: a legal, measured per-face HFT
width table from the public PDFs; the page-fit witness via a Hancom
round-trip; the 4 saeopja-48027 cells; `repeatHeader`.** #288 names the
first directly — the two moel-2013 carriers' cancelling errors and the
93.0 %-vs-99 %-gate one-width-per-class model both point to measuring HFT
face widths from public, black-box PDF output rather than reading Hancom's
own (non-public) HFT tables. Second, the page-bottom fit-rule candidate
(`vertsize − spacing`, #256/#260) still needs a Hancom round-trip and remains
blocked on a COM ownership agreement not yet in place — the
development-validation document's identical-to-six-decimals re-measurement
this window (§3) confirms this is still the one gap the public corpus
cannot decide. Carried alongside: the 4 saeopja-48027 cells gridmax leaves
unexplained (#277); the table-split rule's single witness (kstartup tbl9,
#278) and `repeatHeader`'s complete absence of a positive corpus case.
Structurally prior to all of these: the #286/#288 convergence hop itself,
still unlanded, and whether the desktop's GUI smoke can finally run once
disk allows — free space moved from 5.0–5.4 GB to 6.6 GB across #284/#287
but has not yet cleared the bar.

## 9. Certification status

Every result in this checkpoint — #283 (fallback-face advance, measured to
its end, not shipped, seam only), #284 (desktop re-merge onto #281, no fix
needed), #285 (bold-advance rule, shipped fix), #286 (advance-seam
convergence, no fix commit of its own), #287 (desktop re-merge onto #286, no
fix needed), #288 (Type-3/HFT face identification, measurement only, not
shipped) — remains **own-uncertified**. `render_cert.py` still cannot
certify this renderer absent a PDF text layer, unchanged since checkpoint-01.

**What moved, restated plainly:** this window closed out the fallback-face
advance question #267 had left measured-but-unshipped since checkpoint-14/
15's era — #283 shows conclusively that no candidate rule can both close
the substituted-Hangul residual and hold the break test, so the rule stays
out, correcting along the way which face is actually embedded (real
휴먼명조, not a Hancom stand-in) and what the 1/600-inch grid actually
governs (the pen, not the advance). A second, independent probe aimed at
punctuation spacing instead found and shipped a different, smaller fix —
bold runs draw with the bold cut but advance with the regular one — clearing
a real chunk of installed-face over-measure (median |Δ| 56.57 → 10.56) with
zero break regressions, deliberately shipped below the 99 % break gate on a
stated rationale that the gate is unreachable by any advance rule at all.
#286 then unified every advance computation behind one seam. #288 pushed
the remaining PDF-vs-render gap to its root: the ten reference PDFs' 37
anonymous fonts are Hancom's own non-TrueType HFT faces, not obscure
third-party fonts, so no font hunt on this machine — 492 candidates,
21 fonts with zero matches — can ever close them; the fix has to be a
measured public-PDF width table, not a font substitution. The renderer,
single-tipped at #281 entering this window, is **two-tipped again** at its
close: #286 (#283+#285 converged) and #288 (measurement-only, off #285,
unconverged). The desktop line moved twice, cleanly, staying one hop behind
the renderer's research tip but current with everything that ships
(#286); its GUI smoke has still never run.

**Owed, carried forward from checkpoint-18, plus this window's additions:**

- The #286/#288 renderer convergence hop — not landed; expected mechanical
  since #288 changes no rendering behaviour, but unmeasured until it
  happens.
- #288's full `pipeline/tests` gate — never posted as its own comment; not
  to be treated as an independent result (mirrors #280 at checkpoint-18).
- A legal, measured per-face HFT width table from the public PDFs (#288) —
  the stated road to closing the two moel-2013 carriers, since Hancom's own
  HFT tables are out of scope.
- The 4 saeopja-48027 cells gridmax leaves unexplained (#277).
- The table-split rule's single witness (kstartup tbl9, #278) and
  `repeatHeader`'s complete lack of a positive corpus case.
- The move-whole anchored-table arm's generalization beyond `CELL` +
  anchored — untested outside what the corpus already shows (#278); the
  overflow clamp on gridmax — untested (#277).
- A public path-A witness for the `vertsize − spacing` page-bottom fit
  candidate (#260, #256) — needs a Hancom round-trip, needs COM ownership
  agreement not yet in place; the development-validation document's
  re-measurement on #281 (§3) again lands on exactly this gap.
- The development-validation document's font-resolution hypothesis for its
  5 line-count and 40 character-split discrepancies (#260) — not opened
  beyond the aggregate re-measurement this window.
- Computed layout's own +1800 page-top drift against the
  development-validation document's Hancom-exported PDF (#257) —
  unresolved, untouched this window.
- The desktop's build-from-merged-source GUI smoke evidence (#248, #262,
  #266, #271, #284, #287) — still does not exist; free disk moved 5.0–5.4 GB
  → 6.6 GB but remains judged marginal.
- The `LayoutSnapshot` proposal (#253) — no response recorded this window;
  no level-C run exists anywhere (path C NOT RUN on every PR this window).
- `layout_policy`/`layout_policy_reason` surfaced in the desktop UI — still
  not a branch or PR.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.

## 10. Coordinator interaction this window

**No new coordinator status request arrived this window.** REG-001
(2026-09-05 23:47 KST) and STATUS-001 (2026-09-06 00:51 KST) — both already
recorded in checkpoint-18 — remain the only coordinator requests on file;
both were answered as comments on #274 because its message pipe was stale
each time, and #274 stayed the fallback handoff channel throughout
checkpoint-18's window. No later request has arrived to supersede them, and
none of #283–#288 records a new one. Recorded here again so that #274's
role as the standing handoff channel — not a stale, one-time exception —
carries forward into this checkpoint.
