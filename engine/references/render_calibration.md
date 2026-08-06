# WSL LibreOffice (H2Orestart) render calibration

Status: partial. WSL LibreOffice 24.2 + H2Orestart 0.7.13 cannot render real
hwpx documents that contain HWP native equation objects. A workable subset
(text + images + tables, no equations) does render and has been calibrated
against Hancom COM. Equation-bearing documents have **no** WSL/LO render path
today — advisory FILL-loop checks that depend on LO rendering must be skipped
or run COM-only for such documents.

## Killer feature

`<hp:equation>` elements in `Contents/section0.xml` (HWPX format, hwpml
`2011/paragraph` namespace) crash the H2Orestart 0.7.13 Java import filter
under LibreOffice 24.2, surfaced as a generic `Unspecified Application Error`
dialog with `--convert-to` returning a non-zero exit and no PDF written.

- LibreOffice was built without `SAL_LOG` diagnostic support in this
  environment (confirmed: `SAL_LOG=+WARN+INFO` produces zero extra output
  even on a *successful* conversion) — no stack trace or Java exception is
  obtainable from this build. The failure could only be localized by
  zip/XML bisection, not by log inspection.
- No dedicated crash-report file appears under `~/.H2Orestart` or the
  LibreOffice `UserInstallation` profile after a failing run.

### Bisection evidence (pure-Hancom-produced document, 156 paragraphs / 5
pics / 4 tables / 7 equations in the original)

| step | removed | converts? |
|---|---|---|
| baseline | (nothing) | fail |
| (a) | all `BinData/*` + `<hp:pic>` | fail |
| (b) | (a) + `<hp:tbl>` | fail |
| (c) | (a) + (b) + `<hp:equation>` | **pass** |
| (d) | `<hp:equation>` only (pics/tables/BinData untouched) | **pass** |

Step (d) isolates the effect: removing only the 7 `<hp:equation>` elements
(each holding a Hancom equation-editor `<hp:script>` body, e.g.
`{dx}over{dt}= sigma \` (y - x), ...`) is necessary and sufficient. Pictures
and tables are not implicated. The same isolation was reproduced on a
second, independently produced hwpx (our XML-authoring-engine output,
same paragraph/pic/tbl/eq counts) — identical result: fails with equations
present, passes with only `<hp:equation>` stripped.

A minimal synthetic hwpx (bare paragraph + mandatory `secPr`/`pagePr`, no
equation/pic/tbl) converts fine on the same LO+H2Orestart build, confirming
the crash is not a generic import-filter breakage but specific to the
equation control path.

### Known-issue cross-check

Checked github.com/ebandal/H2Orestart issues (WebFetch, no account access
needed for public issue text). No issue explicitly names `hp:equation` /
`NoSuchElementException` as the equation-import crash cause. The closest
match is **issue #16** ("특정 한글 hwpx 파일 변환 및 열기 시, 즉시 종료되는
현상" — specific hwpx files crash on convert/open with "Unspecified
Application Error", filed against H2Orestart 0.5.8 / LO 7.3–7.6), which
remains open/unresolved with the root document-feature never confirmed in
the thread. Treat as circumstantial support for "some element types crash
H2Orestart's HWPX path," not as a confirmed match for this exact case.
Issue #50 (garbled TOC / misplaced in-table images) is a rendering-fidelity
bug, unrelated to this crash.

## Workable subset

Text + images (`<hp:pic>` + `BinData/*`) + tables (`<hp:tbl>`), with all
`<hp:equation>` elements removed. This is representative enough to calibrate
(it retains the layout-heavy elements: multi-page flow, inline images,
multi-row/col tables) but **excludes any document that uses the native HWP
equation editor** — currently the majority of report kb documents on this
skill, which routinely embed 5–10 equations.

## Measured deltas (LibreOffice minus Hancom COM), on the equation-stripped subset

Two independently-produced source documents, both truncated to the same
11-Hancom-page / 9-LO-page range after equation removal:

| metric | doc A (pure-Hancom-produced) | doc B (XML-authoring-engine-produced) |
|---|---|---|
| page_count (Hancom / LO) | 11 / 9 | 11 / 9 |
| page_count delta | -2 | -2 |
| total_text_len delta | -52 (≈0.5% of Hancom total) | -3097 (≈22% of Hancom total) |
| total_image delta | 0 | 0 |
| max `\|bottom_white_pt delta\|` over pages | 364 | 176 |
| max_gap_scale (LO/Hancom gap ratio, worst page) | 1.51 | 5.33 |

### Suggested tolerances (conservative: max of the two runs)

```
bottom_white_tolerance_pt = 364
max_gap_scale             = 5.33   # see caveat below — likely outlier-inflated
page_count_drift_allowed  = 2
```

## Caveats (honest)

- **n=2 documents, both derived from the same underlying report content**
  (one truly Hancom-authored, one produced by our own XML engine from the
  same source). This is not a broad sample — treat the tolerances as a
  starting point, not a validated production gate.
- **page_count_drift_allowed = 2**: LibreOffice consistently packed the
  9-page equivalent of an 11-Hancom-page document tighter in both runs.
  This looks systematic (denser paragraph/table flow under LO) rather than
  random, but was only observed on two same-content documents — could be a
  property of this specific report's table/pic density, not a general LO
  vs. Hancom pagination constant.
- **max_gap_scale = 5.33 is likely a single-outlier artifact**: doc B's
  worst page-level gap ratio came from a page where the Hancom gap value
  was already small (near-zero-denominator ratio blowup), not a
  proportionally-scaled divergence across the document. Per-page ratios
  >3x on a single page should trigger manual review rather than being
  silently absorbed by a blanket tolerance — do not treat 5.33 as license
  to ignore large single-page gap deltas.
- **doc B's total_text_len delta (22%) is much larger than doc A's (0.5%)**
  despite both being the equation-stripped variant of comparable documents.
  This suggests XML-engine-produced hwpx has more Hancom/LO text-extraction
  divergence than genuinely Hancom-authored hwpx even outside the equation
  killer feature — worth a follow-up investigation before trusting LO-side
  text-length checks on XML-engine output specifically.
- **advisory tier currently excludes equation-bearing documents.** Any
  document with one or more `<hp:equation>` elements has no LibreOffice/
  H2Orestart render path at all in this environment (0.7.13 / LO 24.2) —
  the FILL/advisory loop must fall back to COM-only verification, or skip
  LO-based checks entirely, for such documents until H2Orestart fixes
  HWPX equation import (no upstream fix confirmed as of this writing).
- SAL_LOG diagnostics were unavailable in this LO build; the killer feature
  was found purely by zip/XML bisection. If a future LO build supports
  SAL_LOG, re-run diagnostics for a proper stack trace before filing
  upstream.
