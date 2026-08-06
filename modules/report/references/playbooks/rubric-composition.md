# Composition rubric (CONTRACT §P) — 4 binary checks

For the vision-judge (Stage 5 phase 2, Stage 5.7). **Binary only: each check
is pass or fail, no scores.** Read the contact sheet FIRST (§S); pull a
hi-res single page ONLY for a page a check flags. Acceptance means uniform
density, full body pages, readable equations, compact tables, and no
unexplained mid-page voids. **Pass rule: all
four keys below must be `true` (= defect-free) to accept the report.**

## The 4 checks

Keys are the literal `rubric` object field names emitted by
`fill_report.py` (single source of truth) — use these keys everywhere,
not numbering.

| Key | PASS | FAIL |
|---|---|---|
| `mid_bottom_void` | body pages full to the bottom margin | a body page has a large blank band mid- or bottom-page |
| `density_uniformity` | line/paragraph density even across body pages | one page visibly sparse/dense vs neighbors |
| `table_proportion` | table rows ≈1 line, cols proportioned to content | rows wrap to multiple lines, or a col is absurdly wide/narrow |
| `heading_plus_void` | headings followed by content | a heading sits at page bottom AND is followed by void |

## Explicit NON-defect (do not flag)
A heading alone at the bottom of a page, with NO void after it (content
continues on the next page normally), is **NOT a defect**. Heading *position*
is fine; heading *followed by void* is the defect. This is `heading_plus_void`,
not `mid_bottom_void`.

## Textual pass/fail examples
- `mid_bottom_void` FAIL: "p5 has a ~1/3-page white band below 표1 before
  Ⅳ starts." → need: flow next block up, or `pageBreak="CELL"
  repeatHeader="1"` split the long table (S2), or a `rewrite_para` need on
  Ⅲ. with `delta_lines: +2`.
- `mid_bottom_void` PASS: "every body page fills to within one line of the
  bottom margin."
- `density_uniformity` FAIL: "p3 is half-empty while p2 and p4 are full —
  density jumps." → need: `rewrite_para` with `delta_lines: ±1` to `±2` to
  rebalance.
- `density_uniformity` PASS: "density is consistent; no page reads
  noticeably lighter."
- `table_proportion` FAIL: "표1 rows each wrap to 2 lines; first col too
  narrow." → need: `{"type":"resize_table","index":1,
  "cols":"10,16,12,9,10,43"}` — widen the data col.
- `table_proportion` PASS: "표1 rows are single-line; cols proportioned
  (last col widest)."
- `heading_plus_void` FAIL: "Ⅳ. heading is the last line on p4, p5 top
  starts with a figure leaving a gap under the heading." → keepWithNext
  should bind heading to content; if it persists, a `rewrite_para` need
  above the heading.
- `heading_plus_void` PASS: "Ⅳ. heading is followed immediately by its
  first paragraph."

## Repair rule (§P/§Q) — needs schema
Every FAIL → write `needs.json`, an array of objects, each one of:
```json
{"type": "rewrite_para", "anchor": "Ⅲ. 본론", "delta_lines": -2, "reason": "p3 density high vs neighbors"}
{"type": "resize_table", "index": 1, "cols": "10,16,12,9,10,43"}
```
NEVER a new format knob. Writer applies the minimal delta → re-run
`fill_report.py --loop --proof --proof-needs needs.json` (same flags as
the initial call, §P) to reassemble and re-check. ≤3 proof iters, then
verdict `status: escalate_human`.

## Positive anchors (what "pass" looks like)
Use the form and any approved operator reference as positive anchors:
- Use only operator-supplied positive anchors under `<WS>/refs/`.
- Without a supplied reference, apply the binary checks without inventing a
  personal style target.
Typical positive characteristics are uniform density, full body pages, readable
equations, compact table rows, and deliberate whitespace on figure-only pages.
The void rule applies to body/text pages.

## Contact-sheet comparison procedure
1. `contact_sheet.py --pdf OUT.pdf --out-dir DIR --dpi 70 --per-sheet 6`.
2. Open `contact_N.png`; scan every body page thumbnail against all four
   rubric keys (`mid_bottom_void`, `density_uniformity`, `table_proportion`,
   `heading_plus_void`).
3. For any thumbnail that looks off, request that ONE page at hi-res to
   confirm before emitting a `need` (avoid false positives from thumbnail
   blur).
4. Emit `needs` JSON (see vision-judge template). Do not emit a need on a
   figure-only page's bottom whitespace.
