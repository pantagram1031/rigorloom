# Operations — CLI contracts and JSON outputs

All paths are checkout-relative. Every operation is non-destructive (reads
the input, writes `--out`/`--save-as`). Exit codes follow the checker
convention where noted: 0 = pass/clean, 2 = usage/config error, 3 = finding.

## TOC

1. [probe](#1-probe) — capability probe
2. [form_inspect](#2-form_inspect) — offline form profiling
3. [preedit](#3-preedit) — replace / delete-guides / normalize-clones
4. [check_residue](#4-check_residue) — scan-derived residue gate
5. [charpr_check / style_diff](#5-charpr_check--style_diff) — format proofs
6. [layout_qa / fill_report](#6-layout_qa--fill_report) — PDF measurement
7. [tidy_hwpx](#7-tidy_hwpx) — blank-paragraph cleanup
8. [com_backend / build_report / xml_backend](#8-com_backend--build_report--xml_backend) — assembly
9. [render_probe / privacy_scan](#9-render_probe--privacy_scan)
10. [visual_verify](#10-visual_verify) — the render→judge loop

## 1. probe

```
python engine/scripts/probe.py --json
```

One compact JSON line: `{schema, platform, render:{hancom_com, soffice,
renderers[], pdf_capable}, modules:{discovered, enabled, cli, run_modes,
checkers}, backends:"unconfigured"|{...}}`. Never fails (exit 0); degraded
sources appear as `{"error": ...}`. Injected into SKILL.md at load.

## 2. form_inspect

```
python engine/scripts/form_inspect.py FORM.hwpx --out profile.json
    [--baseline baseline.json] [--base-pt 10] [--line-spacing 160]
```

Offline (no Hancom), `.hwpx` only. `profile.json` keys: `form_hash`,
`anchors` (headings/labels, in scan order), `placeholders`, `guide_text`,
`constraints` (base_pt / line_spacing_pct / max_pages — 0 detected on
fixed-grid forms; the fill gate there is layout immutability, not budget),
`page_metrics`, `table_map` (per-cell addr/size/borderFill/shading),
`break_audit`. `--baseline` additionally writes the font/size/color/spacing
distribution `baseline.json` consumed by `style_diff`. Exit 2 on file error;
otherwise 0 (diagnostic tool, never a gate).

**Contract: structure only.** The profile carries anchor/guide strings, not
the document body. Do not dump section XML into context.

## 3. preedit

Three offline operations; all validate every modified XML member is
well-formed BEFORE writing (a malformed member renders the whole document
blank in Hancom — structurally impossible here), and all strip the cached
`<hp:linesegarray>` of any paragraph whose text changed (stale linesegs
overprint at old coordinates).

```
python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json [--allow-missing]
python engine/scripts/preedit.py delete-guides IN.hwpx --out OUT.hwpx [--color '#0000FF'|blue] [--charpr-ids 5,6]
python engine/scripts/preedit.py normalize-clones IN.hwpx --out OUT.hwpx --clone SRC:NEW [--set textColor=#000000] [--repoint FROM:TO:TEXT]
```

- `replace`: MAP.json is `{"placeholder text": "value", ...}`. Two tiers per
  key: (A) run-text strip-compare (whole-run match, whitespace-tolerant),
  (B) raw substring over the section XML — so **keys must be
  document-unique strings**: a generic key like `http://` also hits xmlns
  namespace URIs in the markup (measured: 15 hits on a 1-table form; the
  unique-run key `" http://"` hits once). Check the reported hit count
  against your expectation. Values are XML-escaped. Output JSON:
  `{"ok": true, "hits": {key: n}}`. 0-hit key = hard error, no output written
  (`--allow-missing` reports 0 instead — idempotent re-run mode). Replaced
  text inherits the run's original charPr (possibly guide-colored) — color
  normalization is `normalize-clones`' job, not `replace`'s.
- `delete-guides`: deletes paragraphs referencing guide charPr (by color or
  explicit ids) with the T18 guard built in: table/secPr/ctrl/object
  paragraphs are never deleted.
- `normalize-clones`: removes all prior clones, recreates exactly one per
  spec, recomputes `itemCnt` from actuals, then asserts no dangling charPr
  (T22) before writing.

Idempotence contract (all three): applying an operation to its own output is
content-identical (zip member contents; timestamps ignored).

## 4. check_residue

```
python pipeline/scripts/check_residue.py --form-profile profile.json --artifact OUT.hwpx
    [--keep-pattern REGEX] [--keep "exact anchor"]... [--out verdict.json]
```

The form scan's anchor+guide inventory IS the forbidden list. Exit 0 clean,
3 residue found / artifact malformed / pinned target missing, 2 usage.
Validity precedes scanning: every `section*.xml`+`header.xml` is XML-parsed
first (`artifact_malformed` is HARD).

Keep-list semantics by document family:

- **Report finals**: default `--keep-pattern` (numbered headings) is right —
  guide/placeholder text must be gone.
- **Form fills** (labels legitimately survive): pass the label anchors as
  `--keep` entries (derive: profile anchors minus the keys your fill
  consumed). With `guide_text: 0` forms the gate then only proves consumed
  placeholders are gone — state that honestly; do not blanket-keep with a
  match-all pattern.

## 5. charpr_check / style_diff

```
python engine/scripts/charpr_check.py --file OUT.hwpx [--base-pt 10] [--caption-pt 9]
python engine/scripts/style_diff.py OUT.hwpx --baseline baseline.json [--build-yaml build.yaml] [--out diff.json]
```

`charpr_check`: offline charPr proof — verdict booleans `body_ok`
(body runs are base_pt+black), `caption_present`, `title_larger`.
`style_diff`: any format value in the output that is neither in the form
baseline nor declared in build.yaml is an anomaly (exit 1). Together they
replace "look at the PDF" for format invariants.

## 6. layout_qa / fill_report

```
python engine/scripts/layout_qa.py --file verify.pdf [--bottom 25] [--gap 3]
python engine/scripts/fill_report.py --measure --pdf verify.pdf --build-yaml build.yaml [--out verdict.json]
```

`layout_qa`: per-page `bottom_white_pct`, `max_gap_lines` (body-line
multiples; figure-occupied spans exempt), `flags`. Thresholds change only by
argument, never by editing the script. `fill_report --measure` is the
headless fill-loop verdict: ordered `needs` list for the writer/assembler;
it never writes prose itself. Numeric gate first, visual check second;
designed whitespace on cover/summary pages is exempt (T5).

## 7. tidy_hwpx

```
python engine/scripts/tidy_hwpx.py FILE.hwpx --before "앵커" [--after "앵커"] [--keep 1] [--out OUT.hwpx]
```

Offline blank-paragraph cleanup anchored to explicit paragraphs — the COM
collapse pass is retired (T7: heading charPr contamination). Keeps `--keep`
blanks (default 1); never over-compress (1 blank around tables/figures is
designed).

## 8. com_backend / build_report / xml_backend

Windows + Hancom only (`render.hancom_com: true`). Heavy flows — operator
CLIs, not auto-fired.

```
python engine/scripts/com_backend.py inspect --file FORM.hwp
python engine/scripts/com_backend.py edit --file FORM.hwp --ops ops.json --save-as OUT.hwpx --export-pdf verify.pdf
python engine/scripts/build_report.py --content bundle/content.md --form FORM.hwp > ops.json   # --dry-run: no Hancom
```

`inspect` first, always (anchors must exist before `goto_text`). Ops in
batches of 5–8 with verification between batches. `build_report` refuses on
any SECTION-anchor mismatch (fix content.md, never bypass). ops JSON schema:
`engine/references/ops_schema.md`; equation syntax:
`engine/references/hwpeqn_cheatsheet.md` (brace every script: `x^{2}`, T13).
`xml_backend.py` applies the COM-free core of build_report ops to `.hwpx`
directly when no Hancom is present.

## 9. render_probe / privacy_scan

```
python pipeline/scripts/render_probe.py [--json]     # renderer matrix only (probe.py wraps this)
python pipeline/scripts/privacy_scan.py DIR          # HARD-clean required before anything ships
```

`privacy_scan` exit 0 = clean; binary office documents pass only through the
sha256-pinned corpus allowlist (`tests/corpus/forms/manifest.json`).

## 10. visual_verify

The autonomous render→judge loop. Two halves: this script is the
deterministic one (never skippable, never calls a model), and the vision one
is you, reading page PNGs against `docs/research/visual-rubric.md`.

```
# pass 1 — machine half + vision task
python pipeline/scripts/visual_verify.py --artifact OUT.hwpx \
    [--pdf verify.pdf] [--expectations exp.json] [--png-dir DIR] [--dpi 130] \
    [--baseline BASE.pdf|DIR] [--form-profile profile.json] \
    [--content bundle/content.md] [--vision-scope all|targeted] \
    [--attempt M --max-fix-attempts N] --out visual_verdict.json

# pass 2 — merge the vision verdict you wrote
python pipeline/scripts/visual_verify.py --artifact OUT.hwpx --pdf verify.pdf \
    --expectations exp.json --vision-verdict vision.json --out visual_verdict.json
```

Exit 0 = accepted, 2 = usage, 3 = finding **or** vision still pending.

- **Rendering.** `--pdf` if you have one; an `.hwpx` without one goes through
  ONE serial `com_backend.py convert` (never `--kill-stale`). No Hancom and
  no `--pdf` is a usage error, never a pass. Pages are rasterized to
  `--png-dir` (default `<pdf>_pages/`) at `--dpi` (default 130). Equation
  scope errors (T13) need a separate `--dpi 300` run on that page.
- **Deterministic backstops**, all merged into one findings list: hwpx
  section/header XML validity (T23 `artifact_malformed`); zero-text document
  and zero-content page (T25 `blank_render`); stored `PrintInfo/PrintMethod`
  plus `pages_document` vs `pages_pdf` (W6.2 `imposition_mismatch`); declared
  page budget; declared `base_pt` / `line_spacing_pct` / `margins_mm`;
  declared `fill_map` values present in the render; `forbidden_text`;
  `layout_qa` (mapped onto rubric classes, unmapped findings preserved
  verbatim); `check_residue` with `--form-profile`; `check_density` with
  `--content`; pixel diff with `--baseline` (changed-region bboxes per page,
  so a caller can assert unchanged regions stayed unchanged).
- **`expectations.json`** keys: `pages_document`, `page_budget {min,max}` or
  `max_pages`, `base_pt`, `line_spacing_pct`, `margins_mm {top,bottom,left,
  right}`, `fill_map {label: value}`, `intentionally_blank [label]`,
  `blank_pages [n]`, `forbidden_text [str]`. Everything absent is listed
  under `deterministic.skipped` — the verdict says what it could NOT check.
- **`vision_verdict.json`** shape: `{schema, artifact, pdf, dpi, png_dir,
  rubric, acceptance, pages[], deterministic{}, vision{}, vision_required[],
  loop{}, hard[], warn[], counts, verdict}`. `verdict` is one of `pass`,
  `fail`, `vision_pending`, `deterministic_pass`.
- **The vision handback** (`--vision-verdict`) is
  `{"schema": "rigorloom/visual-vision-verdict/v1", "pages_reviewed": [...],
  "findings": [{"page", "class", "severity", "evidence"}]}`. `class` is
  validated against the rubric's closed vocabulary — an unknown class or
  severity, or an out-of-range page, is a **usage error (exit 2)**, not a
  finding. Every page in `vision_required` must appear in `pages_reviewed`
  or you get a HARD `vision_incomplete`.
- **`--deterministic-only`** can exit 0 but sets `acceptance: false`. It is a
  smoke check. Only a run with a complete vision verdict is an acceptance.
- **`--max-fix-attempts N`** does not loop for you: the loop lives in the
  caller (fix → re-render → re-run). Pass `--attempt M` and once `M >= N`
  with the run still not accepted, the script adds a HARD `loop_exhausted`
  and you escalate to a human instead of retrying.
