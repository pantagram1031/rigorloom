# 1:1-scale reference PDFs (E3.2-adjacent, W6.1 follow-up)

2026-09-04. The three pinned reference PDFs under
`tests/corpus/forms/render/{gianmun-byeolji-1ho,gianmun-byeolji-2ho,
nrf-gyeolgwa-bogoseo-yangsik}.pdf` were produced by the original W6.1 bench
(`docs/research/xc1-conversion-bench.md`) **before** the §9.3 fix, and are
print-scale reductions, not 1:1 renders. This directory holds the same three
forms re-converted at 100% scale, produced here as candidates only — the
corpus references were **not** overwritten (they are sha256-pinned in
`tests/corpus/forms/manifest.json`; replacing them is the orchestrator's
call).

## Root cause (confirmed, matches §9.3)

All three forms' `settings.xml` stores `PrintInfo/PrintMethod = 4` (2-up
"모아찍기" imposition), with `ZoomX`/`ZoomY` both 100. Hancom's
`SaveAs(..., "PDF")` honors this stored print method even for a single-page
document with nothing to pair — each page is placed into an imposed
half-sheet slot at roughly `1/sqrt(2) ≈ 0.707` scale instead of being
exported full-size. `nrf` (4 document pages) additionally lost a
page-count-parity signal (2 landscape PDF pages instead of 4 portrait) for
the same reason, already documented in §9.3.

## Conversion command used (the existing §9.3 fix, unmodified)

```
python engine/scripts/com_backend.py convert --file <converted/slug.hwpx> --to <out.pdf>
```

`com_backend.py convert`'s PDF branch (see `_stage_print_normalized_hwpx`)
stages a temp copy of the `.hwpx` source with `PrintMethod` forced to `0`
before `SaveAs("PDF")`, leaving the original untouched, and writes a
`<out>.pdf.conversion.json` sidecar recording
`source_print_method`/`print_method_normalized`/`pages_document`/
`pages_pdf`. No other flag or option was passed — this is the harness's
existing default behavior; no new scale/fit-to-page setting had to be
added.

## Verification: glyph-height ratio vs declared charPr height (PyMuPDF)

For each form, the first non-empty `<hp:t>` run in `Contents/section0.xml`
was located, its `charPrIDRef` resolved against `Contents/header.xml`'s
`hh:charPr@height` (HWPUNIT, 1/100 pt = declared point size), then the
matching text span was found on PDF page 1 (`page.get_text("dict")`) and
its rendered bbox height / `span["size"]` compared to the declared point
size.

| form | declared pt | old (corpus ref) ratio | new (this dir) ratio |
|---|---:|---:|---:|
| gianmun-byeolji-1ho | 8.00 | 0.704 | 1.004 |
| gianmun-byeolji-2ho | 8.00 | 0.704 | 1.004 |
| nrf-gyeolgwa-bogoseo-yangsik | 14.00 | 0.711 | 1.003 |

Old ≈ 0.704–0.711 (matches the documented 0.707 print reduction). New ≈
1.003–1.004 (1:1, within normal font-metric rounding). Measurement script:
`ad hoc, not committed` — logic is: parse `hh:charPr@height` for the run's
`charPrIDRef`, `fitz.open(pdf).load_page(0).get_text("dict")`, match the
span by its first character, compare `span["size"]` (pt) to
`height / 100`.

`pages_document == pages_pdf` for all three post-fix conversions (1/1, 1/1,
4/4) — the nrf page-count-parity backstop from §9.3 is clean here, unlike
the still-pinned old corpus PDF (2 pages, imposed).

## Privacy

`pipeline/scripts/privacy_scan.py` on this directory reports 3 HARD
`binary_document_ext` findings — expected: these three PDFs are new binary
files not yet in `tests/corpus/forms/manifest.json`'s sha256 allowlist (the
allowlist is corpus-scoped and adding these here was out of scope; the
orchestrator decides whether/where they get pinned). Content-wise, the only
embedded metadata is the original form's institutional PDF `author` field
("법제처 국가법령정보센터" on the gianmun forms, empty on nrf) — carried
over from the source `.hwpx`, not introduced here, and not personal data.
