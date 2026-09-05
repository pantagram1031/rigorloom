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
| `e2.5-flow-agreement.json` | the block flow pass measured against each document's own cached page assignment and `vertpos`, per form and summed |
| `kstartup-…{before,computed}-e2.5.scoreboard.json` | the one corpus form the flow pass changes, scored against its Hancom reference PDF with the cached pagination and with the flow pass |

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
This is the *cache-reading* pagination, and on kstartup it is measurably wrong
(20 pages against the reference's 22); *Block layout and page reflow (E2.5)*
below is the pass that computes a page assignment instead of reading one, and
says what each is worth.

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
| `hh:ratio` | horizontal glyph scale, % | advance scales, and so does the ink: the piece is rasterised to its own mask at natural width, resampled horizontally (LANCZOS, pinned), composited in the run colour. **Vertically inert** — it never enters the line height |
| `hh:spacing` | letter spacing, % **of the character's own advance** | a gap *between* characters — n−1 per line, no trailing gap |
| `hh:relSz` | relative character size, % | scales the point size before rasterisation, and the advance with it. **Does not enter the line height** |
| `hh:offset` | baseline shift, % of the **declared** `hh:charPr@height` | **positive lowers** the glyph; the recorded line box follows |

Every one of those readings was forced by measurement rather than chosen, and
three of them were wrong until `render-check-01` was measured character by
character — `docs/research/line-and-character-metrics.md`, reproduced by
`python tests/corpus/render-check/measure_metrics.py`.

gianmun's `발신명의` is `charPr` id 8 — 15 pt, `ratio="100"`, `spacing="50"` —
and Hancom's own render draws that span 58.65 pt at a reported size of
10.67 pt, i.e. **5.496 em**. Four advances plus three half-em gaps is 5.5 em;
four advances plus *four* gaps would be 6.0. So the gap count is n−1. What that
run could *not* settle is what the percent is a percent **of**: a Hangul cell
advances by exactly 1 em, so "% of the character size" and "% of this
character's advance" predict the same 0.5 em. `render-check-01`'s `F13` draws
Latin and spaces at the same 자간 and separates them — `ABCdef` at −15 measures
31.077 pt against 31.106 proportional and 27.595 flat; a half-width space at
+30 measures 6.479 against 6.500 and 8.000. Proportional, with no exception.
Em is the unit for the gianmun figure because its reference PDF is one of the
three the scoreboard rejects as a ~0.707 print reduction — the ratio is
scale-free, the absolute pixels are not.
`test_the_spread_run_matches_the_hancom_reference_in_em` pins gianmun;
`test_the_spacing_gap_is_a_percent_of_the_characters_own_advance` pins what it
could not say.

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

**The unit the cache is trusted in is the DOCUMENT, not the paragraph.**
`docs/research/lineseg-on-save-01.md` measured Hancom saving three corpus
forms twice each, untouched and with one character appended. Untouched, all
223 cached line boxes came back byte-identical in all 9 `hp:lineseg` fields —
Hancom recomputes line layout on every save, but the recomputation is
idempotent. With one character appended, the *edited* paragraph did not move
at all, while a paragraph **534 positions downstream** shifted its `vertpos`
from 0 to 70884 and two never-laid-out paragraphs elsewhere gained line boxes.
So a per-paragraph test cannot decide anything: it cannot name the paragraphs
a layout pass would also have moved.

What can decide it is **provenance** — is this package the direct, unedited
output of Hancom's own most recent save? The renderer answers from
`version.xml@application`, the only writer signature an HWPX carries, and
declares the answer in the sidecar (`layout_policy`, `layout_policy_reason`,
`layout_provenance`):

| `layout_provenance.writer` | what decides it | `layout_policy` |
| --- | --- | --- |
| `hancom_untouched` | `application` starts with Hancom's product name | `cache` |
| `rigorloom_written` | `application` is `Rigorloom` | `computed` |
| `unknown_writer` | any other value, or no `version.xml`/attribute | `computed` |

Two things override the file: a caller that names an edited paragraph in
`relayout_paragraphs` (an edited package is not an untouched one, wherever
the edit landed), and `--line-layout computed`. `--layout-policy cache|computed`
pins either policy for MEASUREMENT — pinning `cache` on an edited package is
unsound and is declared as an override in the reason string.

`computed` means the **whole** document: `line_layout` and `block_layout` both.
There is no half-computed document under `auto` any more.

**The stamp, and why it lives in `version.xml`.** `hwpx_write.blank_package`
has always written `application="Rigorloom"`; `xml_backend.HwpxDocument.save`
now does too, through `hwpx_write.stamp_writer_application`, which rewrites
only the `application` and `appVersion` attribute values and leaves every
other byte of the member alone. Without it the edit path — which copies
`version.xml` forward verbatim, as it does every member it did not change —
would keep claiming Hancom wrote the package last, and `auto` would trust a
cache describing the text from before the edit. `version.xml` is the right
home because Hancom overwrites the whole member on its own save, so the marker
**clears itself** the moment Hancom is the last writer again. A marker parked
in `Contents/content.hpf` would not: whether Hancom preserves an unknown
`opf:meta` across a resave is NOT MEASURED here, and a marker that survived
would pin the package to `computed` forever.

This does make a Rigorloom-edited package trivially distinguishable from a
Hancom-edited one, which is what E3 is otherwise trying to eliminate
(`hwpx_write.canonical_from_elementtree`). The tension is deliberate and
resolved the same way every time in this repo: an honest, declared marker
beats a silent mimicry that would make `auto` draw a stale box.

Under `auto`, `computed` wins for exactly three named reasons, each counted in
`line_layout.computed_reasons`:

| reason | what it means |
| --- | --- |
| `policy` | the whole document is computed — the caller asked, or provenance said so. `layout_policy_reason` says which |
| `cache_absent` | the paragraph carries no `hp:linesegarray` at all |
| `textpos_past_end` | a cached line starts past the end of the character stream, so no character range lines up with that box |
| `caller_marked_edited` | the caller passed the paragraph in `relayout_paragraphs`, under a pinned `cache` policy |

`cache_absent` and `textpos_past_end` are **not** staleness inferences and are
not affected by the policy: they describe a cache this reader cannot *read*,
so there is nothing to draw from either way. `textpos_past_end` earns that
reading by measurement — it fires on exactly one paragraph of each of three
**unedited** corpus forms (moel-2013 #159, saeopja #321, kstartup #264), all
three carrying an `hp:ctrl` this reader gives no character cell (a HYPERLINK
`hp:fieldBegin`/`fieldEnd` pair, an `hp:colPr`) where the authoring engine
counted one. That is a reader gap, named and **not fixed here**; it is
emphatically not evidence that somebody edited a government form template.

`stale_line_width` is the interesting one. The bound counts only full-width
cells (Hangul, Hanja, kana, CJK punctuation, an inline object slot — whose
advance in HWP is exactly the declared character size × `hh:ratio`, whatever
face draws them) plus their `hh:spacing` gaps, which are exact because the gap
is a percent of that same cell advance. Latin and spaces contribute no width;
their gaps count only when **negative**, since a positive gap on a
proportional character is a percent of an advance the bound does not know and
cannot be assumed to be a full cell's worth. It can therefore never exceed the width the authoring
engine actually fitted, which makes the detector **sound**: it fires on no
paragraph of any of the ten corpus forms (the worst unedited line reaches
0.901 of its box by this bound, against a 1% tolerance), and
`test_no_unedited_corpus_paragraph_is_judged_stale` asserts that on all ten.

It is also **incomplete**, and the sidecar says so in those words: an edit
that leaves every line still fitting is invisible in the file. An editor that
knows it changed a paragraph must declare it through `relayout_paragraphs`
rather than rely on detection.

Since this slice it **decides no paragraph**. `_scan_stale_cache` runs it once
over the whole document at load, reports every hit in
`line_layout.stale_diagnostics`, and uses it for exactly one thing: because it
raises no false positive, a hit *falsifies* a `cache` policy. A package
claiming to be Hancom's own untouched save that carries a line box too narrow
for the text on it is not that package, so the WHOLE document goes computed
and `layout_policy_reason` starts `stale_cache_contradicts_provenance`. That
is what catches an edit applied by something that did not stamp its own
signature — the case the notes could otherwise only hope did not happen. (The
sweep skips a lineseg carrying no `horzsize`, having no column width to fall
back on; zero corpus linesegs are shaped that way.) A paragraph is named there by its document-order
position among every `hp:p` in `section0`, counting from 0 — `hp:p@id` is not
unique (moel-2025 gives `2147483648` to 329 of its 330 paragraphs), and the
caller can compute the ordinal from the same file without asking the renderer.

Every line box in the sidecar carries `mode: "lineseg" | "computed"`, so a
reader can tell per line which engine broke it.

### What the computed default costs, measured

An edited document is now always drawn computed, so the question is what that
costs where the cache *would* have been usable. Every number below is
`render_scoreboard.py` at 96 dpi against the forms' own Hancom reference PDFs,
the same document scored twice — `--layout-policy cache` against
`--line-layout computed --block-layout computed` — so nothing but the policy
moves. Columns are **computed minus cache**; negative is worse.

| form | pages cache / computed / ref | Δssim | Δssim_inked | Δtext_line_iou | Δpair_rate |
| --- | --- | --- | --- | --- | --- |
| admrul-gajokdolbom-hyuga-sinchengseo | 1 / 1 / 1 | −0.0864 | −0.2741 | **−0.4088** | 0.0000 |
| gianmun-byeolji-1ho | 1 / 1 / 1 | −0.0037 | −0.0170 | −0.0116 | 0.0000 |
| gianmun-byeolji-2ho | 1 / 1 / 1 | +0.0007 | +0.0033 | +0.0032 | 0.0000 |
| jeongbo-gonggae-cheongguseo | 1 / 1 / 1 | +0.0007 | +0.0019 | +0.0008 | 0.0000 |
| jumin-deungchobon-sinchengseo | 3 / 3 / 3 | −0.0072 | −0.0011 | −0.0032 | 0.0000 |
| kstartup-jiwon-…-saeopgyehoekseo | 21 / **22** / 22 | +0.0547 | +0.1268 | **+0.3616** | +0.1428 |
| moel-pyojun-geunrogyeyakseo-2013 | 7 / 7 / 7 | −0.0119 | −0.0143 | −0.0453 | +0.0061 |
| moel-pyojun-geunrogyeyakseo-2025 | 7 / 7 / 7 | −0.0734 | −0.0834 | −0.2128 | −0.0214 |
| nrf-gyeolgwa-bogoseo-yangsik | 4 / 4 / 4 | −0.0232 | −0.0402 | −0.1576 | −0.0089 |
| saeopja-deungnok-sinchengseo | 6 / 6 / 6 | −0.0231 | −0.0326 | −0.0768 | −0.0024 |

Corpus means, cache → computed: `ssim` 0.8006 → 0.7833 (−0.0173),
`ssim_inked` 0.2779 → 0.2449 (−0.0331), `text_line_iou` 0.6319 → 0.5768
(−0.0550), `text_line_pair_rate` 0.8362 → 0.8478 (**+0.0116**),
`changed_channel_ratio` 0.1132 → 0.1145 (+0.0013). **Page count exact against
the reference: 9 of 10 under cache, 10 of 10 under computed** — the one form
that changes is kstartup, which is *the form where the cache is wrong* (see
*kstartup is the form where the CACHE is wrong, not the flow pass*), and
computed fixes it.

Line breaking, the same corpus, conditional-break agreement (the breaker
restarted at each line start the authoring engine chose, asked only where it
would put the next break): **77 / 216 decisions exact, 0.356**, worst
moel-2025 at 7/47 and best gianmun-2ho at 2/2. Block flow agreement against
the cache is *identical* whether the lines under it are cached or computed —
all ten forms score the same page-assignment hits either way (kstartup
46/165, nrf 51/53, the other eight 100%), so the flow pass's error is its own
and not the breaker's leaking into it.

`render-check-01` is the one document where the policy flip costs **nothing at
all**: its renders are byte-identical under both policies (9 pages either
way), because all 216 of its paragraphs are already excluded from the cache —
`hwpx_write` wrote its `hp:lineseg` and every one of them trips
`textpos_past_end`, so 238 of 238 paragraphs were laid out by this breaker
before the policy existed. Its scoreboard cannot be taken: its sections
declare different page sizes and `render_scoreboard.ssim` refuses operands of
different sizes. Pre-existing, named, not fixed here.

The private report-class holdout (E2.1's, aggregate only) is the sharpest
version of the same answer: 18 reference pages, and **18 pages under both
policies**, while every geometry channel falls — `ssim` 0.6963 → 0.6108,
`ssim_inked` 0.1834 → 0.0982, `text_line_iou` 0.5680 → **0.2311**,
`text_line_pair_rate` 0.9150 → 0.7804, `changed_channel_ratio` 0.1400 →
0.1633. It is a Hancom-saved package, so the policy keeps it on `cache`; the
computed column is what an edit to it would now cost.

**So: is computed good enough to be the default for edited documents?** For
*pagination*, yes and better — page counts hold on 10 of 10 corpus forms and
on the holdout, and the one disagreement it fixes is a real one. For *line
geometry*, no: it is measurably worse wherever the cache is valid, by −0.055
mean IoU on the corpus and −0.337 on the holdout, and on one form (admrul) by
−0.409. That is the honest shape of the trade, and it is the right trade only
because the policy routes a document to computed exactly when its cache is
*not* valid — where the alternative is not this table's cache column but a
layout describing text the document no longer has. What the table really
prices is a **misclassification**: what it costs to call an untouched Hancom
package edited. Nothing here argues for computed as a general default, and
E2.1's *Where it fails, and why* still names the advance-width gap that this
column is mostly measuring.

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
declared `hh:charPr@height` over the characters on the line — and over any
inline object's `hp:sz@height`, which was a measured defect before it was a
rule (see below). The **character metrics stay out of it**: `hh:relSz`,
`hh:ratio` and `hh:offset` change the drawn glyph, not the line's advance.
No corpus form declares any of the three away from neutral, so the corpus
could not have said; `render-check-01`'s `F15` line of `relSz="140"` text on a
10 pt charPr advances 15.950 pt, not the 22.40 a 14 pt line would
(`docs/research/line-and-character-metrics.md` §2). Against the cache, the computed `textheight` is exact
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

| form | paras | line count | break sequence | multi-line | multi-line count | break positions (was) |
| --- | --- | --- | --- | --- | --- | --- |
| admrul | 22 | 22 | 21 | 2 | 2 | 1 / 2 (1) |
| gianmun-1ho | 32 | 32 | 31 | 1 | 1 | 0 / 2 (0) |
| gianmun-2ho | 20 | 19 | 19 | 2 | 1 | 1 / 2 (1) |
| jeongbo | 58 | 58 | 53 | 6 | 6 | 2 / 7 (1) |
| jumin | 133 | 133 | 117 | 27 | 27 | 14 / 36 (9) |
| kstartup | 453 | 434 | 415 | 29 | 26 | 13 / 44 (12) |
| moel-2013 | 263 | 242 | 222 | 34 | 26 | 10 / 49 (7) |
| moel-2025 | 314 | 296 | 271 | 37 | 27 | 7 / 47 (6) |
| nrf | 89 | 89 | 87 | 3 | 3 | 1 / 3 (1) |
| saeopja | 764 | 758 | 749 | 17 | 14 | 9 / 24 (5) |
| **total** | **2148** | **2083** (0.970) | **1985** (0.924) | **158** | **133** (0.842) | **58 / 216** (0.269) (43) |

The bracketed column is what the same run measured before the space became a
half-width cell (*The space is a half-width cell*, below).  The two paragraph
columns moved the other way — 2103 → 2083 and 2003 → 1985 — and that is not
netted out here: a wider space pushes a handful of paragraphs the authoring
engine kept on one line onto two.  The break column is the one that tests the
breaker, and the raster scoreboard moved with it, not against it.

Twelve further paragraphs carry no usable cache and are excluded.

Read honestly, the headline number is the last column and it is **0.269**. The
first two columns are high because a corpus of government forms is
overwhelmingly single-line paragraphs — 2148 paragraphs, only 158 of which
break at all — and a paragraph that cannot break cannot disagree. The multi-line
subset is where the breaker is actually tested, and there it reproduces the
authoring engine's exact line sequence on 35 of 158 (31 before this slice).

### Where it fails, and why — this was an advance-width gap, not a rule gap

Restarting the breaker at each line start the authoring engine chose and asking
only where it puts the *next* break (`conditional_breaks`, error propagation
removed): **53 of 216 exact, 82 too early, 81 too late** — against **45 exact,
29 early, 142 late** before the space became a half-width cell.

`late` dominating by five to one *was* the diagnosis, and it is gone: the
residual is now two-sided within one decision of even, which is what a
corrected systematic bias looks like. `cached_line_fill` — how full the
authoring engine's own line is when this renderer measures it — moves from a
median of **0.92** to **0.97**, and moves toward 1.0 on all ten forms:

| form | fill median, hmtx space | fill median, half cell |
| --- | --- | --- |
| admrul | 0.974 | 1.031 |
| gianmun-1ho | 0.965 | 1.005 |
| gianmun-2ho | 0.943 | 0.987 |
| jeongbo | 0.967 | 1.008 |
| jumin | 0.935 | 0.978 |
| kstartup | 0.924 | 0.966 |
| moel-2013 | 0.820 | 0.892 |
| moel-2025 | 0.849 | 0.907 |
| nrf | 0.936 | 0.982 |
| saeopja | 0.969 | 0.983 |

Eight of the ten now sit inside 2% of 1.0. The two `moel` forms do not, and
they are the two worst break-agreement forms; whatever is left there is a
*second*, smaller term and is not the space. Those two are also the forms whose
declared 한양 faces this machine resolves worst, which is the first thing to
check and is not yet proven to be the cause.

### The space is a half-width cell

The deficit was concentrated in the space character, and the way it was settled
was **not** another sweep against the corpus: the ten Hancom reference PDFs
were read for the advances Hancom itself drew, which is black-box evidence of
the same kind the `hh:spacing` rule already rests on.

Method (`test_the_reference_pdfs_advance_a_space_by_half_the_character_cell`).
For every horizontal text span in every reference PDF, a glyph's advance is the
distance to the *next* glyph's origin, divided by the span's declared size.
Only spans whose every Hangul cell measures exactly 1.000 em are sampled, so no
`hh:ratio`, no 공백 축소 and no justification stretch is acting on the sample.
That leaves 1296 space advances:

| face | n | p10 | median | p90 | the face's own `hmtx` space |
| --- | --- | --- | --- | --- | --- |
| MalgunGothic | 432 | 0.4500 | 0.5000 | 0.5060 | 0.352 |
| Dotum | 420 | 0.4923 | 0.4940 | 0.5068 | 0.334 |
| Batang | 205 | 0.4960 | 0.5000 | 0.5000 | 0.333 |
| DotumChe | 146 | 0.4933 | 0.4933 | 0.5067 | 0.500 (monospaced) |
| MalgunGothicBold | 25 | 0.4930 | 0.5000 | 0.5040 | 0.352 |
| H2hdrM | 10 | 0.5000 | 0.5000 | 0.5000 | 0.333 |

1222 of the 1296 land in [0.49, 0.51]; the residual spread is the PDF's own
text-positioning quantisation. **Five faces whose `hmtx` space advances differ
from one another all render a space at the same 0.50 em, and the one face that
already advances a space by 0.50 em is the monospaced one.** 0.5 is therefore a
property of HWP's cell model, not of any face: the space is the half-width
counterpart of the full-width cell `is_full_width` already states, and
`SPACE_CELL_FRACTION` carries the measurement. `hh:ratio` scales the half cell
exactly as it scales the full one.

Once the space is a half cell, the per-class advance error against the same
PDFs — this renderer's advance for a glyph, against Hancom's median advance for
that same glyph on that same face, weighted by how often it was drawn — is:

| class | distinct glyphs | n | error before | error after |
| --- | --- | --- | --- | --- |
| hangul | 465 | 2009 | −0.0000 em | −0.0000 em |
| space | 6 | 1238 | **−0.1373 em** | **+0.0028 em** |
| digit | 32 | 164 | −0.0021 em | −0.0021 em |
| latin | 19 | 39 | +0.0063 em | +0.0063 em |
| ascii punctuation | 37 | 275 | +0.0036 em | +0.0036 em |
| fullwidth / CJK punctuation | 2 | 2 | −0.0120 em | −0.0120 em |
| other | 15 | 53 | +0.0016 em | +0.0016 em |

The space was the only class out by more than 0.007 em, and it was out by
twenty times that. `test_no_glyph_class_is_measured_more_than_a_hundredth_of_
an_em_out` pins the bound. Faces this machine has not got installed are
skipped rather than substituted — a substitute would measure the substitution.

**Scope, and what is not proven.** Every reference render in this corpus is a
Korean form. Whether HWP takes a Latin-face space from `hmtx` in a document
with no Hangul in it at all is *not* measured here; the rule is applied
uniformly and declared in the sidecar (`half_width_space_cell` in `applied`).

### One holdout document, which never entered the decision

The ten corpus forms are the measuring stick, and the reference PDFs the rule
was read off are the same ten documents. That is a real circularity risk even
though the rule was read off glyph advances rather than off break positions, so
it was checked against a document outside the set: a private report-class
`.hwpx` (Batang body text, 415 scored paragraphs, 260 cached break positions)
that has never been part of this corpus. Only aggregates are recorded here; the
document itself stays local and is not quoted.

Its own Hancom PDF, measured the same way: 467 space advances on spans whose
Hangul cells are exactly 1.000 em, median **0.4933**, p10 0.4933, p90 0.5067,
against Batang's `hmtx` space advance of 0.333. The rule reproduces on a face
and a document class the corpus does not cover.

| | hmtx space | half cell |
| --- | --- | --- |
| break positions | 37 / 260 | **71 / 260** |
| conditional exact / early / late | 63 / 39 / 158 | **108** / 115 / 37 |
| paragraph line count exact | 400 / 415 | **407 / 415** |
| paragraph sequence exact | 336 / 415 | **349 / 415** |
| multi-line count exact | 68 / 83 | **75 / 83** |
| `cached_line_fill` median | 0.9382 | **0.9801** |

Every channel improves here, including the two paragraph columns that went the
other way on the corpus — a report is mostly multi-line prose, which is exactly
the case the corpus of forms barely exercises. The residual has flipped sign
(115 early against 37 late) rather than shrinking to nothing, which says the
same thing the corpus does: something smaller is still unaccounted for, and it
is no longer the space.

### What was measured and rejected

- **0.45 em for the space** — the fit the previous slice found. Re-run against
  the corpus it is still the peak: 0.40 / 0.45 / 0.48 / 0.50 / 0.52 / 0.55 em
  score 57 / **69** / 62 / 58 / 51 / 47 break positions of 216. It buys 11 more
  than the measured 0.50 and is **not adopted**, because the reference PDFs say
  0.50 on every face and the corpus break positions are the measuring stick,
  not the training set. That 0.45 outscores the truth is itself information: it
  is absorbing some *other* residual, which is where the next slice should
  look.
- **Integer HWPUNIT per glyph instead of float accumulation.** Rounding every
  advance and every letter-spacing gap to whole HWPUNIT before accumulating
  changes **nothing at all**: 58/216, 53/216 conditional, 2083 line counts —
  every number identical. The quantum is 0.001 em at 10 pt, an order of
  magnitude below the residual per-class error, so it cannot be the term.
  Rejected as unmeasurable rather than as wrong.
- **`hh:ratio` not applied to the space cell.** 58/216 break positions either
  way, one line count and one sequence *worse* without it. Kept, because the
  full-width cell rule scales by `hh:ratio` and the half cell should not be a
  special case for the sake of nothing.
- **`hh:spacing` opening no gap adjacent to a space** (자간 as strictly
  letter-spacing). This was named as "the first thing to try next" when it
  bought +10 break positions against the old space model. Tried: against the
  half cell it now *costs* 13 — 58 → 45 break positions, 53 → 41 conditional,
  2083 → 2025 line counts. It was compensating for the space bug. Rejected,
  and the E2.3 drawing pin that made it doubtful is intact.
- **Which face Hancom takes a space from** (the Hangul face for Hangul runs,
  the Latin face for Latin runs) — the question does not arise. The half cell
  consults no face at all, which is why six faces with four different `hmtx`
  space advances all render at 0.50.

### Incremental relayout, and what it does not do

Paragraphs after a relaid-out one in the same container are shifted by its
height change, so an edited paragraph cannot be drawn over its neighbour; and
a table's row heights are now solved *after* its columns, from the layout each
paragraph will actually get, so an edited cell grows its row instead of
overflowing it. Cell content is vertically centred against the same measured
block, not against the cached one.

That was the whole of the incremental relayout in E2.1, and it was explicitly
not E2.5: nothing reflowed onto another page and a relaid-out paragraph still
*started* where the cached layout put it. **E2.5 closes that** — see *Block
layout and page reflow* below. Inside a table cell the paragraph-shift model
above is still what runs; the flow pass owns the section body.

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

**The cached box is not always what JUSTIFY stretches to.** The line above —
"`horzsize` stays the full column even for a centred line" — turned out to be
a corpus-only reading. On a private report-class holdout (prose body text,
485 paragraphs, 415 scored), 123 body paragraphs' interior JUSTIFY lines all
stretched to a cached `hp:lineseg@horzsize` that was a document-wide-constant
**853 HWPUNIT** short of the paragraph's own available width — verified
against the reference PDF, whose measured line right-edges (`PyMuPDF`
`get_text("words")`, grouped into lines) land on the *wider* figure
(`avail_w_hwp`, the same box `--line-layout computed` already used), not the
narrower cached one. Right-edge agreement (nearest reference line by
y-position, matched within 0.5 em) measured **29/239 lines (12.1%)** before a
fix and **208/239 (87.0%)** after, at 144 dpi. The remaining ~13% are mostly a
crude line-matcher artifact (nearest-y matching against a multi-column or
figure-adjacent reference line), not a residual alignment bug — see
`docs/research/` for the run this measured.

The fix is `_draw_line`'s `stretch_avail_hwp`: a box computed *separately*
from the one used for `LEFT`/`CENTER`/`RIGHT` offset and for
`line_boxes` bookkeeping, used only to size `JUSTIFY`/`DISTRIBUTE` slack, and
only ever `max()`-widened against the cached `horzsize` — never narrowed. For
a cached line, that box is `avail_w_hwp - horzpos - margin_right` (the same
quantity `_line_box` computes for a freshly-broken line); for a computed
line, `avail_hwp` already *is* that quantity, so nothing changes there. This
also protects the opposite case, seen on several corpus forms (table cells
whose cached box is *wider* than the cell `avail_w_hwp` this renderer
computes — up to 689 HWPUNIT on moel-2013): `max()` leaves those untouched,
which is why the ten-form regression floor's pass/blocked verdicts are
byte-for-byte identical before and after (per-form `ssim_inked_mean` moves by
≤0.0003 either direction). On the holdout: `text_line_iou_mean` 0.5349 →
0.5389, `ssim_inked_mean` 0.1289 → 0.1295, page-11 `text_line_iou` (candidate
lines) 0.6144 → 0.6188 — a real but modest aggregate move, because the two
other named mechanisms on that page (equation glyphs not math-italic, the
double-rule box border) are untouched by this slice.

**Inline vs anchored objects.** `hp:pos@treatAsChar="1"` objects are laid out
*inside* the line (they consume width and participate in alignment); anything
else is placed from `@horzOffset`/`@vertOffset` against the frame
`@horzRelTo`/`@vertRelTo` names. Getting this wrong is visible: gianmun's
발신명의 box sat at the left margin instead of centred, and the 직인 box sat on
top of it, until inline objects joined the line.

## Block layout and page reflow (E2.5)

`paginate()` *reads* the page assignment the authoring engine left in the
cached `vertpos`. `OwnRenderer.flow()` *computes* one: it stacks every
top-level block down the column from its own measured height and decides,
itself, where a page ends. The two are deliberately separate, because the only
honest way to grade a flow pass without a reference render is to run it on an
**unedited** document and ask how far it lands from the cache — which is what
`--flow-agreement` does, and what the table below reports.

### Two policies, and why an unedited render is byte-identical

- **`auto`** (default, and what ships). On a package provenance says is
  Hancom's own untouched save, nothing is placed by the flow pass at all:
  `flow_plan()` returns `None` and `render()` takes exactly the path it took
  before E2.5. Measured, not asserted: all ten corpus forms, 51 pages, render
  to **byte-identical PNGs** before and after this slice, and the seven
  comparable scoreboards are unchanged to every decimal place they carry.
  (Still true after the provenance policy: the ten forms plus
  `render-check-01` are byte-identical at 96 dpi against pre-policy HEAD.)
  On any other package `auto` resolves to `computed` for the whole document —
  see *Which engine laid out which paragraph* — so the incremental
  "seed the flow at the edited block" path below is reached only under a
  pinned `cache` policy. It is kept, and kept measured, because it is the
  right answer once an edited package can be trusted paragraph by paragraph
  again; it is not the shipping answer today.
- **`computed`** (`--block-layout computed`). The flow pass places every block
  from the top of the document. This is how the flow pass is *measured*.

When a paragraph *is* relaid out, the flow pass is seeded at that block's own
cached page and cached top and takes over from there: **nothing above an edit
moves, everything after it is re-placed.** The sidecar's `block_layout` says
so per block (`placement: cached | flowed`) and per page (`page_reflowed`),
alongside `first_flowed_block` and the `flow_counters` below.

### The inter-paragraph advance is the declared margin — in the right unit

Where the next top-level paragraph starts:

```
next.first.vertpos == prev.last.vertpos + prev.last.vertsize
                    + prev.last.spacing
                    + prev.margin_next + next.margin_prev
```

with both margins **in HWPUNIT**. This used to read `/ 2`, because the advance
the authoring engine leaves really is half of what the corpus paraPr appear to
declare — 200/600/1000/2000 declared against 100/300/500/1000 laid out; face
value held on 334 of the corpus's 539 adjacent top-level pairs, halving each
side on 534.

The half was the **unit**, not the rule. Every corpus `hh:paraPr` wraps its
`hh:margin` and `hh:lineSpacing` in the MCE `hp:switch`, and a length in the
`hp:default` branch — the branch a reader without the 2016 `HwpUnitChar`
namespace must take — is in a unit exactly half a HWPUNIT: over 811 corpus
paraPr the ratio `default / case` is 2.0 without exception on `intent` (328),
`left` (116), `right` (54), `prev` (143), `next` (11) and the one `FIXED`
`lineSpacing`, and 1.0 on all 806 `PERCENT` values, a percent being no length.
`_para_pr_geometry_source` now converts at the parse; `PARA_MARGIN_SCALE` is
gone, and `left`/`right`/`intent` — which the old constant never touched, so
they were being read doubled — are right for the first time.

The reference-side half of this is Hancom's own render of
`tests/corpus/render-check/render-check-01.hwpx`, an `.hwpx` authored with no
switch at all: its bare `<hc:prev value="600" unit="HWPUNIT"/>` leaves exactly
6.00 pt. One rule now fits both, with corpus flow agreement unchanged at
542/590 blocks. See `docs/research/line-and-character-metrics.md` §6.

### An anchored object reserves its extent, and that was the whole of kstartup

An **anchored** (`treatAsChar="0"`) object whose `@textWrap` is
`TOP_AND_BOTTOM` — 80 of the corpus's 81 tables — reserves its own declared
extent in the flow: the next block starts below it, not beside it. kstartup
anchors a full-page table to a paragraph whose own line box is 1600 HWPUNIT
tall, and the authoring engine starts the next paragraph **68032** HWPUNIT
further down. Before this rule the flow pass put 49 of that form's 165 blocks
on the right page and nrf 6 of 53; with it, nrf goes to 51 of 53 and the
adjacent-pair relation above holds on 142 of kstartup's 145 pairs.

This is *not* text wrapping around the object, which this tier still does not
do (limit 17). It is the conservative reading, and no corpus form carries a
small floated object that would distinguish the two.

### What the flow pass honours

Read and acted on: page height with the top/bottom margin (`hp:pagePr`),
`hp:p@pageBreak` and `hh:breakSetting@pageBreakBefore`, `hp:p@columnBreak`
(**as a page break** — every corpus `hp:colPr` declares `colCount="1"`, so
there is no second column to break into and the sidecar says that rather than
dropping the instruction), `@keepLines`, `@widowOrphan`, `@keepWithNext`,
`hp:tbl@pageBreak`, `hh:margin/hh:prev` and `/hh:next`, and the anchored-object
reserve above.

Three of those are implemented and **not exercised by this corpus**, which is
worth saying plainly: all 774 corpus `breakSetting` carry `keepLines="0"`,
`keepWithNext="0"` and `pageBreakBefore="0"`, and the 3 that carry
`widowOrphan="1"` sit on paragraphs that never split. They are honoured on the
strength of the spec, and the counters in `block_layout.flow_counters` are the
channel that will say when one first fires.

Parsed and **not** acted on, named in every sidecar: multi-column text,
`hp:tbl@repeatHeader` on a split table, text wrap around an anchored object, a
block taller than one page (placed and allowed to overflow, because no rule
can make it fit), headers/footers/notes taking room in the flow, and any
section past `section0`.

**Table splitting.** A table is split at a row boundary only when **both**
halves of the permission hold: it declares `hp:tbl@pageBreak="CELL"`
(셀 단위로 나눔) **and** it is anchored rather than 글자처럼 취급
(`hp:tbl/hp:pos@treatAsChar="0"`). `NONE` (나누지 않음) and `TABLE`
(표 단위로 나눔) both move the whole table to the next page, and so does every
inline table whatever it declares. The corpus declares CELL on 62 tables and
NONE on 19; `TABLE` never appears and is grouped with `NONE`.

The second half is measured, not read off the schema: Hancom never splits an
inline table — eleven probe variants and three Hancom-authored controls, no
exception ([`docs/research/table-page-break-rule.md`](../../docs/research/table-page-break-rule.md)).
An inline table that does not fit the room left moves whole; one that does
not fit a whole page is drawn from the top of that page and allowed to
overflow, which is what Hancom does with its own. The fit test for such a
line clears the table's **whole** height rather than the usual `baseline`
allowance (`_row_extent`) — a table has no descender to hang past the margin.

A split leaves two placement records carrying the row range each page draws,
and `_render_table` draws exactly that range with the row origin pulled back
— the continuation page does **not** repeat the header row, where Hancom's
anchored split does.

### How well the flow pass agrees with the engine that wrote the file

`python own_render.py FORM.hwpx --flow-agreement` reproduces every number
below; the committed run is
`engine/references/own-render-samples/e2.5-flow-agreement.json`. Line layout
stays `auto`, so a disagreement here is the **block** model's and not the line
breaker's. `dy` is HWPUNIT from the top of the body box, the same origin
`hp:lineseg@vertpos` uses.

| form | blocks | page agreement | median \|dy\| | p90 | max | pages computed / cached |
| --- | --- | --- | --- | --- | --- | --- |
| admrul-gajokdolbom-hyuga-sinchengseo | 15 | 15 / 15 (1.000) | 0 | 0 | 0 | 1 / 1 |
| gianmun-byeolji-1ho | 3 | 3 / 3 (1.000) | 0 | 0 | 0 | 1 / 1 |
| gianmun-byeolji-2ho | 3 | 3 / 3 (1.000) | 0 | 0 | 0 | 1 / 1 |
| jeongbo-gonggae-cheongguseo | 1 | 1 / 1 (1.000) | 0 | 0 | 0 | 1 / 1 |
| jumin-deungchobon-sinchengseo | 3 | 3 / 3 (1.000) | 0 | 0 | 0 | 3 / 3 |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | 165 | 46 / 165 (0.279) | 0 | 0 | 69785 | **22 / 20** |
| moel-pyojun-geunrogyeyakseo-2013 | 154 | 154 / 154 (1.000) | 0 | 0 | 0 | 7 / 7 |
| moel-pyojun-geunrogyeyakseo-2025 | 187 | 187 / 187 (1.000) | 0 | 0 | 1000 | 7 / 7 |
| nrf-gyeolgwa-bogoseo-yangsik | 53 | 51 / 53 (0.962) | 0 | 5120 | 71630 | 4 / 4 |
| saeopja-deungnok-sinchengseo | 6 | 5 / 6 (0.833) | 0 | 72538 | 72538 | 6 / 6 |
| **total** | **590** | **468 / 590** (0.7932) | **0** | | | |

Read honestly: **0.793**, and the median `|dy|` is 0 on every one of the ten
forms — where the flow pass puts a block on the right page, it puts it at
exactly the cached vertical position. 117 of the 122 misses are one form.

`--flow-agreement --line-layout computed` compounds the two errors instead of
isolating the block model, and it is the channel `_line_metrics` is graded on.
The object-line rules (`docs/research/object-line-box.md`) move it from
**344 / 590** pages and 119 / 590 exact `dy` to **392 / 590** and
**216 / 590**, with no form worse on either count: `kstartup` computes 22
pages (its reference's own count) where it computed 27, and `gianmun-1ho`,
`gianmun-2ho` and `admrul` each drop from 2 to their cached 1. The `auto`
column above does not move at all — it reads the cached line boxes — which is
what keeps the shipping render byte-identical on 51 of the corpus's 52 pages.

### kstartup is the form where the CACHE is wrong, not the flow pass

kstartup's 0.279 is not a flow-pass failure and reporting it as one would be
dishonest. The disagreement is a **constant two-page offset from block
position 48 onward, with `dy = 0` on 111 of the 117 blocks in it** — the flow
pass puts every block at the cached vertical position, two pages later. It
does that because `paginate` merges two pages the authoring engine did break:
the paragraph after a full-page anchored table does not restart at
`vertpos = 0`, so the backwards-jump heuristic never fires there.

Which of the two is right is settled by the reference PDF, not by either of
them. Scored against Hancom's own render of the same form
(`kstartup-….{before,computed}-e2.5.scoreboard.json`):

| | pages | `page_count_exact` | line-box IoU | pair rate | `ssim` | `ssim_inked` |
| --- | --- | --- | --- | --- | --- | --- |
| `auto` (what ships) | 20 | **false** | 0.2542 | 0.7988 | 0.8112 | 0.2313 |
| `computed` (flow pass) | **22** | **true** | **0.5921** | **0.8949** | 0.8436 | 0.2122 |
| Hancom reference | 22 | — | — | — | — | — |

The flow pass computes the reference's page count from the geometry alone, and
line-box IoU more than doubles. `ink_delta_abs_max` moves the other way
(0.0375 → 0.0621 against a 0.05 bound) and is now the only floor check the
form fails, where before it failed `page_count_exact` instead.

It is **not** switched on by default, because `auto` is defined as "keep the
cache until something is edited" and that definition is exactly what makes an
unedited render byte-identical. Whether `auto` should prefer the flow pass
*when the two disagree* is a policy question, and answering it for all ten
forms needs the reference renders the first item of *Remaining order of work*
is about.

### The scoreboard, before / after / computed

Means over the seven comparable forms (the three reduced references are
excluded — see *Three of the ten reference PDFs are not 1:1 renders*):

| | `ssim` | `ssim_inked` | line-box IoU | pair rate |
| --- | --- | --- | --- | --- |
| before (E2.4) | 0.7354 | 0.1347 | 0.4747 | 0.8012 |
| after (`auto`, what ships) | 0.7354 | 0.1347 | 0.4747 | 0.8012 |
| `computed` (the flow pass) | 0.7355 | 0.1282 | **0.5055** | **0.8135** |

The shipping row is not "close to" unchanged, it *is* unchanged — the same
statement as the byte-identity, measured a second way. The honest measure of
the flow pass is the third row: placing every block ourselves *gains* 0.031 of
line-box IoU and 0.012 of pair rate against the authoring engine's own cached
positions, and costs 0.006 of `ssim_inked`. Per form it is dominated by
kstartup (0.2542 → 0.5921); it is worse on `saeopja` (0.5562 → 0.4706, where
the flow splits a table the cache kept whole) and on `moel-2025`
(0.5167 → 0.4803), and unchanged on the other four.

### One holdout document, which never entered the decision

Both rules above were fixed on the ten public corpus forms, so they were then
checked against a document outside that set: the same private report-class
document *One holdout document* (E2.1) used — 18 pages of prose, figures,
equations and tables. It is not in this repo and nothing from it is quoted;
only the aggregate below leaves the machine.

- **The adjacent-pair advance relation holds on 225 of 225 pairs, exactly.**
  The half-margin and the anchored-object reserve were derived from
  government forms and transfer to a report-class document without a single
  miss. That is the strongest evidence in this slice that the block-stacking
  model is a rule and not a corpus fit.
- **Page assignment: 189 of 243 blocks (0.778)**, and the page *count* comes
  out exactly right — 18 computed against 18 cached.
- **Vertical position drifts: median `|dy|` 17821 HWPUNIT (356 px at 144 dpi),
  signed median +3600 — the flow pass places content *lower*.** With the
  advance relation exact, the drift cannot be the advance: every one of the 54
  misses is a block one page late, and everything on a page whose break landed
  differently sits at a different offset.

### Where the page break is still wrong, measured and NOT tuned

The flow pass breaks a page the moment a line's box no longer fits inside
`usable_height`. The authoring engine is looser than that. Measured on the
cached layout, the deepest line box on a page, as a fraction of the usable
box, ignoring the trailing spacing:

| document | median fill | max fill |
| --- | --- | --- |
| jeongbo | 0.9996 | 0.9996 |
| saeopja | 0.9902 | 1.0172 |
| kstartup | 0.9875 | — (the wild-`vertOffset` anchor, limit 12) |
| moel-2013 | 0.9806 | 1.0680 |
| nrf | 0.8097 | 1.0251 |
| holdout (report-class) | 0.9961 | 1.0080 |

Four documents put a line box **past** the bottom of the usable box and keep
it on the page anyway. A strict fit test therefore breaks one line early
wherever that happened, and that is what the holdout's 54 late blocks are.

The obvious move — a tolerance on the fit test — is deliberately **not**
taken. A tolerance chosen to make these ten forms agree is a corpus fit, not a
rule, and the corpus is the training set. What the residual needs is the same
treatment the space cell got: a measurement of what Hancom actually does at a
page bottom, off the reference renders, and then a rule. Until then this is a
named, unexplained, one-sided residual, and the numbers above are what it
costs.

### What a reflowed document still does not get

Measured on the edited-document fixture (`moel-2025`, one paragraph
lengthened until it outgrows its page): 7 pages become 9, the paragraph after
the edit moves from page 1 to page 2, nothing above the edit moves, and **no
line box leaves the body box on any page** — the last of which is the specific
defect E2.1 named and left open. What it still does not get is limits 16-18:
no repeated header on a split table, no text wrapping beside an anchored
object, and a `keepWithNext` chain that gives up rather than looping.

## Headers, footers, notes (E2.6)

`hp:header` and `hp:footer` are controls, exactly like `hp:pageNum`: they sit
in an `hp:ctrl` inside a run of a body paragraph and carry their own
`hp:subList`, not children of `hp:secPr`. `hp:footNote` and `hp:endNote` are
controls too, and their position in the run stream IS the reference position,
so a raised, reduced numeral is drawn there and the note body is drawn
elsewhere. `_furniture_scan` walks the top-level blocks once for all four at
once and stops at each, so a header's own paragraphs are never rescanned for
a note.

### Honoured

- **Header / footer.** Drawn in the areas `hh:margin@header` / `@footer`
  declare — `[top, top + header]` and `[height - bottom - footer,
  height - bottom]` — from the top of the area, per `@applyPageType`
  (`BOTH` / `EVEN` / `ODD`) and `hp:visibility@hideFirstHeader` /
  `@hideFirstFooter`.
- **Footnote.** Collected per page in flow order, set bottom-anchored inside
  the body box above the footer area, with the `hp:footNotePr` separator
  line, `@aboveLine` / `@belowLine` / `@betweenNotes` spacing, and
  `hp:autoNumFormat` prefix/suffix numbering. Under `--block-layout computed`
  the flow pass subtracts the block's own height from `usable_height` on the
  page its block starts on, *during* the placing sweep (one bounded retry —
  `NOTE_FLOW_MAX_PASSES` governs the reserve-settle loop, not this retry —
  when the reserve itself pushes the block to the next page). Under the
  shipping `auto` policy nothing can be reserved, so a collision with the
  cached layout is detected and named per render
  (`note_collisions`, `"hp:footNote block over body text"`).
- **Endnote.** Collected in document order, set after the last page's inked
  body text, with the `hp:endNotePr` separator and spacing. Unlike a
  footnote, an endnote block is not bound to one page, so continuation IS
  implemented here — at a note boundary: a note that does not fit the room
  left starts the next page whole.
- **Numbering.** `DIGIT` format only; `CONTINUOUS` starts at 1 (every corpus
  form's `@newNum` is a writer-internal id, not a start number — see
  `test_a_continuous_numberings_newnum_is_not_a_start_number`); a restart
  type (e.g. `ON_SECTION`) uses `@newNum` as the start. Footnotes and
  endnotes are separate numbering sequences.
- **Determinism.** A page carrying a header, a footer, a footnote and an
  endnote renders to identical bytes twice
  (`test_a_page_with_furniture_renders_deterministically`).
- **Line-box provenance.** Every line box now carries which piece of
  furniture drew it in its `mode` field (`header` / `footer` / `footnote` /
  `endnote`, alongside `lineseg` / `computed`), so a reference-PDF comparison
  can include or exclude furniture.

### Declared-skipped, not honoured

- `hp:masterPage` — neither read nor drawn.
- A header or footer taller than its declared `hh:margin` area is drawn at
  full height into the body box, not clipped and not grown into; the body
  box is NOT shortened by the overrun, so such content and the first body
  line can collide.
- Note continuation across a page boundary (a single note split mid-body) is
  not implemented; a footnote that does not fit its reserved block is
  DROPPED and named, never drawn outside its box.
- `hp:footNotePr/hp:placement@place` — only the bottom-of-body placement is
  drawn; `EACH_COLUMN` and beneath-text are read and not acted on, because
  this tier is single-column.
- `hp:endNotePr/hp:placement@place` — `END_OF_DOCUMENT` and `END_OF_SECTION`
  are the same thing here, because only `section0` is laid out.
- `hp:noteLine@length` non-positive (every corpus form: `-1`) is read as "the
  default", which KS X 6101 does not publish; 5&nbsp;cm is drawn and named as
  this renderer's reading (`NOTE_LINE_DEFAULT_HWP`).
- The reference mark's own character-cell width/height
  (`NOTE_MARK_RELSZ` = 65%, `NOTE_MARK_RAISE` = 0.35 em) is this renderer's
  reading of how `hp:lineseg@textpos` counts a note control, not a
  measurement.
- A single endnote taller than the body box is set from the top of its own
  page and allowed to overflow — the same answer this tier already gives a
  block taller than a page.

**Where an endnote is set is `hp:endNotePr/hp:placement@place`, and it is
MEASURED.** `END_OF_DOCUMENT` means the end of the DOCUMENT: every section
that is not the last hands its endnotes forward, and the last section sets
the lot, in spine order, after its own last page. `END_OF_SECTION` keeps the
old behaviour — each section sets its own. Until this was measured both
readings collapsed to "end of the section that authors the note", which cost
a page on `render-check-01`: its one `hp:endNote` is authored in section 0,
did not fit under the `F47` table that already overflows the body box, and
took a page of its own — candidate 10 pages against Hancom's 9. Hancom sets
that note on page 9 of 9, the last page of the document, under the page's
last inked line (separator y=464.5 pt, note body y=470.5–478.5 pt, last body
line ending 456.3 pt). With the rule in, `render-check-01` is **9 pages
against 9, exact for the first time**, and its page agreement is 51/51
(docs/research/render-check-01.md note 1). Still NOT honoured: Hancom sets
the note in the FIRST COLUMN of that two-column section (separator
x 85.0–297.7 pt) and this renderer sets it at the body box's full width —
declared in the sidecar, a band difference and not a page-count one. No
corpus form and no holdout carries an endnote, so the corpus render is
byte-identical (52/52 page PNGs, sha256) and the holdout stays 18/18 exact
with every scoreboard channel unchanged.

### Corpus coverage: none of the four is exercised

`grep`-equivalent scan of every `Contents/section*.xml` inside the ten
corpus `.hwpx` files (`tests/corpus/forms/converted/*.hwpx`) for
`hp:header`, `hp:footer`, `hp:footNote`, `hp:endNote`:

| form | header | footer | footNote | endNote |
| --- | --- | --- | --- | --- |
| admrul-gajokdolbom-hyuga-sinchengseo | – | – | – | – |
| gianmun-byeolji-1ho | – | – | – | – |
| gianmun-byeolji-2ho | – | – | – | – |
| **jeongbo-gonggae-cheongguseo** | **1 (empty)** | – | – | – |
| jumin-deungchobon-sinchengseo | – | – | – | – |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | – | – | – | – |
| moel-pyojun-geunrogyeyakseo-2013 | – | – | – | – |
| moel-pyojun-geunrogyeyakseo-2025 | – | – | – | – |
| nrf-gyeolgwa-bogoseo-yangsik | – | – | – | – |
| saeopja-deungnok-sinchengseo | – | – | – | – |

`jeongbo` is the one form with an `hp:header`, and its `hp:subList` carries
paragraphs with no characters at all — an empty header, asserted by
`test_the_corpus_carries_exactly_one_header_and_no_footer_or_note`. No corpus
form and no private report-class holdout carries a footer, a footnote or an
endnote. **Every geometry in this lane is therefore pinned by synthetic
fixtures and by KS X 6101, not measured against a Hancom reference render**
— the sidecar's `page_furniture.evidence` says so on every render.

### Before / after, measured

Because the one corpus header that now draws is empty, the prediction is that
nothing moves. Re-rendered `tests/corpus/forms/converted/*.hwpx` against
their `tests/corpus/forms/render/*.pdf` at 144 dpi, `7b04653` (pre-E2.6,
scratch worktree) vs this branch (post-E2.6, all three commits):

| form | ssim | ssim_inked | line-box IoU | pair rate | PNG sha256 |
| --- | --- | --- | --- | --- | --- |
| admrul-gajokdolbom-hyuga-sinchengseo | unchanged | unchanged | unchanged | unchanged | identical |
| gianmun-byeolji-1ho | unchanged | unchanged | unchanged | unchanged | identical |
| gianmun-byeolji-2ho | unchanged | unchanged | unchanged | unchanged | identical |
| **jeongbo-gonggae-cheongguseo** | **unchanged** | **unchanged** | **unchanged** | **unchanged** | **identical** |
| jumin-deungchobon-sinchengseo | unchanged | unchanged | unchanged | unchanged | identical |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | unchanged | unchanged | unchanged | unchanged | identical |
| moel-pyojun-geunrogyeyakseo-2013 | unchanged | unchanged | unchanged | unchanged | identical |
| moel-pyojun-geunrogyeyakseo-2025 | unchanged | unchanged | unchanged | unchanged | identical |
| nrf-gyeolgwa-bogoseo-yangsik | unchanged | unchanged | unchanged | unchanged | identical |
| saeopja-deungnok-sinchengseo | unchanged | unchanged | unchanged | unchanged | identical |

All ten forms, including jeongbo, score exactly the same `ssim_mean`,
`ssim_inked_mean`, `text_line_iou_mean` and `text_line_pair_rate_mean` to
every decimal place `render_scoreboard.py` carries, and every page PNG
(51 pages total) hashes identical before and after. The three-commit slice
moved zero pixels on the public corpus; what it moved is jeongbo's sidecar
(`paragraphs` 77→78, `runs` 104→105, `elements_rendered.headers` 0→1,
`hp:header` leaving `elements_skipped`) and the four counters
(`headers`/`footers`/`footnotes`/`endnotes`) now present in every sidecar.

### What synthetic fixtures cover, since the corpus does not

`_note_renderer` / `_furniture_renderer` (`engine/tests/test_own_render.py`,
~line 260 on) build a minimal `hp:header` / `hp:footer` / `hp:footNote` /
`hp:endNote` directly into a corpus form's XML tree, so the following are
asserted rather than only claimed:

- **Inside the declared area.** A header's and a footer's ink lands in
  `[top, top+header]` / `[height-bottom-footer, height-bottom]`
  (`test_a_header_and_a_footer_land_in_the_areas_the_margins_declare`,
  `test_the_header_area_moves_with_the_declared_header_margin`); a
  footnote block's ink never exceeds the body floor
  (`test_a_footnote_is_drawn_at_the_bottom_of_the_body_box`).
- **Body height reduced.** Under `--block-layout computed` the per-page
  reserve equals the note block's own measured height, exactly
  (`test_the_flow_pass_shortens_the_page_by_exactly_the_footnote_block`);
  growing `hp:footNotePr/hp:noteSpacing@aboveLine` grows the reserve by the
  same delta (`test_the_separator_spacing_comes_from_footnotepr`).
- **No overflow.** A footnote that does not fit its reserve is dropped and
  named, and no line box lands past the body floor
  (`test_a_footnote_that_does_not_fit_is_dropped_and_named_not_overflowed`);
  an endnote taller than the body box is set and named, not hidden
  (`test_an_endnote_taller_than_one_page_is_declared_not_hidden`); the
  `auto` policy's inability to reserve is detected and named, not silently
  overdrawn (`test_the_cached_page_assignment_cannot_reserve_and_says_so`).
- **Numbering.** `hp:autoNumFormat` prefix/suffix is honoured
  (`test_note_numbering_follows_autonumformat`); an unimplemented format is
  declared, not guessed (`test_an_unimplemented_numbering_format_is_declared_not_guessed`);
  `CONTINUOUS`'s `@newNum` is not mistaken for a start number, and a restart
  type's is (`test_a_continuous_numberings_newnum_is_not_a_start_number`);
  footnotes and endnotes number independently
  (`test_footnote_and_endnote_numbering_are_separate_sequences`).
- **Continuation and determinism.** Endnotes continue onto a new page at a
  note boundary (`test_endnotes_continue_onto_new_pages_at_a_note_boundary`);
  a page carrying all four furniture kinds renders byte-identically twice
  (`test_a_page_with_furniture_renders_deterministically`); every line box
  names the furniture that drew it
  (`test_every_line_box_says_which_furniture_drew_it`).

### Not proven

No claim here is checked against a Hancom reference render: nothing in
`tests/corpus/forms/render/*.pdf` and nothing in the private report-class
holdout carries a footer, a footnote, or a non-empty header, so the areas,
the separator default, the reserve arithmetic and the reference-mark cell are
all geometry asserted against this renderer's *own* measurements, not against
what Hancom actually draws. Whether a real Hancom header/footer/note
document agrees with any of this is open until such a document — or a
regenerated 1:1 reference PDF for one — enters the corpus.

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
   for two strokes and a gap, and it stays solid and says so. `DASH` is now
   drawn dashed at a measured period — see *Dashed borders* below. `CIRCLE`
   (moel-2013, 3 sides) is still a solid line of the declared width, named
   per side in the sidecar: its rules produce no resolvable dotted run in
   that form's reference PDF, so there is nothing to measure it against.
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
7. **Multi-column text (`hp:colPr`) is honoured for equal-width columns
   (E2.7); unequal widths and vertical text are declared, not guessed.**
   `colCount>1` with `sameSz="true"` fills column 1 top-to-bottom, then
   column 2, and so on, then the page — the flow pass models a column as a
   narrower virtual page (`flow`'s *Columns*), so this reuses the same
   overflow mechanism a page break already has, not a second one.
   `sameSz="false"` (per-column `hp:colSz`) and a non-`HORIZONTAL`
   `hp:secPr@textDirection` both render as a single column instead, named in
   `elements_skipped`. `hp:colPr/hp:colLine` (the column separator) is drawn
   when declared. **No corpus form declares `colCount>1`**, so this is pinned
   entirely by synthetic fixtures built from a corpus form's own section
   (`engine/tests/test_own_render.py::_column_fixture`), not measured against
   any reference render. A footnote's reserve is computed per COLUMN rather
   than per page when both are present — declared, and untested: no fixture
   combines the two.
8. **Every section is laid out, in `content.hpf` spine order (E2.7).**
   `spine_section_order` reads the OPF manifest+spine, falling back to a
   numeric filename sort (`section10` after `section2`, not before it as a
   string sort would put it) when the manifest carries no usable spine —
   which is every corpus form measured, since none has more than one
   section. Each section supplies its own `hp:pagePr` (size, margins,
   header/footer heights), its own `hp:startNum@page` page-number
   restart-or-continue, and its own `hp:colPr`; a section always starts a new
   page. Declared, not measured: footnote/endnote `CONTINUOUS` numbering
   restarts at 1 in every section rather than carrying on from the last, and
   a document mixing `END_OF_DOCUMENT` and `END_OF_SECTION` across sections
   is untested (one document, one note, measured); and
   a section with real columns is ALWAYS placed by the computed flow pass
   (never seeded from the cache) — so an unedited multi-column section does
   NOT render byte-identical the way every single-column section on this
   corpus still does. Pinned by synthetic fixtures
   (`engine/tests/test_own_render.py`, spine-order/geometry/page-numbering
   tests); the private report-class holdout (E2.1's) has exactly one section
   and `colCount=1`, so it exercises neither path.
9. **Headers, footers, footnotes and endnotes ARE drawn (E2.6); master pages
   are not.** See *Headers, footers, notes (E2.6)* for what is honoured, what
   is declared-skipped, and why none of it is measured against a Hancom
   reference render. `hp:pageNum` — 쪽 번호 매기기 — is a control, not a footer
   paragraph, and is stamped on every page at a measured position; see
   *Report-class documents*. `BOTTOM_LEFT`, `BOTTOM_CENTER` and
   `BOTTOM_RIGHT` only — every other `pos` is declared and nothing is drawn
   for it.
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
12. **`kstartup-jiwon-sincheongseo-saeopgyehoekseo` paginates wrong under
    `auto` — and E2.5 says why, and computes it right.** The shipping path
    reads the page assignment out of the cached `vertpos`, and on this form
    that heuristic is wrong: the paragraph after a full-page **anchored**
    table does not restart at `vertpos=0`, so `paginate` merges pages the
    authoring engine did break. It reads 20 pages where the Hancom reference
    has 22, and one candidate page carries the content of three. Run with
    `--block-layout computed` the flow pass computes **22** from the geometry
    alone and the scoreboard moves with it (`text_line_iou_mean` 0.2542 →
    0.5921, pair rate 0.799 → 0.895, `page_count_exact` false → **true**;
    only `ink_delta_abs_max` 0.0621 against a 0.05 bound still fails the
    floor). It is not switched on by default because `auto` is defined as
    "keep the cache until something is edited" and that definition is what
    makes an unedited render byte-identical. Deciding whether `auto` should
    prefer the flow pass **when the two disagree** is the next slice's
    question, and it needs the other nine forms' reference renders to answer.
    The same form also draws line boxes at `y0` ≈ 85.9 million px on page 18,
    from an anchored object at a wild declared `vertOffset`; identical in both
    line layout modes, so it is a separate defect and still open. A third,
    distinct mechanism — the same anchored table's `hh:sz@height` itself
    understating what its own content needs, drawing straight through a page
    bottom with no break at all — is a different bug again and is fixed; see
    *Anchor overflow*, below.
13. **The line breaker agrees with the authoring engine on 58 of the corpus's
    216 break positions** (*Line breaking from metrics*, above; 43 before the
    space became a half-width cell). It is used only where the cached layout
    cannot be, which on an unedited document is nowhere — but it is what an
    edited paragraph gets, and 0.269 is what that is worth today. The old
    residual — an advance-width gap concentrated in the space character — is
    measured and closed; what is left is two-sided (82 early, 81 late) and
    concentrated in the two `moel` forms, and is not yet explained.
14. **The flow pass agrees with the authoring engine on 468 of the corpus's
    590 top-level blocks** (*Block layout and page reflow*, below), with a
    median `|dy|` of 0 on all ten forms. 117 of the 122 misses are kstartup,
    where the disagreement is a constant two-page offset and the flow pass is
    the one that matches Hancom. It is used only where the cached layout
    cannot be, which on an unedited document is nowhere — but it is what
    everything after an edit gets.
15. **The staleness detector is sound but incomplete, and decides nothing
    per paragraph.** It cannot see an edit that leaves every line still
    fitting; `relayout_paragraphs` is the channel an editor must use instead.
    Since the provenance policy it only diagnoses, and falsifies a `cache`
    policy document-wide. See *Which engine laid out which paragraph*.
15a. **Provenance is a claim about the last writer, not a proof of
    integrity.** `version.xml@application` says which program wrote the
    package; it cannot detect a third program that edited a Hancom-saved file
    while leaving Hancom's signature in place. `stale_line_width` catches such
    an edit only when it makes some line overflow its own box. And whether
    Hancom preserves this repo's stamp across its own resave is NOT MEASURED —
    if it did, an edited-then-Hancom-saved package would stay on `computed`,
    which is the safe direction but not the accurate one.
16. **A split table does not repeat its header row.** `hp:tbl@repeatHeader` is
    set on all 81 corpus tables and is parsed, counted and skipped: the
    continuation page starts at the row the split cut at. Declared in every
    sidecar that splits a table.
17. **Text still does not wrap *around* an anchored object; the flow reserves
    its whole extent instead.** That is what makes the kstartup number above
    right, and it is also why a small floated picture with `textWrap=SQUARE`
    would push text below itself rather than beside it. No corpus form has
    one, so the two readings are not distinguishable on this corpus and the
    conservative one is taken.
18. **`keepWithNext` is resolved by one backward pass, not to a fixed point.**
    A chain of blocks that between them exceed a page cannot be satisfied at
    all; after `KEEP_WITH_NEXT_MAX_CHAIN` moves the flow gives up, leaves the
    block where it fell, and counts it in
    `block_layout.flow_counters.keep_with_next_given_up`. No corpus form
    declares `keepWithNext`, so the rule is implemented and **not exercised**
    by the corpus — it is honoured on the strength of the spec, and that is
    stated rather than hidden.
19. **The flow pass's row-fit test now allows a line's descender to cross the
    margin (measured, not tuned).** Was: the strict test broke a page the
    moment a line's box (`vertpos + vertsize`) no longer fit inside
    `usable_height`, one line earlier than four corpus documents keep a line
    box past that bound (max fill 1.068 on moel-2013) and Hancom's own
    reference render still draws it (`docs/research/line-fit-rule.md`, ink
    34–42pt past the declared bottom margin on the two reliable-reference
    overfull pages). Now: a row fits if `vertpos + baseline <= usable_height`
    (`baseline` = the cached `hp:lineseg@baseline`, or
    `round(0.85 * textheight)` where absent) — `baseline <= vertsize` always,
    so the change is strictly more permissive. Measured against the 51 corpus
    pages: 47/51 satisfied the old predicate, 50/51 satisfy the new one, and
    the 47 that already fit keep fitting (zero regression; the auto-mode
    corpus render is byte-identical, sha256-verified over all 51 PNGs). The
    one page the new predicate does not resolve is `nrf`'s empty trailing
    paragraph, whose `vertpos` is already past `usable_height` before any
    box-portion is added — no box-portion rule rescues that. On the private
    report-class holdout, page count stays 18/18 exact and the late-block
    count drops from **54 of 243 to 7 of 243**; 5 blocks that used to agree
    now land one page early instead (231/243 agree overall, up from 189/243).
    No tolerance was added — this is the measured typographic constant
    already used elsewhere in this renderer (`BASELINE_RATIO`), not a value
    chosen to make the corpus agree.

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

### The line reserves the equation's own extent, not `hp:sz@height`

**Hancom does not honour the declared height.** It re-lays the script out on
open and reserves what its own layout needs; the stored `hp:sz` is a cache it
refreshes. Measured on `render-check-01`, whose declared extents were written
by `build_render_check.py` and never by Hancom:

| script | declared | Hancom reserves |
| --- | --- | --- |
| `a over b` | 2400 | 2252 |
| `sqrt {x^{2} + y^{2}}` | 2400 | 1304 |
| `sum _{i=1} ^{n} i^{2} = … over 6` | 3600 | 2696 |
| `left [ matrix{ 1 & 2 # 3 & 4 } right ]` | 3600 | 2108 |

Two equal declared heights reserving 2252 and 1304 rule out every function of
the declared extent. **No attribute says "size to content"**: all four declare
`heightRelTo="ABSOLUTE"`, `protect="0"`, `lineMode="CHAR"`, `baseUnit="1000"`
and `Equation Version 60` — exactly what every equation of the Hancom-authored
holdout declares, and those two documents disagree about whether the stored
height is honoured. The rule adopted is this renderer's own layout of the
script, clamped to the declared box:

    reserve = min(declared, max(nominal, ink))

`nominal` (the `_EQ_ASC`/`_EQ_DESC` stacking cells) carries it — worst
residual +256 HWPUNIT (17.0%), mean 170, against +1492 (84.0%) and mean 910
for the declared height; the ink extent alone scores −494 (19.3%) and is
rejected, but joins as a **floor** so a line never reserves less room than the
equation puts glyphs in. n = 18: 4 measured off the reference PDF, 14 against
a Hancom-authored holdout's own declared extents (nominal / declared mean
0.9934, sd 0.0748). Pinned at `EQUATION_EXTENT_DPI` so the reserve does not
move with `--dpi`. Full derivation and what it is worth:
[`docs/research/equation-line-box.md`](../../docs/research/equation-line-box.md).

### `hp:sz` is the ceiling, and scale-to-fit is a declared fallback

The declared extent is the ceiling the equation is drawn inside, and where the
layout is smaller it is also what the line reserves. So the equation is
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

### Italic variable shaping

Hancom sets equation variables in italic; until this slice this renderer set
every equation glyph upright, because OWPML names a *family* and
`SystemFontIndex` resolved regular and bold cuts only. Two things changed:

1. **`SystemFontIndex` now reads italic cuts, not just bold ones.** Each
   installed font file's OS/2 `fsSelection` bit 0 and `head` `macStyle` bit 1
   are read directly out of the file (the same fields a shaping engine
   trusts), OR'd with a third signal a face can carry without setting either
   bit — its name-table subfamily string containing "Italic" or "Oblique".
   Any one of the three is enough to file that face under the family's
   `italic` (or `bold_italic`) slot. Checked against a real installed pair on
   the dev machine: Times New Roman resolves its `italic` slot to
   `timesi.ttf`, the file Windows itself ships as "Times New Roman Italic".
2. **The equation lane resolves that per equation face and applies it to
   identifier tokens only.** `hwpeqn_parse` already tags every drawn atom
   with a style (`var`, `num`, `op`, `func`, `sym`, `text`, `bigop`); `var` is
   the ONLY style a bare Latin word token — a single letter, or one letter of
   an unbraced run like `sn` — ever gets, because `word()` routes anything
   matched against `FUNCTIONS` / `GREEK` / `SYMBOLS` / etc. to a different
   style first. So "apply italic to identifiers" reduces to "apply italic to
   `var` atoms": numbers, operators, function names (`sin`/`cos`/`log`/
   `lim`…), symbols (Greek included, upper- and lower-case — the grammar
   never produces a `var` atom for a Greek letter), and quoted literals (the
   only path a Hangul glyph can reach the tree by) all stay upright by
   construction, not by a token-class exclusion list that could drift out of
   sync with the parser. An explicit `rm`/`it` style word overrides the
   default either way, on whatever it wraps.
3. **Where the family has no installed italic cut, the regular cut is
   sheared instead.** A ~12 degree synthetic oblique — the standard "fake
   italic" a renderer without italic outlines falls back to — computed by
   rasterising the glyph upright onto its own small mask and resampling it
   through an affine transform that pins the baseline row and shifts every
   row above it right in proportion to the shear (`_eq_draw_sheared`). The
   NOMINAL character cell `_eq_glyph` reports for stacking purposes is the
   upright face's either way, so this does not perturb fraction/limit
   spacing — only the drawn pixels for that one leaf are sheared.

Which of the three states applied is declared per equation face in the
sidecar, `fonts.faces[slot=equation].italic`: `cut` (an installed italic
file was used), `synthetic` (sheared), or `none`. `HancomEQN` — the font
every corpus and fixture equation declares — is not installed on the
machines this renderer has run on so far, so every measurement to date has
exercised the `synthetic` path; the `cut` path is proven against Times New
Roman in `test_a_real_italic_cut_is_used_without_a_shear` and
`test_system_font_index_finds_an_installed_italic_cut`, not against an
equation face.

**Measured, after all, on the private report-class holdout.** No corpus form
carries an `hp:equation` (unchanged from the *Equations* section above), but
the holdout named in *One holdout document* turned out to have equations too
— 14 of them, its own `Preview`-verified original. Scored with
`render_scoreboard.score_form` at 144 dpi, before (the pre-italic commit) and
after (this slice), aggregate only, nothing quoted:

| channel | before | after |
| --- | --- | --- |
| whole-page `ssim_mean` | 0.728998 | 0.729013 |
| whole-page `ssim_inked_mean` | 0.129474 | 0.129458 |
| whole-page `text_line_iou_mean` | 0.538851 | 0.538851 |
| whole-page `text_line_pair_rate_mean` | 0.904137 | 0.904137 |
| equation-region `ssim_mean` (14 crops, `hp:sz` boxes) | 0.433831 | 0.435337 |
| equation-region `ssim_inked_mean` | 0.028416 | 0.028776 |
| equation-region ink-mask IoU mean | 0.039072 | 0.037703 |

The whole-page row barely moves, for the reason mechanisms 1 and 4 already
established: the same 14 equations are ~1.5% of 18 pages, so a fraction-of-a
percent change on them is arithmetic noise on the page-level mean.
Text-line geometry is exactly unchanged (italic does not move a line box).
On the equations themselves, `ssim` and `ssim_inked` move a hair positive;
a from-scratch ink-mask IoU built for this measurement (candidate vs.
reference pixels both thresholded below 128, on the `hp:sz` box, no
`render_scoreboard` region support exists to call instead) moves a hair
negative. Read honestly, none of the three channels moves enough to call
the shear proven — `HancomEQN` is not installed on this machine either, so
before and after both substitute the same fallback face; italic only
changes *whether that fallback's letterforms lean*, not *which* letterforms
they are, and the corpus fonts a rasterised IoU is actually sensitive to are
Hancom's math-italic glyphs, not this renderer's stand-in's. What the
measurement rules out is a large regression: no channel moved by more than
0.0014.

Visual check on the crop the largest equation region scores from (page 11,
`Q_r^{2025}(\ell) = \sum_x a_x h_{2025}(x) K_\ell(d(x,S_r)) / \sum_x a_x
h_{2025}(x)`, `K_\ell(d)=\exp(-d/\ell)\ (d\le3\ell)`): the reference sets
every one of `Q, a, h, K, d, S, x, ℓ` in a visibly slanted italic and
`exp`/digits/operators upright, exactly the token-class split this slice
implements; this renderer's synthetic-oblique render reproduces the same
split with a visible (if shallower, this-machine-font-dependent) lean —
**after a bug this same check caught and a follow-up commit fixed**: the
first cut of `_eq_draw_sheared` read the glyph bbox with the wrong Pillow
anchor and pivoted the shear on the wrong row, which did not just look
less italic — it broke the layout outright, smearing equation bodies out
of their brackets. That regression is what the crop check is for; the
`ssim`/`ssim_inked`/IoU numbers above are already the fixed version's.

### What an equation still does not get

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

### Three of the ten reference PDFs were not 1:1 renders — fixed 2026-09-04

Found by the first run of this scoreboard, and it was not about the renderer.
Through 2026-09-03, `gianmun-byeolji-1ho`, `gianmun-byeolji-2ho` and
`nrf-gyeolgwa-bogoseo-yangsik` drew their text at **~0.707 = 1/√2** of the
`hh:charPr@height` their files declare, anchored near the top-left of an
otherwise A4 page. Three independent measurements agreed:

- glyph-weighted median span size ÷ declared size: 0.707, 0.707, 0.709, against
  0.996–1.023 for the other seven;
- gianmun's `발신명의`, declared 15 pt, drawn by Hancom at 10.67 pt;
- each document's own `Preview/PrvImage.png` shows the content **filling** the
  page, exactly as this renderer lays it out.

The documents were right; those three reference renders carried a print
reduction. Root cause (confirmed): all three forms' `settings.xml` stored
`PrintInfo/PrintMethod = 4` (2-up "모아찍기" imposition), which Hancom's
`SaveAs(..., "PDF")` honors even for a single-page document with nothing to
pair — each page lands in an imposed half-sheet slot at ~1/√2 scale instead
of exporting full-size. `nrf` (4 document pages) additionally lost its
page-count-parity signal (2 landscape PDF pages instead of 4 portrait) for
the same reason.

**Fixed 2026-09-04** (E2 refs-1:1 slice): re-converted with
`com_backend.py convert`'s existing `PrintMethod`-normalization staging
(forces `PrintMethod` to 0 on a temp copy before `SaveAs("PDF")` — no new
code, an existing §9.3 fix that these three references had predated), then
re-pinned in `tests/corpus/forms/manifest.json` with provenance
(`converter`, `hancom_version`, `source_print_method`/
`print_method_normalized_to`, `pages_document`/`pages_pdf`,
`geometry_scale_verified`). Verified independently with PyMuPDF: glyph-height
ratio 1.004, 1.004, 1.003 respectively (was 0.704, 0.704, 0.711), and
`pages_document == pages_pdf` for all three (1/1, 1/1, 4/4 — nrf's parity
signal is clean now too). Full provenance and the conversion sidecars:
`engine/references/render-1to1/NOTES.md`.

All ten corpus reference PDFs are now 1:1 renders. `reference_geometry_scale`
no longer blocks any of them (`comparable: true`, scale 0.995–1.004 for the
three), and a permanent regression test
(`test_every_render_reference_matches_its_declared_charpr_height`) pins a
tighter [0.97, 1.03] band across a sample of each reference's own dominant
declared-size spans, so a future replacement PDF that regresses toward this
same 0.707 defect — or any other silent rescale — fails at commit time.

First-ever real (non-blocked) metrics for the three, 144 dpi, this machine's
fonts, current renderer:

| form | ssim | ssim_inked | line IoU | pair rate | page_count exact |
| --- | --- | --- | --- | --- | --- |
| gianmun-1ho | 0.9112 | 0.0600 | 0.6215 | 1.0000 | yes (1/1) |
| gianmun-2ho | 0.9074 | 0.0531 | 0.5515 | 0.7826 | yes (1/1) |
| nrf | 0.8673 | 0.3246 | 0.6597 | 1.0000 | yes (4/4) |

All three clear the existing `PROPOSED_THRESHOLDS` regression floor
comfortably and set no new worst value across any channel, so the floor's
five bounds were left exactly as they were (calibrated worst-of-seven before
this fix) rather than re-fit to all ten — see the threshold `rationale` in
`render_scoreboard.py`. The other seven forms' scores are unchanged to 4
decimal places (re-verified by re-running `--corpus` against both the old and
new reference sets: their inputs never changed, so their outputs could not).

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

### The half-width space cell, on the same scoreboard

The break-position number is one channel; the raster is the independent one,
and it moved the same way. Same scoreboard build, same machine, the only
difference being whether a space is the face's `hmtx` advance or the half cell:

| form | `ssim_inked` | line IoU | `ssim` |
| --- | --- | --- | --- |
| admrul | 0.3048 → 0.3218 | 0.4845 → 0.4840 | 0.8859 → 0.8913 |
| jeongbo | 0.0354 → 0.0388 | 0.4385 → 0.4551 | 0.6176 → 0.6203 |
| jumin | 0.0825 → 0.0826 | 0.5741 → 0.5892 | 0.6377 → 0.6416 |
| kstartup | 0.2210 → 0.2313 | 0.2460 → 0.2542 | 0.8080 → 0.8112 |
| moel-2013 | 0.0441 → 0.0695 | 0.4469 → 0.4674 | 0.7655 → 0.7746 |
| moel-2025 | 0.1467 → 0.1810 | 0.4929 → 0.5167 | 0.7530 → 0.7637 |
| saeopja | 0.0187 → 0.0179 | 0.5393 → 0.5562 | 0.6439 → 0.6447 |
| gianmun-1ho | 0.1007 → 0.1005 | — | 0.8810 → 0.8811 |
| gianmun-2ho | 0.0338 → 0.0332 | — | 0.8769 → 0.8771 |
| nrf | 0.3713 → 0.3691 | — | 0.7573 → 0.7561 |

Means over all ten: `ssim` 0.7627 → 0.7662, `ssim_inked` 0.1359 → 0.1446,
line-box IoU 0.3281 → 0.3386, `changed_channel_ratio` 0.1291 → 0.1283. Every
form keeps its verdict against the regression floor, `kstartup` included (it
was already failing `page_count_exact`, for the pagination reason at limit 12,
and still is). Pair rate is flat to four decimals except `kstartup`, −0.0016.

The two `moel` forms move most on `ssim_inked` (+0.025, +0.034), which is where
the corpus's spaced Hangul prose is. `nrf` and `saeopja` lose a thousandth of
`ssim_inked`; those are the three reduced-reference and the sparsest forms, and
the movement is inside the noise the reduction itself introduces.

## Anchor overflow: a table split at the row its own content calls for (E2.7)

`docs/research/residual-advance-and-ink.md`'s Q2 named two new kstartup
mechanisms, distinct from limit 12's cache-vs-flow disagreement and wild
`vertOffset`: a block overflowing a page with no break at all (page 6), and
a candidate cell-shading bug. The first is fixed here; the second was
investigated and not reproduced.

### The declared height was stale, not the fit test

kstartup's largest anchored (`treatAsChar="0"`), `pageBreak="CELL"` table
declares `hh:sz@height=70529` HWPUNIT — just under the page's 71000 usable
height, so both the flow pass and (via `_anchor_table_geometry`'s new
content-based check) the `auto`/cache path used to call it a fit. Measured
from its own content (`_table_tracks`, the same measurement a row's own
`cellSz` height is already solved from — this renderer's own comment there:
"HWP grows a row to fit its content and leaves the stored value behind"),
it needs **96966** — 37% more. Every other anchored, `pageBreak="CELL"`
table in the ten-form corpus (five more in kstartup, one in `nrf`) matches
its own content within 0.5%; this is the one exception, and the mechanism
generalises: a corpus scan found it nowhere else.

One further wrinkle, found chasing the residual overlap the first fix left
behind: one of that table's own rows turned out to be **two** rows Hancom
itself rendered across a page break — `○ 사업비 사용 계획`'s own content
ending one page, `○ 성과목표 및 기대효과` starting fresh on the next — and
recorded that the same way `paginate` records a top-level page break: the
row's own paragraph list's cached `vertpos` restarts to 0 partway through.
`_restart_segments` finds that boundary (the identical backward-jump rule
`paginate` already uses, one level deeper), `_paragraph_block_extent` sums
segments instead of taking one flat max across them, and
`_expand_segmented_rows` turns the row into two synthetic ones inside
`_table_tracks` before any row height is solved — so every mechanism below
that point (the split decision, the drawing) sees an ordinary row boundary
and needed no second unit built for it.

### The fix, in both block-layout policies

- **`computed`.** `_anchor_table_geometry` recomputes an anchored,
  CELL-splittable table's row heights from content (`_table_tracks` with
  the new `natural_rows=True`, which skips the compress-to-declared-height
  step on the row axis only). `_place_block` uses the larger of declared
  and content-measured extent for its fit test, and when even that
  overflows, `_split_anchor_overflow` gives the SAME move-or-split answer
  an inline flowing table already got: move whole to a fresh page when
  that is enough, else split at the last row boundary that fits — here,
  after row 1, giving the "사업비" segment 27455 HWPUNIT (fits the current
  page) and "성과목표" 69511 (fits a fresh one) instead of the whole
  96966 crammed into 71000. `_render_floating` threads the row range
  through both halves: the first page gets rows `[0, cut)`, a continuation
  page gets `[cut, end)`, and `_render_table` draws each using
  `natural_rows` (recursively marked on every table nested inside the
  split one too — `_mark_natural_height` — since compressing a NESTED
  table to ITS OWN stale declared height while the paragraph after it
  keeps the cache's correct, uncompressed position is the identical bug
  one level deeper; the corpus scan behind this fix found exactly one such
  case, 2% short).
- **`auto`.** The shipping default never runs the flow pass on an unedited
  document (E2.5's whole point), so the same overflow was reachable
  through `paginate`'s cached-page path too, and had to be caught there:
  `_paginate_with_anchor_overflow_fix` applies the identical
  move-or-split decision to `paginate`'s own groups, and
  `_render_floating`'s `_auto_anchor_splits` queue hands back each row
  range as the paragraph is encountered the second time, on the page the
  split inserted. `_block_layout_report` was updated to report the
  corrected page list rather than re-deriving an uncorrected one.
- **Whitespace line boxes.** `_draw_line` no longer records a line box (or
  counts one) for a run of nothing but spaces — it draws no visible ink at
  all, so its font-ascent/descent box overlapping real content at the same
  height is not the "line box" the sidecar's own words mean, and was
  producing a phantom collision report against kstartup's own blank
  spacer paragraphs once the real overlap above was gone.

### Scored

| | `ssim` | `ssim_inked` | line-box IoU | pair rate | `ink_delta_abs_max` |
| --- | --- | --- | --- | --- | --- |
| before | 0.6074 | 0.03291 | 0.5544 | 0.8877 | 0.055634 |
| after | 0.6238 | 0.03291 | 0.5585 | 0.9326 | 0.055634 |

Page count stays exact (22) in both. `ink_delta_abs_max` does not move: it
was already, and remains, page 22's — the pre-existing block-position-drift
bug (limit 12's first sub-issue) content, not page 6's. Page 6 itself drops
out of the worst-8-pages list entirely; every other channel that samples the
whole document (`ssim`, pair rate) moves the right direction because a page
that used to draw two blocks' worth of ink on top of itself now draws one.
All nine other corpus forms render byte-identical (sha256, `auto` and
`computed`) before and after — the new code paths are gated behind content
overflowing its own declared height, which nothing else in the corpus does.

### Cell shading — investigated, not reproduced

The research doc's third finding named a candidate mechanism: a
`hh:borderFill`/`hh:winBrush` resolution bug filling the "동의서" tables'
label cells (수집·이용목적 등) light blue where Hancom draws white. Traced
to source: every `hc:winBrush` in kstartup (50 distinct `hh:borderFill`
entries) carries `alpha="0"` uniformly, including ones already known to
render correctly (`faceColor="#FFFFFF"`, `faceColor="none"`) — so `alpha`
is not a fill/no-fill switch this format uses, and this renderer does not
read it as one. The named cells (`hh:borderFill` id 24/28/30,
`faceColor="#DFEAF5"`) were rendered directly and sampled against a fresh
render of the reference PDF's own page 22, at the SAME, correctly-aligned
position: candidate (223, 234, 245) against reference (222, 233, 245) — a
1-of-255 rounding difference, not a colour bug. The most likely explanation
is that the research measurement compared candidate's page 21 (where this
table sits before limit 12's block-drift bug is fixed) against reference's
page 22 at MISALIGNED grid coordinates, not a real fill-resolution defect.
No code change was made; `test_border_fill_resolves_exactly_its_declared_
facecolor_or_none` and the two synthetic-cell tests pin the mechanism that
is actually in the code.

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

1. ~~**Regenerate the three reduced reference PDFs at 1:1.**~~ Done 2026-09-04
   (E2 refs-1:1 slice) — see *Three of the ten reference PDFs are not 1:1
   renders* above, now updated in place. All ten document classes are
   comparable.
1b. ~~**Render `hp:equation`.**~~ Done — see *Equations* above. What it left
   open is italic variable shaping, which is now the largest visual difference
   on the equation pages and needs per-cut face resolution, not equation work.
2. ~~**Close the advance-width gap the breaker exposed.**~~ Largely done, by
   the reference-PDF measurement this item asked for: the space is a
   half-width cell, not the face's `hmtx` advance (*The space is a half-width
   cell*). A cached line now measures a median 0.97 of its own box, 43 → 58
   break positions, and the raster scoreboard moved with it. **What is left**
   is the second, smaller term the same measurement exposes: `moel-2013` and
   `moel-2025` still fill only 0.89 / 0.91 and hold most of the remaining
   disagreement, and 0.45 em outscoring the measured 0.50 on break positions
   (69 vs 58) says something else is still being absorbed there. Those two
   forms are also the ones whose declared 한양 faces resolve worst on this
   machine — first thing to check, not yet proven.
3. Vector PDF text output — unlocks `render_cert`'s word-anchor channel and
   with it the actual certificate.
4. Sub-pixel glyph registration: see item 2, of which this is the intra-line
   half.
5. ~~**Block layout (E2.5).**~~ Done — see *Block layout and page reflow*.
   What it leaves open is the `auto` policy question named in limit 12: on
   kstartup the flow pass and the cached-`vertpos` heuristic disagree, and the
   flow pass is right. Answering that for all ten forms needs the reference
   renders item 1 is about.
6. ~~**A vendored font with known metrics.**~~ Largely done for the plain
   body serif/sans/monospace slot — see *Bundled Korean fallback faces
   (family map)* below: `BundledFontMap` maps 바탕/함초롬바탕/휴먼명조/
   신명조/한양신명조/궁서, 돋움/굴림/함초롬돋움/맑은 고딕/한양중고딕/HY견고딕
   and 돋움체/굴림체 to three OFL Nanum families shipped in the repo, so
   those specific declared names resolve to the same face everywhere. What
   is left: everything NOT in that table (HCI Poppy, 한컴바탕, 신명 신문명조,
   HY울릉도M, 필기, and any Latin/decorative face) still falls through to the
   single machine-dependent system fallback, so the scoreboard is not fully
   off the machine's installed faces yet — only closer.
7. `kstartup` pagination (limit 12) — now diagnosed and computable; what is
   left is the policy decision, not the mechanism.
8. ~~**Italic cuts in `SystemFontIndex`, for equations.**~~ Done — see
   *Italic variable shaping*. `SystemFontIndex` now reads a real italic cut
   where a family installs one and applies it (or a synthetic shear) to
   equation identifier tokens. What is left: bold-italic cuts are recorded
   but nothing yet asks for one, the shear angle is not measured against a
   reference, and emphasised PROSE (`hh:charPr@italic`, distinct from the
   equation lane) still has no italic-cut resolution of its own — `_face_for`
   only ever asks for `"bold" if bold else "regular"`.
9. Only then ask `render_cert` for a per-document-class grade. Until it
   answers, the grade stays `own-uncertified`.
10. **`MalgunGothicBold` bold-face advance metric.** Found by the E2
    refs-1:1 slice's own re-baseline of
    `test_no_glyph_class_is_measured_more_than_a_hundredth_of_an_em_out`:
    with the three re-pinned references doubling the qualifying sample count
    for this face's bold Latin glyphs, `I`/`R`/`B` measure ~0.04-0.05 em wide
    of Hancom's own reference render (e.g. `I` 0.270 em declared/measured by
    Hancom vs 0.310 em this renderer draws), pulling the `latin` glyph class
    from 0.0056 to 0.0111 em mean error — not a reference-swap artifact (the
    per-glyph reference ratios themselves barely moved), a genuine pre-
    existing gap in how this renderer resolves `MalgunGothicBold`'s bold
    metrics table. Out of scope for the refs-1:1 slice (font-metric
    resolution, not reference pinning); the regression floor was widened to
    0.012 to keep the gate honest rather than hiding the finding.

## E2 refs-1:1 slice — closing gate run, 2026-09-04

Ran clean at commit `ea0887c` on `claude/engine-e2-refs-1to1`:

- `pytest engine/tests -q`: 1160 passed, 135 skipped, 0 failed (267s). The
  determinism tests (`test_the_computed_breaker_is_deterministic_too`,
  `test_the_flow_pass_is_deterministic`, `test_a_page_with_furniture_renders_
  deterministically`) are in this run and green.
- `python scripts/py_compile_sweep.py`: 103 files, 0 failures.
- `python pipeline/scripts/privacy_scan.py archive --json`: hard 0, warn 0,
  total 0, incomplete false.

No code changes made in this pass beyond what the E2 refs-1:1 slice commit
already carries; this is a gate-verification entry, not new work. The
`engine/references/render-1to1/NOTES.md` provenance file this section's PDF
re-pin notes cite lives on `claude/engine-e3-hancom-accept`
(commit `b8a87e1`), not yet merged into this branch — a known cross-branch
reference, not a broken one; no test on this branch depends on that path.

## The whole-page offset was `hp:outMargin` — measured and closed, 2026-09-04

The standing E2 registration gap this file names in several places — "every
rule on `jeongbo` page 1 sits a constant −2.83 pt above where the reference
draws it", `moel-2013` −2.93, `saeopja`/`jumin`/`admrul` ≈ −1.4 — is one
defect with one cause, and it is not the page box. It is the table's own
**`hp:outMargin`** (바깥쪽 여백), which this renderer listed as a structural,
no-ink tag and never read.

### How it was measured

Rules straight out of the two vector sources, no raster and no cross-
correlation: every cell rectangle the renderer places (HWPUNIT, so pt =
HWPUNIT/100) against every horizontal and vertical rule in the reference
PDF's own drawing operators, matched with the same order-preserving DP the
row-height measurement above uses.

One correction has to come out first, or nothing lines up. **The reference
PDFs are exported onto an integer-point A4 page**: `page.rect` is 595 x 841
while every corpus form declares 59528 x 84188 HWPUNIT = 595.28 x 841.88 pt.
The content is scaled to match, so a raw delta carries a slope of
841.88/841 − 1 = +0.00105 pt/pt vertically and +0.00047 horizontally — about
0.9 pt over a page, which is the same order as the defect being hunted.
Subtracting that per-axis scale leaves a residual that is flat to within a
tenth of a point, and that residual is the registration error. (The
scoreboard rasterises the reference onto the candidate's own pixel grid,
which undoes the same scale, which is why the raster channel saw a constant
and not a ramp.)

### The measurement, before

`dy`/`dx` are candidate minus reference in pt, scale-corrected, median over
the matched rules on the form's pages. `outMargin` is the value the form's
tables declare in all four slots.

| form | outMargin | dy | dx | top / header / gutter |
| --- | --- | --- | --- | --- |
| jumin-deungchobon-sinchengseo (p1 table) | 0 | **+0.07** | **+0.07** | 5669 / 0 / 0 |
| admrul-gajokdolbom-hyuga-sinchengseo | 141 | −1.37 | −1.33 | 5669 / 0 / 0 |
| gianmun-byeolji-1ho | 141, 140 | −1.38 | −1.33 | 5669 / 0 / 0 |
| gianmun-byeolji-2ho | 141 | (see below) | −1.34 | 5669 / 0 / 0 |
| jeongbo-gonggae-cheongguseo | 283 | −2.78 | −2.75 | 5668 / 0 / 0 |
| jumin (p2, p3 tables) | 141 | −1.33 / −1.37 | −1.36 | 5669 / 0 / 0 |
| kstartup-jiwon-sincheongseo | 140, 141, 283, 138 | −1.42 | −1.41 | 5668 / 332 / 0 |
| moel-pyojun-geunrogyeyakseo-2013 | 283 (p1–5), 141 | −2.85 | 0.00 (centred) | 3600 / 3600 / 0 |
| moel-pyojun-geunrogyeyakseo-2025 | 0 (8 tables), 141 | −0.45† / −1.35 | −0.43† / −1.26 | 2834 / 2834 / 0 |
| nrf-gyeolgwa-bogoseo-yangsik | 140, 138 | −1.37 | −1.37 | 5668 / 1416 / 0 |
| saeopja-deungnok-sinchengseo | 141 | −1.35 | −1.34 | 5668 / 0 / 0 |

† an artefact of the measurement, not an offset: those pages' tables draw a
doubled rule ~1.08 pt apart and the DP matches the first of the pair. Their
midpoints agree to +0.16 pt, i.e. zero, which is what `outMargin=0` predicts.

Read the first two columns together and the rule is exact: the offset is
`−outMargin/100` pt in both axes, per table, with no reference to the form.

### Hypotheses this kills

Every candidate that lives on the page rather than on the object is
disproven by one line of the table: `jumin` p1 and `admrul` declare the
**same** `hp:pagePr` — top 5669, header 0, footer 0, gutter 0,
`gutterType="LEFT_ONLY"`, same page size — and register 0.07 pt and 1.37 pt
apart. So none of these is the cause:

* **header-height handling.** `body_top = top + header` is right as it
  stands. The two forms with the largest declared `header` (`moel-2013`
  3600, `moel-2025` 2834) are not the two with the largest offset, and
  `jeongbo` — the only form carrying an `hp:header` element at all — has
  `header="0"` and an offset of exactly its tables' `outMargin`.
* **gutter / binding side.** Every corpus form declares `gutter="0"` and
  `gutterType="LEFT_ONLY"`. There is nothing to add to either side.
* **1 mm HWPUNIT rounding of the margins** (7200/25.4 = 283.46). 283 does
  appear — but as `jeongbo`'s and `moel-2013`'s `outMargin`, not as a margin
  correction, and forms that declare 138/140/141 are off by 1.38/1.40/1.41
  pt, which no rounding of a 5669 margin produces.
* **raster origin convention** (pixel centre vs edge). 0.5 px at 144 dpi is
  0.25 pt; the vector measurement above never touches a raster and sees the
  same offsets.

### The rule, and what it costs

`hp:outMargin` is the gap *outside* an object's own box (schema:
`DevDoc/OWPML SCHEMA/ParaList XML schema.xml`, on every `ShapeObject`
alongside `hp:sz` and `hp:pos`). The authoring engine gives the object a
slot `left + width + right` wide and draws the box `(left, top)` inside it.
`_object_origin` applies the inset — for inline objects at the line cursor
and for anchored ones at the declared `hp:pos` — and `_object_extent`
returns the wider slot.

Horizontal footprint is measured, not assumed: `moel-2013` centres a table
declaring `outMargin=283`, and its reference draws that table centred on the
body box. Insetting the box without widening the slot would put it 2.83 pt
right of centre; the table's `dx` of 0.00 above is that prediction holding.

**The line HEIGHT deliberately does not grow, and that is a declared limit.**
Nothing in the reference set measures the height an inline object claims —
the cached `hp:lineseg` carries it on every corpus form — and adding
`top + bottom` there is a guess that shows up only under
`block_layout=computed`, where it cost `kstartup` a 23rd page against a
21-page reference. The box still moves down by `top`, which is the half the
references do measure.

> **The limit was wrong twice over, and both halves are now measured**
> (`docs/research/object-line-box.md`). The cached `hp:lineseg` *is* the
> measurement — it was simply never read on the lines that carry an object.
> Over the ten forms' **79 object lines**, `vertsize` (and `textheight`) is
> `hh:sz@height + outMargin@top + outMargin@bottom` on **79 of 79**, exactly,
> against 16/79 for the extent alone. The 23rd page it used to cost was the
> *other* defect masking this one: the paragraph's `PERCENT` leading was being
> taken off the object-sized line box, so kstartup's full-page inline tables
> each claimed a further 40% of a page. With the leading taken off the run's
> own character size instead — exact on 66 of 79 cached lines, within
> 2 HWPUNIT on 12 more — `kstartup` computes **22** pages against its 22-page
> reference (it was 27 under `line_layout=computed`), and `gianmun-1ho`,
> `gianmun-2ho` and `admrul` each drop from 2 to their cached 1.
> `_line_metrics` adds the vertical margin; `_object_extent` still does not,
> so it is added exactly once.

### The measurement, after

Matched rules whose scale-corrected `|dy|` is within a tolerance, summed over
every page of every form:

| tolerance | before | after |
| --- | --- | --- |
| 1 pt | 61 / 428 | **365 / 428** |
| 0.25 pt | 28 / 428 | **335 / 428** |

Scoreboard, `--corpus`, corpus means: `ssim` 0.7837 -> 0.8250, `ssim_inked`
0.1376 -> 0.2551, `text_line_iou` 0.5170 -> 0.6423, `text_line_pair_rate`
0.8364 -> 0.8364. **Page counts are unchanged on all ten forms**, and no
form's `ssim` or `text_line_iou` falls.

Per form, `ssim` / `ssim_inked` / `iou`:

| form | ssim | ssim_inked | text_line_iou |
| --- | --- | --- | --- |
| admrul | 0.8913 -> 0.9197 | 0.3218 -> 0.5007 | 0.5070 -> 0.5877 |
| gianmun-1ho | 0.9112 -> 0.9375 | 0.0600 -> 0.2965 | 0.6215 -> 0.8428 |
| gianmun-2ho | 0.9075 -> 0.9075 | 0.0545 -> 0.0538 | 0.5515 -> 0.6468 |
| jeongbo | 0.6207 -> 0.7571 | 0.0398 -> 0.2692 | 0.4551 -> 0.8273 |
| jumin | 0.6426 -> 0.6822 | 0.0851 -> 0.1399 | 0.5893 -> 0.6711 |
| kstartup | 0.8134 -> 0.8282 | 0.2219 -> 0.2884 | 0.2451 -> 0.2727 |
| moel-2013 | 0.7751 -> 0.7880 | 0.0698 -> 0.1008 | 0.4680 -> 0.5063 |
| moel-2025 | 0.7634 -> 0.7706 | 0.1804 -> 0.1918 | 0.5167 -> 0.5396 |
| nrf | 0.8673 -> 0.8924 | 0.3246 -> 0.4418 | 0.6597 -> 0.7225 |
| saeopja | 0.6447 -> 0.7664 | 0.0179 -> 0.2681 | 0.5562 -> 0.8060 |

**No corpus form renders byte-identically**, and none can: all twelve
committed forms (the ten scored plus the two `grant/` forms) declare a
non-zero `outMargin` on at least one object. What is pinned instead is the
no-op: a document whose objects declare `outMargin=0`, and the same document
with the `hp:outMargin` elements deleted outright, render to identical PNG
bytes — so the rule moves nothing that does not ask to be moved, and no
per-form constant is involved anywhere.

### The one exception, and it is not this rule

`gianmun-byeolji-2ho` goes the other way on the rule channel: 8 of 10 matched
rules within 1 pt before, 2 of 10 after. Its `dx` is fixed (−1.34 -> +0.05)
and its `text_line_iou` rises 0.5515 -> 0.6468, but its `dy` runs
+0.58 pt at the table's first rule and +3.55 pt twelve rows down. That is
**row-height accumulation, not registration**: our row pitch on that table is
24.44 pt against the reference's 24.09 (24.12 scale-corrected), so the error
grows ~0.33 pt per row and used to cancel the 1.41 pt outer margin somewhere
near the middle of the page. This file's row-height measurement already names
`gianmun-2ho` as one of the two forms genuinely wrong on that channel and
defers it; it is still deferred.

`kstartup` pages 6, 9, 10, 15 and 16 keep large residuals for the reason E2.5
already names — its pagination under `auto` is wrong on those pages, so the
rules being compared are not the same rules.

### Private holdout (windpath, aggregate only)

14 pages compared. `dx` median −1.403 pt -> −0.018 pt; `dy` median
−1.423 -> −1.122, with 0/81 matched rules within 0.25 pt before and 28/76
after. Horizontal registration is closed there too; the vertical residual on
a report-class document is paragraph flow above the table, a different
channel from this one.


## Bundled Korean fallback faces (family map), 2026-09-04

`BundledFontMap` (own_render.py) adds a third face-resolution tier between
the installed system index and the single generic system fallback: a fixed
table mapping 14 plain body serif/sans/monospace Hancom/HWP face names to
three OFL Nanum families shipped in `engine/references/fonts/family-map/`
(licences in `engine/references/fonts/LICENSES.md`). See *Fonts: resolved
where installed, substituted where not* above (updated in place) and item 6
of *Remaining order of work*.

Resolution order: installed exact face -> `BundledFontMap` -> generic system
fallback. Declared per face in the sidecar as `fonts.faces[].source`
(`installed` | `bundled` | `system`) and `family_map` (the bundled family
name, when `source == "bundled"`). `resolved_character_share` keeps its old
meaning (installed + bundled); `installed_character_share` /
`bundled_character_share` split it back apart, since a bundled hit is still
not the exact declared face.

**Corpus scoreboard, before -> after** (`render_scoreboard.py --corpus`,
before = this commit's parent, after = this commit; measured on a machine
without Hancom Office installed, so every improving form below was landing
on the generic Malgun fallback before):

| form | resolved share | ssim_mean | ssim_inked_mean | line IoU mean |
|---|---|---|---|---|
| admrul | 0.545 -> 0.624 | 0.8913 -> 0.8929 | 0.3218 -> 0.3265 | 0.5070 -> 0.5186 |
| kstartup | 0.938 -> 0.984 | 0.8134 -> 0.8138 | 0.2218 -> 0.2223 | 0.2451 -> 0.2458 |
| moel-2013 | 0.858 -> 0.993 | 0.7751 -> 0.7792 | 0.0698 -> 0.0733 | 0.4680 -> 0.4817 |
| moel-2025 | 0.738 -> 0.968 | 0.7637 -> 0.7719 | 0.1808 -> 0.1905 | 0.5167 -> 0.5334 |
| nrf | 0.572 -> 0.788 | 0.8673 -> 0.8676 | 0.3246 -> 0.3251 | 0.6597 -> 0.6235 |

The other five corpus forms (gianmun-1ho, gianmun-2ho, jeongbo, jumin,
saeopja) declare no face `_FAMILY_MAP_TABLE` maps that this machine's
installed index does not already resolve, so their scoreboards are
byte-identical before and after, exactly as the design intends: installed
still wins, unconditionally. `nrf`'s line-IoU mean is the one number that
moved the wrong way (0.6597 -> 0.6235) despite every other channel on that
form improving — not investigated further here, reported as measured, not
smoothed over.

**Private holdout** (바람숲_corpus여백.hwpx/.pdf, `report-windpath-hanmadang`
output v6; local only, not committed or quoted beyond aggregate numbers):
`resolved_character_share` was already `1.0` (installed) before this
change — every face this document declares is already installed on this
machine — so `BundledFontMap` matched 0 characters and before/after are
identical: `ssim_inked_mean` 0.129458, line-IoU mean 0.538851, text-line
pair rate 0.904137, all unchanged. Visual read of page 1 (candidate PNG vs
the operator's Hancom reference render): body-text weight and the serif/
sans split match the reference closely; the one visible difference is a
pre-existing line-count/pagination gap near the bottom of page 1 (unrelated
to fonts — see *Close the advance-width gap the breaker exposed* above),
present identically before and after. This holdout does not demonstrate the
bundled tier's effect — it simply was not a case that needed it.

**Not proven / left open:** a Hancom-installed machine was not available to
re-run this corpus on, so "installed still wins" is verified by construction
(`_face_for`'s order, and the priority unit test) and by the fact that faces
already resolving on THIS machine did not change, not by a second machine's
measurement. Declared names outside the 14-entry table (HCI Poppy, 한컴바탕,
신명 신문명조, HY울릉도M, 필기, and any Latin/decorative face) are unaffected
by this slice and still machine-dependent.

Evidence: `pytest engine/tests/test_own_render.py -q` — 185 passed;
`pytest engine/tests -q` — 1163 passed, 135 skipped, 0 failed;
`python scripts/py_compile_sweep.py` — 103 files, 0 failures.


## Dashed borders — measured, 2026-09-04 (E2 borders/rows slice)

`docs/research/h2orestart-vs-own.md` names two defects on the two worst
forms. This is the first: `hh:borderFill@type="DASH"` was stroked as a solid
line of the declared width. 55 border sides across six corpus forms declare
it (`gianmun-2ho` 7, `jeongbo` 4, `jumin` 9, `kstartup` 23, `moel-2025` 4,
`nrf` 8).

**Measured black-box off the Hancom reference PDFs, not guessed.** None of
the ten references carries a PDF `d` (dash-array) operator: Hancom emits
every dash as its own path piece, so the pattern reads straight out of the
page geometry. Collinear pieces merged per rule, run/gap taken as medians,
over every reference that declares a DASH side:

| declared | stroked | dash | gap | period | dash/w | gap/w | forms |
|---|---|---|---|---|---|---|---|
| 0.10 mm | 0.240 pt | 0.360 | 0.480 | 0.840 | 1.270 | 1.693 | nrf |
| 0.12 mm | 0.360 pt | 0.480 | 0.720 | 1.200 | 1.411 | 2.116 | gianmun-2ho, jumin, kstartup, moel-2025 |
| 0.15 mm | 0.480 pt | 0.600 | 0.840 | 1.440 | 1.411 | 1.976 | jeongbo |
| 0.70 mm | 2.039 pt | 2.879 | 4.318 | 7.197 | 1.451 | 2.176 | jeongbo |

`dash/w` and `gap/w` are against the **declared** width (0.12 mm = 34.02
HWPUNIT = 0.3402 pt), not the width Hancom strokes. The stroked width is
quantised onto what looks like a 600 dpi device grid — 0.240 / 0.360 /
0.480 / 2.039 pt are exactly 2 / 3 / 4 / 17 units of 1/600 in — and the dash
geometry tracks the *declared* width, not the quantised one. That is the one
non-obvious thing in the measurement: fitting the ratios against the stroked
width gives no consistent constant, fitting against the declared width does.

`BORDER_DASH_PERIOD = 3.53` (× declared width) and `BORDER_DASH_DUTY = 0.40`
reproduce the 0.12 mm class — 43 of the 55 sides — exactly: 0.4804 / 0.7206
predicted against 0.4800 / 0.7200 measured. Within 3% on 0.70 mm, within
0.05 pt on 0.15 mm. 0.10 mm is the loosest fit (0.400 / 0.600 predicted
against 0.360 / 0.480) and nothing in the corpus separates "Hancom keeps a
per-width-class table" from "the 0.10 mm rule is quantised harder", so one
ratio serves every class and the residual is stated rather than fitted away.
At 144 dpi a 0.12 mm dash is 0.96 px on a 2.4 px pitch — the residual is
well under the pixel the corpus is scored at.

`DOT`, `DASH_DOT`, `DASH_DOT_DOT` and `LONG_DASH` are **declared, not
measured**: no corpus form declares any of them on any side, so there is no
Hancom reference for them at all. They are built out of the DASH family's
own measured period (a dot is one stroke-width of ink; a long dash is two
dash lengths) so the four read as one system, and every side drawn with one
says "not measured itself" in the sidecar. `CIRCLE` is unchanged and still
declared as stroked-solid.

Phase is anchored to the **page origin**, not to the edge: a table rule is
drawn once per cell it crosses, and a per-edge phase would restart the
pattern at every column boundary. The reference's dashed rules run the whole
width of the table on one uninterrupted phase; anchoring at the origin makes
every collinear piece agree without any of them knowing about the others.

### What it moved (144 dpi, corpus scoreboard, before → after)

| form | ssim | ssim_inked | line IoU | dashed edges |
|---|---|---|---|---|
| jeongbo-gonggae-cheongguseo | 0.6203 → 0.6207 | 0.0388 → 0.0398 | 0.4551 → 0.4551 | 6 |
| gianmun-byeolji-2ho | 0.9074 → 0.9075 | 0.0531 → 0.0545 | 0.5515 → 0.5515 | 7 |
| moel-pyojun-geunrogyeyakseo-2025 | 0.7637 → 0.7634 | 0.1808 → 0.1804 | 0.5167 → 0.5167 | 4 |
| kstartup-jiwon-…-saeopgyehoekseo | 0.8134 → 0.8134 | 0.2218 → 0.2219 | 0.2451 → 0.2451 | 84 |
| jumin-deungchobon-sinchengseo | 0.6426 → 0.6426 | 0.0851 → 0.0851 | 0.5893 → 0.5893 | 13 |
| nrf-gyeolgwa-bogoseo-yangsik | 0.8673 → 0.8673 | 0.3246 → 0.3246 | 0.6597 → 0.6597 | 18 |
| **corpus mean (10)** | **0.7837 → 0.7837** | **0.1374 → 0.1376** | **0.5170 → 0.5170** | |

The other four forms — `admrul`, `gianmun-1ho`, `moel-2013`, `saeopja` —
declare no DASH side and render **byte-identical** (sha256 over their PNG
pages). Two consecutive full-corpus renders hash identically, so the dash
walk is deterministic.

**Honest reading of that table: the scoreboard barely moves.** At 144 dpi a
dashed rule differs from a solid one by roughly one pixel in three along a
handful of thin lines, which is far below what an 8×8-block SSIM or a
text-line IoU can see. The defect was real and is closed — the render now
draws what the file declares, and `jeongbo` and `gianmun-2ho` no longer skip
any element at all — but nobody should expect this to move a corpus metric,
and the numbers above are the evidence that it does not.

## Table row heights are NOT too tall — measured, 2026-09-04

`docs/research/h2orestart-vs-own.md`'s second named defect ("the same form's
table rows render visibly taller in the own renderer than the reference…
Row height is being computed with more padding than Hancom's own layout
uses") **does not reproduce as a row-height defect.** No code was changed
for it; here is the measurement that says why.

Method: every horizontal cell border the renderer actually draws (page,
y, x-span) against every horizontal rule in the reference PDF (dash pieces
merged into runs), reference rescaled onto the render's own pixel grid.
Rules aligned with a **monotone** (order-preserving) DP, not greedy
nearest-neighbour: greedy crosses whenever two rules sit within a couple of
points of each other — a double rule, a thin banner row — and every crossed
pair invents two large equal-and-opposite row-height errors that are not
there. Per-row height is the spacing between consecutive matched rules, so a
constant page offset cancels out of it.

| form | rows compared | within 1 pt | mean abs error |
|---|---|---|---|
| jeongbo-gonggae-cheongguseo | 23 | 22 (0.957) | 0.212 pt |
| jumin-deungchobon-sinchengseo | 46 | 46 (1.000) | 0.196 pt |
| saeopja-deungnok-sinchengseo | 170 | 168 (0.988) | 0.183 pt |
| moel-pyojun-geunrogyeyakseo-2025 | 25 | 23 (0.920) | 0.470 pt |
| admrul-gajokdolbom-hyuga-sinchengseo | 5 | 5 (1.000) | 0.042 pt |

0.2 pt is the 144 dpi half-pixel quantum. On the two forms the slice was
aimed at, row heights are already at the measurement floor and there is
nothing to fix; a "padding constant" correction here could only make them
worse.

**What is actually wrong on those forms is registration, not row height.**
Every rule on `jeongbo` page 1 sits a constant −2.83 pt (283 HWPUNIT, almost
exactly 1 mm) above where the reference draws it, from the first rule at
y=143 to the last at y=797 — a whole-page offset, not an accumulating one.
`moel-2013` shows −2.93 pt on five of its seven pages; `saeopja`, `jumin`
and `admrul` show ≈ −1.4 pt, half of it. That is the standing E2 registration
gap this file already names, and it is what makes the rows *look* wrong.

Two forms are genuinely worse on this channel and are **follow-up, not this
slice**: `gianmun-2ho` (0 of 5 rows within 1 pt, offset +11.5 pt) and
`kstartup` (38 of 67, and per-page offsets running from −0.5 to −18.9 pt —
the same form whose pagination E2.5 already names as wrong under `auto`).

## A paragraph the cache split across a page — fixed, 2026-09-04

Found on the private windpath holdout: page 1 carried a stray one-word line
("있다.", the tail of a body paragraph) at the top of the body box, above
the title, where the Hancom reference starts with the title.

OWPML's cached `hp:lineseg@vertpos` is measured from the top of the body box
of the page the line is on and restarts on every page. `paginate` already
reads that backward jump to find page boundaries *between* top-level
paragraphs, and `_restart_segments` reads it between the paragraphs of a
container — but nothing looked *inside* one paragraph. A body paragraph long
enough to run off the bottom of a page has its continuation lines cached
from the next page's top, so its own `vertpos` sequence drops back to (near)
zero part-way through; `_render_cached_lines` then drew every one of its
linesegs from the head page's origin, and the tail's near-zero `vertpos` put
it at that page's very top.

`Paragraph.page_runs` applies the same rule within a paragraph, `paginate`
starts a page at each run after the first, and `_render_paragraphs` draws
each run as a view over its own lineseg range — counted, floated and
layout-recorded once, on the head view. `_render_cached_lines` grew a
`rebase` flag: the computed flow pass keeps rebasing a range onto the origin
it chose, the cached path does not, because there the cached `vertpos` is
already measured from the continuation's own page.

**No paragraph in any of the ten corpus forms has more than one run** — all
ten are one-block-per-page government forms — and all ten render
byte-identical after the change. That is pinned as a test, alongside a
synthetic fixture built from a corpus form's own paragraph with a restarting
`linesegarray`. On the holdout: page 1 now starts with the title, the tail
draws at the top of page 2 where its cache puts it, and the page count is
unchanged at 18.


## E2 convergence — registration + fonts + table move in one tree, 2026-09-04

Three E2 renderer slices that had only ever been measured apart are now one
tree (`claude/engine-e2-converge`): the `hp:outMargin` registration inset
(#211, the branch this merge starts from), the bundled Korean fallback faces
(#208) and the inline-table move rule (#210, which also brings
`render_check.py` and the render-check corpus, plus `hwpx_write.py` from the
writer line). Every number pinned by any of the three is re-measured here on
the merged tree, and each one either moves with a stated reason or is
confirmed unchanged.

### Corpus scoreboard, `--corpus`, merged

Against the numbers #211 pinned (its own before → after table above is
untouched; this is that table's "after" column re-measured with fonts and the
table rule also present):

| form | ssim | ssim_inked | text_line_iou | pages c/r |
| --- | --- | --- | --- | --- |
| admrul | 0.9197 -> **0.9213** | 0.5007 -> **0.5067** | 0.5877 -> **0.5993** | 1/1 |
| gianmun-1ho | 0.9375 | 0.2965 | 0.8428 | 1/1 |
| gianmun-2ho | 0.9075 | 0.0538 | 0.6468 | 1/1 |
| jeongbo | 0.7571 | 0.2692 | 0.8273 | 1/1 |
| jumin | 0.6822 | 0.1399 | 0.6711 | 3/3 |
| kstartup | 0.8282 -> **0.8286** | 0.2884 -> **0.2888** | 0.2727 -> **0.2715** | 21/22 |
| moel-2013 | 0.7880 -> **0.7920** | 0.1008 -> **0.1081** | 0.5063 -> **0.5200** | 7/7 |
| moel-2025 | 0.7706 -> **0.7788** | 0.1918 -> **0.2015** | 0.5396 -> **0.5563** | 7/7 |
| nrf | 0.8924 -> **0.8951** | 0.4418 -> **0.4462** | 0.7225 -> **0.7059** | 4/4 |
| saeopja | 0.7664 | 0.2681 | 0.8060 | 6/6 |

Corpus means: `ssim` 0.8250 -> **0.8266**, `ssim_inked` 0.2551 -> **0.2579**,
`text_line_iou` 0.6423 -> **0.6447**, `text_line_pair_rate` 0.8364 ->
**0.8364** (unchanged).

**Every form that moves is a form the bundled family map answers for**, and
it moves by the amount #208 measured on the pre-registration tree — the two
slices are additive, not interacting. The five forms whose declared faces all
resolve installed (gianmun-1ho, gianmun-2ho, jeongbo, jumin, saeopja) are
byte-identical to #211. `nrf`'s `text_line_iou` still falls (0.7225 ->
0.7059), the same direction and the same cause #208 reported and did not
smooth over; registration does not rescue it.

**No page count moves.** `kstartup` reads 21/22 here, but that is its state on
#211 too — it is the one form whose page count has never been exact, and
`test_out_margin_changes_no_corpus_page_count` pins all ten counts, including
that 21. The inline-table move rule (#210) does not repaginate any public
corpus form; the one document it repaginates is the synthetic render-check
document, which is what it was written against.

### The registration rule channel is unmoved

`hp:outMargin`'s headline pin — 365/428 matched rules within 1 pt, 335/428
within 0.25 pt — was produced by an ad-hoc script that was never committed, so
it cannot be re-run byte-identically. What was done instead: the measurement
was reimplemented (candidate cell rectangles out of `_render_table` against
the reference PDF's own `l`/`re` drawing operators, per-axis scale correction,
order-preserving DP) and run twice, once on `origin/claude/engine-e2-registration`
and once on the merged tree. The reimplementation's own scale is smaller
(117 matched horizontal, 107 vertical, because it dedupes rule positions per
page rather than counting per cell side) and is **not** comparable to 365/428
in absolute terms. The two runs are:

| | 1 pt | 0.25 pt |
| --- | --- | --- |
| #211 | dy 117/117, dx 107/107 | dy 102, dx 99 |
| merged | dy 117/117, dx 107/107 | dy 102, dx 99 |

Identical, per form as well as in total, on all ten forms. So the merge moves
the registration channel by nothing and **365/428 and 335/428 stand as
written**.

### The line breaker is unmoved

`test_the_corpus_wide_agreement_is_exactly_this` pins
`[2148, 2097, 2004, 158, 135, 216, 65]` — the 58 -> 65 break-position column
#208 measured. It passes unchanged on the merged tree: registration is a
placement rule and moves no line box, so the breaker sees the same boxes.

### render-check-01

**1 · 32 · 16 · 2 -> 1 match · 35 close · 13 differs · 2 unsupported.**
`F47` from #210 (IoU 0.025 -> 0.535); `F31` (0.222 -> 0.376) and `F32`
(0.205 -> 0.479) from #211's inset. #208 is a measured no-op on that document
— it declares only 바탕, 돋움 and 궁서, all installed here. Page count moved
the wrong way, 10 -> 11 against Hancom's 9, because moving the table whole
removed the term that used to cancel the block-height drift. Full report:
[`docs/research/render-check-01.md`](../../docs/research/render-check-01.md).

### Not proven

- **The rule-agreement re-check is a reimplementation, not the original
  script.** It shows the merge changes nothing in that channel; it does not
  re-derive 365/428.
- **One machine.** Fonts still resolve against this machine's installed index,
  and #208's "installed always wins" is still verified by construction rather
  than on a second machine.
- **No slice was isolated by ablation.** `F31`/`F32` are attributed to
  registration because they move only once registration joins #210, and
  because #208 provably never fires on that document — not because a tree with
  registration removed was rendered.


## Layout was a function of the raster — measured, 2026-09-05

The ink-residual slice recorded a 144 dpi tally it could not claim, because
`F06` broke its lines in different places at 144 dpi than at 96. This is that
finding turned into a number, on a channel with no pixels in it.

### The instrument

`own_render.py --layout-digest` (`layout_digest()`) prints every layout
decision the renderer makes **in the document's own units**: line breaks as
character offsets, `horzpos`/`horzsize`/`vertpos`/`vertsize`/`baseline` in
HWPUNIT, and the flow pass's per-block page and page-relative top. Both
passes are forced to `computed`, because reading the cached `hp:lineseg`
boxes would be dpi-free whatever the renderer does and would measure nothing.
The report deliberately carries **no `dpi` field**: a renderer whose layout is
a function of the document alone emits the same bytes at every resolution.

The column a paragraph is broken into is the paragraph's own cached first line
box where the file carries one and the section's `usable_width` where it does
not (`render-check-01` carries no `linesegarray` at all). Both are read
straight out of the file.

### The drift, before

`render-check-01`, blocks `F06`–`F08`, characters per line:

| block | 96 dpi | 144 / 192 / 288 dpi |
| --- | --- | --- |
| `F06` (줄간격 130%) | 46 · **50** · 5 | 46 · **44** · 11 |
| `F07` (줄간격 160%) | 46 · **50** · 5 | 46 · **44** · 11 |
| `F08` (줄간격 200%) | 46 · **50** · 47 · 48 · 11 | 46 · **44** · 47 · **44** · 21 |

Six characters on `F06`'s second line, and the same six on every block that
shares its text. Whole documents, digest against the 96 dpi digest:

| document | 144 | 192 | 288 |
| --- | --- | --- | --- |
| `render-check-01` | 18 paras rebroken, +2 lines | 20, +3 | 19, +3 |
| `gianmun-byeolji-2ho` | 1 | 3 | 1 |
| `jeongbo-gonggae-cheongguseo` | 5 | 6 | 5 |
| `jumin-deungchobon` | 6, −1 line | 16, +3 | 7, −1 |
| `kstartup-…-saeopgyehoekseo` | 6, −1 | 18, +11, **+1 page, 122 blocks re-paged** | 5, −1 |
| `moel-…-2013` | 25, +12, **+2 pages, 77 blocks re-paged** | 19, +2, +1 page | 16, +2 |
| `moel-…-2025` | 10, −2, 75 blocks moved | 16, +4 | 3, −1 |
| `saeopja-deungnok` | 17, −8 | 24, −7 | 16, −8 |
| `admrul`, `gianmun-1ho`, `nrf` | identical | identical | identical |

Three of the ten forms were already dpi-independent — they are the ones whose
declared character sizes happen to land on integer pixels at every dpi tested.
The worst case is not the smallest raster: `moel-2013` gains **two pages** at
144 dpi relative to 96, and `kstartup` gains one at 192.

### The cause

`_font_for` asks the font book for `pt_to_px(pt) = max(1, round(pt * dpi/72))`
— an **integer** pixel size — and every advance was then `draw.textlength` on
that rasterised font. Two separate leaks, and both are in the layout:

1. **The integer size.** A 10 pt run is 13 px at 96 dpi and 20 px at 144. 13
   px is 9.75 pt, so the text is 2.5% narrower at 96 dpi than the document
   says it is, and 2.5% more of it fits on a line. That is the six characters.
2. **Hinting.** FreeType rounds a hinted glyph's advance to a whole pixel, so
   even at sizes that land exactly on an integer the per-glyph error is up to
   half a pixel — 1/40 em at a 20 px em, and a different fraction at every
   other size.

Nothing downstream of the advances is guilty. `_line_metrics` was already
HWPUNIT and reads declared sizes only; `_object_extent` is HWPUNIT;
`_half_cell_px` and `_offset_px` are exact linear functions of dpi; the
equation extent is already measured at a fixed 600 dpi and scaled. The break
positions were the whole of it, and everything else in the digest moved
because the breaks did.

### The fix

Every advance the layout uses is now measured off the face at a fixed
`LAYOUT_REFERENCE_PX = 1024` em and scaled analytically into HWPUNIT:

    advance_hwpunit = em_width(face, chunk) x declared_pt x 100 x ratio/100

`_em_width` is the only place a font is measured for layout, and its answer
is a property of the outlines and the kern table alone. The raster now enters
exactly once, at the end, when a glyph is drawn — `_font_for` still builds an
integer-pixel font, and the drawn pixel advance is `pxf()` of the HWPUNIT one,
so the drawing cursor and the breaker cannot disagree.

Everything the breaker compares moved to HWPUNIT with it:
`_char_advance_tables`, `span_width`, `_tab_advance`, `compute_lines`'s
`avail`/`width`/`slack`, and the `hh:spacing` gap (a pure proportion, correct
in either unit, so `_spacing_gap_px` became `_spacing_gap`). `_half_cell_hwp`
is the space cell in the document's units and `_half_cell_px` is now derived
from it. A line record gained `width_hwpunit`; `width_px` stays for the
drawing side.

**Which hinting story this is.** Not unhinted metrics — Pillow does not expose
them, and FreeType rounds a hinted advance to a whole pixel. This is the
large-reference-size story: at a 1024 px em that rounding is under 0.1% per
glyph and, decisively, it is the *same* 0.1% at every output resolution.
Stated in the constant's own comment so no reader has to infer it.

### After

`layout_digest` is byte-identical at 96 / 144 / 192 / 288 dpi on the
render-check document and on all ten corpus forms, asserted by
`test_the_layout_is_identical_at_every_dpi` (11 parametrised cases) and, for
the mechanism alone, by
`test_an_advance_is_the_same_fraction_of_an_em_at_every_dpi`. `F06`–`F08` now
read 46 · 44 · 11 at every dpi. The private report-class holdout is identical
across the ladder too (661 lines, 18 pages, at all four).

**Line breaker against the authoring engine's own cache**, corpus-wide,
144 dpi:

| channel | before | after |
| --- | --- | --- |
| break positions matched | 68 / 216 | **80 / 216** |
| per-decision exact (`conditional_breaks`) | 65 / 216 | **77 / 216** |
| — of the misses, `late` | 78 | 65 |
| paragraphs, exact break sequence | 2014 / 2148 | **2030 / 2148** |
| paragraphs, exact line count | 2105 | **2116** |

**What moved at the default 144 dpi.** Five of the eleven documents are
byte-identical before and after (`admrul`, `gianmun-1ho`, `gianmun-2ho`,
`jeongbo`, `nrf`) — their declared sizes already landed on integer pixels at
144. The six that move:

| document | paragraphs rebroken | lines | pages |
| --- | --- | --- | --- |
| `moel-2013` | 24 of 264 | 327 → 317 | 9 → 7 |
| `moel-2025` | 4 of 314 | 349 → 353 | 7 |
| `saeopja-deungnok` | 3 of 765 | 794 | 6 |
| `jumin-deungchobon` | 1 of 133 | 170 | 3 |
| `kstartup` | 2 of 462 | 509 | 22 |
| `render-check-01` | 1 of 227 | 281 → 282 | 7 |

`moel-2013` going 9 → 7 pages is a move *toward* the cached pagination, which
reads 7.

**Corpus scoreboard against the Hancom reference PDFs**, 144 dpi, `auto`
layout. Every form still comparable, every verdict still `pass`, every page
count unchanged. Means over the ten: `ssim_mean` +0.00078,
`ssim_inked_mean` +0.0021, `text_line_iou_mean` +0.00024. Per form, the
extremes: `gianmun-1ho` `ssim_inked` +0.0150 and `jumin` +0.0106 the good way;
`nrf` `ssim_inked` −0.0160 and `text_line_iou` −0.0128 the other. `nrf` is the
one regression worth naming — its faces happened to be better served by the
old 144 dpi rounding. **Diagnosed 2026-09-05** — see *The nrf regression the
resolution-independence slice left behind*: the face is 휴먼명조 resolving to
Nanum Myeongjo, Hancom advances it at 1.0000 em, we measure 0.9502 and the
old raster measured 0.9545, so the old number was accidentally closer.

**render-check-01 tally**, 9/9 pages exact at both resolutions:

| dpi | before | after |
| --- | --- | --- |
| 96 | 3 match · 38 close · 8 differs · 2 unsupported | **6 · 37 · 6 · 2** |
| 144 | 7 · 38 · 4 · 2 | **14 · 31 · 4 · 2** |

The 144 dpi tally the ink-residual slice recorded but would not claim is now
claimable, and it is the better of the two.

**Private holdout (aggregate only).** 18/18 pages exact, before and after.
`ssim_mean` 0.8132 → 0.8206, `ssim_inked_mean` 0.2927 → 0.3158,
`text_line_iou_mean` 0.7641 → 0.7651. Its lineseg break recall is unmoved at
59/252, but the per-decision accuracy goes 0.4365 → 0.4603 and the `late`
misses collapse 38 → 15: the breaker measures a line 0.9794 → 0.9840 as full
as the authoring engine did, which is the same 2% narrowness closing.

### Not proven

- **One machine, one font stack.** Every number here resolves faces against
  this machine's installed index. The em measurement removes the *resolution*
  dependence, not the face dependence.
- **1024 px is not zero.** Hinting still rounds each glyph advance to 1/1024
  em. It is identical at every dpi, which is what was asked, but it is not
  the unhinted outline advance and no test asserts a bound against one.
- **`line_boxes` reports the advance, not the ink.** A space that hangs past
  a line end moves the reported box (7.677 px on the relayout fixture) with no
  pixel drawn there. `test_a_relaid_out_paragraph_stays_inside_its_column`
  now checks the page raster instead, and names this as a follow-up: closing
  it moves `text_line_iou` on eight of the ten forms in both directions and
  needs its own measurement. **Measured and closed 2026-09-05** — see *Where
  a text line's box ends*. It moves the IoU on all ten, seven down and three
  up, for a mean of −0.00177.
- **The dpi ladder is four rungs**, 96–288. Nothing was measured below 96 or
  above 288, and `pt_to_px`'s `max(1, ...)` floor still exists for the raster.
- **The footnote column is now analytic too but is not in the digest.**
  `_note_mark_extent` and the note body column used to reach HWPUNIT through
  `hwp_from_px(draw.textlength(...))` — the same leak, in a channel
  `layout_digest` does not cover. They were converted with everything else,
  but no corpus document exercises them enough for the byte-identity
  assertion to be evidence about them.

### What is still measured on the raster, deliberately

`draw.textlength` survives in exactly two places, and neither is layout: the
glyph mask's buffer size in `_draw_glyph_piece` (a rasterisation allocation),
and the equation box, which is already measured at a fixed
`EQUATION_EXTENT_DPI = 600` and scaled — dpi-free by the same argument as
`LAYOUT_REFERENCE_PX`, arrived at earlier and independently.


## Where a text line's box ends — measured, 2026-09-05

The resolution-independence slice left a named follow-up: `line_boxes`
reported the *advance*, so a space landing at a line end moved the reported
box (7.677 px on the relayout fixture) with no pixel drawn there, and closing
it "moves `text_line_iou` on eight of the ten forms in both directions and
needs its own measurement". This is that measurement.

### Three conventions, and what the reference is

A line's right edge can be read three ways, and every `line_boxes` record now
carries all three explicitly:

| field | what it is |
| --- | --- |
| `x1_advance` | the advance of every glyph piece on the line, a trailing space included. What a **caret** needs. |
| `x1_ink` | where the last glyph's outline stops — the advance minus that glyph's right side bearing. What a **containment check** needs. |
| `x1_visible_advance` | the advance of the last piece that draws ink: the advance reading with trailing whitespace dropped. |
| `x1` | the geometry box, which follows `own_render.LINE_BOX_END`. |

**The reference is an advance box, not an ink box.** `render_scoreboard`
forms the reference line boxes from PyMuPDF's `page.get_text("dict")` line
`bbox`, which is the union of the line's per-character quads, and a MuPDF
character quad spans the character's **advance**, not its ink. Read straight
off the corpus: a 12.96 pt Hangul character in the nrf reference measures
exactly 12.96 wide, i.e. 1.000 em, which is its full-width cell advance —
its ink is narrower on every face (맑은 고딕's `가` inks 1000 of a 1024 em).
Over all 21995 full-width characters in the ten reference PDFs the median is
1.0000 em and 92.1% land within 0.005 em of it.
`test_the_reference_line_box_is_an_advance_box_not_an_ink_box` asserts both
halves.

Pillow is not a way round this: `FreeTypeFont.getbbox` also reports the
advance box (a space's `getbbox` is as wide as its advance and zero high), so
the ink edge has to come off the rendered mask. `_em_right_bearing` measures
it at `LAYOUT_REFERENCE_PX` and divides, so it is dpi-free for the same
reason `_em_width` is, and only the chunk's LAST character is measured:
kerning moves a glyph's origin, never its own advance, so the ink right edge
of a chunk is the chunk's advance minus its last character's bearing (바탕:
`abc` is 1700/1639 and `c` alone 555/494 — the same 61 units).

### The measurement

The scoreboard's pairing is greedy by centre distance and will happily pair
two lines holding different text, which puts a 150 px tail on **every**
convention alike and measures the line breaker rather than the box end. So
the decision is read off the confident subset: pairs whose left edges agree
to 1.5 px and whose baselines agree to 2.0 px, i.e. lines that demonstrably
start in the same place. 817 of the 2086 corpus pairs, 144 dpi:

| convention | n | median abs(dx) | p90 abs(dx) | mean IoU |
| --- | --- | --- | --- | --- |
| `ink` | 817 | 2.484 | 5.427 | 0.8480 |
| `advance` | 817 | 0.371 | 6.239 | 0.8707 |
| `visible_advance` | 817 | **0.363** | **5.275** | **0.8713** |

`ink` loses decisively, as the reference reading above predicts. The two
advance readings are close, and the reason is that **the reference itself is
not consistent**. They differ on only 34 of the 817 — the lines that end in
whitespace — and on those Hancom splits:

| the reference PDF… | n | `advance` median abs(dx) | `visible_advance` median abs(dx) |
| --- | --- | --- | --- |
| dropped the trailing space | 19 | 12.676 | **1.750** |
| kept the trailing space | 15 | **2.682** | 9.591 |

19 > 15 is the whole of `visible_advance`'s margin, and nothing in the OWPML
predicts which way a given line will go. `LINE_BOX_END = "visible_advance"`
is adopted on that evidence and is a **named soft call**, not a proof.

### What it cost, per form

Corpus scoreboard, 144 dpi, `auto` layout. `ssim`, `ssim_inked`, page counts,
pair rates and every lineseg channel are byte-identical before and after —
nothing about the raster or the layout changed, only what the sidecar reports
— so `text_line_iou_mean` is the only column that moves. It moves on all ten
forms, seven down and three up:

| form | text_line_iou_mean |
| --- | --- |
| `nrf-gyeolgwa-bogoseo-yangsik` | **−0.01222** |
| `gianmun-byeolji-1ho` | −0.00378 |
| `jeongbo-gonggae-cheongguseo` | −0.00370 |
| `admrul-gajokdolbom-hyuga-sinchengseo` | −0.00261 |
| `gianmun-byeolji-2ho` | −0.00129 |
| `kstartup-…-saeopgyehoekseo` | −0.00114 |
| `saeopja-deungnok-sinchengseo` | −0.00066 |
| `moel-…-2013` | +0.00153 |
| `moel-…-2025` | +0.00232 |
| `jumin-deungchobon-sinchengseo` | **+0.00386** |

Mean over the ten: 0.647522 → 0.645754, **−0.00177**. Every verdict is
unchanged, every page count is unchanged, `text_line_pair_rate_mean` is
unchanged at 0.836210.

`render-check-01` is unmoved: 9/9 pages exact and the tally is 6 · 37 · 6 · 2
at 96 dpi and 14 · 31 · 4 · 2 at 144, the same as after the
resolution-independence slice. The private report-class holdout is 18/18
pages exact before and after, with `ssim_mean` 0.746015 and
`ssim_inked_mean` 0.175313 unchanged and `text_line_iou_mean`
0.585179 → 0.583784.

**The IoU channel and the abs(dx) channel disagree, and this is recorded
rather than resolved.** On all 2086 pairs — mispairings included — `advance`
scores 0.670222 and `visible_advance` 0.669558, which is where the −0.00177
comes from; on the 817 confident pairs the order reverses (0.8707 vs 0.8713).
The brief for this slice was to minimise abs(dx) on paired lines and that is
what was done; a reader who cares about the aggregate IoU number more than
about the box being right should flip `LINE_BOX_END` back to `"advance"` and
will get the old numbers exactly.

### The relayout containment test, tightened

`test_a_relaid_out_paragraph_stays_inside_its_column` had to give up its
one-pixel bound on the reported box when the resolution-independence slice
made the trailing-space hang visible; it now has it back, on `x1` and on
`x1_ink`, while `x1_advance` is still allowed the half-cell hang and is
asserted to actually take it on the fixture (7.020 px and 8.667 px at 96
dpi). The raster check — no ink right of the column edge — is unchanged.

## The nrf regression the resolution-independence slice left behind

That slice named one form moving the wrong way: `nrf` `ssim_inked` −0.0160
and `text_line_iou` −0.0128. Diagnosed here, and **not fixed here**.

### It is not a layout regression

`nrf`'s line breaking did not change at all. Its `--lineseg-agreement` report
is identical at `origin/claude/engine-e2-ink-residual` (75a1264) and at
2339ce7 on every channel — 234 JSON leaves, 3 differ, and all three are the
`cached_line_fill` percentiles (median 0.984049 → 0.983573). Break positions,
break sequences, line counts, first-line boxes: unchanged. So the new layout
is neither closer to Hancom's cached `hp:lineseg` nor farther from it; the
"if farther" branch of the question does not arise. (`--layout-digest` itself
cannot be diffed across that pair — it was added by the slice under
examination — so the agreement report, which both revisions carry, is the
channel that answers it.)

What changed on `nrf` is the **drawing**: under `auto` it keeps its cached
linesegs, and only the intra-line cursor moved, from `draw.textlength` at a
rounded raster size to `pxf` of the analytic 1024 px em.

### The face, and what the reference says

The glyph class is the full-width cell, and the face is a 한양 one resolved
through the bundled map. `nrf` sets 639 of its 1063 full-width characters in
휴먼명조, which is not installed on this machine and resolves to Nanum
Myeongjo. Measured three ways, in EM:

| | Hangul advance |
| --- | --- |
| Hancom's own reference PDF (n = 639, p05 = p95 = median) | **1.0000** |
| our new 1024 px em measurement (Nanum Myeongjo) | 0.9502 |
| the old raster measurement (21 px of a 22 px font) | 0.9545 |

So **neither** the old advance nor the new one is right, and the old one was
accidentally 0.4% closer because FreeType rounded 20.9 px up to 21. That
rounding is the whole of the named regression.

### The rule that follows, measured, and why it is a follow-up and not a fix

The right answer is the rule this codebase already states in two places and
does not apply on the advance path: `is_full_width`'s docstring and
`_cached_lower_bound_hwp` both say a full-width cell advances by exactly the
declared character size × `hh:ratio`, whatever face draws it — the full-width
counterpart of `SPACE_CELL_FRACTION`. The reference PDFs agree: 21995
full-width characters, median 1.0000 em, 92.1% within 0.005 em, and per
document the median is 1.0000 or 1.0003 on nine of the ten.

It was implemented and measured on the corpus, and it is **not shipped**,
because it buys the raster channel at the line breaker's expense:

| channel | before | with the full-width cell rule |
| --- | --- | --- |
| `nrf` `text_line_iou_mean` | 0.69946 | **0.72981** |
| `nrf` `ssim_inked` | 0.45356 | **0.46134** |
| `nrf` `cached_line_fill` median | 0.9423 | **0.9836** |
| corpus `text_line_iou_mean` | 0.647522 | 0.650740 |
| corpus `ssim_inked_mean` | 0.276175 | 0.278762 |
| corpus `ssim_mean` | 0.830919 | 0.829829 |
| **corpus break positions matched** | **80 / 216** | **66 / 216** |
| paragraphs, exact break sequence | 2030 / 2148 | 1981 / 2148 |
| — of the misses, `early` | 74 | 93 |

It more than reverses the named `nrf` regression and moves
`cached_line_fill` toward 1.0 on three forms and away on none (jumin +0.0081,
kstartup +0.0132, nrf +0.0413), which is the direct evidence that the advance
itself gets *more* correct. But it breaks `moel-2013`, `moel-2025`, `jumin`
and `kstartup` lines earlier, because those forms **already** measured their
own cached lines as overflowing before the change (`cached_line_fill` p90
1.0258 and 1.0458 on the two `moel` forms) and a correct, wider full-width
cell pushes more of them over. That over-measure is a separate, pre-existing
defect — the reference PDF says those forms' 휴먼명조 cells are 1.0003 em
flat, so Hancom is fitting text a 1.0 em model says will not fit — and it has
to be found before the cell rule can land without lowering
`test_the_breaker_agrees_with_the_authoring_engine_exactly_this_much`.

### Not proven

- **The trailing-space split is 34 lines.** 19 against 15 decided
  `LINE_BOX_END`, on one machine's font stack. A different corpus could
  reverse it, and no mechanism was found that predicts which lines Hancom
  writes the space into.
- **`x1_ink` is the mask's ink, not the outline's.** It is measured off a
  1024 px FreeType mask, so it carries the same sub-0.1%-per-glyph hinting
  residual `LAYOUT_REFERENCE_PX` already declares, and it excludes the
  antialias fringe and any synthetic-bold smear, both of which put a pixel or
  two of real ink past it.
- **The confident subset is a filter, not a ground truth.** 817 of 2086 pairs
  qualify; the other 1269 are dropped because our line and the reference's do
  not start in the same place, which is usually a line-breaking disagreement
  but is not proven to be one, line by line.
- **The full-width cell rule was measured, not ablated.** Its cost is
  attributed to the pre-existing over-measure on `moel`/`jumin` because those
  forms' fills were already over 1.0 before it, not because a tree with that
  over-measure removed was rendered.

## The computed-vs-cache gap was an empty run — measured, 2026-09-05

PR #244 made the layout policy document-wide: an untouched Hancom package is
drawn from its cached `hp:lineseg`, and anything this repo wrote, edited or
cannot identify is laid out `computed` for the whole document. Computed is
therefore what every edited document now gets, and the price of it was the
open question. On the corpus at 144 dpi it was 0.645754 → 0.588691
`text_line_iou_mean` and 0.830919 → 0.816681 `ssim_mean`. This is where that
0.057 went.

### The instrument

Both policies are rendered through `OwnRenderer.render()`, with the two
paragraph draw paths (`_render_cached_lines`, `_render_computed_lines`)
wrapped so every `line_boxes` record carries the paragraph that produced it.
A paragraph is then classified by comparing its two lists of boxes:

* **A** — a box's `x0`/`x1` moved, or the paragraph produced a different
  number of lines: the breaker chose different break positions;
* **B** — the same boxes, the same widths, a different `y0`: the line is in
  the right place across the column and the wrong place down the page;
* **C** — a box changed page.

Paragraph identity is what makes the classes mean anything. Pairing boxes by
proximity, which is what the scoreboard has to do against a PDF, cannot tell
class A from class B at all: a line that moved 20 px down pairs with its
neighbour and reads as a break error.

### Where the computed layout diverges, before

144 dpi, ten forms, every paragraph that drew a line under both policies:

| form | agree | A break | B vertical | C page | A and B |
| --- | --- | --- | --- | --- | --- |
| `admrul` | 4 | 1 | **14** | 0 | 1 |
| `gianmun-1ho` | 23 | 1 | 4 | 0 | 0 |
| `gianmun-2ho` | 13 | 3 | 0 | 0 | 0 |
| `jeongbo` | 43 | 12 | 0 | 0 | 0 |
| `jumin` | 70 | 57 | 1 | 0 | 1 |
| `kstartup` | 109 | 20 | 25 | **239** | 8 |
| `moel-2013` | 198 | 35 | 23 | 0 | 1 |
| `moel-2025` | 82 | 40 | **145** | 0 | 37 |
| `nrf` | 33 | 9 | **42** | 0 | 2 |
| `saeopja` | 628 | 55 | 22 | 0 | 52 |

The counts do not rank the mechanisms; the IoU does. Sorted by what each form
lost going from `cache` to `computed`: `admrul` −0.40016, `moel-2025`
−0.22322, `nrf` −0.16632, `saeopja` −0.09131 — and `kstartup` **+0.37000**,
the one form dominated by class C, whose extra page moves it *toward* the
reference. Every form that lost is a form dominated by class B. The line
breaker, which is what a reader expects to be at fault, is not where the
corpus loses its ink.

Class B is a constant per document, not a scatter. `admrul` moves 14 of its
19 drifting paragraphs by exactly −20.00 px; `nrf` moves one run of
paragraphs by −8.00 px and another by +102.40 px; `moel-2025` moves by
+29.76 px and then sheds 0.02 px per line after that. A constant offset
shared by every paragraph below a point in the document is a **block
height**, not a line box.

### The mechanism

`--flow-agreement` reads the flow pass against the cache with the line boxes
held fixed, and `--flow-agreement --line-layout computed` reads the two
errors compounded. On `admrul` the first is exact on 15 of 15 blocks and the
second puts 13 of the 15 at exactly 1000 HWPUNIT — 10 pt, 20 px at 144 dpi —
too high. So the block model is right and one block is measured 1000 HWPUNIT
too short. `_flow_lines` measures a computed block as the sum of
`vertsize + spacing` over its lines, and exactly one line in the whole corpus
is off by more than 2 HWPUNIT:

    admrul paragraph 1, the page's inline table
      cached    vertsize 6618   spacing 2400
      computed  vertsize 6618   spacing 1400

The paragraph is one `hp:run` at 14 pt holding the table and a **second run
at 24 pt whose `<hp:t>` is empty**. The line spacing is 200%, and 2400 is
what 200% of 24 pt leaves over — not 200% of 14 pt, which is the 1400 this
renderer computed. `_line_metrics` walked `para.chars`; an empty run puts no
character there, so the 24 pt shape was invisible to it.

**The rule.** `hh:charPr@height` is a property of the `hp:run`, not of the
characters in it: `hp:run@charPrIDRef` applies to the run whether or not the
run emits text, and the paragraph mark that ends the line is drawn in the
shape the last run declares. So a run that puts no character on a line still
declares that line's character height. `Paragraph` now records `empty_runs`
as `[(char_index, charPrIDRef)]` and `_line_metrics` reads the ones whose
position falls inside the line, the last line owning one that sits at the end
of the character stream.

Measured against the authoring engine's own cache over all 2370 cached lines
of the ten forms, with the cached `textpos` boundaries fixing line identity:

| reading | `vertsize` exact | `spacing` exact | both |
| --- | --- | --- | --- |
| only runs that put characters down | 2365 / 2370 | 1482 | 1481 |
| the empty run joins the PITCH | 2365 | 1487 | 1482 |
| the empty run joins the HEIGHT too | **2370 / 2370** | **1487** | **1487** |

The third row is the one that ships. It is exact on every cached line in the
corpus and there is no line the other two get right and it gets wrong. Every
surviving `spacing` miss is within 2 HWPUNIT of the cache — 0.02 pt, 0.0004
px at 144 dpi — on 883 lines, all of them `PERCENT`. That residual is a
rounding difference in how the pitch is divided into `vertsize + spacing`,
not a rule, and it is not chased here.

### After

Corpus scoreboard, 144 dpi, the policy pinned on both sides:

| channel | computed, before | computed, after | `cache` |
| --- | --- | --- | --- |
| `text_line_iou_mean` | 0.588691 | **0.633897** | 0.645754 |
| `ssim_mean` | 0.816681 | **0.824293** | 0.830919 |
| `ssim_inked_mean` | 0.249020 | **0.277430** | 0.276175 |
| `text_line_pair_rate_mean` | 0.847831 | 0.847831 | 0.836210 |

The gap this slice set out to price closes from −0.05706 to −0.01186 on
`text_line_iou_mean`, and `ssim_inked_mean` under computed layout is now
*above* the cache's. Per form only `admrul` (+0.39449), `nrf` (+0.04648),
`gianmun-1ho` (+0.01133) and `jumin` (+0.00011) move; `saeopja` moves
−0.00036 and the other five are unchanged to five decimals. `admrul`'s
scoreboard verdict goes back to `pass`, which computed layout had been
failing. `--flow-agreement --line-layout computed` on `admrul` is now exact
on 15 of 15 blocks.

**Nothing on the cache path moved.** The ten forms' scoreboards are
byte-identical before and after, per form and in aggregate, and `render_check`
on `render-check-01` is byte-identical at 96 and 144 dpi: 9/9 pages exact,
6 · 37 · 6 · 2 at 96 and 14 · 31 · 4 · 2 at 144. The line breaker is
untouched by construction — `_line_metrics` runs after `compute_lines` has
already chosen its spans — and the lineseg channel confirms it: 80/216 break
positions matched, 77/216 per-decision exact, 2030/2148 paragraphs with an
exact break sequence, the same numbers the resolution-independence slice
left.

### What is left, and it is not this

Class B does not go to zero. After the fix it is 0 on `admrul`, 29 on `nrf`,
145 on `moel-2025`, 25 on `kstartup`, 23 on `moel-2013` and 22 on `saeopja`,
and the three surviving shapes are different mechanisms:

* `moel-2025`'s +29.76 px is downstream of a class-A error — its paragraph 6
  breaks into two computed lines where the cache has one — and the 0.02 px it
  sheds per line after that is the ±1 HWPUNIT `spacing` rounding above,
  accumulating down the column.
* `nrf`'s +102.40 px starts at one paragraph and holds for the rest of the
  document: another block measured short, not yet attributed.
* `kstartup`'s 239 class-C paragraphs are its 21 → 22 page difference, and
  that difference scores *better* than the cache.

### Not proven

- **One form carried the whole finding.** `admrul` is the only corpus
  document whose empty run is a different size from the run beside it in a
  way that costs 10 pt. The rule is right on all 2370 corpus lines, but 2365
  of them were already right; the evidence that it is a RULE and not a patch
  is the OWPML reading of `hp:run@charPrIDRef` plus admrul's cached `spacing`
  being exactly 200% of the empty run's 24 pt.
- **The pitch-only reading was not ruled out by a reference render.** Putting
  the empty run into the height as well is what makes `vertsize` exact on the
  last 5 lines, and those 5 are why the third row was chosen — but no
  reference PDF was measured to confirm that a taller empty run grows the
  DRAWN line box rather than only the pitch.
- **The ±2 HWPUNIT spacing residual is unexplained.** 883 of 2370 lines,
  every one `PERCENT`, every one within 2 HWPUNIT. Sub-pixel per line, but it
  accumulates, and `moel-2025`'s 0.02 px per line is it showing up in the
  render.
- **`nrf`'s remaining 102.40 px was not diagnosed.** It is a block height by
  the same constant-offset argument used above, but which block and why is
  not measured.
- **The classification is 144 dpi and this machine's font stack.** Class A in
  particular is partly a font-substitution artefact — the corpus resolves
  휴먼명조 and friends to bundled substitutes whose advances are not Hancom's
  — and no attempt was made here to separate that from the breaking rules.
- **The holdout is not in these numbers.** The private report-class document
  was not opened; whether the same empty-run line exists in it, and what it
  is worth there, is the operator's measurement to make.

## The classification is a tool now: `layout_divergence.py`

The A/B/C table above was produced by an ad-hoc pass that was never
committed, which is the whole reason the private holdout could not be
measured the same way: only the operator may open it, and there was nothing
to hand them. `engine/scripts/layout_divergence.py` is that pass, committed.

    python engine/scripts/layout_divergence.py FORM.hwpx --out DIR [--dpi 144] [--no-text]
    python engine/scripts/layout_divergence.py --corpus --out DIR [--iou]

It renders the document twice in one process through a subclass of
`OwnRenderer` that tags every `line_boxes` record with the `address` of the
paragraph that drew it — own_render's own global `paragraph_index`, so the
identity comes from the XML tree and is the same under both policies — and
with that line's text. Lines pair by ordinal inside a paragraph. Each pair is
class **A** if it is unpaired or the text differs, else **C** if the page
differs, else **B** if `|dy|` exceeds `--y-tol` (default 0.01 px, i.e. exact
up to the sidecar's rounding), else `agree`. The module docstring carries the
rule and the precedence argument; `engine/tests/test_layout_divergence.py`
pins them.

`DIR/<stem>.divergence.json` holds the per-class counts (per line and per
paragraph), each divergent paragraph's first divergent line, and a histogram
of rounded class-B `dy` — the channel on which a constant per-document offset
shows up as one tall bar. Line text is truncated to 12 characters and
`--no-text` omits the field entirely, which is what a holdout run should use.

### What it measures on the corpus, at this tip

144 dpi, paragraphs (a paragraph is counted under every class one of its
lines lands in), 17 s for the whole corpus:

| form | agree | A | B | C | A&B | IoU delta |
| --- | --- | --- | --- | --- | --- | --- |
| `admrul` | 17 | 1 | 1 | 0 | 0 | −0.00567 |
| `gianmun-1ho` | 27 | 1 | 0 | 0 | 0 | −0.00367 |
| `gianmun-2ho` | 16 | 0 | 0 | 0 | 0 | +0.00317 |
| `jeongbo` | 50 | 5 | 0 | 0 | 0 | +0.00092 |
| `jumin` | 110 | 17 | 2 | 0 | 0 | −0.00464 |
| `kstartup` | 43 | 31 | 98 | **233** | 1 | **+0.37000** |
| `moel-2013` | 127 | 20 | 112 | 0 | 2 | −0.04396 |
| `moel-2025` | 36 | 43 | **225** | 0 | 0 | −0.22322 |
| `nrf` | 55 | 2 | 29 | 0 | 0 | −0.11984 |
| `saeopja` | 673 | 16 | 71 | 0 | 3 | −0.09167 |

The IoU column is `--iou` (`render_scoreboard.score_form` on both policies
against the same reference PDF, 78 s for the corpus) and it reproduces the
"After" section above exactly, form by form: `admrul` −0.40016 + 0.39449 =
−0.00567, `nrf` −0.16632 + 0.04648 = −0.11984, `saeopja` −0.09131 − 0.00036 =
−0.09167, `kstartup` +0.37000 unchanged. The render path this tool traces is
therefore the same render the scoreboard scores.

### It does NOT reproduce the A/B/C table above, and here is the whole of why

Read against "Where the computed layout diverges, before":

* **That table is the state before `c16a93a`.** The empty-run height fix
  landed between it and this tool, and the "What is left" section already
  records what it moved: class B on `admrul` 14 → 0 and on `nrf` 42 → 29.
  At `--y-tol 0.5` this tool gives `admrul` 0 and `nrf` 29 — the post-fix
  numbers, exactly. The IoU column above says the same thing more sharply.
* **The tolerance.** The default 0.01 px counts the ±2 HWPUNIT `PERCENT`
  spacing residual (0.02–0.08 px per line) as class B; the ad-hoc pass did
  not. That residual is most of the excess: at `--y-tol 0.5` the B column
  falls to `admrul` 0, `jumin` 1, `kstartup` 28, `moel-2013` **23**,
  `moel-2025` 173, `nrf` **29**, `saeopja` 68 — and 23 and 29 are the
  earlier table's numbers on the nose. The default stays exact: the residual
  is real ink displacement, it accumulates down a column, and burying it
  under a tolerance is how it stopped being visible the first time.
* **The A rule is not the earlier one, and the earlier one is not
  recoverable.** The table above defines A as "the paragraph produced a
  different number of lines". Implemented literally that gives `admrul` 0 and
  `jeongbo` 0 against the table's 1 and 12, so the ad-hoc pass was not using
  its own stated test either. This tool uses text inequality on the paired
  ordinal — a superset of the count test, since it also catches a re-break
  that preserves the line count — and gets `jumin` 17 against 57 and
  `saeopja` 16 against 55. Neither rule lands on those numbers, the script
  that produced them is not in the repo, and nothing here was bent to close
  the gap.
* **The denominator differs.** The earlier rows sum to fewer lines than the
  corpus draws (`saeopja` 705 against 782 boxes here), so its scope was a
  subset — paragraphs that drew a line under *both* policies, which drops
  exactly the unpaired population this tool books as class A.

`moel-2025` (225 against 145) and `saeopja` (71 against 22) do not close at
any tolerance. Both are downstream of class A: once one line re-breaks, every
later line in the paragraph moves, and a text-based A/B split books that tail
differently from a count-based one.

### Not proven, for this tool

- **The corpus is the training set for the rule and the holdout is not in
  it.** The private report-class document was not opened here either. The
  tool exists so the operator can run it, with `--no-text`, and get the same
  four columns without handing anyone the document.
- **Class A still mixes the breaker with the font stack.** Nothing here
  separates a break the rules moved from a break a substituted advance moved,
  and `jumin`'s 41 class-A lines are the population where that matters most.
- **The pairing assumes draw order is line order within a paragraph.** It is,
  for every path in this renderer today — including a paragraph split across
  a page, which draws its halves in page order — but nothing enforces it.

## Attributing class B to the re-breaks above it — measured, 2026-09-05

The open question the divergence tool left was whether class B is mostly its
own error or the shadow of class A: a paragraph that breaks into one more
computed line pushes everything below it down by one line pitch, and every
one of those pushed paragraphs is booked class B although its own layout is
right. `layout_divergence.py` now answers it, and the answer is *the cause is
upstream far less often than the shape suggests, and where it is upstream the
pitch does not predict the amount*.

### The rule

Per page, paragraphs in reading order, two totals carried over the paragraphs
BEFORE the current one:

* `upstream_line_delta` — the sum of `computed lines − cache lines`;
* `expected_dy_px` — the same sum weighted by each of those paragraphs' own
  line pitch.

A class-B paragraph is `B_inherited` when `upstream_line_delta` is non-zero
**and** the dy of its first class-B line is within `--attribution-tol`
(default 1.0 px) of `expected_dy_px`; otherwise `B_own`. The non-zero guard is
not a formality: with nothing re-broken above it the prediction is exactly 0,
so without the guard every sub-pixel drift would read as "explained by an
upstream delta of zero lines" and the ±2 HWPUNIT `PERCENT` spacing residual —
most of class B at the default `--y-tol` — would disappear into `B_inherited`.

A paragraph's **pitch** is the dominant step between the `y0` of its
consecutive computed lines on one page. That step is `vertsize + spacing` by
this renderer's own line-position relation (`vertpos[i] == vertpos[i-1] +
vertsize[i-1] + spacing[i-1]`), so the pitch is read off the render rather
than re-derived. A paragraph with one computed line falls back to the same
step over its cached linesegs — its own `hp:lineseg` `vertsize + spacing` —
and then to the pitch carried down from the nearest preceding paragraph that
had one. The accumulators reset at every page boundary, because a dy measured
from a different page top is not a dy.

Both accumulators are exposed per paragraph (`expected_dy_px`,
`residual_px`) alongside the brief's simpler reading
(`simple_expected_px = upstream_line_delta × pitch`, `residual_simple_px`),
so the two can be compared instead of one being trusted.

### The corpus split

144 dpi, `--no-text`, ten public forms, paragraphs:

| form | B | B_inh | B_own (upstream re-break) | B_own (none) |
| --- | --- | --- | --- | --- |
| `admrul` | 1 | 0 | 0 | 1 |
| `gianmun-1ho` | 0 | 0 | 0 | 0 |
| `gianmun-2ho` | 0 | 0 | 0 | 0 |
| `jeongbo` | 0 | 0 | 0 | 0 |
| `jumin` | 2 | 1 | 0 | 1 |
| `kstartup` | 98 | 0 | 0 | 98 |
| `moel-2013` | 112 | 4 | 21 | 87 |
| `moel-2025` | 225 | 0 | **161** | 64 |
| `nrf` | 29 | 0 | 0 | 29 |
| `saeopja` | 71 | 0 | 33 | 38 |
| **total** | **538** | **5** | **215** | **318** |

Five of 538. The hypothesis as stated — dy is a whole number of line pitches
inherited from upstream — is **refuted on this corpus**, and the two ways it
fails are different mechanisms:

* **318 class-B paragraphs have no re-break above them at all.** For
  `kstartup` (98) and `nrf` (29) that is the whole column. `nrf`'s residual is
  +102.40 px on all 29, one bar, which is the undiagnosed block height the
  empty-run slice already named; `kstartup`'s is −0.08 px on 46 and −0.04 px
  on 24, which is the `PERCENT` spacing residual accumulating down the page.
  Neither is a break error and neither is inherited.
* **215 do have a re-break above them, and the pitch over-predicts the
  push.** `moel-2025` paragraph 6 breaks 1 → 2 computed lines; the step
  between its two computed lines is 35.90 px, but every paragraph below it
  moves by 29.76 px, not 35.90. The residual is a constant, not a scatter:
  −6.14 px at `upstream_line_delta` 1, and per added line the whole form
  clusters at −10.01 (34 paragraphs), −6.67 (34) and −20.02 (5). `saeopja`
  clusters at −20.22 per added line on 17. A constant miss per added line
  means the missing term is a rule, not noise: re-breaking a paragraph does
  not only append a line, it changes the `spacing` of the lines that were
  already there, and the block grows by the new line's own advance rather
  than by the paragraph's dominant one.

So class B *is* downstream of class A on the forms where class A is present —
161 of `moel-2025`'s 225 — but "downstream" is not "one pitch per line".

### Class A and the font stack

For each class-A paragraph the report now names its first divergent line's
break cause: the line count each policy made, the character count on each
side of that ordinal (so "computed broke earlier" is a shorter computed line),
the drawn width in px on each side, and every run's face — declared name, the
family it resolved to, and whether that was `installed`, `bundled` (the
repo's OFL substitute for a Hancom face) or `system` (the machine-dependent
fallback).

Over the corpus's 136 class-A paragraphs: **96 draw every run on an installed
face and 40 have at least one substituted run** (37 bundled, 9 system; a line
mixing both is in each) — a 0.294 substituted share. By characters it is
4556 installed, 655 bundled, 111 system. Per form the split is bimodal rather
than uniform: `jumin` 17/17, `jeongbo` 5/5 and `saeopja` 16/16 installed, and
at the other end `admrul` 1/1 and `nrf` 2/2 substituted, `moel-2025` 27 of 43.
`admrul`'s single class A is the clean case — 바탕 falls through to
`malgun.ttf`, the computed line is 54.23 px narrower than the cached one, and
it breaks two characters earlier.

Read against the hypothesis this slice was sent to test: **the fallback-font
advance is a real contributor to class A but it is not most of class A.**
Seventy per cent of class-A paragraphs re-break with every run on the face the
document asked for, so the breaking rule itself is doing most of the work.

### Not proven

- **The pitch model's residual is not explained, only shown to be constant.**
  −6.14 px per added line on `moel-2025`, −20.22 on `saeopja`. Reading the
  actual `vertsize + spacing` of the added line — which needs tagging the
  advance onto each drawn line, not inferring it from `y0` steps — would say
  whether the whole miss is the added line's own advance being smaller than
  the paragraph's dominant one. That is the next measurement, not this one.
- **`B_own_with_upstream_rebreak` is a correlation.** A re-break above a
  drifting paragraph on the same page is not proof it caused the drift; the
  constancy of the residual is the evidence, and it is circumstantial.
- **The class-A font share is this machine's font stack.** A machine with
  Hancom Office installed resolves more of these faces and would move the
  96/40 split; the `bundled` rows are stable across machines by construction,
  the `system` rows are not.
- **Nothing here separates a break the rules moved from a break a substituted
  advance moved.** The 96 installed-face class-A paragraphs prove the breaker
  differs from Hancom's on faces we have; they do not price it.
- **The holdout is not in these numbers.** The private report-class document
  was not opened. `--no-text --corpus` is what the operator runs on it; the
  four attribution columns come back without any document content.
- **`own_render.py` was not touched.** This slice measures. The corpus
  scoreboard, the classification counts and the IoU column are all unchanged
  from #249's tip.

## What sits above the first drift on a page — measured, 2026-09-05

#250 left class B with a shape nobody had a mechanism for: 318 of 538
class-B paragraphs have nothing re-broken above them, and on the private
holdout the residual is a whole multiple of the body pitch — +48, +72, +24,
+264, +120 px at 96 dpi against a 24 px pitch — with an upstream line-count
delta of 0 on 224 of 267.  Whole pitches that no re-break produced means the
height is added BETWEEN paragraphs or at a paragraph's bottom, and the
paragraph immediately above the first drift on a page is the only place it
can come from.  `layout_divergence.py` now reports that paragraph.

### The instrument

Per page, paragraphs in document order: find the first whose ordinal-0 line
is paired on the same page under both policies and whose `dy` exceeds
`--y-tol`, and report its PREDECESSOR with its last line under each policy
(the cache's `vertpos`/`vertsize`/`spacing`, the computed side's `y0`/`y1`
and pitch), the two candidate bottoms those imply, the gap from each bottom
to the drifting paragraph's first line, and the predecessor's own `hh:paraPr`
— line spacing type and value, `hh:margin/prev` and `/next`, whether its text
is empty, and every object it carries with that object's extent under both
policies.  `first_drift_predecessors.kinds` is a histogram keyed on
`(anchor kind, empty text, line spacing type)` and `dominant_kind` is its
tallest bar.

Two bottoms, deliberately.  `ink` is `y0 + vertsize`, which is
`_cached_extent`'s reading and excludes the last line's trailing `spacing`;
`advance` is `y0 + vertsize + spacing`, which is what `_flow_lines` sums into
a block height.  Which of the two the gap below a paragraph is measured from
was the first candidate mechanism, and the report states both rather than
picking one.

**The population that matters here is one the A/B/C classification cannot
see.**  A paragraph with no characters draws no line box — `_render_paragraphs`
and `_render_flow_page` both `continue` on `not para.chars` — so it is in
neither policy's `line_boxes`, its line-count delta is 0 either way, and every
paragraph below it is booked `B_own_no_upstream_rebreak` however wrong its
height is.  For those the report leaves the pixel domain: the cache states a
height (the sum of the paragraph's `hp:lineseg` advances) and the flow pass
states another (its seat height, captured off `_render_flow_page`), and the
difference is the drift in the units it was made in.  Their page membership
comes from the flow seat, or by ENCLOSURE — a paragraph lying between two
paragraphs that are both on one page is on it too; neighbours that disagree
leave it unplaced rather than guessed at.

### What the corpus says

144 dpi, `--no-text`, ten forms.  Pages that have a drift at all, keyed by
the kind of paragraph the drift starts under:

| predecessor kind | `--y-tol 0.01` | `--y-tol 0.5` |
| --- | --- | --- |
| `none` / text / `PERCENT` | 13 | 10 |
| `inline:tbl` / empty / `PERCENT` | 5 | 4 |
| `none` / empty / `PERCENT` | 4 | 3 |
| **pages with a drift** | **22** | **17** |

Per form the dominant kind at `--y-tol 0.5` is `none/empty=0/PERCENT` on
`jumin` (1/1), `moel-2013` (3/4), `moel-2025` (5/6) and `saeopja` (1/3),
`inline:tbl/empty=1/PERCENT` on `kstartup` (2/2), and `none/empty=1/PERCENT`
on `nrf` (1/1).  The A/B/C and attribution columns are unchanged from #250 at
both tolerances, which is the check that the pass added nothing to the
classification.

**No one mechanism dominates**, and the two shapes behind those rows are
different:

* **The predecessor grew (10 of 17).**  `moel-2013` page 4: the drift is
  +36.66 px and the predecessor's own block is +36.70 px taller under the
  flow pass than the cache says it is.  `moel-2025` pages 1/2/3: +29.76 /
  +32.28 / +26.64 against +29.88 / +32.52 / +26.76.  The height is inside the
  predecessor, so this is #250's class-A tail seen from below, not a gap.
  What IS new is where the shortfall lives: the gap from the predecessor's
  ink bottom to the next paragraph's first line shrinks by a constant
  −5.98 / −6.02 px on those pages, which is #250's −6.14 px residual located
  — it is the predecessor's LAST line's advance, not the inter-paragraph gap
  and not the paragraph's dominant pitch.
* **The predecessor drew nothing (7 of 17).**  Every one is an empty
  paragraph.  On six of them the flow seat height equals the sum of the
  cached `hp:lineseg` advances exactly (`height_delta_hwp` 0), so the empty
  paragraph's own height is right and the cause is above it.

### `nrf`: the one measured page-fit difference

The seventh is `nrf` page 2, and it is the corpus's only instance of the
shape the holdout shows.  The drift is +102.40 px on all 29 class-B
paragraphs — exactly 5120 HWPUNIT, two whole 2560-HWPUNIT body pitches — with
nothing re-broken above it.  The predecessor is paragraph 37, empty, and:

    usable_height (body box)         71436 HWPUNIT
    cached vertpos of paragraph 36   71630   <- past the body bottom
    cached vertpos of paragraph 37   71630   <- the SAME seat
    flow seat of paragraph 36        page 2, top 0
    flow seat of paragraph 37        page 2, top 2560
    paragraph 38, cached             page 2, vertpos 0
    paragraph 38, computed           page 2, top 5120

So the authoring engine seated two trailing empty paragraphs 194 HWPUNIT past
the bottom of its own body box, and gave them the same `vertpos` rather than
advancing — it neither paginated them nor made room for them.  The flow pass
does paginate them, because its page-fit test measures a block by its
`advance` and knows nothing about whether the block puts ink down, and the
first paragraph of page 2 therefore starts two empty-paragraph heights lower.

The rule that reading suggests is that an INKLESS paragraph does not force a
page: it draws nothing, so nothing crosses the margin, and Hancom lets it
hang.  That is consistent with the schema (`hp:lineseg` is cached geometry,
not a fit assertion) and with `_row_extent`'s existing measured concession
that a line may cross the bottom margin by its descender
(`docs/research/line-fit-rule.md`).

### Nothing was changed

`own_render.py` is untouched.  Three reasons, in order:

1. **The mechanism does not dominate.**  Ten of seventeen drifting pages
   start under an ordinary drawn paragraph whose own block grew, which #250
   already attributes to class A.  A page-fit change would not move them.
2. **The measured basis is one page boundary on one form.**  `nrf`'s two
   paragraphs are the only corpus instance where the cached seat is past the
   body box at all: the report's `cache_seat_past_page_bottom` is `false` on
   the other six undrawn predecessors.  Writing an inkless-paragraph rule off
   one boundary is exactly the corpus-as-training-set overfit the empty-run
   slice's "Not proven" already warns about, and it would be tuned on the
   form whose IoU it would move.
3. **Pagination is the highest-blast-radius knob in the flow pass.**  A block
   that stops forcing a page changes page counts, and `kstartup`'s extra page
   currently scores +0.37000 IoU *better* than the cache.

Corpus scoreboard, 144 dpi, both policies pinned, before and after this
slice: `cache` `text_line_iou_mean` 0.645754, `ssim_mean` 0.830919,
`ssim_inked_mean` 0.276175, `text_line_pair_rate_mean` 0.836210; `computed`
0.633897 / 0.824293 / 0.277430 / 0.847831.  All ten forms' scoreboard JSON is
byte-identical across the change under both policies (label field aside) and
every verdict is unchanged.  `render_check` on `render-check-01` is unchanged:
9/9 pages exact, 6 · 37 · 6 · 2 at 96 dpi and 14 · 31 · 4 · 2 at 144.

### Not proven

- **`nrf` is one boundary.**  Two paragraphs, one page, one form.  The
  inkless-paragraph reading explains it and nothing else on the corpus
  contradicts it, but nothing else on the corpus tests it either.
- **The rule was not read out of a published spec.**  KS X 6101 and the OWPML
  schema describe `hp:lineseg` as cached geometry and say nothing about when
  the authoring engine will refuse to paginate; "an inkless paragraph does
  not force a page" is inferred from `nrf`'s cache, not quoted.
- **The −6 px gap shortfall is located, not explained.**  It is the
  predecessor's last line's advance falling short of the paragraph's dominant
  pitch, which is what #250 guessed; why that line's advance is smaller is
  still unmeasured, and reading it needs the added line's own
  `vertsize + spacing` rather than a `y0` step.
- **Enclosure is an inference.**  A paragraph placed on a page because its
  neighbours are both on it has no direct evidence of its own; six of the
  seven undrawn predecessors are placed that way or by a flow seat, and a
  wrong placement would name the wrong predecessor.
- **The two bottoms did not separate on the corpus.**  No page was found
  where the gap from the `advance` bottom agrees across the policies while
  the gap from the `ink` bottom does not, so the question the two readings
  were added to answer is still open.
- **The holdout is not in these numbers.**  The private report-class document
  was not opened.  `--corpus --no-text` is what the operator runs on it; the
  predecessor section carries paragraph addresses, HWPUNIT measurements and
  declared style values, and no document text under any flag.
