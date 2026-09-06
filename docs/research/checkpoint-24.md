# Checkpoint 24 — the Korean break unit ships as the syllable, a substituted 휴먼명조 face closes eleven lines, and the reconverged numbers diverge from #322's own body by a rule its chain never had

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-23` (this
branch, `claude/docs-checkpoint-24`, is cut from `origin/claude/docs-checkpoint-23`
and stays unmerged). All eight PRs covered this window are **OPEN/DRAFT** —
nothing in this window has merged to `main`. Covers research **#316**
(`claude/engine-e2-syllable-13`, on #313: the public format document makes the
Korean break unit a one-bit switch with no exception clause; the cache breaks
70 of 204 `KEEP_WORD` lines inside a 어절; the 13 lines the `syllable`
candidate regressed in checkpoint-23 split into 11 stand-in-face width errors
and 2 right-edge-budget admissions; nothing shipped), **#317**
(`claude/engine-e2-line-height-remainder`, on #314: the 19 `text_line_height`
class-B paragraphs are one dropped `hp:lineBreak` control; the 15
`cell_valign` paragraphs are an exact re-solve of a box `table_row_heights`
or a re-break elsewhere already moved; nothing shipped), **#320**
(`claude/engine-e2-standin-11`, on #316: the 11 stand-in-face lines are all
one substituted face, 휴먼명조, measured from the reference PDFs' own glyph
origins at 0.996 em against the bundled stand-in's 0.950; ships a
`standin_faces` section in the measured width table and its resolver, the
breaker not switched), **#321** (`claude/engine-e2-wrap-36`, on #319:
`kstartup` table 36's `vertOffset` is `xs:nonNegativeInteger` in three
independent public sources, not a signed field; the export seats the table as
if the wrapped offset were 0, not as the signed −213 the prior checkpoint's
repair candidate proposed; nothing shipped, no rule met the spec's own
condition to ship), **#322** (`claude/engine-e2-syllable-switch`, on #320:
ships the syllable break unit for CJK cells, reproducing the `syllable`
candidate by construction, with one declared regression, `kstartup` ¶719);
integration **#319** (`claude/engine-e2-seating-setter`, on #317: a
`table_index` property setter on `SeatingRenderer`, fixing the two errors
#318 found, orchestrator's own hand edit, no worker); convergence **#323**
(`claude/engine-e2-converge-13`, on #314, merges #321's chain — carrying #317
and #319 — and #322's chain — carrying #316 and #320 — with no conflicts;
computed raster 0.864976 / 0.409681 / 0.728976 and `layout_divergence`
1932/42/48/31 both differ from what #322's own body predicted, explained
below as the orchestrator's reading, not the PRs'); desktop **#318**
(`claude/desktop-on-renderer-314`, on #310, tip #314: re-merge bringing in
#311/#312/#313; 2 errors traced to a cross-line `table_index` collision and
fixed by cherry-picking #319; a further paragraph-join regression traced to
the desktop line's own `layout_divergence` edit from #262 and fixed on this
branch; final gate green). **A desktop re-merge onto #323 and an
`hp:lineBreak` breaking slice on #322 are both in flight as this document is
written; both are unnumbered and neither is counted here.**

**A process deviation, continued from checkpoint-23, stated plainly, without
speculation about cause:** every Opus research worker this round — #316,
#317, #320, #321, #322, and the diagnostic fix posted as #318's third
comment — self-reports running as `claude-opus-5[1m]` (Claude Opus 5 on a
1M-token context window), against the project rule and against each launch's
request for plain Opus. Each PR records this itself rather than the checkpoint
asserting it (see §9). #318's own re-merge (the PR body, as opposed to its
fix comment) is recorded only as "Merge: Sonnet," no context figure, the same
pattern as #310 and #305 before it. #319's edit and #323's merge both ran on
standard context: #319 is "orchestrator: Fable, edit by hand (no worker)"
and #323's worker states plainly "Worker: claude-sonnet-5 (Claude Sonnet 5),
200K-token context window (not 1M)."

**Two open decisions for the product/reviewer, stated plainly (carried from
checkpoint-21, unchanged in kind this window):**

1. **Whether #301's 96-HWPUNIT right-edge tolerance is acceptable as a
   declared error budget for the advance metrics**, rather than being read
   as (or mistaken for) a Hancom fit rule. The admissible window stays
   [18.5, 26.3) per #307 — no PR this window re-derives it, so it is carried,
   not restated by anyone this round. **This window's addition (not a
   resolution):** #316 measures that a budget of 0 recovers `kstartup` ¶719
   (the only installed-face regression the `syllable` candidate has) at no
   cost, but the other twelve of its own thirteen would need a *negative*
   budget of at least −911 HWPUNIT, and the score collapses below the
   shipped breaker's own numbers long before that. #322, shipping the
   syllable unit, quotes exactly this finding as its reason for leaving the
   budget at 96 rather than tuning it off one paragraph: "changing the
   budget on the evidence of one paragraph is not a measurement of the
   budget." `kstartup` ¶719 is now a shipped, declared, pinned regression
   rather than a probe finding — the reviewer's call on 96 is unmoved, with
   one more concrete paragraph now depending on it. Still open.
2. **The sidecar data-list line** in `desktop/sidecar/build.ps1` — adding
   `engine/references/fonts/hft-widths.measured.json` so a frozen desktop
   build does not silently fall back to the pre-#292 HFT metric. Still
   unowned this window; #318 restates it "still stands for the product
   line," the same language #310 and #305 used before it. **This window's
   addition:** #320 adds a new `standin_faces` section to that same JSON
   file (145 code points, 2330 observations, 4 forms, for 휴먼명조 alone), so
   the file the sidecar line would add now carries more than it did at
   checkpoint-23 — the missing line now also withholds the stand-in-face
   table from a frozen build, not only the HFT one. No PR this window edits
   `build.ps1`. Ownership sits on the product side per #253.

## What changed since checkpoint-23

| metric | checkpoint-23 | checkpoint-24 | moved in |
|---|---|---|---|
| renderer-line tip | #314 (`claude/engine-e2-converge-12`) | Two chains off #314: **#317 → #319 → #321** (probes + one integration fix, `own_render.py` untouched by any of the three) and **#313 → #316 → #320 → #322** (#316 probe; #320 ships `standin_faces` data; #322 ships the syllable break unit) — **#323 converges both onto #314**; tip is now #323 | #316, #317, #319, #320, #321, #322, #323 |
| class-B remainder (102, #314) | `table_row_heights` 63, `text_line_height` 19, `cell_valign` 15, `page_top_unattributed` 3, `text_rebreak:width` 2 named open | #317 measures but does not close `text_line_height` (one `hp:lineBreak` carrier) and `cell_valign` (exact re-solve, both roots inherited); #321 measures but does not close a `table_row_heights` side question (`kstartup` table 36's seat); #320's stand-in table moves `text_rebreak:width` 2 → 4 (chain-B-local, pre-#312 baseline); #322 ships the syllable unit and moves `table_row_heights` 63 → 12, `text_line_height` 19 → 20, `cell_valign` 15 → 13, `text_rebreak:width` 4 → 0 (all chain-B-local numbers, still missing #312's `empty_paragraph` rule) | #317, #320, #321, #322 |
| the syllable break unit | measured only, `syllable` candidate: installed 89/113, other 10/47, 13 regressions, 43 gains (#313) | **shipped** (#322): CJK-CJK breaks allowed regardless of the declared `breakNonLatinWord`; with #320's stand-in table already in the tree, installed 89/113, other **32/47** (up from 10/47), **1** regression (`kstartup` ¶719, declared and pinned), 53 gains; `breakNonLatinWord` moves `PARAPR_HONORED` → `PARAPR_NOT_HONORED` | #322, built on #320 |
| the 13 syllable regressions | undiagnosed, next slice's named job (#313) | **11 are one substituted face** (휴먼명조, bundled at 0.950 em against the reference PDFs' own 0.996 em, #320); **2 are the right-edge budget** admitting an over-box span (`kstartup` ¶719, `nrf` ¶32, #316) | #316, #320 |
| installed-face punctuation residual | +253.3 HWPUNIT / 487 advances, "no mechanism yet" | **unchanged, not re-measured this window** — no PR this round revisits it | — |
| `kstartup` table 36's origin | unsigned-wrap defect found, not chased (#311) | **measured, not shipped** (#321): the OWPML schema, Hancom's own model source, and the HWP 5.0 binary document all declare `vertOffset`/`horzOffset` `xs:nonNegativeInteger` / `UINT32`, not signed; the reference PDF's export agrees with reading the wrap as 0 (+0.10 px) and disagrees with reading it as signed −213 (−4.16 px) — one witness, nothing shipped | #321 |
| `layout_divergence` classes (agree/A/B/C), renderer line | 1830 / 94 / 102 / 28 (#314) | chain-B-local (pre-#312): 1801/94/131/28 (#316, unchanged) → 1799/94/133/29 (#320) → **1903/42/77/31, A&B 1 → 0** (#322's own body); **#323's merged tree measures 1932/42/48/31** — A (42) and C (31) match #322's own expectation exactly, agree/B do not, though agree+B is 1980 in both, explained below (§7) | #322 (own numbers), #323 (measured, differs) |
| corpus raster, 144 dpi, cache (ssim / ssim_inked / IoU) | 0.861944 / 0.393719 / 0.736589 (#314) | chain-B-local: 0.861944/0.393719/0.736589 (#316) → **0.868907/0.418264/0.743523** (#320) → **0.868910/0.418275/0.743520** (#322, NOT byte-identical to #320 — `kstartup`'s line-IoU dips 0.780876→0.780847 because the breaker still runs on paragraphs with no usable cached `hp:lineseg` even under `cache` policy) → **#323 measures the same 0.868910/0.418275/0.743520**, matching #322 exactly | #320, #322; confirmed #323 |
| corpus raster, 144 dpi, computed (ssim / ssim_inked / IoU) | 0.850452 / 0.373788 / 0.706026 (#314) | chain-B-local: 0.848325/0.364894/0.692148 (#316, pre-#312 baseline) → 0.853950/0.383682/0.698067 (#320) → 0.862849/0.400787/0.715097 (#322's own body) → **#323 measures 0.864976 / 0.409681 / 0.728976** — higher than #322's own number on all three channels, explained below (§7) as #312's rule reaching this chain for the first time in the merge | #320, #322 (own), #323 (measured, higher) |
| `lineseg_vs_pdf` | 411/411 lines, 8566/8566 chars | **unchanged everywhere this window** (a control; cannot see the flow pass) — #316, #320, #322 and #323 all report 411/411, 8566/8566 | unchanged |
| `right_edge_probe --corpus --breaks`, shipped row | 48/113 installed, 21/47 other, 0 regressions | chain-B-local: unchanged through #316 and #320 → **89/113, 32/47** after #322 ships the syllable unit (the same number the `syllable` candidate scored with #320's table already in the tree); #323 confirms 89/113, 32/47 via the `tol12` candidate matching the shipped row exactly | #322, confirmed #323 |
| desktop line | #310 (on renderer tip #308), a re-merge onto #314 in flight, unnumbered | **#318 lands that re-merge onto #314**, bringing in #311/#312/#313; 2 errors (a `table_index` setter collision) fixed by cherry-picking #319; a further paragraph-join regression traced to #262's `layout_divergence` edit and fixed on this branch (commit b451cb6); final gate green, matching the renderer line's own numbers exactly; a further desktop re-merge onto #323 is now in flight, unnumbered | #318, #319 |
| worker model / context | #311/#312/#313 self-report 1M against the rule; #314 explicitly 200K; #310 "Sonnet," no figure | **new this window**: #316, #317, #320, #321, #322 self-report `claude-opus-5[1m]`; #318's re-merge body states "Merge: Sonnet," no figure, but #318's own diagnostic fix comment self-reports `claude-opus-5[1m]`; #319 is a hand edit, no worker; #323's worker states `claude-sonnet-5`, 200K, explicitly "not 1M" | #316, #317, #318 (fix), #320, #321, #322, #323 |
| writer line | unmoved since checkpoint-06 | still unmoved — no PR this window mentions it | — |
| runtime line | unmoved since checkpoint-06 | still unmoved — no PR this window mentions it | — |

## 1. Branch DAG

Renderer line: **two unconverged chains off #314, reconverged once.** Chain
A runs directly off #314 and is probe-and-integration only (`own_render.py`
untouched by all three of its PRs). Chain B runs off #313 — the branch #314
already merged in checkpoint-23 — and is where the syllable break unit is
measured and then shipped; **its own reported numbers therefore never
include #312's shipped rule** until #323 merges it back in.

| PR | branch | base | slice |
|---|---|---|---|
| #317 | `claude/engine-e2-line-height-remainder` | `claude/engine-e2-converge-12` (#314) | `class_b_probe.py --line-height` / `--valign`: the 19 `text_line_height` paragraphs trace to one dropped `hp:lineBreak` control (`moel-2025` ¶73); the 15 `cell_valign` paragraphs are an exact re-solve of a box moved elsewhere (14 by `table_row_heights`, 1 by a re-break inside the cell); `own_render.py` untouched; nothing shipped |
| #319 | `claude/engine-e2-seating-setter` | `claude/engine-e2-line-height-remainder` (#317) | one property setter, `SeatingRenderer.table_index`, fixing the collision #318 found; orchestrator's own hand edit, no worker |
| #321 | `claude/engine-e2-wrap-36` | `claude/engine-e2-seating-setter` (#319) | `kstartup` table 36's `vertOffset`: three public sources agree it is unsigned; the export's own placement agrees with reading the wrap as 0, not as a signed −213; nothing shipped, no rule met the spec's ship condition |
| #316 | `claude/engine-e2-syllable-13` | `claude/engine-e2-cell-rebreak` (#313) | `syllable_break_probe.py --candidates --regressions`: the public format document's one-bit Korean break switch, the cache's 70/204 mid-어절 `KEEP_WORD` cuts, and the 13 `syllable`-candidate regressions split into 11 stand-in-face widths and 2 right-edge-budget admissions; nothing shipped |
| #320 | `claude/engine-e2-standin-11` | `claude/engine-e2-syllable-13` (#316) | `hft_width_table.py --build` + `own_render.py` advance path: 휴먼명조 is the one substituted face behind all 11, measured from the reference PDFs' glyph origins; ships a `standin_faces` section and its resolver-gated lookup; the breaker is not switched |
| #322 | `claude/engine-e2-syllable-switch` | `claude/engine-e2-standin-11` (#320) | `own_render.break_opportunities`: ships the syllable break unit for CJK cells, reproducing the probe's `syllable` candidate by construction; one declared regression (`kstartup` ¶719), pinned |
| #323 | `claude/engine-e2-converge-13` | `claude/engine-e2-converge-12` (#314), merges #321 (carries #317, #319) and #322 (carries #316, #320) | converges both chains onto #314's tip; no conflicts in either merge; numbers differ from #322's own expectation on the computed channel and on `layout_divergence`'s agree/B split, explained in §7 |

Desktop line: one re-merge this window, plus one integration fix on the
renderer line prompted by it, plus one more desktop hop already in flight.

| PR | branch | base | note |
|---|---|---|---|
| #318 | `claude/desktop-on-renderer-314` | `claude/desktop-on-renderer-308` (#310), tip #314 | re-merge onto renderer tip #314, bringing in #311 (row-height remainder probe), #313 (cell re-break decomposition), #312 (`_inkless_stays_at_page_foot`, shipped); clean `ort` auto-merge, no manual conflict markers; two errors found afterward and fixed by cherry-picking #319; a further paragraph-join regression found and fixed on this branch (commit b451cb6, `layout_divergence.py` only) |

**A desktop re-merge onto #323 is in flight as this document is written.**
It has no PR number and none is assigned here.

**An `hp:lineBreak` breaking slice, based on #322, is also in flight** —
#322's own comment names it directly: "Next on this path: honour
`hp:lineBreak` (#317's one carrier)." It has no PR number and none is
assigned here.

Docs line: no new docs PR this window besides this checkpoint document
itself.

Writer line, unchanged from checkpoint-23 — still #224 → #235 → #238 →
#239; no PR this window mentions it.

Runtime line, unmoved since checkpoint-06 (last PR #204); no PR this window
mentions it.

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` … `-23` (each off its own window's renderer
state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #316 — the public document makes the Korean break unit one bit, and the 13 regressions split into 11 widths and 2 budgets

**Probe only; `own_render.py` byte-identical to `claude/engine-e2-cell-rebreak`.**
Depends on #313. Worker, as self-reported: `claude-opus-5[1m]`, 1M — the
project rule forbids 1M context and the launch asked for plain Opus;
recorded, not hidden. Orchestrator: Fable.

**What the public document says:** 『한/글 문서 파일 구조 5.0』 revision
1.3:20181108, §4.2.10, bit 7 (`HWPTAG_PARA_SHAPE`): `줄 나눔 기준 한글 단위`
is one bit — 0 = 어절, 1 = 글자, "no third state and no exception clause."
`neolord0/hwpxlib` carries the same enumeration (`KEEP_WORD` / `BREAK_WORD`).
No other attribute in the ten forms' declarations (`hh:breakSetting`,
`hp:paraPr`, `hh:charPr`'s per-script children, `hh:autoSpacing`) carries a
per-script exception; `HWPTAG_FORBIDDEN_CHAR` is named but its contents are
not published.

**The cut-class matrix:** 2995 paragraphs carry `hp:lineseg`, 160 multi-line,
218 cached line ends. `KEEP_WORD` 2226 declared / `BREAK_WORD` 769. Of 204
`KEEP_WORD` cuts, **70 (34%)** fall inside a 어절 — all sitting between
**0.033 and 0.393** of their own column, refuting an emergency-break reading.
Zero of 218 cuts fall inside a Latin word or a digit group under either
declared value, though the cache does cut at a Hangul/digit script change.

**The thirteen, grouped:** all JUSTIFY, `KEEP_WORD`, `condense=0`,
hanging-indented; the cache cuts at a space, our breaker takes one more
syllable. Only seven distinct sentences behind the thirteen paragraphs.
Eleven overshoot the box by **135.4 to 911.4 HWPUNIT** and all carry a
stand-in face; two (`kstartup` ¶719 +58.8, `nrf` ¶32 +83.7) are admitted
only by the 96 HWPUNIT budget, and `kstartup` ¶719's every face is the
declared, installed one.

**Candidate narrowings, none shipped:** `syllable` 89/113 installed, 10/47
other, 13 regressions, 43 gains; `cjk-cjk`, `cjk-cjk+alnum`, `cjk-cjk+digit`
all cost the same 13. Budget sweep under `syllable`: 0 → 90/113, 10/47, 12
regressions (recovers `kstartup` ¶719 at no cost); −150 → 77/113, 13/47, 11
regressions; further negative values collapse the score below shipped.
**No setting reaches zero regressions, so nothing ships.**

**Gates:** `py_compile_sweep` 120 files, 0 failures; `engine/tests` 1694
passed/135 skipped (317.62s); `tests` 497 passed/3 skipped (498.84s);
`privacy_scan` HARD=0 WARN=54 TOTAL=54. New unit tests:
`test_syllable_break_probe.py`, 14 passed. **Full gate, tip `5c1e49d`**
(comment): `pipeline/tests` three pieces 581/5/0 + 397/3/0 + 459/0/0
(2m43s+4m37s+4m06s), 0 failed overall. Orchestrator's own reading (stated as
left open, not taken): the `syllable` reading looks like the cache's own
behaviour and the 13 losses are attributed to width on stand-in faces (11)
and the budget (2), not the break rule — the breaker is not switched on
that reading here.

### #317 — `text_line_height`'s 19 are one dropped `hp:lineBreak`, and `cell_valign` is exact

**Probe only; `own_render.py` untouched.** Depends on #314. Worker, as
self-reported: `claude-opus-5[1m]`, 1M — recorded as on #311, #312, #313.
Orchestrator: Fable.

**`text_line_height`:** our height rule is exact on 2376/2376 cached lines
compared on the cache's own spans — no height rule can improve on that.
All 19 class-B paragraphs are `span:control_break`, telescoping to one
carrier, `moel-2025` ¶73: an `hp:lineBreak` control takes a `textpos` cell
the cache breaks after, but our flow pass never sees the control and the
following spaces hang onto line 1 instead, changing which run measures line
2 (13 pt vs 11 pt, `PERCENT` 103 leading exact on both: 40 on 1300, 32 on
1100). `snapToGrid`, mixed run sizes, and ratio/relSz/HFT metering are each
refuted as candidates. 22 corpus paragraphs carry `hp:lineBreak`; only ¶73
propagates into class B.

**`cell_valign`:** the cell-alignment equation (`offset = 0` / `(avail_h -
block)//2` / `avail_h - block`) reproduces the drawn `d_block_offset` on
**15/15** rows here and **1499/1499** non-`TOP` cells corpus-wide — no
counter-example. 14 of the 15 are `table_row_heights` seen from inside the
cell (row grew, CENTER re-centred correctly); the 1 (`moel-2013` ¶220/¶222)
is a cell whose content re-broke 4→5 lines elsewhere, lifting the block
extent. **Nothing ships for either root** — the seam each would touch is
already exact; the fixes belong to `table_row_heights`'s own branch and to
honouring `hp:lineBreak`.

**Before/after (unchanged, untouched renderer):** cache 0.861944/0.393719/
0.736589, computed 0.850452/0.373788/0.706026, 53 pages, 10/10, identical to
#314. `layout_divergence --corpus` 1830/94/102/28, unchanged; `class_b_probe`
roots unchanged (`table_row_heights` 63, `text_line_height` 19, `cell_valign`
15, `page_top_unattributed` 3, `text_rebreak:width` 2). `lineseg_vs_pdf`
411/411, 8566/8566.

**Gates:** `py_compile_sweep` 119 files, 0 failures; `engine/tests` 1691
passed/135 skipped (281.74s); `tests` 492 passed/7 skipped (417.71s);
`privacy_scan` HARD=248 WARN=89 (all under untracked `desktop/`, tracked
HARD=0). **Full gate, tip `dee9a2b`** (comment): `pipeline/tests` three
pieces 579/7/0 + 397/3/0 + 459/0/0 (1m50s+3m47s+4m46s), 0 failed overall.
Comment: the `hp:lineBreak` carrier "starts as the next breaker slice once
the stand-in width slice on #316 frees that path."

### #320 — the eleven are one substituted face, 휴먼명조, and the reference PDFs draw it

**Ships `standin_faces` data; advance path only, breaker not switched.**
Depends on #316. Worker, as self-reported: `claude-opus-5[1m]`, 1M —
recorded as on #311, #312, #313, #316. Orchestrator: Fable.

**Answer:** 휴먼명조 (declared `TTF`, not installed on this machine, answered
by bundled NanumMyeongjo) is the **only** face in the whole corpus this
resolver answers from the bundled family map, and it accounts for all
eleven. Measured against the reference PDFs' own glyph origins (pen distance
between consecutive glyphs on a text-showing run): 휴먼명조 advances a Hangul
syllable at **0.996 em**, the bundled stand-in at **0.950 em** — 60 HWPUNIT
per character at 13 pt. Per-line table: our span was **2286 to 3410 HWPUNIT
narrower** than the ink Hancom actually laid down; corrected, the same span
is **932 to 1636 HWPUNIT over** the box — far outside the 96 budget, so the
break falls where the cache put it, on all eleven. 145 code points over 2330
observations converge to one number (median 0.99638, 4 distinct values, a
spread the PDF's own coordinate grid explains). 휴먼명조 reaches the PDF as a
`Type0`/`CIDFontType2` subset-embedded TrueType, not the anonymous `Type3`
the HFT table measures — a third font-handling category, not an HFT gap.

**Shipped:** a `standin_faces` section in
`engine/references/fonts/hft-widths.measured.json` and a resolver-gated
lookup (`_standin_declared_face` / `_standin_advance_hwp`) consulted after
the HFT table; answers `None` when a face resolves installed, so a machine
with 휴먼명조 is untouched. Existing sections byte-identical (2599
insertions, 0 deletions). **The breaker is NOT switched** — reported so the
two changes can be reviewed apart.

**Break score, both breakers:** shipped unchanged 48/113, 21/47, 0 change.
`syllable`, with the table: **89/113 installed** (unmoved from #316's own
number), **32/47 other** (up from 10/47), **1 regression** (`kstartup`
¶719, down from 13), 53 gains (up from 43). `jumin` ¶139 unmoved by the
table in either breaker (it is `syllable`'s own gain).

**Raster, both policies, 144 dpi:** cache 0.861944/0.393719/0.736589 →
**0.868907/0.418264/0.743523**; computed 0.848325/0.364894/0.692148 →
**0.853950/0.383682/0.698067**. 53 pages, 10/10 exact on both, before and
after; six forms with no 휴먼명조 unchanged to six decimals.
`layout_divergence --corpus`: **1801/94/131/28 → 1799/94/133/29** — `nrf`
¶31/¶32 go agree→B (landing under `text_rebreak:width`, which is why that
root moves 2→4), `kstartup` ¶740 goes A→C (same line, same dy, only the page
differs). `lineseg_vs_pdf` 411/411, 8566/8566, unchanged (control).

**Cost: one paragraph.** `nrf` ¶30 goes from 2 lines to 3 under the widened
휴먼명조 — but ¶30 was already a break-sequence disagreement (cache `[0,50]`,
ours `[0,45]`) before this change, so no paragraph that agreed on breaks
stopped agreeing. `paragraphs_line_count_exact` 2132→2131,
`break_sequence_exact` 2056→2056 (unmoved).

**Gates:** `py_compile_sweep` 120 files, 0 failures; `engine/tests` 1700
passed/135 skipped; `tests` 497 passed/3 skipped; `privacy_scan` HARD=0
WARN=54. **Full gate, tip `05c9dd2`** (comment): `pipeline/tests` three
pieces 581/5/0 + 397/3/0 + 459 passed/0 skipped, 0 failed (2m16s+4m25s+4m20s).
Comment: "the switch starts as the next slice on top of this one, with
`kstartup` paragraph 719 declared as its one known cost."

### #321 — `kstartup` table 36's `vertOffset` is unsigned, and the export ignores the wrap too

**Notes only; nothing ships.** One file changes,
`engine/references/own-render-notes.md`. Depends on #319. Worker, as
self-reported: `claude-opus-5[1m]`, 1M — recorded as on the other research
PRs this round. Orchestrator: Fable.

**What three public sources say:** the OWPML ParaList schema declares
`vertOffset`/`horzOffset` as `xs:nonNegativeInteger`; Hancom's own
`hancom-io/hwpx-owpml-model` (`pos.h`) types both as `UINT`; the HWP 5.0
binary format document (rev 1.3:20181108) uses the unsigned `HWPUNIT` type
for both offsets (표 69), not the signed `SHWPUNIT` or `INT32` it defines
elsewhere and marks with a 부호 (sign) check. None of the three says signed.

**Table 36 (anchor ¶701) against the reference PDF, page 20:** reading the
declared `vertOffset` (unsigned `4294967083`) as-is puts the box top
85,899,341.76 px off the PDF's top rule (204.98 px). Reading it as a signed
int32 (−213) puts the box top at 200.82 px, **4.16 px off**. **Reading it as
if it were 0 puts the box top at 205.08 px, 0.10 px off** — inside the
frame-conversion control's own agreement (horizontal: 122.80 vs 122.81 px,
0.01 px). Hancom's own export does not apply the signed reading either; it
places the table where `vertOffset = 0` would.

**Pages 5 and 7's unexplained heads:** re-measured against `layout_divergence`'s
first-drift-predecessor records — table 5 (anchor ¶127) and table 36
(anchor ¶701) are **neither** the predecessor of either page-5 or page-7
head; page 5's head follows table 6, page 7's follows table 9. Table 36
does appear as the predecessor of a different, page-21 `page_move` row.
`clip_tracks` was re-measured (not quoted) and fires under **both**
policies on `kstartup` tables 5 and 36, refuting "cache mode never computes
row heights."

**Nothing shipped** — the spec's own condition was to ship the signed
reading only if the schema said signed; it says unsigned. Pages 5 and 7 do
not move; `clip_tracks` still fires on tables 5 and 36. A candidate rule
("an out-of-range anchor offset draws at the frame origin") is named but
explicitly **not** scored — one witness, one table, a corpus-fitted
threshold never scored as a drawing rule.

**Before/after, every probe, 144 dpi (documentation only, every number
re-run and unchanged):** `render_scoreboard` cache 0.861944/0.393719/
0.736589, computed 0.850452/0.373788/0.706026, 53 pages, 10/10 both;
`layout_divergence` 1830/94/102/28; `class_b_probe` root histogram
63/19/15/3/2; `lineseg_vs_pdf` 411/411, 8566/8566; `page_fit_probe
--scan-all` off-sheet lines 44 of 3209; `render_check render-check-01`
identical at both dpi. **This branch does not include #320's table**, so
none of the above is comparable with #320's own numbers.

**Gates:** `py_compile_sweep` 119 files, 0 failures; `engine/tests` 1692
passed/135 skipped (319.32s); `tests` two pieces 382/4 + 110/3 = 492
passed/7 skipped; `privacy_scan` tracked HARD 0, HARD=248 WARN=89 total, all
inside untracked `desktop/`. **Full gate, tip `be826d9`** (comment):
`pipeline/tests` three pieces 579/7/0 + 397/3/0, and **the third piece's
pass/skip count is not given in the comment text** (it reads "and the third
piece as stated below, 0 failed" with no number following) — 0 failed
overall is asserted but the third piece's own figure is not sourced here.
Comment's carried finding: "the export seats kstartup table 36 as if its
out-of-range offset were 0 (one witness), which is a candidate rule for the
anchored-object seam once a second witness exists."

### #322 — the Korean break unit ships as the syllable, and `kstartup` 719 is what it costs

**Ships the syllable break unit.** Depends on #320. Worker, as
self-reported: `claude-opus-5[1m]`, 1M. Orchestrator: Fable.

**The change:** one branch of `own_render.break_opportunities` — where
either side of a candidate break is a CJK cell, the break is allowed
outright, regardless of the paragraph's declared `breakNonLatinWord`. This
reproduces `syllable_break_probe.py`'s own `syllable` candidate **by
construction**: the probe's `narrowed(NARROWINGS["syllable"])` predicate is
unconditionally true inside that branch, so the shipped number and the
probed number cannot drift. `breakNonLatinWord` moves `PARAPR_HONORED` →
`PARAPR_NOT_HONORED`; a new `KOREAN_BREAK_UNIT` and
`line_layout.declared_break_setting` are emitted into every sidecar so a
reader can see the override without opening the source file.

**Break score:** before (shipped, pre-switch) 48/113 installed, 21/47
other; **after, shipped == `syllable`: 89/113 installed, 32/47 other, 1
regression, 53 gains** — matching #320's own `syllable`-with-table numbers
exactly, now for real rather than as a candidate.

**Raster, both policies, 144 dpi (measured fresh on this branch, not carried
from #320):** cache 0.868907/0.418264/0.743523 → **0.868910/0.418275/
0.743520** — **not byte-identical**, against the spec's own expectation:
`kstartup` moves 0.908852/0.510764/0.780876 → 0.908881/0.510869/**0.780847**,
because paragraphs with no usable cached `hp:lineseg` still run through the
breaker under an explicit `cache` policy, and `kstartup` is the one form
with enough of them to register. Computed 0.853950/0.383681/0.698067 →
**0.862849/0.400787/0.715097**. 53 pages, 10/10 both, before and after. Two
forms dip on one channel while rising on others: `kstartup` cache line-IoU
−0.000029; `moel-2025` computed line-IoU 0.600223→0.597219 (−0.003004) while
its ssim rises 0.815867→0.825113 and ssim_inked 0.297475→0.331888. Every
other form and channel rises or is unchanged.

**`layout_divergence --corpus`: 1799/94/133/29 → 1903/42/77/31, A&B (1→0).**
Root list (own body, still chain-B-local — pre-#312): `table_row_heights`
63→**12**, `empty_paragraph` 29→29 (unmoved — this chain has never merged
#312), `text_line_height` 19→**20**, `cell_valign` 15→**13**,
`text_rebreak:width` 4→**0**, `page_top_unattributed` 3→3. Two of #311's
three carrier cells close exactly (`moel-2013` ¶261, `saeopja` ¶189, both
now 2/2 and 3/3 lines); `saeopja` ¶393 stays over-broken, as #316 said it
would — a genuine +238.0 HWPUNIT width excess, not a break-opportunity
question. `lineseg_agreement`: break positions matched 92→**160** (nearly
doubling — "the largest single move any slice has made on it"), line count
exact 2131→2137, break-sequence exact 2056→2108, seven of ten forms rise,
none falls. `jumin` ¶139 now exact; ¶160 stays outside `break_scoreboard`'s
scorable set. `lineseg_vs_pdf` 411/411, 8566/8566, unchanged (control).

**The one regression, declared and pinned: `kstartup` ¶719.** JUSTIFY,
`condense=0`, hanging-indented, every face declared and installed (맑은 고딕).
Our arithmetic already puts the deciding span **+58.8 HWPUNIT over** its
44,744-HWPUNIT box, admitted only by the 96 budget. **Not tuned away** —
#316's own finding (budget 0 recovers it, the other twelve of the original
thirteen need ≥−911) is quoted as the reason the budget stays at 96.
Pinned in `test_the_syllable_unit_costs_kstartup_719_and_that_is_declared`.

**Gates:** `py_compile_sweep` 120 files, 0 failures; `engine/tests` 1705
passed/135 skipped; `tests` two pieces 386/1 + 111/2 = 497 passed/3 skipped;
`privacy_scan` HARD=0 WARN=59. **Full gate, tip `2199bf9`** (comment):
`pipeline/tests` three pieces 581/5/0 + 397/3/0, **the third piece's number
again not given** ("as stated below, 0 failed" with no figure following),
0 failed overall asserted. Comment: "Next on this path: honour
`hp:lineBreak` (#317's one carrier)."

### #319 — a base renderer may assign `SeatingRenderer.table_index`

**Integration fix, one property setter, no rendering change.** Depends on
#317. Orchestrator: Fable, edit by hand — **no worker, standard context**.

Reproduces #318's finding: `AttributeError: property 'table_index' of
'SeatingRenderer' object has no setter`, on the #318 merged tree (4
passed/2 errors), passing on #317's own tree (6 passed) — so not
pre-existing on either base individually. `@table_index.setter` stores the
handed-over value as the property's cache; on the renderer line nothing
assigns it, so behaviour there is unchanged. The same commit is cherry-picked
onto #318.

**Gates (comment, tip `b67c3ae`):** `engine/tests` 1692 passed/135 skipped/0
failed (8m13s); `tests` 492 passed/7 skipped/0 failed (12m40s, auto-backgrounded
past the 10-minute foreground limit under two concurrent worker pytests,
completed exit 0); `pipeline/tests` three pieces, 579/7 and 397/3 given —
**the third piece's number is not stated** ("and the third piece below"
with nothing following in the comment). No renderer scoreboard re-run
(`own_render.py` untouched by this PR).

### #318 — the desktop line re-merged onto renderer tip #314, then two errors and a paragraph-join regression fixed

**One merge, clean; two follow-up fixes.** Base `claude/desktop-on-renderer-308`
(#310's branch), tip #314. Merge: Sonnet, no context figure stated;
orchestrator: Fable. **The diagnostic fix comment's own worker, separately:
`claude-opus-5[1m]`, 1M — "the model was not selectable from inside the
run."**

**The merge itself:** brings in #311 (row-height remainder probe, nothing
shipped), #313 (cell re-break decomposition, nothing shipped), #312
(`_inkless_stays_at_page_foot`, shipped). `git merge --no-ff` auto-merged
cleanly via `ort` (`own_render.py` and its test file, no manual conflict
markers). `desktop/sidecar/build.ps1` untouched. Initial gates: `py_compile_sweep`
145 files, 0 failures; `engine/tests` **1688 passed, 135 skipped, 2 errors**;
`tests` two pieces 531/4 + 568/3 = 1099 passed/7 skipped; `pipeline/tests`
two halves 579/7/17 + 858/3/46; `privacy_scan` HARD=6471 WARN=441 TOTAL=6912,
all under six gitignored, zero-tracked desktop build paths. GUI smoke NOT
RUN (5.5 GB free).

**Fix 1, the 2 errors:** the worker's own attribution (pre-existing) is
corrected by the orchestrator's comment — reproduced as **not** pre-existing
on either base individually. Cause: the desktop's `OwnRenderer.__init__`
assigns `self.table_index` (desktop commit 30778e4) while
`class_b_probe.SeatingRenderer` declares it a read-only property; only
#311's new tests construct a `SeatingRenderer`, so #310 never hit it. Fixed
by cherry-picking #319's setter (one conflict, resolved by taking only the
rename line, since #319 sits on #317 whose new attributes this tree lacked).
Result: `test_row_height_probe.py` + `test_class_b_probe.py` 35 passed/**1
failed** — the errors are gone, but a real cross-line finding surfaces.

**Fix 2, the paragraph-join regression:** the remaining failure
(`table_row_heights_paragraphs >= 1`) traced to #262's own
`layout_divergence.py` edit ("the tool's paragraph index wins the address
slot"), which replaced a `record.setdefault("address", address)` with an
unconditional assignment — losing the `setdefault`'s second, undocumented
job of preventing an outer `_draw_line` call from re-addressing lines a
nested table cell's own call had already claimed. Instrumented on `jumin`:
the paragraph index was complete (141/141 before and after render) but
render collapsed 165/167 line boxes onto **3 distinct addresses** — the
three top-level paragraphs holding the form's tables. **Fix:** a new
`_addressed_boxes` set on `TracingRenderer`, tracking `id()` of every
line-box record already addressed; `_draw_line` skips a record already
claimed. Restores the `setdefault`'s old meaning while keeping the flat
index's win and the OWPML dict's move to `owpml_address`. Same jumin render:
3 distinct addresses → 129. Commit `b451cb6`, **one file, +17 lines,
`layout_divergence.py` only** — `own_render.py` untouched.

**Before/after, `layout_divergence --corpus` paragraphs (agree/A/B/C):**
every form the brief's spot-checks named (`admrul`, `gianmun-1ho`,
`jeongbo`, `kstartup`) now equals the renderer line exactly (e.g. `kstartup`
135/17/3/6 → 353/18/3/28, matching #314's own renderer-line number). Total
479/57/26/6 → **1830/94/102/28**, matching the renderer line's own #314
number exactly. Three forms (`jumin`, `moel-2013`, `saeopja`) move on LINE
counts too — attributed to the same bug (cross-cell ordinal pairing once
every cell line collapsed into one table-level bucket), stated as not
independently cross-checkable against the brief since it only quoted the
four forms above.

**Final gates:** `py_compile_sweep` 145 files, 0 failures; `engine/tests`
1691 passed/135 skipped; `test_row_height_probe.py` + `test_class_b_probe.py`
**36 passed**; `tests` four pieces 364/3 + 167/1 + 305/0 + 263/3 = 1099
passed/7 skipped; `pipeline/tests` three pieces 579/7/17 + 399/3/33 +
459/0/13 = 1437 passed/10 skipped/63 subtests; `privacy_scan` HARD=6471
WARN=441 TOTAL=6912, all under gitignored `desktop/` paths (804 files),
**tracked HARD=0**. Address-behaviour tests (`test_runtime_geometry.py`,
`test_runtime_plan.py`, `test_runtime_render.py`, `test_own_render.py`):
510 passed before and after, identical (the desktop's address feature lives
in `own_render.py`, untouched by this fix). `render_scoreboard --corpus
--dpi 144`: cache 0.861944/0.393719/0.736589 and computed 0.850452/0.373788/
0.706026, both matching the renderer line's expectation exactly, unchanged
by the fix. GUI smoke: NOT RUN (6.0 GB free).

**Stated, not done:** `layout_policy`/`layout_policy_reason` still not
surfaced in the desktop UI (owed since #248); the sidecar data-list handoff
from #298 still stands for the product line.

## 3. The development-validation document, this window

**Not reopened.** Of the eight PRs this window, only #316 names the
development-validation document at all, and only to state that it was
**not** used: "Only the public corpus was read. The private
development-validation document is not named, quoted or measured anywhere
in this slice." None of #317, #318, #319, #320, #321, #322 or #323 names or
quotes it, touches it, or reports a fresh measurement against it. It stays
on checkpoint-20's last reading (unchanged since checkpoint-21: cache
0.6964/0.1834/0.5667, computed 0.6108/0.0982/0.2294, cited from #281's
comment) with the page-bottom fit rule still the standing gap and no public
witness.

## 4. Regressions (with the PR's or commit's own explanation)

**One shipped, declared regression, pinned in its own test.** #322's
syllable break unit costs `kstartup` ¶719 — the only installed-face
regression among the original 13, admitted only by the 96-HWPUNIT budget.
Named and explained in §2 above; not tuned away on the stated reasoning
that one paragraph is not a measurement of the budget.

**Two forms dip on one raster channel each, both explained as measured, not
tuned.** #322: `kstartup` cache-policy text-line IoU −0.000029 (paragraphs
lacking a usable cached `hp:lineseg` still run through the breaker under an
explicit `cache` policy); `moel-2025` computed-policy text-line IoU
−0.003004 while its ssim and ssim_inked both rise.

**One cost from the stand-in table, explained as pre-existing disagreement,
not a new fault.** #320: `nrf` ¶30 goes from 2 lines to 3 under the widened
휴먼명조 metric, but was already a break-sequence disagreement before the
change (cache `[0,50]`, ours `[0,45]`), so no paragraph that agreed on
breaks stopped agreeing.

**Two errors, one desktop-line paragraph-join regression, both found and
fixed within this window, on the desktop line (#318).** The `table_index`
setter collision (fixed by cherry-picking #319) and the cross-line
paragraph-join collapse traced to #262's `layout_divergence.py` edit (fixed
by commit b451cb6, restoring the renderer line's own paragraph counts
exactly). Both are attributed to a genuine desktop/renderer cross-line
interaction, not to anything shipped this window on the renderer side.

**One large privacy-scan number on every desktop-adjacent tree, repeated
from checkpoint-22 and -23, explained as environmental.** #318 reports
HARD=6471 (WARN=441, TOTAL=6912) both before and after its fixes; #317,
#320, #321 each report HARD=248 or HARD=0 depending on whether the untracked
`desktop/` directory was present in that worktree; #323 reports HARD=248
WARN=94 TOTAL=342. Every PR that reports a nonzero HARD total traces every
hit to untracked, `.gitignore`-matched paths under `desktop/`, stating
"tracked HARD = 0" or equivalent.

**One process deviation, not a code regression, restated and extended from
checkpoint-23:** #316, #317, #320, #321, #322, and the diagnostic fix on
#318 each self-report running on a banned `claude-opus-5[1m]` (1M) context.
See §9.

## 5. Unsupported / declared elements still open

Carried from checkpoint-23, with this window's closures, ships, and new
items:

- **Shipped this window:** the syllable break unit for CJK cells (#322),
  with `kstartup` ¶719 as its one declared, pinned cost; the `standin_faces`
  section of the measured width table for 휴먼명조 (#320), resolver-gated,
  breaker not switched by that PR alone.
- **Measured, not closed:** the `text_line_height` 19 (#317) — one
  `hp:lineBreak` carrier, the fix is honouring the control as a hard break,
  named as the very next slice on #322's own chain; `cell_valign` 15 (#317)
  — exact re-solve, both causes owned by other roots (`table_row_heights`,
  the extra-line re-break), nothing to fix here; `kstartup` table 36's
  anchored-object seat (#321) — one witness that the export seats an
  out-of-range offset as 0, not yet a rule (needs a second witness).
- **Closed this window, chain-B-local (i.e. not yet reflected in the
  merged tree's own class_b_probe root histogram, which #323 does not
  repost):** `table_row_heights` moves 63 → 12 on #322's own numbers
  (two of #311's three carrier cells now close exactly; `saeopja` ¶393
  stays open, a genuine width excess).
- **New, unexplained:** `saeopja` ¶393's own width excess (+238.0 HWPUNIT
  on a 2894-HWPUNIT column) — named again by #322 as staying open, same as
  checkpoint-23.
- **New, resolved as a non-finding:** `breakNonLatinWord="KEEP_WORD"`'s
  meaning against the cache's mid-word cuts, open at checkpoint-23 — #316's
  public-document reading (one bit, no exception clause) and #322's shipped
  rule together answer it: the cache does not honour `KEEP_WORD` as written,
  and the renderer now matches that behaviour rather than the declaration.
- **New, undiagnosed in detail but explained in aggregate:** the computed
  raster and `layout_divergence` discrepancy between #322's own body and
  #323's merged-tree measurement (§7) — the orchestrator's own reading, not
  a PR's, and not independently re-verified beyond the arithmetic identity
  (agree+B pool, 1980, identical in both).
- **New process deviation, recorded not hidden:** #316, #317, #320, #321,
  #322 and the #318 diagnostic-fix comment each self-report
  `claude-opus-5[1m]` (1M context) against the project rule and the
  plain-Opus launch request; #319's edit and #323's convergence both ran on
  standard context (no worker at all, and `claude-sonnet-5` 200K
  respectively).
- **New, unconverged as of writing:** a desktop re-merge onto #323, and an
  `hp:lineBreak` breaking slice on #322, are both in flight; neither has a
  PR number yet.
- **Re-derived earlier, still not closed:** #301's 96-HWPUNIT right-edge
  tolerance sitting outside its own [18.5, 26.3) admissible window — #316's
  budget-0 finding on `kstartup` ¶719, now shipped as #322's one declared
  regression, is a further instance of the same problem, not a resolution;
  the reviewer's call remains open.
- **Unchanged from checkpoint-23, still fully open, not touched this
  window:** the installed-face punctuation residual (+253.3 HWPUNIT / 487
  advances, no mechanism); the page-fit public witness's Hancom round-trip,
  blocked on COM ownership; the gridmax tail's narrower open question
  (73/75 vs 2/75, #291); the table-split rule's single witness (`kstartup`
  tbl9, #278) and `repeatHeader`'s complete lack of a positive corpus case;
  the move-whole anchored-table arm's generalization beyond `CELL` +
  anchored, untested; the overflow clamp on gridmax, untested; the
  development-validation document's 5 line-count and 40 character-split
  discrepancies and their font-resolution hypothesis (#258/#260), not
  reopened this window (§3); computed layout's own +1800 page-top drift
  against that document's PDF (#257), unaddressed; the `LayoutSnapshot`
  contract and `x1` glossary (#253), no response recorded; `layout_policy`/
  `layout_policy_reason` still not surfaced in the desktop UI; the
  acceptance harness's lexical-reader fix for header/footer text (#235's
  queued item); the desktop GUI smoke, still never run, free disk read 6.0G
  at #318 (up from 4.0G at #310); the sidecar data-list line for
  `hft-widths.measured.json` in `desktop/sidecar/build.ps1`, still not
  edited, now also withholding #320's `standin_faces` section from a frozen
  build, ownership per #253; Codex-app-closed sessions moved; Cursor login.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #316 | engine/tests 1694/135 (317.62s); tests 497/3 (498.84s) | **`pipeline/tests` three pieces 581/5/0 + 397/3/0 + 459/0/0, tip `5c1e49d` (2m43s+4m37s+4m06s) — 0 failed overall** | `py_compile_sweep` 120/0; privacy HARD=0 WARN=54. **Worker self-reported `claude-opus-5[1m]`.** |
| #317 | engine/tests 1691/135 (281.74s); tests 492/7 (417.71s) | **`pipeline/tests` three pieces 579/7/0 + 397/3/0 + 459/0/0, tip `dee9a2b` (1m50s+3m47s+4m46s) — 0 failed overall** | `py_compile_sweep` 119/0; privacy HARD=248 (all untracked `desktop/`, tracked 0). **Worker self-reported `claude-opus-5[1m]`.** |
| #320 | engine/tests 1700/135; tests 497/3 | **`pipeline/tests` three pieces 581/5/0 + 397/3/0 + 459/0/0, tip `05c9dd2` (2m16s+4m25s+4m20s) — 0 failed overall** | `py_compile_sweep` 120/0; privacy HARD=0 WARN=54. **Worker self-reported `claude-opus-5[1m]`.** |
| #321 | engine/tests 1692/135 (319.32s); tests 382/4 + 110/3 = 492/7 | **`pipeline/tests` 579/7/0 + 397/3/0 posted; third piece's own pass/skip count NOT given in the comment text ("as stated below" with no figure) — 0 failed overall asserted regardless, tip `be826d9`** | `py_compile_sweep` 119/0; privacy tracked HARD=0, HARD=248 total (untracked `desktop/`). **Worker self-reported `claude-opus-5[1m]`.** |
| #322 | engine/tests 1705/135; tests 386/1 + 111/2 = 497/3 | **`pipeline/tests` 581/5/0 + 397/3/0 posted; third piece's own pass/skip count NOT given in the comment text — 0 failed overall asserted regardless, tip `2199bf9`** | `py_compile_sweep` 120/0; privacy HARD=0 WARN=59. **Worker self-reported `claude-opus-5[1m]`.** |
| #319 | engine/tests 1692/135 (8m13s); tests 492/7 (12m40s, backgrounded) | **`pipeline/tests` 579/7 + 397/3 posted; third piece's number NOT given in the comment ("the third piece below" with nothing following) — the PR states both cherry-picked commits are integration fixes with no rendering change, tip `b67c3ae`** | Hand edit by orchestrator; no worker, no context figure applicable. |
| #318 | engine/tests 1691/135 (final, post-fix; 1688/135/2 errors initial); tests four pieces 364/3+167/1+305/0+263/3 = 1099/7 | **`pipeline/tests` three pieces 579/7/17 + 399/3/33 + 459/0/13 = 1437/10/63 subtests, posted directly in the fix comment — 0 failed** | `py_compile_sweep` 145/0; privacy HARD=6471 (all untracked `desktop/` paths, tracked 0); GUI smoke NOT RUN (6.0G free, up from 5.5G at the initial merge). Merge worker: "Sonnet," no context figure; **the diagnostic-fix comment's own worker self-reported `claude-opus-5[1m]`.** |
| #323 | engine/tests 1717/135 (388.54s); tests 383/4 + 110/3 = 493/7 | **`pipeline/tests` three pieces 579/7/17 + 397/3/33 + 459/0/13 = 1435/10/63 subtests, posted directly in the PR body — 0 failed** | `py_compile_sweep` 120/0; privacy HARD=248 WARN=94 TOTAL=342 (all untracked `desktop/`, tracked 0). Worker: `claude-sonnet-5`, 200K, explicitly not 1M. |

Gates as reported: **#316, #317, #320 each 0 failed with a complete
three-piece `pipeline/tests` figure (follow-up comments); #321 and #322 and
#319 each assert 0 failed overall but the comment's own text omits the
third `pipeline/tests` piece's pass/skip figure, which is recorded here as
a genuine sourcing gap rather than filled in; #318's fix comment and #323's
PR body each post a complete gate table directly, both 0 failed.** Six
Opus-worker self-reports of `claude-opus-5[1m]` land this window (#316,
#317, #320, #321, #322, and #318's diagnostic-fix comment); #319 is a hand
edit with no worker; #323's worker explicitly reports standard 200K
context; #318's original re-merge worker's context is not stated ("Sonnet,"
no figure).

## 7. Integration conflicts expected when lines converge

**#323's two merges onto #314 both completed with zero conflicts.** #321
(carrying #317 and #319) merged first, touching
`engine/references/own-render-notes.md`, `engine/scripts/class_b_probe.py`,
`engine/scripts/track_probe.py`, `engine/tests/test_class_b_probe.py` — no
overlap with what #322 later changes. #322 (carrying #316 and #320) merged
second, auto-merging `engine/scripts/own_render.py` and
`engine/tests/test_own_render.py` cleanly against the #321 merge, no
conflict markers in either merge.

**The numbers still moved, and the reason is a rule, not a conflict — the
orchestrator's own reading, stated here rather than in either PR.** #322's
chain (`#313 → #316 → #320 → #322`) branches off #313, the branch #314
already merged in checkpoint-23 alongside #312 (`_inkless_stays_at_page_foot`).
**#322's chain never merges #312.** Every number #322 itself reports —
`layout_divergence` 1799/94/133/29 → 1903/42/77/31, computed raster
0.862849/0.400787/0.715097 — is measured on a tree that still lacks #312's
rule. #323's merge base is #314, which does carry #312, so the merged tree
is the first place #312's rule and #322's syllable unit ever coexist. That
is read here as the explanation for both discrepancies: the merged
`layout_divergence` (1932/42/48/31) differs from #322's own expected
(1903/42/77/31) exactly on the `agree`/`B` split and not on `A` (42, matches
exactly) or `C` (31, matches exactly), and `agree + B` is the same pool
(1980) in both — consistent with some of what #322's own (pre-#312) numbers
classed as class-B `empty_paragraph` paragraphs now agreeing once #312's
rule is present. The merged computed raster (0.864976/0.409681/0.728976)
is higher than #322's own expectation on all three channels
(roughly +0.002/+0.009/+0.014), which the same explanation covers: #312's
rule independently improves the computed channel wherever it applies, on
top of whatever #322's syllable unit already moved. **#323 does not repost
`class_b_probe.py --corpus`'s root histogram**, so no updated
`table_row_heights`/`text_line_height`/`cell_valign`/`text_rebreak:width`/
`page_top_unattributed`/`empty_paragraph` breakdown for the fully merged
tree is sourced here; this checkpoint states the arithmetic identity
(agree+B = 1980 both times) as what is actually verified, and the
`empty_paragraph`-recovery reading as the orchestrator's account of it, not
a number quoted from either PR.

**Desktop converged once more, cleanly, with two follow-up fixes, and one
more hop is in flight.** #318 (onto renderer tip #314, bringing in #311,
#312, #313) merged via `ort` with only auto-merges, no manual conflict
markers — then needed the cherry-picked `table_index` setter (#319) and its
own paragraph-join fix (commit b451cb6) before its gate went green. A
desktop re-merge onto #323 is in flight as this document is written — its
conflict profile is unmeasured here since it has not yet produced a PR.

**An `hp:lineBreak` breaking slice on #322 is also in flight**, unmeasured
here for the same reason — it has not yet produced a PR.

**Writer and runtime lines remain unconverged with anything**, unchanged
from checkpoint-23.

## 8. Next measurable research question

**In the order #322 and #317 name it: honour `hp:lineBreak` as a hard break
in the character stream and the line-fit pass** — #317's own carrier behind
all 19 `text_line_height` class-B paragraphs (`moel-2025` ¶73), named
directly by #322's own comment as "next on this path." Behind that, in the
order the PRs name them: `kstartup` ¶719 — the syllable unit's one declared
regression, unexplained beyond "the budget is the only term left on it";
`saeopja` ¶393's own +238.0 HWPUNIT width excess, still open after two of
#311's three carrier cells closed; the reviewer's decision on the
96-HWPUNIT budget, still outside its [18.5, 26.3) admissible window, now
with #316's budget-0 finding (recovering `kstartup` 719 alone, collapsing
the score for the other twelve) as one more measured instance of the same
problem; a second witness for #321's out-of-range-anchor-offset candidate
rule (`kstartup` table 36's export-seats-at-0 finding, one table so far);
the installed-face punctuation residual, still with no mechanism, untouched
this window; the page-fit Hancom round-trip, still blocked on COM
ownership.

## 9. Certification status

Every result in this checkpoint — #316 (syllable-13 diagnostic split,
measured, nothing shipped), #317 (line-height/valign remainder, measured,
nothing shipped), #320 (stand-in face table, shipped as data), #321
(table-36 offset, measured, nothing shipped), #322 (syllable break unit,
shipped, one declared regression), #319 (integration fix, no rendering
change), #318 (desktop re-merge plus two follow-up fixes, no renderer
change), #323 (renderer convergence of two chains, zero conflicts) —
remains **own-uncertified**. `render_cert.py` still cannot certify this
renderer absent a PDF text layer, unchanged since checkpoint-01. **Path C
NOT RUN on any PR this window** — #316, #317, #320, #321 and #322 each
state it explicitly in their own "Not proven" sections; nothing in #318,
#319 or #323 contradicts it. The corpus remains the training set, restated
by #316, #320 and #322 in their own words.

**Process deviation, stated plainly, without speculation about cause,
continued from checkpoint-23.** Six Opus self-reports of `claude-opus-5[1m]`
land this window: #316's body ("Worker: claude-opus-5[1m], 1M yes;
orchestrator: Fable") and comment ("recorded as on #311, #312, #313");
#317's body ("1M context window: YES … flagged, not hidden") and comment
("recorded as on #311, #312, #313, #316"); #320's body ("1M yes — the
project rule forbids a 1M context window and this slice was nevertheless
run on one") and comment ("recorded as on #311, #312, #313, #316, #317");
#321's body ("1M context: yes — the project rule forbids a 1M context and
this run was on one") and comment ("recorded as on the other research PRs
this round"); #322's body ("1M yes") and comment (same); and #318's own
diagnostic-fix comment, separately from its "Merge: Sonnet" body line: "Run
as claude-opus-5[1m]. Its context window is 1M, which the project's
CLAUDE.md rule ('1M 컨텍스트 금지') forbids — flagging it rather than
leaving it implicit. The model was not selectable from inside the run." By
contrast, #319's edit is "orchestrator: Fable, edit by hand (no worker)"
and #323's worker states plainly "Worker: claude-sonnet-5 (Claude Sonnet 5),
200K-token context window (not 1M)." No PR offers a cause for the six Opus
launches landing on 1M context this window, continuing the pattern from
checkpoint-23; none is speculated here.

**What moved, restated plainly:** this window took the two unconverged
research chains checkpoint-23 left off #314 and pushed both further before
reconverging them. Chain A (#317 → #319 → #321) measured `text_line_height`
to one dropped control and `cell_valign` to an exact re-solve, closing
neither but naming the fix for the first and clearing the second entirely;
along the way it fixed a cross-line property-setter collision the desktop
merge (#318) had exposed. Chain B (#316 → #320 → #322) took the 13
regressions checkpoint-23's `syllable` candidate cost, split them into 11
substituted-face widths and 2 budget admissions, shipped the width table as
data, and then shipped the syllable break unit itself with one declared
regression — the first behavioural change to the breaker in this
checkpoint's whole research history. #323 converged both chains onto #314
cleanly, but its own measured numbers differ from what #322's chain alone
predicted, because that chain never carried #312's rule until this merge —
recorded here as the orchestrator's explanation, verified only by the
arithmetic identity the merge itself exposes (agree+B unchanged at 1980).
The desktop line landed one re-merge (#318) that needed two follow-up fixes
before its gate matched the renderer line exactly, with a second re-merge
already in flight, unnumbered — the same pattern the last two checkpoints
recorded. Set against that measured progress, six workers this window
self-reported running outside the project's own model-context rule,
recorded here rather than smoothed over, extending checkpoint-23's finding
rather than resolving it.

**Owed, carried forward from checkpoint-23, plus this window's additions:**

- Land the desktop re-merge onto #323 that is in flight as this is written,
  once it exists as a numbered PR.
- Land the `hp:lineBreak` breaking slice on #322 that is in flight as this
  is written, once it exists as a numbered PR — named directly by #322's
  own comment as "next on this path."
- Diagnose `kstartup` ¶719, the syllable unit's one declared regression —
  the budget is the only term left on it, and it was not moved.
- Close `saeopja` ¶393's own +238.0 HWPUNIT width excess — the one of
  #311's three carrier cells the syllable unit does not reach, a width
  question rather than a break-opportunity one.
- Decide #301's error-budget framing given #307's admissible window
  [18.5, 26.3) — the reviewer call named open since checkpoint-21, now
  further evidenced (not resolved) by #316's budget-0 finding on the
  syllable unit's one shipped regression.
- Find a second witness for #321's out-of-range-anchor-offset candidate
  rule (`kstartup` table 36's export-seats-at-0 finding is one table so
  far) before scoring it as a drawing rule.
- Find a mechanism for the +253.3 installed-face punctuation residual
  (#307) — untouched this window.
- Ask (do not answer here) why six workers this window ran on a
  1M-context model the project rule forbids, when the launches asked for
  plain Opus — the same open question checkpoint-23 first recorded.
- Independently re-post `class_b_probe.py --corpus`'s root histogram on the
  fully merged (#323) tree — not sourced in this checkpoint because #323's
  own body does not include it.
- The sidecar data-list line for `hft-widths.measured.json` in
  `desktop/sidecar/build.ps1` — named by #298, restated still open by
  #305, #310, and again by #318, now also withholding #320's
  `standin_faces` section, owed on the product side per #253.
- The page-fit public witness via a Hancom round-trip (#256/#260/#295) —
  untouched this window; still blocked on the COM ownership agreement.
- The gridmax tail's narrower open question — which end of a short row
  absorbs a shortfall — a 2-point observation (73/75 vs 2/75, #291,
  unchanged this window).
- The table-split rule's single witness (`kstartup` tbl9, #278) and
  `repeatHeader`'s complete lack of a positive corpus case.
- The move-whole anchored-table arm's generalization beyond `CELL` +
  anchored — untested; the overflow clamp on gridmax — untested (#277).
- The development-validation document's font-resolution hypothesis for its
  5 line-count and 40 character-split discrepancies (#260), and computed
  layout's own +1800 page-top drift against its PDF (#257) — neither
  reopened this window (§3).
- The `LayoutSnapshot` proposal (#253) — no response recorded this window;
  no level-C run exists anywhere (Path C NOT RUN on every PR this window).
- `layout_policy`/`layout_policy_reason` surfaced in the desktop UI — still
  not a branch or PR.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- The desktop's build-from-merged-source GUI smoke evidence — still does
  not exist; free disk read 4.0G at #310, 6.0G at #318 (post-fix), still
  judged marginal by the pattern of prior checkpoints.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.

## 10. Coordinator interaction this window

**Unchanged since checkpoint-22.** No new coordinator status request
arrived this window — a search of #316 through #323's bodies and comments
for coordinator language, REG-/STATUS- request IDs, or #274 turns up
nothing. REG-001 (2026-09-05 23:47 KST) and STATUS-001 (2026-09-06 00:51
KST), both already recorded in checkpoints 18–23, remain the only
coordinator requests on file; both were answered as comments on #274,
which stayed the fallback handoff channel throughout. None of #316–#323
records a new request. Recorded here again so that #274's role as the
standing handoff channel carries forward into this checkpoint unchanged.
