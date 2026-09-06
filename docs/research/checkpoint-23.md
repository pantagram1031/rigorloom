# Checkpoint 23 — the empty-paragraph remainder turns out to be a page foot and ships, the row-height remainder narrows to a line-breaker question that does not, and three research workers ran on a banned 1M context

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-22` (this
branch, `claude/docs-checkpoint-23`, is cut from `origin/claude/docs-checkpoint-22`
and stays unmerged). All five PRs covered this window are **OPEN/DRAFT** —
nothing in this window has merged to `main`. Covers research **#311**
(`claude/engine-e2-row-height-remainder`, on #308: the 63 `table_row_heights`
class-B paragraphs are three over-broken cells; nothing shipped; two side
findings — `clip_tracks` fires under the cache policy on `kstartup` tables 5
and 36, and `kstartup` table 36's origin seats at an unsigned-wrap value),
**#312** (`claude/engine-e2-empty-remainder`, on #308: the 29 `empty_paragraph`
class-B paragraphs are a page foot at `nrf`, not a height fault;
`_inkless_stays_at_page_foot` ships; computed IoU 0.692148 → 0.706026, classes
1801/94/131/28 → 1830/94/102/28), **#313** (`claude/engine-e2-cell-rebreak`,
on #311: two of the three cells are cut mid-word by the cache under
`breakNonLatinWord="KEEP_WORD"`, the third is a genuine width excess; a
`syllable` breaking candidate moves installed agreement 48 → 89 but costs 21
→ 10 on `other` with 13 regressions; nothing shipped); convergence **#314**
(`claude/engine-e2-converge-12`, on #308, merges #313 — which contains #311 —
and #312; one notes-only conflict; all numbers equal #312's expectations);
desktop **#310** (`claude/desktop-on-renderer-308`, on #305's branch, tip
#308: re-merges #304, #306, #307 onto the desktop line). **A desktop
re-merge onto #314 and a syllable-13 research slice (on #313) are in flight
as this document is written; both are unnumbered and neither is counted
here.** Writer line (#224 → #235 → #238 → #239) and runtime line (#204) did
not move. Docs line: no new docs PR this window besides this checkpoint
document itself.

**A process deviation, stated plainly, without speculation about cause:**
the three Opus research workers on #311, #312 and #313 each self-report
running as `claude-opus-5[1m]` (Claude Opus 5 on a 1M-token context window),
although the project rule forbids a 1M context window and each launch asked
for plain Opus. Each PR's own comment records this rather than hiding it
("the project rule forbids 1M context and the launch asked for plain Opus,
so this is recorded rather than hidden" — #311's and #312's comments; #313's
comment: "recorded as on #311 and #312"). The convergence worker on #314 ran
on standard-context Sonnet: the PR body states "Worker: Claude Sonnet 5
(`claude-sonnet-5`), 200K context (not 1M)." The desktop merge worker on #310
is recorded only as "Merge: Sonnet," with no context-window figure given.
See §6 and §9 for the fuller record.

**Two open decisions for the product/reviewer, stated plainly (carried from
checkpoint-22, unchanged this window):**

1. **Whether #301's 96-HWPUNIT right-edge tolerance is acceptable as a
   declared error budget for the advance metrics**, rather than being read
   as (or mistaken for) a Hancom fit rule. The admissible window is still
   [18.5, 26.3) per #307; **96 still sits outside its own window** — stated,
   not hidden. **This window's addition (not a resolution):** #313 tests a
   `budget240` candidate (raising the constant to 240 HWPUNIT, the smallest
   whole 20-HWPUNIT pen step above `saeopja` ¶393's excess) that would close
   ¶393 exactly with one regression (`moel-2013` ¶220 changes hands) — not
   shipped, and the PR itself notes "twenty steps is two and a half times
   the eight #302 re-derived on a [18.5, 26.3) window." This does not move
   the reviewer's call; it adds one more instance of the same
   96-outside-its-window problem. Still open.
2. **The sidecar data-list line** in `desktop/sidecar/build.ps1` — adding
   `engine/references/fonts/hft-widths.measured.json` so a frozen desktop
   build does not silently fall back to the pre-#292 HFT metric. Still
   unowned this window; #310 restates it "still stands for the product
   line," the same language #305 used in checkpoint-22. Ownership sits on
   the product side per #253.

## What changed since checkpoint-22

| metric | checkpoint-22 | checkpoint-23 | moved in |
|---|---|---|---|
| renderer-line tip | #308 (`claude/engine-e2-converge-11`) | **#311** (probe, `table_row_heights` remainder, on #308) → **#313** (probe, cell-rebreak/right-edge, on #311) is one chain; **#312** (ships `_inkless_stays_at_page_foot`, on #308 directly) is a second, parallel branch; **#314 converges #313 (containing #311) + #312 onto #308** — tip is now #314 | #311, #312, #313, #314 |
| class-B remainder (131, #306/#308) | `table_row_heights` 63, `empty_paragraph` 29 named next | **`empty_paragraph` 29 → 0**, closed by #312's shipped rule; **`table_row_heights` 63 stays open** — #311 traces all 63 to three over-broken cells and refutes both candidate row rules corpus-wide; class B 131 → **102** | #311, #312 |
| the three carrier cells (within `table_row_heights`) | not yet isolated | #313: two of three (`moel-2013` ¶261, `saeopja` ¶189) are `breakNonLatinWord="KEEP_WORD"` mid-word cuts the cache takes and our breaker honours — a break-opportunity question, not a width one; the third (`saeopja` ¶393) is a genuine +238.0 HWPUNIT width excess, +142 of it unexplained (HFT lead for #292); `syllable` candidate: installed 48 → 89, other 21 → 10, 13 regressions; nothing shipped | #313 |
| installed-face punctuation residual | +253.3 HWPUNIT / 487 advances, "no mechanism yet" | **unchanged, confirmed again**: +0.52/glyph, zero on ¶393 (its one punctuation mark sits on an HFT-metered face) — still no mechanism | #313 (confirms, does not close) |
| `layout_divergence` classes (agree/A/B/C) | 1801 / 94 / 131 / 28 | unchanged through #311 and #313 (probe-only); **#312 moves it to 1830 / 94 / 102 / 28**; #314's merged tree confirms **1830 / 94 / 102 / 28** "matches expected exactly" | #312, confirmed #314 |
| `class_b_probe` root list | `table_row_heights` 63, `empty_paragraph` 29, `text_line_height` 19, `cell_valign` 15, `page_top_unattributed` 3, `text_rebreak:width` 2 | `empty_paragraph` 29 → **0**; remaining roots unchanged: `table_row_heights` 63, `text_line_height` 19, `cell_valign` 15, `page_top_unattributed` 3, `text_rebreak:width` 2 (total 102) | #312 |
| corpus raster, 144 dpi, cache (ssim / ssim_inked / IoU) | 0.861944 / 0.393719 / 0.736589 | **still byte-identical** through #311, #312, #313, #314 (0.861944 / 0.393719 / 0.736589, 53 pages, 10/10 exact); all 53 cache-policy PNGs SHA-256-identical before/after #312 | unchanged |
| corpus raster, 144 dpi, computed (ssim / ssim_inked / IoU) | 0.848325 / 0.364894 / 0.692148 | unchanged through #311 and #313 (probe-only); **#312 moves it to 0.850452 / 0.373788 / 0.706026** (one page changes: `nrf` page 2); #314's merged tree reports the same, "equal to #312" | #312 |
| `lineseg_vs_pdf` | 411/411 lines, 8566/8566 chars | **unchanged** everywhere this window (a control; cannot see the flow pass) | unchanged |
| `right_edge_probe --corpus --breaks` | 48/113 installed, 21/47 other, 0 regressions | **unchanged**: #313's own tip and #314's merged tree both confirm 48/113, 21/47, 0 regressions | unchanged |
| desktop line | #305 (on renderer tip #303), a further re-merge onto #308 in flight, unnumbered | **#310 lands that re-merge onto #308**, clean, no conflicts (bringing in #304, #306, #307); privacy_scan HARD=6471, all under `desktop/.gitignore`-matched untracked paths, 0 in tracked files; GUI smoke NOT RUN (4.0G free); a further desktop re-merge onto #314 is now in flight, unnumbered | #310 |
| worker model / context | "Worker: Opus" / "Worker: Sonnet," no context figure stated | **new this window**: #311, #312, #313 self-report `claude-opus-5[1m]` (1M context) against the project rule and the plain-Opus launch request, recorded by each PR's own comment; #314's worker states `claude-sonnet-5`, 200K context, explicitly "not 1M"; #310's merge worker recorded only as "Sonnet," no context figure | #311, #312, #313, #314 |
| writer line | unmoved since checkpoint-06 | still unmoved | — |
| runtime line | unmoved since checkpoint-06 | still unmoved | — |

## 1. Branch DAG

Renderer line: **#311 (probe) → #313 (probe) is one unconverged chain off
#308; #312 (ships a rule) is a second, parallel branch off #308 directly;
#314 converges both back onto #308.**

| PR | branch | base | slice |
|---|---|---|---|
| #311 | `claude/engine-e2-row-height-remainder` | `claude/engine-e2-converge-11` (#308) | `row_height_probe.py --remainder`: groups the 63 `table_row_heights` class-B paragraphs by mechanism; both grouping mechanisms are 63/63 exact but resolve to three carrier cells our line breaker splits one line short of the cache; two candidate row rules tested and refuted corpus-wide; probe only, `own_render.py` untouched |
| #313 | `claude/engine-e2-cell-rebreak` | `claude/engine-e2-row-height-remainder` (#311) | `right_edge_probe.py --cells`: decomposes each of #311's three cells' excess into trailing 자간, installed punctuation residual, HFT-table width, the 96 budget, and a residual; finds two cells are a `breakNonLatinWord="KEEP_WORD"` break-opportunity question, not a width one; scores four candidate closing terms, none exact on all three cells with zero regressions; probe only, `own_render.py` untouched |
| #312 | `claude/engine-e2-empty-remainder` | `claude/engine-e2-converge-11` (#308) | `class_b_probe.py --empty`: confirms the renderer's own empty-paragraph height rule is exact on all 941 inkless paragraphs in the corpus (838 comparable), and roots the 29 `empty_paragraph` class-B paragraphs in a page-foot placement question at `nrf`; ships `OwnRenderer._inkless_stays_at_page_foot`, chosen against three refuted candidates; closes the root 29 → 0 |
| #314 | `claude/engine-e2-converge-12` | `claude/engine-e2-converge-11` (#308), merges #313 (contains #311) and #312 | converges the two unconverged chains onto #308's tip: #313 merges clean, #312 produces one conflict in a notes file, resolved by concatenation; all reported numbers match the two source PRs' own expectations exactly |

Desktop line: one re-merge this window (onto the old tip #308), plus one
more in flight unnumbered (onto the new tip #314).

| PR | branch | base | note |
|---|---|---|---|
| #310 | `claude/desktop-on-renderer-308` | `claude/desktop-on-renderer-303` (#305), tip #308 | re-merge onto renderer tip #308, bringing in #304 (table-origin probe), #306 (page-top space-before rule, shipped) and #307 (trailing 자간, right-edge window re-derived); one clean `ort` merge, no manual conflict markers; `desktop/sidecar/build.ps1` untouched |

**A desktop re-merge onto #314 is in flight as this document is written.**
It has no PR number and none is assigned here.

**A syllable-13 research slice, based on #313, is also in flight as this
document is written** — diagnosing the 13 lines the `syllable` breaking
candidate regresses. It has no PR number and none is assigned here.

Docs line: no new docs PR this window besides this checkpoint document
itself.

Writer line, unchanged from checkpoint-22 — still #224 → #235 → #238 →
#239.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-14` and
`claude/docs-checkpoint-15` … `-22` (each off its own window's renderer
state).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #311 — the `table_row_heights` remainder is three over-broken cells; no row rule ships

**Probe only; `own_render.py` untouched.** Depends on #308. Worker, as
self-reported: Opus 5, 1M context (`claude-opus-5[1m]`) — the project rule
forbids 1M context and the launch asked for plain Opus; recorded, not
hidden. Orchestrator: Fable.

**Question:** of the 131 class-B paragraphs on #308, the largest root is
`table_row_heights` = 63. For each, does path A (the cache read: cell
`hp:lineseg` extents and the row's declared `hp:tc/hp:cellSz@height`) or
path B (the original re-laid out by our own row-height rule) win — grouped
by mechanism, shipping only if one mechanism covers a majority exactly with
no counter-example anywhere in the corpus.

**Grouping:** `cell_rebreak:+1_line:within_declared_row` 35/35 exact
(carrier `saeopja` ¶190, table 1 row 12, carrier row 11);
`cell_rebreak:+1_line:over_declared_row` 28/28 exact (carrier `moel-2013`
¶262, table 6 row 10, carrier row 9) — total **63/63**. Three cells carry
all 63: `moel-2013` table 6 r9c1 (¶261, 28 paragraphs, content 2100 → 3200,
lines 2 → 3, row 2666 → 3766), `saeopja` table 1 r11c0 (¶189, 23
paragraphs, content 2880 → 3920, lines 3 → 4, row 3162 → 4202), `saeopja`
table 4 r0c8 (¶393, 12 paragraphs, content 2040 → 3280, lines 2 → 3, row
2430 → 3562). Each is one paragraph our breaker splits into one more line
than the cache holds; the text-column widths match the cache's own
4-HWPUNIT quantiser (37843/37840, 47475/47472, 2894/2892 HWPUNIT), so the
fault is the line breaker, reached through a table rather than a page —
invisible to `class_b_probe` as a text root because the re-broken
paragraph's own first line does not move.

**Shipped: nothing.** Two candidate row rules, both refuted corpus-wide:
"a row's declared `cellSz@height` is a ceiling as well as a floor" —
refuted on path A itself: of 501 corpus rows with a height every unspanned
cell agrees on, **64 the cache read draws taller than the declaration**
(worst `kstartup` 69505 HWPUNIT; 13 of `moel-2013`'s 33 declared rows).
"The row that overflowed its own declaration pays the table's excess, not
the last row" (`clip_overflow_rows`) — right where designed (`saeopja`
table 4 comes back `[2430, 2430]`, `moel-2013` table 6 comes back exactly
path A) and wrong twice: path A, `kstartup` table 36 (the clip fires under
BOTH policies — row 0 asks 61960 against a declared 58747, 282 past the
box — and moves the boundary 61960 → 61678, changing the byte-identical
cache render, unverifiable against the reference PDF, which draws two
strokes in that x-span and neither is that boundary); path B, `saeopja`
table 1 (the excess is 1040 on row 11, but row 3 overflows its own
declaration by far more, so "largest overflow first" charges row 3
instead: `[…, 26922, …, 1082]` where path A draws `[…, 27962, …, 1082]`).

**Side findings, not chased:** "cache mode does not compute row heights" is
false — `clip_tracks` fires under the cache policy too, on `kstartup`
tables 5 and 36; cache mode is byte-identical here because nothing
changed, not because it cannot change. `kstartup` table 36 seats at
`4294977337` HWPUNIT, an unsigned wrap of a negative offset, so its rows
could not be scored against the PDF even where the PDF draws a rule.

**Before/after, both policies, 144 dpi (unchanged, `own_render.py`
untouched):** cache 0.861944/0.393719/0.736589, computed
0.848325/0.364894/0.692148, 53 pages, 10/10 exact, both before and after.
`layout_divergence --corpus` **1801/94/131/28**, unchanged; full root list
unchanged: `table_row_heights` 63, `empty_paragraph` 29, `text_line_height`
19, `cell_valign` 15, `page_top_unattributed` 3, `text_rebreak:width` 2.
`lineseg_vs_pdf --corpus` **411/411** lines, **8566/8566** characters — a
control, cannot see the flow pass. `render_check.py` render-check-01: 6
match/37 close/6 differ/2 unsupported @96dpi, 14·31·4·2 @144dpi, 9/9 pages
exact, same under both policies — its document carries no cached
`hp:lineseg`, so this tests only that the probe change costs the renderer
nothing.

**Not proven:** nothing was fixed — 63 class-B paragraphs stay class B, the
whole content of the measurement is that they belong to the line breaker's
question, not the root name's. Three cells is three observations, not a
population. The clip candidate was scored on one ordering only (largest
overflow first); other orderings are unmeasured, deliberately, to avoid
another turn of the same overfit. The corpus is the training set.

**Gates:** `py_compile_sweep` 119 files, 0 failures; `engine/tests` 1671
passed/135 skipped, 14 warnings, 3:17; `tests` 496 passed/3 skipped, 9:53;
`privacy_scan` HARD=0 WARN=54 TOTAL=54 (no untracked directory contributed
hits — the working tree held only the three files in this commit).
`pipeline/tests` not run here (orchestrator's to run). **Full gate, tip
`96b62eb`** (comment): `pipeline/tests` in two halves, 581 passed/5 skipped
+ 856 passed/3 skipped, 0 failed (2m44s + 10m00s, second half slowed by a
concurrent worker's pytest in another worktree); with the worker's
engine/tests 1671/135 and tests 496, 0 failed overall.

### #312 — the `empty_paragraph` remainder is a page foot, not a height; `_inkless_stays_at_page_foot` ships

**Shipped.** Depends on #308. Worker, as self-reported: Opus 5, 1M context
(`claude-opus-5[1m]`) — the project rule forbids 1M context and the launch
asked for plain Opus; recorded, not hidden. Orchestrator: Fable.

**Question:** of the 131 class-B paragraphs on #308, `class_b_probe.py
--corpus` roots 29 at `empty_paragraph`, all in `nrf`. Is the height wrong,
or something else?

**Answer, up front: the name is right about the shape and wrong about the
mechanism.** Not one of the 29 is a paragraph whose height is wrong — the
renderer's own empty-paragraph rule is exact on every inkless paragraph in
the corpus. Over the corpus: 941 inkless paragraphs (179 body, 761 cell, 1
in a bare `hp:subList`), 838 with exactly one cached line to compare
against — **vertsize exact 838/838, spacing exact 838/838, advance exact
838/838**, `PERCENT` line spacing throughout, every declared
`hh:charPr@height` read off the empty run. What the 29 carry is a page
foot: `nrf`'s body box is 71436 HWPUNIT; ¶35 fits and its advance leaves
the cursor at 71630, already past the bottom; the cache puts ¶36 and ¶37
(two inkless paragraphs) both at `vertpos` 71630 and opens page 2 only for
¶38 (which carries ink); the flow pass broke at ¶36 instead, carrying both
onto page 2 and pushing everything there down by 2 × 2560 = 5120 HWPUNIT,
i.e. +102.40 px at 144 dpi.

**Grouping:** `page_foot_inkless_overflow`, the block itself, **2/2** exact
(`nrf` ¶38, dy +102.40 px, split `inherited`); inherited through the
container, **27/27** exact (`nrf` ¶42, dy +102.40 px, split `container`,
`cell_top:table_origin` → `via_holder:empty_paragraph`); own
empty-paragraph height wrong: **0** — 838/838 exact, measured not assumed.

**Shipped:** `OwnRenderer._inkless_stays_at_page_foot(block, room)` — a
block with no characters at all (`inkless`, excluding every object
paragraph), exactly one row, arriving at `room <= 0`, is drawn at the
cursor and does not advance it. Counted in
`flow_counters.inkless_kept_at_page_foot`, declared in `BLOCK_HONORED`.
Chosen against three other candidates, each refuted by a real corpus step:
"any block that does not fit opens a new page" (470/472, refuted by `nrf`
¶36/¶37); "an inkless paragraph never opens a new page" (471/472, refuted
by `kstartup` ¶419 — the identical shape, but arriving with 396 HWPUNIT
still to go, where the cache DOES break); "any block stays once the cursor
is past the bottom" (470/472, refuted by `nrf` ¶38 and `kstartup` ¶398,
both past the bottom but carrying text, both moved by the cache). The
shipped rule — "an inkless paragraph stays only when the cursor has
already reached the bottom" — scores **472/472**.

**Before/after, both policies, 144 dpi:** cache byte-identical
0.861944/0.393719/0.736589, 53 pages, 10/10 (all 53 cache-policy page PNGs
SHA-256-identical before/after — the only cache-side difference is the
sidecar gaining a line). Computed **0.850452/0.373788/0.706026** (from
0.848325/0.364894/0.692148), 53 pages, 10/10 — exactly one page in the
corpus changes, `nrf` page 2. `layout_divergence --corpus` **1830/94/102/28**
(from 1801/94/131/28, A&B 1 both); `nrf` alone: agree 84, B 0, seats
differ 0, pages 0 (from agree 55, B 29, seats differ 53, pages 7).
`class_b_probe --corpus` root `empty_paragraph`: **0** (from 29); other
roots unchanged (`table_row_heights` 63, `text_line_height` 19,
`cell_valign` 15, `page_top_unattributed` 3, `text_rebreak:width` 2).
`class_b_probe --corpus --empty` own-rule heights 838/838, identical.
`lineseg_vs_pdf --corpus` 411/411 lines, 8566/8566 characters, identical
(a control). `render_check` render-check-01: identical, all four runs
(6·37·6·2 @96dpi, 14·31·4·2 @144dpi, 9/9 pages exact) — its document
carries no cached `hp:lineseg`, both policies take the computed path, none
of its seven flow page heads arrives at an overfull cursor; "not moving is
a control, not a verdict."

**Not proven:** the whole discriminating population is two paragraphs at
one page foot in one document — the three refuted candidates make the
choice a measurement, but "exact on 472 of 472" rests on 470 steps where
every candidate agrees. "Already at the bottom" is a reading of what the
cache draws, not a documented OWPML rule. The clamp (¶37 sitting at ¶36's
`vertpos` rather than below it) is inferred from one pair; a third such
paragraph would test it and this corpus has none. A multi-row inkless
paragraph is refused rather than answered (no corpus form has one). Path C
is NOT RUN anywhere; every own render stays `own-uncertified`; the corpus
is the training set, again.

**Gates:** `py_compile_sweep` 119 files, 0 failures; `engine/tests` 1668
passed/135 skipped, 14 warnings, 318.78s; `tests` 492 passed/7 skipped,
385.67s; `privacy_scan` **HARD=248 WARN=89 TOTAL=337** — every one of the
248 HARD hits is inside the untracked `desktop/` directory in this
worktree (vendored package-metadata e-mail addresses, the venv's own
`pyvenv.cfg` user-profile paths); HARD outside `desktop/` is 0.
`pipeline/tests` not run here. **Full gate, tip `914b4e2`** (comment):
`pipeline/tests` in three pieces, 579 passed/7 skipped, 397 passed/3
skipped, 459 passed, 0 failed (2m12s + 3m48s + 4m35s); with the worker's
engine/tests 1668/135 and tests 492/7, 0 failed overall; the privacy
HARD=248 confirmed entirely inside the untracked `desktop/` build leftover
in this worktree, not in any of this branch's commits — tracked content is
HARD=0.

### #313 — the three over-broken cells are two faults, and neither term ships

**Probe only; `own_render.py` untouched.** Depends on #311. Worker, as
self-reported: Opus 5, 1M context (`claude-opus-5[1m]`) — the project rule
forbids 1M context and this run was on one; recorded as on #311 and #312.
Orchestrator: Fable.

**Question:** for #311's three cells (`moel-2013` ¶261, `saeopja` ¶189,
`saeopja` ¶393), the cached lines, our lines, the text column, our
measured width of each cached line under the shipped metric, the excess
over the box, and its decomposition into (a) trailing 자간, (b) installed
punctuation residual, (c) HFT-table widths, (d) the 96 right-edge budget,
(e) anything else; then whether one closing term is consistent
corpus-wide. New view: `right_edge_probe.py --cells`, an eighth view on
the existing probe.

**Two of the three are not a width disagreement at all.** The cache breaks
`moel-2013` ¶261 between "예금통장" and "에," and `saeopja` ¶189 between
"제61조제3" and "항" — inside a word, in paragraphs whose `hp:paraPr`
declares `breakNonLatinWord="KEEP_WORD"`. Our breaker honours the
declaration, so those cuts are not in its opportunity set and it takes the
previous space instead: our width for the cache's own line is **784.3**
and **675.0** HWPUNIT *under* the box, respectively. `saeopja` ¶393 is a
genuine width excess: **+238.0** HWPUNIT.

**Decomposition (deciding line, HWPUNIT):**

| term | `moel-2013` ¶261 | `saeopja` ¶189 | `saeopja` ¶393 |
|---|---:|---:|---:|
| excess (shipped metric, vs the real column) | −784.3 | −675.0 | **+238.0** |
| (a) trailing 자간 (#307), already counted | +20.0 | 0.0 | **−104.0** |
| (b) installed punctuation residual (#307) | +2.08 | +2.08 | 0.00 |
| (c) measured HFT table vs the face metric (#292) | 0.0 (0 chars) | 0.0 (0 chars) | 0.0 (6/6 chars on an HFT face the table doesn't carry) |
| (d) right-edge budget (#301) | 96 | 96 | 96 |
| (e) anything else | n/a — not width-limited | n/a — not width-limited | **+142.0** |

(b) prices at +253.3/487 = +0.52 per glyph. On ¶393 it is zero because that
run's one punctuation mark sits on a face Hancom meters through its own
HFT table, and #307's residual is about installed faces only. (c) is zero
on all three: no HFT face on the first two, and on ¶393 the declared face
IS 한양신명조 but `hft_width_table` carries no measured advance for any of
its six characters, so all six advances come from the installed
`H2MJSM.TTF` outlines unchecked against Hancom's pen (four ASCII digits at
0.625 em) — that is where the +142 sits: at the half-cell figure the line
would come to 2784 against a 2894 column. Recorded as where to look (the
lead for #292), not as a rule.

**The term that would close each cell, and its corpus consistency**
(`--cells` scores `advance_probe.break_scoreboard` and
`lineseg_agreement`):

| candidate | installed | other | regress | gain | cells closed |
|---|---:|---:|---:|---:|---|
| shipped | 48/113 | 21/47 | 0 | 0 | none |
| `syllable` | **89/113** | **10/47** | 13 | 43 | ¶261, ¶189 |
| `syl@just` | 85/113 | 10/47 | 13 | 39 | ¶261, ¶189 |
| `budget240` | 48/113 | 21/47 | 1 | 1 | ¶393 |

`syllable` (forcing `BREAK_WORD` on every paragraph) closes ¶261 and ¶189
exactly and is the largest single move on the break score so far (installed
48 → **89/113**), also fixing `jumin` ¶139 (cache and ours both `[0, 60,
113]` become exact) — but it fails the gate: `other` falls 21 → 10, and 13
paragraphs the shipped tree reproduces stop being reproduced. Scoping to
JUSTIFY only (`syl@just`) leaves the **same 13 regressions** and the same
10/47. `budget240` (raising the right-edge constant to 240 — 20 pen steps,
the smallest whole step above ¶393's excess) closes ¶393 exactly with 1
regression (`moel-2013` ¶220 changes hands) and leaves the corpus totals at
48/113 and 21/47 — but 20 steps is "two and a half times the eight #302
re-derived on a [18.5, 26.3) window."

**Shipped: nothing.** No single term is exact on all three cells with zero
regressions corpus-wide. The three cells are two different faults — a
break-opportunity question and a width question — that cannot be one rule.
`own_render.py` is untouched. What ships is the measurement:
`right_edge_probe.py --cells` and 13 unit tests.

**Before/after, both policies, 144 dpi (unchanged, untouched renderer):**
cache 0.861944/0.393719/0.736589, computed 0.848325/0.364894/0.692148, 53
pages, 10/10. `layout_divergence --corpus` **1801/94/131/28** (A&B 1),
unchanged; roots unchanged. `lineseg_vs_pdf --corpus` **411/411** lines,
**8566/8566** characters — a control. `right_edge_probe --corpus --breaks`
**48/113** installed, **21/47** other, on `condense`, `tol12`, `pen` and
`gap`, zero regressions. `render_check.py` render-check-01: 6 match/37
close/6 differ/2 unsupported @96dpi, 14·31·4·2 @144dpi, 9/9 pages exact —
its document carries no cached `hp:lineseg`, so this tests only that the
probe change costs the renderer nothing.

**Not proven:** `breakNonLatinWord` may not mean what this renderer reads
it as — two of the three cells declare KEEP_WORD and the cache breaks
their Hangul mid-word anyway; the corpus census is KEEP_WORD 592/BREAK_WORD
182 of 774 `paraPr`, so it is declared on every one and the open question
is what it MEANS — no public document consulted here settles it. The 13
regressions were not diagnosed (same 13 under both syllable candidates,
named in the probe's output, not read line by line). `saeopja` ¶393's +142
has a candidate (한양신명조 metering ASCII digits at half a cell), not a
measurement — #292's own reference PDFs were not consulted here. Three
cells is three observations, two of them in one form. The corpus is the
training set, again, and `budget240` was picked as the smallest whole pen
step above one cell's excess, which is a fit.

**Gates:** `py_compile_sweep` 119 files, 0 failures; `engine/tests` 1680
passed/135 skipped; `tests` 496 passed/3 skipped; `privacy_scan` HARD=0
WARN=54 TOTAL=54. `pipeline/tests` not run here. **Full gate, tip
`9133359`** (comment): `pipeline/tests` in three pieces, 581 passed/5
skipped, 397 passed/3 skipped, 459 passed, 0 failed (2m09s + 3m48s +
3m29s); with the worker's engine/tests 1680/135 and tests 496/3, 0 failed
overall. Comment: the lead this PR opens — the cache cutting KEEP_WORD
Hangul mid-word in two of the three cells, `syllable` breaking moving
installed agreement 48 → 89 while costing 13 lines on the other side —
starts as the next slice: diagnose the 13.

### #314 — converge #311 + #313 + #312 onto the renderer tip

**Merges #313 (contains #311) and #312 onto `claude/engine-e2-converge-11`
(#308).** Worker: Claude Sonnet 5 (`claude-sonnet-5`), 200K context, not
1M; orchestrator: Fable. No comments.

**Branches merged, in order:** (1) `origin/claude/engine-e2-cell-rebreak`
(#313, contains #311) — probes only, `own_render.py` untouched. Commit
`2e97f7d`. (2) `origin/claude/engine-e2-empty-remainder` (#312) — ships
`_inkless_stays_at_page_foot` in `own_render.py`. Commit `7a654bf`.

**Conflict and resolution:** `engine/references/own-render-notes.md` —
both branches append dated entries at the same point in the file. Resolved
by keeping both sides in merge order: #313's two entries first (already in
HEAD), then #312's entry appended after (the incoming side), no other
edits to either block. No other conflicts:
`engine/scripts/class_b_probe.py`, `engine/scripts/own_render.py`,
`engine/tests/test_own_render.py` merged cleanly, no markers.

**Gates on the merged tree:** `py_compile_sweep` 119 files, 0 failures;
`engine/tests` 1683 passed, 135 skipped, 14 warnings, 385.51s; `tests` 492
passed, 7 skipped, 384.23s; `pipeline/tests` in three pieces (sorted files
1–27 / 28–38 / 39–48 of 48): 579 passed/7 skipped/17 subtests (96.22s),
397 passed/3 skipped/33 subtests (208.89s), 459 passed/13 subtests
(197.08s); `privacy_scan` **HARD=248 WARN=89 TOTAL=337** — all 248 HARD
hits inside the untracked `desktop/` directory, tracked content HARD=0.

**Scoreboard, both policies, 144 dpi:** cache 0.861944/0.393719/0.736589,
53 pages, 10/10, identical to #308; computed **0.850452/0.373788/0.706026**,
53 pages, 10/10, equal to #312. `layout_divergence --corpus`
**1830/94/102/28** — matches expected exactly; root list for the 102
class-B paragraphs: `table_row_heights` 63, `text_line_height` 19,
`cell_valign` 15, `page_top_unattributed` 3, `text_rebreak:width` 2.
`lineseg_vs_pdf --corpus` **411/411** lines, **8566/8566** characters —
matches expected exactly. `right_edge_probe --corpus --breaks` **48/113**
installed, **21/47** other, 0 regressions — matches expected exactly. "No
numbers differ from the spec's expectations; nothing was tuned."

### #310 — the desktop line re-merged onto renderer tip #308

**One merge, clean, no conflicts.** Base `claude/desktop-on-renderer-303`
(#305's branch), tip #308. Depends on #305 (desktop) and #308 (renderer).
Merge: Sonnet; orchestrator: Fable. No comments.

**Brings in:** #304 (table-origin probe — a moved table origin followed
all the way up, page breaks no longer charged for it), #306 (page-top
space-before rule, shipped — the page top answers the same question the
cell top already answers), #307 (trailing 자간 in `_line_fits` — the
installed punctuation residual split from the HFT-metered runs, the
right-edge window shrunk accordingly). All three land via `b6f494d`
(renderer tip #308). `git merge --no-ff origin/claude/engine-e2-converge-11`
resolved cleanly via `ort` (only auto-merges in
`engine/scripts/own_render.py` and `engine/tests/test_own_render.py`, no
manual conflict markers). `desktop/sidecar/build.ps1` was not touched.

**Gates on the merged tree:** `py_compile_sweep` 145 files, 0 failures;
`engine/tests` 1672 passed, 135 skipped, 14 warnings, 240.47s; `tests` (56
files, run foreground in 4 pieces): 364/3 skipped (354.20s), 164/1 skipped
(118.70s), 292 passed (298.74s), 279/3 skipped (158.78s) — total 1099
passed, 7 skipped; `pipeline/tests` (48 files, run foreground in 2
halves): half 1 (first 27 files) 579 passed/7 skipped/17 subtests
(90.90s), half 2 (remaining 21 files) 858 passed/3 skipped/46 subtests
(445.83s) — total 1437 passed, 10 skipped, 63 subtests passed;
`privacy_scan` **HARD=6471 WARN=441 TOTAL=6912** (exit 3, not HARD=0) —
every HARD hit sits under paths matched by `desktop/.gitignore` and
tracked by zero files (`git ls-files` returns 0 for each):
`desktop/sidecar/.venv/`, `desktop/sidecar/build/` and `/dist/`,
`desktop/src-tauri/resources/rigorloomd/`, `desktop/scripts/_run/`; no
hits in a git-tracked file.

**Caret geometry coverage (inside the `tests` pieces):**
`tests/test_runtime_geometry.py` 101 passed (piece 3/4);
`tests/test_runtime_plan.py` 28 passed (piece 4/4);
`tests/test_runtime_render.py` 33 passed (piece 4/4).

**Desktop GUI smoke: NOT RUN** (4.0G free on C:; a pre-built exe smoke is
not cited). **Stated, not done:** `layout_policy`/`layout_policy_reason`
still not surfaced in the desktop UI (owed since #248); the sidecar
data-list handoff from #298 (`hft-widths.measured.json` not shipped by
`build.ps1`) still stands for the product line.

## 3. The development-validation document, this window

**Not reopened.** None of #310, #311, #312, #313 or #314 names or quotes
the development-validation document, touches it, or reports a fresh
measurement against it. It stays on checkpoint-22's last reading
(unchanged since checkpoint-21: checkpoint-20's page — cache
0.6964/0.1834/0.5667, computed 0.6108/0.0982/0.2294, cited from #281's
comment) with the page-bottom fit rule still the standing gap and no
public witness.

## 4. Regressions (with the PR's or commit's own explanation)

**None claimed in what shipped this window.** #312's shipped rule moves
the computed channels only upward (ssim 0.848325 → 0.850452, inked
0.364894 → 0.373788, IoU 0.692148 → 0.706026) and leaves cache mode
byte-identical (all 53 PNGs SHA-256-verified before/after). #311 and #313
are probe-only, `own_render.py` untouched, and both report every number
unchanged from their base. #314 is a no-tuning convergence reproducing
(not introducing) the two source PRs' numbers exactly.

**One measured-but-not-shipped regression set, named plainly by the PR
that found it.** #313's `syllable` candidate would move installed
agreement 48/113 → 89/113 but costs `other` 21/47 → 10/47 — **13
regressions**, named in the probe's output and not shipped for exactly
that reason. Carried to §5 and §8 as the next slice's own target
("diagnose the 13"), not as a code regression against anything currently
running.

**One large privacy-scan swing, repeated from checkpoint-22, explained as
environmental, not a code regression.** #312 and #314 both report
`privacy_scan` HARD=248 (WARN=89, TOTAL=337); #310 reports HARD=6471
(WARN=441, TOTAL=6912) on the larger desktop-merged tree. Every hit in
every case is traced to untracked, `.gitignore`-matched paths under
`desktop/` (a bundled venv, PyInstaller build/dist output, a bundled
sidecar binary, and local run-session scratch data) — "zero HARD in
tracked content" is stated by each PR that reports a nonzero total.

**One process deviation, not a code regression, restated from the
preamble:** #311, #312 and #313 each self-report running on a banned
`claude-opus-5[1m]` (1M) context despite the project rule and the
plain-Opus launch request. See §6 and §9.

## 5. Unsupported / declared elements still open

Carried from checkpoint-22, with this window's closures and new items:

- **Closed this window:** the `empty_paragraph: 29` class-B root named
  open in checkpoint-22 — #312 traces all 29 to one page-foot event at
  `nrf` (not a height fault; the renderer's own empty-paragraph rule is
  exact on all 941 inkless paragraphs in the corpus) and ships
  `OwnRenderer._inkless_stays_at_page_foot`; the root goes 29 → 0; class B
  131 → 102.
- **Measured, not closed:** the `table_row_heights: 63` class-B root — #311
  isolates all 63 to three carrier cells and refutes both candidate row
  rules corpus-wide (one contradicted by 64 corpus rows the cache itself
  draws taller than declared; the other exact on two of the three cells
  and wrong on the third, `kstartup` table 36, in a way the reference PDF
  cannot arbitrate). #313 further splits the three cells into two
  different faults — a `breakNonLatinWord="KEEP_WORD"` break-opportunity
  question (two cells) and a genuine width excess with a +142 HWPUNIT
  unexplained residual (one cell, `saeopja` ¶393) — and scores four
  candidate closing terms, none exact on all three with zero corpus-wide
  regressions. Stays open, unshipped.
- **New, unexplained:** what `breakNonLatinWord="KEEP_WORD"` means against
  the cache's own mid-word cuts (#313) — the corpus declares it on 592 of
  774 `paraPr` (BREAK_WORD on the other 182), so the attribute is present
  everywhere and the open question is its meaning, not its presence.
- **New, undiagnosed:** the 13 lines the `syllable` breaking candidate
  regresses on `other` (#313) — a syllable-13 research slice is already in
  flight to name them, unnumbered as of this document.
- **New, named as a lead, not measured:** `saeopja` ¶393's +142 HWPUNIT
  residual as a candidate for #292's HFT-table gap on 한양신명조 ASCII digit
  advances — #313 names it, #292's own reference PDFs were not consulted
  here.
- **New side findings, not chased (#311):** `clip_tracks` fires under the
  cache policy on `kstartup` tables 5 and 36 (refuting the premise that
  cache mode never computes row heights); `kstartup` table 36's origin
  seats at an unsigned-wrap value (`4294977337` HWPUNIT), leaving its rows
  unscoreable against the reference PDF.
- **New process deviation, recorded not hidden:** #311, #312 and #313's
  workers each self-report `claude-opus-5[1m]` (1M context) against the
  project rule and the plain-Opus launch request; #314's convergence
  worker ran on standard-context Sonnet (`claude-sonnet-5`, 200K,
  explicitly "not 1M").
- **New, unconverged as of writing:** a desktop re-merge onto #314, and a
  syllable-13 research slice on #313, are both in flight; neither has a PR
  number yet.
- **Re-derived earlier, still not closed:** #301's 96-HWPUNIT right-edge
  tolerance sitting outside its own [18.5, 26.3) admissible window — #313's
  `budget240` candidate (240, closing `saeopja` ¶393 with one regression)
  is a further instance of the same problem, not a resolution; the
  reviewer's call remains open.
- **Unchanged from checkpoint-22, still fully open:** the installed-face
  punctuation residual, +253.3 HWPUNIT over 487 advances, still no
  mechanism; the page-fit public witness's Hancom round-trip, blocked on
  COM ownership (untouched this window); the gridmax tail's narrower open
  question (73/75 vs 2/75, #291); the table-split rule's single witness
  (kstartup tbl9, #278) and `repeatHeader`'s complete lack of a positive
  corpus case; the move-whole anchored-table arm's generalization beyond
  `CELL` + anchored, untested; the overflow clamp on gridmax, untested;
  the development-validation document's 5 line-count and 40
  character-split discrepancies and their font-resolution hypothesis
  (#258/#260), not reopened this window (§3); computed layout's own +1800
  page-top drift against that document's PDF (#257), unaddressed; the
  `LayoutSnapshot` contract and `x1` glossary (#253), no response
  recorded; `layout_policy`/`layout_policy_reason` still not surfaced in
  the desktop UI; the acceptance harness's lexical-reader fix for
  header/footer text (#235's queued item); the desktop GUI smoke, still
  never run, free disk read 4.0G at #310 (down from 5.0 GB at #305, still
  judged too thin); the sidecar data-list line for
  `hft-widths.measured.json` in `desktop/sidecar/build.ps1`, still not
  edited, ownership per #253; Codex-app-closed sessions moved; Cursor
  login.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #311 | engine/tests 1671 passed/135 skipped (3:17); tests 496 passed/3 skipped (9:53) | **`pipeline/tests` two halves 581/5/0 + 856/3/0, tip `96b62eb` (2m44s+10m00s, second half slowed by a concurrent worker's pytest) — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 119/0; privacy HARD=0 WARN=54 TOTAL=54. **Worker self-reported `claude-opus-5[1m]` — 1M context against project rule and the plain-Opus launch request, recorded by the comment.** |
| #312 | engine/tests 1668 passed/135 skipped (318.78s); tests 492 passed/7 skipped (385.67s) | **`pipeline/tests` three pieces 579/7/0 + 397/3/0 + 459/0/0, tip `914b4e2` (2m12s+3m48s+4m35s) — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 119/0; privacy HARD=248 (all inside untracked `desktop/`, tracked HARD=0). **Worker self-reported `claude-opus-5[1m]` — same deviation as #311.** |
| #313 | engine/tests 1680 passed/135 skipped; tests 496 passed/3 skipped | **`pipeline/tests` three pieces 581/5/0 + 397/3/0 + 459/0/0, tip `9133359` (2m09s+3m48s+3m29s) — 0 failed overall** (posted as a follow-up comment) | `py_compile_sweep` 119/0; privacy HARD=0 WARN=54 TOTAL=54. **Worker self-reported `claude-opus-5[1m]` — recorded as on #311 and #312.** |
| #314 | engine/tests 1683 passed/135 skipped (385.51s); tests 492 passed/7 skipped (384.23s) | **`pipeline/tests` three pieces 579/7/17 subtests (96.22s) + 397/3/33 subtests (208.89s) + 459/0/13 subtests (197.08s), posted directly in the PR body — 0 failed** | `py_compile_sweep` 119/0; privacy HARD=248 (all inside untracked `desktop/`, tracked HARD=0). **Worker: `claude-sonnet-5`, 200K context, explicitly not 1M.** |
| #310 | engine/tests 1672 passed/135 skipped (240.47s); tests 4 pieces, 1099 passed/7 skipped total | **`pipeline/tests` 2 halves 579/7/17 subtests (90.90s) + 858/3/46 subtests (445.83s), total 1437 passed/10 skipped/63 subtests — posted directly in the PR body** | `py_compile_sweep` 145/0; privacy HARD=6471 (all inside untracked, `.gitignore`-matched `desktop/` paths, tracked HARD=0); GUI smoke NOT RUN (4.0G free on C:). Worker: "Merge: Sonnet," no context figure given. |

Gates as reported: **#311 0 failed (follow-up comment), #312 0 failed
(follow-up comment), #313 0 failed (follow-up comment), #314 gate table
posted directly in body, all numbers matching the spec's expectations,
#310 gate table posted directly in body with the privacy_scan HARD count
explained as environmental and GUI smoke NOT RUN.** Three of the five
workers this window (#311, #312, #313) self-report running on a 1M-context
model against the project's own rule and the launch instruction; #314's
worker explicitly reports standard 200K context; #310's merge worker's
context is not stated.

## 7. Integration conflicts expected when lines converge

**#314's convergence produced one non-functional conflict.** #313 (which
contains #311) merged onto #308's tip clean. #312 — also based on #308
directly — produced one conflict in
`engine/references/own-render-notes.md`, where both branches append a
dated research-notes entry at the same point; resolved by keeping both,
concatenated in merge order (#313's two entries first, then #312's
appended after), no prose rewritten either side. `engine/scripts/class_b_probe.py`,
`engine/scripts/own_render.py` and `engine/tests/test_own_render.py`
auto-merged with no conflict markers at all.

**Desktop converged once more, cleanly, and one more hop is in flight.**
#310 (onto renderer tip #308, bringing in #304/#306/#307) merged via `ort`
with only auto-merges in `own_render.py` and its test file, no manual
conflict markers. A desktop re-merge onto #314 is in flight as this
document is written — its conflict profile is unmeasured here since it has
not yet produced a PR.

**A syllable-13 research slice on #313 is also in flight**, unmeasured
here for the same reason — it has not yet produced a PR.

**Writer and runtime lines remain unconverged with anything**, unchanged
from checkpoint-22.

## 8. Next measurable research question

**In the order #313 names it: what `breakNonLatinWord="KEEP_WORD"` means
against the cache's own mid-word cuts in two of the three `table_row_heights`
carrier cells, and the 13 lines the `syllable` breaking candidate loses on
`other` while gaining 43 on `installed` — named directly as the next
slice's job ("diagnose the 13") by #313's own comment.** Behind that, in
the order the PRs name them: the +253.3 installed-face punctuation
residual, still with no mechanism (#307, reconfirmed unexplained by
#313's decomposition); the HFT table's missing 한양신명조 digit advances,
named as #313's own lead for #292 (the +142 HWPUNIT residual on `saeopja`
¶393, not yet checked against #292's reference PDFs); the reviewer's
decision on the 96-HWPUNIT budget, still outside its [18.5, 26.3)
admissible window, with #313's `budget240` candidate adding one more
instance of the same problem rather than resolving it; and the page-fit
Hancom round-trip, still blocked on COM ownership, untouched again this
window.

## 9. Certification status

Every result in this checkpoint — #311 (row-height remainder probe,
measured and grouped, no rule shipped), #312 (empty-paragraph remainder
rule, shipped), #313 (cell-rebreak decomposition, measured, no term
shipped), #314 (renderer convergence of two branches, one non-functional
conflict resolved), #310 (desktop re-merge, no fix needed) — remains
**own-uncertified**. `render_cert.py` still cannot certify this renderer
absent a PDF text layer, unchanged since checkpoint-01. Path C NOT RUN on
any PR this window (#311, #312 and #313 each state it explicitly; nothing
in #310 or #314 contradicts it); the corpus remains the training set.

**Process deviation, stated plainly, without speculation about cause.**
The three Opus research workers on #311, #312 and #313 each self-report
running as `claude-opus-5[1m]` — Claude Opus 5 on a 1M-token context
window. The project rule forbids a 1M context window, and each of the
three launches asked for plain Opus. Each PR's own comment records this
rather than hiding it: #311's comment states "the project rule forbids 1M
context and the launch asked for plain Opus, so this is recorded rather
than hidden"; #312's comment states the same; #313's comment states it is
"recorded as on #311 and #312." The convergence worker on #314, by
contrast, ran on standard-context Sonnet: the PR body states "Worker:
Claude Sonnet 5 (`claude-sonnet-5`), 200K context (not 1M)." The desktop
merge worker on #310 is recorded only as "Merge: Sonnet," with no
context-window figure stated either way. No PR offers a cause for the
three Opus launches landing on 1M context; none is speculated here.

**What moved, restated plainly:** this window took the 131 class-B
paragraphs #306 named open at checkpoint-22 and split them along their own
lines. `table_row_heights` (63) resolved to three carrier cells (#311),
which then split again into a break-opportunity question on two cells and
a width question on the third (#313) — neither closed, both precisely
measured, and the next slice is named by the PR that found it.
`empty_paragraph` (29) resolved to one page-foot placement event at `nrf`
and shipped a rule (#312: `_inkless_stays_at_page_foot`, 472/472 against
the corpus's discriminating steps, computed IoU 0.692148 → 0.706026, class
B 131 → 102). The renderer forked into two chains off #308 and reconverged
once (#314), with one non-functional conflict resolved by concatenation.
The desktop line landed one re-merge onto the old tip (#310) with a second
already in flight onto the new one, unnumbered, as this document is
written — the same pattern checkpoint-22 recorded a window earlier. Set
against that measured progress, three of the five workers this window ran
outside the project's own model-context rule, recorded here rather than
smoothed over.

**Owed, carried forward from checkpoint-22, plus this window's
additions:**

- Land the desktop re-merge onto #314 that is in flight as this is
  written, once it exists as a numbered PR.
- Land the syllable-13 diagnostic slice on #313 that is in flight as this
  is written, once it exists as a numbered PR.
- Decide what `breakNonLatinWord="KEEP_WORD"` means against the cache's
  own mid-word cuts (#313) — the corpus declares it on 592 of 774
  `paraPr`, so the reading question, not the attribute's presence, is what
  blocks a rule.
- Diagnose the 13 lines the `syllable` breaking candidate regresses on
  `other` (#313), named directly as the next slice's job.
- Check `saeopja` ¶393's +142 HWPUNIT residual against #292's own reference
  PDFs — named as a lead for the HFT table's missing 한양신명조 digit
  advances, not yet measured.
- Decide #301's error-budget framing given #307's admissible window
  [18.5, 26.3) — the reviewer call named open in checkpoint-21, restated
  in checkpoint-22, and now further evidenced (not resolved) by #313's
  `budget240` candidate.
- Find a mechanism for the +253.3 installed-face punctuation residual
  (#307) — still decomposed but unexplained, reconfirmed by #313.
- Ask (do not answer here) why three of five workers this window ran on a
  1M-context model the project rule forbids, when the launches asked for
  plain Opus.
- The sidecar data-list line for `hft-widths.measured.json` in
  `desktop/sidecar/build.ps1` — named by #298, restated still open by
  #305 and again by #310, owed on the product side per #253.
- The page-fit public witness via a Hancom round-trip (#256/#260/#295) —
  untouched this window; still blocked on the COM ownership agreement.
- The gridmax tail's narrower open question — which end of a short row
  absorbs a shortfall — a 2-point observation (73/75 vs 2/75, #291,
  unchanged this window).
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
  not exist; free disk read 5.0 GB at #305, 4.0G at #310, still judged
  marginal.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.

## 10. Coordinator interaction this window

**Unchanged since checkpoint-22.** No new coordinator status request
arrived this window — a search of #310 through #314's bodies and comments
for coordinator language, REG-/STATUS- request IDs, or #274 turns up
nothing. REG-001 (2026-09-05 23:47 KST) and STATUS-001 (2026-09-06 00:51
KST), both already recorded in checkpoints 18–22, remain the only
coordinator requests on file; both were answered as comments on #274,
which stayed the fallback handoff channel throughout. None of #310–#314
records a new request. Recorded here again so that #274's role as the
standing handoff channel carries forward into this checkpoint unchanged.
