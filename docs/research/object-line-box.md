# The line box an inline object claims — measured

`render-check-01` runs **11 pages against Hancom's 9**
([render-check-01.md](render-check-01.md) note 1), and the page-level
disagreement had already survived two rounds of metric fixes. This page walks
the document **block by block**, in flow order, against the reference PDF's own
text layer and rule positions, finds the first block where the two engines part
company by more than half a line, and names the mechanism.

Reproduce:

```sh
python tests/corpus/render-check/measure_object_lines.py          # the rules
python tests/corpus/render-check/measure_block_drift.py           # the walk
```

## 1. Where the drift starts, and what it is not

Walking section 0's 100 top-level blocks — each block's first-line baseline in
the reference PDF against the same baseline in `own_render`'s `computed` flow
pass — the two engines agree to **0.05–0.50 pt** for the first 48 blocks. That
is under a twentieth of a line, and it is the PDF's own 0.12 pt positioning
grid plus 45 paragraph gaps of accumulated rounding. Three of the five
candidates this pass was opened to test are therefore **rejected by the
measurement, not adopted**:

| candidate | measured | verdict |
|---|---|---|
| the inter-paragraph half-margin rule failing per pair type | heading→body, body→heading and body→body all land within 0.10 pt over 45 consecutive pairs | no defect |
| the last line of a paragraph keeping or dropping its spacing tail | every block-to-block advance matches the cached-tail reading (18.70 vs 18.75, 38.84 vs 38.85, …) | no defect |
| table row height / empty-cell padding | `F27`'s three rows measure 23.97 pt each off the reference's own rules against a declared `hp:cellSz@height` of 2400, and `_table_tracks` solves 2400 | no defect |

The **first block past half a line** is block 48, `F24`'s body paragraph:
Hancom breaks it into two lines and we fit it on one, so we run 15.99 pt (one
160% line) **short**. That is the line breaker, not pagination, it is
pre-existing, and it moves the drift the wrong way for a page-count gap.

The block after it is where the real mechanism is. `F27` 표 — 기본 격자 is a
72 pt table on a 160% / 10 pt paragraph. Hancom advances **80.73 pt** over it.
We advanced **115.20 pt** — and 115.20 is exactly 72.00 × 1.60.

## 2. The line spacing was being applied to the object

`_line_metrics` takes the line's `textheight` as the largest declared
character size on the line, and an inline object contributes its own extent
there (measured, and right: kstartup's full-page inline table has a cached
`vertsize` of ~63000 against a `charPr` height of 1000). The `PERCENT` leading
was then computed off that same number — so a 72 pt table on a 160% paragraph
claimed 115.2 pt of the column instead of 80.8, and every table, picture and
equation in the document pushed 60% of its own height of empty space ahead of
it.

The authoring engine's own cached `hp:lineseg` settles both halves. Over the
**79 object lines** of the ten converted corpus forms:

| reading of the line box (`vertsize`) | exact | worst residual |
|---|---|---|
| `hh:sz@height` alone | 16 / 79 | 566 |
| **`hh:sz@height` + `hp:outMargin@top` + `@bottom`** | **79 / 79** | **0** |

| reading of `spacing` (`PERCENT`) | exact | worst residual |
|---|---|---|
| leading off the line box — what this renderer did | 4 / 79 | 98266 |
| **leading off the run's own `hh:charPr@height`** | **66 / 79** | 1000 |

Twelve of the thirteen misses in the second table are within **2 HWPUNIT
(0.02 pt)** of the rule — 1300 → 392 where `round(1300 × 1.30) − 1300` gives
390, and so on — eleven of them +1 or +2 and one −1, on four of the ten
forms. That is a sub-percent
quantisation in Hancom's own arithmetic, not a different rule; it is left
unexplained rather than fitted. The one genuine miss is `admrul`'s 200%
paragraph, where the cache leads by 2400 against the object run's 1400.

**Rules adopted.**

1. An inline object's line box is its extent **plus its own vertical
   `hp:outMargin`**. n = 79, residual 0.
2. The line's `PERCENT`/`FIXED` leading is computed from the largest declared
   **character** size on the line, object slots excluded. n = 79, exact 66,
   ±2 HWPUNIT on 12 more, one outlier at 1000.

A line with no inline object contributes to neither rule: the two heights are
the same number there, and every text-line pitch measurement in
[line-and-character-metrics.md](line-and-character-metrics.md) is untouched.

## 3. Confirmation on the reference PDF, which is not the training set

The rules above are read off the ten corpus forms' **caches**.
`render-check-01` is Rigorloom-authored, carries no `hp:lineseg` at all, and is
measured against **Hancom's rendered PDF** instead — an independent body of
evidence. Its four table blocks whose surrounding geometry is fully determined:

| block | object | predicted advance | measured off the PDF | residual |
|---|---|---|---|---|
| `F27` 3×3 grid | 7200 + 282 | 80.82 pt | 80.73 | −0.09 |
| `F29` 셀 음영 | 4800 + 282 | 56.82 | 57.13 | +0.31 |
| `F31` 테두리 종류 | 4800 + 282 | 56.82 | 56.72 | −0.10 |
| `F32` 셀 세로 정렬 | 6000 + 282 | 68.82 | 68.84 | +0.02 |

n = 4, worst residual 0.31 pt, three of four inside the PDF's 0.12 pt grid.
The old reading predicts 115.20 / 76.80 / 76.80 / 96.00 and misses by 34 to
27 pt each.

The 141 HWPUNIT half of it is visible directly: `F27`'s top rule sits
**1.38 pt** below where the line box starts, against the 1.41 the object
declares, and its bottom rule sits 7.43 pt above where the next block's own
margin begins — 1.41 of outer margin plus 6.00 of leading, predicted 7.41.

## 4. What it was worth

| | before | after |
|---|---|---|
| render-check page agreement | 41 / 51 | **47 / 51** |
| render-check `iou` mean | 0.4104 | **0.4139** |
| render-check `ssim` mean | 0.8073 | 0.7988 |
| render-check tally | 3 · 37 · 9 · 2 | 3 · 37 · 9 · 2 |
| render-check page count | 11 vs 9 | 11 vs 9 |
| corpus flow agreement, `line_layout=auto` (ships) | 469 / 590 pages · 542 / 590 exact `dy` | unchanged |
| corpus flow agreement, `line_layout=computed` | 344 / 590 · 119 / 590 | **392 / 590 · 216 / 590** |
| `kstartup` computed page count | 27 | **22** (reference 22) |
| `gianmun-1ho` / `gianmun-2ho` / `admrul` computed page count | 2 · 2 · 2 | **1 · 1 · 1** (cache 1 · 1 · 1) |
| `kstartup` scoreboard, `block_layout=computed` | `ssim` 0.8774 · `text_line_iou` 0.6686 | **0.8794 · 0.6705** |

`F28` 표 — 셀 병합 moves `close` → **`match`**; `F34`, `F35`, `F42`, `F43`,
`F44` and `F45` join the agreeing side of a page boundary. `F32` 셀 세로 정렬
moves `match` → `close` (IoU 0.647 → 0.509) while its **registration improves
by two orders of magnitude**: its band top was 0.088 of the page height away
from Hancom's and is now 0.0003 away, and its band is 126 px against the
reference's 126 where it was 162. The padded-band IoU rewarded the taller band
for covering more of the reference's ink; the geometry underneath it is now
right, and what is left inside the box is the interior row distribution that
[render-check-01.md](render-check-01.md) note 3 already owns.

`F06`–`F08`'s bands are unchanged to the pixel (121/121, 140/140, 94/94).

## 5. The page count did not move, and this is what is left

Section 0 still runs **8 pages to Hancom's 7**, and the whole of the residual
is now one named mechanism: **the four equation blocks**. `hp:equation` takes
its inline slot from the declared `hp:sz`, and Hancom lays the equation out
itself and gets a different height:

| block | declared `hp:sz@height` | Hancom's measured box |
|---|---|---|
| `F36` 분수 | 2400 | 2252 |
| `F37` 근호 | 2400 | 1304 |
| `F38` 총합 | 3600 | 2696 |
| `F39` 행렬 | 3600 | 2108 |

That is 36.4 pt of drift over four blocks, and it is exactly what pushes
`F45`'s 글상자 off page 4 — with the footnote reserve page 4 has room for it at
Hancom's position and not at ours. Fixing it means measuring `hp:equation`
layout against the reference, which is a different subsystem; it is a
**follow-up**, not this pass.

The other two pages are already owned elsewhere: the two-column section 2 runs
2 pages to Hancom's 1 ([render-check-01.md](render-check-01.md) note 4, where
Hancom does not apply `hp:colPr` at all).

## Not proven

- **The corpus caches are the training set for both rules, and there are
  79 lines of them.** The reference-PDF confirmation in §3 is n = 4.
- **The ±2 HWPUNIT wobble in Hancom's own leading is unexplained.** Twelve of
  79 lines miss the adopted rule by 1 or 2 HWPUNIT in both directions. No
  rounding rule tried reproduces it, and none was adopted to absorb it.
- **`admrul`'s 200% object line is a real miss** (cache 2400, rule 1400) and no
  reading explains it. One line of 79.
- **`FIXED` line spacing on an object line is not measured.** All 79 cached
  object lines are `PERCENT`. The adopted rule states `FIXED` against the same
  character-size basis, which is the natural reading and reduces to today's
  behaviour on every text line, but nothing measures it.
- **A `PERCENT` below 100 on an object line is not measured either** — the
  corpus minimum is 100 — so whether Hancom lets such a line advance by less
  than its own box is unknown; this rule lets it.
- **One page of the shipping `auto` path changes.** 51 of the corpus's
  52 rendered pages are byte-identical before and after; `kstartup` page 5,
  which carries the one stale paragraph holding an inline object, moves and
  its `ssim` falls 0.7575 → 0.7514 against a page whose block assignment comes
  from the cache heuristic `own-render-notes.md` limit 12 already calls wrong.
  On the pagination that is right for that form (`block_layout=computed`) the
  same form improves.
- **The block walk covers section 0 only.** Sections 1 (landscape) and 2
  (two-column) are scored but not walked block by block.
