# Hancom acceptance — run 02 (E3.2)

2026-09-05, writer tip `71e2369` (`origin/claude/engine-e3-writer-colpr-order`,
branch `claude/engine-e3-accept-02`). Hancom Office closed at the start;
`Hwp.exe` process-busy checked clear via `tasklist /FI "IMAGENAME eq
Hwp.exe"` before each of the four legs below (single COM session at a time,
strictly serial). `hwpx_lint.py --section-order` ran clean (`ok: 4 file(s),
1 check(s), no warnings`) on all four edited inputs before any COM leg. All
four ran to completion via `engine/scripts/hwpx_accept.py` (official pyhwpx
Automation only; harness always exits 3, never promotes).

Sources: (a)/(c) a fresh `hwpx_write.py roundtrip` of the corpus form, (b)
`hwpx_write.py blank`, (d) `tests/corpus/render-check/render-check-01.hwpx`
fetched read-only from `origin/claude/engine-e2-converge-3` (unmodified,
Rigorloom-authored, 51 features: headers/footers/footnotes/endnotes/columns/
equations). A unique text marker was inserted into the first `<hp:t>` of
`Contents/section0.xml` in each before the harness ran (outside the harness,
which never edits, only verifies).

## Verdicts

| Source | open_no_repair | save_new_path | close | reopen | edit_preserved | structures_preserved | bindings_valid |
|---|---|---|---|---|---|---|---|
| `accept-gianmun-byeolji-1ho.json` | pass | pass | pass | pass | pass | pass (3 tbl, 67 p, unchanged) | pass |
| `accept-blank-package.json` | pass | pass | pass | pass | pass | pass (0 tbl, 1 p, unchanged) | pass |
| `accept-kstartup-jiwon.json` (largest form) | pass | pass | pass | pass | pass | pass (42 tbl, 798 p, unchanged) | pass |
| `accept-render-check-01.json` (NEW, 51-feature doc) | pass | pass | pass | pass | **fail** (`edit_marker_not_found`) | pass (6 tbl, 227 p, unchanged) | pass |

27/28 checks passed. No repair/recovery dialog was suspected on any open or
reopen — window titles matched run-01's pattern exactly (generic "빈 문서 1 -
한글" for a/c/d, the actual filename for b) with no "복구" string anywhere.

## Diffs vs run 01

- (a), (b), (c): **no diffs**. Same 7/7 pass, and `structures_preserved`'s
  `qname_count_delta` is byte-for-byte identical to run 01 for the blank
  package (same 18 keys/values); (a) and (c) again show an empty delta.
  Writer content relevant to these three legs did not change between the
  two tips (the only diff, `71e2369`, adds a read-only lint check).
- (d) is new in run 02 — no run-01 baseline.

## (d) render-check-01 — `edit_preserved` fail, root-caused

The harness's `edit_preserved` check calls `hwp.GetTextFile("TEXT", "")` on
the reopened candidate and looks for the marker substring in that plain-text
export. It came back `edit_marker_not_found`. Root cause: the "first `<hp:t>`"
in this document's `section0.xml` falls inside a **header** run (its text
reads `render-check-01 페이지 머리말 (header)`), not the body flow —
`GetTextFile("TEXT", "")` exports body paragraph text and does not include
header/footer object content. This was confirmed structurally: the marker
string `RIGORLOOM-E3-ACCEPT-RENDERCHECK-02` **is present, byte-for-byte, in
`Contents/section0.xml` of the Hancom-saved candidate** (checked directly by
unzipping the candidate and searching every XML part). So the edit *was*
preserved by Hancom; the fail is a gap in this check's extraction method for
header-anchored text, not evidence of data loss. Flagging for a future run:
place the marker in a body paragraph, not "the first `<hp:t>` found," for
any source with header/footer content.

## (d) — did Hancom preserve the 51 features' structures?

Table and paragraph counts are unchanged (6 tbl, 227 p) — the harness's own
pass/fail policy for `structures_preserved`. The full `qname_count_delta`
(computed via the repo's lexical `XmlNode` reader over the whole package, the
same mechanism run 01 used) is **not** empty like (a)/(c), unlike the smaller
~30-element metadata delta run 01 noted for the blank package. Two clusters:

- **Removed** (style-catalog definitions in `header.xml`, presumably
  de-duplicated/consolidated on save): `hh:paraHead` -11, `hh:heading` -5,
  `hh:border` -5, `hh:breakSetting` -5, `hh:paraPr` -5, `hp:run` -7,
  `hh:charPr`/`hh:underline`/`hh:strikeout`/`hh:shadow`/`hh:offset`/
  `hh:ratio`/`hh:fontRef`/`hh:spacing`/`hh:outline` -3 each, `hh:numbering`/
  `hh:numberings`/`hh:bullets`/`hh:bullet`/`hh:img` -1 each.
- **Added** (border-fill / run-default plumbing, plus font-table growth
  paralleling the blank-package pattern): `hp:default`/`hp:switch`/`hp:case`
  +19 each, `hc:left`/`hc:right`/`hc:next`/`hc:prev` +14 each, `hh:margin`/
  `hh:lineSpacing` +14 each, `hp:t` +12, `hp:stringParam` +4, `hh:font`/
  `hh:typeInfo` +7 each, `opf:meta` +5, `hp:autoNumFormat` +3,
  `hp:integerParam`/`hh:trackchageConfig` +1 each.

Reading: the body/paragraph/table flow (what `structures_preserved`'s policy
checks, and what carries the document's visible content) round-trips intact,
same as the other three legs. The property-definition catalog was
substantially restructured — consistent in *kind* with the blank package's
already-flagged header normalization, but much larger here because a
51-feature document carries many distinct paragraph/char styles for Hancom
to consolidate. **Not proven**: that every one of the 51 features renders
identically — this harness is COM-Automation-only (open/save/close/reopen/
text/counts), it does not re-render to PDF or inspect page layout, so a
qname-count balance is evidence of structural survival, not visual proof.

## Not done here

- The writer was not modified. `structures_preserved`'s policy (table +
  paragraph counts) did not fail on any leg, so no writer-side finding to
  record.
- `source`/`candidate`/title absolute paths were redacted to `<scratchpad>`
  before commit; `pipeline/scripts/privacy_scan.py` (which per T-notes now
  catches JSON-escaped `\\` paths too) was run over the four committed JSON
  files with 0 HARD findings.
