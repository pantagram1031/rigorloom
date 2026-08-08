# Operations — CLI contracts and JSON outputs

All paths are checkout-relative. Every operation is non-destructive (reads
the input, writes `--out`/`--save-as`). Exit codes follow the checker
convention where noted: 0 = pass/clean, 2 = usage/config error, 3 = finding.

## TOC

1. [probe](#1-probe) — capability probe
2. [form_inspect](#2-form_inspect) — offline form profiling (+ `--full-text`)
3. [preedit](#3-preedit) — replace (`--map` / `--at-cell`) / fill-cells / delete-guides / normalize-clones
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
    [--full-text [TABLE:]ROW,COL ...]
```

Offline (no Hancom), `.hwpx` only. `profile.json` keys: `form_hash`,
`anchors` (headings/labels, in scan order), `placeholders`, `guide_text`,
`constraints` (base_pt / line_spacing_pct / max_pages — 0 detected on
fixed-grid forms; the fill gate there is layout immutability, not budget),
`page_metrics`, `table_map` (per-table `index`/`depth`, per-cell
`addr`/`span`/size/borderFill/shading/classification/`text_preview` +
`truncated` — plus the T30 pre-flight fields
`charpr`/`script_anomaly`/`charpr_suggested` on `fill_target` cells),
`body_baseline_charpr`, `script_anomaly_targets`, `spacer_cells`,
`fill_target_count`,
`break_audit`. `--baseline` additionally writes the font/size/color/spacing
distribution `baseline.json` consumed by `style_diff`. Exit 2 on file error;
otherwise 0 (diagnostic tool, never a gate).

**`text_preview` is `text[:30]` and says when it cut** — `truncated: true`
(T34). A silent cut is worse than a short one: the 협업기간 skeleton
`"20   .    .    .  ~  20   .    .    .   (     개월)"` previews as
`"20   .    .    .  ~  20   .   "`, which HIDES the `(     개월)` blank in
its middle, and a round-3 clean-room agent reasonably concluded the skeleton
ended there. Never treat a preview as the cell's text.

**`classification` has four values, and `spacer` is the one that saves you
work.** `guide` / `static` / `fill_target` / `spacer`. A **spacer** is an
empty cell the GRID needs and no writer ever touches; it is excluded from
`fill_target_count` and listed separately under `spacer_cells`
(`{table, addr, pattern}`). Three conjunctive conditions, all read off the
table itself — there is no address list anywhere in the code:

1. **no printed content** (it would otherwise be a `fill_target`);
2. **no label neighbour** — nothing names it, so nothing can be asked for it.
   A label neighbour is a printed cell ending exactly where this one starts on
   the same row band (`법인등록번호` → the cell to its right), or a printed
   cell directly above covering **exactly** this cell's column band (a matrix
   column header). Column-band equality is the whole rule: a form title or a
   prose paragraph also sits "above" a full-width strip without delimiting a
   field, and PPS's narrow `첨부서류` at (17,0) does not own the full-width
   strip at (18,0). Two stacked full-width bands are document flow, never a
   label/value pair;
3. **filler geometry**, one of two shapes the corpus grids actually use:
   - `full_width_band` — spans every column of its table AND is shorter than
     the shortest cell in that same table that manages to print text. It spans
     the label column too, so no field can live in it, and the grid itself
     proves no text line fits at that height. PPS (1,0)/(9,0)/(12,0) at 240
     and (16,0)/(18,0) at 1280/1080 against a 1860 shortest printed cell;
   - `stub_head` — the empty corner where a header row crosses a label column:
     every other cell in its row is a printed `static`, and the cell directly
     beneath it, sharing its exact column band, prints text. PPS (13,0), above
     `협업업체` and beside `업 체 명 / 대표자 / 전 화 / 사업장주소`.

On the PPS 협업승인신청서 that is 19 empty cells → **13 `fill_target` + 6
`spacer`**. A genuinely empty fillable cell keeps its label neighbour and
stays a `fill_target`: (2,7), the blank beside `법인등록번호`, is empty, is
not thin, and is named — so it is still yours to fill. Spacers carry no T30
pre-flight fields, because nothing will ever be written into them.

**Contract: structure only.** The profile carries anchor/guide strings, not
the document body. Do not dump section XML into context.

**`--full-text [TABLE:]ROW,COL` is the one documented escape from that
contract** (repeatable; `TABLE:` defaults to 0). It emits `full_text`
`[{table, addr, text, truncated_preview, runs:[{index, text, charpr}]}]` —
the **exact** run text, whitespace intact — for the cells you name and no
others. It is opt-in **per cell** on purpose: the key absent from the profile
unless requested, no flag that dumps the body, and each request is a decision
you can justify. Reach for it only when you need a byte-exact string, which
in practice means a `replace --map` key or a `check_residue --fill-map`
entry. To *edit* a printed skeleton you do not need the string at all — use
`preedit replace --at-cell ROW,COL=값` (§3), which addresses the run instead.
`runs[].index` IS `--at-cell`'s `#RUN` (one shared enumerator), and the
string round-trips: fed back as a `replace` key it hits exactly once.

## 3. preedit

Four offline operations (`replace` has two keying modes — string and
address); all validate every modified XML member is
well-formed BEFORE writing (a malformed member renders the whole document
blank in Hancom — structurally impossible here), and all strip the cached
`<hp:linesegarray>` of any paragraph whose text changed (stale linesegs
overprint at old coordinates).

```
python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json [--allow-missing]
python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx [--table 0] --at-cell 'ROW,COL[#RUN]=TEXT' ... --at-cell-append 'ROW,COL[#RUN]=TEXT' ... [--at-cell-map AT.json] [--at-cell-expect 'ROW,COL[#RUN]=SUBSTR' ...] [--at-cell-charpr 'ROW,COL[#RUN]=ID' ...]
python engine/scripts/preedit.py fill-cells IN.hwpx --out OUT.hwpx [--table 0] --cell ROW,COL=TEXT ... [--map CELLS.json] [--overwrite] [--charpr ID] [--charpr-per-cell ROW,COL=ID ...]
python engine/scripts/preedit.py delete-guides IN.hwpx --out OUT.hwpx [--color '#0000FF'|blue] [--charpr-ids 5,6]
python engine/scripts/preedit.py normalize-clones IN.hwpx --out OUT.hwpx --clone SRC:NEW [--set textColor=#000000] [--repoint FROM:TO:TEXT]
```

**Which one fills a form.** Look at `table_map` first, and split on whether
the cell already prints something:

| the cell | use |
|---|---|
| `classification: fill_target` — *genuinely empty*: `<hp:run charPrIDRef="N"/>` with no `<hp:t>` at all (19 of 19 empty cells on the PPS 협업승인신청서) | **`fill-cells --cell ROW,COL=값`** (T27). There is no string to key on, so `replace --map` structurally cannot reach it |
| already prints a **seat**: a skeleton the form typeset for you to write over or into — `" 우(     -     )"`, `" http://"`, `"20   .    .    .  ~  20   .    .    .   (     개월)"` | **`replace --at-cell ROW,COL=값`** or **`--at-cell-append`** (T34). Address-keyed, so you never need the skeleton's exact internal whitespace |
| a literal, document-unique placeholder string you already hold (`[제목]`) | **`replace --map`** |

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
- `replace --at-cell` — **address-keyed, no string at all** (T34). The form's
  printed seats are exactly the strings you cannot type reliably: their
  internal spacing is invisible in a 30-char preview and absent from
  `anchors`. So key on the address instead. `ROW,COL` is the `cellAddr`
  `table_map` reports and `--table N` is the same index as `fill-cells`
  (shared scanner). `#RUN` is the 0-based text-run index within the cell, the
  same enumeration `form_inspect --full-text` reports.
  - **Two explicit modes, never guessed.** `--at-cell ROW,COL=TEXT` replaces
    the run's **whole** text. `--at-cell-append ROW,COL=TEXT` keeps the
    printed prefix and appends — `" http://"` → `" http://host.kr"`, which is
    the *normal* shape of a labeled field, not an edge case (T31). Pick the
    one you mean; the tool will not infer it.
  - **Multi-run cells refuse.** A cell with more than one text run exits 2
    with `code_name: at_cell_run_ambiguous` and a `runs` array giving every
    index with its exact text. Neither "first run wins" nor "flatten the
    cell" is offered: PPS (15,0) carries the regulation sentence, the
    `년 월 일` 신청일 line, `신청인`, `(서명 또는 인)` and `조달청장 귀하` as
    separate runs, and either guess deletes real content. That refusal
    listing is also the cheapest way to learn the indices.
  - A cell with **no** text run is refused and pointed at `fill-cells` (T27).
  - `--at-cell-map AT.json` is `{"11,2": "값", "15,0#2": {"text": "…",
    "mode": "append"}}` — a bare string means `replace`.
  - `--at-cell-expect ROW,COL[#RUN]=SUBSTR` is a pre-write precondition,
    compared with **all whitespace removed on both sides**, so you can assert
    `우(-)` or `개월` without counting spaces. A mismatch writes nothing.
  - `--at-cell-charpr ROW,COL[#RUN]=ID` repoints the run's charPr; it is also
    how you get past the T30 pre-flight refusal below (the refusal prints the
    flag with `#RUN` filled in, and that form is accepted even if your
    `--at-cell` named the cell without `#RUN`).
  - Same guards as `fill-cells`: stale-lineseg strip on changed paragraphs
    only, well-formedness of every modified member before writing, T30
    charPr pre-flight, T22 dangling-charPr assertion when a charPr is
    repointed, duplicate targets are a hard error, and a refusal anywhere
    writes nothing. Re-runs are no-ops in **both** modes (`action: "noop"`,
    `replaced: 0`), so append never doubles a value.
  - Output JSON: `{"ok": true, "mode": "at-cell", "table": n,
    "tables_total": n, "replaced": n, "body_baseline_charpr_id": "0",
    "cells": [{"addr": [r, c], "run": i, "mode": "replace"|"append",
    "hits": 0|1, "action": "replaced"|"appended"|"noop", "before": "…",
    "after": "…", "charpr": id|null}]}`. `before` is the seat's **exact**
    text — that is where you read it from, not from the section XML.
  - `--map` and `--at-cell*` in one call is a usage error (exit 2). Chain two
    calls: mixed in one, string replacement and address offsets rewrite each
    other.
- `fill-cells`: addresses cells by the `cellAddr` **`table_map` reports** —
  `--cell ROW,COL=TEXT` (repeatable) or `--map` `{"2,3": "값"}`. `--table N`
  (default 0) indexes tables in document order, nested tables included and
  counted separately (outer first; `table_map` carries the same `index` and
  a `depth`). Merged cells own the top-left coordinate only, so addresses are
  not contiguous — a coordinate a rowSpan/colSpan covers has no cell and is a
  hard error listing the real addresses. Creates the `<hp:t>` inside the empty
  run and **preserves that run's charPr**. A non-empty target is refused
  unless `--overwrite`; a refusal anywhere in the batch writes nothing at all.
  Output JSON: `{"ok": true, "table": n, "tables_total": n, "filled": n,
  "body_baseline_charpr_id": "0", "cells": [{"addr": [r, c], "hits": 1,
  "action": "filled"|"overwritten", "previous": "…", "charpr": "0"|null}]}`.
  - **`--charpr-per-cell ROW,COL=ID` (repeatable) is the charPr flag you will
    actually need**, and it belongs in the fill command you type — not only in
    the T30/T32 prose below. It sets **one** target's charPr and wins over
    `--charpr`; targets it does not name keep their own. The T30 pre-flight
    emits exactly this flag list as `suggested_flags`, so the normal fill call
    is `fill-cells --cell … --charpr-per-cell ROW,COL=<charpr_suggested> …`,
    not a bare `fill-cells --cell …`. An address it names that is not in the
    fill list, or a duplicated address, is a usage error — not a silent no-op.
  - `--charpr ID` **applies to the whole batch** (T32) and is only safe when
    every target in the call shares a charPr — which is precisely what the T30
    pre-flight breaks (anomalous cells need repointing, normal ones must be
    left alone). Prefer `--charpr-per-cell`.
  - Either flag then also runs the T22 dangling-charPr assertion before
    writing.

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
the loop closes without ever opening the header. `replace --at-cell` runs the
**same** pre-flight on the seat run it is about to rewrite, and its refusal
carries `--at-cell-charpr ROW,COL#RUN=<id>` instead — so T34's address-keyed
path cannot be used to route around T30. Non-target runs are never
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
content-identical (zip member contents; timestamps ignored). `replace --map`
needs `--allow-missing` for the second run, `fill-cells` needs `--overwrite`;
`replace --at-cell*` needs no flag — a run already holding the final value is
reported `action: "noop"`.

Geometry contract: an `--at-cell` / `fill-cells` edit changes text runs and
the cached `<hp:linesegarray>` of the paragraphs it touched, and **nothing
else** — cell count, addresses, spans, borderFill and cellSz are byte-identical
(fixed by regression on the real PPS seats).

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
    [--accept-without CHECK ...] \
    [--attempt M --max-fix-attempts N] --out visual_verdict.json

# pass 2 — merge the vision verdict you wrote
python pipeline/scripts/visual_verify.py --artifact OUT.hwpx --pdf verify.pdf \
    --expectations exp.json --vision-verdict vision.json --out visual_verdict.json
```

**Exit codes — the whole table, one row per terminal state.** Nothing else is
reachable; in particular **exit 1 is not in the contract** and a run that
produces it is a bug (T36).

| `verdict` | exit | meaning |
| --- | --- | --- |
| `pass` | 0 | accepted — both halves clean AND every SAFETY check ran (or was waived) |
| `deterministic_pass` | 0 | `--deterministic-only` smoke check; `acceptance: false` by construction |
| `vision_pending` | 3 | machine half clean, vision half still owed |
| `fail` | 3 | a HARD finding, deterministic or vision |
| `safety_incomplete` | 3 | nothing failed, but a SAFETY check never RAN and was not waived |
| `usage_error` | 2 | bad input, unreadable file, unwritable `--out` |

- **`acceptance: true` is a claim that every SAFETY check RAN** (T36). The
  SAFETY set is `page_parity`, `xml_wellformedness`, `check_residue`,
  `empty_cell_expected_fill`, `fill_charpr_script_mismatch` — named once, in
  `visual_verify.SAFETY_CHECKS`, and published in every verdict under
  `deterministic.safety_checks`. If any of them lands in
  `deterministic.skipped_checks`, the verdict is `safety_incomplete` (exit 3)
  with a HARD `acceptance_safety_skipped` naming which ones and why. The pixel
  diff is deliberately NOT in the set (T35: a renderer-less machine loses one
  check, not the run) and neither are the `format_noncompliance/*` tolerance
  legs — declining to pin a tolerance is not hiding a defect class.
- **Waive a check only on the record.** `--accept-without CHECK` (repeatable,
  closed vocabulary = the SAFETY set) lets acceptance proceed without one, and
  the verdict carries `acceptance_waivers: [...]` plus the unwaived remainder in
  `acceptance_blockers`. Waiving is per check, never a blanket switch, and it
  hides nothing: the skip is still reported in `deterministic.skipped`.

- **Rendering.** `--pdf` if you have one; an `.hwpx` without one goes through
  ONE serial `com_backend.py convert` (never `--kill-stale`). No Hancom and
  no `--pdf` is a usage error, never a pass. Pages are rasterized to
  `--png-dir` (default `<pdf>_pages/`) at `--dpi` (default 130). Equation
  scope errors (T13) need a separate `--dpi 300` run on that page.
- **Deterministic backstops**, all merged into one findings list: hwpx
  section/header XML validity (T23 `artifact_malformed`); zero-text document
  and zero-content page (T25 `blank_render`); stored `PrintInfo/PrintMethod`
  plus `pages_document` vs `pages_pdf` (W6.2 `imposition_mismatch`, see the
  page-count sources below); declared
  page budget; declared `base_pt` / `line_spacing_pct` / `margins_mm`;
  declared `fill_map` values present in the render; script/scale/offset
  inheritance on fill-modified runs (T30 `fill_charpr_script_mismatch`);
  `forbidden_text`; `layout_qa` (mapped onto rubric classes, unmapped findings
  preserved verbatim); `check_residue` with `--form-profile`; `check_density`
  with `--content`; pixel diff with `--baseline` (changed-region bboxes per
  page, so a caller can assert unchanged regions stayed unchanged).
- **`pages_document` is never yours to remember** (T36). Page parity takes the
  first source it can get and records which in
  `deterministic.pages_document_source`: `conversion` (Hancom's own `PageCount`,
  when this script did the convert) → `expectations` (an explicit declaration) →
  `artifact_layout_cache` (derived here from the artifact's own
  `<hp:lineseg vertpos>` cache, counting the points where `vertpos` stops
  increasing; cell-relative linesegs inside `hp:tc`/`hp:subList` are excluded).
  Parity skips only when all three are unavailable, and the reason then names
  which leg was missing. The derived source is honest about its limits: the cache
  under-counts when the body lives inside tables and goes stale after an offline
  XML edit (T24), and n-up imposition can only FOLD pages, so on that source only
  `pages_pdf < pages_document` is HARD — the other direction is a WARN naming
  both explanations. An authoritative source keeps both directions HARD.
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
  auditable. `--keep` / `--keep-pattern` without `--form-profile` are a usage
  error.
- **`--fill-map` and `expectations.fill_map` are ONE concept, not two inputs**
  (T36). They used to be different: the flag drove the residue keep derivation,
  while the *expectations member* was what activated the declared-value presence
  check (`empty_cell_expected_fill`) and the T30 charPr post-flight — so a caller
  who passed only the flag got a verdict with both of those in `skipped[]`.
  Passing `--fill-map` now **seeds** `expectations.fill_map`, so one map drives
  all three consumers and `deterministic.fill_map_source` says where it came from
  (`cli`, `expectations`, or `cli+expectations`). Passing the same expectations
  file to both flags is the blessed invocation; passing two **different** maps is
  a usage error, because there is no honest answer to which one the artifact was
  filled with. `--fill-map` alone no longer needs `--form-profile` (it is
  meaningful without the residue delegate); `--keep`/`--keep-pattern` still do.
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
- **`visual_verdict.json`** shape: `{schema, artifact, pdf, dpi, png_dir,
  rubric, rubric_path, acceptance, acceptance_waivers[], acceptance_blockers[],
  pages[], deterministic{}, vision{}, vision_required[], loop{}, hard[], warn[],
  counts, verdict}`. `verdict` is one of `pass`, `fail`, `vision_pending`,
  `deterministic_pass`, `safety_incomplete`, `usage_error` — see the exit table
  above. `deterministic` carries `safety_checks[]`, `skipped[]` (human
  `"check: reason"` strings), `skipped_checks[]` (the keys alone),
  `pages_document_source` and `fill_map_source`.
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
