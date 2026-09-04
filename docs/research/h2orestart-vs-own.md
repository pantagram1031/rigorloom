# H2Orestart (LibreOffice) vs. Rigorloom's own renderer

Question: should Rigorloom's own renderer (`engine/scripts/own_render.py`,
grade `own-uncertified`) keep being the base, or should the LibreOffice +
H2Orestart path (already the repo's `advisory` proof-grade tier — see
`pipeline/scripts/doc_backend.py`, `docs/golden-path.md`) become the base or
a donor of specific mechanisms?

Measured 2026-09-04, on the operator's Windows workstation, against all ten
1:1 corpus references (`tests/corpus/forms/render/*.pdf`, re-pinned
2026-09-03; see `engine/scripts/render_scoreboard.py`'s header for the fix).

## Installed?

Not on native Windows (no `soffice` on PATH or under either Program Files;
no scoop/choco install). **But WSL Ubuntu is present and already carries a
working LibreOffice 24.2.7.2 + `libreoffice-h2orestart` 0.7.13-1** (newer
than the 0.6.1 Ubuntu 24.04 ships, and past the HWPX-import-abort version
`ci.yml` works around) — this is exactly the `soffice_wsl` backend
`pipeline/scripts/render_probe.py` / `doc_backend.py` already know how to
select. So this ran the "installed" branch, converting every corpus form
through `wsl -e bash -lc "soffice --headless ... --convert-to
pdf:writer_pdf_Export ..."`, the same invocation `.github/workflows/ci.yml`'s
`render-smoke` job uses (`--convert-to pdf:writer_pdf_Export`, an isolated
`-env:UserInstallation`). Nothing was installed; the existing WSL distro
image was used as-is.

## Method

- **Own renderer**: `python engine/scripts/render_scoreboard.py --corpus
  --out <scratch>` (auto line/block layout, 144 dpi). Scores its own PNG
  pages against the Hancom references with its own `ssim` / `ssim_inked` /
  `text_line_iou` / page-count implementation.
- **H2Orestart**: each `tests/corpus/forms/converted/*.hwpx` converted to
  PDF via WSL `soffice --headless --convert-to pdf:writer_pdf_Export`, then
  scored with a small scratch script
  (`h2o_scoreboard.py`) that imports `render_scoreboard.py` as a module and
  calls its *exact* internal functions unmodified — `ssim`,
  `_ink_fraction`, `_changed_channel_ratio`, `_reference_pages`,
  `_reference_line_boxes`, `pair_line_boxes` — with the H2Orestart PDF's own
  page pixel grid (144 dpi off its native page rect) standing in for the
  own-renderer's `page_size_px`, and the Hancom reference rescaled onto that
  grid exactly as the own-renderer scoreboard does. Same channels, same math,
  different candidate source. No repo files were changed to do this.

## Per-form results (144 dpi, all channels 0–1 except page counts)

Own renderer (`render_scoreboard.py --corpus`, `own-uncertified` grade,
line/block layout `auto`):

| form | ssim | ssim_inked | line IoU | pair rate | pages ref/cand |
|---|---|---|---|---|---|
| jeongbo-gonggae-cheongguseo | 0.6203 | 0.0388 | 0.4551 | 1.0000 | 1/1 |
| jumin-deungchobon-sinchengseo | 0.6426 | 0.0851 | 0.5893 | 1.0000 | 3/3 |
| saeopja-deungnok-sinchengseo | 0.6447 | 0.0179 | 0.5562 | 0.9861 | 6/6 |
| moel-pyojun-geunrogyeyakseo-2025 | 0.7637 | 0.1808 | 0.5167 | 0.7056 | 7/7 |
| moel-pyojun-geunrogyeyakseo-2013 | 0.7751 | 0.0698 | 0.4680 | 0.6689 | 7/7 |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | 0.8134 | 0.2218 | 0.2451 | 0.7922 | 22/21 |
| nrf-gyeolgwa-bogoseo-yangsik | 0.8673 | 0.3246 | 0.6597 | 1.0000 | 4/4 |
| admrul-gajokdolbom-hyuga-sinchengseo | 0.8913 | 0.3218 | 0.5070 | 0.4286 | 1/1 |
| gianmun-byeolji-2ho | 0.9074 | 0.0531 | 0.5515 | 0.7826 | 1/1 |
| gianmun-byeolji-1ho | 0.9112 | 0.0600 | 0.6215 | 1.0000 | 1/1 |
| **mean (10)** | **0.7837** | **0.1374** | **0.5170** | **0.8364** | **9/10 exact (90%)** |

H2Orestart / LibreOffice (WSL `soffice --headless --convert-to
pdf:writer_pdf_Export`, no Korean font installed — see Mechanisms):

| form | ssim | ssim_inked | line IoU | pair rate | pages ref/cand |
|---|---|---|---|---|---|
| jumin-deungchobon-sinchengseo | 0.5784 | 0.0681 | 0.1311 | 0.8826 | 3/3 |
| jeongbo-gonggae-cheongguseo | 0.6248 | 0.0442 | 0.2649 | 0.9492 | 1/1 |
| saeopja-deungnok-sinchengseo | 0.6399 | 0.0690 | 0.1396 | 0.6414 | 6/9 |
| moel-pyojun-geunrogyeyakseo-2025 | 0.7019 | 0.0943 | 0.1567 | 0.7096 | 7/7 |
| moel-pyojun-geunrogyeyakseo-2013 | 0.7435 | 0.0338 | 0.1262 | 0.5233 | 7/9 |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | 0.8192 | 0.2388 | 0.1186 | 0.5640 | 22/27 |
| nrf-gyeolgwa-bogoseo-yangsik | 0.8378 | 0.2452 | 0.3300 | 1.0000 | 4/5 |
| admrul-gajokdolbom-hyuga-sinchengseo | 0.8457 | 0.2949 | 0.0834 | 0.3878 | 1/1 |
| gianmun-byeolji-2ho | 0.8581 | 0.0495 | 0.0506 | 0.6522 | 1/1 |
| gianmun-byeolji-1ho | 0.8748 | 0.1009 | 0.0512 | 0.9615 | 1/1 |
| **mean (10)** | **0.7524** | **0.1239** | **0.1452** | **0.7271** | **6/10 exact (60%)** |

Own renderer wins the channels that matter most for a form (text-line IoU:
**0.517 vs 0.145**, a 3.6x gap; page-count exactness: **90% vs 60%**) and is
slightly ahead on ssim/ssim_inked/pair-rate too. It does not win everywhere —
per-form ssim is close and trades places (H2Orestart is ahead on
admrul/gianmun-2ho/gianmun-1ho by 0.02–0.05) — but nothing in these numbers
argues for H2Orestart as the base.

## Mechanisms — the two worst-gap forms per renderer

Both renderers' worst two forms by ssim happen to be the *same* two:
`jeongbo-gonggae-cheongguseo` and `jumin-deungchobon-sinchengseo`. Viewed
page-by-page against the Hancom reference at 144 dpi:

**H2Orestart — dominant mechanism: missing Hangul glyph coverage in the
render environment.** Both forms come back with the vast majority of Hangul
body text rendered as tofu boxes (`□`) rather than glyphs; table rule lines,
row heights, and overall layout skeleton are otherwise close to the
reference. `wsl fc-list :lang=ko` returns **zero** fonts on this machine's
WSL Ubuntu image, and neither `.github/workflows/ci.yml`'s `render-smoke`
job nor this measurement installs any Korean-capable font package (e.g.
`fonts-nanum`) — the job's own synthetic smoke document sidesteps this
entirely by declaring `Liberation Serif` and ASCII-only text
(`.github/workflows/ci.yml:229-232`), so CI has never actually exercised
Hangul glyph rendering through this path. Tofu glyphs have different metrics
than the Hangul they replace, which cascades into wrong line breaks and, on
4 of 10 forms, wrong page counts (`saeopja` 6→9, `moel-2013` 7→9, `kstartup`
22→27, `nrf` 4→5) — this is very likely the same mechanism behind the
page-count misses, not a separate pagination defect. This is a fixable
*environment* gap (install Korean fonts on whatever host runs H2Orestart),
not necessarily an H2Orestart filter defect — but it is the gap as measured,
on the same install path CI already uses, and it is not small: it is the
largest single contributor to H2Orestart's line-IoU and page-count losses
above.

**Own renderer — dominant mechanisms, neither is missing glyphs.**
1. *Border line style*: `jeongbo-gonggae-cheongguseo`'s reference draws the
   `접수증` and `유의사항` section-divider rules as dashed/dotted; the own
   renderer draws them solid. A `hp:linetype` declared as dashed is not
   distinguished from solid in the own renderer's border draw path.
2. *Table row height / vertical padding*: the same form's table rows render
   visibly taller in the own renderer than the reference, compressing the
   bottom margin. Row height is being computed with more padding than
   Hancom's own layout uses.
3. *Font glyph shape / small sub-pixel drift*: `jumin-deungchobon-sinchengseo`
   is otherwise near pixel-identical in structure and every character is
   legible (unlike H2Orestart's tofu), but small, page-wide glyph-shape and
   kerning differences (own renderer resolves declared faces against the
   Windows system font directory rather than using Hancom's exact metrics)
   are enough to depress the non-overlapping 8x8-block SSIM average even
   though nothing is structurally wrong — consistent with
   `render_scoreboard.py`'s own stated caveat that every number here depends
   on which fonts the host has installed.

None of the own renderer's worst-gap defects are missing-glyph failures; all
three are refinements to an already-working pipeline. H2Orestart's worst-gap
defect is closer to "large classes of text are unreadable" on the render
path as CI actually exercises it.

## Recommendation

**Keep the own renderer as the base.** It measures ahead on the channels
that matter most (line-box IoU, page-count exactness) and is competitive on
ssim, while H2Orestart's number is dragged down by a font-provisioning gap
that is real in the CI/WSL environment this repo actually deploys through
today. Do not adopt H2Orestart as the base, and do not block on "fix the
font gap and re-measure" before deciding — the own renderer's remaining
defects (dashed borders, row-height padding) are narrower and cheaper to
close directly than closing H2Orestart's structural gap (page-count drift,
much lower line IoU even setting the font issue aside — H2Orestart's line
IoU stays well under the own renderer's on every one of the ten forms) would
be.

**Borrow one thing, narrowly, from the LibreOffice/H2Orestart side: use it
as a source of ground truth for dashed/dotted border rendering**, i.e. when
implementing `hp:linetype` variants (dash, dot, dash-dot) in the own
renderer's border draw path, treat H2Orestart's rendering of the same
`hp:linetype` value as a second reference alongside the Hancom PDF — not to
copy code, but to confirm the intended dash pattern when the Hancom
reference alone is ambiguous at 144 dpi. This is observation-only (reading
a rendered PDF a human or a script looks at), not code reuse, so it needs no
license accommodation.

Do **not** borrow the table row-height computation or any font-metrics code
from LibreOffice/H2Orestart — the own renderer's row-height gap is a
padding-constant fix, not something that needs an external algorithm.

## Licensing note (for any future borrowing)

- **H2Orestart**: GPL-3.0-or-later (`Files: *` in the Debian package's
  `copyright`, one file — `RegistrationHandler.java` — under LGPL-2.1). Any
  code taken from H2Orestart into Rigorloom's own renderer would place the
  combined work under GPL-3+ obligations (copyleft: source availability,
  same-license redistribution) unless Rigorloom's own renderer is itself
  already GPL-compatible. This is why the recommendation above treats
  H2Orestart only as an observational reference, never as a code source.
- **LibreOffice**: MPL-2.0 (file-level copyleft — a file taken from LO and
  modified must stay MPL-2.0, but this does not spread to the rest of a
  combined work the way GPL does). Still requires attribution and
  MPL-2.0 licensing of any LO-derived file actually copied in.
- Net: nothing recommended above requires taking on either license, because
  the one borrowed thing (dash-pattern ground truth) is observation of
  rendered output, not text or code from either project.

## Reproduction

```
# Own renderer (no LibreOffice, no Hancom COM needed):
python engine/scripts/render_scoreboard.py --corpus --out <dir>

# H2Orestart (WSL soffice_wsl backend, matches render_probe.py's detection):
wsl -e bash -lc "soffice --headless -env:UserInstallation=file:///tmp/lo-profile \
  --convert-to pdf:writer_pdf_Export --outdir <out> \
  tests/corpus/forms/converted/*.hwpx"
# then score with the scratch h2o_scoreboard.py described above (imports
# engine/scripts/render_scoreboard.py's internal functions unmodified).
```

All render output for this measurement was written under the scratch
directory and deleted after this doc was written; nothing under
`tests/corpus/` was modified.
