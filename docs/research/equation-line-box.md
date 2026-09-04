# The line box an inline equation claims — measured

[object-line-box.md](object-line-box.md) §5 closed on one named residual:
`render-check-01` ran **11 pages against Hancom's 9**, and the whole of the
first extra page was four `hp:equation` blocks whose declared `hp:sz@height`
Hancom did not honour. This page settles what Hancom honours instead.

Reproduce:

```sh
python tests/corpus/render-check/measure_equation_extent.py
python tests/corpus/render-check/measure_equation_extent.py OTHER.hwpx
```

The script is deliberately independent of the rule it settles: the reserve it
derives for Hancom cancels out whatever this renderer reserved, so it
re-derives the same four numbers before and after the rule changed.

## 1. How the reserve is derived from the reference PDF

`render-check-01` carries no usable `hp:lineseg` — it is Rigorloom-authored
and its cached boxes were never Hancom's — so the reserve is read off
Hancom's own render.

Each equation sits in an identical interval: a `[Fnn]` label paragraph, the
equation paragraph, the next label. Everything in that interval except the
equation's own box is the same in all four, so

    label-to-label advance = C + H

with `C` the surrounding geometry and `H` the equation's box. `C` is read off
**this** renderer's own flow pass over the same four intervals, where the same
identity holds with the box this renderer reserved. It comes out at

    31.60  31.60  31.60  31.60 pt      (spread 0.000)

— the same constant four times, on both sides, which is what makes the
derivation sound rather than a fit. `measure_block_drift.py` independently
shows the two engines agree about that surrounding geometry to 0.05 pt over
the 48 blocks before it.

## 2. What Hancom reserves

| block | script | declared `hp:sz@height` | Hancom reserves | reserved / declared |
|---|---|---|---|---|
| `F36` 분수 | `a over b` | 2400 | **2252** | 0.938 |
| `F37` 근호 | `sqrt {x^{2} + y^{2}}` | 2400 | **1304** | 0.543 |
| `F38` 총합 | `sum _{i=1} ^{n} i^{2} = … over 6` | 3600 | **2696** | 0.749 |
| `F39` 행렬 | `left [ matrix{ 1 & 2 # 3 & 4 } right ]` | 3600 | **2108** | 0.586 |

**Two equal declared heights reserve 2252 and 1304.** That single fact kills
every rule that is a function of the declared extent — no factor, no padding,
no rounding. Hancom re-lays the script out on open and reserves what its own
layout needs; the stored `hp:sz` is a cache it refreshes, not an instruction
it obeys.

### There is no "size to content" attribute

Read, and constant across all four: `heightRelTo="ABSOLUTE"`, `protect="0"`,
`lineMode="CHAR"`, `baseUnit="1000"`, `textColor="#000000"`,
`version="Equation Version 60"`. Those are *exactly* what every equation of
the Hancom-authored holdout declares too — and that document's declared
extents **are** honoured. Two documents, identical flags, opposite outcomes:
no flag is deciding this.

The one attribute that does vary is `baseLine`. The fixture writes a flat
`85` on all four; Hancom writes a measured value per equation (59, 61, 62,
64, 69, 73, 76 across the holdout's 14). That is a *tell* that the fixture's
extents were never Hancom's — not a rule, and it is not read as one.

## 3. The rule adopted

    reserve = min(declared, max(nominal, ink))

where `nominal` is the layout tree's ascent + descent on the
`_EQ_ASC`/`_EQ_DESC` stacking cells and `ink` is the rectangle
`_eq_bounds` says the glyphs mark. Both are measured at a pinned
`EQUATION_EXTENT_DPI`, so the reserve — and therefore the pagination — does
not move with `--dpi`.

Residual against the four measured reserves:

| candidate | worst residual | mean \|e\| |
|---|---|---|
| declared `hp:sz@height` (what this renderer did) | +1492 HWPUNIT (84.0%) | 910 |
| ink extent alone | −494 (19.3%) | 346 |
| **nominal extent alone** | **+256 (17.0%)** | **170** |
| **`min(declared, max(nominal, ink))` — adopted** | **+256 (19.3%)** | **178** |

`nominal` is the term that carries the rule; the same finding `_EQ_ASC`
already records — Hancom stacks on a nominal character cell, not on the
face's own metrics. `ink` joins it as a **floor**, not as a fit: a fence
grown around a fraction, or an accent, marks outside its own cell, and a line
may not reserve less room than the equation puts glyphs in. It costs the fit
nothing measurable.

`min(…, declared)` is not a tolerance either. `_render_equation` already
guarantees an equation is drawn *inside* its declared box, scaling down where
this renderer's metrics do not fit, so the drawn extent can never exceed the
declared one and the line reserves exactly what is drawn. On that side of the
clamp the behaviour is byte-for-byte what it was.

**Rejected by measurement, not by taste:** a constant factor on the content
(the best one is 0.99 and removes none of the spread) and a constant padding
(`reserve − content` runs −1786…+222 HWPUNIT over the four).

## 4. Cross-check on a Hancom-authored document

A private report-class holdout, 14 equations, is the other body of evidence:
because Hancom wrote it, its declared extent **is** Hancom's own measurement
of the very quantity §2 derives from a PDF. This renderer's layout against
it, aggregate only:

| | mean | min | max | sd |
|---|---|---|---|---|
| nominal / declared | 0.9934 | 0.8828 | 1.1089 | 0.0748 |
| ink / declared | 0.9459 | 0.8574 | 1.0614 | 0.0682 |
| adopted / declared | 0.9650 | 0.8828 | 1.0000 | 0.0491 |

n = 18 in all (4 measured off the reference PDF, 14 against Hancom's own
declared extents). What is left is this renderer's **equation layout**
disagreeing with Hancom's by up to 19% on a single equation — a layout
question, not a line-box one.

## 5. What it is worth

| | before | after |
|---|---|---|
| render-check page count | 11 vs 9 | **10** vs 9 |
| render-check page agreement | 47 / 51 | **49 / 51** |
| render-check `iou` mean | 0.4139 | **0.4176** |
| render-check `ssim_inked` mean | 0.1726 | **0.1761** |
| render-check `ssim` mean | 0.7988 | 0.7984 |
| render-check tally | 3 · 37 · 9 · 2 | 3 · 37 · 9 · 2 |
| `F37` 근호 `iou` | 0.423 | **0.481** |
| `F38` 총합 `iou` | 0.337 | **0.434** |
| `F39` 행렬 `iou` | 0.419 | **0.436** |
| corpus render, all ten forms | — | **byte-identical**, page counts unchanged |
| holdout page count | 18 / 18 exact | 18 / 18 exact |
| holdout `text_line_iou_mean` | 0.5847 | **0.5861** |
| holdout `text_line_pair_rate_mean` | 0.9122 | 0.9122 |
| holdout `ssim_inked_mean` | 0.1731 | 0.1727 |
| holdout `ssim_mean` | 0.7457 | 0.7455 |

`F46` 쪽 나누기 and `F47` 쪽을 넘기는 표 come back onto Hancom's page: 36.4 pt
of drift over the four equation blocks becomes 4.7 pt, which is what moves
the page boundary. No corpus form contains an `hp:equation` — verified by
scanning every `Contents/section*.xml` in `tests/corpus/forms/converted` —
so the corpus cannot move, and it does not: all ten renders hash identically
before and after.

## 6. One coupled change in the drawing, and why it was needed

Sizing the box to the equation's own extent leaves no room for the 1 px
antialias margin `_render_equation` pads its mask with, so the last-resort
raster reduction fired on a box that fits — 13% of it at 96 dpi. That margin
is blank, so the fit test now compares the padded mask against the box **plus
that margin** (the same test as "does the ink fit"), the paste clamp is on
the ink rather than on the mask, and `equations.placements[].ink_px` now
records the ink rectangle rather than the padded mask. The containment
promise is unchanged and still checked on the render's own record.

## Not proven

- **n = 4 on the reference-PDF side.** Every other equation measurement here
  is against a declared extent, which is Hancom's answer only because Hancom
  wrote the file.
- **One document authored each way.** The rule rests on exactly one
  document whose declared extents are known *not* to be Hancom's. A second
  such document would be the first real test of it.
- **The residual is this renderer's equation layout, and it is not
  explained.** `sqrt {x^{2} + y^{2}}` measures 17% taller than Hancom lays it
  out, and one holdout equation 11% shorter. No layout term was tuned to
  reduce that here: it is named and left.
- **`lineMode` is constant at `CHAR` on all 18 equations**, so what a
  different value would do is unknown; the same for `heightRelTo`, which is
  `ABSOLUTE` on all 18.
- **The reserve is not resolution-free, it is pinned.** `fontbook`
  rasterises at an integer pixel size, so the same equation measures up to
  14 HWPUNIT (0.14 pt) apart across 300 / 600 / 1200 dpi. Pinning one
  resolution is what makes the reserve deterministic; the choice of which is
  a measurement grid and nothing rests on it.
- **The two remaining render-check pages are still not equations.** Section
  2's two-column region is one page in Hancom and two here
  ([render-check-01.md](render-check-01.md) note 4), and 4.7 pt of block
  drift is left inside section 0.
