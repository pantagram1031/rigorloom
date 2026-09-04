# Round-trip render check — does a Hancom-saved candidate still render the same?

2026-09-05, writer worktree `claude/engine-e3-roundtrip-render` off HEAD
`fb8ab4f` (`claude/engine-e3-accept-02`). Renderer tip pinned at
`origin/claude/engine-e2-dpi-independence` (`own_render.py`,
`render_check.py`, `render_scoreboard.py`, `hwpeqn_parse.py` fetched
read-only into the scratchpad and run there; not merged into the writer
line). Reference: `tests/corpus/render-check/render-check-01.{pdf,blocks.json}`
from the same renderer tip. Source document: the unmodified,
Rigorloom-authored 51-feature `render-check-01.hwpx`
(`origin/claude/engine-e2-converge-3`, same file `hancom-acceptance-02.md`
run 02 used).

Question: after Hancom opens and saves our authored document, does it still
render the same against the pinned reference PDF?

## Method

The run-02 rerun's saved candidate (`engine/references/acceptance/run-02/render-check-01.rerun.json`)
no longer exists on disk — its path was under a prior session's scratchpad,
which is deleted after each session. It was regenerated once: the same
first-`<hp:t>` marker-planting step run 02 used (this run's marker,
`RIGORLOOM-E3-ROUNDTRIP-RENDER-01`, appended inside the header control's
`<hp:t>` text in `Contents/section0.xml` — confirmed by run 02 to be the
`hp:header` control's own paragraph, not body flow), `hwpx_lint.py
--section-order` clean, `Hwp.exe` confirmed absent via `tasklist` immediately
before and immediately after, single serial COM session via
`engine/scripts/hwpx_accept.py`. Verdict: 7/7 checks pass (`edit_preserved`
found the marker as `kind: "header"`; body structure 6 tbl/227 p/111 tc
unchanged), reproducing run 02's result exactly.

Both the pre-Hancom edited source and the Hancom-saved candidate were then
rendered with the renderer tip's `own_render` (96 dpi, matching
`render_check.py`'s `DEFAULT_DPI`) and scored with `render_check.py` against
the same pinned `render-check-01.pdf`/`.blocks.json`.

## (1) Per-feature verdict comparison

| | match | close | differs | unsupported |
|---|---|---|---|---|
| Original (pre-Hancom, marker planted) | 6 | 37 | 6 | 2 |
| Hancom-saved candidate | 6 | 37 | 6 | 2 |

Aggregate tally is identical and matches the baseline. Page count matches
too (9/9, exact page agreement on both sides).

**Feature-by-feature: 0 of 51 verdicts changed.** Every feature's bucket
(`match`/`close`/`differs`/`unsupported`) is exactly the same before and
after the Hancom round trip — not just the same totals by coincidence.

Sub-threshold score drift (same verdict bucket, but not byte-identical
scores) was checked across all 51 features. The verdict itself is gated on
whole-crop `ssim` + `iou` + `ink_delta` (`match`: ssim≥0.90, iou≥0.55,
|ink_delta|≤0.01; `close`: ssim≥0.65, iou≥0.30, |ink_delta|≤0.025 at 96 dpi
— `render_check.py`'s `THRESHOLDS`); `ssim_inked` is reported as a
diagnostic only (`thresholds.reported_not_gated`), so it is used below only
to flag which crops moved, not to re-derive the verdict:

- **F50 "머리말 (header)"** — the largest `ssim_inked` delta (0.502 → 0.062),
  gating `ssim` also moved (0.965 → 0.851) but `iou` stayed the deciding
  factor (0.196 → 0.059, both well under `close`'s 0.30 floor), verdict
  `differs` in both. This is **not** a roundtrip effect: it's exactly the
  block we deliberately appended the edit marker text to, so the candidate
  legitimately carries more header ink than the original at this location.
  Expected, not evidence of Hancom altering rendering.
- **F44 "하이퍼링크 (hyperlink field)"** — gating `ssim` 0.885→0.899, `iou`
  0.534→0.587, `ink_delta` 0.022→0.018: all three still comfortably inside
  `close`'s band, verdict `close` in both.
- **F19 "밑줄 (underline)"** — gating `ssim` 0.837→0.846, `iou`
  0.530→0.586, `ink_delta` 0.020→0.015: same, verdict `close` in both.
- All other 48 features: delta 0 or negligible, verdict unchanged.

F44 and F19 are plausibly explained by cause (2) below: `hh:charPr`/
`hh:fontRef`/`hh:underline` counts all shifted −3 in Hancom's style-catalog
consolidation, consistent with charPr-id remapping perturbing underline/
hyperlink run styling slightly — but the shift moved both features' gating
metrics *away* from their bucket boundary, not toward it, so neither came
close to flipping.

No feature whose verdict changed → nothing to root-cause on that axis.
`outMargin`/lineseg caches: see (2) — neither package carries any, so they
cannot be the explanation for the (zero) verdict changes here.

## (2) Lexical HWPX diff

**Member list** (13 → 14 members):
- Only in source: `BinData/image1.png`
- Only in candidate: `BinData/image1.PNG` (case-renamed on save),
  `Preview/PrvImage.png` (Hancom-generated thumbnail, absent from our
  writer's output)

**Per-member qname count delta** (candidate − source), non-zero only:

- `Contents/header.xml` — same two clusters run 02 found: **removed**
  `hh:paraHead` −11, `hh:heading`/`hh:border`/`hh:breakSetting`/`hh:paraPr`/
  `hh:align` −5 each, `hh:charPr`/`hh:fontRef`/`hh:offset`/`hh:outline`/
  `hh:ratio`/`hh:relSz`/`hh:shadow`/`hh:spacing`/`hh:strikeout`/
  `hh:underline` −3 each, `hh:bullet`/`hh:bullets`/`hh:img`/`hh:numbering`/
  `hh:numberings` −1 each; **added** `hc:intent`/`hc:left`/`hc:right`/
  `hc:next`/`hc:prev`/`hh:margin`/`hh:lineSpacing` +14 each, `hp:default`/
  `hp:switch`/`hp:case`/`hh:autoSpacing` +19 each, `hh:font`/`hh:typeInfo`
  +7 each, `hh:trackchageConfig` +1. Reproduces run 02's finding: this is
  Hancom de-duplicating/consolidating the style-reference catalog, not the
  body.
- `Contents/section0.xml` — `hp:t` +12, `hp:stringParam` +4, `hp:run` −7,
  `hp:autoNumFormat` +1, `hp:integerParam` +1 (the marker edit itself splits
  one run into more `hp:t`/`hp:run` nodes; auto-number/field plumbing
  Hancom normalizes on save).
- `Contents/section1.xml`, `Contents/section2.xml` — `hp:autoNumFormat` +1
  each only.
- `Contents/content.hpf` — `opf:meta` +5 (metadata, e.g. modified timestamp).

Body/paragraph/table counts (`hp:tbl`/`hp:p`/`hp:tc`) are unchanged
everywhere, confirmed independently of `hwpx_accept.py`'s own check.

**`hp:lineseg` cache — Hancom did NOT add one.** An exhaustive
`iter_local("lineseg")` scan of every `Contents/section*.xml` in both
packages found **zero `hp:lineseg` elements in the source and zero in the
Hancom-saved candidate.** Our writer never emits a cached line-layout, and
Hancom's resave doesn't add one either — for this document, `own_render`'s
`auto` mode has no cache to prefer on either side, so both renders take the
identical CJK-aware greedy-wrap fallback path. That is very likely *why*
the per-feature verdict table is unchanged: there is no cache-vs-no-cache
asymmetry for the renderer to trip on.

## Not proven

- That Hancom never adds `hp:lineseg` on save for *any* document — only
  shown for this 51-feature corpus file. A document that already carries
  cached linesegs before the round trip was not tested here.
- That F44/F19's small sub-threshold drift is specifically caused by the
  charPr-id remapping named above — plausible from the qname clusters, not
  traced element-by-element.
- Visual identity beyond this renderer's own SSIM/IoU/ink metrics at 96 dpi;
  this is evidence of rendering-pipeline stability, not a substitute for a
  Hancom-COM re-render of the candidate.

## Evidence

- `python scripts/py_compile_sweep.py` — clean.
- Privacy gate: `git archive HEAD | tar -x` into scratch,
  `pipeline/scripts/privacy_scan.py` — 0 HARD findings. This document is
  synthetic (corpus test-fixture text and file paths only, no personal
  data).
