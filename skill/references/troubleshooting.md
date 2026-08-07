# Troubleshooting — engine-relevant trouble-table distillate

Symptom → cause → fix, engine scope only (assembly/COM/XML/layout/equation).
This IS the shipped table; the rigorloom repository keeps the full
trouble table with per-row origins (T1–T14, T26–T30) and the Lane-F
unification rows (T16–T22) alongside the plan that produced them.
Report-pipeline rows (T2 dataset downloads, T20 bundle figures) live in
the report module fragment, not here.

## TOC

- [XML/offline editing (preedit, tidy)](#xmloffline-editing)
- [COM editing and assembly](#com-editing-and-assembly)
- [Layout and spacing](#layout-and-spacing)
- [Equations (HwpEqn)](#equations-hwpeqn)
- [Environment/process](#environmentprocess)

## XML/offline editing

| id | symptom | cause → fix |
|---|---|---|
| T18 | guide-paragraph deletion collapsed layout (21 pages, 20-line hole) | deletion by charPr color hit table/secPr/ctrl paragraphs → `preedit delete-guides` has the protection guard built in (`guards.is_protected_para`); never delete guide paragraphs with hand-rolled XML edits |
| T22 | dangling charPr after clone postedit; naive `'id="34"' not in header` guard false-matches a paraPr id | guard and verification must match `<hh:charPr\b[^>]*\bid="34"` → `preedit normalize-clones` asserts this after every run |
| — | document renders BLANK in Hancom after a text replacement | a self-closing `<hp:t/>` mistaken for an opening tag produced unbalanced XML → preedit validates well-formedness of every modified member before writing; if you bypassed preedit, that is the defect |
| — | replaced text overprints at old coordinates (74-char title on top of placeholder layout) | Hancom's cached `<hp:linesegarray>` survived a text change → preedit strips the lineseg of changed paragraphs only; Hancom recomputes on open |
| — | placeholder silently not replaced (no error, no change) | old exact `">key<"` matching failed on leading/trailing run whitespace → preedit tier-A strip-compare fixes this; 0-hit keys are a hard error unless `--allow-missing` |
| T26 | replaced cell shows the value twice, concatenated (`" http://example.krexample.kr"`, hits=2); re-running grows it again | tier B (raw substring) ran over the span tier A had just rewritten, so a value containing its own key was applied twice → `preedit replace` now protects every written span for the rest of the call; one value is written once and re-runs report 0 hits |
| T27 | every fill target reports 0 hits — an empty form cell cannot be reached by `preedit replace` | an empty cell is `<hp:run charPrIDRef="N"/>` with no `<hp:t>` at all, so there is no string to key on (19/19 empty cells on the PPS form) → use `preedit fill-cells --cell ROW,COL=값` with the cellAddr `form_inspect` table_map reports; it creates the `<hp:t>`, preserves the run's charPr, and refuses a non-empty cell without `--overwrite` |
| — | `table_map` reports fewer tables/cells than the form visibly has | tables nest (6 of 12 corpus forms, depth 2) and the old non-greedy `<hp:tbl>(.*?)</hp:tbl>` paired an outer opening tag with an inner closing tag → the scanner is tag-stack based and shared with `fill-cells`, so `--table N` and `table_map[N]` are the same table |
| — | Hancom shows "복구" (recovery) warning on open | DOM re-serialization somewhere in the path → only byte-preserving string surgery on the original bytes is allowed |
| T7 | blank-paragraph cleanup near headings reassigns heading charPr (16pt→10pt) or merges paragraphs | COM delete across a paragraph boundary inherits pending charShape → blanks are cleaned OFFLINE with `tidy_hwpx` anchored to explicit paragraphs, never via COM find/delete |
| T30 | a filled value renders small and raised (~6.35pt against 10pt body) but `charpr_check --base-pt 10` and `style_diff` both pass | the fill inherited a charPr clone that is body text PLUS a trailing `<hh:supscript/>` (or a shrunken `<hh:ratio>`/`<hh:relSz>`/`<hh:offset>`) — nominal `height` never changes, so height-based proofs cannot see it → `visual_verify` with an `expectations.fill_map` compares fill-modified runs' script/scale/offset against the body baseline and HARDs `fill_charpr_script_mismatch`. Genuinely superscripted footnote markers are out of scope by construction |

## COM editing and assembly

| id | symptom | cause → fix |
|---|---|---|
| T4 | reference URLs lose their last 8 chars; garbage tail line accumulates | hyperlink end position recorded before field creation shifts offsets → re-acquire position after field creation (fixed in `insert_hyperlink`) |
| T6 | `goto_text` fails on an anchor that is visibly there | anchor spans two character runs; COM find matches within a single run → use a single-run substring, verify uniqueness in form AND content |
| T8/T10 | body text lands INSIDE an in-table label paragraph / renders center-aligned | next-paragraph move no-ops in a single-paragraph cell; the split paragraph inherits the label's centered shape → runtime guard inserts a break and applies justify (in com_backend) |
| T11 | heading pulled onto the previous page after guide-table deletion | the form used blank-paragraph stacks as page pushers → page-break-before op on the heading anchor; exclude it from tidy |
| T28 | `set_cell` destroyed a label cell; `get_into_nth_table(0)` lands elsewhere on repeated calls in one session | `row`/`col` were keypress counts, not cellAddr — `TableRightCell` wraps rows and `TableLowerCell` skips rowSpans, so on a rowspan-label form (2,3) became (2,6) → pass `addr: [row, col]` (cellAddr), which walks with `TableRightCell` and verifies `get_cell_addr()` at every step, aborting without writing; add `expect_empty`/`expect`; legacy mode needs `raw_traversal: true`. For the drift: `com_backend.py set-cell` = one session per cell, serial, never `--kill-stale` |
| T12 | table caption orphaned at page bottom | caption paragraph lacks keep-with-next → keep-with-next block list in build config |
| T16 | body top position double-counted | Hancom stacks body top = top margin + header height; feeding a measured print-face position straight into `top` double-counts → subtract header height |
| T17 | numeric layout value learned on one template is wrong on its own published compilation (170mm declared vs 163mm printed) | templates do not reproduce their compilations → layout values are per-form-family only; never transfer numbers across families |
| — | inserted body text is blue/red (guide color) or title-sized | insertion inherits the neighboring run's charPr → `insert_text` with `pt` stamps size+black; verify with `charpr_check`, not by eye |
| — | table gets numeric header row + index column 0,1,2… | a pandas DataFrame was passed → `insert_table` takes a pure 2-D list only |
| — | phrase containing a comma only partially deleted | `replace_all` splits FindString on commas → use `find_delete` for comma-bearing phrases |
| — | image inserted at native (huge) size | width/height units are mm, not HwpUnit → give `width_mm`; height follows aspect ratio |

## Layout and spacing

| id | symptom | cause → fix |
|---|---|---|
| T1 | stray blank paragraphs between subsections (2–3 line gaps) | COM `^n` find/replace has no traction on empty paragraphs → offline tidy + layout_qa gap check |
| T5 | line-spacing uniformity never passes on record-sheet forms | cover/summary pages have designed whitespace → exempt declared cover pages + bottom-10% gaps |
| T9 | form heading paragraphs flattened from 180–200% to body 160% spacing | document-wide set-line-spacing hit form-owned paragraphs → capture paragraph formats in the form baseline; style_diff paragraph check gates the restore |
| — | layout_qa flags a figure page | figure-occupied vertical spans are exempt from the gap metric; if it still flags, it is a real blank-paragraph hole |

## Equations (HwpEqn)

| id | symptom | cause → fix |
|---|---|---|
| T3 | multi-row matrix renders broken | LaTeX `\\` row separator not converted to HwpEqn `#` → eqn adapter converts; sanity check fails on leftover `\\` |
| T13 | superscript over-grabs: `x^2)` renders `2)=…` raised | bare `^`/`_` claims everything to the next space → always brace scripts (`x^{2}`, `D_{pq}`); adapter auto-braces one atom; never `\,` right after `{`; verify equations at 300 dpi, not page-level 90 dpi |
| T14 | line before a long inline equation justify-stretches with huge word gaps | wide inline equation wraps as an atomic char → promote multi-step derivations to display equations; end the lead-in clause before them |
| — | equation renders raw (`\frac`, `≤ ft`) | double-backslash LaTeX in the source → eqn.py normalizes since v0.2.1 but author single backslashes |

## Environment/process

| id | symptom | cause → fix |
|---|---|---|
| T21 | concurrent COM sessions kill each other | `--kill-stale` used name-scoped `taskkill /F /IM Hwp.exe` → per-machine lock; never name-kill while another session holds it |
| — | COM hangs on the security-approval popup | old Hancom without auto-registered FilePathCheckerModule → register the security module once, manually |
| — | COM unresponsive | orphan Hwp.exe process → close all Hancom instances before starting |
