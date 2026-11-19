# doc_core: one document layer for every surface

`runtime/scripts/rt_doc.py` (installed as `rigorloom_runtime.rt_doc`) is the
only place Rigorloom touches a document's contents for the new document verbs.
The CLI, the MCP tools and the UI call its functions; none of them talk to the
HWP engine or to `rt_kit` themselves. The contract is
`doc-core-api.md` in the product brief; this page says how this implementation
behaves.

Every function returns `{"ok": true, ...}` or
`{"ok": false, "error": {"code", "message", "retryable", ...}}` and never
raises. A wrong argument type (a path that is not a string, ops that are not a
list, text that is not text) is `bad_input`, never `internal`.

## Errors

| Key | When | Meaning |
|---|---|---|
| `code`, `message`, `retryable` | always | see the table below |
| `at` | when an address or file is involved | the address (or output path) the error is about |
| `i` | edit | the index of the op in `ops` that failed or was refused |
| `step` | edit, engine | the index of the failing step in the engine's edit script (not the op) |
| `done` | edit, engine | the op indexes whose steps had all run before the failing step; nothing was written |
| `engine_done` | edit, engine | the engine's own record of the steps that ran |
| `written` | edit | `false`: no file was changed |
| `candidates` | `bad_address`, `ambiguous_match`, unknown style | addresses (`p3`, `t1/r2/c0`, `h:"..."`, `place:<id>`) to try instead; never empty while the document has paragraphs |
| `range` | `bad_address` for a page or offset | `[lo, hi]`, the valid pages (`[1, count]`) or offsets (`[0, length]`) |
| `rev` | `stale` | the file's current rev |
| `total` | `ambiguous_match` | how many matches there were |
| `expected`, `actual` | `expect_mismatch` | what `expect` said and what is there (text, or a match count) |
| `reason` | `capability_unavailable` | why: `engine_not_configured`, `engine_path_missing`, `engine_function_missing`, `structural_edit_unsupported`, `hwp_binary_unsupported`, `rasterizer_missing`, `page_layout_unavailable`, ... |
| `fn`, `engine_fn` | engine errors | the engine function involved |

| Code | Retryable | Means |
|---|---|---|
| `bad_input` | no | the request is malformed: wrong types, unknown op, bad regex, an output that is the input (or a link to it), a precondition on an op that has none |
| `bad_address` | no | an address that is malformed or does not resolve (with `at` and `candidates`), or a page or offset out of range (with `range`); never `bad_input` |
| `not_found` | no | a missing file, a missing output folder, `replace` text that does not occur, a missing picture |
| `stale` | yes | `base` is not the file's current rev (also when another writer replaced the file during an in-place edit); read again |
| `busy` | yes | another rt_doc writer holds the destination's lock; retry |
| `locked` | yes | another program has the file open (Windows sharing violation on read or replace) or the file is not accessible; close it and retry |
| `expect_mismatch` | no | `expect` did not hold |
| `ambiguous_match` | no | `replace` without `all: true` matched more than once |
| `conflict` | no | two ops in one edit touch overlapping text or something another op removes |
| `capability_unavailable` | no | this installation cannot do it; see `reason` |
| `engine_timeout` | yes | the engine did not answer within `RIGORLOOM_DOC_ENGINE_TIMEOUT` seconds (start, send and wait all count); the worker is restarted |
| `engine_unavailable` | yes | the engine worker could not start or stopped |
| `engine_protocol` | no | the engine answered something that does not have the doc_core shape |
| `internal` | no | a bug; nothing was written |

The codes are declared in `runtime/scripts/rt_codes.py` (`DOC_CORE_CODES`,
plus `capability_unavailable` in `DOMAIN_CODES`). `bad_input` and
`bad_address` are usage errors for the CLI (exit 2). An adapter that frames a
doc_core `internal` for the runtime transport reports `internal_error`.

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
| `p12:5-18` | code points 5 to 18 of its text (used by `replace` and in match lists) |
| `t3` | top-level body table 3 in document order (nested tables not counted) |
| `t3/r2/c1/t0` | the first table nested in that cell (`.../t0/r0/c0/p0` goes on below it) |
| `t3/r2` | row 2 of it (for `table.add_row` / `table.delete_row`) |
| `t3/r2/c1` | the cell at row 2, column 1; a covered (merged-away) coordinate means its top-left anchor cell |
| `t3/r2/c1/p0` | paragraph 0 of that cell |
| `h:"제목"` | the heading with that text, or the only heading starting with it |
| `place:<id>` | a fill seat from `outline()` |
| `page:4` | page 4, counted from 1 (engine only) |

Edit results carry `remap`: `{"from", "to"}` for every top-level paragraph,
table, table row and cell paragraph whose address changed (`to` is `null`
when it was deleted). An address below a listed one follows its longest listed
prefix (`t1 -> t2` makes `t1/r0/c3` `t2/r0/c3`); `rt_doc.follow_remap(remap,
at)` does that. The map is computed from the ops, not guessed, and checked
against the written document; if the document does not confirm it, the result
says `remap_approx: true` and the map is a text alignment, except that an edit
which removes something (a paragraph, table, row or cell paragraph) the
document does not show removed is refused with `internal` and `written: false`
instead of being reported done. When typed text has
line breaks, the paragraph keeps its address (it holds the first line) and the
new paragraphs follow it.

The numbering is the engine's own (doc-core-api.md, ruling 2026-11-19): `p<N>`
and cell paragraphs match `hnc_edit` (a test checks counts and text on every
engine fixture), and `t<N>` counts top-level body tables as `hnc_addr` does.
Inside `hp:switch` only the branch layout uses (the first `hp:case`, else
`hp:default`) has table addresses; tables in headers, footers, notes,
captions and text boxes have none. Offsets everywhere count Unicode code
points of a paragraph's text. The shared fixture
`tests/fixtures/doc_core/addressing.hwpx` (nested table, merged cell,
`hp:switch`, two forms with the same labels; built by `build_addressing.py`,
expected answers in `addressing.json`) runs in both repos.
An address that does not resolve gives `bad_address` with `candidates`: the
nearest headings, place ids or valid addresses.

## Fill places

`outline()` lists `places: [{id, at, label, kind, value, filled, page?}]`, and
`place:<id>` addresses one. Without the engine they are:

- click-here fields (누름틀, `fieldBegin type="CLICK_HERE"`): label = its
  `Direction` text, kind `field`, at = the paragraph that holds it; `fill`
  types inside the field;
- an empty table cell labelled by the cell to its left (else above), kind `cell`;
- a blank paragraph right under a heading: kind `body`;
- a blank label line (`성명: `, `성명: ___`; the rule is in doc-core-api.md,
  "Label lines and heading keys"): kind `cover_field`, or `cell_field` in a
  cell. `fill` keeps the label, the colon and the white space after it and
  replaces the rest (`성명: ` becomes `성명: 둘째`).

With the engine, a cell whose paragraphs hold a table or picture is not
listed (fill cannot type there). An engine whose `outline` takes
`known=[ids]` is asked for its places that way, with the ids from the lineage
cache below; an engine without it (or that rejects the argument) is asked for
`analyze()` as before.

A filled cell and a text cell are the same bytes (amendment 2026-11-19
05:50Z), so `outline().places` lists a text cell only when its id is known
(rt_doc filled it; it is then labelled as when it was blank). A label comes
from the cell to the left, else the one above, never from an empty cell or a
known filled one. `place:<id>` resolves against the identity hash of every
cell, listed or not, so a seat filled elsewhere can still be read and filled
again by its id.

With the engine they are its form analysis (`analyze`), plus click-here
fields it does not list.

An id hashes an identity that filling cannot change (ruling 2026-11-19):
`place_id(*parts)` = the first 12 hex of the sha256 of the parts joined by
NUL (`rt_doc.place_id`), with parts

| Seat | Parts |
|---|---|
| cell | `"cell"`, the table's `hp:tbl @id` (its address when it has none), row, col |
| body seat | `"body"`, the text of the heading above it, how many earlier headings have that text |
| label line (`성명: ...`) | `"field"`, the label, how many earlier lines have that label, filled or not |
| click-here field | `"click"`, its name (else prompt), how many earlier click-here fields have that name |
| anything else | its kind, its label, how many earlier seats of that kind have that label |

So two forms with the same labels get different ids, and typing into one seat
never moves an id to another. In the rare case that two seats still hash
alike, each is listed as `<id>@<at>` and `place:<id>` alone is refused with
both as candidates.

`places_complete` says whether the list covers every kind of seat in the
document; when it is `false`, `places_reason` says what is missing (form
controls such as check boxes without the engine, a field across paragraphs, a
failed engine analysis). A filled seat stays listed: when rt_doc writes a
document (`edit`, `fill`), the seats of the document it started from are
carried into the result through the exact remap and kept in a small cache
(`RIGORLOOM_DOC_CACHE`, default `~/.cache/rigorloom/doc-core`, keyed by the
output's sha256; entries older than 90 days, or beyond the newest 5000, are
pruned), so a filled seat keeps its id and shows its `value` with
`filled: true`. In a document filled outside rt_doc, a seat discovery no
longer recognises as empty is not listed, and every other seat keeps its id.

`outline()` also gives `paragraphs` (the count of top-level paragraphs),
`paragraph_range` (`"p0..pN"`) and, per table, `title`: the first cell's text,
at most 40 characters.

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
  The file is read once; the rev, the plan and the engine all use those bytes.
- Every op is checked before anything is written: address kinds, ranges
  (`p3:2-5` only for `set` and `replace`), `expect` (`expect_mismatch`; only
  `set`, `replace`, `delete`, `fill` and `table.delete_row` take one, others
  refuse it with `bad_input`; on a table it is the table's text, rows by `\n`
  and cells by `\t`), and ops that interfere (`conflict`): overlapping text,
  or an op on something another op deletes (a paragraph, table or row; one
  row deleted twice).
- `replace` with `at` on a paragraph searches that paragraph's own text, not
  the cells of a table inside it; address the table or cell for those. A text
  `expect` on `replace` needs `at`.
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
  result goes next to it as `<name>.edited.hwpx`. An `out` that is the input
  under another name (a hard or symbolic link) is refused, and an existing
  symbolic link is never written through; the same holds for `render`,
  `convert` and `new`.
- Writing: the whole result (remap, signals, preview data) is built and the
  output parsed back before anything is published. The file is staged as a
  unique temp file in the target folder (with the destination's file mode, or
  0666 less the umask for a new file), flushed, and moved into place with
  `os.replace` under the destination's lock (a thread lock and a
  `.~<name>.rtdoc-lock` file, held only for the final check and move; a lock
  older than two minutes is taken as left by a crashed writer and is broken by
  renaming it to a unique name first, so two waiters cannot both break it;
  staged `.rtdoc-*.tmp` files older than an hour are swept). An in-place
  edit checks the rev again under that lock right before the move, so of two
  edits from the same base one wins and the other gets `stale`. Writers that
  do not use rt_doc (Hancom saving the file) are only detected by that check.
  If something optional fails after the output was built (layout signals),
  the edit still succeeds and says so in `warnings`.
- `preview=True` writes to a temp copy and adds `changed: [{i, page, rect}]`.
  `rect` stays `null` until the engine has `geometry`.

## Rendering and pages

`render(path, pages, scale=2.0, fmt="png")` asks the engine for a PDF of
those pages and rasterizes it with pypdfium2 (optional; without it PNG
rendering is `capability_unavailable`). Pages come back in the order asked
for and each is the page it names; a page asked twice or outside the
document is refused before anything is drawn, and nothing is written unless
every page drew. `fmt="pdf"` writes one PDF (pages in ascending order; each
page record has `file` and `index`). `convert(to="png")` with an `out` ending
in `.png` writes a one-page document to `out` and a longer one to
`<stem>.p<N>.png` beside it; any other `out` is a folder. Every path returned
exists. `pages(path)` gives the
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
