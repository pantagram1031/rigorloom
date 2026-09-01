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

**Line layout — read the file's own cache, do not re-derive it.** This is the
single largest fidelity decision in the slice.
`<hp:linesegarray><hp:lineseg …/>` carries the line boxes the authoring engine
already computed: `vertpos`, `horzpos`, `horzsize`, `vertsize`, `baseline`, and
`textpos` (the paragraph character offset the line starts at). The renderer
slices the paragraph's character stream by `textpos` and draws each line at its
cached box. Line breaking therefore matches the authoring engine exactly
wherever the cache is present and consistent.

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
3. **Equations and pictures are placeholders.** `hp:equation`, `hp:pic`,
   `hp:ole`, `hp:chart`, `hp:container` and the drawing shapes get a grey
   outlined box labelled 수식 / 그림 / 도형. When the element declares `hp:sz`
   the box is at the declared extent; when it does not, the box is a fallback
   size and the label carries a `?` and the sidecar says
   `UNKNOWN extent`. **No corpus form contains an `hp:equation`** — verified by
   scanning every `Contents/section*.xml` in `tests/corpus/forms/converted/`;
   the equation path is therefore pinned by a direct unit test rather than a
   document fixture.
4. **Non-solid borders are stroked as solid.** `DASH`, `DOUBLE_SLIM`, `CIRCLE`
   appear in the corpus and are drawn as a solid line of the declared width,
   named per side in the sidecar.
5. **Tabs are not resolved.** `hp:tab` inside a run advances nothing; the
   cached line box absorbs it. Where a form uses tabs to build a column, that
   column collapses.
6. **Text does not wrap around anchored objects.** They are drawn at their
   declared offset, over whatever is there.
7. **Multi-column text (`hp:colPr`) is ignored** — PARA and COLUMN both resolve
   to the paragraph's container.
8. **Only `section0` is laid out.** No corpus form has more, but the sidecar
   says so when one does.
9. **Headers, footers, footnotes, endnotes and master pages are not drawn.**
10. **Row heights are approximate where the content extent is.** Eight of 81
    corpus tables miss their declared height by more than 2% before the
    residual is redistributed; the redistribution keeps the outer box exact but
    shifts interior rows. Visible on `saeopja` as two colliding rows.
11. **Cross-machine byte equality is not claimed.** Same input → same PNG bytes
    on one machine and one Pillow build (pinned by test). Different installed
    fonts or a different FreeType build will differ — and since face resolution
    now reads the machine's font directory, *which* faces are installed is a
    first-class input, not a footnote.
12. **`kstartup-jiwon-sincheongseo-saeopgyehoekseo` paginates wrong.** It is
    the one comparable form whose rendered page count does not match its
    Hancom reference, so it fails the regression floor's `page_count_exact`
    check today. A pagination defect, not a typography one; unfixed.

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
2. Vector PDF text output — unlocks `render_cert`'s word-anchor channel and
   with it the actual certificate.
3. Sub-pixel glyph registration: the largest remaining term, per `ssim_inked`.
4. A vendored font with known metrics, so cross-machine determinism becomes
   claimable and the scoreboard stops depending on which faces this machine has.
5. `kstartup` pagination (limit 12).
6. Equations and pictures, in that order.
7. Only then ask `render_cert` for a per-document-class grade. Until it
   answers, the grade stays `own-uncertified`.
