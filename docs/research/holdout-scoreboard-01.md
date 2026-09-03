# Holdout scoreboard 01 — private report-class regression run

One end-to-end measurement of the PRIVATE report-class holdout at renderer
tip `400c00df0c353fd641c0e55a279a1df2ab7ff4fa` (branch
`claude/engine-e2-sections`, 2026-09-04), run against `render_scoreboard.py`
and `own_render.py`'s agreement channels, per the recurring-tracker template.
The document itself is not in this repo, is not quoted here, and none of its
bytes, text, names, or page images left the local scratchpad. Only aggregate
numbers appear below — this is run 01 of what should become a recurring
series so a later run can diff against this one directly.

**Document** (aggregate facts only, matching the corpus figures already
published in `own-render-notes.md`): 18 pages, 415 scored multi-line-eligible
paragraphs / 485 total paragraphs, 27 tables / 240 cells, 11 pictures, 14
equations, one `hp:pageNum` control, one section, Batang body text — same
private holdout `own-render-notes.md` already cites in the "Report-class
documents" and "One holdout document" sections. Fonts: 100% of characters
resolved to an installed Batang face (`resolved_character_share` 1.0); no
substitution on this machine.

## 1. render_scoreboard, 144 dpi — auto vs computed, vs previously published

`auto` = shipped default (`--line-layout auto --block-layout auto`).
`computed` = full relayout (`--line-layout computed --block-layout computed`,
the channel that grades the E2.1 line breaker and E2.5 flow pass against
Hancom with none of the document's own cached geometry kept).

| metric | auto (this run) | computed (this run) | previously published |
| --- | --- | --- | --- |
| page count | **18 / 18 exact** | 21 / 18 — **not exact** | 18/18 exact |
| `ssim_mean` | 0.7289 | 0.6839 | — (n/a in cited PRs) |
| `ssim_min` | 0.6267 | 0.5365 | — |
| `ssim_inked_mean` | 0.1289 | 0.1200 | 0.1263 |
| `ssim_inked_min` | −0.0339 | 0.0221 | −0.0405 (last cited) |
| `text_line_iou_mean` | 0.5349 | 0.1797 | 0.5334 (last cited, PR #196) |
| `text_line_pair_rate_mean` | **0.9041** | 0.6057 | 0.9041 (PR #196) |
| `changed_channel_ratio_mean` | 0.1246 | 0.1431 | 0.1247 (last cited) |
| `ink_delta_abs_max` | 0.0099 | 0.0334 | 0.0099 (last cited) |
| regression-floor verdict | **pass** (6/6 checks) | **fail** (2/6: `page_count_exact`, `text_line_iou_mean`) | pass |

**Auto mode reproduces the published state almost exactly** —
`ssim_inked_mean` 0.1289 vs the 0.1263 last cited (both computed the same
way, small run-to-run drift is expected from block SSIM's sub-pixel
sensitivity, not a regression), and `text_line_pair_rate_mean` 0.9041 matches
the PR #196 figure bit-for-bit. Auto mode clears the regression floor cleanly.

**Computed mode is the headline finding of this run.** Relaying the whole
document out from the flow pass alone — no cached `hp:lineseg@vertpos`, no
cached page assignment — produces **21 pages instead of 18** and fails the
regression floor on two channels (`page_count_exact`, `text_line_iou_mean`
0.180 against a 0.20 floor). This was not visible in the previously-cited PR
numbers, which measured `auto` line-layout with `computed` *block* layout
only (see the flow-agreement table below) — this run is the first to score
`render_scoreboard` with both axes set to `computed` together on this
document.

## 2. Agreement channels (`own_render.py --lineseg-agreement` / `--flow-agreement`)

| channel | this run | previously published |
| --- | --- | --- |
| line-break positions matched | **71 / 260** | 71/260 |
| break-position recall | 0.2731 | — |
| break-sequence agreement (paragraphs) | 349 / 415 (0.8410) | — |
| conditional exact / early / late | 108 / 115 / 37 | 108/115/37 |
| `cached_line_fill` median | 0.9801 | — |
| flow-agreement, `line-layout=auto` — page assignment | **231 / 243** (0.9506) | 231/243 |
| flow-agreement, `line-layout=auto` — pages computed vs cached | 18 vs 18 | — |
| flow-agreement, `line-layout=computed` — page assignment | 48 / 243 (0.1975) | not previously run at this axis combination |
| flow-agreement, `line-layout=computed` — pages computed vs cached | 21 vs 18 | — |

The `line-layout=auto` flow-agreement channel — the one the cited PR numbers
were measured on — reproduces **231/243 exactly**, and the line-breaker's
`71/260` and `108/115/37` conditional split reproduce exactly too. Nothing
regressed on the channels that were previously measured. The
`line-layout=computed` flow-agreement run (not previously published for this
document) is where the divergence lives: page assignment agreement collapses
to 48/243 once the flow pass has no cached anchor to fall back to for a
paragraph whose line count it got wrong. `flow_counters` shows the
`line-layout=computed` run moves 2 tables whole and splits 1 across a page
boundary that the `line-layout=auto` run (1 table split, 0 moved) does not —
consistent with the extra 3 pages. The task's cited "late blocks 7/243" figure
is not a field either `--flow-agreement` output carries directly (it was a
derived count in the original PR analysis); the one directly comparable field,
`page_assignment_agreement`, reproduced exactly at 231/243, so nothing points
to a regression there.

## 3. `elements_skipped` tally (from the `own_render.py` render sidecar)

| element | auto mode count | computed mode count | reason (abridged) |
| --- | --- | --- | --- |
| `hp:stringParam` | 55 | 55 | no handler at this tier; nothing drawn |
| `hp:equation` | 14 | 14 | italic variable shaping not applied (regular/bold cuts only) |
| `hp:equation@equation_scaled` | 13 | 12 | laid out larger than declared `hp:sz`; scaled to fit |
| `hp:integerParam` | 11 | 11 | no handler; nothing drawn |
| `hp:parameters` | 11 | 11 | no handler; nothing drawn |
| `hp:tbl@repeatHeader` | 0 | 1 | table split across a page boundary does not repeat its header row |
| **distinct entries** | **5** | **6** | |
| **total skipped instances** | **104** | **104** | |

Auto mode's 5 distinct entries match the "5 distinct entries" state
`own-render-notes.md` already records for this document. Computed mode picks
up a 6th (`hp:tbl@repeatHeader`) purely as a side effect of the extra table
split caused by the page-count blowup in section 1 — it is not a new gap on
its own.

## 4. Worst two pages (auto mode, ranked by `ssim_inked`), mechanisms only

Ranked by `ssim_inked` (the metric that ignores blank paper and scores only
where either page has ink): page 11 (−0.0339, worst) and page 8 (−0.0013,
second worst). Both are body-text pages carrying prose paragraphs plus boxed,
numbered display equations — the two densest content types on this document.
Viewed side by side against the reference render at the same 144 dpi pixel
grid (candidate vs. Hancom-rasterized reference), three mechanisms account
for the gap on both pages:

1. **Full justification is not applied to body paragraphs.** The reference
   stretches interword (and, for Hangul, intercharacter) spacing so every
   full line's right edge lands flush on the paragraph's right margin — the
   ordinary behavior for Hancom body text. The candidate breaks lines at the
   same points (line-break agreement is high on these pages) but leaves the
   natural word-spacing in place, so lines end ragged short of the margin.
   Because this accumulates along every line rather than at one spot, it
   registers as a small positional disagreement on nearly every glyph in
   every paragraph — the single largest contributor to the low `ssim_inked` /
   `text_line_iou` on both pages, and the one a Hangul reader would notice
   first, since justified body text is the expected look for this document
   class.
2. **Equation glyphs render upright instead of math-italic.** The reference
   draws every equation glyph — variables and function names alike (e.g. a
   `clip(...)` call) — in a slanted math-italic cut. The candidate draws the
   same glyphs in the regular upright face. This is a declared, known gap:
   it is the exact reason `hp:equation` appears in the skipped-element tally
   ("italic variable shaping is not applied ... this renderer resolves
   regular and bold cuts only"). It changes the character shapes inside every
   equation box on both pages without moving anything's position, so it
   depresses `ssim_inked` inside each box without touching `text_line_iou`.
3. **Equation box double-rule border differs in stroke weight and offset.**
   Both renders draw the box border as two parallel strokes with a gap
   between them (the `DOUBLE_SLIM` mechanism already fixed elsewhere in this
   renderer) — but at the zoomed pixel level the candidate's two strokes sit
   closer together and roughly one pixel further from the box's declared
   text margin than the reference's. It is a minor, sub-pixel-registration
   effect next to (1) and (2), and it is the kind of difference the
   `ssim_inked_min` metric is known to punish disproportionately (see
   `own-render-notes.md`'s "Two numbers moved the wrong way" note on this
   same mechanism class).

No content is dropped or reordered on either page: every paragraph, box, and
caption that appears in the reference appears in the candidate at the same
page and in the same relative position; the gap is entirely in text-fill
style and glyph shaping inside otherwise well-placed structure.

## 5. Ranked: what a Hangul reader would notice first

1. **Ragged-right body text where the source is justified.** The most
   visually loud difference on every prose page — Korean report readers
   expect flush-right justified paragraphs, and its absence is visible at a
   glance without reading a word.
2. **Non-italic equation variables/functions.** Noticeable to anyone who
   looks at the equations at all, but confined to 14 equations across the
   document rather than every line of prose.
3. **Equation-box border weight/offset.** The least noticeable of the three —
   both renders draw a visibly double-ruled box in roughly the right place;
   only close side-by-side inspection reveals the stroke spacing differs.
4. **Nothing structural.** Page count, paragraph order, table layout, and
   caption placement all match the reference in auto mode (the mode this
   renderer ships); a reader skimming page-by-page would not notice anything
   missing or out of place, only that the typesetting looks slightly less
   "finished" than Hancom's own output.

## Reproduction

```
python engine/scripts/render_scoreboard.py FORM.hwpx REFERENCE.pdf \
  --out OUT --dpi 144 --line-layout auto --block-layout auto --save-pages
python engine/scripts/render_scoreboard.py FORM.hwpx REFERENCE.pdf \
  --out OUT --dpi 144 --line-layout computed --block-layout computed --save-pages
python engine/scripts/own_render.py FORM.hwpx --lineseg-agreement --dpi 144
python engine/scripts/own_render.py FORM.hwpx --flow-agreement --dpi 144 --line-layout auto
python engine/scripts/own_render.py FORM.hwpx --flow-agreement --dpi 144 --line-layout computed
python engine/scripts/own_render.py FORM.hwpx --out-dir OUT --dpi 144   # for elements_skipped
```

Renderer under test: `rigorloom-own/0.1`, `own_render` renderer_version
`0.1.0`, at commit `400c00df0c353fd641c0e55a279a1df2ab7ff4fa`. All renders and
scoreboard JSON for this run live under the local scratchpad
(`holdout-01/`), not in this repo.
