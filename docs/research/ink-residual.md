# The ink residual — what still differs when the rows are pixel-exact

[line-and-character-metrics.md](line-and-character-metrics.md) closed the line
metrics: on [render-check-01](render-check-01.md) the three PERCENT
line-spacing features measure **121/121, 140/140 and 94/94 px** against
Hancom's own bands, and every feature band on pages 1–2 starts within 0.0002
of the page height of Hancom's. `F06`, `F07` and `F08` nevertheless still read
`differs`, on both the `ssim` and the `ink_delta` channels.

This page answers the question that leaves: **when the rows already match to
the pixel, what ink still differs?**

## What was measured

| | |
|---|---|
| Candidate | `rigorloom-own` 0.1.0, `claude/engine-e2-converge-3`, `auto` layout |
| Reference | Hancom's `render-check-01.pdf`, rasterised by **PyMuPDF 1.27.2** at the same dpi |
| Method | every glyph of `F01`/`F06`/`F07`/`F08`/`F13`/`F15` paired against the reference **by its own character**, from the PDF's `rawdict` text layer against a trace of `own_render._draw_glyph_piece` |
| Pairs | 101 / 182 / 182 / 136 / 106 / 112 glyphs, 100 % paired at 96 dpi |
| Resolutions | 96, 144, 192, 288, 384 dpi, all 51 features |

**The reference is Hancom's outlines as MuPDF rasterises them.** Nothing here
can separate what Hancom drew from what MuPDF's antialiasing made of it, and
no claim below tries to. "The reference's coverage" means MuPDF's coverage of
Hancom's PDF text layer, and that is the only reference this harness has.

## The four hypotheses, with numbers

### (a) Rasteriser weight — **confirmed, and it is the whole of it**

Both engines resolve the same face for the body runs (바탕 → `batang.ttc`
face 0), the same size, on lines whose baselines agree to ≤ 0.5 px. Per glyph,
padded 2 px on every side so a sub-pixel offset cannot clip ink out of the
window:

| dpi | em, px | coverage ratio (ours ÷ reference) | median | dark-pixel ratio |
|---|---|---|---|---|
| 96 | 13 | **1.80** | 1.76 | **2.60** |
| 144 | 20 | **1.16** | 1.10 | 1.25 |
| 192 | 27 | ~1.0 | | |
| 288 | 40 | ~1.0 | | |

Mean coverage per padded glyph box at 96 dpi: reference **0.0824**, ours
**0.1467** — our stems are 78 % heavier at 13 px em. The excess is
**multiplicative and uniform**: 1.71 on `F01` (which reads `close`), 1.80,
1.80 and 1.83 on `F06`/`F07`/`F08` (which read `differs`), 1.62 on `F13`.
It is the *same renderer behaviour* on a passing feature and a failing one.

Because it is multiplicative, the band-level delta is
`reference_ink_fraction × (ratio − 1)` — proportional to how much text the
band holds. Measured `ink_delta ÷ reference ink fraction` at 96 dpi: `F01`
0.96, `F06` 1.04, `F07` 1.04, `F08` 1.00, `F13` 0.89. The gate compares that
product to a **constant** 0.025, so a dense band is charged more than a sparse
one for identical behaviour, and `F06`/`F07`/`F08` are simply three of the
densest glyph-text bands in the document (reference ink fraction 0.0343 /
0.0296 / 0.0345 against 0.0243–0.0266 for `F01`–`F05`).

The whole effect dies with resolution. Over all 51 features:

```
                    96dpi    144dpi   192dpi   288dpi   384dpi
F06 ink delta      +0.0358  +0.0077  +0.0054  +0.0002  -0.0001
F08 ink delta      +0.0346  +0.0053  +0.0033  -0.0007  -0.0016
F45 ink delta      -0.0078  -0.0144  -0.0168  -0.0158  -0.0166
```

`F45` is the control and it is the point: it is the one feature the renderer
*declares* not drawn (글상자, `hp:rect`), and its delta does **not** collapse —
it holds at −0.008…−0.023 at every resolution while every drawn text feature
walks to zero. A missing element and a heavy rasteriser look nothing alike
once you vary the raster.

`ssim` carries the same story from the other side. Over the 48 features with
ink, Pearson(reference band ink fraction, `ssim`) = **−0.801**: two thirds of
the block-SSIM channel's variance on this document is *how much text is in the
band*, because a uniform coverage excess destroys SSIM's luminance and
contrast terms in proportion to the ink present. `F06` at 0.564 and `F01` at
0.702 differ by 0.14 of SSIM and by 41 % of band density.

**No fudge was applied.** There is no rule in KS X 6101, and nothing in the
reference, that says by how much a rasteriser should be lightened; tuning our
coverage to match MuPDF's would be fitting the renderer to one PDF viewer.
The floor is recorded instead — see *What was adopted*.

### (b) A systematic x-offset (e.g. a dropped left side bearing) — **refuted**

At 96 dpi the first glyph of every paired line starts within **0.008 px** of
the reference span's own x (or exactly `13.008` px on the first-line-indent
lines, which is the indent, not an offset). A dropped `hmtx`/`glyf` left side
bearing would appear as a constant per-glyph shift at the line origin. It does
not appear at all, so there is no bearing rule to apply.

What does drift is *advance accumulation* inside a line: −5.1 px mean on
`F01`, −0.5 to −2.8 px on `F06`/`F07`/`F08` over a 44-character line, i.e.
0.01–0.12 px per character. That is a line-breaking input, not ink, and it is
below the tolerance every channel here uses.

### (c) Font substitution on that block — **refuted**

The sidecar's own `face_resolution` says every declared face resolved
`installed`, with `substituted_character_share` **0.0**:

| declared | slot | file | face index | family |
|---|---|---|---|---|
| 바탕 | hangul/latin/symbol | `batang.ttc` | 0 | 바탕 |
| 돋움 | hangul/latin/symbol | `gulim.ttc` | **2** | 돋움 |
| 궁서 | hangul/latin/symbol | `batang.ttc` | 2 | 궁서 |

`gulim.ttc` is the *container*; face 2 inside it is Dotum, which is exactly
what the reference's text layer names for the `[Fnn]` label runs. An earlier
pass of this measurement reported "Dotum vs gulim.ttc" and was reading the TTC
basename, not the face.

### (d) The scorer (band a few px off, SSIM window straddling an edge) — **refuted for the region**

| | `F06` | `F07` | `F08` |
|---|---|---|---|
| band height, reference / candidate (96 dpi) | 120.7 / 120.9 | 140.7 / 140.9 | 93.3 / 93.2 |
| lines, reference / candidate | 6 / 6 | 6 / 6 | 4 / 4 |
| glyphs paired | 182 / 182 | 182 / 182 | 136 / 136 |
| worst baseline disagreement | 0.1 px | 0.1 px | 0.1 px |

The band is right, the lines are right, and the SSIM window is not straddling
anything. The scorer *is* implicated, but on its bounds rather than its
regions: see (a).

## What was adopted, and what was declared a floor

**Declared a floor, not fixed.** `render_check.RASTERISER_FLOOR` records the
coverage ratios above, the `reference_ink_fraction × (ratio − 1)` model, and
the fact that at 96 dpi the `close` bound (0.025) and the floor are the same
size — so the ink channel's *positive* side cannot separate a real ink error
from the rasteriser at that resolution, while its *negative* side (where `F45`
lives) still can.

**Two bounds made resolution-aware, each an exact no-op at 96 dpi.**

1. `iou_tolerance_px(dpi)`. The tolerance was already stated physically in
   this module — "one pixel at 96 dpi is 0.26 mm, below what a reader can see"
   — but was hard-coded as a pixel count, so the same document scored at
   288 dpi was being held to 0.09 mm. It is now the pixel count covering
   0.26 mm: 1 px at 96, 2 at 144 and 192, 3 at 288.
2. `ink_delta_bound(base, dpi)`. The residual lives in the ~1 px antialias and
   hinting band along glyph outlines, so for a region of fixed *physical* size
   the share of pixels in that band — and therefore the delta two rasterisers
   can disagree by — falls as 1/dpi. The bound scales the same way. This only
   ever **tightens** the gate above 96 dpi, and it is conservative: the
   measured residual decays faster than 1/dpi (1.80 → 1.16 → ~1.0 over
   96 → 144 → 192).

Neither is fitted. Both return exactly the ratified value at `DEFAULT_DPI`,
which is pinned by
`test_the_derived_bounds_are_exact_no_ops_at_the_default_dpi`.

**One channel added, reported and not gated.** `ink.mass_reference`,
`ink.mass_candidate`, `ink.mass_delta` and `ink.mass_ratio` are the same
quantity as `ink.delta` without the 128 threshold. The threshold asks a
yes/no question of every antialiased edge pixel and so amplifies a
rasteriser's weight rather than measuring it — 1.80 of coverage becomes 2.60
of pixel count. `ratio` is the shape the residual actually has, and a later
pass can read it without re-deriving any of this.

## Verdicts, before and after

At the ratified **96 dpi**, nothing moves, and nothing should:

| feature | before | after |
|---|---|---|
| `F06` 줄간격 130% | `differs` (ssim 0.564, IoU 0.375, ink +0.0361) | `differs`, identical |
| `F07` 줄간격 160% | `differs` (ssim 0.619, IoU 0.376, ink +0.0312) | `differs`, identical |
| `F08` 줄간격 200% | `differs` (ssim 0.621, IoU 0.386, ink +0.0346) | `differs`, identical |
| `F13` 자간 | `differs` (ssim 0.648, IoU 0.368, ink +0.0251) | `differs`, identical |
| `F15` 상대 크기 | `differs` (ssim 0.642, IoU 0.415, ink +0.0173) | `differs`, identical |

Tally **3 match · 38 close · 8 differs · 2 unsupported**, page count 9/9
exact, page agreement 51/51 — unchanged, and the gated channels (`ssim`,
`iou`, `ink.delta`) are byte-identical on all 51 features. That is the
regression floor `evals/tasks/render-check-01.yaml` pins, and it is preserved
by construction.

The five features stay `differs` because the measurement says they should:
each fails `ssim` (0.564–0.648 against a 0.65 bound) as well as `ink_delta`,
and no defensible bound change closes a 0.09 SSIM gap. What the measurement
adds is *why* — they are the densest glyph-text bands in the document, and at
13 px em our rasteriser is 80 % heavier than the reference's.

At **144 dpi**, where the physical tolerance is 2 px rather than 1, the tally
moves 3·32·14·2 → **7·38·4·2** and mean IoU 0.3706 → **0.5411** (96 dpi mean
is 0.4214). That number is recorded, not claimed: see the caveat below before
treating it as progress.

## Not proven

- **Whose rasteriser is "right".** The reference is MuPDF's antialiasing of
  Hancom's outlines. A different viewer would give a different coverage ratio,
  and this document cannot rank them.
- **Line breaking is not resolution-independent, and that is a separate bug.**
  At 96 dpi our line breaks match Hancom's on `F06`–`F08` to within one
  character; at 144 dpi they lose four to five characters per line
  (`F06` line 3 begins 서식에서만 for us against 나옵니다. for Hancom). Break
  decisions are being made after the advance has been rounded into device
  pixels. Until that is fixed, the 144 dpi tally above is measuring two
  changes at once and **the default dpi should not be moved**. Follow-up.
- **The private holdout was not re-scored.** It is not committed to this
  repository and is not present in this worktree. It is scored through
  `render_scoreboard`, which this slice does not touch — no renderer, layout
  or scoreboard code changed — so its 18/18 pages and its aggregate channels
  are unchanged by construction rather than by measurement.
- **`F35`, `F48`, `F50`** are the other three `differs` at 96 dpi and are not
  ink questions: `F35` is the anchored-image wrap band, `F48` a landscape
  section exported onto a portrait sheet, `F50` a header band. They are
  untouched here.
