# Visual rubric — reading a rendered page image

The rubric an agent applies when LOOKING at a rendered page PNG. It is the
vision half of `pipeline/scripts/visual_verify.py`; the machine half runs
first and always, and hands over a `vision_required` list of page indices,
PNG paths, and a pointer to this file.

**Scope.** One page image at a time, 130 dpi, rendered by fitz from the same
PDF the deterministic half measured. You are judging the RENDER, not the
prose. Content quality, tone, factual accuracy, and Korean style are out of
scope — other gates own those.

**Class vocabulary is closed.** `visual_verify --vision-verdict` validates
every finding's `class` against the table below. An unknown class is a usage
error (exit 2), not a finding. Do not invent classes; if what you see fits
nothing here, report it under `evidence` of the nearest class and say so, or
raise it as a rubric gap (see §4).

**Severity is fixed per class** (column `sev`), except where the class says
otherwise. Do not downgrade a `hard` because it "looks minor".

## 1. Class table

| class | sev | deterministic coverage |
|---|---|---|
| `blank_render` | hard | FULL — `visual_verify` (zero-text document, zero-content page) |
| `artifact_malformed` | hard | FULL — `visual_verify` XML parse; also `check_residue` |
| `imposition_mismatch` | hard | FULL — stored `PrintMethod != 0` + doc/PDF page parity |
| `page_budget_violation` | hard | FULL — declared budget vs PDF page count |
| `guide_text_visible` | hard | PARTIAL — `layout_qa` body_markers + `check_residue` |
| `empty_cell_expected_fill` | hard | PARTIAL — fill-map value absent from PDF text |
| `format_noncompliance` | hard | PARTIAL — measured pt/spacing vs declared; **script/scale/offset inheritance on fill-modified runs (`fill_charpr_script_mismatch`) is FULL** |
| `overprint` | hard | NONE (targeting only — glyph-bbox overlap ratio) |
| `text_clipped` | hard | NONE |
| `alignment_drift` | warn | NONE |
| `orphan_widow` | warn | PARTIAL — `layout_qa` caption/figure rules only |
| `figure_overlap` | warn | FULL — `layout_qa` figure_placement |

"FULL" means the machine half already HARDs on it and your job is only to
corroborate or to catch a variant the mechanism cannot see. "NONE" means the
verdict is yours; nothing else in the system can see it.

## 2. Per class

### `blank_render` (hard)
**Looks like:** an entirely white page, or a page carrying only the form's
ruled lines/borders with no glyphs anywhere.
**NOT:** a designed cover page with a small centered title block; a
deliberately blank continuation sheet declared in `expectations.blank_pages`;
a page whose only content is a figure (raster) with no text.
**Deterministic:** `visual_verify` HARDs when document text length is 0
(T25 floor) or a page has zero text blocks AND zero image blocks. Your added
value: a page that has *some* stray text but is substantively empty.

### `artifact_malformed` (hard)
**Looks like:** a render that is blank or truncated because the source
`.hwpx` member did not parse — usually the whole document collapses.
**NOT:** a short document.
**Deterministic:** FULL. `visual_verify` XML-parses every
`Contents/section*.xml` + `Contents/header.xml` before rendering; a
`ParseError` is HARD and the render is reported as untrusted. You will rarely
be asked for this class — report it only if the machine half missed the
member (a rubric gap worth naming).

### `imposition_mismatch` (hard)
**Looks like:** a landscape page containing two full portrait pages side by
side (n-up 모아찍기), or a rendered page count lower than the document's.
**NOT:** a genuinely landscape-designed form (a wide table form); a document
whose sections legitimately change orientation.
**Discriminator:** an imposed sheet shows TWO separate page frames with their
own margins and (if present) two page numbers. A native landscape page has
one frame.
**Deterministic:** FULL — the source's stored `PrintInfo/PrintMethod != 0`
and/or `pages_document != pages_pdf`. Report it in vision only when the
machine half could not read the source (`.hwp` input, no expectations).

### `page_budget_violation` (hard)
**Looks like:** nothing on a single page — this is a document-level class.
**Deterministic:** FULL. Report it in vision only when the last page is
substantively empty and therefore should not count against a "at least N
pages" floor (that judgment IS yours: say whether the final page carries real
content).

### `guide_text_visible` (hard)
**Looks like:** the form's own instruction prose still printed in the filled
artifact — "…을 작성하세요", "여기에 입력", "예시)", bracketed 【안내】 blocks,
grey/blue/red italic instruction runs, a placeholder token like `OOO` or
`____` that was supposed to be replaced.
**NOT:** a label ("성명", "소속") — labels legitimately survive a form fill;
a legally required notice printed in the blank form for the reader (e.g. a
personal-information consent paragraph); an example that the form prints in a
separate boxed 예시 section the filler is not meant to remove.
**Discriminator:** guide text tells the FILLER what to do; notice text tells
the READER something. If removing it would change what the recipient agency
reads, it is not guide text.
**Deterministic:** PARTIAL — regex/inventory based, so it misses guide text
that is an image, is worded outside the pattern set, or lives in a form the
scan never profiled. Vision is the backstop for exactly those.

### `empty_cell_expected_fill` (hard)
**Looks like:** a table cell or form field that is blank where the
surrounding rows are filled, or where `expectations.fill_map` declared a
value for that label.
**NOT:** a signature cell (`(서명 또는 인)`, 인, 서명) — those stay blank by
contract; a staff-only / 접수란 / 처리기관 cell (usually shaded darker, and
many forms print "색상이 어두운 칸은 작성하지 않습니다"); a
not-applicable row the filler correctly left empty; a cell the form marks
「해당자만」.
**Discriminator:** shading. Darker cell = office use = intentionally blank.
Read the form's own instruction line if it is visible on the page.
**Declared blanks are not findings.** The machine half suppresses this class
for a cell the grid owns (a separator band or a matrix stub head — the same
`spacer` shapes `form_inspect` reports) and for a seat listed in
`declared_blank`; both are recorded under
`deterministic.layout_qa.empty_cell_suppressed`. What survives names the seat
by its LABEL. If you are about to report this class from the page image for a
cell that is blank by design, add it to `declared_blank` instead — a warning
every correct run emits is a warning nobody reads.
**Deterministic:** PARTIAL — `visual_verify` checks that each declared
`fill_map` value string appears in the page text, which catches a dropped
value but cannot tell an unfilled cell from an intentionally blank one, and
cannot see a cell that has no declared value.

### `format_noncompliance` (hard)
**Looks like:** body text visibly larger/smaller than the rest of the
document; line spacing visibly tighter or looser than the declared value;
body text running into the margin or starting far inside it.
**NOT:** headings, captions, table text, footnotes, or the cover title —
those have their own sizes; a form-owned label whose size the form fixed
(T9: form paragraphs keep their designed 180–200% spacing, body is 160%).
**Deterministic:** PARTIAL — `visual_verify` compares the page's median span
size against `expectations.base_pt` (± tolerance) and the median line pitch
against `expectations.line_spacing_pct`. Medians hide a single wrong
paragraph; that one is yours.

**Newly deterministic — invisible superscript inheritance (T30).** A filled
value can inherit a charPr that is identical to body text *except* for a
`<hh:supscript/>` / `<hh:subscript/>` child or a shrunken
`<hh:ratio>`/`<hh:relSz>`/`<hh:offset>`: nominal height stays 10pt, so
`charpr_check --base-pt 10` and `style_diff` both pass it, while Hancom
renders the value at ~6.35pt raised off the baseline. `visual_verify` now
compares the script/scale/offset profile of every **fill-modified** run
(a run whose text carries a declared `expectations.fill_map` value) against
the document's body-baseline charPr and HARDs on any difference as
`fill_charpr_script_mismatch`, class `format_noncompliance`, detector
`visual_verify.fill_charpr_script`. The check is scoped to fill-modified
runs on purpose: an intentionally superscripted footnote marker, ordinal, or
unit exponent is untouched by a fill and is never flagged. Your added value
is unchanged — a wrong size on a run the fill map never declared.

### `overprint` (hard) — the T24 class
**Looks like:** glyphs drawn on top of glyphs. Two texts sharing the same
band, letters interleaved into unreadable soup, a long title printed across a
shorter placeholder's old layout, or the same line drawn twice at a small
offset (ghosting).
**NOT:** a watermark or 직인/도장 image behind text (a uniform, low-contrast,
usually rotated graphic — deliberate); a strikethrough, underline, or
highlight; a superscript/subscript touching its base; an equation whose
fraction bar sits close to a body line; text over a light table fill.
**Discriminator:** overprint makes text UNREADABLE at the collision. If both
texts are individually readable and one is clearly a background element, it
is not overprint.
**Cause to name in `evidence` when it fits:** stale `<hp:linesegarray>`
retained on a paragraph whose text was replaced with longer text — Hancom
draws the new text at the old cached coordinates (T24).
**Deterministic:** NONE. `visual_verify` computes a glyph-bbox overlap ratio
per page and uses it ONLY to rank the page into `vision_required` with
`reason: overprint_suspected`. It never emits the class itself, because
overlap ratio false-positives on every case in the NOT list.

### `text_clipped` (hard)
**Looks like:** a glyph cut mid-stroke by a cell border, frame edge, or page
edge; a line whose last characters are sheared off; text that visibly
continues under a table rule; a value truncated with no ellipsis.
**NOT:** an intentional ellipsis (…); a hyphenated line break; text that ends
flush against a border with a normal side bearing (tight but whole); a
Korean line break inside a cell (wrapping is not clipping).
**Discriminator:** look for a PARTIAL glyph. Whole glyphs sitting close to a
border are fine; half a 글 is not.
**Deterministic:** NONE — fitz reports the text logically present regardless
of whether the render clipped it, so extracted text length cannot see this.

### `alignment_drift` (warn)
**Looks like:** baselines in the same row of a table sitting at different
heights; a column of values whose left edges wander; a heading indented
differently from its siblings; a numbered list whose numbers do not line up;
body paragraphs with two different left margins.
**NOT:** an intentional hanging indent; a centered cell next to a
left-aligned cell where the form designed it that way; the T10 case only if
the form itself centers that label; a right-aligned numeric column (correct);
different indentation across different heading LEVELS.
**Discriminator:** compare against the same element type elsewhere on the
page. Drift is inconsistency within a class, not variety across classes.
**Severity note:** `warn` by default. Escalate to `hard` in `severity` only
when the drift makes a table row unreadable or crosses a cell boundary.
**Deterministic:** NONE.

### `orphan_widow` (warn)
**Looks like:** a heading alone at the bottom of a page with its body on the
next (T11); a single last line of a paragraph alone at the top of a page; a
table caption at page bottom with the table overleaf (T12); one row of a
table stranded on its own page.
**NOT:** a section that legitimately starts at the bottom of a page with two
or more lines following; a cover/summary page that ends early by design; the
last page of the document.
**Deterministic:** PARTIAL — `layout_qa`'s `figure_placement.caption_missing`
and the keep-with-next build config cover the figure/table-caption variants;
the heading-orphan and single-line-widow variants are vision-only.

### `figure_overlap` (warn)
**Looks like:** an image bbox intersecting body text.
**NOT:** a figure with a caption directly beneath it; text wrapping around a
figure where the form designed a wrap.
**Deterministic:** FULL — `layout_qa` `figure_placement.figure_overlap`.
Corroborate only.

## 3. Reporting format

`visual_verify --vision-verdict FILE` expects:

```json
{
  "schema": "rigorloom/visual-vision-verdict/v1",
  "rubric": "skill/references/visual-rubric.md",
  "pages_reviewed": [1, 2, 3],
  "findings": [
    {"page": 2, "class": "overprint", "severity": "hard",
     "evidence": "title band y~120px: two text layers interleaved, unreadable; long title drawn over shorter placeholder layout (stale lineseg)"}
  ]
}
```

Rules:
- `pages_reviewed` MUST include every page the machine half listed in
  `vision_required`. A missing page is `vision_incomplete` (hard) — the
  vision half is not skippable.
- No findings on a reviewed page = that page is clean. Do not emit
  "everything looks fine" entries.
- `evidence` is what you SAW and where (band, cell, coordinates in image
  pixels). Not what you infer about the pipeline, unless the cause is one of
  the named T-rows.
- One finding per defect instance, not per glyph.

## 4. Rubric gaps

If a real defect fits no class, do NOT stretch a class to cover it. Record it
in the run log and open a rubric gap: name the incident, the page, and what a
new class would have to observe. A rubric that quietly absorbs everything
stops discriminating.

Known gaps as of v0.17:

- **Colour fidelity.** Nothing in the rubric judges whether a run is the
  right colour (guide-blue left black-ish, 빨강 not normalized). `charpr_check`
  / `style_diff` own that offline; vision at 130 dpi is not the instrument.
- **Font FACE substitution.** A missing font silently substituted by the
  renderer looks fine at 130 dpi. Out of scope; the offline charPr proofs are
  the mechanism.
- **Overprint at equation scale.** T13-class script-scope errors are
  invisible at 130 dpi; they need a 300 dpi crop of the equation. The rubric
  deliberately does not claim to catch them — `visual_verify --dpi 300` on
  the equation page is a separate, operator-triggered run.
