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
| Page count | reference **9**, candidate **9** — exact; see note 1 |
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

**3 match · 38 close · 8 differs · 2 unsupported** over 51 features.

`F49` 다단 is the one row that moved since the line-metrics measurement
(**3 · 37 · 9 · 2**), and it moved because *the document* was fixed, not the
renderer: see note 4. Page agreement is **49/51** — unchanged by the document
fix (which moves no page). Page agreement is now **51/51** and the page
count is **exact** — see the endnote-placement measurement at the end of
note 1.

Measured on the E2 line-metrics tree (`claude/engine-e2-line-metrics`), which
adds the character- and line-metric rules of
[line-and-character-metrics.md](line-and-character-metrics.md) to the converged
tree. That page is the measurement; this one is what it was worth. Five
features moved off `differs` and two onto `match` since the converged tree
(**1 · 35 · 13 · 2**):

| feature | before | after | mechanism |
|---|---|---|---|
| `F17` 진하게 | IoU 0.129 `differs` | IoU 0.655 `close` | the paraPr margin unit — the two engines now keep the same paragraph on the same page, so the band is no longer 20 px against 77 |
| `F28` 표 — 셀 병합 | IoU 0.137 `differs` | IoU 0.613 `close` | same, and for the same reason |
| `F16` 글자 위치 | IoU 0.211 `differs` | IoU 0.435 `close` | `hh:offset` was drawn with the sign inverted and off the relSz-scaled size |
| `F14` 장평 | IoU 0.345 `differs` | IoU 0.385 `close` | `hh:relSz`/`hh:ratio` left the line height, so the block band stopped drifting |
| `F27` 표 — 기본 격자 | IoU 0.294 `differs` | IoU 0.338 `close` | the margin unit, again — registration, not row height |
| `F22` 아래첨자 | IoU 0.524 `close` | IoU 0.558 **`match`** | `hh:offset` sign |
| `F32` 표 — 셀 세로 정렬 | IoU 0.479 `close` | IoU 0.647 **`match`** | the margin unit |

One moved the other way: `F35` 그림 — 어울림 (IoU 0.317 `close` → 0.117
`differs`), whose anchored image now lands on a page Hancom does not put it on.
That is the page-count gap of note 1, not a wrapping change.

Means over the 51 features: `ssim` 0.7918 → **0.8073**, `ssim_inked` 0.1396 →
**0.1739**, IoU 0.3728 → **0.4104**. Page agreement fell from 45/51 to
**41/51**: the correct (larger) paragraph margins push more content down, and
`F34`, `F42`, `F43` and `F44` joined `F35`, `F46`–`F49` on the wrong side of a
page boundary. The candidate still runs 11 pages to Hancom's 9.

> **The object line box landed, and the table above carries its numbers.**
> [object-line-box.md](object-line-box.md) walks section 0 block by block
> against the reference and finds the mechanism: the paragraph's `PERCENT`
> line spacing was being applied to an inline object's own extent, so a 72 pt
> table on a 160% paragraph claimed 115.2 pt of the column, and the object's
> vertical `hp:outMargin` was missing from the line box. Both are measured
> against the authoring engine's cached `hp:lineseg` (79/79 exact for the box,
> 66/79 for the leading). Page agreement 41/51 → **47/51** and IoU
> 0.4104 → **0.4139**; `F28` reaches `match`, and `F34`, `F35`, `F42`–`F45`
> come back onto Hancom's page. `ssim` slips 0.8073 → **0.7988** and `F32`
> gives up its `match` (IoU 0.647 → 0.509) while its band goes from 162 px to
> the reference's own 126 and its top from 0.088 of the page height away to
> 0.0003 — the padded-band metric was rewarding a band too tall to be right.
> The page count did **not** move, and note 1 below now names what is left.

> **The equation extent landed too, and the table above carries its numbers.**
> [equation-line-box.md](equation-line-box.md) shows Hancom sizes an inline
> `hp:equation`'s slot to its own layout of the script and not to the declared
> `hp:sz@height`. Page agreement 47/51 → **49/51**, IoU 0.4139 → **0.4176**,
> `ssim_inked` 0.1726 → **0.1761**, `ssim` 0.7988 → 0.7984, tally unchanged at
> 3 · 37 · 9 · 2 — and the **page count moves for the first time, 11 → 10**
> against Hancom's 9.

| feature | ssim | ssim(inked) | IoU | ink Δ | page | verdict |
|---|---|---|---|---|---|---|
| `F01` [정렬 — 왼쪽 (align LEFT)](render-check-01/F01.png) | 0.702 | 0.096 | 0.360 | +0.0236 | 1 | **close** |
| `F02` [정렬 — 가운데 (align CENTER)](render-check-01/F02.png) | 0.702 | 0.118 | 0.415 | +0.0240 | 1 | **close** |
| `F03` [정렬 — 오른쪽 (align RIGHT)](render-check-01/F03.png) | 0.701 | 0.105 | 0.416 | +0.0240 | 1 | **close** |
| `F04` [정렬 — 양쪽 (align JUSTIFY)](render-check-01/F04.png) | 0.700 | 0.116 | 0.391 | +0.0244 | 1 | **close** |
| `F05` [정렬 — 배분 (align DISTRIBUTE)](render-check-01/F05.png) | 0.703 | 0.142 | 0.417 | +0.0249 | 1 | **close** |
| `F06` [줄간격 — 130% (PERCENT)](render-check-01/F06.png) | 0.564 | 0.103 | 0.375 | +0.0361 | 1 | **differs** |
| `F07` [줄간격 — 160% (PERCENT)](render-check-01/F07.png) | 0.619 | 0.117 | 0.376 | +0.0312 | 1 | **differs** |
| `F08` [줄간격 — 200% (PERCENT)](render-check-01/F08.png) | 0.621 | 0.118 | 0.386 | +0.0346 | 1 | **differs** |
| `F09` [줄간격 — 고정 24pt (FIXED)](render-check-01/F09.png) | 0.745 | 0.076 | 0.358 | +0.0225 | 2 | **close** |
| `F10` [첫줄 들여쓰기 (first-line indent)](render-check-01/F10.png) | 0.707 | 0.073 | 0.349 | +0.0241 | 2 | **close** |
| `F11` [내어쓰기 (hanging indent)](render-check-01/F11.png) | 0.680 | 0.104 | 0.335 | +0.0239 | 2 | **close** |
| `F12` [좌우 여백 (left/right margin)](render-check-01/F12.png) | 0.681 | 0.098 | 0.365 | +0.0241 | 2 | **close** |
| `F13` [자간 (hh:spacing −15 / 0 / +30)](render-check-01/F13.png) | 0.648 | 0.075 | 0.368 | +0.0251 | 2 | **differs** |
| `F14` [장평 (hh:ratio 50 / 100 / 150)](render-check-01/F14.png) | 0.696 | 0.133 | 0.385 | +0.0247 | 2 | **close** |
| `F15` [상대 크기 (hh:relSz 60 / 100 / 140)](render-check-01/F15.png) | 0.642 | 0.157 | 0.415 | +0.0173 | 2 | **differs** |
| `F16` [글자 위치 (hh:offset +40 / 0 / −40)](render-check-01/F16.png) | 0.707 | 0.142 | 0.435 | +0.0246 | 2 | **close** |
| `F17` [진하게 (bold)](render-check-01/F17.png) | 0.887 | 0.344 | 0.655 | +0.0146 | 2 | **close** |
| `F18` [기울임 (italic)](render-check-01/F18.png) | 0.813 | 0.151 | 0.454 | +0.0148 | 3 | **close** |
| `F19` [밑줄 (underline)](render-check-01/F19.png) | 0.806 | 0.127 | 0.429 | +0.0199 | 3 | **close** |
| `F20` [취소선 (strikeout)](render-check-01/F20.png) | 0.797 | 0.106 | 0.447 | +0.0135 | 3 | **close** |
| `F21` [위첨자 (superscript)](render-check-01/F21.png) | 0.896 | 0.255 | 0.554 | +0.0077 | 3 | **close** |
| `F22` [아래첨자 (subscript)](render-check-01/F22.png) | 0.916 | 0.161 | 0.555 | +0.0084 | 3 | **match** |
| `F23` [글꼴 — 바탕 (declared face 바탕)](render-check-01/F23.png) | 0.783 | 0.105 | 0.418 | +0.0175 | 3 | **close** |
| `F24` [글꼴 — 돋움 (declared face 돋움)](render-check-01/F24.png) | 0.801 | 0.161 | 0.484 | +0.0092 | 3 | **close** |
| `F25` [글꼴 — 궁서 (declared face 궁서)](render-check-01/F25.png) | 0.807 | 0.204 | 0.501 | +0.0012 | 3 | **close** |
| `F26` [글자 크기 8 / 10 / 12 / 14 / 18 / 24 pt](render-check-01/F26.png) | 0.859 | 0.213 | 0.444 | +0.0085 | 3 | **close** |
| `F27` [표 — 기본 격자 (plain grid 3×3)](render-check-01/F27.png) | 0.810 | 0.352 | 0.338 | +0.0224 | 3 | **close** |
| `F28` [표 — 셀 병합 (colSpan 2 + rowSpan 2)](render-check-01/F28.png) | 0.945 | 0.276 | 0.613 | +0.0060 | 3 | **match** |
| `F29` [표 — 셀 음영 (cell shading #D9D9D9)](render-check-01/F29.png) | 0.725 | 0.413 | 0.555 | +0.0104 | 4 | **close** |
| `F30` [캡션 — 표 (table caption)](render-check-01/F30.png) | 0.921 | 0.364 | 0.529 | +0.0120 | 4 | **close** |
| `F31` [표 — 테두리 종류 (SOLID / DASH / DOT / DOUBLE / 굵기)](render-check-01/F31.png) | 0.667 | 0.123 | 0.431 | +0.0237 | 4 | **close** |
| `F32` [표 — 셀 세로 정렬 (TOP / CENTER / BOTTOM)](render-check-01/F32.png) | 0.805 | 0.094 | 0.510 | +0.0083 | 4 | **close** |
| `F33` [그림 — 본문 안 (inline, treatAsChar)](render-check-01/F33.png) | 0.838 | 0.353 | 0.497 | +0.0057 | 4 | **close** |
| `F34` [캡션 — 그림 (image caption)](render-check-01/F34.png) | 0.833 | 0.117 | 0.455 | +0.0144 | 4 | **close** |
| `F35` [그림 — 어울림 TOP_AND_BOTTOM (anchored, text wrap)](render-check-01/F35.png) | 0.675 | 0.212 | 0.227 | +0.0056 | 4 | **differs** |
| `F36` [수식 — 분수 (fraction)](render-check-01/F36.png) | 0.954 | 0.285 | 0.597 | +0.0047 | 5 | **match** |
| `F37` [수식 — 근호 (sqrt)](render-check-01/F37.png) | 0.932 | 0.253 | 0.481 | +0.0057 | 5 | **close** |
| `F38` [수식 — 총합·상하한 (sum with limits)](render-check-01/F38.png) | 0.880 | 0.177 | 0.434 | +0.0115 | 5 | **close** |
| `F39` [수식 — 행렬 (matrix)](render-check-01/F39.png) | 0.924 | 0.126 | 0.436 | +0.0062 | 5 | **close** |
| `F40` [개요 번호 — 3수준 (numbered outline, 1. / 1.1 / 1.1.1)](render-check-01/F40.png) | 0.859 | 0.109 | 0.322 | +0.0096 | 5 | **close** |
| `F41` [글머리표 (bullets)](render-check-01/F41.png) | 0.880 | 0.175 | 0.405 | +0.0076 | 5 | **close** |
| `F42` [각주 (footnote)](render-check-01/F42.png) | 0.837 | 0.145 | 0.467 | +0.0134 | 5 | **close** |
| `F43` [미주 (endnote)](render-check-01/F43.png) | 0.862 | 0.166 | 0.462 | +0.0134 | 5 | **close** |
| `F44` [하이퍼링크 (hyperlink field)](render-check-01/F44.png) | 0.864 | 0.240 | 0.476 | +0.0223 | 5 | **close** |
| `F45` [글상자 / 그리기 개체 사각형 (text box)](render-check-01/F45.png) | 0.854 | 0.516 | 0.174 | -0.0083 | 5 | **unsupported** |
| `F46` [쪽 나누기 (page break, pageBreakBefore)](render-check-01/F46.png) | 0.798 | 0.200 | 0.524 | +0.0190 | 6 | **close** |
| `F47` [표 — 쪽을 넘기는 표 (table split across a page)](render-check-01/F47.png) | 0.993 | 0.240 | 0.535 | +0.0008 | 6 | **close** |
| `F48` [구역 나누기 — 가로 용지 + 다른 여백 (section break, landscape)](render-check-01/F48.png) | 0.947 | 0.084 | 0.288 | +0.0036 | 8 | **differs** |
| `F49` [다단 — 2단 구역 (two-column section)](render-check-01/F49.png) | 0.864 | 0.111 | 0.344 | +0.0092 | 9 | **close** |
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

> **The first contribution is gone, and the drift is not.** Block heights and
> paragraph gaps were measured off the reference PDF
> ([line-and-character-metrics.md](line-and-character-metrics.md)) and both are
> now exact: on pages 1–2 every feature band starts within 0.0002 of the page
> height of Hancom's and `F06`/`F07`/`F08` measure 121/121, 140/140 and 94/94
> px against Hancom's own bands. The `F17` and `F28` page-boundary artefacts
> named above are gone with them (both now `close`, IoU 0.655 and 0.613). The
> page count is still 11 against 9, and page agreement went **down**, 45/51 to
> 41/51, because the correct — larger — 문단 위/아래 간격 pushes more content
> past each boundary: `F34`, `F42`, `F43` and `F44` joined the disagreeing set.
> Whatever is left is a pagination rule, not a metric.

> **It was not a pagination rule — it was the line box an inline object
> claims, and it is measured and fixed**
> ([object-line-box.md](object-line-box.md)). Walking section 0 block by block
> against the reference text layer, the first 48 blocks agree to within
> 0.50 pt; the first real gap is `F24`'s body paragraph, where our line
> breaker fits on one line what Hancom takes two for — 16 pt the *wrong* way
> for a page-count gap, and pre-existing. The block after it is the mechanism:
> every inline object claimed its own height **times the paragraph's
> line-spacing percent**, and was missing its own vertical `hp:outMargin`.
> `F27`'s 72 pt table advanced 115.20 pt where Hancom advances 80.73; the two
> rules together predict 80.82. Page agreement 41/51 → **47/51**.
>
> **The page count still did not move, and the residual is now named.** With
> the object lines right, section 0 runs 8 pages to Hancom's 7 and the whole
> of that page is the four `hp:equation` blocks: an equation takes its inline
> slot from the declared `hp:sz@height`, and Hancom lays the equation out
> itself and gets 2252 / 1304 / 2696 / 2108 against the declared
> 2400 / 2400 / 3600 / 3600 — 36.4 pt of drift over four blocks, exactly what
> pushes `F45` off page 4. The other extra page is note 4's two-column
> section, which Hancom renders full width on one page. Neither is a
> pagination rule; both are object-extent questions, and both are follow-ups.
>
> **The equation half is measured and closed.** Hancom reserves its own
> layout of the `hp:script`, not the declared `hp:sz@height` — the same
> declared 2400 reserves 2252 for `a over b` and 1304 for a square root, and
> no attribute distinguishes the two documents that disagree about whether
> the stored extent is honoured
> ([equation-line-box.md](equation-line-box.md)). With
> `min(declared, max(nominal, ink))` off this renderer's own layout tree the
> drift over the four blocks is 4.7 pt, the **page count moves 11 → 10**
> against Hancom's 9, page agreement 47 → **49 / 51**, `iou` mean
> 0.4139 → **0.4176** and `ssim_inked` 0.1726 → **0.1761**; `F37` `iou`
> 0.423 → 0.481, `F38` 0.337 → 0.434, `F39` 0.419 → 0.436. `F46` and `F47`
> come back onto Hancom's page. The table above carries the post-fix numbers.
> The one page left in section 0 is 4.7 pt of unattributed block drift;
> note 4's two-column section is the other.

> **Neither guess was right, and the last page is measured and closed.** It
> was not block drift and not the two-column section: it was **where an
> endnote is set**. Every section of this document declares
> `hp:endNotePr/hp:placement@place="END_OF_DOCUMENT"`, and the one
> `hp:endNote` is authored in section 0. This renderer read
> `END_OF_DOCUMENT` and `END_OF_SECTION` as the same thing — the end of the
> section that authors the note — so it set the note at the end of section 0,
> where the `F47` table already overflows the body box, and gave it a page of
> its own. That page WAS the gap. Hancom sets the same note on page 9 of 9,
> the last page of the document (section 2's only page), under that page's
> last inked line: separator at y=464.5 pt, note body at y=470.5–478.5 pt,
> the last body line ending at 456.3 pt. With `END_OF_DOCUMENT` deferred to
> the last section, the candidate is **9 pages against Hancom's 9 — exact for
> the first time** — section 0 runs 7 pages to Hancom's 7, page agreement
> 49 → **51 / 51**, and the tally is unchanged at 3 · 38 · 8 · 2. `F49`'s
> band now ends where the endnote begins rather than at the foot of the body
> box, which is the whole of `iou` 0.4217 → 0.4214 and `ssim` 0.7994 →
> 0.7993. What Hancom does that this renderer still does not: it sets the
> note in the **first column** of the two-column section (separator
> x 85.0–297.7 pt, one column wide), where we set it at the body box's full
> width. That is a width difference on one line, not a page-count one, and it
> is declared rather than fixed here.

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

> **And most of the rest was the paragraph-margin unit.** With
> `line-and-character-metrics.md` §6 the table blocks land where Hancom puts
> them vertically as well: `F27` 0.294 → 0.338 (`close`), `F28`
> 0.137 → 0.613 (`close`), `F31` 0.376 → 0.419, `F32` 0.479 → 0.647
> (**`match`**). Twice now this heading's "row height" has turned out to be
> registration; whatever row-height error remains is below what this document
> separates from the rasteriser, and the item should not be re-attacked as row
> height without a probe that measures a row directly.

### 4. `F49` 다단 — 2단 구역 (IoU 0.141 → 0.355, `differs` → `close`)

**The document was malformed; the renderer was right.** This item used to read
"we lay the section out in two columns, Hancom renders it full width". It was
measured, and the disagreement was not about columns at all — it was about
where the `hp:colPr` control sits in the section-head paragraph.

Two probe documents (one section per case, Hwp 2024 13.0.0.2986, PDF export
read back for the x-extent of the text — `colCount="2"` in every case):

| case | section-head control order | Hancom renders |
|---|---|---|
| `P1` | `secPr`, header, footer, `colPr` `sameGap=0` | one column |
| `P2` | `secPr`, header, footer, `colPr` `sameGap=1134` | one column |
| `P3` | `secPr`, header, footer, `colPr` `sameSz=0` + 2×`colSz` | one column |
| `P6` | `secPr`, header, footer, `colPr` `BALANCED_NEWSPAPER` | one column |
| `P7` | `secPr`, header, footer, `colPr` `sameSz="true"` | one column |
| `Q1` | `secPr`, header, `colPr`, footer | one column |
| `Q3` | `secPr`, footer, `colPr` | one column |
| `Q2` | `secPr`, `colPr` | **two columns** |
| `P4`/`Q4` | `secPr`, `colPr`, header, footer | **two columns** |
| `P5` | `secPr`, header, footer; `colPr` in the *next* paragraph | **two columns** |

So none of the attribute candidates matters. `type`, `layout`, `sameSz`,
`sameGap` and explicit `hp:colSz` children all behave the same on both sides
of the line; what decides it is that **Hancom ignores an `hp:colPr` that any
header or footer control precedes inside the section-head paragraph**. It
honours one that comes straight after `hp:secPr` (`Q2`, `Q4`), and it honours
one carried by a later paragraph (`P5`) — the furniture controls of the
*section head* are the whole mechanism.

`render-check-01` emitted the `P1` order, so Hancom was right to render `F49`
full width: the document declared a column definition in a position that does
not take effect. `build_render_check.sec_pr` now emits `secPr`, `colPr`,
furniture; the document, its reference PDF and their manifest hashes are
re-pinned on that. `own_render`'s column logic is unchanged — it was already
laying the section out the way Hancom does once the document says so.

What was left in this row was the pagination drift of note 1, not columns,
and that is closed too: `F49` now lands on page 9 in both engines. It reads
`close` rather than `match` on its band, not on its page — Hancom sets the
document's endnote inside `F49`'s own column and we set it at full body
width, so the band's foot differs by one line.

### 4a. `F06`/`F07`/`F08` 줄간격, `F13` 자간, `F15` 상대 크기 — the rows match and the ink does not

These five are the `differs` rows that survive every layout fix on this page.
Their bands are right: `F06`/`F07`/`F08` measure 121/121, 140/140 and 94/94 px
against Hancom's own bands, their six, six and four lines have baselines that
agree to **0.1 px**, and every one of their 182/182/136 glyphs pairs against
the reference by its own character.

**The residual is our rasteriser's weight, and it is measured rather than
tuned away** ([ink-residual.md](ink-residual.md)). Per glyph, on the same
resolved face and size, our coverage is **1.80×** the reference's at 96 dpi
(dark-pixel count 2.60×, stems 78 % heavier at a 13 px em), falling to 1.16×
at 144 dpi and to ~1.0 by 192. The excess is multiplicative, so a band's ink
delta is its own reference ink fraction times (ratio − 1) — and these are
three of the densest glyph-text bands in the document. The same 1.71–1.83
ratio is measured on `F01`, which reads `close`. Across the 48 inked features
Pearson(band ink fraction, `ssim`) = **−0.801**.

Three other explanations were tested and refuted: no left-side-bearing is
dropped (line origins land within **0.008 px** of the reference's span x), no
face is substituted (돋움 resolves to `gulim.ttc` face **2** = Dotum, and
`substituted_character_share` is 0.0), and the scorer's regions are not
displaced. What did change is the harness's two resolution-dependent bounds,
each an exact no-op at 96 dpi; the tally above is unmoved.

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

*Measured since, and four of the five guesses were wrong in a useful way.*
[line-and-character-metrics.md](line-and-character-metrics.md) reads each of
these rules off the reference PDF's own text layer, one at a time. The heading
and the original text below are kept because they record the state the
measurement was started from.

> `hh:spacing` really was a unit mismatch, but not in the conversion — the gap
> is a percent of the character's **own advance**, not a flat percent of the
> character size, which is why narrow Latin glyphs collided and full-width
> Hangul did not. `hh:offset` was drawn with the **sign inverted** and against
> the relSz-scaled size instead of the declared one. `hh:relSz` was being
> counted **into the line height**, which Hancom does not do. `hh:ratio` and
> the `PERCENT` line pitch were already right — `PERCENT` is `value/100` of the
> declared character size and always was (24 baseline steps, worst residual
> 0.091 pt). What was actually moving `F06`–`F08` was one level down: the
> paraPr MCE switch's `default` branch states every length in half a HWPUNIT,
> so 문단 위/아래 간격 was halved by a constant and `left`/`right`/`intent` were
> read doubled. `F14` and `F16` are now `close`; `F06`–`F08` and `F13`/`F15`
> still read `differs`, but their bands now agree with Hancom's **to the pixel**
> and they fail on `ssim`/`ink Δ` alone — the rasteriser ceiling this page
> already declares unisolated, not layout.

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

Hancom's own `PageCount` reports 10 for a PDF it exports as 9 pages, and
**both numbers are true of the layout each describes.** Read through
Automation (`PageCount`, `GetPageText`, `goto_page` + `KeyIndicator` +
`GetPos` per page), the editing layout is stable at 10 pages before the
export, after forcing a full pagination pass to the end of the document, and
again after the export. Its page 6 holds exactly one paragraph — para 95,
whose caret control name is `사각형` — and that paragraph's only content is
`F45`'s anchored `hp:rect`; page 5 ends at para 71 and page 7 begins at
para 96. The exported PDF puts the same rect on page 5 at y=675.2–684.2 pt,
inside a body box that ends at 756.84 pt, and renumbers nothing: its own
`hp:pageNum` fields evaluate 1–9 with no gap, so the export path laid out
nine pages rather than dropping a tenth. The extra page is therefore a
screen-vs-print divergence in Hancom around one anchored drawing object, not
a trailing empty page and not lost content — the "exporter suppresses a
furniture-only trailing page" hypothesis is **falsified** here, and no
suppression rule was adopted.

This is also not the page this renderer was adding. Ours agreed with the PDF
on `F45` (page 5) and `F46`/`F47` (page 6) all along; our extra page was the
endnote, at the end of note 1. Measuring the two against each other: the
reference PDF is what render-check scores, the editing layout is a second
Hancom answer, and the two disagree with each other by one page on a
document neither engine here authored.

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
   to be the `hp:outMargin` offset, then fixed (#211), and most of the rest was
   the paraPr margin unit (line-and-character-metrics.md §6): all four now read
   `close` or `match`. Whatever row-height error is left is below what this
   document can separate from the rasteriser.
3. ~~`hp:colPr` applied from the head of the section where Hancom does not
   (`F49`).~~ **Measured, and it was the document.** Hancom ignores an
   `hp:colPr` that a header or footer control precedes in the section-head
   paragraph (note 4); `render-check-01` emitted exactly that order.
   `build_render_check` now emits `secPr`, `colPr`, furniture, and `F49` reads
   `close` against a two-column Hancom reference. The renderer was not
   changed, and item 7's pagination drift is closed as well: this row is
   now a band difference only.
4. Header/footer horizontal placement (`F50`, `F51`).
5. ~~`hh:spacing` over-condenses on negative values (`F13`).~~ **Measured and
   fixed** — the gap is a percent of the character's own advance
   ([line-and-character-metrics.md](line-and-character-metrics.md) §3).
6. `hp:autoNum` has no handler, so a page-number *field* inside a footer draws
   nothing (`F51`).
7. ~~Cumulative block drift, two pages over nine, and it is no longer block
   *height*.~~ **Measured and fixed** —
   [object-line-box.md](object-line-box.md): an inline object's line box is
   its extent plus its own vertical `hp:outMargin`, and the paragraph's line
   spacing leads off the run's character size, not off that box. Page
   agreement 41/51 → **47/51**. Two page-count items are left in its place,
   both object extents rather than pagination rules: **`hp:equation` takes its
   inline slot from the declared `hp:sz@height`**, which Hancom's own layout
   disagrees with by 1 to 15 pt per equation and which costs section 0 its
   extra page; and the two-column section of item 3, whose column definition
   Hancom now honours as well, so the page it disagrees on is pagination and
   nothing else. **Both are closed.** The equation extent went first
   ([equation-line-box.md](equation-line-box.md), 11 → 10 pages), and the
   second was not the two-column section at all: it was
   `hp:endNotePr/hp:placement@place`, read as end-of-section where it says
   END_OF_DOCUMENT, which gave section 0's one endnote a page of its own
   (note 1). Page count is now **9 = 9, exact**, and page agreement
   **51/51**.
8. `hh:tabPr`'s stops are never read: the corpus declares them as
   `hh:tabItem` inside the same MCE `hp:switch` the paraPr geometry uses, and
   the reader looks for `hh:tab` outside it, finds none, and falls back to its
   declared default interval. Named by the switch-unit measurement, not fixed
   here.

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
- **The line-metrics deltas are two changes measured as one, with one
  intermediate run.** The character-metric rules alone (자간, `hh:offset`,
  `hh:relSz` out of the line height) score **1 · 35 · 13 · 2**, means `ssim`
  0.7937 / IoU 0.3750: only `F16` moves off `differs`, because every band is
  still drifting. Adding the paraPr switch-unit rule gives the 3 · 37 · 9 · 2
  above. Attribution per feature in the table is by mechanism, not by a
  per-feature isolating run.

- **The endnote rule is one document, one note.** `END_OF_DOCUMENT` is
  honoured by deferring to the last section, measured on a document with one
  endnote authored in the first of three sections. Nothing here measures two
  sections that each carry notes, a document whose last section declares
  `END_OF_SECTION` while an earlier one declares `END_OF_DOCUMENT`, or note
  numbering across such a hand-off — the order is spine order and the numbers
  are each section's own, by construction, not by measurement. No corpus form
  and no holdout carries an endnote at all.
- **The endnote's column is not fixed.** Hancom sets this document's endnote
  inside the first column of the two-column last section (separator
  x 85.0–297.7 pt); we set it at the body box's full width. Measured, named
  in the sidecar, and left — it costs `F49` band accuracy, not a page.
- **Hancom disagrees with itself by one page on this document, and that is
  unexplained.** The editing layout is 10 pages and the export is 9; the
  difference is `F45`'s anchored `hp:rect`, which the editor puts alone on
  its own page and the exporter fits on the previous one. Which layout is
  "right" is not decided here — render-check scores the PDF, so the PDF is
  what the renderer is measured against. Whether the same divergence appears
  on any other document, or on any other Hancom build, is unmeasured.
