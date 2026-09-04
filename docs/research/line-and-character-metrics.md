# Line and character metrics, measured off Hancom

`docs/research/render-check-01.md` note 6 groups seven `differs` features —
`F06`–`F08` (줄간격 PERCENT), `F13` (자간), `F14` (장평), `F15` (relSz),
`F16` (글자 위치) — as one guess: "the line-metric gap". This page replaces the
guess with measurements taken from the reference PDF's own text layer, one
rule at a time, and says which of them the renderer had wrong.

Reproduce (PyMuPDF, no renderer involved — it prints every table below):

```sh
python tests/corpus/render-check/measure_metrics.py
```

## What the measurement rests on

Hancom exports this A4 document at 595×841 pt against the nominal
595.276×841.89, so every measured length is **0.99954** of its declared value;
every number below is divided by that before it is compared to a declared
value. Character origins in the PDF sit on a **1/600 in (0.12 pt) grid** — that
is the floor on any residual here, and it is why a residual of 0.09 pt counts
as exact and one of 0.8 pt does not.

The document's declarations are in
`tests/corpus/render-check/build_render_check.py`: body text is 10 pt 바탕
(`hh:charPr@height="1000"`), feature labels 11 pt 돋움, and every body
paragraph is `PERCENT` 160 unless its block says otherwise.

## 1. Line pitch — `hh:lineSpacing`

Baseline-to-baseline within one paragraph, over `F01`–`F09`:

| paragraph | declared | expected | n | worst residual |
|---|---|---|---|---|
| `F01`–`F05` | `PERCENT` 160 @ 10 pt | 16.00 pt | 10 | 0.078 pt |
| `F06` | `PERCENT` 130 @ 10 pt | 13.00 pt | 4 | 0.066 pt |
| `F07` | `PERCENT` 160 @ 10 pt | 16.00 pt | 4 | 0.067 pt |
| `F08` | `PERCENT` 200 @ 10 pt | 20.00 pt | 2 | 0.091 pt |
| `F09` | `FIXED` 2400 | 24.00 pt | 4 | 0.019 pt |

**Rule.** `PERCENT` is `value / 100` times the **declared character size**, and
`FIXED` is the declared value read as 1/100 pt. n = 24, worst residual 0.091 pt,
inside the PDF's own grid.

**Rejected.** Reading `PERCENT` against the face's ascent+descent (Batang's
1.16 em) misses by 2.1–3.9 pt on the same 24 steps; a fixed 1.2 line misses by
1.0–12.0 pt. Neither is a near miss.

This is what `own_render._line_metrics` already did. **Nothing was changed
here, and `F06`–`F08` do not move for this reason** — see §6 for what their
verdict is actually made of.

## 2. The character metrics do not enter the line height

`F15`'s second line is drawn entirely at `hh:relSz="140"` on a 10 pt charPr.
If relSz entered the line height that line would advance 14 pt × 160% =
22.40 pt; at 10 pt it advances 16.00 pt. Measured as the gap from a
paragraph's last baseline to the next block's first baseline, which is
identical to three decimals across three paragraphs of different metrics:

| last line of | metrics on it | gap to the next label |
|---|---|---|
| `F13` | none | 22.906 pt |
| `F14` | `ratio="150"` | 22.906 pt |
| `F15` | `relSz="140"` | 22.906 pt |

And within `F15`, the first line carries a `relSz="140"` character and still
advances 15.950 pt, not 22.40. `F14`'s `ratio="150"` line advances 15.949 pt.

**Rule.** `textheight` is the largest **declared** `hh:charPr@height` on the
line; `hh:relSz`, `hh:ratio` and `hh:offset` do not enter it.

**Changed.** `_line_metrics` multiplied the declared height by `hh:relSz`.

## 3. `hh:spacing` (자간) is a percent of the character's own advance

`F13` draws the same string three times, at `spacing` −15 / 0 / +30, all 10 pt
바탕. A full-width Hangul cell advances by exactly 1 em, so it cannot tell a
gap proportional to the advance from a flat percent of the character size —
both readings predict 8.50 pt at −15 and the measurement is 8.479 pt. The
Latin runs and the half-width space can tell them apart:

| span | measured | ∝ advance | flat % of size |
|---|---|---|---|
| `ABCdef` at −15 | 31.077 pt | **31.106** | 27.595 |
| `ABCdef␣` at +30 | 54.236 pt | **54.074** | 62.595 |
| space (0.5 em) at −15 | 4.319 pt | **4.250** | 3.500 |
| space (0.5 em) at +30 | 6.479 pt | **6.500** | 8.000 |

**Rule.** The gap after a character is that character's **own advance** times
`spacing / 100`. n = 4 discriminating spans; worst residual 0.163 pt against
the proportional reading, 8.36 pt against the flat one.

**Rejected.** The flat reading (`percent × the character size`) was fitted to
gianmun's 발신명의 run — four *Hangul* cells at 15 pt with `spacing="50"`,
drawn 5.5 em wide. Both readings satisfy that run exactly, so nothing measured
before is contradicted; it simply never discriminated.

**Changed.** `_spacing_px` → `_spacing_gap_px(advance_px, spacing)`. This is
note 6's "`F13` over-condenses … which reads like a unit mismatch": at −15 the
old rule took 1.5 pt off a 3.6 pt `f`, leaving 2.1 pt where Hancom leaves
3.06 pt, so narrow glyphs collided while wide ones did not.

The n−1 rule is unchanged: no gap is drawn after the last character of a line.

## 4. `hh:ratio` (장평) scales the advance and the glyph, horizontally only

| declared | measured full cell | expected | `ABCdef` measured | expected |
|---|---|---|---|---|
| 50 | 4.998 pt | 5.00 | 18.239 pt | 18.298 |
| 150 | 15.003 pt | 15.00 | 54.955 pt | 54.893 |

The vertical is untouched: the line carrying the `ratio="150"` run advances
15.949 pt (10 pt at 160%). In the PDF the ratio run is a text matrix with
unequal x and y scale, which is why PyMuPDF reports its span size as the
geometric mean (9.952 × √1.5 = 12.188), not as 1.5 × the size.

**Unchanged.** `own_render` already scaled both the advance and the composited
glyph mask by `ratio / 100`, and already kept `ratio` out of the line height.

## 5. `hh:offset` (글자 위치) — sign and reference size, both wrong

| run | declared | drawn, relative to the neutral baseline |
|---|---|---|
| `F16` run 1 | `offset="40"`, 10 pt | **+3.962 pt (lower on the page)** |
| `F16` run 3 | `offset="-40"`, 10 pt | −3.952 pt |
| `F21` 위첨자 | `offset="35"`, `relSz="65"`, 10 pt | **+3.482 pt (lower)** |
| `F22` 아래첨자 | `offset="-35"`, `relSz="65"`, 10 pt | −3.602 pt |

**Rule.** A **positive** `hh:offset` moves the glyph **down** the page, by the
declared percent of `hh:charPr@height`. n = 4, worst residual 0.102 pt.

**Rejected.** Reading the percent against the `hh:relSz`-scaled size predicts
±2.275 pt for `F21`/`F22` against a measured ±3.5, a 1.2 pt miss.

Hancom's own render therefore draws this document's 위첨자 *below* its base
line and its 아래첨자 above it — the builder named the runs for the intent, and
Hancom honoured the attribute. The renderer is measured against what Hancom
draws, not against the run's name.

**Changed.** `_text_pieces` computed `offset_px = size_px × offset / 100` with
`size_px` the relSz-scaled font size, and `_draw_glyph_piece` subtracted it
from the baseline. Now `_offset_px(cid, offset)` returns the raise, negated,
off the declared height.

## 6. The paragraph gap, and the unit that was hiding under it

`F06`–`F08` read `differs` because our whole block band sat ~23 pt above
Hancom's by the time the flow pass reached them, not because the pitch inside
them was wrong (§1). Chasing that drift turned up a unit error one level below
the paragraph margin.

Between two adjacent top-level paragraphs, taking the baseline offset inside a
line box as `0.85 × textheight` (`BASELINE_RATIO`, already pinned by the
corpus), this document's gaps are exactly what it declares, at face value:

| pair | `A@next` | `B@prev` | gap beyond the line advance |
|---|---|---|---|
| title → `F01` label | 0 | 600 | 6.026 pt |
| `F01` label → body | 200 | 0 | 1.958 pt |
| `F01` body → `F02` label | 0 | 600 | 5.936 pt |

But `PARA_MARGIN_SCALE = 0.5` — half of each declared side — is what the ten
converted corpus forms measured, and it was not a small preference: over their
590 top-level blocks, `own_render --flow-agreement` places

| reading | blocks on the cached vertical position |
|---|---|
| half each side | **542 / 590** |
| face value | 236 / 590 |
| `max(A@next, B@prev)` | 236 / 590 |

`max` was the one hypothesis that could have satisfied both (it equals
half-each-side whenever the two sides declare the same value); the corpus
rejects it outright.

**The difference is not the margin rule, it is the unit.** Every corpus
`hh:paraPr` wraps its `hh:margin` and `hh:lineSpacing` in the MCE pattern —
`<hp:switch><hp:case hp:required-namespace="…/2016/HwpUnitChar">…</hp:case>
<hp:default>…</hp:default></hp:switch>` — and the two branches carry the same
length in two different units. Over the twelve corpus forms' 811 `paraPr`,
every one of which carries the switch, `default / case` is **exactly 2.0** with
no exception on every length non-zero in both:

| field | pairs at ratio 2.0 | pairs at any other ratio |
|---|---|---|
| `hc:intent` | 328 | 0 |
| `hc:left` | 116 | 0 |
| `hc:right` | 54 | 0 |
| `hc:prev` | 143 | 0 |
| `hc:next` | 11 | 0 |
| `hh:lineSpacing` `FIXED` | 1 | 0 |
| `hh:lineSpacing` `PERCENT` | — | 806 at ratio **1.0** |

A `PERCENT` line spacing is a percent, not a length, and is identical in both
branches on all 806 — which is what makes "a different unit" the reading rather
than "a different value". The `case` branch's elements are the ones carrying
`unit="HWPUNIT"`.

So the whole of the old halving was the reader taking the `default` branch — as
a renderer without the 2016 namespace must — and then not converting. It halved
`prev`/`next` with a constant and left `left`/`right`/`intent` **doubled**.
`render-check-01`, authored as `.hwpx` and carrying no switch, declares
`unit="HWPUNIT"` outright and was then halved for no reason.

**Rule.** A length read out of a `paraPr` switch's `default` branch is halved
to reach HWPUNIT; a length outside such a switch is already HWPUNIT. One rule,
both bodies of evidence: corpus flow agreement is unchanged at **542 / 590**
blocks exact and 469 / 590 pages, and `render-check-01`'s block bands now land
on Hancom's to within 0.0002 of the page height.

**Changed.** `_para_pr_geometry_source` returns `(branch, length_scale)`;
`PARA_MARGIN_SCALE` is gone. Fixing the doubled `intent`/`left` is most of what
moved the line breaker: corpus break positions 65 → 68 of 216, paragraph line
counts 2097 → 2105, `kstartup` alone 435 → 450.

## What it was worth

Measured on `render-check-01` (96 dpi, `auto` layout policy) and on the ten
corpus forms with a Hancom reference PDF:

| | before | after |
|---|---|---|
| render-check tally (match · close · differs · unsupported) | 1 · 35 · 13 · 2 | **3 · 37 · 9 · 2** |
| render-check `ssim` mean / IoU mean | 0.7918 / 0.3728 | **0.8073 / 0.4104** |
| corpus `ssim` mean | 0.791547 | **0.793152** |
| corpus `ssim_inked` mean | 0.250879 | **0.259804** |
| corpus text-line IoU mean | 0.617809 | **0.620571** |
| corpus page count exact / verdict pass | 9 / 10 · 9 / 10 | 9 / 10 · 9 / 10 |
| lineseg break positions (of 216) | 65 | **68** |
| flow-agreement blocks exact (of 590) | 542 | 542 |

Off `differs`: `F14` 장평, `F16` 글자 위치, `F17` 진하게, `F27` and `F28` 표.
To `match`: `F22` 아래첨자, `F32` 셀 세로 정렬. One feature moved the other way
— `F35` 그림 어울림 (IoU 0.317 → 0.117), whose anchored image now lands on a
different page from Hancom's; that is the page-count gap `render-check-01.md`
note 1 already owns, not a wrapping change.

`F06`–`F08` are still `differs`, but for a different reason than before: their
bands now agree with Hancom's **to the pixel** (121/121, 140/140, 94/94 px) and
they fail only on `ssim` (0.56–0.62 against the 0.65 bound) and `ink Δ`
(+0.031…+0.036 against 0.025) — the rasteriser/hinting ceiling
`render-check-01.md` already names as unisolated, not layout. `F13` misses
`close` by 0.0001 on `ink Δ` and 0.0024 on `ssim`; `F15` by 0.008 on `ssim`.

## Not proven

- **One document, one Hancom build**, the same limit `render-check-01.md`
  already carries. Every rule here comes from `render-check-01.pdf`.
- **The switch-branch unit is measured, not read.** KS X 6101 is not the
  source of the 2.0; 811 paraPr across twelve forms are. No form in the corpus
  carries a `paraPr` switch whose two branches disagree in any other way, so
  "the default branch is in half a HWPUNIT" is the simplest reading of that
  ratio and not the only conceivable one. Four `intent` and four `next`
  elements are 0 in the `case` branch and non-zero in `default`; they are
  counted in neither column above and no reading explains them.
- **The same doubling in `hh:tabPr`.** The corpus's `hh:tabItem@pos` shows the
  identical 2.0 between the two branches, and this renderer does not read tab
  stops out of the switch at all (it looks for `hh:tab`, finds none, and falls
  back to its declared default interval). Untouched here.
- **The order `hh:spacing` composes in.** The gap is taken as a percent of the
  advance *after* `hh:ratio` and `hh:relSz`. `F13` declares neither, so the
  ordering is the natural reading of the rule, not a measurement.
- **`hh:offset` on a line's height.** Whether a large offset grows the line box
  is untested: `F16`'s ±40 at 10 pt stays inside the 160% line. The renderer
  grows its own drawn box's ascent/descent by the shift and does not touch
  `textheight`.
- **Faces.** Every measurement above is on 바탕/돋움 as Hancom resolved them.
  A face whose Latin advances differ would change the *numbers* in §3, not the
  rule, since the rule is stated against whatever advance the face gives.
- **`hh:relSz` under 100% on the line height** is measured only upward (140).
  A line whose *largest* declared height belongs to a relSz-shrunk run is not
  exercised by this document.
