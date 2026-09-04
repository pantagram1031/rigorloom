# render-check-01 — Hancom vs `own_render`, feature by feature

`tests/corpus/render-check/render-check-01.hwpx` is a Rigorloom-authored
synthetic document carrying 51 labelled feature blocks — one per Tier-1 and
Tier-2 visual feature of [the Hangul feature
catalog](hangul-feature-catalog.md). This page puts Hancom's rendering and
`own_render`'s side by side, one feature at a time, so the renderer backlog
can be argued from per-feature evidence instead of a page-level SSIM.

Reproduce:

```sh
python tests/corpus/render-check/build_render_check.py          # the document
python engine/scripts/com_backend.py convert \
    --file tests/corpus/render-check/render-check-01.hwpx \
    --to   tests/corpus/render-check/render-check-01.pdf        # the reference
python engine/scripts/render_check.py \
    tests/corpus/render-check/render-check-01.hwpx \
    tests/corpus/render-check/render-check-01.pdf \
    --blocks tests/corpus/render-check/render-check-01.blocks.json \
    --dpi 96 --report docs/research/render-check-01.report.json \
    --png-dir docs/research/render-check-01
```

## What the comparison rests on

| | |
|---|---|
| Reference | Hwp 2024 13.0.0.2986 / Hancom PDF 1.3.0.550, via `com_backend.py convert` |
| Candidate | `rigorloom-own` 0.1.0, grade `own-uncertified`, `--dpi 96`, default `auto` layout policy |
| 1:1 | `render_scoreboard.reference_geometry_scale` = **0.995** (declared median 10.00 pt vs reference median 9.95 pt, tolerance 0.05) — comparable, no scale correction applied |
| Page count | reference **9**, candidate **11** — *not* exact; see note 1 |
| Hancom acceptance | a COM open+save round-trip of the document keeps all 51 feature elements |

Regions are derived, never hand-placed, and the two sides are located
independently of each other:

- **candidate** — the block ordinal recorded in `render-check-01.blocks.json`,
  looked up in `own_render`'s `block_layout[section]["blocks"]`, which carries
  the page and `vertpos_hwpunit` the flow pass gave that block. Page furniture
  has no top-level block and uses the section's own header/footer bands.
- **reference** — PyMuPDF `search_for` on the feature's own `[Fnn]` marker in
  the Hancom PDF's text layer. That is the authoring engine's placement of the
  same anchor, so a pagination disagreement surfaces as `page_agreement: false`
  rather than silently cropping the wrong band.

Crops are **padded, never rescaled** (the two engines break lines differently,
and squashing the taller band would score that away). `iou` is the
intersection-over-union of the two ink masks **dilated by one pixel** — at
96 dpi that is 0.26 mm of tolerance, below what a reader can see and far below
what a real layout bug produces. `ink Δ` is candidate ink fraction minus
reference; negative means we drew less than Hancom.

### Verdicts

| verdict | bound |
|---|---|
| `unsupported` | the renderer's own `elements_skipped` says this feature's element was **not drawn** or drawn as a placeholder |
| `match` | `iou >= 0.55` and `abs(ink Δ) <= 0.010` and `ssim >= 0.90` |
| `close` | `iou >= 0.30` and `abs(ink Δ) <= 0.025` and `ssim >= 0.65` |
| `differs` | anything else |

`ssim_inked` is reported but **not** gated on. Measured here it stays between
−0.05 and 0.60 for every feature, including visibly correct ones, because
block SSIM over 10 pt Korean glyphs collapses as soon as the two engines pick
different faces. A gate every feature fails ranks nothing. The bounds above
were set against the spread this document produced, so they separate its
features; they are **not** a ratified regression gate and no second document
has been scored with them.

## Result

**1 match · 35 close · 13 differs · 2 unsupported** over 51 features.

Measured on the converged E2 tree (`claude/engine-e2-converge`: the
`hp:outMargin` registration fix #211, the bundled Korean fallback faces #208
and the inline-table move rule #210 in one tree). Three features moved off
`differs` since this page was first written against the pre-convergence tree
(**1 · 32 · 16 · 2**):

| feature | before | after | mechanism |
|---|---|---|---|
| `F47` 표 — 쪽을 넘기는 표 | IoU 0.025 `differs` | IoU 0.535 `close` | #210 — an inline (글자처럼 취급) table never splits; it moves whole, as Hancom's does. See note 2 |
| `F31` 표 — 테두리 종류 | IoU 0.222 `differs` | IoU 0.376 `close` | #211 — the `hp:outMargin` inset puts the table box where Hancom puts it, so the grids overlap. See note 3 |
| `F32` 표 — 셀 세로 정렬 | IoU 0.205 `differs` | IoU 0.479 `close` | #211, same inset |

Means over the 51 features: `ssim` 0.7813 → 0.7918, `ssim_inked` 0.1218 →
0.1396, IoU 0.3429 → 0.3728. Page agreement is unchanged at 45/51 — the same
six features (`F44`–`F49`) still land on a different page in the two engines.
The bundled-fonts tier (#208) changed **nothing** on this document: it
declares only 바탕, 돋움 and 궁서, all three installed on the measuring
machine, so the installed tier wins and `BundledFontMap` is never consulted.
This is the first measurement with registration and fonts in one tree.

| feature | ssim | ssim(inked) | IoU | ink Δ | page | verdict |
|---|---|---|---|---|---|---|
| `F01` [정렬 — 왼쪽 (align LEFT)](render-check-01/F01.png) | 0.679 | 0.086 | 0.354 | +0.0236 | 1 | **close** |
| `F02` [정렬 — 가운데 (align CENTER)](render-check-01/F02.png) | 0.677 | 0.100 | 0.403 | +0.0240 | 1 | **close** |
| `F03` [정렬 — 오른쪽 (align RIGHT)](render-check-01/F03.png) | 0.693 | 0.106 | 0.403 | +0.0240 | 1 | **close** |
| `F04` [정렬 — 양쪽 (align JUSTIFY)](render-check-01/F04.png) | 0.693 | 0.119 | 0.393 | +0.0246 | 1 | **close** |
| `F05` [정렬 — 배분 (align DISTRIBUTE)](render-check-01/F05.png) | 0.678 | 0.117 | 0.395 | +0.0249 | 1 | **close** |
| `F06` [줄간격 — 130% (PERCENT)](render-check-01/F06.png) | 0.552 | 0.078 | 0.356 | +0.0361 | 1 | **differs** |
| `F07` [줄간격 — 160% (PERCENT)](render-check-01/F07.png) | 0.595 | 0.080 | 0.346 | +0.0312 | 1 | **differs** |
| `F08` [줄간격 — 200% (PERCENT)](render-check-01/F08.png) | 0.579 | 0.067 | 0.284 | +0.0368 | 1 | **differs** |
| `F09` [줄간격 — 고정 24pt (FIXED)](render-check-01/F09.png) | 0.740 | 0.061 | 0.328 | +0.0225 | 2 | **close** |
| `F10` [첫줄 들여쓰기 (first-line indent)](render-check-01/F10.png) | 0.652 | 0.060 | 0.323 | +0.0241 | 2 | **close** |
| `F11` [내어쓰기 (hanging indent)](render-check-01/F11.png) | 0.668 | 0.092 | 0.327 | +0.0239 | 2 | **close** |
| `F12` [좌우 여백 (left/right margin)](render-check-01/F12.png) | 0.674 | 0.077 | 0.344 | +0.0241 | 2 | **close** |
| `F13` [자간 (hh:spacing −15 / 0 / +30)](render-check-01/F13.png) | 0.633 | 0.071 | 0.366 | +0.0255 | 2 | **differs** |
| `F14` [장평 (hh:ratio 50 / 100 / 150)](render-check-01/F14.png) | 0.639 | 0.101 | 0.345 | +0.0247 | 2 | **differs** |
| `F15` [상대 크기 (hh:relSz 60 / 100 / 140)](render-check-01/F15.png) | 0.611 | 0.055 | 0.217 | +0.0150 | 2 | **differs** |
| `F16` [글자 위치 (hh:offset +40 / 0 / −40)](render-check-01/F16.png) | 0.584 | 0.063 | 0.211 | +0.0246 | 2 | **differs** |
| `F17` [진하게 (bold)](render-check-01/F17.png) | 0.801 | 0.052 | 0.129 | +0.0358 | 2 | **differs** |
| `F18` [기울임 (italic)](render-check-01/F18.png) | 0.801 | 0.097 | 0.422 | +0.0148 | 3 | **close** |
| `F19` [밑줄 (underline)](render-check-01/F19.png) | 0.789 | 0.096 | 0.420 | +0.0201 | 3 | **close** |
| `F20` [취소선 (strikeout)](render-check-01/F20.png) | 0.801 | 0.120 | 0.425 | +0.0135 | 3 | **close** |
| `F21` [위첨자 (superscript)](render-check-01/F21.png) | 0.898 | 0.246 | 0.532 | +0.0077 | 3 | **close** |
| `F22` [아래첨자 (subscript)](render-check-01/F22.png) | 0.914 | 0.142 | 0.524 | +0.0084 | 3 | **close** |
| `F23` [글꼴 — 바탕 (declared face 바탕)](render-check-01/F23.png) | 0.791 | 0.141 | 0.428 | +0.0175 | 3 | **close** |
| `F24` [글꼴 — 돋움 (declared face 돋움)](render-check-01/F24.png) | 0.788 | 0.103 | 0.463 | +0.0092 | 3 | **close** |
| `F25` [글꼴 — 궁서 (declared face 궁서)](render-check-01/F25.png) | 0.803 | 0.186 | 0.477 | +0.0012 | 3 | **close** |
| `F26` [글자 크기 8 / 10 / 12 / 14 / 18 / 24 pt](render-check-01/F26.png) | 0.848 | 0.170 | 0.409 | +0.0085 | 3 | **close** |
| `F27` [표 — 기본 격자 (plain grid 3×3)](render-check-01/F27.png) | 0.773 | 0.003 | 0.294 | +0.0175 | 3 | **differs** |
| `F28` [표 — 셀 병합 (colSpan 2 + rowSpan 2)](render-check-01/F28.png) | 0.747 | 0.052 | 0.137 | +0.0329 | 3 | **differs** |
| `F29` [표 — 셀 음영 (cell shading #D9D9D9)](render-check-01/F29.png) | 0.894 | 0.700 | 0.757 | +0.0084 | 4 | **close** |
| `F30` [캡션 — 표 (table caption)](render-check-01/F30.png) | 0.901 | 0.215 | 0.498 | +0.0120 | 4 | **close** |
| `F31` [표 — 테두리 종류 (SOLID / DASH / DOT / DOUBLE / 굵기)](render-check-01/F31.png) | 0.723 | 0.117 | 0.376 | +0.0198 | 4 | **close** |
| `F32` [표 — 셀 세로 정렬 (TOP / CENTER / BOTTOM)](render-check-01/F32.png) | 0.836 | 0.031 | 0.479 | +0.0067 | 4 | **close** |
| `F33` [그림 — 본문 안 (inline, treatAsChar)](render-check-01/F33.png) | 0.865 | 0.234 | 0.481 | +0.0041 | 4 | **close** |
| `F34` [캡션 — 그림 (image caption)](render-check-01/F34.png) | 0.831 | 0.108 | 0.401 | +0.0144 | 4 | **close** |
| `F35` [그림 — 어울림 TOP_AND_BOTTOM (anchored, text wrap)](render-check-01/F35.png) | 0.825 | 0.255 | 0.317 | -0.0098 | 4 | **close** |
| `F36` [수식 — 분수 (fraction)](render-check-01/F36.png) | 0.959 | 0.286 | 0.600 | +0.0044 | 5 | **match** |
| `F37` [수식 — 근호 (sqrt)](render-check-01/F37.png) | 0.941 | 0.205 | 0.461 | +0.0046 | 5 | **close** |
| `F38` [수식 — 총합·상하한 (sum with limits)](render-check-01/F38.png) | 0.884 | 0.066 | 0.313 | +0.0085 | 5 | **close** |
| `F39` [수식 — 행렬 (matrix)](render-check-01/F39.png) | 0.946 | 0.134 | 0.416 | +0.0043 | 5 | **close** |
| `F40` [개요 번호 — 3수준 (numbered outline, 1. / 1.1 / 1.1.1)](render-check-01/F40.png) | 0.855 | 0.102 | 0.305 | +0.0096 | 5 | **close** |
| `F41` [글머리표 (bullets)](render-check-01/F41.png) | 0.874 | 0.168 | 0.395 | +0.0076 | 5 | **close** |
| `F42` [각주 (footnote)](render-check-01/F42.png) | 0.826 | 0.091 | 0.431 | +0.0134 | 5 | **close** |
| `F43` [미주 (endnote)](render-check-01/F43.png) | 0.840 | 0.097 | 0.314 | +0.0172 | 5 | **close** |
| `F44` [하이퍼링크 (hyperlink field)](render-check-01/F44.png) | 0.843 | 0.122 | 0.432 | +0.0224 | 5/6 | **close** |
| `F45` [글상자 / 그리기 개체 사각형 (text box)](render-check-01/F45.png) | 0.977 | 0.584 | 0.197 | -0.0024 | 5/6 | **unsupported** |
| `F46` [쪽 나누기 (page break, pageBreakBefore)](render-check-01/F46.png) | 0.798 | 0.200 | 0.524 | +0.0190 | 6/7 | **close** |
| `F47` [표 — 쪽을 넘기는 표 (table split across a page)](render-check-01/F47.png) | 0.993 | 0.240 | 0.535 | +0.0008 | 6/7 | **close** |
| `F48` [구역 나누기 — 가로 용지 + 다른 여백 (section break, landscape)](render-check-01/F48.png) | 0.943 | 0.068 | 0.268 | +0.0036 | 8/10 | **differs** |
| `F49` [다단 — 2단 구역 (two-column section)](render-check-01/F49.png) | 0.818 | 0.051 | 0.150 | +0.0085 | 9/11 | **differs** |
| `F50` [머리말 (header)](render-check-01/F50.png) | 0.940 | 0.153 | 0.153 | +0.0090 | 1 | **differs** |
| `F51` [꼬리말 + 쪽 번호 (footer with page number)](render-check-01/F51.png) | 0.974 | 0.154 | 0.156 | +0.0030 | 1 | **unsupported** |

Each feature name links to its side-by-side strip (Hancom left, ours right)
under [`render-check-01/`](render-check-01/). Full numbers, including the
per-feature `band_px` and the declared limits each feature owns, are in
[`render-check-01.report.json`](render-check-01.report.json).

## Notes — what differs, and the mechanism

### 1. Pagination drift: we run one page longer than Hancom

Ours is 11 pages against Hancom's 9, and six features (`F44`–`F49`) land on a
different page in the two engines. Two more are page-boundary artefacts rather
than feature failures: for `F17` (진하게) the reference band is 20 px and ours
is 77 px, because Hancom pushed the content paragraph onto the next page while
we kept it with its label; `F28` is 28 px against 150 px for the same reason.
Their low IoU says nothing about bold or about merged cells.

*Mechanism guess.* Two contributions. Block heights run slightly tall on our
side — visible in the alignment blocks, where the same filler is three lines
for us and two or three for Hancom depending on where the space advance lands
— and that accumulates down the page. On top of that Hancom moves a block that
would be badly split, where we split in place: see note 2.

*Since fixed, and it cost a page.* Note 2's rule landed, so we no longer split
that table in place — we move it whole, as Hancom does. That removed the
second contribution and made the drift **worse** by one page (10 → 11), which
is the honest outcome: moving the table whole pushes its rows down instead of
filling the room the split used. The residual is now entirely the first
contribution, block heights running tall.

### 2. `F47` 표 — 쪽을 넘기는 표 (IoU 0.025, the largest gap)

Hancom moves the whole 26-row table to the next page rather than start it in
the few centimetres left below its label. We start it immediately and split it
at the page edge. The reference band for the feature is therefore empty and
ours is a full table, which is why this is the worst score on the page and why
the number overstates how wrong the *table* drawing is.

*Mechanism guess.* Table-start widow handling: `hp:tbl@pageBreak` is
`CELL` here, and Hancom appears to apply a keep-with rule before it applies
the split rule. `own_render`'s own `block_not_honored` list already names
`hp:tbl@repeatHeader`; this is a neighbouring, unnamed rule.

> **Measured since, and the guess was wrong.** There is no keep-with rule.
> `pageBreak` is only half the permission: Hancom splits a table at a row
> boundary only when it is *anchored*, and this one is 글자처럼 취급
> (`treatAsChar="1"`), so it can never split — it moves whole and, on a page
> that is still too short for it, overflows. Eleven probe variants and three
> Hancom-authored controls, no exception:
> [table-page-break-rule.md](table-page-break-rule.md). Fixed there; `F47`
> now reads `close` (IoU 0.025 → 0.535, ssim 0.686 → 0.993), and the table
> above carries the post-fix numbers. Heading and body kept as written, since
> they record the state the rule was found from.

### 3. Every table block is vertically compressed (`F27` 0.294, `F32` 0.479, `F31` 0.376)

The grids are drawn correctly — right columns, right merges, right shading —
but our rows are visibly shorter than Hancom's, so nothing lines up
vertically.

*Mechanism guess.* Row height is taken from content (max over cells) and the
declared `hp:cellSz@height` of 2400 HWPUNIT is not treated as a floor. This
matches `own-render-notes.md`'s own description of `solve_tracks`.

> **Half of it was registration, not row height.** The `hp:outMargin` inset
> (#211) moved every table box by the object's own outer margin, and these
> three features gained most of what the convergence gained: `F27`
> 0.154 → 0.294 (still `differs`), `F32` 0.205 → 0.479 and `F31`
> 0.222 → 0.376 (both now `close`). The heading numbers above are the
> post-convergence ones. What is left is genuinely row height — the rows are
> still short, they are simply no longer short *and* offset.

### 4. `F49` 다단 — 2단 구역 (IoU 0.150)

We honour `hp:colPr@colCount=2` and lay the section out in two columns.
Hancom renders the same section full width. Both engines kept
`colCount="2"` through the COM round-trip, so they disagree about when the
control takes effect, not about what it says.

*Mechanism guess.* The `hp:colPr` control sits in the same run as `hp:secPr`
at the head of the section. Hancom likely requires a column definition to be
established by a column break or a section restart before it applies to the
paragraphs that follow. The catalog's expectation was the opposite of what was
measured — it lists 다단 as declared-skipped by our renderer — so this row of
the catalog needs updating.

### 5. `F50` 머리말 / `F51` 꼬리말 (IoU 0.153 / 0.156)

Both are drawn — contradicting the catalog, which lists header/footer as
declared-skipped — but ours sits noticeably to the right of Hancom's.

*Mechanism guess.* The header/footer `hp:subList` declares its own
`textWidth`; centring against the page box rather than against that declared
width would shift the text right by half the margin difference, which is what
the strips show. `F51` is additionally marked `unsupported` because the
`hp:autoNum` field inside the footer is in `elements_skipped` with "nothing
drawn"; the `hp:pageNum` control beside it *is* drawn, so the page number
appears but the field does not.

### 6. Typography knobs that read `differs`

`F13` 자간 over-condenses: the `hh:spacing="-15"` run collides its glyphs
where Hancom merely tightens them, which reads like a unit mismatch in the
1/100-em conversion rather than a missing feature. `F14` 장평, `F15` relSz and
`F16` offset are all drawn and all displaced; `F06`–`F08` line spacing is
applied but with our own line heights, so the block drifts. None of these is
missing — they are the line-metric gap `own-render-notes.md` already names as
backlog #3.

### 7. Reference-side limits, not renderer limits

`F48` 구역 나누기 — 가로 용지 is scored against a **portrait** reference:
Hancom's PDF export emits every page at 595×841 pt even though the section
declares landscape A4 (84188×59528 HWPUNIT) and the COM round-trip preserves
it. We emit 1123×794. The verdict for this feature measures the export path,
not the renderer, and cannot be improved from the renderer side.

Hancom's own `PageCount` reports 10 for a PDF it exports as 9 pages; the
export is complete (every section, page numbers 1–9), so the extra page is
Hancom's count, not lost content.

### 8. Declared limits the report carries but does not penalise

`hh:{left,right,top,bottom}Border@type` `DASH`, `DOT` and `DOUBLE_SLIM` are
all "stroked as solid" (`F31`); `hp:equation` is laid out from its
`hp:script` with identifier tokens approximated (`F36`–`F39`, and `F36`
분수 is the document's one `match`); `hp:pic@pos` places the anchored image at
its declared offset without wrapping text around it (`F35`). These are named
limits on elements that *are* on the page, so those features keep a real
pixel verdict.

`hp:rect` (`F45` 글상자) is the one genuine placeholder: a grey box at the
declared extent, with the text inside not rendered.

## Pre-existing renderer findings, listed not fixed

This pass measures; it changes nothing in the renderer. In backlog order by
size of the gap:

1. ~~Table start/split policy — a table that does not fit is split in place
   rather than moved (`F47`).~~ **Measured and fixed** —
   [table-page-break-rule.md](table-page-break-rule.md). With it out of the
   way, item 7 below is the whole of the remaining page-count gap, and it
   grew rather than shrank: the candidate now runs 11 pages to Hancom's 9,
   because the extra page and the unmoved table used to cancel out.
2. Table row height ignores the declared `hp:cellSz@height` floor
   (`F27`, `F28`, `F31`, `F32`). Half of what this item was worth turned out
   to be the `hp:outMargin` offset, now fixed (#211); `F31` and `F32` read
   `close` on the residual, `F27` and `F28` still `differs`.
3. `hp:colPr` applied from the head of the section where Hancom does not
   (`F49`).
4. Header/footer horizontal placement (`F50`, `F51`).
5. `hh:spacing` over-condenses on negative values (`F13`).
6. `hp:autoNum` has no handler, so a page-number *field* inside a footer draws
   nothing (`F51`).
7. Cumulative block-height drift, one page over nine (note 1).

Two catalog rows are contradicted by measurement and should be corrected
there: 머리말/꼬리말 and 다단 are both listed as declared-skipped, and both are
drawn.

## Not proven

- **One document, one build.** Every number here comes from a single
  synthetic document rendered once by one Hancom build. Nothing is claimed
  about real-world documents, and no holdout document has been scored.
- **The thresholds are not ratified.** They were fitted to this document's
  spread to make it rank; a second document may need different bounds, and
  moving them must be a deliberate, separate decision.
- **The mechanisms above are guesses.** Each is consistent with the strips and
  with the renderer's own notes, but none was confirmed by reading or
  instrumenting the renderer — that was out of scope for this pass.
- **Font substitution is the ceiling and was not isolated.** All three
  declared faces (바탕 · 돋움 · 궁서) do resolve on the measuring machine —
  `batang.ttc` and `gulim.ttc`, checked against `SystemFontIndex` — so the
  comparison is not across two arbitrary typefaces. It is still not the same
  rasteriser or the same hinting as Hancom's, and how much of each `close`
  verdict is shaping and how much is layout stays unmeasured. The bundled
  fallback tier (#208) is therefore untested by this document: it is never
  reached.
- **`ssim_inked` is reported but uninterpreted.** It is negative on one
  table feature (`F27`), which is a legitimate SSIM outcome on anti-correlated
  blocks, but no meaning is attached to the magnitude here.
- **The convergence deltas are attributed, not isolated per slice by
  re-render.** `F47` was measured on the table-move head alone (1 · 33 · 15 ·
  2); `F31`/`F32` moved only once registration joined it, and no run isolates
  registration from fonts — the fonts tier is a proven no-op here, which is
  what makes the attribution safe.
