# Holdout tracker 02 — the converged E2 tree

The private holdout is a report-class document (18 pages, body text, tables,
figures and equations) that has never been in the corpus and is not committed
here. **Aggregate numbers only.** Its content, filename, page images and any
excerpt of it stay out of this repository; nothing below identifies it beyond
its shape as a document.

Tracker 01 is the same document scored on the pre-convergence tree — the
numbers `own-render-notes.md` carries from the JUSTIFY stretch-box slice and
from the bundled-faces slice, which measured it and found no movement.

## What was scored

| | |
|---|---|
| Renderer | `rigorloom-own`, `claude/engine-e2-converge` — registration (#211) + bundled faces (#208) + inline-table move (#210) |
| Mode | `auto` line layout, `auto` block layout — the render as it ships |
| dpi | 144, against the document's own Hancom PDF |
| 1:1 | `reference_geometry_scale` 0.996 (declared median 10.00 pt, reference 9.96) — comparable |
| Verdict | passes every unratified threshold; grade stays `own-uncertified` |

## Tracker 01 → tracker 02

| channel | tracker 01 | tracker 02 | Δ |
|---|---|---|---|
| `page_count` | 18 / 18 exact | **18 / 18 exact** | — |
| `ssim_mean` | 0.7280 | **0.7457** | +0.0177 |
| `ssim_min` | 0.6264 | **0.6313** | +0.0049 |
| `ssim_inked_mean` | 0.1295 | **0.1731** | +0.0436 |
| `ssim_inked_min` | −0.0405 | **+0.0273** | +0.0678 |
| `text_line_iou_mean` | 0.5389 | **0.5847** | +0.0458 |
| `text_line_pair_rate_mean` | 0.9041 | **0.9122** | +0.0081 |
| `changed_channel_ratio_mean` | 0.1247 | **0.1215** | −0.0032 |
| `ink_delta_abs_max` | 0.0099 | **0.0095** | −0.0004 |

Every channel moves the right way, and `ssim_inked_min` crosses zero: there is
no longer a page on which our ink is anti-correlated with Hancom's.

## Which slice paid for it

**Registration (#211), essentially all of it.** The holdout's tables declare a
non-zero `hp:outMargin`, so every table box on every page moves by that inset
— which is exactly the channel `ssim_inked` and `text_line_iou` measure, and
exactly where the gain lands.

**Bundled faces (#208): a measured no-op, again.** The sidecar reports
`resolved_character_share` 1.0, `installed_character_share` 1.0,
`bundled_character_share` **0.0** — every face this document declares is
installed on the measuring machine, so `BundledFontMap` is never consulted.
This reproduces what tracker 01 found; the bundled tier is still untested by
this holdout.

**Inline-table move (#210): no repagination.** The page count is 18/18 before
and after. This document has no inline table that fails to fit its remaining
room, so the rule never fires on it. That is worth saying explicitly, because
the rule *did* cost the synthetic render-check document a page.

## Read honestly

- `ssim_inked_mean` at 0.17 is still low in absolute terms. The move is
  large *relative to tracker 01*, not close to fidelity. The remaining gap on
  this document is the line-metric one `own-render-notes.md` names as backlog:
  advance widths, and equation glyphs that are not math-italic.
- `text_line_pair_rate` barely moves (+0.008) because it was already 0.90 —
  registration moves lines that were already paired, it does not find new
  ones.
- One document, one machine, one Hancom build, one run.

## Not proven

- **Nothing here is a certification.** The thresholds this document passes are
  unratified, and passing them promotes no grade.
- **The slice attribution is by mechanism, not by ablation.** No tree with
  registration removed was rendered against this document; #208 is excluded by
  its own `bundled_character_share` of 0.0 and #210 by the unchanged page
  count, which leaves #211 — but that is an argument, not a fourth run.
- **The tracker-01 baseline is a re-quote, not a re-run.** Those numbers come
  from `own-render-notes.md`, measured on the pre-convergence tree at the same
  dpi and mode; the pre-convergence tree was not re-scored for this page.
- **Side-by-side page images were produced and reviewed locally** (pages 1, 5
  and 11, 96 dpi) and deliberately left out of the repository, as this
  document's content must be. What the review shows, described without
  quoting the document: table and equation boxes now sit on Hancom's own
  boxes, top edge and left edge together, which is the registration fix
  visible; the residual on every reviewed page is line-metric — our lines fit
  more characters, so paragraphs finish a line or two early and the bottom of
  each page carries whitespace Hancom does not have. Equation *content* still
  differs (upright where Hancom sets math-italic, and tighter sub/superscript
  placement), which is the backlog item this convergence does not touch.
