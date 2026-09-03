# own_render — format findings, fidelity limits, and the path to certification

`engine/scripts/own_render.py`, renderer id `rigorloom-own/0.1`, grade
`own-uncertified`.

Tier 3 of the render stack: Hancom COM is ground truth where it is installed,
LibreOffice/H2Orestart is advisory, and this is the renderer that is always
available. It is written against OWPML / KS X 6101 — the public XML the
`.hwpx` container carries — and against the corpus files themselves. No Hancom
binary or Hancom source was inspected at any point.

**Nothing this renderer produces may be presented as Hancom-faithful.** Every
run emits `grade: "own-uncertified"` and a named `elements_skipped` list.
Promotion is per document class, through `pipeline/scripts/render_cert.py`.

## Visual evidence

`engine/references/own-render-samples/` holds, for two committed public corpus
forms:

| file | what it is |
| --- | --- |
| `<form>-p1.png` | our render at 144 DPI |
| `<form>.render.json` | the sidecar for that render |
| `<form>-embedded-preview.png` | the **document's own** `Preview/PrvImage.png`, i.e. what the authoring engine drew |
| `<form>.{before-e2.3,after-e2.3,after-e2.2}.scoreboard.json` | the measurement against that form's Hancom reference PDF, at each of the three renderer states |
| `<form>.{before,after,computed}-e2.1.scoreboard.json` | the same measurement across the E2.1 line-breaking slice: before it, after it as it ships (`auto`), and with every line broken by the own breaker (`computed`) |

…plus two corpus-wide artefacts, which are the evidence for E2.1 and cover all
ten forms rather than two:

| file | what it is |
| --- | --- |
| `e2.1-line-breaking.scoreboard-summary.json` | before / after / computed, every form, every scored channel, with the comparable-form means |
| `e2.1-lineseg-agreement.json` | the line breaker measured against each document's own cached `hp:lineseg`, per form and summed |

The embedded preview is there so a human can judge the gap at a glance. It is
a comparison aid, not a measurement — the measurement is the scoreboard
(*Measuring against Hancom*, below); the certificate is `render_cert`.

## Units

`1 HWPUNIT = 1/7200 inch`, `1 pt = 100 HWPUNIT`.

Cited from `engine/scripts/form_inspect.py::_page_metrics`, which states the
same in its docstring, and independently confirmed: every A4 corpus form
declares `<hp:pagePr width="59528" height="84188">`, and
`210 mm = 8.2677 in × 7200 = 59528`.

Border widths are the exception — they are declared as strings in millimetres
(`width="0.12 mm"`) and are converted separately.

## What this slice implements

**Page.** `hp:secPr/hp:pagePr` `@width`/`@height` and `hp:margin`. Usable box
uses the same formula and the same gutter caveat as `form_inspect._page_metrics`
(`gutterType` decides which side the gutter lands on, so it is reported and
never folded in).

**Pagination.** OWPML's cached `vertpos` restarts at the top of every page —
measured across all ten corpus forms, the maximum top-level `vertpos` never
exceeds one usable page height. A page therefore begins where `vertpos` jumps
backwards, with a quarter-page floor so that a duplicated line box is not
mistaken for a page. Resulting page counts: gianmun-1ho/2ho, admrul, jeongbo 1;
jumin 3; nrf 4; moel-2013 7, moel-2025 7; saeopja 6; kstartup 20.
`@pageBreak` is deliberately **not** consulted — on this corpus it also appears
on paragraphs whose `vertpos` does not restart, so honouring it invents pages.

**Line layout — the file's own cache where it still describes the text, this
renderer's own breaker where it does not.**
`<hp:linesegarray><hp:lineseg …/>` carries the line boxes the authoring engine
already computed: `vertpos`, `horzpos`, `horzsize`, `vertsize`, `baseline`, and
`textpos` (the paragraph character offset the line starts at). The renderer
slices the paragraph's character stream by `textpos` and draws each line at its
cached box. Line breaking therefore matches the authoring engine exactly
wherever the cache is present and still describes the paragraph's text — which
is every paragraph of an unedited document.

The moment an edit changes a paragraph's text that cache is stale, and a stale
box is the one thing this renderer must never draw. *Line breaking from
metrics* below is the breaker that takes over, what decides when it takes over,
and exactly how well it agrees with the engine that wrote the file.

Alignment is *not* in the cache — `horzpos` stays 0 and `horzsize` stays the
full column even for a centred line — so horizontal alignment is applied here
from `hh:paraPr/hh:align@horizontal` against the measured content width.

**Tables.** `hp:tbl` → `hp:tr` → `hp:tc`, addressing per the conventions
`engine/scripts/hwpx_tables.py` documents (document order for the table index;
`cellAddr` is the merged cell's top-left grid coordinate; the coordinates a
span covers carry no `tc`). Nested tables recurse.

Column widths and row heights are *solved*, not read: OWPML stores a `cellSz`
per cell, not per track, so a grid whose columns are all covered by merged
cells is underdetermined by the unit-span cells alone. gianmun's 15-column
header table gives only 6 columns directly. `solve_tracks` runs Gauss-style
elimination (repeatedly close any constraint left with one unknown), which
recovers **every** column on the corpus, then distributes the residual against
the table's declared `hp:sz` so the outer box is always exact.

Row heights need one extra rule: `cellSz@height` is a *minimum*. HWP grows a
row to fit its content and leaves the stored value behind — gianmun's body row
stores 4895 and renders 34617. The height taken is
`max(cellSz@height, content_extent + cellMargin.top + cellMargin.bottom)`,
where `content_extent = max(vertpos + vertsize)` over the cell's own
paragraphs' line boxes. **The trailing `spacing` of the last line must be
excluded**: including it inflates single-line cell heights by up to 51% against
the declared table height. With it excluded, reconstructed row sums land within
2% of `hp:sz` on 73 of 81 corpus tables (median error 0.0%).

**Borders and fills.** Real per-side geometry from `hh:borderFill`:
`hh:{left,right,top,bottom}Border` `@type`/`@width`/`@color`, and cell shading
from `hc:fillBrush/hc:winBrush@faceColor`. `type="NONE"` draws nothing — which
matters: gianmun is mostly an *invisible* grid with three horizontal rules and
one grey band, and a renderer that stroked every cell would produce a page that
looks nothing like the form.

**Inline objects.** `hp:pic` is rasterised from `BinData` and `hp:equation` is
laid out from its `hp:script`, both at the declared `hp:sz` extent — see
*Report-class documents* and *Equations* below. Everything else this tier
cannot draw gets a named placeholder box rather than a hole.

### Absent borders on gianmun are the form, not the renderer

Worth writing down because the render *looks* like borders are missing, and the
first instinct is to go fix border drawing.

`gianmun-byeolji-1ho` declares 14 `hh:borderFill` entries; its 34 cells
reference 10 of them. Counting every side of every cell as the file declares
it: **13 sides are `SOLID`, the other 123 are `type="NONE"`.** Nineteen of the
34 cells use `borderFillIDRef="6"`, whose four sides are all `NONE` — that is
the large blank body of the letter.

The render reports `borders: 13`. Declared-solid and drawn agree exactly, so
nothing is being dropped: gianmun is an *invisible layout grid* with three
horizontal rules (ids 7/8/10/13), one grey band (`id 9`, faceColor #C0C0C0)
and one red 직인 box (`id 11`). `Preview/PrvImage.png` — the authoring engine's
own thumbnail, committed next to the sample — shows the same borderless page.

The positive control is `jeongbo-gonggae-cheongguseo`, which does declare a
real grid: 136 borders parsed and drawn, matching its embedded preview.

So border **parsing** was never the refinement target. Against the embedded
preview the real gaps on this form were, in order: `발 신 명 의` rendered tight
where the authoring engine spreads it, and every line ran on the wrong face
because of the substitution. **Both are closed** (see *Character typography*
and *Fonts* below); both were intra-line text metrics, not table geometry.

**Text runs.** Per-run `hh:charPr`: `@height` (÷100 → pt), `@textColor`,
`hh:bold`, `hh:underline@type`, and the four character metrics below.
Underline is drawn because ruled blanks in government forms *are* underline
runs — `form_inspect._is_ruled` and T112 both treat them as load-bearing.

### Character typography (`hh:ratio` / `hh:spacing` / `hh:relSz` / `hh:offset`)

OWPML declares these once per **language slot**
(`<hh:ratio hangul="97" latin="100" hanja="…" japanese="…" other="…"
symbol="…" user="…"/>`), and the slot that applies is the one the character's
script belongs to.

| element | meaning | applied as |
| --- | --- | --- |
| `hh:ratio` | horizontal glyph scale, % | advance scales, and so does the ink: the piece is rasterised to its own mask at natural width, resampled horizontally (LANCZOS, pinned), composited in the run colour |
| `hh:spacing` | letter spacing, % **of the character size** | a gap *between* characters — n−1 per line, no trailing gap |
| `hh:relSz` | relative character size, % | scales the point size before rasterisation |
| `hh:offset` | baseline shift, % of the character size | raises/lowers the glyph, and the recorded line box follows |

Two of those readings were forced by measurement rather than chosen.
gianmun's `발신명의` is `charPr` id 8 — 15 pt, `ratio="100"`, `spacing="50"` —
and Hancom's own render draws that span 58.65 pt at a reported size of
10.67 pt, i.e. **5.496 em**. Four advances plus three half-em gaps is 5.5 em;
four advances plus *four* gaps would be 6.0. So the gap count is n−1, and the
percentage is of the character size rather than of the ratio-scaled advance.
Em is the unit because gianmun's reference PDF is one of the three the
scoreboard rejects as a ~0.707 print reduction — the ratio is scale-free, the
absolute pixels are not. `test_the_spread_run_matches_the_hancom_reference_in_em`
pins it.

**The slot table is ours, not the standard's.** KS X 6101 names the seven slots
and says a character is metered by its script's slot; it does not publish the
codepoint partition, which is an implementing engine's detail. The mapping in
`own_render.script_slot` is the plain Unicode-block reading of the slot names,
and every sidecar declares it as an approximation in
`typography_slot_model`. The `user` slot is **never** selected: HWP fills it
from a user-defined character range table that the document does not carry, so
a renderer reading only the file cannot honour it.

How much the slot model can be trusted from this corpus alone: of the **791**
`charPr` definitions across the ten forms, exactly **3** give one slot a
different value from the others (kstartup 188/189 `ratio`, saeopja 90
`spacing`). The corpus therefore cannot tell a working slot model from a broken
one, which is why the mechanics are pinned with synthetic `charPr` and the
count of 3 is itself pinned by test. `hh:relSz` and `hh:offset` are never
declared away from neutral by any corpus form at all — same situation as
`hp:equation`, and handled the same way: direct unit tests, no invented
fixture.

The sidecar reports what was **applied**, not only what was skipped
(`typography.applied_characters`). "We apply `hh:ratio`" is unfalsifiable on a
document that never declares one; on gianmun the sidecar says 371 characters
spaced, 19 ratio-scaled, 2 lines justified.

## Line breaking from metrics (E2.1)

`own_render.compute_lines` breaks a paragraph into line boxes from font
metrics and `hp:paraPr`, with no reference to the cached layout. It exists
because an edited paragraph has no usable cache, and it is measured against
the cache on unedited paragraphs — the only channel on which a from-scratch
line breaker can be graded without a reference render.

### Which engine laid out which paragraph, and why

Two policies, declared per render in `line_layout.policy`, and per paragraph
in `line_layout.paragraphs_relaid_out`:

- **`auto`** (default, and what ships). A paragraph keeps its cached
  `hp:lineseg` boxes unless they provably no longer describe its text.
- **`computed`** (`--line-layout computed`). Every paragraph is relaid out by
  this breaker. This is how the breaker is *measured*; it is not how a
  document is rendered most faithfully, and the scoreboard below says by how
  much.

Under `auto`, `computed` wins for exactly five named reasons, each counted in
`line_layout.computed_reasons`:

| reason | what it means |
| --- | --- |
| `cache_absent` | the paragraph carries no `hp:linesegarray` at all |
| `textpos_past_end` | a cached line starts past the end of the character stream, so the text is *shorter* than the cache describes |
| `stale_line_width` | a cached line's font-independent lower-bound width exceeds its own cached `horzsize`, so the text is *longer* than that line could hold |
| `caller_marked_edited` | the caller passed the paragraph in `relayout_paragraphs` |
| `policy` | the whole render was asked for computed lines |

`stale_line_width` is the interesting one. The bound counts only full-width
cells (Hangul, Hanja, kana, CJK punctuation, an inline object slot — whose
advance in HWP is exactly the declared character size × `hh:ratio`, whatever
face draws them) plus the declared `hh:spacing` gaps; Latin and spaces
contribute nothing. It can therefore never exceed the width the authoring
engine actually fitted, which makes the detector **sound**: it fires on no
paragraph of any of the ten corpus forms (the worst unedited line reaches
0.901 of its box by this bound, against a 1% tolerance), and
`test_no_unedited_corpus_paragraph_is_judged_stale` asserts that on all ten.

It is also **incomplete**, and the sidecar says so in those words: an edit
that leaves every line still fitting is invisible in the file. An editor that
knows it changed a paragraph must declare it through `relayout_paragraphs`
rather than rely on detection. A paragraph is named there by its document-order
position among every `hp:p` in `section0`, counting from 0 — `hp:p@id` is not
unique (moel-2025 gives `2147483648` to 329 of its 330 paragraphs), and the
caller can compute the ordinal from the same file without asking the renderer.

Every line box in the sidecar carries `mode: "lineseg" | "computed"`, so a
reader can tell per line which engine broke it.

### What the breaker honours

Read off `hp:paraPr` and acted on: `hh:breakSetting@breakLatinWord` and
`@breakNonLatinWord` (`KEEP_WORD` = 어절/단어 단위, `BREAK_WORD` = 글자 단위),
`@lineWrap=BREAK`, `@condense`, `hh:lineSpacing@type` `PERCENT` and `FIXED`
with `@value`, `hh:margin` `left`/`right`/`intent`, `hh:align@horizontal`, and
the explicit `LEFT` stops of `hh:tabPr`. Parsed and **not** acted on, named in
every sidecar: `HYPHENATION`, `@widowOrphan`/`@keepWithNext`/`@keepLines`/
`@pageBreakBefore` (block-level pagination, which this tier does not do),
`@fontLineHeight=1`, `@snapToGrid`, `BETWEEN_LINES` spacing, non-`LEFT` tab
stops, and `<hp:tab/>` elements already in a document (they are not placed in
the character stream, so the line they sit on is measured without them).

`hh:margin`/`hh:lineSpacing` are read from the `<hh:default>` branch of the
`<hh:switch>` every corpus `paraPr` wraps them in — the `<hh:case>` branch
requires the 2016 `HwpUnitChar` namespace and states the same quantities in
character units. 774 of 774 corpus paraPr carry the switch and 477 differ
between the branches, so the choice is not cosmetic.

**금칙처리.** KS X 6101 no more publishes the prohibited-character sets than it
publishes the language-slot partition, so the table is this renderer's
conventional Korean/CJK one and every sidecar declares it as such
(`line_layout.prohibition_table`). A break opportunity is withdrawn when the
character after it may not start a line or the character before it may not end
one, and the filter applies to a space break exactly as to a syllable break.

### The vertical model is four measurements, not four assumptions

Taken off all 3214 cached `hp:lineseg` of the corpus *before* being
implemented, and re-measured by
`test_the_cached_line_geometry_relations_hold_across_the_corpus`:

| relation | holds on |
| --- | --- |
| `vertsize == textheight` | 3214 / 3214 |
| `baseline == round(0.85 × textheight)` | 3212 exact, all 3214 within 1 HWPUNIT |
| `vertpos[i] == vertpos[i-1] + vertsize[i-1] + spacing[i-1]` | 219 / 219 continuation lines |
| PERCENT: `vertsize + spacing == round(textheight × value/100)` | every PERCENT paragraph |

The 0.85 is HWP's baseline convention and is a **measured constant of this
corpus**, not a number the standard publishes. `textheight` is the maximum
declared `hh:charPr@height × hh:relSz` over the characters on the line — and
over any inline object's `hp:sz@height`, which was a measured defect before it
was a rule (see below). Against the cache, the computed `textheight` is exact
on 2303 of the 2370 comparable lines, `baseline` on 2303, and `spacing` on
1421; almost every `spacing` miss is ±2 HWPUNIT, i.e. 0.04 px at 144 dpi.

### Two attribute readings were decided by measurement, not by their names

- **`hp:paraPr@condense`** (공백 축소; corpus values 0 ×603, 25 ×130, 20 ×37,
  30 ×4). Read as "spaces may shrink **to** `condense`%", so that 0 lets them
  vanish, the breaker matches 16 of the corpus's 216 break positions. Read as
  "spaces may shrink **by** `condense`%", so that 0 is the default and means no
  condensing, it matches 48. The second reading is kept.
- **A negative `hh:intent`** (내어쓰기). The textbook reading — first line at
  the left margin, continuation lines pushed in by its magnitude — matches
  2710 of the 3214 cached boxes. "The intent moves the first line only,
  clamped at 0" matches 2860, and "the intent never moves the box" matches
  2895. The hanging reading is therefore **not implemented**; a negative
  intent moves no line box here. That choice costs a little on the break
  numbers (recall 48 → 43) and is kept anyway, because 3214 cached boxes are a
  far larger and more direct sample than 216 break positions.

### How well the breaker agrees with the engine that wrote the file

`python own_render.py FORM.hwpx --lineseg-agreement` reproduces every number
below; the committed run is
`engine/references/own-render-samples/e2.1-lineseg-agreement.json`.

The breaker is run on each paragraph's **unedited** text, inside the line box
the authoring engine itself used (the paragraph's cached first `horzpos +
horzsize`, plus the declared right margin), so a disagreement is the breaker's
and never the table solver's. A paragraph whose cache is unusable is excluded
and counted, not scored as a failure.

144 dpi, on a machine with Hancom Office's faces installed:

| form | paras | line count | break sequence | multi-line | multi-line count | break positions |
| --- | --- | --- | --- | --- | --- | --- |
| admrul | 22 | 22 | 21 | 2 | 2 | 1 / 2 |
| gianmun-1ho | 32 | 32 | 31 | 1 | 1 | 0 / 2 |
| gianmun-2ho | 20 | 19 | 19 | 2 | 1 | 1 / 2 |
| jeongbo | 58 | 58 | 52 | 6 | 6 | 1 / 7 |
| jumin | 133 | 132 | 113 | 27 | 26 | 9 / 36 |
| kstartup | 453 | 435 | 416 | 29 | 26 | 12 / 44 |
| moel-2013 | 263 | 254 | 234 | 34 | 25 | 7 / 49 |
| moel-2025 | 314 | 304 | 283 | 37 | 27 | 6 / 47 |
| nrf | 89 | 89 | 87 | 3 | 3 | 1 / 3 |
| saeopja | 764 | 758 | 747 | 17 | 14 | 5 / 24 |
| **total** | **2148** | **2103** (0.979) | **2003** (0.932) | **158** | **131** (0.829) | **43 / 216** (0.199) |

Twelve further paragraphs carry no usable cache and are excluded.

Read honestly, the headline number is the last column and it is **0.199**. The
first two columns are high because a corpus of government forms is
overwhelmingly single-line paragraphs — 2148 paragraphs, only 158 of which
break at all — and a paragraph that cannot break cannot disagree. The multi-line
subset is where the breaker is actually tested, and there it reproduces the
authoring engine's exact line sequence on 31 of 158.

### Where it fails, and why — this is an advance-width gap, not a rule gap

Restarting the breaker at each line start the authoring engine chose and asking
only where it puts the *next* break (`conditional_breaks`, error propagation
removed): **45 of 216 exact, 29 too early, 142 too late.**

`late` dominating by five to one is the diagnosis. `cached_line_fill` — how
full the authoring engine's own line is when this renderer measures it — has a
median of **0.92**: the breaker thinks there was still a tenth of the box free
where the authoring engine had already closed the line, so it keeps fitting the
next word on. The breaking *rules* put the break at a permitted position; the
*advance widths* say the wrong position is permitted.

Two things localise the gap further. Both were measured with a probe harness
that takes each line's box straight from its own cached `horzsize` instead of
re-deriving it from the margins, which scores **49/216** as its baseline
rather than the 45/216 above; the difference is the first-line box model, not
the breaking, and the deltas below are what matter.

- Splitting by face resolution: on lines where every declared face resolved,
  per-break accuracy is 38/156 and the fill median 0.925; where at least one
  face was substituted, 11/60 and 0.894. Substitution makes it worse but is
  **not** the main term — 0.925 is still a long way from 1.0.
- Sweeping the space advance: replacing the resolved face's space advance with
  a fixed fraction of the em moves per-break accuracy 49 → 60 → **69** → 52 →
  40 for 0.35 / 0.4 / 0.45 / 0.5 / 0.55 em (font advance itself: 49). The
  deficit is concentrated in the space character. **0.45 em is not adopted**:
  no reading of the standard justifies that number, the curve is a fit rather
  than a discovery, and tuning it against the corpus would turn the measuring
  stick into a training set.

One further variant was tested and rejected: making `hh:spacing` open no gap
adjacent to a space (자간 as strictly letter-spacing) raises per-break accuracy
from 49/216 to 59/216. It is not adopted because it would also change
intra-line *drawing*, which E2.3 pinned against the Hancom reference, and 10
breaks out of 216 is not enough evidence to move a measured model. It is the
first thing to try next.

### Incremental relayout, and what it does not do

Paragraphs after a relaid-out one in the same container are shifted by its
height change, so an edited paragraph cannot be drawn over its neighbour; and
a table's row heights are now solved *after* its columns, from the layout each
paragraph will actually get, so an edited cell grows its row instead of
overflowing it. Cell content is vertically centred against the same measured
block, not against the cached one.

That is the whole of the incremental relayout in this slice. It is **not**
E2.5: nothing reflows onto another page, no paragraph moves between pages, and
a relaid-out paragraph still *starts* where the cached layout put it — this
slice re-derives line breaking inside a paragraph, not the block stacking that
decides where a paragraph begins.

### A measured defect this slice found and fixed

Running the breaker over the corpus in `computed` mode and diffing every line
box against the cached layout showed admrul drifting up the page by a median
104 px and as much as 430, with `dx` of exactly 0 — purely vertical, so the
block model. The cause: `_line_metrics` took a line's height from the point
size of the runs on it, and an inline object is not a run. kstartup has
paragraphs whose entire content is one full-page inline table, cached
`vertsize` ≈ 63000 HWPUNIT against a `charPr` height of 1000; taking the run's
size shrank such a paragraph by a whole page and pushed everything below it up
the sheet. An inline (`treatAsChar="1"`) object now contributes its declared
`hp:sz@height`. Effect: computed `textheight` exact 2287 → 2303 of 2370;
admrul `|dy|` median 104.36 → 5.64, max 430.00 → 11.28.

### The scoreboard, before / after / computed

`engine/references/own-render-samples/e2.1-line-breaking.scoreboard-summary.json`
carries the full three-state run; the two sample forms also have their
individual `*.{before,after,computed}-e2.1.scoreboard.json`.

Means over the seven comparable forms (the three reduced references are
excluded — see *Three of the ten reference PDFs are not 1:1 renders*):

| | `ssim` | `ssim_inked` | line-box IoU | pair rate |
| --- | --- | --- | --- | --- |
| before (PR #173) | 0.7275 | 0.1227 | 0.4394 | 0.8014 |
| after (`auto`, what ships) | 0.7270 | 0.1225 | **0.4393** | 0.8014 |
| `computed` (the breaker itself) | 0.7198 | 0.1103 | **0.4035** | 0.7953 |

The shipping path is unchanged to four decimal places, and every form keeps
its verdict against the regression floor in all three states. The residual
movement is confined to the three forms that contain paragraphs with **no**
cache (kstartup 4, moel-2013 1, saeopja 1): those previously used an ad-hoc
greedy wrap and now use the real breaker, which moves kstartup's IoU by
−0.00003, moel-2013's by −0.0006 and saeopja's by −0.00001. No paragraph whose
cache is usable changed at all.

The honest measure of the breaker is the third row: laying every line out
ourselves costs **0.036 of line-box IoU** against the authoring engine's own
cached boxes, and 0.012 of `ssim_inked`. Per form, `computed` mode is *better*
than the cache on jeongbo (0.4385 → 0.5049) and jumin (0.5741 → 0.5827) and
worse on the rest, worst on moel-2013 (0.4455 → 0.2891).

### Alignment

`hp:lineseg` carries the line box but never the alignment offset — `horzpos`
stays 0 and `horzsize` stays the full column even for a centred line — so the
offset is computed from the measured content width, **character typography
included**. That inclusion is the point: taken from the unspaced width, a
`spacing="50"` run lands half its added width right of where the authoring
engine puts it.

- `LEFT` / `CENTER` / `RIGHT`: a start offset.
- `JUSTIFY` (양쪽): every line of a paragraph *except its last* is stretched to
  the box; the last line is left-aligned. A one-line paragraph is entirely
  "last line" and is untouched — which is most cell content on this corpus.
- `DISTRIBUTE` (배분): every line including the last.
- Slack goes into inter-character gaps, or into the spaces alone when the line
  has any. **Nothing is ever shrunk**, so a substituted face that overruns its
  box cannot be hidden by pulling text back.

Measured worth of justification, by ablation on the comparable forms
(with it / without it, line-box IoU): moel-2025 0.4706/0.4668, jumin
0.5700/0.5421, moel-2013 0.4397/0.4498, jeongbo unchanged. Net positive, kept.

**Inline vs anchored objects.** `hp:pos@treatAsChar="1"` objects are laid out
*inside* the line (they consume width and participate in alignment); anything
else is placed from `@horzOffset`/`@vertOffset` against the frame
`@horzRelTo`/`@vertRelTo` names. Getting this wrong is visible: gianmun's
발신명의 box sat at the left margin instead of centred, and the 직인 box sat on
top of it, until inline objects joined the line.

## Named fidelity limits

Each of these is reported in the sidecar's `elements_skipped` at render time,
not only here.

1. **Fonts: resolved where installed, substituted where not — and the render
   is machine-dependent by design.** Each face a document declares is looked
   up per language slot (`hh:charPr/hh:fontRef` carries one font id per slot,
   `hh:fontfaces` resolves it per slot) against the installed faces' own family
   names, read out of each font's OpenType `name` table. That table is the
   whole mechanism: the faces carry their Korean family names in their own
   records — `HANDotum.ttf` declares both `HCR Dotum` and `함초롬돋움`,
   `gulim.ttc` index 2 declares both `Dotum` and `돋움` — and FreeType, hence
   Pillow, exposes only the English one. One declared naming exception: HWP
   writes the 한양 foundry with a `한양` prefix where the files say `HY`.

   A face that is not installed falls back to Malgun Gothic
   (`C:\Windows\Fonts\malgun.ttf`) and is named in the sidecar's `fonts.faces`
   **and** in `elements_skipped`, with its character count. Measured
   resolved-character share on the reference machine (Hancom Office installed):
   gianmun-1ho/2ho, jeongbo, saeopja 1.00; jumin 0.998; kstartup 0.929;
   moel-2013 0.800; moel-2025 0.649; nrf 0.613; admrul 0.494. What does not
   resolve is Hancom's own HFT families (휴먼명조, HCI Poppy, 한컴바탕,
   신명 신문명조, HY울릉도M, 필기), which are not installed as TrueType.

   The consequence is stated in the sidecar in these words: the same document
   on a machine without these faces will not produce the same pixels. Set
   `RIGORLOOM_OWN_RENDER_FONT` / `…_FONT_BOLD` to pin one face — that switches
   per-face resolution off entirely and takes the machine out of the
   measurement, which is what a certification run wants.
2. **Character typography is applied; the slot partition is an approximation.**
   `hh:ratio`, `hh:spacing`, `hh:relSz`, `hh:offset` are parsed and drawn (see
   *Character typography* above). The named limit that remains is the
   codepoint→slot table, which the standard does not publish and this renderer
   therefore approximates, and the `user` slot, which is unreachable from the
   file alone. Both are declared in every sidecar.
3. **Equations and pictures are drawn; the other objects are placeholders.**
   `hp:pic` is rasterised from the container and `hp:equation` is laid out
   from its `hp:script` — see *Report-class documents* and *Equations* below.
   `hp:ole`, `hp:chart`, `hp:container` and the drawing shapes still get a
   grey outlined box labelled 그림 / 도형, and so does an `hp:equation` whose
   script is missing or unparseable. When the element declares `hp:sz` the box
   is at the declared extent; when it does not, the box is a fallback size and
   the label carries a `?` and the sidecar says `UNKNOWN extent`. **No corpus
   form contains an `hp:equation`** — verified by scanning every
   `Contents/section*.xml` in `tests/corpus/forms/converted/`; the equation
   path is therefore pinned by synthetic fixtures, built in
   `engine/tests/test_own_render.py` from a corpus form plus scripts the
   repo's own `eqn.py` converter emits.
4. **`DOUBLE_SLIM` is drawn as two strokes; the other non-solid types are
   stroked as solid.** A `DOUBLE_SLIM` edge splits its declared width — which
   is the width of the *band*, measured, not of a stroke — into two strokes of
   a third each at the band's extremes. Below three pixels there is no room
   for two strokes and a gap, and it stays solid and says so. `DASH` and
   `CIRCLE` are still drawn as a solid line of the declared width, named per
   side in the sidecar.
5. **`<hp:tab/>` elements already in a document are not resolved.** They are
   not placed in the character stream, so the line they sit on is measured
   without them and the cached box absorbs them; where a form uses tabs to
   build a column, that column collapses. Three corpus paragraphs are
   affected. The computed breaker *does* resolve a literal `\t` in the stream
   — which is the shape an edited paragraph has when a user presses Tab —
   against `hh:tabPr`'s explicit `LEFT` stops, falling back to a 40 pt
   interval that is this renderer's choice and is named in the sidecar
   (23 of the 42 corpus `tabPr` declare no stop at all). `RIGHT`, `CENTER`
   and `DECIMAL` stops are advanced as `LEFT`.
6. **Text does not wrap around anchored objects.** They are drawn at their
   declared offset, over whatever is there.
7. **Multi-column text (`hp:colPr`) is ignored** — PARA and COLUMN both resolve
   to the paragraph's container.
8. **Only `section0` is laid out.** No corpus form has more, but the sidecar
   says so when one does.
9. **Headers, footers, footnotes, endnotes and master pages are not drawn
   — but `hp:pageNum` is.** 쪽 번호 매기기 is a
   control, not a footer paragraph, and is stamped on every page at a
   measured position; see *Report-class documents*. `BOTTOM_LEFT`,
   `BOTTOM_CENTER` and `BOTTOM_RIGHT` only — every other `pos` is declared
   and nothing is drawn for it.
10. **Row heights are approximate where the content extent is.** Eight of 81
    corpus tables miss their declared height by more than 2% before the
    residual is redistributed; the redistribution keeps the outer box exact but
    shifts interior rows. The `saeopja` collision this used to name was a
    different defect and is fixed — see *Report-class documents*.
11. **Cross-machine byte equality is not claimed.** Same input → same PNG bytes
    on one machine and one Pillow build (pinned by test). Different installed
    fonts or a different FreeType build will differ — and since face resolution
    now reads the machine's font directory, *which* faces are installed is a
    first-class input, not a footnote.
12. **`kstartup-jiwon-sincheongseo-saeopgyehoekseo` paginates wrong.** It is
    the one comparable form whose rendered page count does not match its
    Hancom reference, so it fails the regression floor's `page_count_exact`
    check today. A pagination defect, not a typography one; unfixed. The same
    form also draws line boxes at `y0` ≈ 85.9 million px on page 18, from an
    anchored object at a wild declared `vertOffset`; identical in both line
    layout modes, so it is this same defect and not the breaker's.
13. **The line breaker agrees with the authoring engine on 43 of the corpus's
    216 break positions** (*Line breaking from metrics*, above). It is used
    only where the cached layout cannot be, which on an unedited document is
    nowhere — but it is what an edited paragraph gets, and 0.199 is what that
    is worth today. The residual is an advance-width gap concentrated in the
    space character, not a gap in the breaking rules.
14. **Block layout is not implemented, so relayout does not reflow the page.**
    A relaid-out paragraph shifts the paragraphs after it in its own container
    and grows its table row, and nothing else: it still starts where the cache
    put it, nothing moves between pages, and a paragraph that grows past the
    bottom of the body box is drawn there anyway. That is E2.5's work.
15. **The staleness detector is sound but incomplete.** It cannot see an edit
    that leaves every line still fitting; `relayout_paragraphs` is the channel
    an editor must use instead. See *Which engine laid out which paragraph*.

## Report-class documents

Every form in the corpus is a blank government form: one section, no
pictures, no equations, no page numbers, and one line of text in every table
cell. A *report* — multi-section prose with figures, equations, captions,
numbered headings, page numbers and tables whose rows differ in height — was
never rendered by this renderer until a Hancom-rendered report was measured
against it. Six mechanisms came out of that measurement. The document itself
is private and is not in this repo; only aggregate numbers appear here.

The measured document: 18 pages, 485 paragraphs, 515 runs, 27 tables, 240
cells, 11 embedded pictures, 14 equations, one `hp:pageNum` control, one
section. Scored at 144 dpi against its own Hancom PDF, page count 18/18
exact before and after.

| channel | before | after |
| --- | --- | --- |
| `ssim_mean` | 0.7306 | 0.7273 |
| `ssim_min` | 0.6310 | 0.6264 |
| `ssim_inked_mean` | 0.1034 | **0.1263** |
| `ssim_inked_min` | 0.0123 | −0.0367 |
| `text_line_iou_mean` | 0.5508 | **0.5630** |
| `text_line_pair_rate_mean` | 0.8134 | **0.8390** |
| `changed_channel_ratio_mean` | 0.1060 | 0.1237 |
| `ink_delta_abs_max` | 0.0371 | **0.0085** |

`elements_skipped` went from 13 distinct entries to 5.

### What was fixed, and what each was worth

1. **`hp:pic` is drawn from `BinData`.** The OPF manifest in
   `Contents/content.hpf` is the published mapping from the
   `binaryItemIDRef` a picture cites to the container entry holding its
   bytes; the id is `image7` while the entry may be `.PNG`, `.jpg` or `.bmp`,
   so a filename guess is not sound. `hp:imgClip` is a crop *fraction* of
   `hp:imgDim`'s declared source extent, not of the file's pixel size, so a
   clipped picture is right whatever resolution it happens to be. `hp:flip`
   is honoured; rotation is declared and not applied. A binary Pillow cannot
   decode — HWP embeds EMF/WMF as readily as PNG — keeps the placeholder box
   and stays named. Worth `ssim_inked_mean` 0.1034 → 0.1378 and
   `ink_delta_abs_max` 0.0371 → 0.0162 on its own.
2. **`hp:pageNum` is stamped on every page.** It is a control, not a footer
   paragraph, so it is found by walking to the `hp:run` that carries it —
   that run's `charPrIDRef` meters the number. Placement was measured, not
   assumed: the number's line box sits with its **bottom edge on `page height
   − bottom margin`**, aligned inside the body box `[left margin, width −
   right margin]`. Predicted 807.86 pt / centre 307.57 pt against a reference
   that draws 807.93 / 307.60. That covers `BOTTOM_LEFT`, `BOTTOM_CENTER`
   and `BOTTOM_RIGHT`; every other `pos` is declared and nothing is drawn for
   it rather than guessed from the one position measured. `sideChar`,
   `formatType=DIGIT`, `hp:startNum@page` and `hideFirstPageNum` are
   honoured. The stamp is recorded in `line_boxes` as `mode: "pagenum"`,
   because the reference PDF extracts it as a text line like any other.
   Worth `text_line_pair_rate_mean` 0.8134 → 0.8390.
3. **A table row is as tall as its tallest cell, not its first.**
   `solve_tracks` resolved a unit-span track from the *first* constraint
   covering it and ignored every later one. For columns that is harmless —
   every cell in a column declares the same `cellSz` width — and on a
   government form it was harmless for rows too, because every row there is
   one line tall. A report table separates them: a two-column row holding one
   line on the left and two on the right got the left cell's height, and the
   right cell's second line was drawn over the row below. The declared-total
   redistribution then hid the cause by stretching every row proportionally,
   so the outer box stayed exact while the interior was wrong.

   Taking the max is not a heuristic. On the measured document every
   `cellSz@height` is 282 HWPUNIT — a stored minimum carrying no information
   — and once rows are solved as the max over their cells, the row heights
   sum to the table's own declared `hp:sz@height` **exactly, on all 27
   tables**, where before eight rows were short by 560–2300 HWPUNIT. The
   file's two independent records agree only under the max reading. Worth
   `text_line_iou_mean` 0.5547 → 0.5630 here, and on the corpus it fixed
   `saeopja`'s two colliding rows: `text_line_iou` 0.3990 → 0.5393, `ssim`
   0.6218 → 0.6441.
4. **`DOUBLE_SLIM` declares a band, and Hancom draws two strokes in it.** An
   edge declaring 283.46 HWPUNIT (6 px at 144 dpi) comes back from the
   reference as two 2-px strokes with a 2-px gap spanning exactly those 6 px,
   and the same 2/2/2 shape repeats on every such edge. Stroking the band
   solid put three times the ink on it. Worth `ink_delta_abs_max` 0.0162 →
   0.0085.
5. **A bold run on a family with no bold cut is smeared, not dropped.** 바탕 /
   Batang ships no bold face, and it is the face this document is set in, so
   this is the ordinary case rather than an edge one: `_face_for` handed back
   the regular face and every bold run — 281 of 16047 characters, which is
   what a report's section headings are made of — drew at regular weight. HWP
   fakes the weight; so does this now, by drawing the glyph again a fraction
   of an em to the right. The smear is horizontal on purpose: Pillow's
   `stroke_width` thickens in every direction and reads as an outline, not a
   weight. The advance is **not** changed, so a cached line still measures
   the width the authoring engine gave it. One pixel per 24 px of glyph size,
   floor 1, is this renderer's choice and is declared — the standard does not
   publish what HWP smears by, and at body sizes every em fraction between
   about 1/40 and 1/13 rounds to the same single pixel. Visible, not
   statistical: `ssim_inked_mean` moved 0.1261 → 0.1263.
6. **A defect found on the way: the face cache never hit.** `_face_for`'s
   inner loop `for key in (slot, slot.upper())` shadowed the cache key
   `(cid, slot, bold)` computed six lines above it, so every write filed
   itself under the string `"hangul"` while every read asked for the tuple.
   Every character on the page re-ran a system font-index lookup, and any
   per-face fact recorded there was filed under the wrong name — which is why
   mechanism 5 was invisible until this was fixed.

### Two numbers moved the wrong way, and why

`ssim_inked_mean` is up overall, but `ssim_inked_min` went from 0.0123 to
−0.0367 and `ssim_mean` slipped 0.003. Both come from mechanism 4. A single
fat stroke covered the reference's two thin ones whatever the sub-pixel
offset, so block SSIM rewarded it for the wrong reason; two thin strokes are
punished by any misregistration at all. The ink channel halved and the
side-by-side is plainly closer, so what the block statistic is measuring here
is registration — the standing E2 gap — and not whether the border is right.
`changed_channel_ratio_mean` rose 0.1060 → 0.1237 for the same class of
reason plus mechanism 1: a page that used to be blank where a photograph
belongs disagrees with the reference on fewer channels than one carrying a
real photograph a fraction of a pixel out of place. Neither channel carries a
threshold. `ssim_inked_min` −0.0367 still clears the −0.1 regression floor,
and the floor passes on every comparable corpus form except `kstartup`'s
pre-existing `page_count_exact` failure (limit 12), which none of this
touches.

### What a report-class document still does not get

- `hp:parameters` / `hp:stringParam` / `hp:integerParam` (11 / 55 / 11) —
  field bookkeeping, no ink of its own.
- Footnotes, endnotes, headers and footers. The measured document declares
  `hp:footNotePr` and `hp:endNotePr` but carries no note and no header or
  footer, so this lane is still unmeasured against a real one; one corpus
  form does carry `hp:header` and it is still skipped and declared.
- Multi-section documents. The measured document has one section, so limit 8
  is still untested against a real multi-section report.
- The measurement's own blind spot: on bibliography pages Hancom splits a
  justified URL into many spans, so `unpaired_reference` reads high on the
  line channel where the render is visually near-identical. That is a
  property of the pairing, not of the renderer.

## Equations (`hp:equation`)

An `hp:equation` carries its content as an HwpEqn *script*, in an `hp:script`
child, plus a declared `hp:sz`, a `baseUnit` (the base size, in HWPUNIT), a
`baseLine` (where inside the box the equation's baseline sits, as a percentage
of the height) and a `font`. Until this slice all of that became a grey box
labelled 수식.

`engine/scripts/eqn.py` already converts LaTeX **into** HwpEqn so a document
can be authored; nothing read the other way, which is why the element could
only ever be boxed. `engine/scripts/hwpeqn_parse.py` is that other direction:
a metric-free parser — no Pillow, no font — producing the tree
`own_render._eq_layout` measures and `_eq_draw` inks.

### What is laid out

Fractions (`over`, `atop`), sub- and superscripts including limits, roots
(`sqrt`, `root … of …`), fences with sizing (`left ( … right )` and the other
delimiters), the big operators, operator names set upright, Greek and the
symbol vocabulary, quoted literals, the `` ` `` / `~` spacing atoms, accents,
style words, and grids (`matrix`, `pmatrix`, `bmatrix`, `dmatrix`, `cases`,
`pile`, `eqalign`). On the measured report all 14 equations parse with **zero**
unsupported constructs: 86 subscripts, 15 superscripts, 14 `over`, 14 Greek,
16 literals, 10 symbols, 8 `sum`, 8 function names, 5 fences, 2 `min`, 1 each
of `int`, `max`, `sqrt` and `bar`.

A construct with no node — `size`, `color`, `binom`, `buildrel`, the size
words — becomes a `Raw` node that draws its own token text and is named per
construct in `elements_skipped` as `hp:equation@script[<name>]`. An equation
with no script, or one that nests past the parser's recursion budget, falls
back to the placeholder box and says which.

### Three decisions were made by measurement, and are declared as such

1. **`over` binds the immediately preceding primary**, not the whole preceding
   expression. KS X 6101 does not publish HwpEqn's grammar and the readings
   differ on unbraced input; Hancom's own editor always writes
   `{numerator}over{denominator}`, where they agree.
2. **`sum` and the other symbol operators stack their limits; integrals and
   the word-shaped operators do not.** The reference render sets `sum_{x}`
   with x under the sigma, and `int_{e}`, `min_{s,m}`, `max_{q}` with the
   limit to the right. That split is one reference render's evidence, not a
   rule anybody published.
3. **Stacking runs on a nominal 0.78 / 0.22 em character cell, not on the
   face's own ascent/descent.** The face metrics carry line leading that a
   maths layout must not stack: reading them made every fraction about 12%
   taller than the extent Hancom recorded in `hp:sz`, so every equation was
   then scaled down to fit a box it should have filled. The `hp:sz` fit is
   decided on the **drawn ink** instead (`_eq_bounds`), which is also what
   makes the containment claim below checkable.

### `hp:sz` is the ground truth, and scale-to-fit is a declared fallback

The declared extent is what the authoring engine measured the equation to be,
and it is what the paragraph's line box was sized around. So the equation is
laid out *inside* it. Where this renderer's metrics do not fit — a substituted
maths face advances differently — the equation is re-laid out smaller, and if
rounding still leaves it over, the raster is reduced. Either way the scaling
is declared as `hp:equation@equation_scaled` and recorded per equation. The
box is never overflowed: an equation that spills draws over the text around
it, which is worse than a box.

Every equation's declared box and inked rectangle are written to the sidecar
(`equations.placements`), so containment is checkable from the output rather
than asserted in a docstring. On the measured report 13 of 14 equations scale,
between 0.812 and 0.995 — the residual is font substitution and this
renderer's spacing choices, both named.

### One line box per baseline, not one per equation

A PDF text extractor reads a stacked equation as several text lines — a
numerator line, a denominator line. Recording the whole equation as one
`line_boxes` entry would pair one candidate box against three reference lines
and score right geometry as wrong. The drawn glyphs are grouped by baseline
instead; the 14 equations contribute 55 line boxes. Rules and strokes are
excluded: a fraction bar is not a text line.

### What it is worth, measured

Same document, same scoreboard build, 144 dpi, page count 18/18 exact before
and after.

| channel | before | after |
| --- | --- | --- |
| `ssim_mean` | 0.7273 | **0.7280** |
| `ssim_min` | 0.6264 | 0.6264 |
| `ssim_inked_mean` | 0.1263 | 0.1262 |
| `ssim_inked_min` | −0.0367 | −0.0405 |
| `text_line_iou_mean` | 0.5630 | 0.5334 |
| `text_line_pair_rate_mean` | 0.8390 | **0.9041** |
| `changed_channel_ratio_mean` | 0.1237 | 0.1247 |
| `ink_delta_abs_max` | 0.0085 | 0.0099 |

`elements_skipped` stays at 5 distinct entries: `hp:script` leaves it and
`hp:equation@equation_scaled` joins it.

Read honestly. The pair rate moves 6.5 points, which is the real result: two
thirds of the reference text lines this renderer was not accounting for on the
equation pages are now drawn and recorded. `text_line_iou_mean` falls for the
arithmetic reason that those newly paired lines were previously *not scored at
all* — an unpaired reference line contributes nothing to the IoU mean, and a
paired one at imperfect registration contributes a low number. The raster
channels barely move because 14 equations are about 1.5% of 18 pages, and they
move slightly the *wrong* way for the same reason mechanisms 1 and 4 did: a
page that used to be blank where an equation belongs disagrees with the
reference on fewer channels than one carrying an equation a fraction of a pixel
out of place. Every regression-floor check still passes, on this document and
on every comparable corpus form.

### What an equation still does not get

- **Italic variable shaping.** Hancom sets equation variables in italic; this
  renderer sets them upright, because OWPML names a *family* and
  `SystemFontIndex` resolves regular and bold cuts only. This is the largest
  remaining visual difference on the reference comparison — the geometry lines
  up, the letterforms do not.
- `hp:equation@lineMode` and `@textWrap`. The equation is drawn at the object
  box the paragraph already reserved for it; no text is re-wrapped around it.
- Integral limits are tucked less tightly against the sign than Hancom tucks
  them, and a fence carries slightly more air than Hancom's.
- The `_EQ_AXIS`, `_EQ_ASC`/`_EQ_DESC`, spacing and operator-scale constants
  are this renderer's calibration against one reference render. They are named
  in the source with that status; they are not published metrics.

## Determinism

- No timestamp is written into the PNG (no `pnginfo`, no `tIME`).
- `compress_level` is pinned; `optimize=False`.
- Pillow's font layout engine is pinned to `Layout.BASIC`. Pillow uses Raqm
  when the build has it, and Raqm shapes differently — leaving it to the build
  would make the same document render differently on two machines for reasons
  that have nothing to do with the document.
- Every geometric quantity derives from integers in the file.

`test_two_renders_are_byte_identical` enforces the same-machine half.

## Path to `render_cert` certification

`pipeline/scripts/render_cert.py` measures a candidate renderer by:

1. invoking `[binary, "{in}", "{out}"]` — already supported: passing a second
   positional argument writes a PDF;
2. probing `binary --version` and requiring one non-empty line — already
   supported (`rigorloom-own 0.1.0`);
3. comparing the candidate PDF against an immutable Hancom reference PDF on
   three channels: **page count**, **unique-word anchors** (via PyMuPDF text
   extraction), and **raster changed-channel ratio**.

Two of those three are reachable today. The blocker is the word-anchor channel:
`render_to_pdf` writes *raster* pages, so the candidate PDF has no text layer
and PyMuPDF extracts nothing. The prerequisite for full certification is a
vector text backend — emitting PDF text-showing operators with an embedded
font, at the same positions this renderer already computes. The layout half is
done; only the output encoder is missing.

## Measuring against Hancom — `engine/scripts/render_scoreboard.py`

The certification path is blocked on the output encoder, but the *measurement*
is not. `render_scoreboard.py` rasterises the immutable Hancom reference PDF
onto exactly the pixel grid the own renderer drew (never the reverse, so a
metric change can only come from the renderer) and reports, per page:

| metric | what it is |
| --- | --- |
| `ssim` | block-8×8 SSIM, Wang et al. 2004 constants. **scikit-image is not installed in this environment**, so this is an in-repo implementation with a *non-overlapping box* window instead of an 11×11 Gaussian sliding one. Declared as `ssim_variant` in every scoreboard rather than passed off as skimage's number. |
| `ssim_inked` | the same statistic averaged over blocks *either* page marked. It exists because most of a government form is paper: every blank block scores ~1.0 on both sides and the plain mean is dominated by agreement about emptiness. |
| `changed_channel_ratio` | `render_cert._compare_rasters`' definition verbatim, so a number here can be read against a render_cert threshold. Carries **no** threshold: a font-substituting renderer cannot reach a meaningful one, and a gate nobody can pass is not a gate. |
| `ink` | fraction of pixels below 128, and candidate − reference. |
| `text_line_iou` | the renderer's own `line_boxes` paired one-to-one against the reference PDF's `get_text("dict")` lines, greedy by ascending centre distance, capped at a quarter page height. A pair with IoU 0 still counts as a pair; dropping it would flatter the mean. |

No new dependency: PyMuPDF and Pillow are already `engine` extras.

### Three of the ten reference PDFs are not 1:1 renders

Found by the first run of this scoreboard, and it is not about the renderer.
`gianmun-byeolji-1ho`, `gianmun-byeolji-2ho` and `nrf-gyeolgwa-bogoseo-yangsik`
draw their text at **~0.707 = 1/√2** of the `hh:charPr@height` their files
declare, anchored near the top-left of an otherwise A4 page. Three independent
measurements agree:

- glyph-weighted median span size ÷ declared size: 0.707, 0.707, 0.709, against
  0.996–1.023 for the other seven;
- gianmun's `발신명의`, declared 15 pt, drawn by Hancom at 10.67 pt;
- each document's own `Preview/PrvImage.png` shows the content **filling** the
  page, exactly as this renderer lays it out.

The documents are right; those three reference renders carry a print reduction.
Scoring against them would grade the operator's reference facility, so
`reference_geometry_scale` detects it and the verdict is **blocked** —
`pass: null`, never `false`. The metrics are still reported and flagged
relative-only, because a before/after delta on the same misaligned pair still
shows movement. **Regenerating those three references at 1:1 is the single
highest-value thing the operator can do for this lane.**

### Measured state, 144 dpi, machine with Hancom Office fonts installed

Three renderer states, all scored with the same scoreboard build (the
historical renderers were taken from their own commits — if the metric set
moved between columns, the delta would be measuring the ruler):
**A** = PR #166 + `line_boxes`, **B** = after E2.3 character typography,
**C** = after E2.2 face resolution.

| form | class | cmp | `ssim_inked` A→B→C | line IoU A→B→C | `ssim` A→B→C |
| --- | --- | --- | --- | --- | --- |
| admrul | hr | ✓ | 0.2953 → 0.2920 → 0.3066 | 0.4599 → 0.4595 → 0.4845 | 0.8844 → 0.8836 → 0.8863 |
| jeongbo | petition | ✓ | 0.0379 → 0.0382 → 0.0372 | 0.4447 → 0.4321 → 0.4385 | 0.6132 → 0.6178 → 0.6175 |
| jumin | petition | ✓ | 0.0840 → 0.0798 → 0.0820 | 0.5620 → 0.5700 → 0.5741 | 0.6343 → 0.6370 → 0.6373 |
| kstartup | grant | ✓ | 0.2203 → 0.2209 → 0.2207 | 0.2564 → 0.2510 → 0.2470 | 0.8096 → 0.8108 → 0.8114 |
| moel-2013 | hr | ✓ | 0.0318 → 0.0391 → 0.0446 | 0.4461 → 0.4397 → 0.4455 | 0.7601 → 0.7630 → 0.7653 |
| moel-2025 | hr | ✓ | 0.1344 → 0.1407 → 0.1481 | 0.4920 → 0.4706 → 0.4872 | 0.7456 → 0.7490 → 0.7530 |
| saeopja | petition | ✓ | 0.0210 → 0.0213 → 0.0194 | 0.3936 → 0.3956 → 0.3990 | 0.6204 → 0.6212 → 0.6218 |
| gianmun-1ho | gongmun | ✗ | 0.0980 → 0.0995 → 0.1007 | — | 0.8810 → 0.8823 → 0.8810 |
| gianmun-2ho | gongmun | ✗ | 0.0369 → 0.0361 → 0.0359 | — | 0.8750 → 0.8755 → 0.8737 |
| nrf | research | ✗ | 0.3701 → 0.3714 → 0.3717 | — | 0.7566 → 0.7572 → 0.7574 |

Read honestly: the gains are real, consistent and **small**. Plain SSIM is up
on nine of ten forms end to end; `ssim_inked` on six of ten; line-box IoU on
five of seven comparable. Nothing here is a step change, and the numbers say
why: `ssim_inked` sits between 0.02 and 0.37 against a fidelity target of 0.70,
so what dominates now is sub-pixel glyph registration *inside* lines that are
already in the right place at the right size — not any single unimplemented
element.

### Thresholds are a regression floor, not a fidelity bar

Every bound in `PROPOSED_THRESHOLDS` sits just below the worst measurement of
the seven comparable forms (`ssim_min` 0.4867 jumin, `ssim_inked_min` −0.0224
saeopja, IoU 0.2470 kstartup, pair rate 0.4490 admrul, ink delta 0.0375
kstartup). A renderer change that makes any scored channel worse fails; today
passes. Clearing it says "no worse than 2026-09" and nothing else. A separate
`FIDELITY_TARGET` block records what an `own-certified` grade should actually
demand — recorded, not evaluated, so the distance stays visible. `ratified:
false` on both; the grade stays `own-uncertified` on every class.

## Remaining order of work

1. **Regenerate the three reduced reference PDFs at 1:1** — until then three
   document classes (gongmun, research) cannot be graded at all.
1b. ~~**Render `hp:equation`.**~~ Done — see *Equations* above. What it left
   open is italic variable shaping, which is now the largest visual difference
   on the equation pages and needs per-cut face resolution, not equation work.
2. **Close the advance-width gap the breaker exposed.** A cached line measures
   a median 0.92 of its own box by this renderer's advances, and the deficit is
   concentrated in the space character. This is now the largest single term in
   *both* open measurements: it is why the breaker matches only 43 of 216 break
   positions, and it is the same quantity `ssim_inked` is measuring inside a
   line. Two candidate mechanisms are named and rejected as unproven in *Line
   breaking from metrics*; the way to settle it is a reference PDF measurement
   of what Hancom actually advances for a space in a Korean face, not another
   sweep against the corpus.
3. Vector PDF text output — unlocks `render_cert`'s word-anchor channel and
   with it the actual certificate.
4. Sub-pixel glyph registration: see item 2, of which this is the intra-line
   half.
5. **Block layout (E2.5).** Paragraph stacking, page reflow and a table row
   that can push its table onto the next page — without them a relaid-out
   paragraph is correct only inside its own container.
6. A vendored font with known metrics, so cross-machine determinism becomes
   claimable and the scoreboard stops depending on which faces this machine has.
7. `kstartup` pagination (limit 12).
8. Italic (and other non-regular) cuts in `SystemFontIndex`, which is what
   equations and emphasised prose both now wait on.
9. Only then ask `render_cert` for a per-document-class grade. Until it
   answers, the grade stays `own-uncertified`.
