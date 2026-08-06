# XC-1: hwp→hwpx conversion + per-family recognition bench (W6.1)

Status: DONE (2026-08-06/07, operator machine, branch `w6-xc1-bench`).
Executes the `XC-1-convert-fidelity` scenario from
`docs/research/form-eval-scenarios.md` §Cross-cutting and unblocks all 7
XC-1-blocked scenarios in that doc for W6.2 onward.

Engine: `engine/scripts/com_backend.py` (pyhwpx COM), Hancom Office
**13.0.0.2986**, single operator machine, single Hancom install. All 10
`.hwp` corpus members converted strictly serially — one file at a time, Hwp
closed between files, no `--kill-stale`, no retries. Zero hangs, zero
errors, zero retry-storms across the full run (20 COM calls: 10 convert +
10 inspect, plus 10 render + 1 ad hoc version query for the report below).

## 1. Conversion outcome (10/10 OK)

| slug | family | src bytes | hwpx bytes | outcome |
|---|---|---:|---:|---|
| jumin-deungchobon-sinchengseo | petition | 62,976 | 65,613 | OK |
| jeongbo-gonggae-cheongguseo | petition | 130,048 | 66,424 | OK |
| saeopja-deungnok-sinchengseo | petition | 99,840 | 110,652 | OK |
| admrul-gajokdolbom-hyuga-sinchengseo | petition | 34,816 | 32,521 | OK |
| gianmun-byeolji-1ho | gongmun | 32,768 | 30,304 | OK |
| gianmun-byeolji-2ho | gongmun | 30,208 | 29,451 | OK |
| nrf-gyeolgwa-bogoseo-yangsik | research | 18,944 | 56,694 | OK (see §4 render caveat) |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | grant | 86,016 | 105,208 | OK |
| moel-pyojun-geunrogyeyakseo-2013 | hr | 30,720 | 61,302 | OK |
| moel-pyojun-geunrogyeyakseo-2025 | hr | 69,120 | 71,237 | OK |

No file failed, hung, or required a retry. One transient observation: after
the kstartup convert-to-PDF call returned `{"ok": true}`, `Hwp.exe` was
still listed in `tasklist` for a few seconds before exiting on its own — not
a hang (well under the 120 s threshold), logged here for the record since
COM discipline requires reporting it, not because it changed the outcome.

Outputs: `tests/corpus/forms/converted/<slug>.hwpx` (10 files) and
`tests/corpus/forms/render/<slug>.pdf` (10 files, §4). Corpus `.hwp`
originals are untouched — every conversion ran against a scratch-staged
copy, never the tracked corpus file directly (sha256 of the 10
`documents[]` `.hwp` entries in `manifest.json` is unchanged from before
this bench).

## 2. Parity: method and results

**`pipeline/scripts/check_convert_parity.py` cannot run on this pairing as
built.** Its CLI takes `(extracted, assembled)` where `assembled` must be
`.hwpx` and `extracted` is `content.md` / an extraction directory / another
`.hwpx` — and internally it also resolves an `extraction_manifest.json`
pointing back to a *source hwpx* to compute `source_hwpx` fingerprints
(`source_hwpx()` in the script, `content_extract.py:33`). It has no code
path for a `.hwp` source at all; that tool's contract is
report-pipeline-extraction-vs-assembly, not raw-format-conversion parity.
Recorded here rather than silently worked around.

**Substitute method used instead (honest, lossy, documented):**

1. **Source-side**: `com_backend.py inspect --file <staged .hwp>
   --preview-chars 100000` — COM-opens the original `.hwp` and calls
   `HwpObject.GetTextFile("TEXT", "")` for the *entire* document body (not
   the truncated PrvText preview scenario docs assumed was available before
   this bench ran) plus native `tables` / `equations` / `pictures` /
   `pages` (`HeadCtrl` walk + `PageCount`) counts.
2. **Converted-side**: `pipeline/scripts/content_extract.py`'s
   `semantic_fingerprint()` / `extract_document()` run offline (no COM) on
   `converted/<slug>.hwpx`, giving structural `paragraphs` / `tables` /
   `pictures` / `equations` counts and a normalized-text char count.
3. Compared side by side. **Not** a byte-identity or hash-equality check —
   the two extraction paths normalize differently (COM `GetTextFile` vs.
   hwpx-XML paragraph walk), so exact char-count equality is not expected
   and was not required; the check is "counts land in the same
   neighborhood, structural counts (tables/pictures/equations) match
   exactly."

| slug | src chars (COM) | hwpx chars (content_extract, normalized) | src tables/pics/eqns | hwpx tables/pics/eqns | src pages | PDF pages |
|---|---:|---:|---|---|---:|---:|
| jumin-deungchobon-sinchengseo | 5,815 | 3,904 | 3 / 1 / 0 | 3 / 1 / 0 | 3 | 3 |
| jeongbo-gonggae-cheongguseo | 1,399 | 1,197 | 2 / 1 / 0 | 2 / 1 / 0 | 1 | 1 |
| saeopja-deungnok-sinchengseo | 9,346 | 7,009 | 7 / 0 / 0 | 7 / 0 / 0 | 6 | 6 |
| admrul-gajokdolbom-hyuga-sinchengseo | 316 | 713 | 2 / 0 / 0 | 2 / 0 / 0 | 1 | 1 |
| gianmun-byeolji-1ho | 558 | 630 | 3 / 0 / 0 | 3 / 0 / 0 | 1 | 1 |
| gianmun-byeolji-2ho | 420 | 459 | 2 / 0 / 0 | 2 / 0 / 0 | 1 | 1 |
| nrf-gyeolgwa-bogoseo-yangsik | 2,418 | 3,588 | 3 / 0 / 0 | 3 / 0 / 0 | **4** | **2** |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | 11,424 | 13,629 | 42 / 5 / 0 | 42 / 0 / 0 | 22 | 22 |
| moel-pyojun-geunrogyeyakseo-2013 | 10,035 | 11,233 | 7 / 0 / 0 | 7 / 0 / 0 | 7 | 7 |
| moel-pyojun-geunrogyeyakseo-2025 | 9,383 | 11,720 | 10 / 0 / 0 | 10 / 0 / 0 | 7 | 7 |

Tables and equations match exactly (`content_extract`'s `<hp:tbl>` /
equation-script element counts) on all 10 files. Char counts differ by
20–125% in both directions — expected given the different normalization
paths (COM `GetTextFile` includes field/UI chrome text; the XML paragraph
walk does not; whitespace collapsing differs) — this is a **structural**
parity check, not a text-identity check, and should not be read as either.

**Two real findings, not artifacts of the method:**

- **kstartup pictures: 5 (COM control count) vs 0 (`content_extract`
  semantic count).** `content_extract`'s picture counter looks for a
  specific hwpx picture element shape that this converted file's 5 images
  apparently don't match (or they moved into a container `content_extract`
  doesn't walk). Flagged as an open item for whoever next touches
  `content_extract.py`'s picture detection — not investigated further here
  (out of this bench's scope; COM discipline budget was spent on the
  conversion+probe+render loop, not on this tool's internals).
- **nrf pages: 4 (both source `.hwp` AND the freshly-converted `.hwpx`,
  confirmed by a direct COM `inspect` on `converted/nrf-...hwpx` — see §4)
  vs 2 in the exported PDF.** The hwp→hwpx *conversion* is not the problem;
  the hwpx→PDF *export* step is. See §4.

## 3. Per-family recognition table (form_inspect, offline, all 12 now probed)

`tests/corpus/forms/probe_results.json` extended from 2/12 probed (Bench-0)
to **12/12 probed, 0 skipped**. Family ⑤ (corp) and the school gap have 0
corpus members, so no probe exists for them — consistent with the
documented corpus boundary, not a miss.

| family | forms | anchors (range) | guide_text hits | fillable cells (range) |
|---|---:|---|---|---|
| petition | 4 | 16–646 | 3/4 (admrul=0) | 16–782 |
| gongmun | 2 | 15–26 | 2/2 | 5–48 |
| research | 1 | 72 | 1/1 (20 hits) | 32 |
| grant | 3 | 28–357 | **1/3** (kstartup=152; both PPS procurement forms=0) | 16–362 |
| hr | 2 | 159–203 | 1/2 (2025=0) | 69–101 |
| school | 0 | — | — | — (corpus gap, unchanged) |
| corp | 0 | — | — | — (documented boundary, unchanged) |

Per-file detail (form_inspect, offline, no COM):

| slug | family | anchors | guide_text | tables | cells | constraints_detected |
|---|---|---:|---:|---:|---:|---:|
| jumin-deungchobon-sinchengseo | petition | 68 | 5 | 3 | 85 | 0 |
| jeongbo-gonggae-cheongguseo | petition | 34 | 2 | 1 | 66 | 0 |
| saeopja-deungnok-sinchengseo | petition | 646 | 7 | 6 | 782 | 0 |
| admrul-gajokdolbom-hyuga-sinchengseo | petition | 16 | 0 | 2 | 16 | 0 |
| gianmun-byeolji-1ho | gongmun | 26 | 1 | 2 | 5 | 0 |
| gianmun-byeolji-2ho | gongmun | 15 | 1 | 1 | 48 | 0 |
| nrf-gyeolgwa-bogoseo-yangsik | research | 72 | 20 | 3 | 32 | 0 |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | grant | 357 | 152 | 39 | 362 | 0 |
| pps-hyeopeop-seungin-sinchengseo | grant | 29 | 0 | 1 | 45 | 0 |
| pps-jeongbogonggae-donguiseo | grant | 28 | 0 | 3 | 16 | 0 |
| moel-pyojun-geunrogyeyakseo-2013 | hr | 159 | 1 | 7 | 69 | 0 |
| moel-pyojun-geunrogyeyakseo-2025 | hr | 203 | 0 | 9 | 101 | 0 |

`constraints_detected = 0` on all 12 — the Bench-0 finding ("fixed-grid
forms don't declare report-style prose constraints") holds across every
family now that the full corpus is probeable, not just the 2 native-hwpx
grant forms.

### Guide-text detector gap: bigger than the "procurement" hypothesis

Bench-0 flagged `guide_text = 0` on both native PPS (조달청/procurement)
forms and treated it as an open question, not a confirmed procurement-only
gap. With all 12 forms now probed, the gap is **not** procurement-specific:

- Both PPS procurement forms: 0 (as before).
- **admrul-gajokdolbom-hyuga-sinchengseo (petition, 행정규칙 layer)**: 0,
  despite being an official form with instructional structure.
- **moel-pyojun-geunrogyeyakseo-2025 (hr, the newer/2025 revision)**: 0,
  while its own 2013 predecessor scores 1.
- Everything else scores 1–152 hits (kstartup's 152 mostly reflects its
  22-page 사업계획서 body having many instruction/label lines, not that
  the detector suddenly works differently there).

The current heuristics (colored runs / 작성예시 patterns tuned on report
templates) miss guide text on at least 4/12 forms across 3 different
families (petition, hr, grant-procurement) — this is a detector-coverage
gap, not a family-specific one. Feeds directly into the §6.2 fix-or-bound
decision the scenario doc anticipated.

### Table-count discrepancy: form_inspect vs content_extract

`form_inspect.py`'s `table_map` count and `content_extract.py`'s raw
`<hp:tbl>` element count **disagree on 6/10 converted files** (always
`form_inspect` <= `content_extract`, by 1–3 tables): jeongbo (1 vs 2),
gianmun-1ho (2 vs 3), gianmun-2ho (1 vs 2), saeopja (6 vs 7), kstartup (39
vs 42), moel-2025 (9 vs 10). The two tools evidently define "a table"
differently — plausibly `form_inspect` collapses a nested table (a `<hp:tbl>`
inside another table's cell) into its parent while `content_extract` counts
every element — but this was not root-caused within this bench's scope.
Anyone building on either tool's table count as a hard invariant should
know the two are not interchangeable. The recognition table in §3 above
uses `form_inspect` (the tool the scenario doc specifies for family
recognition); §2's parity table uses `content_extract` (the tool
`check_convert_parity` itself uses internally).

## 4. Render honesty (T25)

All 10 conversions were exported to PDF
(`com_backend.py convert --file converted/<slug>.hwpx --to
render/<slug>.pdf`) and checked with `fitz` for page count and total
extracted text length.

| slug | PDF pages | PDF text length |
|---|---:|---:|
| jumin-deungchobon-sinchengseo | 3 | 5,673 |
| jeongbo-gonggae-cheongguseo | 1 | 1,301 |
| saeopja-deungnok-sinchengseo | 6 | 7,912 |
| admrul-gajokdolbom-hyuga-sinchengseo | 1 | 207 |
| gianmun-byeolji-1ho | 1 | 428 |
| gianmun-byeolji-2ho | 1 | 289 |
| nrf-gyeolgwa-bogoseo-yangsik | **2** | 2,079 |
| kstartup-jiwon-sincheongseo-saeopgyehoekseo | 22 | 9,548 |
| moel-pyojun-geunrogyeyakseo-2013 | 7 | 8,257 |
| moel-pyojun-geunrogyeyakseo-2025 | 7 | 7,003 |

Text length > 0 on all 10 — the categorical T25 render-honesty floor
passes everywhere.

**But one real page-count drift, investigated, not smoothed over.** The
source `.hwp`'s `PageCount` (COM) is 4 for nrf-gyeolgwa-bogoseo-yangsik. A
direct COM `inspect` on the *converted* `converted/nrf-...hwpx` (done as a
follow-up check, not part of the original 20-call plan) also reports
`PageCount = 4` and `text_chars_total = 2418` — **identical to the
source**. So the hwp→hwpx conversion itself is exact for this file. The
drift appears only when that same hwpx is exported to PDF: the PDF has 2
pages. The PDF's extracted text (2,079 chars) is close to the hwpx's
2,418, which suggests the 2 missing pages were mostly blank/whitespace
continuation sheets rather than a chunk of lost body content — but that is
an inference from a character-count ratio, not a verified page-by-page
diff, and should be read as such. **This is a PDF-export-step finding, not
a conversion-step finding**: the hwp→hwpx conversion this bench measures
passed; the hwpx→PDF render (used here only for the eyeball PNGs and the
T25 floor, not for the corpus's certified `.hwpx` artifacts) undercounted
pages on 1/10 files. Flagged for whoever next touches the PDF-export path
in `com_backend.py`.

## 5. Per-family eyeball PNGs (fitz, 130 dpi, first form per family)

Rendered from the PDFs in §4, page 1 only. Paths are inside the worktree's
local scratch dir (not committed — `.scratch/` is untracked); the
coordinator should open these directly on the operator machine:

- petition: `C:\Users\SAMSUNG\dev\rigorloom-w6-xc1\.scratch\xc1-png\petition.png` (jumin-deungchobon-sinchengseo, p.1/3)
- gongmun: `C:\Users\SAMSUNG\dev\rigorloom-w6-xc1\.scratch\xc1-png\gongmun.png` (gianmun-byeolji-1ho, p.1/1)
- research: `C:\Users\SAMSUNG\dev\rigorloom-w6-xc1\.scratch\xc1-png\research.png` (nrf-gyeolgwa-bogoseo-yangsik, p.1/2 — see §4 caveat on this file's PDF page count)
- grant: `C:\Users\SAMSUNG\dev\rigorloom-w6-xc1\.scratch\xc1-png\grant.png` (kstartup-jiwon-sincheongseo-saeopgyehoekseo, p.1/22)
- hr: `C:\Users\SAMSUNG\dev\rigorloom-w6-xc1\.scratch\xc1-png\hr.png` (moel-pyojun-geunrogyeyakseo-2013, p.1/7)

school and corp have 0 corpus members — no PNG possible, consistent with
the documented gap/boundary.

Visual spot-check (petition/jumin, eyeballed during this bench): grid
lines, box borders, and Korean text render cleanly at 130 dpi; no visible
font substitution or layout collapse on page 1.

## 6. Manifest and privacy

`tests/corpus/forms/manifest.json` extended: the 10 converted `.hwpx`
outputs and their 10 rendered `.pdf` siblings are now `documents[]` entries
(`kind: "xc1_converted_hwpx"` / `"xc1_render_pdf"`) with `path` + `sha256`,
so the manifest-pinned binary allowlist (`privacy_scan.py
--binary-allowlist`) covers them — this is required for the allowlist
mechanism to work at all: `load_binary_allowlist()` only reads the
top-level `documents[]` list, so a first attempt at a separate
`manifest.converted` side-block was invisible to the scanner and produced
20 `binary_document_ext` HARD findings. Fixed by folding both sets into
`documents[]` (with duplicate `slug` values across the `.hwp` source, the
`.hwpx` conversion, and the `.pdf` render for the same form — harmless,
since the allowlist keys by resolved file path, not slug). A
`xc1_conversion_metadata` block (tool, Hancom version, timestamp, naming
note) stays at the top level for humans.

**Naming deviation, documented, not reconciled**: outputs land flat under
`converted/<slug>.hwpx` per this bench's task spec, not the
`<family>/<slug>.converted.hwpx` colocated layout
`docs/research/form-eval-scenarios.md`'s `XC-1-convert-fidelity` scenario
describes. Recorded in `manifest.json`'s `xc1_conversion_metadata.note_naming`.

```
$ python pipeline/scripts/privacy_scan.py .
binary allowlist: .../tests/corpus/forms/manifest.json (32 sha256-pinned entries)
... (34 WARN, all pre-existing korean_student_id_proximity hits in test
     fixtures unrelated to this bench — see kb below)
summary: HARD=0 WARN=34 TOTAL=34
EXIT=0
```

## 7. Full suite quick check

`python pipeline/scripts/module_registry.py write-enabled --none` (core-only
point, `modules/enabled.yaml` is gitignored) then `python -m pytest -q`:

```
835 passed, 565 skipped, 17 subtests passed in 305.11s (0:05:05)
```

0 failures. The 565 skips are the expected core-only module-gated skips
(`modules/report`, `modules/style` tests) plus pre-existing fixture/env
skips unrelated to this bench.

## 8. Honest limitations

- **Single Hancom install, single Windows machine.** No cross-version
  fidelity data (e.g. a second Hancom Office build converting the same
  corpus) — every number in this doc is one build's behavior.
- **`check_convert_parity.py` was not actually run** — its contract doesn't
  fit hwp→hwpx conversion (§2). The substitute comparison is real and
  documented but is a different, weaker check (structural-count
  neighborhood, not hash/byte parity) than what that script provides for
  its intended report-pipeline extraction/assembly use case.
- **COM `GetTextFile("TEXT","")` is not literally "PrvText"** — it's closer
  to a full-body text dump than the truncated preview stream the scenario
  doc assumed would be the only source-side signal available; this bench
  used the stronger signal where the API allowed it, but the source/hwpx
  normalization mismatch (§2) means char-count deltas are still not a hard
  parity signal.
- **`content_extract`'s picture count undercounts on kstartup** (0 vs 5
  COM-visible picture controls) — open item, not root-caused here (§2).
- **PDF export drops pages on nrf** (§4) — open item, not root-caused
  beyond the character-count inference.
- **`form_inspect` vs `content_extract` table counts disagree on 6/10
  files** (§3) — open item, not root-caused here.
- **DocSummary author metadata was not stripped** on the converted files
  (manifest's existing `privacy.metadata_note` caveat about issuing-agency
  clerk names in `HwpSummaryInformation` carries forward unchanged to the
  `.hwpx` siblings — not evaluated in this bench, flagged for whoever next
  touches metadata stripping).
- **Guide-text detector gap (§3) is now a 4/12 finding across 3 families**,
  up from Bench-0's "0/2 on procurement" — this materially widens the open
  6.2 item; not fixed here (out of scope for a conversion bench).
