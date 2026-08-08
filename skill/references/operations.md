# Operations — CLI contracts and JSON outputs

All paths are checkout-relative. Every operation is non-destructive (reads
the input, writes `--out`/`--save-as`). Exit codes follow the checker
convention where noted: 0 = pass/clean, 2 = usage/config error, 3 = finding.

## TOC

1. [probe](#1-probe) — capability probe
2. [form_inspect](#2-form_inspect) — offline form profiling
3. [preedit](#3-preedit) — replace / fill-cells / delete-guides / normalize-clones
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
`page_metrics`, `table_map` (per-table `index`/`depth`, per-cell
`addr`/`span`/size/borderFill/shading/classification — plus the T30
pre-flight fields `charpr`/`script_anomaly`/`charpr_suggested` on
`fill_target` cells), `body_baseline_charpr`, `script_anomaly_targets`,
`break_audit`. `--baseline` additionally writes the font/size/color/spacing
distribution `baseline.json` consumed by `style_diff`. Exit 2 on file error;
otherwise 0 (diagnostic tool, never a gate).

**Contract: structure only.** The profile carries anchor/guide strings, not
the document body. Do not dump section XML into context.

## 3. preedit

Four offline operations; all validate every modified XML member is
well-formed BEFORE writing (a malformed member renders the whole document
blank in Hancom — structurally impossible here), and all strip the cached
`<hp:linesegarray>` of any paragraph whose text changed (stale linesegs
overprint at old coordinates).

```
python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json [--allow-missing]
python engine/scripts/preedit.py fill-cells IN.hwpx --out OUT.hwpx [--table 0] --cell ROW,COL=TEXT ... [--map CELLS.json] [--overwrite] [--charpr ID] [--charpr-per-cell ROW,COL=ID ...]
python engine/scripts/preedit.py delete-guides IN.hwpx --out OUT.hwpx [--color '#0000FF'|blue] [--charpr-ids 5,6]
python engine/scripts/preedit.py normalize-clones IN.hwpx --out OUT.hwpx --clone SRC:NEW [--set textColor=#000000] [--repoint FROM:TO:TEXT]
```

**Which one fills a form.** Look at `table_map` first. A cell whose
`classification` is `fill_target` is *genuinely empty* — in real forms it is
`<hp:run charPrIDRef="N"/>` with no `<hp:t>` at all (measured: 19 of 19 empty
cells on the PPS 협업승인신청서). There is no string to key on, so `replace`
cannot reach it: use **`fill-cells`** (T27). Use `replace` only where a
literal placeholder string exists in the document.

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
  **Each span is written once** (T26): a value that contains its own key
  (`{" http://": " http://example.kr"}`) is applied exactly once and re-runs
  are no-ops — tier B never rewrites what tier A (or an earlier key, or an
  earlier run of the same command) already wrote.
- `fill-cells`: addresses cells by the `cellAddr` **`table_map` reports** —
  `--cell ROW,COL=TEXT` (repeatable) or `--map` `{"2,3": "값"}`. `--table N`
  (default 0) indexes tables in document order, nested tables included and
  counted separately (outer first; `table_map` carries the same `index` and
  a `depth`). Merged cells own the top-left coordinate only, so addresses are
  not contiguous — a coordinate a rowSpan/colSpan covers has no cell and is a
  hard error listing the real addresses. Creates the `<hp:t>` inside the empty
  run and **preserves that run's charPr** (`--charpr ID` overrides, and then
  the T22 dangling-charPr assertion runs too). A non-empty target is refused
  unless `--overwrite`; a refusal anywhere in the batch writes nothing at all.
  Output JSON: `{"ok": true, "table": n, "tables_total": n, "filled": n,
  "body_baseline_charpr_id": "0", "cells": [{"addr": [r, c], "hits": 1,
  "action": "filled"|"overwritten", "previous": "…", "charpr": "0"|null}]}`.
  **`--charpr` applies to the whole batch** (T32) — it is only safe when every
  target shares a charPr. Per-cell ids need `--charpr-per-cell ROW,COL=ID`
  (repeatable, wins over `--charpr`); an address it names that is not in the
  fill list is a usage error, not a silent no-op.

### The charPr pre-flight before any fill (T30)

"Preserves that run's charPr" is only safe when that run's charPr *is* body
formatting. On the PPS form, cell (10,2)'s empty run carried a charPr
identical to body text **plus** `<hh:supscript/>`: a correct-looking fill
rendered at ~6.35pt raised off the baseline, and because nominal `height`
never changed, `charpr_check --base-pt 10` and `style_diff` both passed it.
So run the pre-flight — never guess the id, and never read `header.xml` by
hand (the structure-only contract above forbids exactly that):

1. **Inspect.** `form_inspect FORM.hwpx --out profile.json` reports
   `body_baseline_charpr` (`{id, height_pt, signature}` — the document's own
   body charPr) once at the top level, and per `fill_target` cell:
   `charpr` (the id the fill would inherit), `script_anomaly`
   (`true` when that charPr differs from the baseline on any of
   `supscript`/`subscript`/`ratio`/`relSz`/`offset`; `false` = checked and
   clean; `null` = could not be judged), and `charpr_suggested` (the baseline
   id to use instead). `script_anomaly_targets` lists just the anomalies.
2. **Check.** `script_anomaly_targets == []` → fill normally, nothing to do.
3. **Fill with the suggested id.** For each anomalous target pass
   `--charpr-per-cell ROW,COL=<charpr_suggested>`.

If you skip step 1, `fill-cells` refuses (exit 3, `code_name`
`fill_charpr_script_anomaly`) rather than silently producing a 6pt raised
fill. The refusal names **every** anomalous target in one shot and carries
`suggested_flags` — the ready-to-paste `--charpr-per-cell` argument list — so
the loop closes without ever opening the header. Non-target runs are never
compared, so a genuinely superscripted footnote marker, ordinal or unit
exponent is out of scope by construction.
`visual_verify`'s `fill_charpr_script_mismatch` (T30) is the post-flight half
of the same comparison — both halves share one implementation
(`engine/scripts/charpr_script.py`) so they cannot disagree, which is the
whole point: anything the pre-flight lets through, the gate lets through.

**Expect anomalies to be common, and decide per cell.** Measured over the 10
converted corpus forms: 6 forms have at least one anomalous target and
`jeongbo-gonggae-cheongguseo` has 18 of 19. Most are a 2–5 percentage-point
`ratio` (character-width) delta — the form's own typography, not the
superscript trap. The refusal is still correct, because the post-flight gate
compares the same five properties and would HARD on those fills afterwards; a
pre-flight that passed what the gate rejects is the worst of both. So treat it
as a decision, not a rubber stamp: `suggested_flags` normalizes the cell to
body formatting, and if the cell is *meant* to carry a different style, pass
that style's id instead.
- `delete-guides`: deletes paragraphs referencing guide charPr (by color or
  explicit ids) with the T18 guard built in: table/secPr/ctrl/object
  paragraphs are never deleted.
- `normalize-clones`: removes all prior clones, recreates exactly one per
  spec, recomputes `itemCnt` from actuals, then asserts no dangling charPr
  (T22) before writing.

Idempotence contract (all four): applying an operation to its own output is
content-identical (zip member contents; timestamps ignored). `replace` needs
`--allow-missing` for the second run, `fill-cells` needs `--overwrite`.

## 4. check_residue

```
python pipeline/scripts/check_residue.py --form-profile profile.json --artifact OUT.hwpx
    [--keep-pattern REGEX] [--keep "exact anchor"]... [--fill-map MAP.json] [--out verdict.json]
```

`MAP.json` takes **either shape, at every consumer of the flag** (T35): a bare
`{key: value}` object (the `preedit replace --map` file) or a wrapper object
carrying a `fill_map` member (a `visual_verify --expectations` file). One
loader — `check_residue.load_fill_map` — serves `check_residue`,
`visual_verify` and every module checker, so one file works for all of them. A
wrapper whose `fill_map` member is not an object is a usage error naming both
shapes; it is never read as a bare map.

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
- **Prefix-preserving fills** need `--fill-map MAP.json`, not `--keep`
  (T31). Filling a labeled field keeps the label as a prefix, so the key text
  survives INSIDE the value: `" http://"` → `" http://hanbit.example.kr"`,
  `" 우(     -     )"` → the same skeleton plus the address. With the map
  declared, an occurrence of a forbidden string that lies wholly inside an
  occurrence of a declared value is attributed to that value's span; an
  occurrence anywhere else still HARDs. `--keep " http://"` cannot express
  that — it suppresses the string document-wide, including a second field you
  never filled. Guide text is never attributable (same reason it is never
  keepable). Matching is whitespace-normalized on both sides, so the form's
  skeleton spacing need not survive verbatim. The verdict carries
  `fill_attribution {keys, value_spans, occurrences, attributed,
  unattributed}` and every residue row carries `occurrences`, `attributed`,
  `at_offsets` and a `context` snippet per unattributed hit.

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
python engine/scripts/com_backend.py set-cell --file FORM.hwp --addr ROW,COL --text "값" [--table 0] --save-as OUT.hwpx [--expect-empty | --expect TEXT]
python engine/scripts/build_report.py --content bundle/content.md --form FORM.hwp > ops.json   # --dry-run: no Hancom
```

`inspect` first, always (anchors must exist before `goto_text`). Ops in
batches of 5–8 with verification between batches.

**Cell addressing (T28).** `set_cell`'s `addr: [row, col]` is the `cellAddr`
`table_map` reports; the op walks to it and verifies with `get_cell_addr()`
after every move, aborting without writing on any mismatch. The old
`row`/`col` were **keypress counts** (`TableLowerCell` × row, then
`TableRightCell` × col) — `TableRightCell` wraps across rows and
`TableLowerCell` jumps over rowSpans, so on the PPS form targeting cellAddr
(2,3) landed on (2,6), the `법인등록번호` label cell. That mode still exists
behind an explicit `"raw_traversal": true`; the validator rejects bare
`row`/`col` before Hancom starts. Always pass `expect_empty` (or
`expect: "current text"`) so a wrong landing refuses instead of overwriting.
`get_into_nth_table(n)` drifts across repeated calls inside one Hancom
session, so prefer the `set-cell` subcommand: **one invocation = one session =
one cell**, run serially, never `--kill-stale` (T21). The walk itself is
entry-point independent (it wraps), so drift cannot silently retarget it.
For `.hwpx` prefer the offline `preedit fill-cells` — no Hancom, no drift. `build_report` refuses on
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
is you, reading page PNGs against `references/visual-rubric.md`.

```
# pass 1 — machine half + vision task
python pipeline/scripts/visual_verify.py --artifact OUT.hwpx \
    [--pdf verify.pdf] [--expectations exp.json] [--png-dir DIR] [--dpi 130] \
    [--baseline BLANK.hwpx|BASE.pdf|DIR] \
    [--form-profile profile.json [--fill-map MAP.json] \
                    [--keep TEXT ...] [--keep-pattern REGEX]] \
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
  declared `fill_map` values present in the render; script/scale/offset
  inheritance on fill-modified runs (T30 `fill_charpr_script_mismatch`);
  `forbidden_text`; `layout_qa` (mapped onto rubric classes, unmapped findings
  preserved verbatim); `check_residue` with `--form-profile`; `check_density`
  with `--content`; pixel diff with `--baseline` (changed-region bboxes per
  page, so a caller can assert unchanged regions stayed unchanged).
- **`--baseline` names the BLANK FORM, so it takes one** (T35). Pass the
  `.hwpx`/`.hwp` blank and it is converted through the same ONE serial
  `com_backend.py convert` the artifact takes (never `--kill-stale`); an
  already-rendered `.pdf` or a directory of page images is used as-is. With no
  renderer on the machine, the pixel diff is reported under
  `deterministic.skipped` with a reason (and `baseline_diff.skipped`) — one
  check lost, not the whole run, and never a crash. The converted PDF is
  recorded as `baseline_diff.baseline_pdf`.
- **Residue on a FORM FILL needs a keep list.** The residue gate's forbidden
  list is auto-derived from the form scan, so on a fill every surviving label
  reads as residue and the delegate can never return 0. Forward one:
  `--keep TEXT` (repeatable) and `--keep-pattern REGEX` go straight to
  `check_residue`, and `--fill-map MAP.json` derives the standard form-fill
  keep list for you — `(anchors ∪ placeholders)` minus the entries the fill
  mapping targeted (whitespace-normalized substring match, either direction).
  `MAP.json` is the `preedit replace --map` file (a bare `{key: value}`
  object) or a wrapper object with a `fill_map` member — either shape, here and
  at every other consumer of the flag (T35). Guide text is never keepable. The
  derivation is recorded
  under `deterministic.residue_keep` (`derived_keep`, `consumed`, `unfilled`,
  `explicit_keep`, `keep_pattern`, `keep_total`) so the invocation is
  auditable. These flags without `--form-profile` are a usage error.
- **A correct fill KEEPS the label — that is the normal shape, not an edge
  case** (T31). Filling a labeled field means keeping the label as a prefix:
  a URL field goes `" http://"` → `" http://hanbit.example.kr"`, a zip field
  keeps its `" 우(     -     )"` skeleton and appends the address. The key
  text therefore survives by construction, and a derivation that assumes it
  VANISHED fails a correct fill (second clean-room run: a lost retry and a
  hand-built `--keep`). So the derivation is artifact-aware and the map is
  forwarded to the delegate:
  - a key is **consumed** when its mapped VALUE is present in the document
    (whitespace-normalized), and falls back to key-absence when the value is
    not found — no value and the key gone too is equally nothing to flag;
  - a key whose value is absent while the key text is still there is
    **unfilled**: neither kept nor consumed, so it HARDs. That is the point;
  - surviving key text inside a value is attributed to that value's SPAN, per
    occurrence — never suppressed document-wide, so a second, genuinely
    unfilled occurrence of the same key still HARDs and the finding reports
    its offset and surrounding context.
  Do not hand-build `--keep` for a prefix-preserving fill: `--keep " http://"`
  blinds the gate to every unfilled URL field in the document.
- **T30, the invisible superscript.** With an `expectations.fill_map`, every
  run whose text carries a declared value is compared against the document's
  body-baseline charPr on `supscript`/`subscript`/`ratio`/`relSz`/`offset`. A
  difference is HARD `fill_charpr_script_mismatch` (class
  `format_noncompliance`): nominal height is unchanged in this trap, so
  `charpr_check` and `style_diff` cannot see it. Only fill-modified runs are
  in scope, so intentional superscripts are never flagged. This is the
  POST-flight half; the pre-flight (`form_inspect` `script_anomaly` →
  `fill-cells --charpr-per-cell`) is under §3 and shares this comparison
  code, so a fill that passed the pre-flight cannot fail here for this reason.
- **`expectations.json`** keys: `pages_document`, `page_budget {min,max}` or
  `max_pages`, `base_pt`, `line_spacing_pct`, `margins_mm {top,bottom,left,
  right}`, `fill_map {label: value}`, `intentionally_blank [label]`,
  `blank_pages [n]`, `forbidden_text [str]`. Everything absent is listed
  under `deterministic.skipped` — the verdict says what it could NOT check.
- **`vision_verdict.json`** shape: `{schema, artifact, pdf, dpi, png_dir,
  rubric, rubric_path, acceptance, pages[], deterministic{}, vision{},
  vision_required[], loop{}, hard[], warn[], counts, verdict}`. `verdict` is one of `pass`,
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
