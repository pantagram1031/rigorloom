# Residual advance error and ink delta — checkpoint-02 follow-up

Status: RESEARCH. Answers the two questions checkpoint-02 raised against
`engine/references/own-render-notes.md`'s advance section ("moel-2013/2025
still fill 0.89/0.91 — second smaller term, likely 한양 faces") and the
kstartup `ink_delta_abs_max` 0.0621 line. Measurement + docs only — no
renderer code changed. Corpus-only: every figure below comes from the ten
public `tests/corpus/forms/` fixtures and their Hancom reference PDFs; the
three 0.707-scale references (gianmun-1ho, gianmun-2ho, nrf) are excluded per
`render_scoreboard.py`'s own geometry-scale rule. Scripts used to produce the
numbers below live under the session scratchpad, not in this repo, per the
task's instruction to keep them out of the tree.

**Machine caveat** (own_render.py's own documented behaviour, not new here):
every number in this report depends on which faces are installed on the
measurement machine. This machine has real HY-series faces (H2MJSM.TTF,
H2GTRM.TTF, H2GTRE.TTF) under `C:\Windows\Fonts`, so `한양신명조`/`한양중고딕`
*resolve* here — that is itself one of this report's findings, since the
private notes speculated the opposite without having checked.

---

## Q1 — which glyph class carries the 0.89/0.91 residual fill on moel-2013/2025

### Method

Reused `engine/tests/test_own_render.py::_unstretched_span_advances` /
`_glyph_class` / `test_no_glyph_class_is_measured_more_than_a_hundredth_of_
an_em_out` verbatim (same PyMuPDF `rawdict` glyph-origin-delta method, same
"every Hangul cell in the span measures exactly 1.000 em" filter), restricted
to the two moel reference PDFs, and additionally split by the PDF-reported
face name (`span["font"]`) instead of collapsing straight to class. For each
face, `own_render.SystemFontIndex.lookup()` was run to record whether this
machine resolves it or falls back to the substitute (`resolve_fonts()` ->
Malgun Gothic on this machine, no vendored Pretendard and no
`RIGORLOOM_OWN_RENDER_FONT` pin).

### Declared vs. rendered vs. resolved face, per form

The two forms' `header.xml` declare `한양신명조` and `한양중고딕` among many
other faces, but the *actual* PDF-reported fonts used for the runs the reader
sees are dominated by one face neither `header.xml` census suggested up front:

| form | PDF-reported face | characters | share | resolves on this machine? |
| --- | --- | --- | --- | --- |
| moel-2013 | Dotum | 4655 | 59.6% | yes -> `gulim.ttc` |
| moel-2013 | **휴먼명조 (Human Myeongjo)** | **2406** | **30.8%** | **no -> substituted with Malgun Gothic** |
| moel-2013 | T2/T3/T4/T5/T6 (embedded CID subsets) | 657 | 8.4% | n/a (subset fonts, not looked up) |
| moel-2013 | DotumChe | 65 | 0.8% | yes -> `gulim.ttc` |
| moel-2013 | H2gtrE (HY견고딕) | 31 | 0.4% | yes -> `H2GTRE.TTF` |
| moel-2025 | **휴먼명조 (Human Myeongjo)** | **3550** | **54.6%** | **no -> substituted with Malgun Gothic** |
| moel-2025 | MalgunGothic / MalgunGothicBold | 1315 | 20.2% | yes -> `malgun.ttf` / `malgunbd.ttf` |
| moel-2025 | T2/T4/T5/T6/T9/T10/T11 (CID subsets) | 928 | 14.3% | n/a |
| moel-2025 | HYwulM (HY울릉도M) | 110 | 1.7% | **no -> substituted** |

`한양신명조`/`한양중고딕` themselves never appear as a PDF-reported face on
either form — they are declared in `header.xml` but not exercised by any run
these two reference PDFs actually draw text with. The one genuinely-declared
한양 face that *is* exercised, HY견고딕 (as `H2gtrE`), resolves correctly and
is 0.4% of moel-2013's characters. The one unresolved 한양-family face,
HY울릉도M, is 1.7% of moel-2025. **Neither is large enough to explain an
11-15% fill deficit.** The dominant unresolved face by character volume is
휴먼명조 — not a 한양 face at all, and not the one the notes flagged.

### Per-class, per-face advance error (unstretched-span gate, restricted to the two moel forms)

| form | class | face | n spans | n chars | median err (em) | mean err (em) |
| --- | --- | --- | --- | --- | --- | --- |
| moel-2013 | space | Dotum | 1 | 274 | +0.0059 | +0.0059 |
| moel-2013 | digit | Dotum | 3 | 7 | -0.0039 | -0.0050 |
| moel-2013 | latin | Dotum | 14 | 30 | -0.0016 | -0.0023 |
| moel-2013 | ascii-punct | Dotum | 8 | 73 | -0.0014 | -0.0020 |
| moel-2013 | hangul | Dotum | 73 | 189 | -0.0003 | -0.0002 |
| moel-2013 | space | 휴먼명조 | 1 | 21 | -0.0001 | -0.0001 |
| moel-2025 | ascii-punct | MalgunGothicBold | 1 | 2 | +0.0536 | +0.0536 |
| moel-2025 | other | MalgunGothicBold | 2 | 2 | +0.0109 | +0.0109 |
| moel-2025 | space | MalgunGothic | 1 | 25 | -0.0060 | -0.0060 |
| moel-2025 | digit | MalgunGothic | 9 | 76 | -0.0035 | -0.0034 |
| moel-2025 | ascii-punct | MalgunGothic | 1 | 4 | +0.0019 | +0.0019 |
| moel-2025 | hangul | MalgunGothic | 9 | 39 | -0.0003 | -0.0002 |
| moel-2025 | space | 휴먼명조 | 1 | 15 | -0.0001 | -0.0001 |

Class-only rollup (char-weighted mean, same aggregation the existing gate
uses):

| form | class | n chars | weighted mean err (em) |
| --- | --- | --- | --- |
| moel-2013 | space | 295 | +0.0054 |
| moel-2013 | digit | 7 | -0.0049 |
| moel-2013 | ascii-punct | 73 | -0.0030 |
| moel-2013 | latin | 30 | -0.0012 |
| moel-2013 | hangul | 189 | -0.0002 |
| moel-2025 | ascii-punct | 6 | +0.0191 |
| moel-2025 | space | 40 | -0.0038 |
| moel-2025 | digit | 76 | -0.0034 |
| moel-2025 | hangul | 43 | -0.0000 |

**Every row is inside the existing ±0.01 em gate** except moel-2025's
`ascii-punct` (+0.019 em, n=6 — a MalgunGothicBold outlier on 2 characters,
not statistically meaningful) and `latin`/`digit` at low single digits of
milli-em. **No class, on either form, shows an error of the size (10-15% of
an em, repeated across a majority of characters) that would explain a
0.89/0.91 fill on its own.** H2gtrE, HYwulM, DotumChe and the T-series CID
subsets contribute **zero** pairs to this table — every one of their spans
failed the "every Hangul cell is exactly 1.000 em" filter, so the gate cannot
see them at all.

### Why the gate measures almost nothing on the dominant face — and what that implies

Only 68 of 휴먼명조's 2406 characters in moel-2013 (2.8%) and 62 of 3550 in
moel-2025 (1.7%) pass the "unstretched span" filter. Directly substituting
Malgun Gothic (what `own_render.py` actually does for this face, rather than
skipping it as the gate does) and measuring against Hancom's own advances for
that filtered slice still gives essentially zero error (moel-2013: hangul
median -0.0003 em/47 chars, space -0.0001 em/21 chars, overall -0.0002 em
weighted over 68 chars; moel-2025: the same shape, -0.0002 em over 62 chars).
**Hangul full-width cells are ~invariant across CJK faces by design, so a
face-substitution error is structurally invisible on the "unstretched" slice
regardless of which face substitutes for which.**

The excluded 97%+ is not noise. A second measurement — median per-span
Hangul-cell scale, with no 1.000 em filter, over *every* horizontal span —
shows 휴먼명조 is disproportionately compressed relative to the well-resolved
body faces on the same two forms:

| form | face | hangul spans | median scale | p10 scale | share of spans < 0.98 |
| --- | --- | --- | --- | --- | --- |
| moel-2013 | Dotum | 71 | 1.0000 | 0.9891 | 5.6% |
| moel-2013 | 휴먼명조 | 310 | 1.0003 | 0.9308 | **25.2%** |
| moel-2013 | DotumChe | 4 | 0.9331 | 0.9257 | 75.0% |
| moel-2025 | 휴먼명조 | 471 | 1.0003 | 0.8613 | **35.2%** |
| moel-2025 | MalgunGothic | 120 | 1.0000 | 0.9642 | 40.0% |
| moel-2025 | T6 (CID subset) | 53 | 0.9677 | 0.8589 | 90.6% |

휴먼명조 spans are condensed below 0.98 four to six times more often than
Dotum's, and the p10 tail runs to 0.86-0.93 — HWP's 최소 공백/자동 줄임
(auto-condense-to-fit) acting on cells too narrow for the declared text. That
condensing decision is computed from the *substitute*'s (Malgun Gothic's)
natural glyph widths in `own_render.py`, not 휴먼명조's, because the face is
unresolved. Two different-shaped faces reaching "fits in N HWPUNIT" by
different condense ratios is a plausible, spec-grounded mechanism for a
line-wide fill deficit that a flat, single-glyph advance-error gate cannot
see by construction — it only samples the spans that are *not* condensed.

### Verdict

**No single flat glyph-metric-substitution mechanism found in the per-class
advance-error channel** (all measured errors are inside ±0.01 em; the
speculative "한양 face resolution" mechanism is not it — those faces resolve
fine here and barely appear in the actual text of either form). The
data instead points at the *condense/auto-shrink* channel interacting with
the unresolved 휴먼명조 face, a channel this gate's "unstretched span" filter
structurally cannot measure. That is the fix-grounded hypothesis, not a
confirmed mechanism — the next slice below is what would confirm or kill it.

**Next slice (Q1):** add a second gate alongside
`test_no_glyph_class_is_measured_more_than_a_hundredth_of_an_em_out` that,
for spans failing the unstretched filter, computes (a) the condense ratio
Hancom's own render actually applied (already computable — the method above),
and (b) the condense ratio `own_render.py`'s auto-shrink logic would compute
for the same declared cell width using the *resolved/substitute* face's
natural widths, and compares the two. If they diverge specifically on
unresolved-face spans and not on resolved-face spans, that confirms
substitute-glyph-width -> wrong-condense-ratio as the mechanism, and the fix
is either (i) vendoring a metrics-compatible 휴먼명조 clone, or (ii) computing
the condense ratio from the face the *document* declares even when a
different face is substituted for drawing (a metrics-only lookup, no
rasterisation required). If they do not diverge, "no single mechanism" stands
and the fill gap likely needs a different channel (e.g. hh:spacing
interaction, or line-box measurement itself) — state that explicitly rather
than iterating blind.

---

## Q2 — where kstartup's `ink_delta_abs_max` 0.0621 comes from

### Method

Reproduced the `computed` (flow-pass) scoreboard run
(`render_scoreboard.score_form(..., block_layout=BLOCK_LAYOUT_COMPUTED)`,
same call the notes' `kstartup-….computed-e2.5.scoreboard.json` used) at
144 dpi, page size 1191x1684 px. On this machine the run reproduces the same
shape of result the notes report (page count exact, 22/22) but a slightly
different `ink_delta_abs_max` — **0.0556 here vs. 0.0621 in the notes** — the
expected drift from the font-installation dependency `render_scoreboard.py`
documents in its own header. The worst page and its mechanism are the same
family of bug either way.

### Per-page ink delta, worst 8 of 22 pages

| page | ref ink | cand ink | delta | ssim | ssim (inked) | line-IoU mean |
| --- | --- | --- | --- | --- | --- | --- |
| **22** | 0.0562 | 0.0005 | **-0.0556** | 0.767 | 0.170 | 0.144 |
| 20 | 0.0621 | 0.0451 | -0.0169 | 0.624 | 0.033 | 0.074 |
| 7 | 0.0126 | 0.0000 | -0.0126 | 0.919 | 0.161 | 0.000 |
| 6 | 0.0358 | 0.0456 | +0.0097 | 0.607 | 0.183 | 0.061 |
| 2 | 0.0478 | 0.0540 | +0.0062 | 0.775 | 0.176 | 0.658 |
| 18 | 0.0375 | 0.0431 | +0.0056 | 0.766 | 0.234 | 0.820 |
| 16 | 0.0448 | 0.0403 | -0.0046 | 0.776 | 0.245 | 0.600 |
| 19 | 0.0196 | 0.0234 | +0.0038 | 0.878 | 0.214 | 0.855 |

### Top-3 contributors by ink mass

**1. Block-to-page assignment drift — a whole content block lands one page
early and overlaps another's tail (page 22, |Δ|=0.0556, the single largest
page in the document).** Candidate page 22 renders almost nothing but the
trailing "2026년 월 일 / 지원자 ○○○ (인)" signature lines; Hancom's page 22
is a full page — title box ("중소기업 지원사업 통합관리시스템 / 기업(신용)정보
수집·이용·제공 동의서"), two bordered tables, a notice paragraph, *and* the
same signature lines. That entire title+2-table block is present in the
candidate render — but crammed onto the **tail of page 21**, after
"(재)광주테크노파크 원장 귀하", overflowing page 21 well past its normal
extent. Region: grid cells at x[198-595], y[210-1052] on page 22 carry the
biggest deltas (-0.233, -0.222, -0.117, -0.116 em-fraction) — exactly the
title+table band. This is the same mechanism the notes already diagnosed
("a constant two-page offset from block position 48 onward" in the flow
pass's block-to-page mapping): with kstartup's ~165 blocks over 22 pages,
block 48 falls around 29% through the document, i.e. page 6-7 — which is
where the *next* contributor below also lands, and the annex bundle from
roughly page 19 onward (many short sub-forms, one block each) shows the
largest cumulative drift because each misassigned block pushes the next.
Confirmed independently: candidate page 20 ("중복지원 금지사항 확약" /
"청렴서약") and reference page 20 ("개인정보 활용 동의서") are two entirely
different annex sub-forms — the back half of the document is page-shifted,
not just ink-shifted.

**2. Block overflow without a page break — literal glyph-on-glyph overlap
(page 6, concentrated Δ +0.048 to +0.068 across x[198-992], y[631-842]).**
Candidate page 6 draws "○ 성과목표 및 기대효과" and its own table (지표명 /
지표 세부내용 / 창업 후 1·2·3년 columns) starting immediately after "○ 사업비
사용 계획"'s second table — but that second table's own last two rows
("R&D 기획지원" / "합계") are still being drawn in the same vertical space,
so the two blocks' text literally overprints. Hancom's reference page 6 ends
cleanly after "○ 사업비 사용 계획"'s two tables and starts "성과목표" fresh on
the next page. This is a page-break/fit decision, distinct from the block-
position drift above: the renderer did not recognise that the next block no
longer fits the remaining page height and needed a new page.

**3. Table cell shading colour — filled cells where Hancom draws none.** On
the "동의서" tables that block 1 above moved onto candidate page 21, the
label-column cells ("수집·이용목적", "수집·이용항목", "수집·이용기관",
"수집·이용기간", "파기대상 정보", "파기절차 및 방법") render with a light-blue
fill in the candidate. Hancom's reference (page 22) draws the identical table
with plain white/unfilled cells and only black borders. This is a genuine,
separate colour-resolution bug — a `hh:borderFill`/shade-colour value this
tier is applying that Hancom's own render does not. Smaller but real: the
same pages also carry bordered placeholder boxes labelled "도형"
(`own_render.py`'s named stand-in for `rect`/`ellipse`/`line`/`arc`/
`polygon`/`curve`/`connectLine`/`textart` it cannot rasterise — see
`_PLACEHOLDER_LABELS` around line 385) at positions where Hancom's reference
shows no comparable ink at all; these add border-line ink the reference does
not carry, on the same two pages.

### Next slice (Q2)

- **Block-position drift** (contributor 1): the existing diagnosis already
  names the mechanism (`paginate` not restarting `vertpos = 0` after a
  full-page anchored table); this measurement adds that its effect compounds
  through the whole annex tail rather than a single page, so the fix should
  be verified against *all* of pages 19-22, not just the page-count/IoU
  numbers already reported.
- **Block overflow / missing page break** (contributor 2) is a **new** finding
  not in the existing notes — propose a slice that checks, before drawing a
  block, whether its declared height fits the remaining page height under
  `BLOCK_LAYOUT_COMPUTED`, and forces a page break when it does not (or
  traces whether `hh:breakSetting@keepLines` is present on this block and is
  being read but not honoured — `PARAPR_HONORED`/`PARAPR_NOT_HONORED` in
  `own_render.py` should be checked against this specific paragraph).
- **Cell shading colour** (contributor 3) is also **new** — propose tracing
  the `hh:borderFill` this table's label cells declare against what
  `own_render.py`'s fill-colour resolution does with it, on this one table,
  before generalising to a corpus-wide shading gate.

---

## Summary for the goal state

- The private notes' "declared 한양 faces resolve worst" hypothesis for the
  moel fill deficit does not hold on this machine (한양신명조/한양중고딕
  resolve; the actually-dominant unresolved face is 휴먼명조, unrelated to
  the 한양 foundry) and the flat per-glyph advance-error channel measures
  near zero even when substitution is modelled directly. The condense-ratio
  channel is the next place to look, not another pass at glyph metrics.
- kstartup's ink floor failure is not one bug but at least three, of which
  the block-position drift already diagnosed is the largest single
  contributor; block-overflow-without-page-break and cell-shading-colour are
  new, smaller, independently fixable findings from this pass.
