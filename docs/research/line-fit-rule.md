# What rule keeps a line on the page past the usable body box

Verification-slot research, measurement only. No renderer code changed.
Worktree `docs/research-line-fit` off `claude/engine-e2-reflow` (7b04653).
Scope: the 10 public corpus forms (`tests/corpus/forms/converted/*.hwpx`,
`tests/corpus/forms/render/*.pdf`), cross-referenced against the flow-pass
section of `engine/references/own-render-notes.md` and the fit test in
`engine/scripts/own_render.py`. The private holdout named there was **not**
opened; its 54/243 late blocks are cited only as the target this predicate is
meant to move.

## Method

For every page of every corpus form: `page_geometry()`'s formula
(`usable_height = height − top − bottom − header − footer`) and
`paginate()`'s vertpos-restart heuristic were re-implemented directly against
`Contents/section0.xml` (stdlib XML, no Pillow/font dependency — see
`measure_line_fit.py`, kept under the scratchpad). For each page, the
**deepest cached `hp:lineseg`** (max `vertpos + vertsize`) was taken as "the
last line," matching the exact convention `own-render-notes.md`'s existing
fill table already uses ("ignoring the trailing spacing"). Its `vertpos`,
`vertsize`, `textheight`, `baseline`, `spacing` were read straight off the
XML attribute. Independently, PyMuPDF opened the matching reference PDF page
and found the lowest non-blank text line's bbox, to compare against the
page's bottom-margin position converted to points (`HWPUNIT / 100`).

`gianmun-byeolji-1ho`, `gianmun-byeolji-2ho` and `nrf-gyeolgwa-bogoseo-yangsik`
are the three reference PDFs `own-render-notes.md` already documents as
non-1:1 print reductions (~0.707 scale, top-left anchored); their PDF ink
positions are reported but excluded from the aggregate ink-distance stats
below, same as the existing scoreboard's own treatment.

## The four overfull pages

Reproduced exactly against `own-render-notes.md`'s fill table (three
documents, not four — the fourth entry in that table's "four documents" count
is the private holdout, not a corpus form; the number that **is** corpus and
matches verbatim is the max fill **1.068**):

| document | page | fill (vertpos+vertsize)/usable | fill_baseline | PDF ink dist to bottom margin | ref PDF reliable? |
| --- | --- | --- | --- | --- | --- |
| moel-pyojun-geunrogyeyakseo-2013 | 5 | **1.0680** | 0.9078 | **−42.29 pt** (ink past margin) | yes |
| moel-pyojun-geunrogyeyakseo-2013 | 6 | 1.0551 | 0.8968 | **−34.09 pt** (ink past margin) | yes |
| saeopja-deungnok-sinchengseo | 1 | 1.0172 | 0.8646 | **−10.07 pt** (ink past margin) | yes |
| nrf-gyeolgwa-bogoseo-yangsik | 0 | 1.0251 | 1.0218 | +285.5 pt (not evidence either way) | **no** — 0.707-scale reference |

All 47 other measured pages have `fill (vertpos+vertsize)/usable ≤ 1.0`.

**What the three moel/saeopja lines actually are**, checked against the raw
XML: each is a *single-lineseg paragraph containing an inline
(`treatAsChar="1"`) table* whose own height (74535 / 73634 / 76989 HWPUNIT)
exceeds `usable_height` (69788 / 75686 HWPUNIT) **by itself**, before any
question of margins or spacing arises — the block is taller than the page.
`_place_block`'s `cursor > 0` guard already never pushes a block's own first
row for exactly this reason ("a block taller than a page splits wherever it
is put" — the docstring at `own_render.py:1814`), so this case does not
currently trigger a refusal at all; it is cited here because it is what the
notes' fill table flags, not because it is the mechanism the holdout's 54
late blocks come from.

`nrf`'s case is a different degenerate: its deepest lineseg (`vertpos=71630`,
`vertsize=1600`) belongs to an **empty paragraph** (no `<hp:t>` text) whose
own `vertpos` is already past `usable_height=71436` before `vertsize` is even
added. No box-portion rule can rescue a box whose *top* is already outside —
and it does not need rescuing, because an empty line draws no ink. (Its
reference PDF is also the unreliable 0.707-scale one, so its "distance"
number above is not real evidence.)

Neither of the two mechanisms behind the four corpus pages is "a normal
prose line whose descender/spacing hangs a little past the margin" — the
corpus simply does not contain a clean instance of that. The candidate rules
below are tested against these four pages anyway, because they are the only
public ground truth available, with the caveat stated plainly.

## Candidate rules, pages consistent / total (51 pages, 10 forms)

| rule | predicate | pages consistent |
| --- | --- | --- |
| (a) baseline inside | `vertpos + baseline ≤ usable` | **50 / 51** |
| (b) textheight inside | `vertpos + textheight ≤ usable` | 47 / 51 |
| (c) vertpos+textheight, spacing may hang | `vertpos + textheight ≤ usable` | 47 / 51 |
| (d) drop last line's spacing tail | `vertpos + vertsize ≤ usable` | 47 / 51 |
| (e) descender may cross margin | `vertpos + baseline ≤ usable` | **50 / 51** |

(b), (c) and (d) collapse to one predicate here: `vertsize == textheight` on
every corpus lineseg (the 3214/3214 relation `own-render-notes.md` already
measured), and "the last line's own trailing spacing" is already excluded by
construction — this is also the *existing* extent used both by
`extent_hwp()` and by `_rows_that_fit`'s per-row `extent`. It is what the
flow pass already enforces, and it is exactly the rule the four overfull
pages fail.

(a) and (e) also collapse to one predicate: `baseline` already *is* "ascent
only, descender excluded," which is what "descender may cross the margin"
means operationally — there is no separate descender constant recorded per
line, only `baseline = round(0.85 × textheight)` (measured on 3212/3214
corpus linesegs). Baseline-inside resolves **3 of the 4** overfull pages
(both moel-2013 pages, saeopja) and is corroborated by real ink: on the two
pages with a reliable reference PDF, Hancom's own render draws ink 34–42pt
*past* the declared bottom margin — direct black-box confirmation that
Hancom does not stop at `vertpos + vertsize`, and that relaxing to baseline
does not admit anything Hancom itself refused. It does **not** resolve
`nrf` — but `nrf`'s failure is the empty-line case above, orthogonal to
which box-portion counts.

**No single box-portion rule explains all four** at zero cost: none can, a
box whose top is already past the boundary is unrescuable by shrinking what
counts of the box. What baseline gets right is the only case that generalizes
— an actual text line, not a degenerate empty paragraph or an unsplittable
block — which is the shape the private holdout's 54 late blocks are reported
to be (report-class prose, not corpus-style forms).

## Where the reference PDF's last-line ink actually sits (unscaled refs, n=45)

| | value |
| --- | --- |
| median distance, ink bottom → bottom margin | **33.5 pt** |
| min distance (closest approach that still stays inside) | 4.2 pt (moel-2013 p0) |
| min signed distance overall (crosses margin) | **−42.3 pt** (moel-2013 p5) |

Typical pages carry ~34pt (roughly two line-heights) of slack before the
margin — Hancom is not routinely running pages to the edge. The one place it
is measured running past the edge is the unsplittable full-page inline table,
not a normal text line's spacing tail.

## The predicate to adopt

Replace the row-fit test's extent (`_rows_that_fit`'s `row["extent"]`,
currently `vertsize`) with `baseline`:

```
a line fits if  vertpos + baseline ≤ usable_height
baseline = cached hp:lineseg@baseline  (== round(0.85 × textheight) where absent)
```

This is a measured typographic constant already used elsewhere in this
renderer (`BASELINE_RATIO`), not a tolerance tuned to this corpus — it changes
the row-fit test from "the whole line box must clear the margin" to "the
descender may cross it," which is exactly what the two reliable-reference
overfull pages show Hancom itself doing. It resolves 3 of the 4 known corpus
overfull pages and every one of the 47 pages that already fit keeps fitting
(baseline ≤ vertsize always, so the change is strictly more permissive and
introduces no regression on this corpus). It does not, and should not, try to
rescue the unsplittable-block or empty-line cases — those already have
(or need only trivial) separate handling and are not "fit tolerance"
questions.

This is the predicate expected to close some share of the private holdout's
54/243 late blocks — a real multi-line prose paragraph near a page bottom is
the shape baseline-inside is built for, unlike the corpus's own two
degenerate cases. Confirming the exact count needs a run against the holdout,
which this task does not open.

## Files

- Measurement script (scratchpad, not committed):
  `measure_line_fit.py`, `line_fit_measurements.json`
- Read for this research: `engine/references/own-render-notes.md` (lines
  1–19, "Block layout and page reflow (E2.5)" section), `engine/scripts/own_render.py`
  (`page_geometry`, `paginate`, `Paragraph.extent_hwp`, `_rows_that_fit`,
  `_place_block`, `_line_metrics`), `engine/references/own-render-samples/e2.5-flow-agreement.json`
