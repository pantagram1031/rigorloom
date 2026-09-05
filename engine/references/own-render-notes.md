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
| PERCENT: `vertsize + spacing == round(textheight × value/100)` | ~~every PERCENT paragraph~~ **2146 / 3214 — this row was wrong** |

The fourth row stood for four slices and it does not hold. Re-measured line
by line it is exact on 2146 of the 3214 cached lines and off by 1 or 2
HWPUNIT on the other 1068, which is the residual #247 and #261 both left
open. The relation that does hold on all 3214 is *The PERCENT leading sits on
a 4 HWPUNIT grid* at the end of this file: it is the **leading**, not the
total advance, that Hancom rounds, and it rounds it onto a 4 HWPUNIT grid,
halves away from zero.

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


## The first seat difference, and which term carries it — measured, 2026-09-05

#252 could see that the drift starts under an inkless paragraph and could not
see any further: a paragraph that draws no line box is invisible to a
line-box pairing, so a whole run of them is one opaque step and the report
could only say "the divergence began above here".  The question this slice
was sent to answer is the obvious next one — at the first paragraph boundary
where the two policies disagree, WHICH height or gap is added or removed —
and answering it needs a channel that does not go through ink.

### The instrument

`layout_divergence.py` now has a seat pass.  For every top-level `hp:p` of
every section, in document order, it records the paragraph's SEAT under both
policies:

* under `cache`, the page `_render_paragraphs` drew it on and the
  `hp:lineseg@vertpos` of its first cached line — the authoring engine's own
  statement of where the paragraph starts, measured from the body top;
* under `computed`, the page and `top` of its flow-pass placement, the same
  quantity in the same units;

with each side's advance (cache: the sum of the paragraph's lineseg
`vertsize + spacing`; computed: the flow record's `height`), its drawn line
count, and everything that could explain a difference: every empty `hp:run`
with its `hh:charPr@height`, every object with extent, out-margins,
`treatAsChar`, `flowWithText` and `vertRelTo`, the paragraph's own
`hh:paraPr` — line spacing, `hh:margin/prev` and `/next`, both spellings of
page-break-before, `keepWithNext`, `keepLines`, `widowOrphan` — and its
section, `columnBreak` and column count.  **An inkless paragraph has a seat
under both policies**, which is the whole point: the pass sees the population
the classification cannot.

Per page the first paragraph whose seat differs is reported with the one
before it and the delta split three ways:

    Δtop(this) = Δ(prev seat top) + Δ(prev advance) + Δ(gap)

where `gap` is `this.top − (prev.top + prev.advance)` under each policy.  The
identity is exact by construction and `identity_ok` re-checks it rather than
asserting it; what it buys is WHERE the height entered.  `d_prev_top` means
the divergence is older than this pair, `d_prev_advance` means the block
above is measured differently, `d_gap` means the space BETWEEN the two
paragraphs is different — the inter-paragraph channel and nothing else.  A
pair the terms cannot be computed for is named (`page_top`, `page_move`,
`no_seat`) instead of guessed at.  `carrier` is the largest term over
`--seat-tol` and `single_term` says whether the other two are both under it.

    python engine/scripts/layout_divergence.py --corpus --out DIR --no-text
    python engine/scripts/layout_divergence.py --corpus --out DIR --no-text \
        --seat-tol 2.5

The tolerance is in HWPUNIT, not pixels: seats are integers on both sides and
the pass never leaves the units the layout was made in.  The default 0.5
means "any difference at all".

### What the corpus says, before anything was changed

144 dpi, `--no-text`, ten forms, top-level paragraphs:

| form | seated both | seats differ | pages with a divergence |
| --- | --- | --- | --- |
| `admrul` | 15 | 0 | 0 |
| `gianmun-1ho` | 3 | 0 | 0 |
| `gianmun-2ho` | 3 | 0 | 0 |
| `jeongbo` | 1 | 0 | 0 |
| `jumin` | 3 | 0 | 0 |
| `kstartup` | 165 | 139 | 20 |
| `moel-2013` | 154 | 109 | 4 |
| `moel-2025` | 187 | 141 | 6 |
| `nrf` | 53 | 10 | 2 |
| `saeopja` | 6 | 0 | 0 |

`saeopja`'s 6 is not a typo: its whole body is inside one table, and a cell
paragraph has a `vertpos` measured from its own cell and no flow seat at all,
so the pass refuses to put it beside a body-box seat.

Over the 32 divergent pages the carrier is `page_move` 16, `d_prev_advance`
11, `page_top` 4 and `d_gap` **1**.  Per form, the FIRST seat difference in
the document:

| form | page | paragraph | Δtop HWPUNIT | carrier | at `--seat-tol 2.5` |
| --- | --- | --- | --- | --- | --- |
| `kstartup` | 1 | 1 | −2 | `d_prev_advance` | para 14, −4, `none` |
| `moel-2013` | 1 | 3 | +2 | `d_prev_advance` | para 4, +3, `none` |
| `moel-2025` | 1 | 2 | −1 | `d_prev_advance` | para 3, −3, `none` |
| `nrf` | 1 | 33 | **−276** | **`d_gap`** | unchanged |

Three of the four are the ±2 HWPUNIT `PERCENT` spacing residual #247 already
named, accumulating: raise the tolerance past it and the delta is a few
HWPUNIT spread across all three terms with no carrier at all.  `nrf` is the
one substantive first seat difference on the corpus, it survives any
tolerance, and it is the form #252 singled out.

### `nrf`: the gap below an anchored table is its outer margin

Paragraph 0 is empty and anchors a table: `hh:sz@height` 63674, `hp:pos`
`treatAsChar="0" vertRelTo="PARA" vertOffset="0"`, `textWrap="TOP_AND_BOTTOM"`,
`hp:outMargin` 138 on all four sides.  The pair reads:

    paragraph 0    cache  top 0      advance  2560   (its own empty line)
                   flow   top 0      advance 63674   (the table's box)
    paragraph 33   cache  top 63950
                   flow   top 63674

    d_prev_top        0
    d_prev_advance   +61114
    d_gap            -61390   (gap 61390 -> 0)
    -------------------------
    Δtop              -276

and 276 is 138 + 138.  The cache seats the next paragraph at
`0 + 138 + 63674 + 138`.  `kstartup` says it again with different numbers:
paragraph 148 anchors 69352 with `outMargin=140`, and its successor is cached
at 69632 = `0 + 140 + 69352 + 140`.  Both exact; those two are every corpus
anchored object that reserves flow room.

**The rule.**  `hp:outMargin` is the gap OUTSIDE the object's own box
(schema: `DevDoc/OWPML SCHEMA/ParaList XML schema.xml`, on every
`ShapeObject`), so the declared `hp:pos` offset names the top of a SLOT that
is `top + height + bottom` tall and the box sits `top` inside it.  This
renderer already reads it exactly that way in three places: `_object_origin`
draws the box `outMargin@top` down from the slot, `_object_extent` widens an
inline slot by `left + right`, and `_line_metrics` grows an INLINE object's
line by `top + bottom` (measured on the corpus's 79 object lines,
`docs/research/object-line-box.md`).  `_anchor_extent` was the one place that
dropped it, reserving `vertOffset + hh:sz@height` and nothing more.  It now
reserves `vertOffset + top + height + bottom`, which is the anchored sibling
of the rule the other three already state.

### The synthetic side, and what it is not

`tests/corpus/render-check/measure_seat_probe.py` asks the same question of a
document nobody but this repo has touched: the same six-paragraph page
eighteen times — a text paragraph, an empty one, an empty one holding an
inline picture, an empty one holding an inline table, an empty one holding an
ANCHORED table, and a read-out paragraph — with exactly one declared
attribute changed each time.

**Path A does not exist for it and path C is NOT RUN.**  A package this repo
writes carries no `hp:lineseg`, so `--layout-policy cache` has nothing to read;
and no Hancom PDF was exported, so nothing below is evidence about what
Hancom would do.  The render is compared against the ANALYTIC seat instead —
the height the paragraph's own `hh:paraPr` and `hh:charPr` say it should
have, computed in the probe from the values it authored the document with.

How far the read-out paragraph moves against the unchanged baseline, HWPUNIT:

| attribute changed | before | after | analytic |
| --- | --- | --- | --- |
| empty paragraph, line spacing 130 / 200 / FIXED 2400 | 0 / 0 / 0 | 0 / 0 / 0 | −300 / +400 / +800 |
| empty paragraph, `charPr` 8 / 14 / 24 pt | 0 / 0 / 0 | 0 / 0 / 0 | −320 / +640 / +2240 |
| empty paragraph, `margin/prev`+`/next` 600+200 | +800 | +800 | +800 |
| inline picture, `outMargin` 141 / 283 | +282 / +566 | +282 / +566 | +282 / +566 |
| inline table, `outMargin` 141 / 283 | +282 / +566 | +282 / +566 | +282 / +566 |
| inline table, `charPr` 24 pt | +840 | +840 | +840 |
| inline table, line spacing 200 | +400 | +400 | +400 |
| **anchored table, `outMargin` 141 / 283** | **0 / 0** | **+282 / +566** | **+282 / +566** |
| inline table → anchored | −600 | −600 | −600 |
| anchored table → inline | +600 | +600 | +600 |

The anchored row is the defect, reproduced on a public document: give an
inline object an outer margin and everything below it moves; give the same
margin to the same object anchored and, before this change, nothing moved.
After it the two agree, which is what the declarations predict.

### The other thing the probe found, and it is NOT fixed here

Every case sits a constant 1600 HWPUNIT above its analytic seat, and the
reason is the empty paragraph.  `_flow_lines` takes the computed branch only
`if mode == LINE_LAYOUT_COMPUTED and para.chars`, and a paragraph with no
characters falls through to its cached linesegs — of which a Rigorloom-written
package has none — so it gets `rows = []` and a block height of **0**.  The
three rows above where line spacing and `charPr` height move the read-out by
nothing are the same fact seen from the side: an empty paragraph with no
cache has no height for those attributes to scale.

That is a real defect and it is deliberately left alone.  It is measured
against this probe's own arithmetic and nothing else: no corpus form
exercises it, because every corpus form's empty paragraph HAS a cached
lineseg to fall back on, and no Hancom render was made to say what the height
should be.  Fixing it means inventing a line for a paragraph that has none,
on a path that only Rigorloom-written documents take — which is the whole
population of edited documents — and it deserves its own measurement with a
reference export, not a rider on this one.

### After

Corpus scoreboard, 144 dpi, both policies pinned, before and after:

| channel | `cache` | `computed` |
| --- | --- | --- |
| `text_line_iou_mean` | 0.645754 | 0.633897 |
| `ssim_mean` | 0.830919 | 0.824293 |
| `ssim_inked_mean` | 0.276175 | 0.277430 |
| `text_line_pair_rate_mean` | 0.836210 | 0.847831 |

**Byte-identical**, all ten forms, under BOTH policies — not just the cache
one.  Page counts are unchanged (`kstartup` 21/22 under cache and 22/22 under
computed, every other form exact), every verdict is unchanged, and
`render_check` on `render-check-01` is unchanged: 6 · 37 · 6 · 2 at 96 dpi and
14 · 31 · 4 · 2 at 144.

What moved is the seat channel, and only on `nrf`: seats differing 10 → 7,
and the −276 page-1 divergence is gone.  The corpus carrier tally goes from
`page_move` 16 / `d_prev_advance` 11 / `page_top` 4 / `d_gap` 1 to `page_move`
17 / `d_prev_advance` 11 / `page_top` 4, i.e. `nrf`'s page 1 stops having a
first seat difference at all and its remaining one is the trailing-empty-
paragraph pagination #252 already declined to touch.  `kstartup` paragraph
148's flow height is now 69632 against the cache's own 69632.

The change buys agreement in a channel the raster cannot see, and costs
nothing in the one it can.  The paragraphs whose seats moved put no ink down
and no page repaginated, which is why the scoreboard does not move; a
document whose anchored object is followed by TEXT rather than by five empty
paragraphs would have moved ink, and none of the ten forms is that document.

### Not proven

- **The rule rests on two anchored objects.**  `nrf` paragraph 0 and
  `kstartup` paragraph 148 are every corpus anchor that reserves flow room,
  and both are `TOP_AND_BOTTOM` tables at `vertOffset=0` with
  `vertRelTo=PARA`.  A `SQUARE`/`TIGHT`/`THROUGH` wrap, a non-zero offset and
  a `PAGE`-relative anchor all take the same code path and none of them is
  measured; the tests pin the arithmetic, not the engine's agreement with it.
- **The synthetic side has no reference.**  Path C was not run.  The probe
  says the flow pass now obeys the document's own declarations; it does not
  say Hancom obeys them the same way.
- **It moved no ink, so no raster channel confirms it.**  The whole evidence
  is the cached seat agreeing to the HWPUNIT on two forms plus the schema
  reading.  A form where the correction changes what a reader sees does not
  exist in this corpus.
- **The empty paragraph's zero height is unfixed and unpriced.**  It is worth
  1600 HWPUNIT per empty paragraph on the probe's 10 pt / 160% baseline, and
  what it is worth on a real Rigorloom-written report is not measured.
- **The seat pass is top-level only.**  A paragraph inside a table cell has
  no flow seat and a cell-relative `vertpos`, so `saeopja` — whose body is
  one table — contributes 6 seats out of 700-odd paragraphs.  Whatever
  happens inside a cell, this channel cannot see it.
- **`page_move` is 16 of 32 carriers and none of them is decomposed.**  Where
  the two policies put a paragraph on different pages the three terms are not
  computable, and that is most of `kstartup`.
- **The holdout is not in these numbers.**  The private report-class document
  was not opened.  `--corpus --no-text` is what the operator runs on it; the
  seat section carries paragraph addresses, HWPUNIT measurements and declared
  style values, and no document text under any flag.

## What the page-bottom fit test clears — measured, 2026-09-05

Worker: Opus; orchestrator: Fable.

The flow pass decides whether one more line still fits above the bottom of
the body box by comparing `vertpos + row["extent"]` against `usable_height`,
and `_row_extent` makes that extent `baseline` for a line of text (#252,
`docs/research/line-fit-rule.md`).  That choice was reasoned from three
overfull corpus pages, none of which turned out to be a normal text line.
This section measures the question directly, from both sides, and the answer
is that **the corpus cannot decide it and one private measurement rules the
current term out** — so nothing in the renderer changed here.

### The instrument

`engine/scripts/page_fit_probe.py` reads the cached seats and never renders
either path.  It re-implements `paginate`'s restart rule while keeping the
lineseg RANGE each page holds (which `paginate` itself throws away into
`Paragraph.page_run`), and at every cached page break it measures both sides
against seven candidate offsets added to `vertpos` — `top`,
`vertsize - spacing`, `vertsize // 2`, `baseline`, `textheight`, `vertsize`,
`vertsize + spacing`:

- **kept**: how far the DEEPEST line the page kept overhangs `usable_height`
  under that candidate.  A kept overhang refutes the candidate outright —
  Hancom kept a line the candidate refuses, and no other rule can make it do
  that.
- **rejected**: how far the first line the cache moved to the next page WOULD
  have overhung had it stayed, seated at the previous line's advance plus the
  `margin_next + margin_prev` gap the flow pass opens between two paragraphs.
  Leaving that gap out understates the would-be top by up to a whole line and
  invents refutations.

A rejected line only refutes a candidate if no OTHER rule already explains
the break, so four classes are excluded from that side: a forced break
(`hp:p@pageBreak`, `pageBreakBefore`, `columnBreak`), a `keepWithNext` push,
a whole inline table moving (a table that does not fit moves whole —
`docs/research/table-page-break-rule.md`), and a page holding an ANCHORED
object, whose room no `hp:lineseg` records.  That last one is not a
technicality: `kstartup`'s cached page 17 holds two short lines and an
anchored table, and read from linesegs alone it looks like a page that broke
with 63 000 HWPUNIT of room left; `nrf`'s page 0 and `kstartup`'s page 5 go
the same way.  Two classes are excluded from the kept
side as well — a line taller than the whole body box (placed by
`_place_block`'s `cursor > 0` guard, which never runs the fit test) and a
line with no characters (it draws no ink).

    python engine/scripts/page_fit_probe.py --corpus

`usable_height` is read per section from that section's own `hp:pagePr`, not
assumed: the ten forms run from 69 788 to 75 686, and none of them is 70 864.
No corpus form declares a footnote, an endnote or a footer, and one
(`jeongbo`) declares a header, so the header/footer MARGINS are the only
furniture term in play and `page_geometry`'s formula already carries them.

### What the corpus says

41 cached page breaks over the ten forms.  **Not one of them is inside a
paragraph** — no corpus paragraph has more than one page run, which
`Paragraph.page_runs`' docstring already predicted and this now measures.
Every corpus break is between two blocks.  27 carry kept-side evidence (12
pages end on an empty line, 2 on a line taller than the page); 5 carry
rejected-side evidence.

| candidate | kept max | rejected min | k! | r! | fits |
| --- | ---: | ---: | ---: | ---: | --- |
| `top` | −1368 | **−445** | 0 | 4 | no |
| `vertsize - spacing` | −720 | +395 | 0 | 0 | **yes** |
| `vertsize // 2` | −868 | +255 | 0 | 0 | **yes** |
| `baseline` | −518 | +731 | 0 | 0 | **yes** |
| `textheight` | −296 | +911 | 0 | 0 | **yes** |
| `vertsize` | −296 | +911 | 0 | 0 | **yes** |
| `vertsize + spacing` | **+1521** | +1427 | 6 | 0 | no |

HWPUNIT, against `usable_height`.  `k!` counts kept lines the candidate would
have refused and `r!` moved lines it would have kept.

Per form, the kept side is where the numbers live: `kstartup` 19 breaks,
`moel-2013` 6, `moel-2025` 6, `saeopja` 5, `nrf` 3, `jumin` 2, and the four
one-page forms contribute none.  The tightest kept line anywhere is
`kstartup` page 7, whose deepest box ends 296 HWPUNIT above the boundary, and
`saeopja` page 4 at 299.  All five rejected-side events are `kstartup`,
pages 1, 12, 13, 14 and 16.

Two things follow, and they are the whole public result:

1. **The corpus refutes `top`.**  Four `kstartup` breaks move a line whose
   TOP would have been 116–445 HWPUNIT inside the page, with no page break,
   no `keepWithNext`, no `keepLines`, no `widowOrphan`, no inline table and
   no anchored object on the page to explain it.  Something below the top
   has to be inside the box for the rule to hold.
2. **The corpus refutes `vertsize + spacing`.**  Six pages keep a line whose
   box plus trailing leading crosses the margin — the trailing spacing of the
   last line on a page is not required to fit, which is the same relation
   `extent_hwp` already excludes for a different reason.

Between those two ends the corpus is silent, and silent for a structural
reason rather than for want of pages: **the largest kept overhang under the
STRICTEST surviving candidate is −296, so no corpus page keeps a line whose
box crosses the margin at all.**  There is no corpus case in the ambiguous
band, and five candidates — including the `baseline` the renderer already
implements — fit every corpus case equally.

### The synthetic side manufactures the band

`tests/corpus/render-check/measure_page_fit_probe.py` builds the case the
corpus lacks.  Forty-five identical single-line paragraphs (`charPr` 1000,
`PERCENT` 160, so `vertsize` 1000, `spacing` 600, `baseline` 850, advance
1600) fill the body, which puts line 40 at exactly 64 000 from the body top;
the section's `hc:bottom` page margin is then swept so `usable_height`
crosses that line's box.  One knob, six settings.

| slack below line 40 | flow pass seats it | candidates that agree |
| ---: | --- | --- |
| 1364 | page 1 | all but `vertsize + spacing` |
| 900 | page 1 | `top` … `baseline` |
| **764** | page 2 | `baseline` and stricter |
| **464** | page 2 | `vertsize // 2` and stricter |
| 164 | page 2 | `vertsize - spacing` and stricter |
| −36 | page 2 | all |

The flow pass agrees with exactly one candidate across all six: `baseline`.
That is the confirmation the probe is for — the mechanism under test really
is `_row_extent`, and the two middle rows are precisely where a change to it
would be visible.  **Path A does not exist** (a Rigorloom-written package
carries no `hp:lineseg`) and **path C was NOT RUN** — no Hancom reference was
exported, so none of this says what Hancom does with the same document.

### The one case that decides it is private, and it rules out `baseline`

The development-validation document the operator ran — not opened here, and
the numbers below are the only thing carried across — has a page-1 paragraph
at 61 430 with `vertsize` 1000, `spacing` 800, pitch 1800, against
`usable_height` 70 864.  The cache keeps SIX lines, the sixth at 70 430;
Rigorloom keeps five and everything after runs +1800 late, which is the
`page_top` first-seat divergence #255 reported on every page.

Read as a constraint, that one page says the measure for a 1000/800 line is
at most `70864 − 70430 = 434`.  Against the seven candidates:

| candidate | offset for a 1000/800 line | ≤ 434? |
| --- | ---: | --- |
| `top` | 0 | yes — but the corpus refutes it |
| `vertsize - spacing` | 200 | **yes** |
| `vertsize // 2` | 500 | no |
| `baseline` | 850 | no — this is what ships |
| `textheight` / `vertsize` | 1000 | no |
| `vertsize + spacing` | 1800 | no — the corpus refutes it too |

**Exactly one of the seven survives both sides: `vertsize - spacing`.**  Read
plainly, it says a line may hang past the bottom margin by as much as its own
trailing leading — the leading below the last line on a page is not drawn, so
it is available to be spent.  Checked back against every corpus event it
holds: kept max −720, rejected min +395.

### Why nothing was changed

The bracket is real but it is not tight, and the half of it that moves the
renderer is private.

- Between `vertsize - spacing` and `baseline` the corpus has **no** case.
  Adopting the former is a relaxation with no public evidence that the
  latter is wrong; the entire upper bound comes from one page of one document
  that is not in this repository and cannot be re-measured by a reader.
- `vertsize - spacing` is not the only expression inside the surviving band.
  `baseline - spacing` (50 for the private line, 698 and 504 for the two
  binding `kstartup` lines) fits every case as well, and so does any fixed
  fraction of `vertsize` between about 0.32 and 0.43.  The measurement picks
  a band, not a formula, and choosing `vertsize - spacing` out of that band
  is a reading rather than a result.
- No public basis settles it.  KS X 6101 and the OWPML lineseg semantics
  already measured in this file name the fields — `LineHeight`,
  `TextPartHeight`, the baseline distance, `LineSpacing` — and say nothing
  about which of them a pagination test compares.

So this lands as a **costed proposal**, and the cost is one line.  Change
`_row_extent`'s text-line return from `baseline` to
`max(0, vertsize - spacing)` (the `spacing` is already on the lineseg and on
the computed line dict, so `_flow_lines` passes it at both call sites) and
move `test_the_flow_pass_compares_baseline_for_a_text_line` in
`engine/tests/test_page_fit_probe.py` to the new term.  On this corpus the
change is a no-op by construction — every kept line clears both terms and
every moved line clears neither — so `render_scoreboard.py --corpus` cannot
grade it.  What would grade it is a run against the private holdout, and the
prediction to hold the change to is specific: the page_top +1800 cascade
closes on every page whose last line sits within `spacing` of the margin.

### The state these numbers were taken against

`render_scoreboard.py --corpus --dpi 144`, this branch, no renderer change,
so before and after are the same run:

| policy | IoU | ssim | ssim_inked | pair | page-count exact |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cache` | 0.645754 | 0.830919 | 0.276175 | 0.836210 | 9/10 |
| `computed` | 0.633897 | 0.824293 | 0.277430 | 0.847831 | 10/10 |

The one cache-mode page-count miss is `kstartup` at 21 against 22, which is
the overflowing anchored table E2.7 already names and not this question.

### Not proven

- **The corpus contains no intra-paragraph page break at all.**  Every number
  above comes from block boundaries.  The fit test's per-row loop in
  `_place_block` is the same code either way, but a paragraph splitting
  mid-flow is the shape the private holdout has and this corpus does not, and
  nothing here measures it.
- **The rejected side is five events on two forms.**  Four of them are
  `kstartup` body lines and they carry the whole refutation of `top`.  If any
  one of the four turns out to have a cause the exclusion list does not name,
  `top` comes back into the band and the surviving candidate changes.
- **The private page is one page.**  It bounds the measure at 434 for a
  1000/800 line and says nothing about how that bound scales.  A second line
  geometry from the same document would separate `vertsize - spacing` from
  `baseline - spacing` and from the fractional readings; one page cannot.
- **Path C was not run anywhere in this section.**  Neither the corpus
  reference PDFs' ink positions nor a fresh Hancom export was consulted.  The
  kept/rejected sides are read off Hancom's own cached seats, which is
  evidence about what its layout engine decided, not about where it drew.
- **`vertsize == textheight` on every corpus lineseg**, so the two columns
  are identical above and the corpus cannot tell them apart.  A document that
  separates them would.
- **The synthetic probe grades the renderer, not Hancom.**  Its six rows say
  the flow pass implements `baseline`; they are silent on whether it should.

## Whether `usable_height` itself is short — measured, 2026-09-05

Worker: Opus; orchestrator: Fable.

E2.7 above left the fit test bracketed but undecided, and one private
measurement made the ambiguity concrete: on the development-validation
document Hancom KEPT a line whose box, under `vertsize`, overhangs the
derived body bottom by **+566** and REJECTED one that would have overhung by
**+626**. Two readings fit that pair. Either the fit allows about
0.6 × `vertsize`, which no part of OWPML suggests, or **our `usable_height`
is short by roughly 600 HWPUNIT** for that geometry, in which case `vertsize`
has its boundary exactly at 0. This section asks the second question of the
public corpus, and the answer is that the derivation is right: the tightest
measurement in the corpus pins the body bottom to **11 HWPUNIT**, and an
offset of 600 would miss it by fifty times that.

### What the derivation is

`OwnRenderer.page_geometry` reads `hp:pagePr` and its `hh:margin` child and
computes

    body_top      = top + header
    usable_height = height - top - bottom - header - footer

`gutter` is reported and never folded in — `gutterType` decides which side it
lands on and every corpus form declares `gutter="0"` with
`gutterType="LEFT_ONLY"`, so nothing on this corpus can grade it.

### The corpus, form by form

Every form is A4 portrait-declared (`width="59528"`, `landscape="WIDELY"`,
`gutterType="LEFT_ONLY"`, `gutter="0"`), one section each, so only the
varying terms are worth a column. "deepest cached" is
`max(vertpos + vertsize)` over the section's top-level `hp:lineseg`s.

| form | height | top | bottom | header | footer | body_top | usable | deepest cached | vs usable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `admrul` | 84189 | 5669 | 2834 | 0 | 0 | 5669 | 75686 | 67920 | −7766 |
| `gianmun-1ho` | 84188 | 5669 | 2835 | 0 | 0 | 5669 | 75684 | 74006 | −1678 |
| `gianmun-2ho` | 84188 | 5669 | 2835 | 0 | 0 | 5669 | 75684 | 73762 | −1922 |
| `jeongbo` | 84188 | 5668 | 2834 | 0 | 0 | 5668 | 75686 | 75655 | −31 |
| `jumin` | 84188 | 5669 | 2834 | 0 | 0 | 5669 | 75685 | 74234 | −1451 |
| `kstartup` | 84188 | 5668 | 4252 | 332 | 2936 | 6000 | 71000 | 70918 | −82 |
| `moel-2013` | 84188 | 3600 | 3600 | 3600 | 3600 | 7200 | 69788 | 74535 | **+4747** |
| `moel-2025` | 84186 | 2834 | 2834 | 2834 | 2834 | 5668 | 72850 | 70215 | −2635 |
| `nrf` | 84188 | 5668 | 4252 | 1416 | 1416 | 7084 | 71436 | 73230 | **+1794** |
| `saeopja` | 84188 | 5668 | 2834 | 0 | 0 | 5668 | 75686 | 76989 | **+1303** |

Three forms look like counter-evidence and none of them is:

* **`nrf` +1794** is paragraphs 4 and 5, two trailing EMPTY paragraphs sharing
  one `vertpos` of 71630 — the seats E2.6 already wrote up. They carry no
  character, so nothing crosses anything.
* **`moel-2013` +4747** is paragraph 152, a single `hp:tbl` with
  `pageBreak="NONE"` and `rowCnt="20"`, and its neighbour 153 (`NONE`,
  `rowCnt="16"`) is +3846. A table that may not split is kept whole, so it
  overflows rather than paginating.
* **`saeopja` +1303** is paragraph 1, a `pageBreak="CELL"` table whose
  `hp:lineseg@vertsize` is 76989. That number is the whole table's height, and
  the drawn page tells a different story — see below.

So **no corpus page seats a line of text whose box crosses the derived body
bottom**, and the probe's existing `taller_than_page` and `empty`
classifications are what keep the three above out of the kept-side evidence.

### The offset scan

`page_fit_probe.py --offset-scan` (also `--scan-range LO:HI:STEP` and
`--band LO:HI`) adds a candidate offset to `usable_height` and recomputes
k!/r! for `vertsize` and `baseline`. Because every overhang is linear in
`usable_height`, the scan is exact: an overhang at offset δ is the offset-0
overhang minus δ, and the consistent band is closed-open,
`[max(kept), min(rejected))`. Only the fit boundary moves; the cached page
grouping and the taller-than-a-page guard stay at the renderer's own
derivation, so that a large offset cannot invent kept evidence out of a
multi-page table's whole-table `vertsize`.

| form | `vertsize` band | `baseline` band |
| --- | --- | --- |
| `admrul`, `gianmun-1ho`, `gianmun-2ho`, `jeongbo`, `nrf` | (no evidence) | (no evidence) |
| `jumin` | [−1451, ∞) | [−12586, ∞) |
| `kstartup` | **[−296, 911)** | **[−518, 731)** |
| `moel-2013` | [−396, ∞) | [−591, ∞) |
| `moel-2025` | [−2635, ∞) | [−2830, ∞) |
| `saeopja` | [−299, ∞) | [−11607, ∞) |
| **joint** | **[−296, 911)** | **[−518, 731)** |

`kstartup` alone bounds the offset from above, on the five rejected-side
events it contributes. Four of those are the `top` refuters, printed
explicitly by the scan: pages 1/12/13/14, paragraphs 40/71/76/80, whose
would-be tops sat 445 / 116 / 289 / 186 HWPUNIT INSIDE a `usable_height` of
71000 and were moved anyway. Their `vertsize` overhangs — 955, 1084, 911,
1014 — are the ceiling: an offset of 911 or more would have kept paragraph
76's line.

The private band [566, 626) is inside both joint bands, so **the corpus
cannot refute the short-derivation reading from the cached seats alone**.
That is as far as path A goes.

### What the drawn page says

`page_fit_probe.py --reference-ink` closes the gap E2.7 named as open
("neither the corpus reference PDFs' ink positions nor a fresh Hancom export
was consulted"). It reads each reference PDF's deepest vector extent and
deepest glyph box and reports both against the derived body box. The two are
kept apart on purpose: a Korean government form prints its paper-spec line in
the bottom margin from a page-anchored object, which is text far below any
body box and evidence about nothing, while a table's ruling has no such
escape.

The result that decides the question is one row:

    saeopja page 1   body [5668, 81354]   ruling [7444, 81343]   -11

`saeopja` is six pages, each one full-page table, and page 1 holds the
76989-tall `pageBreak="CELL"` table from the table above. Hancom ruled it to
**11 HWPUNIT above the derived body bottom** — 0.1 pt on a 297 mm page. A
+600 offset moves that bottom to 81954 and leaves a table that was plainly
sized to the room 611 HWPUNIT short of it. The seat's 76989 is the whole
table's height including what continues past the page; the ruling is where
the ink stopped.

The rest of the corpus agrees from both sides:

* **Top.** `vector_top - body_top` is never below −82 (`moel-2025` −82,
  `kstartup` −7, `nrf` +68, `admrul` +3485 on a form that starts low). If the
  header band were not part of the top offset, `moel-2013` would start 3600
  higher than it does and `kstartup` 332. `body_top = top + header` is
  measured, not assumed.
* **Bottom, with a footer margin and no footer.** `kstartup` declares
  `footer="2936"` and contains no `hp:footer`. Its deepest ruling is
  **−152** from the derived bottom on page 2. Had the footer band not been
  reserved the body would run 2936 further and Hancom would have broken that
  page 3088 early with a 1084-tall line waiting. The footer margin is
  reserved whether or not a footer exists.
* **The only rulings below the derived bottom** are `moel-2013` pages 5 and 6,
  +2353 and +3612 — the two `pageBreak="NONE"` tables — and page 6's ruling
  also runs +12 past `height - bottom`, the paper's own bottom margin, which
  no margin-derived body box can contain. They are the unsplittable-table
  overflow, not a taller body.

### The spec reading

KS X 6101 / OWPML gives `hp:pagePr` a `hh:margin` child carrying `left`,
`right`, `top`, `bottom`, `header`, `footer` and `gutter`, and Hancom's own
편집 용지 dialog stacks them cumulatively down the page: paper edge → `top` →
`header` → body → `footer` → `bottom`. The header and footer bands are
therefore INSIDE the top and bottom margins and outside the body, both are
subtracted, and neither is conditioned on a header or footer existing — the
band is page geometry, not content. `gutter` is added on the side
`gutterType` selects (`LEFT_ONLY`, `RIGHT_ONLY`, `LEFT_RIGHT`, `TOP_ONLY`),
so it shortens the body's width, or its height under `TOP_ONLY`. Our
derivation matches that reading on every term except `gutter`, which is
reported and unapplied and which no corpus form exercises.

Every spec-shaped rule that would produce a positive offset is refuted by the
scan against `kstartup`'s own band of [−296, 911):

| rule | offset on `kstartup` | in band |
| --- | ---: | :--- |
| the footer margin is not reserved when no `hp:footer` exists | 2936 | no |
| the footer margin is never reserved | 2936 | no |
| the body extends to the bottom margin (header and footer both freed) | 3268 | no |
| the header margin is not reserved | 332 | yes, but... |

The last one survives the scan on all ten forms and is still wrong: it keeps
`body_top = top + header` while extending the bottom by `header`, which pushes
the body 332 HWPUNIT into `kstartup`'s footer band, and the measured ink tops
above show the header band is real. It also predicts nothing near [566, 626)
unless the private document happens to declare a header margin of about 600,
which is not a value Hancom's dialog produces from any round millimetre.

### Nothing was changed

`own_render.py` is byte-identical to `origin/claude/engine-e2-page-bottom-fit`
on this branch. No single public-spec rule reconciles the corpus with
[566, 626): the rules that would produce an offset that size are refuted, and
the derivation the renderer already uses is confirmed to 11 HWPUNIT on the
tightest page the corpus has. Tuning `usable_height` to close one private
pair, against that, would be fitting the constant to the residual.

The bands are recorded instead. If the private document is re-probed, the
number to take is `--reference-ink` on its own reference PDF: the derived body
bottom against the deepest ruling on a page whose content fills it. If that
comes back near 0 as `saeopja` does, the +566/+626 pair is about the fit
measure and not about the body box, and E2.7's `vertsize - spacing` reading is
where to look next.

### The state these numbers were taken against

`render_scoreboard.py --corpus --dpi 144`, this branch, no renderer change,
so before and after are the same run:

| policy | IoU | ssim | ssim_inked | pair | page-count exact |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cache` | 0.645754 | 0.830919 | 0.276175 | 0.836210 | 9/10 |
| `computed` | 0.633897 | 0.824293 | 0.277430 | 0.847831 | 10/10 |

`render_check.py` on `render-check-01` at 144 dpi, cache path: match 14,
close 31, differs 4, unsupported 2, pages 9/9 exact.

### Not proven

- **The decisive measurement is one page.** `saeopja` page 1 is the only
  corpus page whose content is ruled to within 300 HWPUNIT of the derived
  bottom. `kstartup` page 2 at −152 is the second, and it is a text page whose
  last line need not touch the margin. Two pages carry the whole refutation of
  a +600 offset.
- **It is a table, and a table is not a line.** What page 1 pins is where
  Hancom stopped ruling a block it was fitting to the page. Whether the
  page-bottom test for a LINE clears the same boundary is E2.7's question and
  this section does not answer it.
- **The private geometry was not read.** The offset the private pair needs is
  [566, 626) for whatever `hp:pagePr` that document declares; every corpus
  band and every named rule here is computed from corpus margins. If that
  document's geometry has a term the corpus has none of — a `TOP_ONLY` gutter,
  a `hp:footNotePr` reserve, a second section — the comparison is not like for
  like.
- **`gutter` is still unapplied.** Every corpus form declares 0, so nothing
  above grades the one term of the derivation that is knowingly incomplete. A
  `TOP_ONLY` gutter would change `usable_height` and no test would notice.
- **The reference-ink mode reads extents, not layout.** It reports the deepest
  vector and the deepest glyph box per page and cannot say which object drew
  either. On `saeopja` page 1 the deepest glyph box is +1007 below the body
  bottom and is the form's paper-spec line in the margin; that attribution is
  read off the page, not asserted by the tool.

## Whether the exported PDF reproduces the saved lineseg — measured, 2026-09-05

Worker: Opus; orchestrator: Fable.

The scoreboard treats path A — the cached `hp:lineseg` seats Hancom wrote at
save time — as if it were the reference in another coordinate system. One
private measurement put that in doubt: on the development-validation document
a paragraph carries **7** cached linesegs while Hancom's own PDF, exported one
minute later by the same Hancom 13.0, draws it in **6** lines. If the cached
seats and the export are two different layout passes, then every number this
repo reads off path A is measuring the wrong thing.

They are not. On the public corpus the export reproduces the saved lineseg
**exactly**: same number of lines, same characters on each line, same page
grouping, on every paragraph the question can be asked of.

### The instrument

`engine/scripts/lineseg_vs_pdf.py <form.hwpx> <reference.pdf>`, or `--corpus`
for every converted form with a reference. `--json OUT` writes the per-line
record, `--no-text` keeps the document's text out of it.

The corpus pair IS the question: `tests/corpus/forms/converted/X.hwpx` is
Hancom's own hwp→hwpx conversion output, so it carries Hancom's save-time
seats, and `tests/corpus/forms/render/X.pdf` is Hancom's PDF export of that
same `.hwpx` — both `com_backend.py convert`, both 13.0.0.2986, per the
corpus manifest.

The two sides share no identifier, so paragraphs are located in the PDF by
their text, under a rule stated once and applied to every document. The key
deletes whitespace and soft hyphens and nothing else, because whitespace is
exactly what a line break is entitled to eat. The PDF's text lines are
concatenated in page then draw order, and a paragraph matches the contiguous
run of WHOLE lines whose concatenation equals its own key, searched forward
from a cursor that never rewinds. If nothing matches, the search is repeated
against a second concatenation with a trailing hyphen dropped from each line
— which never fires on this corpus, and is there so the rule is not silently
wrong on a document that hyphenates. A match found only before the cursor is
reported, not dropped.

Two things had to be got right before any number meant anything.

**A PyMuPDF line is not a laid-out line.** Hancom draws 배분/나눔 text, a
letter-spaced heading, or a run of space-padded fields as several
text-showing operations with wide gaps, and MuPDF's grouper cuts those into
separate `line` records at one height. Read raw, that says "the export broke
one cached line into four" — `admrul` paragraph 9 arrives as 16 records for 2
lines. So inside a run already known to be one paragraph, consecutive pieces
on one page whose vertical extents overlap by at least half the shorter are
regrouped into one line. The regrouping is confined to a matched run, so it
cannot weld two columns together, and the piece count is kept.

**`textpos` counts cells, and `Paragraph.chars` does not.** See below; it is
the finding, not a detail.

### What the corpus says

`--corpus`, this branch, nothing in the renderer touched. `cmp` is the
paragraphs the question can be asked of; `split!` is those whose line count
agrees but whose character split does not; `char%` is the share of characters
sitting in lines that hold exactly the same text on both sides; `dy` is
cached `vertpos` minus the PDF glyph-box top, both relative to `body_top`, in
HWPUNIT; `dy_res` is the median absolute residual about the form's own median
`dy`; `spread` is the median within-paragraph range of `dy`.

| form | cmp | equal | more cached | fewer cached | split! | char% | dy_med | dy_res | spread | skipped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `admrul` | 9 | 9 | 0 | 0 | 0 | 100.0 | 268 | 7 | 6 | 6 |
| `gianmun-1ho` | 0 | – | – | – | – | – | – | – | – | 3 |
| `gianmun-2ho` | 0 | – | – | – | – | – | – | – | – | 3 |
| `jeongbo` | 0 | – | – | – | – | – | – | – | – | 1 |
| `jumin` | 0 | – | – | – | – | – | – | – | – | 3 |
| `kstartup` | 67 | 67 | 0 | 0 | 0 | 100.0 | 11 | 7 | 0 | 98 |
| `moel-2013` | 134 | 134 | 0 | 0 | 0 | 100.0 | 235 | 17 | 2 | 20 |
| `moel-2025` | 172 | 172 | 0 | 0 | 0 | 100.0 | 233 | 19 | 10 | 15 |
| `nrf` | 29 | 29 | 0 | 0 | 0 | 100.0 | −89 | 21 | – | 24 |
| `saeopja` | 0 | – | – | – | – | – | – | – | – | 6 |
| **all ten** | **411** | **411** | **0** | **0** | **0** | **8566/8566 = 100.0** | | | | 179 |

411 of 411, and not one character on a different line. Skipped, by reason:
`inkless` 107, `table` 67, `object` 5 — no paragraph failed to match, and no
paragraph's `textpos` overran the cell stream.

`dy` is a per-form constant of a few hundred HWPUNIT, and that is the leading
the cached box carries above the glyph box, not drift: the residual about it
is 7–21 HWPUNIT, 0.07–0.21 pt, and within one paragraph the range is 0–10.
The sign flips on `nrf` (−89) because its declared line spacing puts the
glyph box above the box top, which is a property of that form's own character
and paragraph shapes and not of the comparison.

### Pages: the partition holds, the index does not

| form | cached page groups | PDF pages | lines on a different page index | grouping breaks |
| --- | ---: | ---: | ---: | ---: |
| `kstartup` | 20 | 22 | 49/77 | **0/76** |
| every other form | = PDF | = cached | 0 | 0 |

`kstartup` is the one form where the two sides give a line a different page
NUMBER, and the difference is a constant +2 that appears across a stretch of
table-only pages and never varies. It is not a re-pagination: **a whole
`hp:tbl` is ONE cached lineseg however many pages it takes**, so the cache
cannot say how many pages that stretch occupies and the reconstruction
(`page_fit_probe.cached_pages`) is short by two. The channel that does not
depend on the index is whether two consecutive lines share a page, and that
partition is identical on every form including `kstartup` — 0 breaks out of
76. `own_render`'s own `paginate` gives 20 for `kstartup` too, which is where
the corpus scoreboard's one failing `page_count_exact` comes from.

### The finding: `textpos` counts cells, and `Paragraph.chars` does not

The first run of this tool reported 18 paragraphs re-broken, all 18 at line 0,
17 of them by exactly one character and all 18 in the same direction. That
uniformity was the tell, and it was ours.

`hp:lineseg@textpos` indexes the paragraph's character STREAM, and an inline
control inside `<hp:t>` occupies a cell in that stream even when it draws no
glyph. `own_render.Paragraph.chars` is built from `itertext()`, which walks
straight past those elements. So slicing `chars` at a `textpos` runs one cell
late for every control before the cut. The corpus carries three such controls
inside `<hp:t>` — `hp:lineBreak` ×30, `hp:tab` ×15, `hp:fwSpace` ×8 — against
`hp:markpenBegin`/`End`, which take no cell. A `<hp:lineBreak/>` is the
common case, because a paragraph that carries one has more than one line by
construction.

`lineseg_vs_pdf.py` builds its own cell stream instead, giving each control
the whitespace character it stands for so the key deletes it, and with that
the 18 divergences go to 0.

**This is a live bug in `own_render.py` and it is NOT fixed here.** (It is
fixed in the section below, "What `hp:lineseg@textpos` counts".)
`OwnRenderer._render_cached_lines` slices `para.chars[start:end]` at exactly
those `textpos` values, so on the cache path every affected paragraph is
drawn with one character on the wrong side of a line break. Corpus-wide,
**21 of the 161 paragraphs with more than one lineseg** are mis-sliced:
`moel-2025` 17, `kstartup` 2, `admrul` 1, `jeongbo` 1. It is the same class
of defect as the `textpos_past_end` condition `unusable_cache_reason` already
documents — "an `hp:ctrl` this reader gives no character cell while the
authoring engine's `textpos` counted one" — and that docstring names
`hp:fieldBegin`/`fieldEnd` and `hp:colPr` as two more members of the family.
The brief for this slice was measurement, so the renderer is byte-identical
to `origin/claude/engine-e2-usable-height`; the fix belongs to whoever takes
the cache path next, and the number to beat is 21 of 161.

### render-check-01 cannot be asked this question

`tests/corpus/render-check/render-check-01.hwpx` was named as the cleanest
public instance of the pairing. It is not an instance at all:
`build_render_check.py` authors it through `hwpx_write.py`, and it **carries
no `hp:linesegarray` anywhere** — all 107 of its top-level paragraphs skip as
`no_lineseg`, and so do all 83 of `table-break-probe.hwpx`. Its PDF is a
Hancom export, but there is no Hancom save-time layout beside it to compare
with, which the dpi-independence section above already says in passing. The
Hancom-saved and Hancom-exported pair this repo actually holds is
`converted/` + `render/`, and that is what `--corpus` reads.

### The interpretation

**The export does not re-flow text.** On ten forms and 8566 characters of
body text, Hancom's PDF writer put every character on the line the save-time
pass had already chosen. Nothing here is consistent with the export running a
second line breaker: a different pass would show breaks in both directions
and at lines other than the first, and would not hold at 100.0% of
characters. Font metrics at export, kerning and justification are all ruled
out as sources of a re-break on this corpus, because none of them produced
one.

So **path A is a faithful stand-in for the reference in the horizontal
channel**: line count, break position, and which page a line lands on. What
it cannot stand in for is anything a lineseg does not record — the vertical
offset between a line box and the glyphs inside it is a real few hundred
HWPUNIT and varies per form, and a multi-page table has no per-page seat at
all.

**And the private 7-versus-6 remains unexplained by this.** Nothing on the
public corpus reproduces it. The measurement shifts where to look: not at the
export's line breaker, which reproduces the save, but at whether that
document's cached seats were written by the same save the PDF was exported
from — a paragraph whose sixth line sits 566 past the body bottom is a cache
that `unusable_cache_reason` and `stale_cache_reason` exist to refuse.

### Nothing was changed

`own_render.py` is byte-identical to `origin/claude/engine-e2-usable-height`.
The scoreboard state these numbers were taken against is the one E2.8
recorded and did not move: `render_scoreboard.py --corpus --dpi 144`, `cache`
IoU 0.645754 / pair 0.836210 / 9 of 10 page-count exact, `computed` IoU
0.633897 / pair 0.847831 / 10 of 10.

### Not proven

- **Five of the ten forms contribute nothing.** `gianmun-1ho`,
  `gianmun-2ho`, `jeongbo`, `jumin` and `saeopja` are whole-page table forms:
  every top-level paragraph is a table or inkless, and all their body text
  lives in cells this tool does not read. The 411 come from five forms, and
  306 of them from the two `moel` contracts, which share most of their text.
- **Table cells were never compared.** A cell paragraph carries its own
  `hp:lineseg`s and its own PDF lines, and the same question could be asked
  of them. It was not, because a cell's column comes from the table's own
  geometry and the reading order of cell text in a PDF is not document order.
  Most of this corpus's text is in cells.
- **The regrouping rule is a judgement.** Half the shorter box's height is a
  chosen threshold. It is applied only inside a matched run, so a wrong call
  can merge two lines of one paragraph but cannot invent a pairing across
  paragraphs; the piece counts are in the JSON for anyone who wants to
  re-cut it.
- **100.0% is a share of characters, not of layout.** Two lines agree when
  they hold the same characters. Where each glyph sits inside the line —
  justification stretch, tab stops, the 배분 gaps that made the regrouping
  necessary — is not measured here at all.
- **`dy` is read against a mediabox that is not the declared page.** The
  references are A4 at 595 × 841 pt while the forms declare 595.28 × 841.88,
  and the conversion used is a flat 100 HWPUNIT per point with no rescale.
  That is worth up to about 88 HWPUNIT at the foot of a page and is inside
  the per-form `dy` constant, not the residual.
- **One machine, one Hancom.** Every pair in the corpus was produced by
  13.0.0.2986 on this machine with these fonts installed. An export from a
  build whose metrics differ from the saving build is exactly the case that
  would re-flow, and this corpus cannot contain it.

## What `hp:lineseg@textpos` counts, and the slicing it fixes — 2026-09-05

Worker: Opus; orchestrator: Fable.

The slice before this one measured that Hancom's PDF export reproduces the
saved `hp:lineseg` exactly, and found our own bug on the way: `textpos`
indexes a stream `Paragraph.chars` is not. This slice reads that stream.

### The model

`hp:lineseg@textpos` indexes the paragraph's TEXT STREAM — the WCHAR run KS X
6101 and the HWP 5.0 paragraph-text record describe, in which a control
character is either a *char* control worth one cell or an *inline*/*extended*
control worth eight. `Paragraph.chars` is a different list: it is built for
the drawing side, one entry per glyph and exactly one slot per inline object,
and `itertext()` walks straight past `<hp:tab/>`, `<hp:lineBreak/>` and their
kind. Slicing `chars` at a `textpos` therefore ran late by whatever the
controls before the cut were worth.

`Paragraph` now builds both streams and the map between them:

| member | what it is |
| --- | --- |
| `chars` | unchanged: `(char, charPrIDRef)`, one slot per inline object |
| `cell_start[i]` | the cell `chars[i]` begins at |
| `cell_count` | the paragraph's total cell count |
| `char_of_cell` / `cell_of_char` | the map, both ways |
| `lineseg_spans()` | `[(lo, hi)]` into `chars`, one per cached line |

Every reader of a `textpos` goes through it: `_render_cached_lines`, the row
planner `_line_rows`, `_object_line`, `stale_cache_reason`,
`page_fit_probe._has_text`, `layout_divergence.cached_line_metrics` (now keyed
on the line's first CHARACTER, because that is what `_line_items` is handed)
and `lineseg_agreement`. Drawing itself is untouched: a tab still advances the
way it did, a line break still breaks, an object still takes one slot.

### The widths, and what pins them

Two constraints hold on every one of the **2995** corpus paragraphs that carry
an `hp:linesegarray` — top level and table cell alike — and neither needs a
reference render:

* **reach** — the last cached line still has to hold a cell, so the widths
  must reach the largest `textpos`;
* **boundary** — a cached line can only START where an element starts, so
  they must not overshoot it either: no `textpos` may land inside a control.

| element | in ¶ | ≥2 seats | cells | how it is pinned |
| --- | ---: | ---: | ---: | --- |
| a literal character | — | — | 1 | by construction |
| `hp:lineBreak` | 20 | 20 | 1 | reach+boundary admit **0 or 1**; the PDF oracle admits only 1 |
| `hp:fwSpace` | 7 | 1 | 1 | char control (HWP 5.0 #31); corpus admits 0–7 |
| `hp:nbSpace`, `hp:hyphen` | 0 | 0 | 1 | char controls (#30, #24); no corpus instance |
| `hp:tab` | 3 | 0 | 8 | inline control (#9); no corpus paragraph constrains it |
| `hp:colPr` | 32 | 2 | 8 | reach+boundary admit **7 or 8**, and the cached box refuses 7 |
| `hp:fieldBegin`/`End` | 9 | 1 | 8 | the cached box refuses every pair sum below 16, and 8 is the cap |
| `hp:tbl` | 80 | 1 | 8 | reach+boundary admit **4–8**; 8 is the extended control (#11) |
| `hp:pic`, `hp:rect` and the other drawing objects | 7 | 0 | 8 | same control (#11); no corpus paragraph constrains them |
| `hp:secPr` | 10 | 0 | 8 | extended control (#1/#2); no corpus paragraph constrains it |
| `hp:header`, `hp:newNum` | 5 | 0 | 8 | extended controls (#16, #18); ditto |
| `hp:markpenBegin`/`End` | 1 | 1 | 0 | an HWPX-only span marker with no control character behind it |
| `hp:titleMark`, `hp:insertBegin/End`, `hp:deleteBegin/End` | 0 | 0 | 0 | the same reading, and **untested**: no corpus instance |
| anything else | — | — | 8 | one control's worth, and `lineseg_vs_pdf` reports the guess |

Under the old reading exactly three paragraphs of three UNEDITED forms fail
both constraints, and they are the three `textpos_past_end` has been firing on
since it was written:

| paragraph | holds | chars | cells then | cells now | max textpos |
| --- | --- | ---: | ---: | ---: | ---: |
| `saeopja` #321 | one `hp:colPr` | 10 | 10 | 18 | 16 |
| `moel-2013` #159 | a HYPERLINK `fieldBegin`/`fieldEnd` | 36 | 36 | 52 | 42 |
| `kstartup` #264 | two inline `hp:tbl` | 13 | 13 | 27 | 15 |

Under the new one, none does — 0 of 2995 fail reach and 0 fail boundary. So
`textpos_past_end` now fires only when the stream genuinely ends early, and
those three caches come back into the cache path.

Two of the three pin their width rather than merely bounding it, and the third
channel that does it is the cached `horzsize` itself: a candidate width fixes
which characters the first cached line holds, and a line whose text does not
fit its own cached box is refuted. Measured with the renderer's own advance
arithmetic at 144 dpi:

| paragraph | candidate | line 0 becomes | visible advance | box |
| --- | --- | --- | ---: | ---: |
| `saeopja` #321 | `colPr` = 7 | `최대출자자와의 관` (9) | 8050 | 7136 — over |
| | `colPr` = **8** | `최대출자자와의 ` (8) | 6640 | 7136 — fits |
| `moel-2013` #159 | pair = 14 | `…에서도 이용` (28) | 13476 | 11752 — over |
| | pair = 15 | `…에서도 이` (27) | 12760 | 11752 — over |
| | pair = **16** | `…에서도 ` (26) | 11616 | 11752 — fits |

Eight is the largest a control can be, so 16 is both the smallest pair sum the
box allows and the largest the format allows: `fieldBegin` and `fieldEnd` are
8 each. `kstartup` #264 is not pinned this way — its line 0 is spaces and two
inline tables, and every width from 4 to 8 leaves the same visible advance.

### What moved

`lineseg_vs_pdf.py` now reads the renderer's own map instead of keeping a
second copy of the model, so the corpus comparison grades the renderer's
reading rather than a private one. It does not move: **411 of 411**
paragraphs, **8566 of 8566** characters, `inkless` 107 / `object` 5 /
`table` 67 skipped, before and after.

The renderer's own slicing does move. Of the **161** corpus paragraphs with
more than one cached line, **25** were drawn with a character on the wrong
side of a break and none is now:

| form | ≥2 seats | mis-sliced before | after |
| --- | ---: | ---: | ---: |
| `admrul` | 2 | 1 | 0 |
| `gianmun-1ho` / `-2ho` | 3 | 0 | 0 |
| `jeongbo` | 6 | 1 | 0 |
| `jumin` | 27 | 0 | 0 |
| `kstartup` | 30 | 3 | 0 |
| `moel-2013` | 35 | 1 | 0 |
| `moel-2025` | 37 | 17 | 0 |
| `nrf` | 3 | 0 | 0 |
| `saeopja` | 18 | 2 | 0 |
| **all ten** | **161** | **25** | **0** |

21 of the 25 are the `lineBreak`/`tab`/`fwSpace` family the previous slice
named and counted; the other 4 need the extended-control widths as well.
Restricted to the paragraphs `lineseg_vs_pdf` can actually compare against the
PDF, 18 of 54 disagreed with the export's own split and 0 do now — which is
the oracle, and it is character-exact:

```
admrul p9    before  '…하고자 하오니 허가' / '하여 주시기 바랍니다. '
             after   '…하고자 하오니 '     / '허가하여 주시기 바랍니다. '
moel-2025 p29 before  '(근로자) 주    소 :연' / ' 락 처 : 성 ' / '   명 : …'
              after   '(근로자) 주    소 :'   / '연 락 처 : '  / '성    명 : …'
```

### The scoreboard

`render_scoreboard.py --corpus --dpi 144`, means over the ten forms:

| policy | channel | before | after |
| --- | --- | ---: | ---: |
| `cache` | text_line_iou | 0.645754 | 0.645275 |
| | ssim | 0.830919 | 0.831060 |
| | ssim_inked | 0.276175 | 0.276567 |
| | text_line_pair_rate | 0.836210 | 0.836393 |
| | page_count exact | 9 of 10 | 9 of 10 |
| `computed` | all four | unchanged | unchanged |

`computed` is byte-identical on every form and every channel, which is the
control: that policy never reads a `textpos`.

Five forms move under `cache`, and they are the five holding a mis-sliced
paragraph:

| form | IoU | ssim | ssim_inked | pair |
| --- | ---: | ---: | ---: | ---: |
| `admrul` | 0.595391 → 0.589760 | 0.926907 → 0.927293 | 0.533986 → 0.535593 | = |
| `jeongbo` | 0.831621 → 0.832390 | 0.765158 → 0.765346 | 0.294106 → 0.294067 | = |
| `kstartup` | 0.272355 → 0.272207 | 0.831700 → 0.831705 | 0.302953 → 0.302943 | 0.790319 → 0.792151 |
| `moel-2025` | 0.557290 → 0.556662 | 0.781896 → 0.782325 | 0.206880 → 0.207606 | = |
| `saeopja` | 0.806544 → 0.807399 | 0.770592 → 0.770993 | 0.279969 → 0.281603 | = |

`moel-2013` does not move at all: its one affected paragraph is a table cell
whose two lines the computed breaker had been putting in the same boxes.

**The pixel channels move toward the reference and the box channel does not,
and the box channel is the one to distrust here.** `ssim` and `ssim_inked` are
read off the Hancom raster and rise on four of the five forms; `text_line_iou`
is an overlap between OUR line box and a PyMuPDF line box, our box ends at
`LINE_BOX_END = visible_advance`, and moving one character — very often a
space — across a break changes where both ends sit. What is not a judgement
call is the split itself: the characters now sit where Hancom's own export
puts them, on all 411 comparable paragraphs.

`render_check.py` on `render-check-01` is unchanged at both 96 dpi (match 6,
close 37, differs 6, unsupported 2) and 144 dpi (match 14, close 31,
differs 4, unsupported 2), 9 of 9 pages either way — the document carries no
`hp:linesegarray`, so there is no `textpos` in it to read.

### `--lineseg-agreement` moved, and one column fell

The breaker's own report compares cached break positions with computed ones,
and those were being compared across the two index spaces. Converted:
2148 → 2151 paragraphs scored, 2116 → 2119 line counts exact, 2030 → 2033
break sequences exact, 158 → 161 multi-line, 139 → 142 of those, 216 → 219
cached break positions, and **80 → 79 matched**.

The one column that fell is worth keeping rather than explaining away. The
corpus's forced breaks are `<hp:lineBreak/>`; the cached break now sits at the
character the control precedes rather than one past it, and `compute_lines`
has no notion of a forced break at all — it breaks on width. Some of the old
agreement at those positions was the two errors cancelling. Teaching the
breaker about `<hp:lineBreak/>` is a separate change and is not made here.

### Not proven

- **Four of the widths have no corpus witness at all.** `hp:tab`,
  `hp:nbSpace`, `hp:hyphen`, `hp:secPr` and the drawing objects other than
  `hp:tbl` appear only in paragraphs with a single cached line, where every
  width satisfies both constraints. They are set from the same control-
  character classification the three measured cases confirm, and a document
  that breaks a line after a tab would test the most load-bearing of them.
- **`hp:titleMark` and the change-tracking markers are a reading, not a
  measurement.** They are given no cell on the same grounds as `markpen` — an
  HWPX-only span marker — and no corpus form carries one.
- **`hp:tbl` is bounded, not pinned.** Reach and boundary admit 4 through 8 on
  the one paragraph that constrains it. 8 is the extended control's width and
  is what the other two measured cases show, but nothing here separates it
  from 7 or 5.
- **`fieldBegin` and `fieldEnd` are pinned only as a sum.** Their paragraph
  constrains `wB + wE` to 16; the even 8/8 split is the classification's, not
  the corpus's, and 16 rests on 8 being the cap.
- **The box refutation is measured with this renderer's advances.** The two
  overflows above are 15% and 13% past the cached box, which is far outside
  the disagreement `--lineseg-agreement` records, but they are still this
  renderer's numbers and not Hancom's.
- **Table cells still never reach the PDF oracle.** The 411 are top-level
  paragraphs. Most of this corpus's text is in cells, and the 4 paragraphs
  that need the extended widths are all cell or object paragraphs, so their
  new splits are checked against the cache's own two constraints and against
  nothing else.
- **The IoU fall is unexplained in detail.** It is attributed above to the
  line box's end moving with the character that moved. No per-line
  attribution was made, and `admrul`'s −0.0056 is the largest single move on
  the board.

## An empty paragraph is one line — measured, 2026-09-05

PR #255 found the defect and priced nothing: `_flow_lines` takes its computed
branch only `if mode == LINE_LAYOUT_COMPUTED and para.chars`, so a paragraph
with no characters falls through to its cached `hp:lineseg`, and a package
this repo wrote carries none. The block came out **0 high**, and the seat
probe read the whole of it as a constant 1600 HWPUNIT that every case sat
above its analytic seat. The three rows where the probe changed the empty
paragraph's line spacing and character height and the read-out moved by
nothing were the same fact seen from the side: there was no line for those
declarations to scale.

That path is every empty paragraph in every edited document, which is the
whole population this renderer exists to draw. This is what the height should
be, measured against the one oracle there is.

### The oracle, and what it says

A Hancom save DOES cache a lineseg for an empty paragraph, so the authoring
engine's own answer is in the corpus. Ten converted forms, every top-level
`hp:p` whose character stream is empty:

* **101 empty top-level paragraphs**, every one with exactly **one** cached
  `hp:lineseg` and exactly **one** `hp:run` — an `<hp:t></hp:t>` that draws
  nothing and declares a shape;
* **none of them carries an object.** An inline picture, table or equation
  occupies a character cell, so a paragraph holding one is not empty by this
  test at all and takes the computed branch already. Its box was measured
  separately and is unchanged here: on the 63 top-level corpus paragraphs
  whose whole character stream is one inline object, the cached `vertsize`
  is the object's `hp:sz` height plus its own vertical `hp:outMargin`, exact
  on **63 of 63**.

**The rule.** An empty paragraph is ONE line, and it is the same line every
other paragraph gets: `vertsize` is the tallest `hh:charPr@height` its runs
declare, and the advance is that height put through the paragraph's own
`hh:lineSpacing` exactly as a text line's is. In code it is
`_line_metrics(para, 0, 0)` — the empty-run pass #247 grew already owns a run
sitting at the end of the character stream, and for a paragraph with no
characters that is every run it has.

Against the cache, all 101:

| quantity | exact |
| --- | --- |
| `vertsize` == the run's declared height | **101 / 101** |
| `textheight` == `vertsize` | 101 / 101 |
| `baseline` == `round(0.85 * vertsize)` | 101 / 101 |
| `spacing` from `hh:lineSpacing` | **91 / 101** |

**There is no counter-example to the rule.** The ten `spacing` misses are all
`PERCENT` and all inside 2 HWPUNIT — the cache four times 2 above the rule and
six times 1 below it, 0.02 pt, 0.0004 px at 144 dpi — which is the same
rounding residual #247 measured on 883 of
the corpus' 2370 cached TEXT lines. It is one residual on both kinds of line,
not a second rule for empty ones. The misses, for the record:

| form | para | spacing | cached | rule | residual |
| --- | --- | --- | ---: | ---: | ---: |
| `gianmun-1ho` | 1 | PERCENT 150 on 900 | 452 | 450 | +2 |
| `kstartup` | 1, 41 | PERCENT 135 on 700 | 244 | 245 | −1 |
| `kstartup` | 3 | PERCENT 130 on 1500 | 452 | 450 | +2 |
| `kstartup` | 72 | PERCENT 143 on 700 | 300 | 301 | −1 |
| `kstartup` | 149 | PERCENT 135 on 1100 | 384 | 385 | −1 |
| `moel-2013` | 22 | PERCENT 145 on 1300 | 584 | 585 | −1 |
| `moel-2013` | 24 | PERCENT 125 on 1300 | 324 | 325 | −1 |
| `moel-2013` | 145 | PERCENT 150 on 1300 | 652 | 650 | +2 |
| `nrf` | 10 | PERCENT 130 on 1300 | 392 | 390 | +2 |

The declared spacings across the 101 are `PERCENT` only — 160 (46), 180 (24),
140 (7), 135 (5), 130 (5), 150 (4), 200 (3), 120 (2), and one each of 100,
125, 143, 145 and **0**. The `PERCENT 0` one is `admrul` paragraph 2: the
cache gives it `vertsize` 400 and `spacing` −400, an advance of exactly zero,
and the rule reproduces both. No corpus empty paragraph declares `FIXED` or
`BETWEEN_LINES`; those two come from the probe below and from the arithmetic,
not from Hancom.

### What computed does for the same paragraphs, and why the corpus cannot move

Ignoring the cache with `--layout-policy computed` does NOT reach the defect
on any corpus form, because the fall-through reads the cached lineseg and
every corpus empty paragraph has one. Measured block height, rule minus what
the flow pass gives today, over all 101:

| delta, HWPUNIT | paragraphs |
| --- | --- |
| 0 | 91 |
| +1 | 6 |
| −2 | 4 |

which is the ±2 residual again and nothing else. Exactly one of the 101 is
measured 0 high today and it is `admrul`'s `PERCENT 0` paragraph, whose height
IS zero.

So the fix is scoped to the case that has no answer: an empty paragraph **and**
no cached lineseg. Where the authoring engine left a seat it is still read,
not recomputed — which is what keeps the corpus untouched, and is also the
honest reading, since the cache is the oracle the rule was fitted to.

### The public probe

`tests/corpus/render-check/measure_seat_probe.py` grows a grid on `P2`, its
empty paragraph: `hh:charPr@height` 10 / 12 / 15 pt against `PERCENT` 160 /
180 / 200, `FIXED 2400` and `BETWEEN_LINES 600`. `BETWEEN_LINES` and the 15 pt
shape are new paraPr/charPr the probe registers itself; `build_render_check`
declares neither. **Path A does not exist for this package and path C is NOT
RUN**: the comparison is the analytic seat the probe computes from the values
it authored, so this says the flow pass obeys the document's declarations, not
that Hancom obeys them the same way.

Before, every one of the 15 grid cases put the read-out paragraph at the same
23800 HWPUNIT — the empty paragraph contributed nothing, whatever it declared.
After, all 15 sit on their analytic seat:

| charPr | PERCENT 160 | PERCENT 180 | PERCENT 200 | FIXED 2400 | BETWEEN_LINES 600 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 pt | 1600 | 1800 | 2000 | 2400 | 1600 |
| 12 pt | 1920 | 2160 | 2400 | 2400 | 1800 |
| 15 pt | 2400 | 2700 | 3000 | 2400 | 2100 |

Across the whole probe — 33 cases, 231 paragraph rows — the seats off their
analytic value go **165 → 0**. That includes the 18 pre-existing cases, whose
constant −1600 offset #255 recorded is gone: `baseline` reads 25400 against
25400, and the empty paragraph's own `ls_130` / `ls_200` / `ls_fixed` /
`pt8` / `pt14` / `pt24` rows now move the read-out by −300 / +400 / +800 /
−320 / +640 / +2240, which is what the declarations predict and what #255
listed as the analytic column those rows were failing.

### After

Nothing on the corpus moved, under either policy, and that is the intended
result rather than a disappointment.

`render_scoreboard.py --corpus --dpi 144`, means over the ten forms, before
and after, both policies:

| policy | text_line_iou | ssim | ssim_inked | pair_rate |
| --- | ---: | ---: | ---: | ---: |
| `cache` | 0.645275 | 0.831060 | 0.276567 | 0.836393 |
| `computed` | 0.633897 | 0.824293 | 0.277430 | 0.847831 |

Identical to six decimals on every channel, before and after, per form and in
aggregate. Page counts are unchanged and exact on nine of ten forms under
either policy: `admrul` 1/1, `gianmun-1ho` 1/1, `gianmun-2ho` 1/1, `jeongbo`
1/1, `jumin` 3/3, `moel-2013` 7/7, `moel-2025` 7/7, `nrf` 4/4, `saeopja` 6/6,
and `kstartup` 21 against a reference 22 under `cache` and 22/22 under
`computed`. Every verdict is unchanged, `kstartup`'s standing failure
included.

`layout_divergence.py --corpus` is byte-identical too, both printed tables and
all ten per-form JSONs. The state it holds at: seats differing `admrul` 15,
`gianmun-1ho` 3, `gianmun-2ho` 3, `jeongbo` 1, `jumin` 3, `kstartup` 165,
`moel-2013` 154, `moel-2025` 187, `nrf` 53, `saeopja` 6; a first seat
divergence on 32 pages across four forms, carried by `page_move` on
`kstartup` (3 of its 20), `d_prev_advance_hwp` on `moel-2013` (4 of 4) and
`moel-2025` (3 of 6), and `page_top` on `nrf` (1 of 2) — the corpus' only
`page_top` carrier, and the trailing-empty-paragraph pagination #252 declined
to touch. `nrf`'s own first divergence is `page_move`, −71630 HWPUNIT at
page 1 paragraph 36.

`render_check.py` on `render-check-01` is byte-identical at 96 dpi (match 6,
close 37, differs 6, unsupported 2) and 144 dpi (match 14, close 31,
differs 4, unsupported 2), 9 of 9 pages exact both times — and the reason is
worth stating rather than assuming, because the change was expected to move
it: **`render-check-01` has no empty paragraph.** All 227 of its `hp:p`,
top-level and in cells, put at least one character down, and so does every one
of `table-break-probe.hwpx`'s 979. The one Rigorloom-written document with a
Hancom reference cannot ask this question, and the seat probe — which has no
reference — is the only place the change shows.

### Not proven

- **No reference render says an empty line is drawn this tall.** The rule is
  fitted to the authoring engine's own cache, and every one of the 101
  paragraphs it was fitted to keeps that cache after the change. The only
  documents the new code path actually runs on are ones nobody has a Hancom
  export of. Path C is the measurement that would close this and it was not
  run.
- **`FIXED` and `BETWEEN_LINES` have no corpus witness for an EMPTY
  paragraph.** All 101 declare `PERCENT`. Those two branches are
  `_line_metrics`' existing arithmetic, measured on text lines, reused; the
  probe and the unit tests pin the arithmetic, not the engine's agreement
  with it.
- **`BETWEEN_LINES` is unmeasured everywhere, not just here.** No corpus form
  declares it on any paragraph, empty or not, so `spacing = max(0, value)` is
  a reading of 여백만 지정 and not a measurement.
- **Computed layout still reads the cache for an empty paragraph.** Under
  `--layout-policy computed` a paragraph WITH a lineseg keeps it, which is
  the inconsistency #247's branch already had and is why the corpus does not
  move. Making computed recompute those too would cost at most 2 HWPUNIT on
  10 of the 101 — the residual above — and it is not done, because the cache
  is the oracle the rule was fitted to and overriding it with a fit to itself
  buys nothing measurable.
- **The ±2 HWPUNIT `PERCENT` residual is still unexplained.** #247 left it
  open on 883 text lines; it is on 10 of 101 empty ones too, at the same
  size, which is evidence it is one rounding rule rather than two, and no
  more than that.
- **Multiple runs on an empty paragraph is untested against Hancom.** Every
  corpus empty paragraph has exactly one run, so "the tallest shape the runs
  declare" is a max over one element there. The max is #247's rule carried
  over, and the unit tests exercise it, but no cached empty paragraph in this
  corpus has two runs to confirm it.
- **The holdout is not in these numbers.** The private report-class document
  was not opened. It is a Rigorloom-written report, so it is exactly the
  population this change moves, and what it is worth there is the operator's
  measurement to make.

## The PERCENT leading sits on a 4 HWPUNIT grid — measured, 2026-09-05

#247 left a residual open on 883 of the corpus' 2370 cached text lines and
#261 found it again on 10 of 101 empty paragraphs, both times calling it "a
rounding difference in how the pitch is divided into `vertsize + spacing`, not
a rule". It is a rule, and it closes on every cached line there is.

`_line_metrics` computed a `PERCENT` line's leading as
`round(height × value / 100) − height`: round the total advance in whole
HWPUNIT, then take the height back off. Hancom does not round the advance.
It rounds the **leading** — and not to a whole HWPUNIT, but to a multiple of
**4**.

### The rule

    spacing = 4 × round(height × (value − 100) / 400)      halves AWAY from zero

`height` is the line's pitch height, which is what `_line_metrics` already
computed: the largest declared `hh:charPr@height` on the line, an inline
object contributing its run's point size rather than its own box. The
function is `own_render.percent_leading` and the quantum is
`own_render.LEADING_QUANTUM`; 4 HWPUNIT is 0.04 pt, or 1/1800 inch.

Two facts of the cache say the quantum is on the leading rather than on the
line:

* **every one of the 3214 cached `hp:lineseg@spacing` in the corpus is a
  multiple of 4** — 3214 / 3214, no exception;
* the cached `vertsize` is **not** — 3161 of 3214. The 53 that are not carry
  an inline object whose box is whatever the object is.

So the advance `vertsize + spacing` is a multiple of 4 only when the height
happens to be, and quantising it directly is refuted below.

### The instrument

`engine/scripts/spacing_residual_probe.py --corpus [--json]`. It reads every
cached `hp:lineseg` of the ten converted forms — top-level paragraphs and cell
paragraphs alike — reconstructs the inputs the authoring engine had (the
declared character heights on the line, the paragraph's `hh:lineSpacing`) and
scores a family of candidate formulas against the cached `spacing`: exact
matches and the residual histogram, per form and in total. It renders
nothing and exercises no policy, so it cannot perturb what
`render_scoreboard.py` or `layout_divergence.py` report.

**`render-check-01` is not in `--corpus` and carries nothing to read.** It is
the one Rigorloom-written package with a Hancom reference render, but
Rigorloom writes no `hp:lineseg` at all; pass it explicitly and the probe
reports 0 cached lines. This question cannot be asked of it.

The population, all ten forms: **3214 cached lines, every one `PERCENT`** —
no corpus paragraph declares `FIXED`, `BETWEEN_LINES` or `AT_LEAST` anywhere.
2376 of them are text lines, 838 belong to a paragraph with no characters, 80
carry an inline object and 127 are of mixed declared height. They span **172
distinct (height, value) pairs**, and the residual is a pure function of that
pair — every line in a cell has the same residual, whatever form, font or
paragraph it came from.

### What the corpus says

| candidate | exact | residual (cache − candidate) |
| --- | ---: | --- |
| **`q4_leading`** (the rule) | **3214 / 3214** | — |
| `q4_advance` — quantise the ADVANCE, not the leading | 3209 | −4 ×5 |
| `q4_leading_half_up` — halves toward +infinity | 3209 | −4 ×5 |
| `q4_leading_half_even` | 2516 | −4 ×3, +4 ×695 |
| `q2_leading` — a 2 HWPUNIT grid | 2300 | −2 ×80, +2 ×834 |
| `q4_leading_trunc` | 2228 | −4 ×5, +4 ×981 |
| `twips` — computed in 1/1440 in, converted back | 2158 | −3 ×14 … +4 ×4 |
| `shipped_round_advance` — what `_line_metrics` had | 2146 | −2 ×5, −1 ×75, +1 ×161, +2 ×827 |
| `gap_half_up` / `gap_floor` / `gap_ceil` / `gap_half_even` / `hundredth_pt` / `advance_half_away` | 2146 | identical to the shipped row |
| `q8_leading` — an 8 HWPUNIT grid | 1800 | −4 ×620, +4 ×794 |

Two things fall out of that table. **The unit is not where the residual
lives.** HWPUNIT *is* 1/100 pt, so `hundredth_pt` is the shipped reading under
another name, and every whole-HWPUNIT rounding — up, down, to even, on the gap
or on the total — scores exactly the same 2146. Changing the rounding mode
buys nothing; changing the grid buys everything. And **the grid is 4 and not
2 or 8**: both neighbours are refuted by hundreds of lines in both directions.

Per form, the shipped reading against the rule:

| form | shipped | rule |
| --- | ---: | ---: |
| `admrul` | 32 / 34 | 34 / 34 |
| `gianmun-1ho` | 66 / 69 | 69 / 69 |
| `gianmun-2ho` | 69 / 69 | 69 / 69 |
| `jeongbo` | 78 / 85 | 85 / 85 |
| `jumin` | 152 / 177 | 177 / 177 |
| `kstartup` | 808 / 840 | 840 / 840 |
| `moel-2013` | 217 / 345 | 345 / 345 |
| `moel-2025` | 179 / 377 | 377 / 377 |
| `nrf` | 99 / 122 | 122 / 122 |
| `saeopja` | 446 / 1096 | 1096 / 1096 |

Restricted to the text lines alone the shipped reading misses **883**, which
is #247's number to the line; restricted to empty paragraphs it misses 185 of
838, of which #261's ten top-level ones are a part. One rule closes both, and
that is the evidence they were ever one residual.

### The five lines that pin the tie rule

`q4_advance` and `q4_leading_half_up` are each exact on 3209 of 3214. What
refutes them is five lines, and all five declare `value < 100`, where the
leading is negative:

| form | height | value | nominal | cache | rule | both rivals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gianmun-1ho` | 1500 | 90 | −150 | **−152** | −152 | −148 |
| `saeopja` | 300 | 50 | −150 | **−152** | −152 | −148 |
| `saeopja` ×3 | 900 | 90 | −90 | **−92** | −92 | −88 |

A negative half-quantum goes further from zero, not toward +infinity, and the
rule is therefore odd about 100%: `percent_leading(h, 100 + d)` is exactly
`−percent_leading(h, 100 − d)`. That symmetry, the grid, the pass-through, the
quarter- and three-quarter-quantum cases and these ties are what the unit
tests pin. Nothing in them is a corpus tally; the corpus check asserts an
empty mismatch list with a non-vacuity floor.

### What changed in the code

`percent_leading` and `LEADING_QUANTUM` sit beside `BASELINE_RATIO`, which is
the other measured constant of this corpus, and `_line_metrics`' `PERCENT`
branch is one call. Nothing else moved: `vertsize`, `textheight` and
`baseline` are derived exactly as before and were already exact on the corpus
(3214, 3214 and 3212-plus-2-within-1). `FIXED` and `BETWEEN_LINES` are **not**
put through the grid — no corpus paragraph declares either, so there is
nothing to fit them to and guessing would be worse than leaving them.

The empty-paragraph branch #261 grew calls `_line_metrics(para, 0, 0)`, so it
inherits the rule for free: its `spacing` is now exact on all 101 top-level
empty paragraphs where it was exact on 91.

### After

**The cache path did not move at all.** `render_scoreboard.py --corpus --dpi
144 --layout-policy cache` is byte-identical before and after on all ten
per-form JSONs — means `text_line_iou` 0.645275, `ssim` 0.831060,
`ssim_inked` 0.276567, `pair_rate` 0.836393, and page counts `admrul` 1/1,
`gianmun-1ho` 1/1, `gianmun-2ho` 1/1, `jeongbo` 1/1, `jumin` 3/3, `kstartup`
21/22, `moel-2013` 7/7, `moel-2025` 7/7, `nrf` 4/4, `saeopja` 6/6. That is
by construction: under `cache` the seats come off the file.

**Under `computed` the raster barely notices, and one channel gets worse.**

| channel | before | after | delta |
| --- | ---: | ---: | ---: |
| `text_line_iou_mean` | 0.633897 | 0.633875 | −0.000022 |
| `ssim_mean` | 0.824293 | 0.824261 | −0.000032 |
| `ssim_inked_mean` | 0.277430 | 0.277281 | −0.000149 |
| `text_line_pair_rate_mean` | 0.847831 | 0.847831 | 0 |

Five forms move and five do not. `admrul` +0.000013, `kstartup` +0.000108 and
`moel-2013` +0.000080 on `text_line_iou`; `moel-2025` −0.000412 and `saeopja`
−0.000003. `ssim_inked` is carried by `kstartup` alone, 0.431328 → 0.429073,
against `moel-2025` +0.000878. Page counts are unchanged on every form under
either policy and every verdict is unchanged, `kstartup`'s standing failure
included.

This is the honest shape of it: the residual is 0.02–0.08 px a line, so no
raster channel can price it, and where it does show up at 144 dpi it shows up
as noise in both directions. **The evidence for the change is in the HWPUNIT
domain, and there it is not close.**

`layout_divergence.py --corpus`, paragraphs agree / A / B / C:

| form | before | after |
| --- | --- | --- |
| `admrul` | 18 / 0 / 1 / 0 | **19 / 0 / 0 / 0** |
| `gianmun-1ho` | 27 / 1 / 0 / 0 | unchanged |
| `gianmun-2ho` | 16 / 0 / 0 / 0 | unchanged |
| `jeongbo` | 50 / 5 / 0 / 0 | unchanged |
| `jumin` | 110 / 17 / 2 / 0 | 111 / 17 / 1 / 0 |
| `kstartup` | 43 / 31 / 98 / 233 | **113 / 31 / 28 / 233** |
| `moel-2013` | 127 / 20 / 112 / 0 | **215 / 20 / 22 / 0** |
| `moel-2025` | 36 / 43 / 225 / 0 | **91 / 43 / 170 / 0** |
| `nrf` | 55 / 2 / 29 / 0 | unchanged |
| `saeopja` | 673 / 16 / 71 / 0 | 674 / 16 / 70 / 0 |
| **total** | 1155 / 135 / 538 / 233 | **1371 / 135 / 320 / 233** |

**Class B falls 538 → 320** and agreement rises 1155 → 1371. Class A is
untouched at 135 and class C at 233, which is what a leading change should do
— it moves seats, not breaks, and `--lineseg-agreement` confirms it: all ten
per-form JSONs are byte-identical (that channel compares `horzpos` and
`horzsize`, so it could not see this either way).

`admrul` is the whole finding in miniature. Its only disagreement between the
two policies WAS this residual — one class-B line at −0.02 px — and computed
layout now reproduces its cached layout exactly. That cost the divergence
tests their fixture: `test_layout_divergence.py`'s `SMALL_FORM` moves from
`admrul` to `gianmun-byeolji-1ho`, which is smaller (one page) and still
diverges for a reason this renderer has not closed.

The seat pass, `seats` (seated under both) / `differ` / `pages with a
divergence`, then the first divergence on the first page that has one:

| form | before | after |
| --- | --- | --- |
| `kstartup` | 165 / 139 / 20 — p1 ¶1, **−2**, `d_prev_advance_hwp` | 165 / **119** / **18** — p4 ¶160, −69632, `page_move` |
| `moel-2013` | 154 / 109 / 4 — p1 ¶3, **+2**, `d_prev_advance_hwp` | 154 / **24** / **2** — p4 ¶119, +1832, `d_prev_advance_hwp` |
| `moel-2025` | 187 / 141 / 6 — p1 ¶2, **−1**, `d_prev_advance_hwp` | 187 / **77** / 6 — p1 ¶7, +1496, `d_prev_advance_hwp` |
| `nrf` | 53 / 7 / 2 — p1 ¶36, −71630, `page_move` | unchanged |
| the other six | 15 / 0 / 0, 3 / 0 / 0, 3 / 0 / 0, 1 / 0 / 0, 3 / 0 / 0, 6 / 0 / 0 | unchanged |

**The ±1–3 HWPUNIT first-seat divergences #255 recorded on `kstartup`,
`moel-2013` and `moel-2025` are gone.** All three documents now agree with
their cache until something much larger happens: a 1832 and a 1496 HWPUNIT
advance difference and a page move of 69632. Those are different mechanisms
and none of them is this one. `nrf` is untouched, which is the right answer —
its first divergence was already a page move and its +102.40 px block was
never this residual.

`render_check.py` on `render-check-01` is byte-identical at 96 dpi (match 6,
close 37, differs 6, unsupported 2) and 144 dpi (match 14, close 31, differs
4, unsupported 2), 9 of 9 pages exact both times. It has no cached lineseg
and no `PERCENT` paragraph this changes the drawn height of.

### Not proven

- **No reference render says the grid is 4.** The rule is fitted to the
  authoring engine's own cache, which is Hancom's arithmetic but not a drawn
  page. `render-check-01` is the only Rigorloom package with a Hancom
  reference and it carries no lineseg at all, so its byte-identical verdicts
  neither confirm nor refute this. Path C is the measurement that would close
  it and it was not run.
- **Why 4 HWPUNIT is not explained.** 0.04 pt, 1/1800 inch. It is not a
  standard typographic unit, no OWPML text mentions it, and nothing here says
  whether it is a fixed-point representation inside the layout engine, a
  device grid, or something else. It is a measured constant of this corpus in
  exactly the sense `BASELINE_RATIO` is, and it is declared as one.
- **The corpus is the training set.** 3214 lines and 172 distinct
  (height, value) pairs against one free parameter and a tie rule is not a
  lookup table, and the tie rule is pinned by five lines with the opposite
  sign from all the others — but it was scored on the same lines it was
  fitted to. No holdout was opened.
- **`FIXED`, `BETWEEN_LINES` and `AT_LEAST` have no witness anywhere.** All
  3214 corpus lines are `PERCENT`. Whether Hancom puts those types on the
  same grid is unmeasured, and they are deliberately left off it.
- **Every corpus pitch height is a whole number of points.** All 3214 are
  multiples of 100 HWPUNIT, so no cached line exercises a fractional-point
  height. `percent_leading` is defined for any integer height and the
  arithmetic is integer throughout, but the corpus could not have said what
  Hancom does there.
- **The raster gain is nil and `ssim_inked` under computed went down.**
  −0.000149 in the mean, carried by `kstartup`'s −0.002255. A 0.02 px per
  line correction cannot show up in SSIM at 144 dpi except as noise, and it
  did. Anyone reading this change as a pixel improvement is reading it wrong.
- **Class B is 320, not 0.** `moel-2025` keeps 170 and `nrf` all 29. #247
  named `nrf`'s +102.40 px as a block measured short and that is still not
  attributed; `moel-2025`'s class-A re-break at paragraph 6 is still upstream
  of most of its remainder.
- **The holdout is not in these numbers.** The private report-class document
  was not opened. It is a Rigorloom-written report whose every paragraph
  takes the computed branch, so it is the population this change actually
  moves, and what it is worth there is the operator's measurement to make.

## What the remaining 320 class-B paragraphs are made of — measured, 2026-09-05

#263 left class B at 320 and named it "not 0" without saying what it is. It
is nine paragraphs and ninety-six cells. Not one of the 320 is a paragraph
that got its own first line wrong.

### Why the seat pass could not answer this

#255's seat pass is top-level only, and it says so: a paragraph inside a
table cell has a `vertpos` measured from its own cell and no flow seat to put
beside it, so `saeopja` — whose whole body is one table — contributes 6 seats
out of 700-odd paragraphs. That limit is load-bearing here. Of the 320
class-B paragraphs **232 are inside a cell** and 88 are top-level, so the
channel that was built to explain class B cannot see three quarters of it.

### The instrument

`engine/scripts/class_b_probe.py --corpus [--json out.json]`, 144 dpi. It
answers the question in the frame the paragraph is actually drawn in. Every
paragraph reaches its line-drawing call through a container — the page body
under `_render_flow_page` or `_render_paragraphs`, a table cell under
`_render_cell_content`, a header or note body under `_draw_stacked` — and the
container hands it an origin:

    absolute top of first line
        = container_y      the container's own top
        + block_offset     the container's vertical-align offset
        + seat             where the container seats the paragraph's block
        + first_offset     where its first line sits inside that block

Every term is read off the arguments the renderer really passed under each
policy, so the four differences are a measurement and their sum is an
identity checked against the drawn `dy` in pixels — `identity_ok`, and it
holds on **320 of 320**. `d_seat` then telescopes over the container: the
step between two consecutive same-container paragraphs is what the earlier
one contributed, and each step is charged to it and the paragraph named.

Three things the pass has to get right or it hides its own answer. A
paragraph with no characters never reaches a line-drawing call, so it is
stepped OVER rather than breaking the chain — the cursor it did not move is
the point — and for top-level paragraphs the pass falls back to the seat
pair `layout_divergence` already computes (cached `vertpos` against flow
top), which is where the inkless ones get a step of their own. A cell whose
own top moved is followed UP to the paragraph that holds its table, because
"the table moved" names nothing. And a re-break is split by whether the
paragraph carries `hp:tab`, which this renderer declares it does not place.

The probe renders each form once per policy, exactly as `layout_divergence`
does, and writes nothing back into either renderer.

### Inheritance versus own

    inherited (d_seat)        101
    container (d_container_y
               or d_block_offset)  219
    own (d_first_offset)        0
    unmeasurable                0

**`d_first_offset` is zero on every one of the 320.** No class-B paragraph
puts its own first line at a different offset inside its own block under the
two policies; every one of them is sitting where something above or around it
put it. Its own advance matches the cache too on all but the handful that are
themselves carriers.

### The mechanism histogram

One ROOT per paragraph — the term that carries most of its `dy`, followed up
through a moved table to the paragraph that holds it. These partition the
population:

| root mechanism | paragraphs | Σ\|dy\| px | per form |
| --- | ---: | ---: | --- |
| `text_rebreak:width` | **167** | 7355.24 | jumin 1, moel-2013 22, moel-2025 142, saeopja 2 |
| `table_row_heights` | 82 | 519.48 | moel-2025 28, saeopja 54 |
| `empty_paragraph` | 29 | 2969.60 | nrf 29 |
| `forced_break` | 28 | 4687.48 | kstartup 28 |
| `cell_valign` | 14 | 60.00 | saeopja 14 |

And every mechanism a paragraph inherits from, which double-books on purpose
(`via_holder:` is the same mechanism reached through the paragraph holding a
moved table):

| mechanism | paragraphs | Σ\|dy\| px |
| --- | ---: | ---: |
| `cell_top:table_origin` | 133 | 11487.80 |
| `text_rebreak:width` | 97 | 3408.04 |
| `cell_top:table_row_heights` | 84 | 573.44 |
| `via_holder:text_rebreak:width` | 80 | 4353.68 |
| `cell_valign` | 42 | 234.86 |
| `via_holder:empty_paragraph` | 27 | 2764.80 |
| `via_holder:forced_break` | 26 | 4369.32 |
| `text_line_height` | 19 | 430.16 |
| `via_holder:interparagraph_gap` | 17 | 2937.60 |
| `via_holder:text_line_height` | 16 | 526.48 |
| `interparagraph_gap` | 13 | 837.28 |
| `empty_paragraph` | 2 | 204.80 |
| `forced_break` | 2 | 318.16 |

`cell_top:table_origin` is the tallest bar of that second table and it is not
a mechanism: a table whose ORIGIN moved did not move itself, its holder was
seated differently, and following it up one level is what turns those 133
rows into the `via_holder:` rows and then into the root table above.

### Nine paragraphs

Charge each class-B paragraph to the single predecessor that paid for most of
its drift, and count the distinct predecessors:

| form | class B | distinct root carriers |
| --- | ---: | --- |
| `jumin` | 1 | ¶46 |
| `kstartup` | 28 | ¶148 |
| `moel-2013` | 22 | ¶118, ¶141 |
| `moel-2025` | 170 | ¶6, ¶37, ¶241 + 28 cells of their own |
| `nrf` | 29 | ¶35 |
| `saeopja` | 70 | ¶166 + 54 cells + 14 cells of their own |

**224 of the 320 come from nine paragraphs.** The other 96 are cell-local:
a row that grew (82) or a cell that re-centred (14), each in its own cell,
with no shared cause to name.

### The top mechanism, and what it is

`text_rebreak:width`, 167 of 320. A text paragraph's computed line breaker
produced a different NUMBER of lines from the cache, and everything below it
in its container — or, through the table it holds, inside it — inherits the
height difference. The seven carriers, as the renderer measures them (the
`cache` width is this renderer drawing the text HANCOM put on that line, so a
cache line wider than the column is this renderer over-measuring it):

| form | ¶ | cache | computed | dwidth px | faces |
| --- | ---: | --- | --- | ---: | --- |
| `jumin` | 46 | 2 lines, 59 ch, 863.44 px | 3 lines, 57 ch | −18.34 | installed only |
| `moel-2013` | 118 | 2 lines, 45 ch, 925.86 px | 3 lines, 38 ch | −35.07 | bundled |
| `moel-2013` | 141 | 1 line, 57 ch, 918.86 px | 2 lines, 49 ch | −29.05 | bundled |
| `moel-2025` | 6 | 1 line, 65 ch, 967.35 px | 2 lines, 62 ch | −26.00 | bundled + system |
| `moel-2025` | 37 | 1 line, 65 ch, 967.35 px | 2 lines, 62 ch | −26.00 | bundled + system |
| `moel-2025` | 241 | 1 line, 54 ch, 881.66 px | 2 lines, 53 ch | −9.76 | installed only |
| `saeopja` | 166 | 3 lines, 67 ch, 933.50 px | 2 lines, 70 ch | −2.90 | installed only |

Six of the seven break EARLIER than Hancom and one breaks later, so it is not
a one-directional bias. **Three of the seven resolve every run to the
declared, INSTALLED face and re-break anyway**, and across the corpus 96 of
the 135 class-A lines are installed-only. Font substitution is therefore not
the explanation; the advance widths this renderer measures differ from
Hancom's by roughly one character at the end of a full line, with the
declared font in hand.

**No fix ships for it.** There is no OWPML attribute, no `paraPr`, no
`lineSpacing` and no KS X 6101 clause that says what a glyph's advance is:
the residual lives in the font metrics and in whatever Hancom does between
them (`hh:ratio`, `hh:spacing` and `hh:relSz` are already read and applied,
`docs/research` and the typography block at the head of `own_render`). Nor is
there a cache-measured invariant to fit: `hp:lineseg` records where a line
STARTS, not how wide its text was, so the cache cannot score a candidate
advance the way it scored the leading in #263. This is a measurement problem
with a reference render, not a rule error, and it is recorded as a proposal
below rather than guessed at.

### The other four, and what each would cost

* **`table_row_heights`, 82 paragraphs, 519.48 px.** `_table_tracks` sets a
  row to `max(cell declared height, content + cell margins)` and the comment
  above it reads `hp:cellSz@height` as a MINIMUM. Under `cache` the content
  never exceeds the declared height, so the rows are exactly as authored;
  under `computed` a taller relaid-out cell grows its row. Cost: honouring
  the declared height exactly would close all 82 and would also clip an
  edited paragraph that grew, which is the case the current reading exists
  for. It needs the row-overflow question answered first, not a flag.
* **`empty_paragraph`, 29 paragraphs, 2969.60 px — all of `nrf`, all at
  +102.40 px.** #247 named that number and left it unattributed; it is
  2 × 2560, and here is where it comes from. `nrf`'s usable height is 71436
  HWPUNIT and its paragraphs 36 and 37 are empty, 16 pt at 160 %, with
  cached `vertpos` **71630 both** — the same seat, past the page bottom. The
  cache does not carry a trailing empty paragraph to the next page; it leaves
  it at the bottom without advancing. The flow pass, which since #261 gives
  an empty paragraph a real 2560-HWPUNIT block, cannot fit either one and
  pushes both onto page 2, displacing every paragraph there by 5120. Cost: a
  rule that a paragraph with no characters does not force a page break sits
  in the flow pass' fit test, is worth all 29, and rests on two cached seats
  in one form — a smaller base than #255's two anchored objects. It wants a
  Hancom reference before it ships.
* **`forced_break`, 28 paragraphs, 4687.48 px — all of `kstartup`, through
  ¶148.** That paragraph declares `pageBreakBefore` AND anchors a table; the
  probe's declared ordering gives it the break label and its detail carries
  the anchor. The step charged to it is 7954 HWPUNIT and it is the only step
  on `kstartup`'s body between ¶148 and ¶734. This is the same paragraph
  #255 measured the `outMargin` reservation on; what is left is not that.
* **`cell_valign`, 14 paragraphs, 60.00 px.** `_render_cell_content` solves
  a CENTER or BOTTOM cell's offset against the block that will actually be
  drawn, so a cell whose content is a different height re-centres. It is the
  smallest bar and it is a consequence of the row question, not a separate
  one.

### Nothing was changed

No rule moved. `render_scoreboard.py --corpus --dpi 144` is what #263
recorded, on both policies:

| channel | `cache` | `computed` |
| --- | ---: | ---: |
| `text_line_iou_mean` | 0.645275 | 0.633875 |
| `ssim_mean` | 0.831060 | 0.824261 |
| `ssim_inked_mean` | 0.276567 | 0.277281 |
| `text_line_pair_rate_mean` | 0.836393 | 0.847831 |

Page counts under `cache`: `admrul` 1/1, `gianmun-1ho` 1/1, `gianmun-2ho`
1/1, `jeongbo` 1/1, `jumin` 3/3, `kstartup` 21/22, `moel-2013` 7/7,
`moel-2025` 7/7, `nrf` 4/4, `saeopja` 6/6; under `computed` `kstartup` is
22/22 and every other form is unchanged. Every verdict is unchanged,
`kstartup`'s standing failure included. `layout_divergence.py --corpus` is
1371 / 135 / 320 / 233 before and after, and `render_check.py` on
`render-check-01` is 6 · 37 · 6 · 2 at 96 dpi and 14 · 31 · 4 · 2 at 144,
9 of 9 pages exact both times. The probe measures; it renders nothing the
scoreboard sees.

### Not proven

- **The top mechanism is named, not solved.** "The advance widths differ" is
  where the measurement stops. Which face, which slot, which characters and
  by how much per glyph is a separate pass against a reference render, and
  the seven carriers above are its worked examples, not its answer.
- **The `hp:tab` split found nothing to split.** Not one carrier on the
  corpus carries a tab, so `text_rebreak:tab` is an empty bucket here. The
  label exists because the renderer declares that gap and a corpus that
  exercised it would otherwise be counted as a width difference; it has no
  witness.
- **`cell_top:table_origin` is followed up exactly one level.** A table
  inside a cell inside a table would need the recursion the probe does not
  do. No corpus form nests that way, so nothing here says what it would
  report if one did.
- **The root is the LARGEST step, not the only one.** Where a paragraph
  inherits from more than one predecessor the root table books it under the
  biggest and the second table books it under all of them; a paragraph whose
  two carriers are close in size is assigned by a margin the tables do not
  show.
- **`page_move` paragraphs are outside this population entirely.** Class B is
  defined as same page under both policies, so the 233 class-C paragraphs and
  every paragraph the two policies page differently are not decomposed here
  and are not in any number above.
- **`saeopja`'s 6 top-level seats are still 6.** The probe reads cell
  paragraphs, which is the whole point, but it reads them against the cell
  they are drawn in; nothing here compares a cell-relative `vertpos` with a
  body-box seat, and nothing should.
- **The corpus is the training set again.** Every carrier, every count and
  the whole ordering of `mechanism` were read off the same ten forms. The
  private report-class holdout was not opened, and its class-B population is
  a different shape: every paragraph takes the computed branch and there is
  no cache to diverge from.

## Whose advance is wrong, and by how much — measured, 2026-09-05

Worker: Opus; orchestrator: Fable.

#265 named the biggest remaining class-B mechanism and stopped there:
`text_rebreak:width`, 167 of 320 paragraphs, descending from seven carriers,
"the advance widths this renderer measures differ from Hancom's". This slice
reads Hancom's own glyph positions out of the reference PDF and says which
advance, on which face, by how much — and finds that two of the seven
carriers are not an advance problem at all.

### The instrument

`engine/scripts/advance_probe.py <form.hwpx> <reference.pdf>`, or `--corpus`;
`--json OUT` writes the per-character record and `--no-text` keeps the
document's text out of it. It reuses `lineseg_vs_pdf`'s pairing verbatim —
the same matching key, the same forward cursor, the same visual-line
regrouping — and reads the PDF with `rawdict` instead of `dict`, which is the
same line records with each span's characters attached. The one change to
`lineseg_vs_pdf` is that `merge_visual_lines` now keeps `parts` instead of
counting and discarding it, so a caller can reach the characters that went
into a merged line.

**Hancom does not draw every character.** This is the fact the whole reading
turns on and it was not in #258, which only ever compared text. On this
corpus a 60-character line commonly reaches the PDF as 31 glyphs in 19
text-showing runs: the spaces are not glyphs, they are the pen being moved
between runs, and **4013 of our characters corpus-wide never appear as a
glyph at all**. So the comparison cannot be glyph against glyph. It is
anchor to anchor: between two characters the alignment matched, Hancom's
distance is `ox[j2] - ox[j1]` in absolute page coordinates and ours is the
sum of our advances over our own characters `i1 .. i2-1` — both sides
covering the same characters. A segment spanning one character on each side,
inside one run, is a pure per-glyph advance and is the only kind the ratio
table below uses. Across a run boundary the distance is a pen move and is
not charged to any glyph; charging it is what made ASCII punctuation look, in
the first version of this probe, as though it had a ratio spread of 0.03 to
2.5.

Our side is `OwnRenderer._measure_hwp` plus the `hh:spacing` gap after it,
which is exactly what `_char_advance_tables` hands the line breaker. It is
**dpi-free** — `LAYOUT_REFERENCE_PX` makes every advance a property of the
outlines and the declared point size — so 96 dpi and 144 dpi give the same
HWPUNIT and the probe has no dpi argument for them. `--dpi` reaches only the
carrier render.

### The ratio, per (resolved face → the PDF's own font, size, 자간, class)

`--corpus`, 8377 anchored single-character advances. `d_med` is the median of
ours minus Hancom in HWPUNIT.

| resolved (ours) | pdf font (Hancom) | pt | 자간 | class | n | median | p10 | p90 | d_med |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `NanumMyeongjo-Regular.ttf` | 휴먼명조 | 13 | 0 | hangul | 2312 | **0.9536** | 0.9449 | 0.9536 | −60.04 |
| `H2MJSM.TTF` | 휴먼명조 | 13 | 0 | space | 864 | 1.0036 | 1.0036 | 1.0037 | +2.35 |
| `NanumMyeongjo-Regular.ttf` | 휴먼명조 | 13 | −6 | hangul | 302 | 0.9492 | 0.9492 | 0.9585 | −62.14 |
| `batang.ttc` | Batang | 12 | 0 | hangul | 282 | **1.0000** | 1.0000 | 1.0000 | 0.00 |
| `malgunbd.ttf` | MalgunGothicBold | 16 | −4 | punct | 185 | 1.0184 | 0.9989 | 1.0184 | +11.28 |
| `batang.ttc` | Batang | 12 | 0 | space | 166 | **1.0000** | 1.0000 | 1.0000 | 0.00 |
| `H2GTRM.TTF` | T6 | 11 | −3 | hangul | 160 | 0.9996 | 0.9996 | 0.9996 | −0.43 |
| `H2GPRM.TTF` | H2gprM | 12 | −12 | hangul | 108 | **1.0000** | 1.0000 | 1.0000 | 0.00 |
| `(fallback)` | T2 | 13 | 0 | digit | 101 | **1.1056** | 1.1056 | 1.1056 | +68.37 |
| `malgun.ttf` | MalgunGothic | 12 | 0 | space | 90 | **1.0000** | 1.0000 | 1.0000 | 0.00 |

231 further runs. Collapsed onto the class alone: hangul 5628 at 0.9536,
space 1943 at 1.0036, punct 466 at 1.0144, digit 209 at 1.1056, fw_punct 84
at 1.0000, latin 33 at 1.0618, other 10 at 1.0545, hanja 4 at 1.0017.

The shape of that table is the answer. **Where our resolved face is the face
Hancom drew with, the ratio is 1.0000** — `batang.ttc`/Batang on 282 Hangul
and 166 spaces, `H2GPRM.TTF`/H2gprM, `malgun.ttf`/MalgunGothic, all exactly
1. Where it is a stand-in it is not: `NanumMyeongjo-Regular.ttf` answering
for 휴먼명조 measures every Hangul syllable at 0.9502 em where the real face
advances 0.9964, and the machine fallback answering for `HCI Poppy` measures
a digit 10.6% wide.

Per line, split by whether every face on the line is the DECLARED one (the
renderer's own `face_resolution@source`), on the 411 comparable lines:

| lines | n | median | median abs | p10 | p90 | within 2 HWPUNIT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 411 | −15.71 | 203.27 | −761.45 | +929.43 | 22 |
| installed faces only | 103 | +41.73 | **56.57** | −0.75 | +705.45 | **20 of 103** |
| a face substituted | 308 | −120.33 | **256.69** | −817.10 | +929.43 | 2 of 308 |

Four and a half times the error on a substituted line, and 20 of the 103
installed-only lines land inside 0.02 pt of Hancom's own width against 2 of
the 308 others.

### The residual on an installed face IS a device grid, and it is 1/600 inch

What is left on the installed side is small, positive and regular, and it is
readable straight off the reference. For a face Hancom has, the advance of a
Hangul syllable is the declared point size **rounded to a whole 1/600 inch**
— 12 HWPUNIT — and not the declared size:

| declared | 1/600 in units | Hancom's Hangul advance | ours |
| ---: | ---: | ---: | ---: |
| 12 pt | 100 | 1200 | 1200 |
| 13 pt | round(108.33) = 108 | **1296** | 1300 |
| 14 pt | round(116.67) = 117 | **1404** | 1400 |
| 11 pt | round(91.67) = 92 | **1104** | 1100 |
| 15 pt | 125 | 1500 | 1500 |
| 20 pt | round(166.67) = 167 | **2004** | 2000 |

and its half-width space is that cell halved and **truncated** onto the same
grid, which is where the sign comes from: at 15 pt the cell is 125 units, its
half is 62.5, and Hancom advances 62 units = 744 HWPUNIT where we advance
750. At 20 pt: 83 units = 996 against our 1000. At 28 pt: 116 units = 1392
against our 1400. The reference's own font sizes carry the same grid — MuPDF
reports 12.96 pt for a declared 13, 11.04 for 11, 14.04 for 14 — on 26 of the
40 (declared size, PDF font) pairs the corpus holds; the 14 that miss are all
subset-embedded fonts (`T2`, `T3`, `T6`, the embedded 휴먼명조) whose reported
size is off by under 0.1%, which is the subset's own font matrix and not a
different grid.

Worth about **+4 HWPUNIT per Hangul syllable and +2 per space at 13 pt**, or
0.3% of a line.

### Every rounding hypothesis was tested, and none of them ships

The question #265 left was whether Hancom rounds. Two forms of the test.
First, directly: what share of Hancom's own per-character advances land
within 0.05 HWPUNIT of a multiple of each candidate grid, against what a
uniform advance would score.

| grid | step | on grid | share | by chance |
| --- | ---: | ---: | ---: | ---: |
| 1 HWPUNIT (= 1/100 pt) | 1.0000 | 2586 | 30.87% | 10.00% |
| 4 HWPUNIT (#263's leading grid) | 4.0000 | 2585 | 30.86% | 2.50% |
| 1/64 pt | 1.5625 | 2292 | 27.36% | 6.40% |
| px @ 96 dpi | 75.0000 | 721 | 8.61% | 0.13% |
| px @ 144 dpi | 50.0000 | 721 | 8.61% | 0.20% |
| px @ 600 dpi (= 12 HWPUNIT) | 12.0000 | 2585 | 30.86% | **0.83%** |

The 1-, 4- and 12-HWPUNIT counts are the same 2585 advances, so the grid
those sit on is 12 and the other two rows are its multiples counted twice.
37 times chance — but only **30.86%** of advances, because the rest come out
of subset fonts whose reported widths are not on it.

Second, and this is the one that decides: does quantising OUR advances onto
each grid reproduce Hancom's per-line widths? 411 comparable lines, exact
within 2 HWPUNIT.

| grid | exact / paired | median abs delta | median delta |
| --- | ---: | ---: | ---: |
| none | 22 / 411 | 203.27 | −15.71 |
| 1 HWPUNIT | 22 / 411 | 206.00 | −17.61 |
| 4 HWPUNIT | 22 / 411 | 197.44 | −8.00 |
| 1/64 pt | 16 / 411 | 198.00 | −8.36 |
| px @ 96 dpi | 5 / 411 | 365.83 | −102.90 |
| px @ 144 dpi | 9 / 411 | 207.65 | −18.00 |
| px @ 600 dpi (= 12 HWPUNIT) | **31 / 411** | 204.00 | −36.05 |
| 1/600 in cell (size rounded, advance truncated) | 16 / 411 | 282.20 | −150.38 |

The 12-HWPUNIT grid is the best of them and it wins nine lines out of 411
while moving the median absolute error by less than one HWPUNIT. The fuller
rule — round the CELL onto the grid first, then truncate the advance — is
**worse than doing nothing** (16 exact, 282.20), because for a size that
rounds UP (11 pt to 11.04) it makes our lines wider, and the substituted
faces it cannot help swamp the installed ones it can.

### The cache CAN score a candidate advance, in one direction

#265 recorded that "`hp:lineseg` records where a line STARTS, not how wide
its text was, so the cache cannot score a candidate advance the way it scored
the leading in #263". It records `@horzsize` as well, which is the box
Hancom fitted that line into. Hancom put those characters on that line, so
our width for them must be no greater than that box: **a cached line our own
metrics call too wide is a proven over-measurement**, with no reference render
in it, and the count of them is a score. It is one-sided on purpose — a line
we call narrow enough may still break elsewhere, because the break also
depends on the next word and on `@condense` — and it reads every paragraph
with a lineseg, cells included, which is where three quarters of this
corpus's text lives.

| form | cached lines | over now | over on the 1/600 grid | worst fill |
| --- | ---: | ---: | ---: | ---: |
| `admrul` | 21 | 0 | 0 | 0.9587 |
| `gianmun-1ho` | 30 | 1 | 1 | 1.0148 |
| `gianmun-2ho` | 18 | 0 | 0 | 0.9967 |
| `jeongbo` | 62 | 5 | 5 | 1.0310 |
| `jumin` | 165 | 2 | 2 | 1.0250 |
| `kstartup` | 447 | 8 | 6 | 1.0256 |
| `moel-2013` | 307 | 9 | 7 | 1.0591 |
| `moel-2025` | 351 | 15 | 13 | 1.0511 |
| `nrf` | 89 | 0 | 0 | 0.9913 |
| `saeopja` | 782 | 11 | 13 | 1.2862 |
| **all ten** | **2272** | **51** | **47** | |

**51 of 2272, 2.2%.** The grid rule closes four of them and opens two new
ones on `saeopja`, for a net of four. That is the cost of the only rule with
a public basis, priced on the widest population this repo can put it in front
of, and it is not worth a change to `_measure`.

### The seven carriers, and the two that are not about advances

`--corpus` runs the carrier pass; all seven matched in the PDF (the four
top-level ones through the pairing, the three cell ones — `jumin` 46,
`moel-2025` 241, `saeopja` 166 — by matching their text anywhere in the
export, which is stated per carrier as `pdf_text_match`).

| form | ¶ | our column | cache's `horzsize` | cache breaks | ours | our width of the cache's line 0 / its box |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| `jumin` | 46 | 42541 | 43172 | [59] | [57, 112] | 42766 / 43172 = **0.9906** |
| `moel-2013` | 118 | 45128 | 45128 | [45] | [38, 79] | 46293 / 45128 = 1.0258 |
| `moel-2013` | 141 | 45128 | 45128 | [] | [49] | 45943 / 45128 = 1.0181 |
| `moel-2025` | 6 | 48190 | 48188 | [] | [62] | 48368 / 48188 = 1.0037 |
| `moel-2025` | 37 | 48190 | 48188 | [] | [62] | 48368 / 48188 = 1.0037 |
| `moel-2025` | 241 | 44057 | 44056 | [] | [53] | 44083 / 44056 = 1.0006 |
| `saeopja` | 166 | 47475 | 46672 | [68, 135] | [68] | 46400 / 46672 = **0.9942** |

**`jumin` 46 and `saeopja` 166 are not advance failures.** Both cached lines
of `jumin` 46 fit inside the cache's own box by our own measurement (0.9906
and 0.9619) and every cached line of `saeopja` 166 fits too — but the column
we hand the breaker is 631 HWPUNIT NARROWER than the box Hancom used on
`jumin` and 803 WIDER on `saeopja`, and the two re-breaks follow the sign of
that difference exactly: `jumin` breaks early because 42766 overruns our
42541, `saeopja` breaks late because 44602 fits inside our 47475 where Hancom
had 46672. Both are cell geometry, both are inside a table, and #265's
`text_rebreak:width` label is wrong on both. That is 3 of the 320 class-B
paragraphs re-attributed, and a mechanism `class_b_probe` has no bucket for.

The other five are width, and the term that carries them is named per line:

* `moel-2013` 118 and 141 are over their box by 1165 and 815 HWPUNIT, and
  the largest single contributor on each is **punctuation** —
  `H2MJSM.TTF/fw_punct +2469` and `H2MJSM.TTF/punct +1768`. The quotation
  marks and parentheses in those two paragraphs are measured off a face that
  gives them a full-width advance (a `“` at 11 pt measures 1133 for us,
  1.03 em) where Hancom draws them at 0.39 em. That is a slot-resolution
  question — which face meters a punctuation character — and it is the same
  family as the substitution above, not a rounding one.
* `moel-2025` 6 and 37 are over by 180 HWPUNIT on 48188, 0.37%. The 1/600
  grid alone brings them to 48028 and they FIT: these two are the carriers
  the device grid would close.
* `moel-2025` 241 is over by 27 HWPUNIT on 44056, 0.06% — and the grid rule
  makes it worse, 44184. Its anchored comparison also says Hancom drew that
  line 45743 wide, past the `horzsize` the lineseg declares, which is either a
  cell whose real column is not its `horzsize` or a mis-match by the
  text-only carrier search; either way, one carrier of the seven is not
  cleanly readable and it is the smallest of them.

### Nothing was changed

`own_render.py` is byte-identical to
`origin/claude/engine-e2-class-b-remainder`. `render_scoreboard.py --corpus
--dpi 144`, both policies, is what #263 and #265 recorded and it did not
move:

| channel | `cache` | `computed` |
| --- | ---: | ---: |
| `text_line_iou_mean` | 0.645275 | 0.633875 |
| `ssim_mean` | 0.831060 | 0.824261 |
| `ssim_inked_mean` | 0.276567 | 0.277281 |
| `text_line_pair_rate_mean` | 0.836393 | 0.847831 |

Page counts under `cache`: `admrul` 1/1, `gianmun-1ho` 1/1, `gianmun-2ho`
1/1, `jeongbo` 1/1, `jumin` 3/3, `kstartup` 21/22, `moel-2013` 7/7,
`moel-2025` 7/7, `nrf` 4/4, `saeopja` 6/6 — 9 of 10 exact; under `computed`
`kstartup` is 22/22 and every other form is unchanged, 10 of 10.
`kstartup`'s standing failure is unchanged under both.
`layout_divergence.py --corpus` is 1371 / 135 / 320 / 233 before and after.
`lineseg_vs_pdf.py --corpus` is 411 / 411 with 8566/8566 characters in
agreeing lines, which is the number the one-line change to
`merge_visual_lines` had to leave alone. `render_check.py` on
`render-check-01` is 6 · 37 · 6 · 2 at 96 dpi and 14 · 31 · 4 · 2 at 144,
9 of 9 pages exact both times.

### The costed proposal

Three rules are now measurable and none of them ships here.

* **The 1/600 inch device grid.** Public basis: the reference PDF's own font
  sizes and the exact Hangul and space advances above. Worth 2 of the 51
  proven over-measurements net 4 (51 → 47), closes `moel-2025` 6 and 37,
  worsens `moel-2025` 241 and `saeopja`. It is real and it is not the
  problem. It should ship WITH the face question, not before it, because on
  its own it moves lines in both directions for a net that a re-measurement
  could reverse.
* **The face.** 308 of 411 comparable lines carry a stand-in, and their error
  is 4.5 times the installed lines'. There is no rule to write: the fix is
  either the declared face on the machine or a metric-compatible substitute,
  and choosing the second means matching a face's Hangul em to the declared
  one, which is a font-selection change and not a layout one.
* **Which face meters a punctuation character.** Two of the seven carriers
  turn on it and it is worth 2469 and 1768 HWPUNIT on their first lines.
  `script_slot` decides it today and nothing in this repo has measured that
  decision against a reference. It is the smallest of the three and the one
  with a bounded population.

And one that is not about advances at all: **the column width of a paragraph
inside a table cell**, worth 631 and 803 HWPUNIT on two carriers, and
currently mis-labelled `text_rebreak:width`.

### Not proven

- **The grid is measured at six sizes and contradicted at one.** 12, 13, 14,
  11, 15 and 20 pt all give round(size × 600/72); 28 pt gives 234 units where
  the rule predicts 233, on 5 characters of one form. The rule is not fitted
  to that case and the case is not explained.
- **Only 411 of 477 paired lines carry a per-line width.** 66 are excluded as
  stretched — a DISTRIBUTE line's gaps are its alignment, and so are a
  JUSTIFY line's on every line but the paragraph's last. Whether Hancom
  stretches a JUSTIFY last line at all is assumed here, not measured.
- **The per-character advance is read through MuPDF.** A PDF text-showing
  operator positions a whole string and the per-character origins are
  reconstructed from the font's own widths, so "Hancom's advance" is Hancom's
  DECLARED advance for that glyph — which is the quantity a line breaker
  needs, but it is not read off the page description.
- **A line's last character carries no ratio.** It has no successor to
  subtract from and its bbox is ink, not advance; the side bearing between
  the two is not modelled and 4013 pen-move characters are not glyph
  advances either.
- **Latin, hanja and `other` are 47 characters between them.** Every ratio
  quoted for them is a median over a handful, and `latin` at 1.0618 mixes
  different letters rather than measuring one.
- **`moel-2025` 241's PDF match is a text search, not the pairing.** The
  three cell carriers are matched by their text anywhere in the export
  because `lineseg_vs_pdf` reads top-level paragraphs only, and on 241 that
  match returns a line wider than the box the lineseg declares.
- **The corpus is the training set, again.** Every ratio, every count and the
  grid itself were read off the same ten forms and the same machine's
  installed fonts. A machine with 휴먼명조 installed would move most of this
  table, which is precisely the point being made and also the reason none of
  it has been fitted to.

## Which margin insets a table cell — measured, 2026-09-05

#267 closed on two paragraphs whose class-B divergence it could show was
*not* an advance failure: on `jumin` 46 the text column this renderer hands a
cell's paragraphs is 631 HWPUNIT narrower than the `hp:lineseg@horzsize`
Hancom saved for the same lines, on `saeopja` 166 it is 803 wider, and every
cached line on both fits our own measurement of its text. It named the two
numbers and stopped there. This run asks which attribute they are made of,
over every cell on the corpus rather than two.

### The instrument

`engine/scripts/cell_column_probe.py FORM.hwpx [--corpus] [--json] [--no-text]
[--paragraph N]` renders each form under the cache policy through a subclass
that wraps `_render_cell_content` and `_render_paragraphs`. The column it
records is the `avail_w_hwp` argument the first of those passes the second —
the renderer's own number, not a second derivation of it that could be wrong
in its own way. A stack of pending cells keeps the reading right for a table
nested inside a cell: the innermost pending cell is always the one whose
paragraphs are about to be laid out.

Two deltas are reported, and the difference between them is load-bearing.
`delta_cell` is `column - max(horzsize)` over the cell's cached lines — the
quantity #267 named. `delta_line` is per line, `_line_box(para, i, column)[1]
- horzsize`: the paragraph's own `hh:margin` and `intent` enter our line box
and the cached one alike and cancel, so this one isolates the CELL's geometry
from the paragraph's. A cell whose lines disagree on a value is reported
`ragged` and left out of the fit.

Six candidate terms are read per cell — the cell's `hp:cellMargin`
left+right, the table's `hp:inMargin` left+right, those two selected by
`hp:tc@hasMargin`, the left+right border widths of the cell's
`hh:borderFill`, `hp:tbl@cellSpacing`, and the solved track sum minus the
declared `cellSz@width` — and every signed combination in `{-1,0,+1}^6` is
scored by how many cells it drives to zero. Scored twice, in fact: exactly,
and to within 8 HWPUNIT (0.03 mm, a third of a pixel at 600 dpi), because a
rule that is right but rounds differently from Hancom is otherwise
indistinguishable from a rule that is simply wrong.

### What the corpus says

Over 1609 compared cells, 1599 of them measurable:

| combination subtracted from the delta | exact | within 8 HWPUNIT |
| --- | ---: | ---: |
| nothing — the renderer as #267 left it | 63 | 716 |
| `-margins +inmargin` | 160 | 1062 |
| `-margins +inset` (`inmargin` or `margins` per `hasMargin`) | 165 | 1102 |
| `+solved` | 218 | 996 |
| `-margins +inmargin +solved` | 311 | 1359 |
| **`-margins +inset +solved`** | **322** | **1406** |

No combination carrying a border-width or `cellSpacing` term ever scored
above one carrying neither. The corpus declares `cellSpacing="0"` on every
table, so that is what "no evidence" looks like here rather than a claim that
a non-zero one would be ignored.

The residuals of the winner are not scattered: 1401 of the 1599 land in
`[0, 4)`, 322 at 0, 348 at 1, 404 at 2, 327 at 3. That is a floor, and the
probe checks the obvious candidate directly — **3164 of the 3177 cached
in-cell `horzsize` values are exact multiples of 4 HWPUNIT**. So the cache's
line box is the column quantised down onto the same 4 HWPUNIT grid #263
measured the PERCENT leading on, and the last three units of every delta
above are that quantiser and not a rule.

### The rule

**A cell's content inset is the table's `hp:inMargin` unless the cell's
`hp:tc@hasMargin` says otherwise.** `hasMargin` — 셀 여백 사용 — is the
override flag: with it set the cell's own `hp:cellMargin` applies, and with
it clear (`"0"`, or absent) the table's default is in force and the cell's
stored `hp:cellMargin` is a value the editor left behind. This is the OWPML
table model's own arrangement and the HWP 5.0 table record's: the table
record carries one default cell margin for every cell it owns, and a cell
carries an override plus the flag that arms it.

This renderer read `hp:cellMargin` unconditionally, which is right on the 56
corpus cells that declare `hasMargin="1"` and wrong on the other 1553.

### The two named cells

**`jumin` 46** (table 1, row 2, col 1, `colSpan="4"`, `hasMargin="0"`) is the
clean case, and its −631 is three terms:

| term | HWPUNIT |
| --- | ---: |
| `cellMargin` 510+510 read where `inMargin` 283+510 was in force | −227 |
| solved track sum 43561 against the declared `cellSz` 43968 | −407 |
| the 4 HWPUNIT floor on the cached `horzsize` | +3 |
| **total** | **−631** |

Both its lines carry the same delta, its paragraph declares no left or right
margin, and `delta_cell` and `delta_line` agree — it is cell geometry end to
end. After the fix its column is 42768 and its delta is −404, all of it the
second term.

**`saeopja` 166 is not a cell-geometry failure at all, and #267's +803 is a
measurement artefact of comparing a column against `max(horzsize)`.** Its
cell's `cellMargin` and `inMargin` are both 141+141, so nothing here moves.
The paragraph declares `margin_left=400`, `margin_right=400`,
`indent=-1900`, and per line:

| line | cached `horzpos` / `horzsize` | ours | delta |
| ---: | --- | --- | ---: |
| 0 | 400 / 46672 | 0 / 47075 | +403 |
| 1 | 400 / 46672 | 400 / 46675 | +3 |
| 2 | 400 / 46672 | 400 / 46675 | +3 |

Lines 1 and 2 are the 4 HWPUNIT floor and nothing else: the column is right.
The +803 of the cell-level delta is `400 + 400 + 3` — the paragraph's own two
margins, which narrow the cached line box and not our column. What IS wrong
on this paragraph is line 0: a negative `intent` of −1900 moves our first
line box to `horzpos` 0 and Hancom left it at 400. That is `_line_box`'s
negative-intent reading, already recorded above as a measured choice between
three readings within 35 boxes of each other on 3214 — and this cell is one
of the boxes that separates them. It is not touched here.

### What changed in the code

`own_render.cell_inset(tc, tbl)` is new and `_table_tracks` calls it where it
used to read `hp:cellMargin` off the cell. It resolves all four sides
together, because the flag governs the margin and not one axis of it; a table
declaring no `hp:inMargin` leaves the cell's own margin standing, since
overriding it with zero would invent a column. Seven unit tests on synthetic
tables cover inherited against overridden, an absent flag, either side of the
pair missing, `colSpan` (which widens the box and never the inset), and
`cellSpacing` and border widths (which do not enter it).

The 4 HWPUNIT floor is **not** applied. It is a property of the saved
`hp:lineseg`, worth at most 3 HWPUNIT, and nothing here shows it is also a
property of the column Hancom broke lines in.

### After

Against the reference PDFs, `render_scoreboard.py --corpus --dpi 144`, means
over the ten forms:

| policy | ssim | ssim inked | line IoU | pages |
| --- | ---: | ---: | ---: | ---: |
| `cache` before | 0.8311 | 0.2766 | 0.6453 | 52 / 53 |
| `cache` after | **0.8420** | **0.3283** | **0.6729** | 52 / 53 |
| `computed` before | 0.8243 | 0.2773 | 0.6339 | 53 / 53 |
| `computed` after | **0.8336** | **0.3246** | **0.6595** | 53 / 53 |

Every form improved or held; no page count moved on either policy. The
largest single move is `gianmun-2ho`, whose inked SSIM goes 0.0563 → 0.3621
in cache mode — a one-page table document whose cells were all inset by
510/510 where 283/283 was in force. `jumin` 0.6917 → 0.7109, `moel-2013`
0.7937 → 0.8193, `saeopja` 0.7710 → 0.7893. `lineseg_vs_pdf.py --corpus`
stays 411/411 with 8566/8566 characters, as it must: it reads the cache
against the PDF and never through this renderer's cell layout.
`render_check.py` on `render-check-01` is unchanged at both 96 dpi
(6 match / 37 close / 6 differ / 2 unsupported, 9 pages) and 144 dpi
(14 / 31 / 4 / 2, 9 pages) — its tables declare the same value in both
margins, so the fix cannot move them.

**`layout_divergence.py --corpus` went the other way, and the reason is worth
recording rather than hiding.** Class B rose 320 → 350, agreement fell 1371 →
1350, class A fell 135 → 118, class C rose 233 → 243. `class_b_probe.py
--corpus` says where: `text_rebreak:width`, the mechanism this whole line of
work is chasing, is **167 before and 167 after — unchanged**. The entire rise
is `table_row_heights` 82 → 109 and `cell_valign` 14 → 17, and it is
concentrated on `moel-2013` (class B 22 → 78, `table_row_heights` 0 → 53)
while `moel-2025` falls (170 → 142, `table_row_heights` 28 → 0).

That measures a real thing. Class B is cache-policy against computed-policy —
this renderer against itself — and a narrower cell column re-breaks more of
its own text, so a column that used to be 284 HWPUNIT too wide on `moel-2013`
was absorbing an advance error that now shows. The channel that grades
against Hancom rather than against ourselves improved on both policies and on
every form. The fix removed a compensating error; it did not create one.

### Not proven

- **The solved track sum is still wrong, and it is not an attribute-handling
  error.** `+solved` is worth 1359 → 1406 cells on its own, and after this fix
  it is the *only* term left in the winning combination. What it names is
  structural: `solve_tracks` forces one global column set on a table whose
  rows do not agree on one. `jumin`'s table 1 declares `hp:sz@width` 50897 and
  its row 0 spans five columns totalling exactly that, while rows 31–38 span
  the same five columns totalling 48067 and rows 33/34/38 split them 29386 +
  18681. Those constraints are mutually contradictory, the even-split and
  proportional-rescale fallbacks distribute the contradiction across every
  column, and the known columns come out 5.87% wide — 6929 declared, 7336
  solved. Hancom evidently lays each row out from its own cells' declared
  `cellSz@width`; reproducing that means giving up the single global track
  set, which changes where every table draws and is not a surgical fix. Left
  alone. The bands it leaves are `jumin` −683 on 19 cells and −407 on 4,
  `kstartup` −156 on 60, `gianmun-1ho` −874 on 2, and on `saeopja` a spread of
  +13 to +20 on 132 cells that is small, dense and unexplained by any of the
  six terms.
- **Whether the 4 HWPUNIT floor belongs in the column.** Measured on the
  saved `horzsize` (3164/3177), not on the breaker's input. Applying it would
  take 1401 cells to exact and move no break by more than 3 HWPUNIT, which is
  precisely why the corpus cannot decide it.
- **`cellSpacing` and border insets are untested, not disproven.** Every
  corpus table declares `cellSpacing="0"`, so the fit had no signal to find.
- **Ten cells are ragged** — their lines disagree on a delta — and are outside
  the fit: 5 on `saeopja`, 4 on `kstartup`, 1 on `jumin`. `saeopja` 166's cell
  is one of them, and its raggedness is the negative-`intent` reading above.
- **The corpus is the training set.** 1609 cells from ten government forms,
  and the `hasMargin="1"` arm of the rule rests on 56 of them.

## The track solve: Hancom lays each table row out on its own — measured, 2026-09-05

#268 fixed which margin insets a cell and left one term standing in the fit:
`+solved`, the difference between the solved track sum and the cell's own
declared `cellSz@width`. It named that term structural rather than an
attribute-handling error and stopped there. This run asks the structural
question directly, over every cell on the corpus.

The public basis says the global solve is our invention. OWPML (KS X 6101)
gives `hp:tbl` a `sz`, a `rowCnt`/`colCnt` and a list of `hp:tr`; every
`hp:tc` under those carries its own `cellSz`, its own `cellAddr` and its own
`cellSpan`. There is no table-level column definition anywhere in the record —
HWP 5.0's binary table record stores the same per-cell width, height and grid
address and no column list. So `solve_tracks` is a reconstruction, and the
cache can be asked whether it is the right one.

### The instrument

`engine/scripts/track_probe.py FORM.hwpx [--corpus] [--pdf] [--rows] [--json]`
subclasses #268's `CellColumnRenderer`, so the text column each cell was
given is still read off the renderer's own `avail_w_hwp` rather than
rederived. Added to it: the solved `xs` per table, and each cell's absolute
drawn box and page.

Four column models are scored:

| model | a cell's box | a cell's x |
| --- | --- | --- |
| `global` | `xs[col+colSpan] - xs[col]` from `solve_tracks` | `xs[col]` |
| `literal` | its own `cellSz@width` | running sum of its own row |
| `addr` | its own `cellSz@width` | `xs[col]` |
| `stretch` | `cellSz@width`, last cell of the row closing to `hp:sz@width` | running sum of its own row |

The residual arithmetic is exact rather than a second derivation: the cell
inset and the paragraph's own `hh:margin` enter the model's line box and the
cache's identically and cancel, so a model's per-line residual is the
renderer's own residual shifted by `model_box - rendered_box`.

`literal`'s row walk carries a merge. A `rowSpan` cell is not repeated in the
rows it reaches into, so the cursor steps over the grid columns it holds and
advances x by its width before placing the next cell the row does list.
Without that carry every row under a merge would start at x=0, and the model
would be measuring the carry's absence. The walk agrees with the file's own
`cellAddr@colAddr` on **1609 of 1609 cells**, which is what says the carry is
right.

### x is not in the cache, and the probe says so rather than assuming it

The task proposed `hp:lineseg@horzpos` as a second oracle, on the reading
that it is a text start. It is — but relative to the cell's own content box.
Over the **2519** cached in-cell linesegs, 2482 equal the paragraph-relative
prediction `max(0, margin_left + intent)` that `_line_box` already computes,
**0** equal any absolute placement, and the largest `horzpos` in a cell
anywhere on the corpus is 1500 HWPUNIT — smaller than any table's second
column. A cache that never records an absolute x cannot separate `literal`
from `addr`, and no amount of reading it harder will change that.

So x got a third oracle off the reference PDF. `--pdf` reads every vertical
stroke Hancom's own export draws (`page.get_drawings()`), in absolute page
coordinates that need no registration — ours in HWPUNIT from the page corner,
which is where `own_render` puts its canvas origin, the PDF's in points at
1 pt = 100 HWPUNIT. Its verdict is real but thin, and the reason is worth
stating: the corpus PDFs draw **1643** distinct vertical stroke positions
while the models predict only 387-527 cell edges, because a cell edge whose
`borderFill` says `NONE` is drawn nowhere. Scored in the only honest
direction — of the strokes Hancom actually drew, how many does a model put a
cell edge under — at one device pixel of 144 dpi (50 HWPUNIT): `global` 263,
`addr` 283, `literal` 305, `stretch` 305. It ranks the models the same way
the width oracle does and it does not prove anything on its own.

### What the corpus says about width

1609 cells compared, 1599 measurable, 10 ragged. A residual in `[0, 4)` is
the column reproduced exactly: #268 measured that the cache saves
`hp:lineseg@horzsize` quantised DOWN onto a 4 HWPUNIT grid (3164 of 3177
values are multiples of 4), so that band is the quantiser. A NEGATIVE
residual is not — no quantiser makes a box narrower than one already rounded
down.

| model | exact | on the 4-HWPUNIT grid | within 8 HWPUNIT |
| --- | ---: | ---: | ---: |
| `global` — the renderer today | 165 | 905 (56.6%) | 1102 |
| `literal` | 322 | 1401 (87.6%) | 1406 |
| `addr` | 322 | 1401 (87.6%) | 1406 |
| **`stretch`** | **324** | **1495 (93.5%)** | **1502** |

Per form, cells on the grid:

| form | of | `global` | `literal` | `addr` | `stretch` |
| --- | ---: | ---: | ---: | ---: | ---: |
| admrul | 16 | 16 | 16 | 16 | 16 |
| gianmun-1ho | 34 | 31 | 31 | 31 | 31 |
| gianmun-2ho | 51 | 51 | 51 | 51 | 51 |
| jeongbo | 70 | 70 | 70 | 70 | 70 |
| jumin | 84 | 40 | 75 | 75 | **81** |
| kstartup | 362 | 302 | 302 | 302 | 302 |
| moel-2013 | 69 | 69 | 67 | 67 | **69** |
| moel-2025 | 102 | 102 | 102 | 102 | 102 |
| nrf | 32 | 32 | 32 | 32 | 32 |
| saeopja | 779 | 192 | 655 | 655 | **741** |

The corpus average hides the measurement. Seven of the ten forms score
identically under all four models — the solved box equals the declared width
on every cell they own, so there is nothing there to disagree about. What
separates the models is the **771 cells the four place differently**:

| model | of those 771, on the grid | cells `global` had on the grid and this model does not |
| --- | ---: | ---: |
| `global` | 143 | 0 |
| `literal` | 639 | 40 |
| `addr` | 639 | 40 |
| **`stretch`** | **733** | **0** |

`stretch` regresses nothing and recovers 590 cells the global solve loses.
`literal` without the row-closing term regresses 40, which is what makes the
`stretch` term a measurement and not an ornament.

### jumin table 1, which is what named the problem

39 rows, 5 columns, `hp:sz@width` 50897. Rows 0-30 total 50897; rows 31-38
total 48067 for the same five columns; rows 33/34/38 split their 48067 as
29386 + 18681. `solve_tracks` closes col2 off the 29386 constraint — a
row-48067 constraint feeding a row-50897 column — and the contradiction
lands on every row of the table:

| cells | declared `cellSz` | solved box | `global` residual | `stretch` |
| --- | ---: | ---: | ---: | ---: |
| rows 4-20 col 2, `colSpan=3` (19 cells) | 39216 | 38530 | −683 | +3 |
| rows 27-30 col 1, `colSpan=4` (4 cells) | 43968 | 43561 | −407 | +0 |
| rows 33/34/38 col 0, `colSpan=3` | 29386 | 31114 | +1729 | +1 |
| rows 33/34/38 col 3, `colSpan=2` | 18681 | 19783 | −1726 | +2 |
| rows 31/32/35/37, `colSpan=5` | 48067 | 50897 | +0…+3, +500 | +0…+3, +500 |

The last two lines are the whole rule in two rows of a table. Rows 33/34/38
declare 29386 + 18681 = 48067 against a table of 50897, and the cache breaks
the FIRST cell at exactly its declared 29386 and the second at
50897 − 29386 = 21511, not at its declared 18681. Rows 31/32/35/37 are one
5-column cell each declaring 48067, and the cache breaks three of them at
50897. Row 31 carries a further +500 that `global` and `stretch` give
identically — the same box, so whatever it is, it is not the column. A
proportional rescale — which is what `solve_tracks` does when it has to —
would have moved the first cell of rows 33/34/38 as well, and it did not
move. The row closes at the table's right edge, and the last cell listed in
the row is what absorbs the difference.

`jumin` goes 40 → 81 of 84 cells on the grid. The three left are +503, +502
and +500, and no model moves them: two of the three are cells every model
gives the same box.

### The rule

**Hancom lays each table row out from its own cells' `cellSz@width`, left to
right, carrying a `rowSpan` cell across the rows it holds; the last cell a
row lists absorbs whatever is left between the row's own total and the
table's `hp:tbl/hp:sz@width`.** There is no global column solve, and rows
that declare contradictory totals are not a contradiction to be resolved —
they are what the file means.

`hp:tbl`'s other attributes were checked for anything that could legitimize a
global width, and none of them does. Over the corpus's 81 tables:
`cellSpacing="0"` on all 81; `repeatHeader="1"` on all 81; `rowCnt` equals
the `hp:tr` count on all 81; `pageBreak` is `CELL` on 62 and `NONE` on 19;
`noAdjust` is `"0"` on 63 and `"1"` on 18. Neither `pageBreak` nor
`noAdjust` correlates with whether a table's rows agree — the 7 tables whose
rows disagree split 3/2/2 across `noAdjust`/`pageBreak` combinations that
also hold 74 tables whose rows agree. `hp:sz@width` is the only table-level
width, and 80 of the 94 distinct row totals on the corpus equal it exactly;
the 14 that do not are the `stretch` term's whole population.

Span handling is the same in all four models and is not what separates them:
751 cells declare `colSpan>1` alone, 103 `rowSpan>1` alone, 109 both, 646
neither. `colSpan` never enters the box twice — a merged cell's `cellSz@width`
is already the whole merged width, which is why `literal` needs no per-column
sum at all.

### Not implemented, and why

The task's gate was 99% of cells with the counter-examples explained.
`stretch` reaches 93.5% of all measurable cells and 95.1% of the contested
ones, so the gate is not met and `own_render.py` is unchanged on this branch.
Two things would have to close before it should be:

- **38 contested cells stay off the grid under `stretch`**, 37 of them on
  `saeopja` and concentrated in one shape. In `saeopja`'s 47996-wide table,
  rows 8/9 total 47868 and the 128 short is not taken by the last cell: the
  cache gives +26 to the `colSpan=3` cell at col 10 and +98 to the
  `colSpan=1` cell at col 17, where `stretch` gives the last cell all 128
  (residual +30) and `literal` gives it none (−98). The shortfall is split
  between two cells in amounts that are neither proportional to their widths
  nor equal, and nothing measured here says what picks them. `jumin` row 31
  is the 38th, at +500.
- **x has no oracle strong enough to move every table rule on.** The model
  changes where every cell in every table is placed, and the only absolute
  evidence for x on this corpus is 1643 PDF strokes that rank `stretch` above
  `global` by 42 out of 1643. That ranks; it does not license.

### Nothing moved, and that is the point

`own_render.py` is byte for byte what #268 left, so every channel reads
exactly as it did there, and the run confirms it rather than assuming it:
`render_scoreboard.py --corpus --dpi 144` gives `cache` 0.8420 ssim / 0.3283
inked / 0.6729 line IoU with 52 of 53 pages exact, and `computed` 0.8336 /
0.3246 / 0.6595 with 53 of 53. `lineseg_vs_pdf.py --corpus` is 411/411
paragraphs with 8566/8566 characters. `cell_column_probe.py --corpus` is 1599
measurable cells with the `-margins +inset +solved` combination still winning
at 322 exact / 1406 near, and `+solved` — which is `literal`'s width, read
through #268's fit rather than this one's — scoring identically.
`layout_divergence.py --corpus` is agreement 1350, class A 118, class B 350,
class C 243. `render_check.py` on `render-check-01` is 6 match / 37 close / 6
differ / 2 unsupported at 96 dpi and 14 / 31 / 4 / 2 at 144, 9 pages on both.

Worker: Opus; orchestrator: Fable.

### Not proven

- **The 66 off-grid cells the four models place identically are not a track
  question at all** and are unchanged from #268: `kstartup` −156 on 60 cells,
  `gianmun-1ho` −874 on 2 and −1157 on 1, `jumin` +503 and +502, `saeopja`
  +602. Every model gives them the same box, so whatever they are, it is not
  the column. Excluding them, `stretch` is 1495 of 1533 — 97.5%, still short
  of the gate.
- **Which cell absorbs a row's residual** is `stretch`'s one free choice and
  it rests on 7 rows of `jumin` plus the `moel-2013` pair. "The last cell the
  row lists" is what those say; `saeopja` says it is not always the last cell
  alone.
- **A row that overflows its table** is untested as a separate case:
  `saeopja` has rows both under and over `hp:sz@width` and `stretch` shrinks
  the last cell symmetrically, but no corpus row overflows by enough to
  separate shrinking from clamping.
- **The corpus is the training set** — 81 tables from ten government forms,
  and the whole `stretch` term rests on the 7 of them whose rows disagree.
- **The PDF rule oracle measures recall of drawn strokes**, so a form whose
  cells declare no borders contributes nothing to it, and a stroke that is
  not a table rule counts against every model equally.

## A row's shortfall is not shared out — it is a boundary already written — measured, 2026-09-05

#270 found that Hancom tiles each table row from its own cells' declared
`cellSz@width` and closes the row at `hp:tbl/hp:sz@width`, and left one
question standing: WHICH cell takes the difference. `stretch` answered "the
last cell the row lists", reached 1495 of 1599 measurable cells on the
cache's 4-HWPUNIT grid, and could not explain 37 `saeopja` cells where a
128-HWPUNIT shortfall splits +26 / +98 between two cells.

This run put nine more models beside it. The answer is that the question was
wrong: there is no shortfall to share out. Hancom keeps one column grid per
table, and a row that does not add up does not choose a victim — it lands
wherever the grid already disagrees with it, which can be two cells, in
amounts that are neither equal nor proportional.

### The instrument

`engine/scripts/track_probe.py FORM.hwpx [--corpus] [--pdf] [--rows]
[--heights] [--models LIST] [--json]` — #270's probe, with nine models added
and `--models` to name a subset. `--rows` now prints every cell of every row
that does not add up, with the box the CACHE gave it beside each model's
residual, so the measurement and the guesses are in the same table.

Six models tile the row exactly as `stretch` does and differ only in who
pays: `prop4` (proportional to declared widths, each share floored onto the
4-HWPUNIT grid, remainder to the last cell), `prop_round` (rounded,
remainder to the last), `prop_widest` (remainder to the widest), `quanta`
(4 HWPUNIT at a time, left to right, until spent), `colspan` (the largest
`colSpan` takes it all) and `stretch` itself.

Three do not compute a shortfall at all. They build one column grid and let
a cell's box be the distance between the two boundaries it sits between:

| model | who may write a boundary |
| --- | --- |
| `firstrow` | row 0 only — the task's "the first row's tracks" reading |
| `gridfirst` | the first cell, in document order, whose width reaches it |
| `gridlast` | a later row overwrites an earlier one — the control |

All three seed `x[0] = 0` and `x[colCnt] = hp:tbl/hp:sz@width`, which is
#270's row-closing term restated as a boundary rather than as an allocation.

### What the corpus says

1599 measurable cells, of which the models place 828 identically and 771
differently. Only the second population is evidence about columns.

| model | exact | on the grid | % | of the 771 | regressions vs `global` | vs `stretch` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `global` — the renderer today | 165 | 905 | 56.6 | 143 | 0 | 590 |
| `literal` | 322 | 1401 | 87.6 | 639 | 40 | 99 |
| `addr` | 322 | 1401 | 87.6 | 639 | 40 | 99 |
| `stretch` — #270's best | 324 | 1495 | 93.5 | 733 | 0 | 0 |
| `prop4` | 265 | 1218 | 76.2 | 456 | 7 | 277 |
| `prop_round` | 255 | 1144 | 71.5 | 382 | 12 | 356 |
| `prop_widest` | 250 | 1144 | 71.5 | 382 | 12 | 356 |
| `quanta` | 250 | 1130 | 70.7 | 368 | 42 | 365 |
| `colspan` | 296 | 1395 | 87.2 | 633 | 2 | 102 |
| `firstrow` | 326 | 1497 | 93.6 | 735 | 0 | 0 |
| **`gridfirst`** | **326** | **1518** | **94.9** | **756** | **0** | **1** |
| `gridlast` | 326 | 1497 | 93.6 | 735 | 0 | 0 |

Every model that shares a shortfall out among a row's own cells loses to the
one that hands it all to the last cell, and loses badly: the best of them,
`prop4`, gives back 277 of the cells `stretch` has. Proportionality is not
what Hancom does, and neither is any rounding of it. `colspan` — the reading
that a merged cell absorbs — is the best of the allocation family at 1395,
still 100 short of `stretch`.

`gridlast` scores exactly what `firstrow` does and 21 below `gridfirst`,
which is what says "first" is doing the work rather than "a grid" doing it.

### The +26 / +98, and where the two numbers come from

`saeopja`'s 47996-wide table, 43 rows, 18 columns. Row 7 lists six cells
totalling 47896; rows 8 and 9 list six totalling 47868, 128 short. The cache
gives +26 to the `colSpan=3` cell at column 10 and +98 to the `colSpan=1`
cell at column 17.

Under `gridfirst` those are not two allocations. They are two boundaries,
and neither was written by row 8:

| written by | boundary | value |
| --- | --- | ---: |
| the table's own `hp:sz@width` | `x[18]` | 47996 |
| row 3, `c0+1` … `c16+2`, a full partition | `x[1]`, `x[3]`, `x[5]`, `x[7]`, `x[9]`, `x[11]`, `x[12]`, `x[14]`, `x[16]` | 3234 … 43961 |
| row 7, `c4+2` at 11448 + 2935 | `x[6]` | 14383 |
| row 7, `c6+7` at 14383 + 19010 | `x[13]` | **33393** |
| row 8, `c6+2` and `c8+2` | `x[8]`, `x[10]` | 20429, **26433** |

Row 8's `c10+3` starts at `x[10]` = 26433 and reaches `x[13]` = 33393, so
its box is 6960 against a declared 6932: **+28**, which the cache's
quantiser saves as +26. Its `c17+1` starts at `x[17]` = 44144 and reaches
`x[18]` = 47996, so its box is 3852 against a declared 3752: **+100**, saved
as +98. The declared widths that produce them are row 7's 19010 at column 6
and the table's own 47996 — not row 8's own widths at all, which is why no
function of row 8 was ever going to find them. Row 7 itself is 100 short and
gives all 100 to its last cell, because at row 7 no interior boundary to its
right had been written yet; `stretch` and `gridfirst` agree there and
disagree one row later.

### The row that pays its shortfall to its FIRST cell

The 47996 table is where the model was found, so it does not test it.
`saeopja`'s 47757-wide table does, and it is the one row on the corpus that
tells `stretch` and `gridfirst` apart in the opposite direction.

Row 4 totals 47757 exactly and lists `c0+3` at 9890, writing `x[3]` = 9890.
Ten rows later row 14 lists `c0+3` at 9759 and `c3+5` at 37867, totalling
47626 — 131 short. `gridfirst` gives `c0+3` the boundary row 4 wrote, so its
box is 9890, **+131 on the FIRST cell**, and `c3+5` then runs 9890 → 47757
for a box of 37867, exactly its declared width and +0. The cache measures
9890 and 37866. `stretch` has it backwards on both cells, and `firstrow`
and `gridlast` miss it too, because the boundary was written by row 4 and
neither of those lets row 4 write it.

Two cells is thin, but they are the only two on the corpus that `gridfirst`
gets right and that were not in view when it was written.

`jumin` table 1 reads the same way. `x[3]` = 29386 is written by the first
row that lists a `colSpan=3` cell at column 0, and rows 33/34/38 then break
their second cell at 50897 − 29386 = 21511 rather than at its declared
18681, exactly as #270 measured — except that #270 had to call it "the last
cell absorbs" and here it is just `x[5]` = `hp:sz@width`.

### The rule

**A table has one column grid. `x[0]` is 0, `x[colCnt]` is
`hp:tbl/hp:sz@width`, and every interior boundary is written by the first
cell, in document order, whose declared `cellSz@width` reaches it. A cell
that reaches a boundary already written is stretched or shrunk to it and
writes nothing. A cell's box is the distance between its two boundaries.**

The grid is a global column set after all — #270 was wrong to call the
global solve our invention in kind, and right to call it wrong in method.
What `solve_tracks` gets wrong is not that it solves globally but that it
rescales: it treats contradictory rows as a system to be reconciled, and
Hancom treats the first statement as binding and every later one as
something to be fitted to it.

### Not implemented, and why

The gate was 99% of cells on the grid with 0 regressions and the remaining
misses explained. `gridfirst` is 1518 of 1599 — **94.9%**, well short of it
on the denominator #270's headline used. Three separate things would have to
close first, and this run closed one of them:

- **The 66 cells every model places identically** are unchanged from #268
  and are not a column question: `kstartup` −156 on 60 cells, `gianmun-1ho`
  −874 on 2 and −1157 on 1, `jumin` +503 and +502, `saeopja` +602. Excluding
  them `gridfirst` is 1518 of 1533, **99.0%** — the first model to cross 99
  on that population, and `stretch` was 97.5%.
- **15 contested cells stay off the grid**, and only three of them have an
  account. Eight are near-misses of one grid step: six at −1 and two at +4,
  all inside the 8-HWPUNIT near band, and `near` improves 1502 → 1526. Four
  are rows 7 and 8 of `saeopja`'s 48027-wide table, where a 19-HWPUNIT
  shortfall goes to the row's FIRST cell (`c0+3` measured at 12018 against a
  declared 12002) while row 4 of the same table gives its 19 to the last
  cell; `gridfirst` writes `x[3]` = 12002 from row 7's own first cell and
  the cache writes 12021, and nothing measured here says where 12021 comes
  from. A per-column width vector consistent with every cached box in that
  table does exist — `w0` = 5660, `w2` = 100, `w9` = 262 and so on — but it
  was solved from the cache's answers, so it predicts nothing. The last
  three are `jumin` row 31 at +500 and two `saeopja` cells whose cached
  horzsize is WIDER than their declared `cellSz@width` (`r3 c6+3` declares
  1062 and the cache breaks it at 2006; `r9 c0+12` declares 48008 and the
  cache breaks it at 47426), which no tiling of their rows can produce.
- **x still has no oracle, and this run made that worse rather than
  better.** The PDF vertical-stroke recall at 50 HWPUNIT is `global` 263,
  `addr` 283, `literal` 305, `stretch` 305, `firstrow` 305, `gridlast` 305,
  **`gridfirst` 303** — two BELOW `stretch`, out of 1643 drawn strokes.
  `gridfirst` wins the width oracle by 23 cells and loses the x oracle by 2
  strokes, and the model moves where every cell in every table is drawn. A
  change to `solve_tracks` moves every table rule on the corpus, and 1643
  strokes that cannot separate the two candidates do not license it.

So `own_render.py` is byte for byte what #268 left, for the second run
running. The rule is recorded and the instrument that found it is in the
tree; what it needs before it ships is an absolute-x oracle, which this
corpus does not contain.

### The row-height question, first look

`--heights` reports the shape of #265's root rather than solving it.
`hp:tr` carries no height in OWPML, so a row's height has to come from its
cells' `cellSz@height`. Over the corpus's 81 tables and 514 rows:

- **500 of 514 rows** have every `rowSpan=1` cell declaring one identical
  height, so "the tallest cell" and "any cell" are the same answer and the
  question does not arise. No row lists zero `rowSpan=1` cells. The 14 that
  disagree spread by 283 HWPUNIT on 5 rows, 100 on 2, and then singletons at
  45, 434, 1300, 1308 and 1345.
- **202 of 212 `rowSpan` cells** declare a height exactly equal to the sum
  of the unit heights of the rows they cover, so the merge adds no
  constraint and no simultaneous solve is needed. The 10 that do not are all
  singletons and all large — +2662, +3562, +3127, +4300, +435, +384, −566.
- **50 of 81 tables** have row heights summing exactly to
  `hp:tbl/hp:sz@height`. The 31 that do not are short by 700 on 2 tables,
  3959 on 2, and then singletons up to 10195.

The reading this supports is that row heights are the max of the row's own
`rowSpan=1` cell heights and that a rowSpan-aware solve buys 10 cells out of
212 — but the 31 tables whose rows do not sum to the declared table height
are a third of the corpus and are not explained by either reading, so this
is a shape and not a rule.

### Nothing moved, and that is measured

`own_render.py` is untouched, and every channel confirms it rather than
assuming it. `render_scoreboard.py --corpus --dpi 144` gives `cache` 0.8420
ssim / 0.3283 inked / 0.6729 line IoU with 52 candidate pages against 53
reference (`kstartup` 21/22), and `computed` 0.8336 / 0.3246 / 0.6595 with
53/53 — both identical to #270 to four places, in both directions.
`lineseg_vs_pdf.py --corpus` is 411/411 paragraphs with 8566/8566
characters. `cell_column_probe.py --corpus` is 322 exact / 1406 near of 1599.
`layout_divergence.py --corpus` is agreement 1350, class A 118, class B 350,
class C 243. `render_check.py` on `render-check-01` is 6 match / 37 close /
6 differ / 2 unsupported at 96 dpi and 14 / 31 / 4 / 2 at 144, 9 pages on
both.

Worker: Opus; orchestrator: Fable.

### Not proven

- **Which cell writes a boundary when two rows reach it at once** is
  `gridfirst`'s one free choice, and document order is what the corpus says.
  `gridlast` — the same grid resolved the other way — scores 21 cells worse,
  which distinguishes the two but does not establish that Hancom's rule is
  ordinal rather than, say, "the widest span wins" (untested; on this corpus
  the earlier row is also usually the wider span).
- **The four `saeopja` 48027 cells contradict document order outright.** Row
  7's first cell is measured 19 HWPUNIT wider than it declares, and the only
  boundary that could do it is one no earlier row writes. Either the grid is
  not built in document order, or something outside `cellSz` writes `x[3]`.
- **A row that overflows its table** is still untested as a separate case,
  unchanged from #270: no corpus row overflows by enough to separate
  shrinking the last cell from clamping it.
- **The corpus is the training set**, and it is the same training set #270
  used — 81 tables from ten government forms, with the whole grid term
  resting on the 7 whose rows disagree. `gridfirst` was designed after
  looking at `saeopja` rows 8/9, so those 37 cells are fitted, not
  predicted. Of the 21 cells it gains over `firstrow` and `gridlast`, 20 are
  in that same fitted table and 2 are the 47757 table's row 14, against 1
  lost; those 2 are the whole of its held-out evidence.
- **The row-height numbers are counts of the declaration, not of the
  render.** There is no cached row height to score against, so nothing above
  says what Hancom actually did with those heights — only what the file
  gives it to work with.

## A cell's text column has a floor, and it is 0.2 inch — measured, 2026-09-05

#268, #270 and #272 each closed leaving the same 66 cells behind: cells
whose cached `hp:lineseg@horzsize` no column model reproduces and every
column model places identically, so whatever moves them is not the column.
`kstartup` −156 on 60, `gianmun-1ho` −874 on 2 and −1157 on 1, `jumin` +503
and +502, `saeopja` +602. This run asks the cell itself.

### The instrument

`engine/scripts/cell_column_probe.py FORM.hwpx --residuals [--corpus]
[--json]` selects that population — measurable, off the cache's 4 HWPUNIT
grid, and given one box by all twelve of #272's models — and dumps for each
cell everything the file offers as a candidate: `hp:tc@hasMargin`, the cell's
own `hp:cellMargin` and the table's `hp:inMargin` and the inset
`cell_inset` resolves from the two, the `hh:borderFill` id with its left and
right line types and widths, `hp:tbl@cellSpacing`, the `hp:subList`'s
`vertAlign`, `textDirection` and `lineWrap`, and per paragraph its `paraPr`
id, `align`, left and right `hh:margin`, `intent`, `hp:heading` type and
level, `hh:tabPr` stop definitions and tabs used, every inline object with
its kind, width, `outMargin` and `treatAsChar`, and every cached line's
`horzpos` and `horzsize` beside our own.

The residual is then fitted. Eight readings of the cell's geometry — as
rendered, a floor, no inset at all, `cellMargin` unconditionally, `inMargin`
unconditionally, plus or minus the border widths, less `cellSpacing` — are
crossed with the three readings of a negative `hh:intent` #268 weighed, and
the cheapest pair that puts EVERY one of the cell's cached lines inside
`[0, 4)` is reported as its account. Cheapest means fewest departures from
what the renderer does now, so a cell that needs one change is never
reported as needing two.

`track_probe.probe_form` grew a `cell_id` per cell and a `keep_renderer`
flag so the elements behind a cell can be reached without rendering the form
twice and matching the two runs up by address.

### What the 66 are made of

Two causes, and neither is a table attribute:

| account | cells | where |
| --- | ---: | --- |
| `column := floor 1440` | 63 | `kstartup` 60, `gianmun-1ho` 3 |
| `horzpos := margin_left only` | 3 | `jumin` 2, `saeopja` 1 |

No residual cell carries a `hp:heading`, a bullet, a tab, an inline object,
a `VERTICAL` text direction or a non-zero `cellSpacing`, and no reading of
the border widths explains a single one of them. That is what the dump is
for: those candidates are ruled out by having been read rather than by not
having been thought of.

### The floor

`kstartup`'s block is one table, rows 2-6 × columns 1-12 — sixty identical
cells 1566 HWPUNIT wide, inset 141 on each side, holding an empty paragraph.
The column that leaves is 1284 and the cache saved `horzsize` 1440 in every
one. Their row's neighbours settle that the inset itself is right: `c13` is
9082 wide, our column is 9082 − 282 = 8800, and the cache says 8800.

`gianmun-1ho` says the same thing from two more widths. Its `r7c6` and `r8c6`
are 848 wide, leaving 566; its `r8c11` is 565 wide, leaving 283. All three
cache 1440.

Over every cached in-cell `hp:lineseg` on the corpus:

- the smallest `horzsize` anywhere is **1440**, the next smallest is 1696,
  and **nothing is below it**;
- **64 lines sit exactly on 1440**, and they come from four different
  columns — 283, 500, 566 and 1284 — so the value is not a function of the
  cell;
- those 64 carry two different `textheight` values, 900 and 1000, so it is
  not a multiple of the text either;
- `gianmun-1ho` `r8c11` is 565 HWPUNIT wide in total and still caches a 1440
  line box, so this is a floor on the LINE and not a clamp on the margins:
  no reading of a 565-wide cell's insets produces 1440, and the text is
  simply allowed to overhang the cell it sits in.

1440 HWPUNIT is 0.2 inch exactly — 5.08 mm, 14.4 pt — which reads as a
designed constant rather than a derived one.

### The rule

**A table cell's text column is its box less its inset, and never less than
1440 HWPUNIT.** `own_render.cell_text_width(box_hwp, margin)` is new and
carries `MIN_CELL_TEXT_WIDTH`; the two places that computed a cell's content
width — `_table_tracks`, for the content extent a row is measured from, and
`_render_cell_content`, for the column the paragraphs are laid out in — both
call it, so the row and the text can never disagree about how wide the cell
is. Six unit tests on the synthetic table #268 built cover a roomy cell,
the three corpus widths, a cell narrower than the floor, the floor's
independence from the inset, the boundary (a column already on 1440 is not
snapped, and 1444 stays 1444), and the render path itself — that
`_render_cell_content` hands `_render_paragraphs` the floored number.

### The three that are not a cell question at all

`jumin` `r15c0`, `jumin` `r1c0` and `saeopja` `r19c0` are the `saeopja` 166
case #268 recorded, three more times. Each is a single cached line whose
paragraph declares a left margin and a negative `intent` larger than it —
500 against −1070, 500 against −1308, 600 against −2180 — and in each the
cache put the line box at `horzpos` = the left margin while `_line_box`
clamps `max(0, left + intent)` to 0. The residual is the margin plus the
grid: 503, 502, 602.

They are left alone, for the reason #268 gave: the reading is a global
property of every paragraph on the corpus and not a cell attribute, and #268
measured all three readings over all 3214 cached line boxes — the clamped
one this renderer implements scores 2860, "a negative intent moves nothing"
2895, the textbook hanging indent 2710. These three cells are three of the
35 that separate the first two. That is now a second, independent line of
evidence for the middle reading and still not a slice: changing it moves
every line box in the corpus and belongs to whichever run takes the indent
question on.

### After

The 66 go to 3, and the three that remain are the three above.
`cell_column_probe.py --corpus` goes **322 exact / 1406 near → 385 / 1470**
of 1599 measurable cells; the −156 band of 60 leaves the residual histogram
and nothing appears in its place. `track_probe.py --corpus` moves with it:
the renderer's own `global` model goes 905 → **969** cells on the
4 HWPUNIT grid, and `gridfirst` — #272's best, which this branch does not
implement — goes 1518 → **1581**, 94.9% → **98.9%** of all 1599, because the
floor was costing every model the same 64 cells.

**Every raster channel is byte-identical before and after, and that is
correct rather than disappointing.** `render_scoreboard.py --corpus --dpi
144` gives `cache` 0.8420 ssim / 0.3283 inked / 0.6729 line IoU with 52 of
53 pages, and `computed` 0.8336 / 0.3246 / 0.6595 with 53 of 53 — the same
JSON byte for byte on both policies, form for form. `lineseg_vs_pdf.py
--corpus` is 411/411 paragraphs with 8566/8566 characters, unchanged.
`layout_divergence.py --corpus` is agreement 1350, class A 118, class B 350,
class C 243, unchanged. `render_check.py` on `render-check-01` is 6 match /
37 close / 6 differ / 2 unsupported at 96 dpi and 14 / 31 / 4 / 2 at 144,
9 pages on both, unchanged.

Nothing moved because of what is IN those 64 lines: 61 of them are empty
paragraphs, and the other 3 hold one character each in a `JUSTIFY`
paragraph, which on a last line is a left-aligned line. A wider column moves
neither. What the fix buys is not a pixel on this corpus — it is that a
narrow cell with text in it will now break where Hancom breaks it, and that
the 64 cells stop hiding the column question underneath themselves.

Worker: Opus; orchestrator: Fable.

### Not proven

- **Whether the floor is on the column or on the line box.** All 64 lines
  declare `margin_left`, `margin_right` and `intent` of zero, so the two are
  the same number in every observation. It is implemented on the column,
  which is the narrower claim: a paragraph whose own margins shrink a roomy
  cell's line box below 1440 is not widened, because nothing measured says
  it should be.
- **1440 is read off ten government forms and nothing else.** It is a
  constant with no public citation behind it here — what stands behind it is
  that four different columns are driven to it, that no cached in-cell line
  anywhere on the corpus is narrower, and that a cell 565 HWPUNIT wide still
  gets it. A document whose narrow cells were authored at a different zoom
  or unit could disprove it in one line.
- **Whether the floor applies outside a table cell** is untested. Every
  observation is in a `hp:tc`, and body columns on this corpus are never
  within an order of magnitude of 1440, so the corpus cannot say. It is
  applied only to cells.
- **The three indent cells are recorded, not fixed**, and the reading that
  would fix them is worth +35 line boxes over all 3214 — measured in #268,
  re-confirmed here from a second direction, and still a whole-corpus change
  rather than a cell one.
- **`stretch`, `firstrow`, `gridfirst` and `gridlast` each pick up 1
  regression against `global`** where they had 0 in #272. It is the same
  cell in all four — `saeopja` `r3c6`, a `colSpan=3` cell declaring 1062
  whose column was 500 and whose cache says 1440. The floor puts the
  renderer's own box on the grid there and the models that give it a
  different box stay off it. The cell was off the grid under every model
  before, so nothing regressed in fact; the baseline moved.
- **The corpus is the training set**, as it was for #268, #270 and #272 —
  the same ten forms, and the floor rests on 64 lines in 4 of them.
