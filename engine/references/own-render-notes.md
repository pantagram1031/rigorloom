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

The embedded preview is there so a human can judge the gap at a glance. It is
a comparison aid, not a measurement — the measurement is `render_cert`.

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

So border **parsing** is not the refinement target. Against the embedded
preview the real gaps on this form are, in order: `발 신 명 의` renders tight
where the authoring engine spreads it (character spacing, limit 2 below), and
every line runs wider than the original because of the font substitution
(limit 1). Both are intra-line text metrics, not table geometry.

**Text runs.** Per-run `hh:charPr`: `@height` (÷100 → pt), `@textColor`,
`hh:bold`, and `hh:underline@type`. Underline is drawn because ruled blanks in
government forms *are* underline runs — `form_inspect._is_ruled` and T112 both
treat them as load-bearing.

**Inline vs anchored objects.** `hp:pos@treatAsChar="1"` objects are laid out
*inside* the line (they consume width and participate in alignment); anything
else is placed from `@horzOffset`/`@vertOffset` against the frame
`@horzRelTo`/`@vertRelTo` names. Getting this wrong is visible: gianmun's
발신명의 box sat at the left margin instead of centred, and the 직인 box sat on
top of it, until inline objects joined the line.

## Named fidelity limits

Each of these is reported in the sidecar's `elements_skipped` at render time,
not only here.

1. **Fonts.** No Pretendard is vendored in this repo and none was found in a
   sidecar path, so every HWP face in a document (돋움, 바탕, 함초롬돋움,
   한양신명조, …) is rasterised with **Malgun Gothic**
   (`C:\Windows\Fonts\malgun.ttf`, bold `malgunbd.ttf`). Advance widths
   therefore differ from the authoring engine's. Line *boxes* do not drift
   (they come from the cache) but text *within* a line does, and a centred or
   right-aligned line drifts by half or all of the accumulated difference.
   Override with `RIGORLOOM_OWN_RENDER_FONT` / `…_FONT_BOLD`.
2. **Character-level typography is not applied.** `hh:ratio` (horizontal glyph
   scaling), `hh:spacing` (letter spacing, ±%), `hh:relSz`, `hh:offset`
   (super/subscript displacement) are parsed by neither this renderer nor drawn.
   Visible consequence: gianmun's `발신명의` renders tight where the authoring
   engine spreads it across its box.
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
    fonts or a different FreeType build will differ.

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

Suggested order of work:

1. vector PDF text output (unlocks the word-anchor channel);
2. character-level typography (`ratio`/`spacing`), the largest remaining source
   of intra-line drift once fonts are pinned;
3. a vendored font with known metrics, so cross-machine determinism becomes
   claimable;
4. equations and pictures, in that order — equations are the harder and the
   more load-bearing for report documents;
5. only then ask `render_cert` for a per-document-class grade. Until it
   answers, the grade stays `own-uncertified`.
