# doc_core: one document layer for every surface

`runtime/scripts/rt_doc.py` (installed as `rigorloom_runtime.rt_doc`) is the
only place Rigorloom touches a document's contents for the new document verbs.
The CLI, the MCP tools and the UI call its functions; none of them talk to the
HWP engine or to `rt_kit` themselves. The contract is
`doc-core-api.md` in the product brief; this page says how this implementation
behaves.

Every function returns `{"ok": true, ...}` or
`{"ok": false, "error": {"code", "message", "at"?, "i"?, "step"?, "done"?,
"candidates"?, "retryable"}}` and never raises.

## With and without the engine

If `RIGORLOOM_HWP_ENGINE` points at a folder with `kit_api.py` (or an
`hwp_engine` package with one is importable), rt_doc starts one engine worker
(`kit_api.py serve` on pipes, with its cache on) the first time it needs it and
stops it when the process exits. Pipes work the same on Windows and Linux.

Without the engine, `.hwpx` files still work for:

- `open`, `outline`, `read`, `find`, `diff`
- `edit` with `set`, `replace`, `table.set_cells`, `fill` and `delete` of a
  cell's text, as long as the new text has no line breaks

Everything else (`.hwp`, new paragraphs or tables, styles, pictures, equations,
pages, rendering, conversion) answers `capability_unavailable` with a
`reason`. `geometry`, `hit_test`, `caret_rect`, `png` rendering and `docx`/`md`
conversion need engine functions that are still being added; until the engine
has them they answer `capability_unavailable` with reason
`engine_function_missing`, and they start working without a change here once
it does.

## Addresses

| Address | Means |
|---|---|
| `p12` | top-level paragraph 12, counting through all sections from 0 |
| `p12:5-18` | characters 5 to 18 of it (used by `replace` and in match lists) |
| `t3` | table 3 in document order, nested tables included |
| `t3/r2` | row 2 of it (for `table.add_row` / `table.delete_row`) |
| `t3/r2/c1` | the cell at row 2, column 1; inside a merged cell it means the merged cell |
| `t3/r2/c1/p0` | paragraph 0 of that cell |
| `h:"제목"` | the heading with that text, or the only heading starting with it |
| `place:<id>` | a fill seat from `outline()` |
| `page:4` | page 4, counted from 1 (engine only) |

The numbering is the engine's own (`hnc_edit`): a test checks paragraph counts,
paragraph text and cell paragraphs against the engine on every engine fixture.
An address that does not resolve gives `bad_address` with `candidates`: the
nearest headings, place ids or valid addresses.

## Reading

`open` gives the rev (the first 12 hex digits of the file's sha256), the
format, sections, fonts and, with the engine, the page count and the fonts the
layout had to substitute. `outline` lists headings, tables and fill places.
Headings come from outline paragraph shapes and heading styles; with the engine
also from its form analysis, and without it a short all-bold line counts as a
heading. `read` returns blocks (`para`, `heading`, `table` with its cell grid);
reading `h:"..."` returns that heading and the paragraphs up to the next
heading at the same level or above. `find` searches every paragraph, cells
included, and reports offsets into the paragraph's text.

## Editing

```python
r = rt_doc.read("보고서.hwpx", "p4")
rt_doc.edit("보고서.hwpx", [
    {"op": "set", "at": "p4", "text": "새 문장", "expect": r["blocks"][0]["text"]},
    {"op": "insert_after", "at": "p4", "markdown": "- 덧붙인 문단"},
    {"op": "table.set_cells", "at": "t1/r1/c0", "grid": [["2026", "완료"]]},
], base=r["rev"], out="보고서.new.hwpx")
```

- `base` must be the file's current rev, otherwise `stale` and nothing happens.
- Every op is checked before anything is written: addresses, `expect`
  (`expect_mismatch`), two ops changing the same text (`conflict`).
- `replace` without `all: true` that matches more than once refuses with
  `ambiguous_match` and lists every match (`p3:10-14`, ...) in `candidates`;
  pass one of them as `at`. An integer `expect` on `replace` is the number of
  matches you expect.
- With the engine, all ops become one engine edit script. They run from the
  end of the document backwards, so every address means what it meant in
  `base`. If a step fails, nothing is written and the error names the op (`i`,
  `at`), the engine step (`step`) and the ops that had run (`done`).
- `insert_after` types the lines after the paragraph the way Enter does in
  Hancom, so new paragraphs take the neighbour's numbering, indent and shape.
  List markers and `#` in the markdown are dropped for that reason. `like`
  copies another paragraph's style and character shape onto them.
- `insert_equation` takes `latex` (converted by `engine/scripts/eqn.py`, whose
  warnings come back under `applied[].warnings` and whose refusals stop the
  edit) or `hwpeqn`. `base_pt` is not supported by the engine yet and is
  reported as a warning. The engine sizes equations with a Node helper; where
  that helper is not set up the engine worker stops, the edit fails, and the
  next call starts a new worker.
- The result has `rev_before`, `rev`, `out`, `applied`, `remap` (addresses
  that moved: `{"from": "p3", "to": "p5"}`, `"to": null` when deleted, rows of
  tables too), and with the engine `changed_pages` (by page hash) and
  `signals` on those pages: `lone_heading`, `bottom_heading` (3 lines or fewer
  after it), `table_split`, `caption_split`, `widow`, `orphan`, `top_blank`,
  plus one `approx` entry naming the fonts the layout substituted.
- The input is never overwritten unless `in_place=True`; by default the
  result goes next to it as `<name>.edited.hwpx`. Files are written to a temp
  file in the target folder and moved into place.
- `preview=True` writes to a temp copy and adds `changed: [{i, page, rect}]`.
  `rect` stays `null` until the engine has `geometry`.

## Rendering and pages

`render(path, pages, scale=2.0, fmt="png")` uses the engine's `png` when it
has one; otherwise it asks the engine for a PDF of those pages and rasterizes
it with pypdfium2 (optional; without it PNG rendering is
`capability_unavailable`). `fmt="pdf"` writes one PDF. `pages(path)` gives the
page count, the paragraph each page starts with and that page's signals.

## Tests

`tests/test_rt_doc.py`. The built-in path runs everywhere on Rigorloom's own
fixtures. The engine tests run when `RIGORLOOM_HWP_ENGINE` is set; they read
the engine's fixtures from the engine folder and never copy them. When the
Hancom fonts are not installed they build a box-glyph stand-in font so the
engine's layout can run; page geometry is then approximate, so the tests check
structure, not positions.

```sh
python -m pytest tests/test_rt_doc.py
RIGORLOOM_HWP_ENGINE=/path/to/engine python -m pytest tests/test_rt_doc.py   # needs fonttools, pypdfium2
```
