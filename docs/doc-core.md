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
| `found_at` | `expect_mismatch` on a table cell | the one other cell of the same table whose text is exactly `expected`, when there is exactly one (the address was off, as when rows are counted from 1) |
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
| `expect_mismatch` | no | `expect` did not hold: the text at that place is not what was expected (a file that changed since it was read is `stale`) |
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
it does. The same holds for an edit op whose engine step the installed engine
predates (the engine answers "unknown hnc_edit operation"): the edit answers
`capability_unavailable`, reason `engine_function_missing`, `fn` naming the
step, and nothing is written.

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
  (`p3:2-5` only for `set`, `replace` and `char_shape`), `expect`
  (`expect_mismatch`; only `set`, `replace`, `delete`, `fill`,
  `table.delete_row`, `table.delete_col`, `char_shape`, `para_shape`,
  `numbering`, `break`, `header`, `note` and `memo` take one,
  others refuse it with `bad_input`; on a table it is the table's text, rows by `\n`
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
- `char_shape` (서식 > 글자 모양) and `para_shape` (서식 > 문단 모양) take `at`
  and `set`, a map of what to change; keys left out keep their value.
  `char_shape` works on a paragraph, a character range, a cell, a row or a
  table: `bold`, `italic`, `emboss`, `engrave`, `sup`, `sub` (true/false),
  `underline` (true/false or `BOTTOM`/`CENTER`/`TOP`), `underline_shape`,
  `strike` (true/false or a line shape), `outline` (외곽선; `false` or one of
  `SOLID`, `DOT`, `THICK`, `DASH`, `DASH_DOT`, `DASH_DOT_DOT`), `shadow`
  (그림자; `false`, `DROP` or `CONTINUOUS`), `shadow_color` (`#RRGGBB`),
  `shadow_offset` (`[x, y]` in %, `-100` to `100` each), `emphasis` (강조점;
  `false` or one of `DOT_ABOVE`, `RING_ABOVE`, `TILDE`, `CARON`, `SIDE`,
  `COLON`, `GRAVE_ACCENT`, `ACUTE_ACCENT`, `CIRCUMFLEX`, `MACRON`,
  `HOOK_ABOVE`, `DOT_BELOW`), `char_border` (글자 테두리; `false` or
  `{"type": line_type, "width": width_mm, "color": "#RRGGBB"}` for all four
  sides, with line types and widths from Hancom's lists), `char_fill` (글자
  배경; `#RRGGBB` or null; given alone it changes only the background and
  keeps the run's 글자 테두리), `color`, `underline_color`, `strike_color`
  (`#RRGGBB`), `shade` and `markpen` (형광펜; `#RRGGBB` or null to remove),
  `size` (pt, 1 to 4096), `font` (a face or `{"hangul": ..., "latin": ...}`),
  `ratio` (장평 %, 50 to 200), `spacing` (자간 %, -50 to 50), `rel_size` and
  `offset` (%). `para_shape` takes whole paragraphs (a range is refused):
  `align` (`JUSTIFY`, `LEFT`, `RIGHT`, `CENTER`, `DISTRIBUTE`,
  `DISTRIBUTE_SPACE`), `left`, `right`, `indent` (negative = 내어쓰기),
  `before`, `after` (pt), `line_spacing` (a percent, or
  `{"type": "FIXED"|"BETWEEN_LINES"|"AT_LEAST"|"PERCENT", "value": pt}`),
  `keep_next`, `keep_lines`, `widow_orphan`, `page_break_before`, `tabs` (탭
  설정; up to 32 tab stops `{"pos": pt (0..1000), "type": "LEFT"|"RIGHT"|"CENTER"|"DECIMAL", "leader": "NONE"|"SOLID"|"DASH"|"DOT"|...}`
  with strictly increasing positions), `auto_tab_left` and `auto_tab_right`
  (true/false), and 문단 테두리/배경 (`border`: `false` or
  `{"type", "width", "color"}` for all four sides, `fill`: `#RRGGBB` or null,
  `offsets`: `[left, right, top, bottom]` in pt from 0 to 1000 each,
  `connect`: true/false; 테두리 and 배경 are one borderFill, so `fill`
  needs `border` too (`border: false` for a background without lines) and a
  fill alone is `bad_input`, while `offsets` or `connect` alone keep the
  paragraph's lines and background; on a document whose `hh:paraPr` has no `hh:border`,
  rigorloom's own .hwpx files among them, this needs hwp-engine 761147c (PR #34)
  or later, and an older engine fails the edit with nothing written). An unknown key or a value out of
  range is `bad_input` before anything runs. Both need the engine, which
  applies them to the selected text or paragraphs, and the edit checks that
  `header.xml` (`charPr`, `paraPr`, `borderFill`, `tabPr`) holds the requested
  values before anything is written. They change no addresses, and run before
  text edits in the same paragraph, so a range means what it meant in `base`.
- `style.create` (서식 > 스타일 > 추가) makes a new style in the document's
  header. It takes `name` (1 to 64 characters on one line, not only digits),
  `eng_name` (optional), `kind` (`para`, the default, or `char`), `based_on`
  (an existing style's name, English name or id; default 바탕글) and the
  changes from that style: `char`, the `char_shape` keys except `markpen`
  (형광펜 is a mark in the text, not part of a 글자 모양), and `para`, the
  `para_shape` keys (refused for a `char` style). A style belongs to the whole
  document, so the op takes no `at` and no `expect`, and no address changes.
  Checked before anything runs: a name or English name the document already
  has (as a name, an English name or an id) is `bad_input`, so the op never
  changes an existing style; an unknown `based_on` is `bad_input` with the
  nearest names as `candidates`; keys and ranges are those of `char_shape` /
  `para_shape`. Two `style.create` ops in one edit that make the same name
  are a `conflict`. A `style` op cannot apply a style that a `style.create`
  in the same edit makes (`bad_input`): apply it in a later edit. Needs the
  engine. After the edit a .hwpx output's header must hold the style once, with
  its type and English name and the requested `char` / `para` properties in
  `charPr`, `paraPr`, `borderFill` and `tabPr`; otherwise the edit fails and
  nothing is written. Changing, renaming or deleting an existing style has no
  op yet: the engine has no such step.
- `numbering` puts whole paragraphs into 개요 번호, 문단 번호 or 글머리표, or
  takes them out: `set` is `{"kind": "outline"|"number"|"bullet"|"none"}`
  with `level` 1 to 7 (the XML's level 0 to 6; `outline` defaults to 1 and
  applies the document's 개요 n style, which must exist), `char` for a
  bullet, and `start` (1 to 9999) or `restart: true` for numbers. The op
  reads each paragraph's base state and sends only the engine steps that
  bring it there (none when it already is). `none` takes off the number or
  bullet and moves a 개요 paragraph back to 바탕글. A `style` and a
  `numbering` op on one paragraph in one edit are a `conflict`; send them
  separately. Needs the engine; addresses do not change.
- Table shape ops (표 > 셀 합치기, 셀 나누기, 칸 넣기·지우기, 셀 크기) need the
  engine. Each owns its whole table for the edit: any other op on that table,
  its cells or what they hold, including a second shape op, is a `conflict`;
  send them in separate edits.
  - `table.merge` at a cell with `to`, the cell at the block's other corner.
    The block grows until no merged cell crosses its edge. The top-left cell
    takes the block and the paragraphs of every merged cell that hold
    anything, in reading order. Cells that hold a table cannot be merged
    away. The remap sends the merged-away cells to null and each of their
    paragraphs to its place in the merged cell.
  - `table.split` at a cell with `rows` and `cols` (1 to 20, not both 1). A
    cell that spans several rows or columns splits along its grid lines, so
    the count must divide the span; a single cell adds grid rows or columns
    and the cells across them span them. The cell keeps its text; the new
    cells are empty; the cells after them move in the remap.
  - `table.add_col` with `after` (a column) and `like` (the column before or
    after the new one, default `after`), as `table.add_row`; `at` a cell
    defaults `after` to its last column. `table.delete_col` with `col` or `at`
    a cell; `expect` is the column's cells by `\n`. Both need a cell that
    sits in that column alone. A deleted column's cells map to null in the
    remap and the cells after it move left.
  - `table.size` sets grid column widths and row heights in millimetres (1 to
    1000): `width_mm` / `height_mm` for the column or row of the cell at (or
    `height_mm` at a row), or `col_widths_mm` / `row_heights_mm` lists, which
    go on the table address only (`bad_address` at a row or cell), null
    keeping one. Merged cells across a column or row change with it. No
    address changes.
  - A column added or deleted inside a merged cell widens or narrows that
    cell; its address and text stay.
  - 셀 너비·높이 같게 (distribute) has no op yet.
- Table style ops (표 > 셀 테두리/배경, 셀 속성, 표 속성) need the engine and change no
  address; they take no `expect`.
  - `table.cell_style` at a cell, a row or a table (or a cell with `to`, the
    block's other corner cell) with `set`: `border` (one line for every side,
    `{type, width, color}` or `"none"`, or `{all, left, right, top, bottom}`
    with a line each; `type` one of 한글's line types such as `SOLID`,
    `DASH`, `DOUBLE_SLIM`; `width` one of 한글's widths in millimetres, 0.1 to
    5.0; `color` `#RRGGBB`), `fill` (`#RRGGBB`, or null / `"none"`),
    `valign` (`TOP`, `CENTER`, `BOTTOM`), `margin_mm` (안 여백, 0 to 50, one
    number or per side) and `header` (제목 셀, true/false). The block grows to
    whole merged cells. A border changes each block cell's side and, across a
    shared edge, the neighbour's opposite side too, as 한글's 셀 테두리 does.
  - `table.style` at a table with `set`: `repeat_header` (제목 줄 자동 반복,
    true/false; the rows whose cells are 제목 셀 repeat on each page) and
    `page_break` (쪽 경계에서 나눔: `CELL`, `TABLE` or `NONE`).
  - Conflicts: two `table.cell_style` ops on one table may not overlap, nor
    share an edge when either sets a border; a `table.add_row` /
    `table.delete_row` or a shape op on the same table, or a second
    `table.style`, is a conflict. Text ops on the table's cells are fine: they
    run before the style op rewrites the table.
- Table formula op (`table.formula`, 표 > 블록 계산식 / 계산식) needs the engine,
  changes no address, and takes no `expect`.
  - `at` is the target cell of a body table (`tN/rR/cC`) and must be empty (one
    empty paragraph with no text, objects or controls; a non-empty cell is
    refused with `bad_input`, and a covered coordinate inside a merged cell is
    `bad_address`).
  - Pass either `func` (`SUM`, `AVG` or `PRODUCT`, case-insensitive) with
    `from` (a cell in the same table, in the same row to the left of `at` or in
    the same column above `at`) or `formula` (a string starting with `=`, 2 to
    200 characters on one line with no control characters), never both.
  - With `func` and `from`, the block from `from` to `at` inclusive must be a
    single unmerged row (`A`..`Z`, columns `0`..`25`) or column of cells;
    `from` in another table is `bad_address`, and `from` diagonal from, equal
    to, right of or below `at`, or a block crossing a merged cell, is
    `bad_input`. The engine (`formula_auto("Sum"|"Avg"|"Pro")`) writes a
    `FORMULA` field in `at` with Hancom's relative formula (`=SUM(A?:C?)` along
    a row or `=SUM(?1:?4)` down a column, 1-based row numbers), `ResultFormat`
    (`%g,` for `SUM`/`PRODUCT`, `%.2f,` for `AVG`), `LastResult` and `Command`,
    plus the formatted value as the cell's text (`%g` with thousands grouping
    for `SUM`/`PRODUCT`; 2 decimal places rounded half-up with thousands
    grouping for `AVG`). Each source cell contributes its leading number
    (optional sign, digits with optional commas, optional decimal part; text
    after the leading number is ignored, and a cell without a leading number
    counts as `0`).
  - With `formula`, the engine (`insert_formula_field(formula)`) writes a
    `FORMULA` field in `at` whose `Command` and `Formula` parameters are
    `formula + ";48"` and writes no result text, as Hancom's own saved
    `TableFormula` field holds none either; when 한글 shows the value has not
    been checked yet.
  - Conflicts: at most one `table.formula` per target cell per edit; any other
    op touching that target cell, or a `table.add_row` / `table.delete_row` or
    shape op on the same table, is a `conflict`.
  - After the edit, `_verify_table_formula` checks that the target cell holds
    one `FORMULA` field with the expected `Formula`, `Command`, `ResultFormat`,
    `LastResult` and cell text (for `func`, computed in rigorloom from the
    source cells' leading numbers; for `formula`, empty text), and that every
    other cell of the table and every other paragraph in the document is
    unchanged; any mismatch fails the edit and nothing is written. Editing or
    removing an existing formula field has no op yet.
- Page ops (쪽 > 편집 용지, 쪽 테두리/배경, 다단 설정, 쪽·단·구역 나누기, 감추기, 새 번호로 시작) need the engine and take
  `at`, a body paragraph (not one in a table, note or box, and not a range).
  - `page_setup` changes the 편집 용지 (and 쪽 테두리/배경 or 시작 쪽 번호) of the section that holds the
    paragraph: `set` takes `paper` (`A3`, `A4`, `A5`, `B4`, `B5`, `LETTER`,
    `LEGAL`, portrait sizes) or `width_mm` / `height_mm` (50 to 1000),
    `landscape` (true/false; the engine keeps width and height as they are and
    writes the orientation), `margins` (`left`, `right`, `top`, `bottom`,
    `header`, `footer`, `gutter`, 0 to 500 mm; margins left out keep their
    value), `gutter_type` (제본: `LEFT_ONLY`, `LEFT_RIGHT`, `TOP_BOTTOM`),
    `start_page` (시작 쪽 번호: integer `1` to `65535`, the section's
    `hp:startNum/@page`) and `border` (쪽 테두리/단색 배경:
    `false` resets the section's `BOTH` (양쪽) page border to borderFill 1, or
    `{"type": line_type, "width": width_mm, "color": "#RRGGBB", "fill"?: "#RRGGBB"|null, "offset_mm"?: [left, right, top, bottom]|number (0..500 mm), "apply"?: "BOTH"|"ODD"|"EVEN", "text_border"?: "PAPER"|"CONTENT", "header_inside"?: bool, "footer_inside"?: bool}`,
    using the same line types and widths from Hancom's lists as `char_border` /
    `para_shape` `border`, plus `type` `NONE` (no `width` or `color`) for a
    page background without lines; `type` is required, so a fill alone never
    draws a frame). On a section whose `hp:secPr` has no
    `hp:startNum` or `hp:pageBorderFill` (rigorloom's own .hwpx files among
    them), `start_page` and `border` need hwp-engine bc43585 (PR #35) or later, which
    adds Hancom's defaults first; an older engine leaves the section as it was,
    the check below fails, and nothing is written.
    Margins that leave no room are refused with `bad_input`: left + right +
    gutter (top + bottom + header + footer, plus the gutter for
    `TOP_BOTTOM`) must stay below the page's width (height), using the
    section's paper and margins for what the op leaves out; a landscape page
    lays the paper's height across. After the edit, the section's `hp:startNum`
    and `hp:pageBorderFill` (plus its referenced `hh:borderFill` in
    `header.xml`) are verified before anything is written.
  - `hide` (쪽 > 감추기) hides page elements on the
    page where the body paragraph at `at` starts: takes boolean flags `header`,
    `footer`, `page_num`, `border`, `fill` and `master_page` (at least one must
    be `true`), and inserts `<hp:pageHiding>` at the start of the paragraph. A
    paragraph that already holds a `pageHiding` control is refused with
    `bad_input`. It takes no `expect` and changes no addresses. After the edit,
    the target paragraph must hold the new `hp:pageHiding` with those six attributes.
  - `new_number` (쪽 > 새 번호로 시작) restarts
    numbering at the start of the body paragraph at `at`: takes `kind`
    (`PAGE`, `FOOTNOTE`, `ENDNOTE`, `PICTURE`, `TABLE` or `EQUATION`) and `num`
    (integer `1` to `65535`), inserting `<hp:newNum>` at the paragraph start. A
    paragraph that already holds a `newNum` control of that `kind` is refused
    with `bad_input`. It takes no `expect` and changes no addresses. After the
    edit, the target paragraph must hold the new `hp:newNum` with `numType` and
    `num`.
  - `columns` changes the column definition (다단) that governs the paragraph
    at `at` (the last `<hp:colPr>` at or before `at` in its section, which covers
    every paragraph under that definition), or with `split: true` (다단 설정
    나누기) starts a new column definition at `at` while leaving the definition
    governing earlier paragraphs unchanged (`goto` `at` at offset 0,
    `break_coldef`, then `set_columns`; nothing is split and no address
    changes). `split` is a boolean (`false` by default) and is refused on a
    section's first paragraph (`bad_address`, because the engine inserts a new
    paragraph after a section's first paragraph and would shift addresses; omit
    `split` to change the section's own column definition) and on a paragraph
    that already starts a column definition (`bad_input`; omit `split` to change
    that definition). `set` takes `count` (1 to 255), `gap_mm` (0 to 100),
    `widths_mm` (단 너비 따로: a list of `count` column widths in millimetres, 5
    to 1000 each), `gaps_mm` (an optional list of `count - 1` inter-column gaps
    in millimetres, 0 to 100 each; requires `widths_mm` and cannot be given with
    `gap_mm`; when omitted with `widths_mm`, each of the `count - 1` gaps
    defaults to `gap_mm`, or 0 mm when `gap_mm` is omitted), `line` (구분선,
    true/false), `kind` (`NEWSPAPER`, `BALANCED_NEWSPAPER`, `PARALLEL`) and
    `layout` (`LEFT`, `RIGHT`, `MIRROR`). With `widths_mm`, widths and gaps are
    converted to HWPUNIT the way `hwpx_kit.mm_hu` does and passed as
    `sizes_hu = [(w_hu, gap_hu), ..., (w_hu, 0)]`, writing `sameSz="0"`,
    `sameGap` equal to the first gap in HWPUNIT, and `<hp:colSz width="..." gap="..."/>`
    for each column. On a section with no column definition before `at` (such
    as rigorloom's minimal `basic.hwpx` fixture), the engine first adds 한글's
    one-column definition to the section's first paragraph and changes that;
    this needs hwp-engine 0cc9e17 (PR #37) or later, and an older engine fails the
    edit with nothing written. After the edit, `_verify_columns`
    checks the `<hp:colPr>` governing `at` (`colCount`, `sameSz`, `sameGap`,
    `type`, `layout`, `<hp:colLine>` and `<hp:colSz>` list), checks with
    `split: true` that the `<hp:colPr>` governing the paragraph right before
    `at` is unchanged and the new `<hp:colPr>` sits at the start of `at`, and
    checks that paragraph texts and all other `<hp:colPr>` controls in the
    document are unchanged; any mismatch fails the edit and nothing is written.
  - `break` with `kind` `page` (쪽 나누기) or `column` (단 나누기) makes the
    paragraph start a page or a column; nothing is split and no address
    changes. `kind: "section"` (구역 나누기) moves the paragraph and every
    paragraph after it in its section into a new section, which copies the
    section's settings and column definition. The engine adds the new section
    after the last one, so a section break goes in the document's last
    section and not on that section's first paragraph. Paragraph and table
    addresses do not change (they count across sections). `expect` guards the
    paragraph's text. Order: the engine runs the edit's steps from the end of
    the document back, and at one paragraph a section break runs after the
    edits inside that paragraph and before an `insert_after` on the
    paragraph before it, so every step still finds its paragraph by its
    position in the original document. A `set` or other text op and a
    `page` or `column` break on one paragraph in one edit both apply.
  - Conflicts: two `page_setup` or two `columns` ops on one section (including
    two `split: true` `columns` ops at the same paragraph) are a
    `conflict`; so is either of them on the section of a section break, a
    second section break in the same edit, a second `break`, `hide` or
    `new_number` on one paragraph,
    and any other op on a paragraph a section break moves. Send them in
    separate edits.
- 머리말·꼬리말 and 쪽 번호 매기기 (쪽 > 머리말/꼬리말, 쪽 번호 매기기) need the
  engine and take `at`, a body paragraph (not one in a table, note or box, and
  not a range); the op changes that paragraph's section.
  - `header` writes the section's own 머리말 (`kind: "header"`, the default) or
    꼬리말 (`kind: "footer"`) for `apply` `BOTH` (양쪽, the default), `ODD` or
    `EVEN`, with `text` (up to 1000 characters as given; `\n` starts a new line
    in it). `{page}` and `{pages}` in `text` insert 쪽 번호 (`hp:autoNum` with
    `numType="PAGE"`) and 전체 쪽수 (`numType="TOTAL_PAGE"`), and `{{` and `}}`
    write literal `{` and `}`; any other `{...}` or unmatched brace is
    `bad_input` with `["{page}", "{pages}"]` as `candidates`. Without `{page}`
    or `{pages}`, the edit runs the single-step `insert_header(text=..., ...)`;
    with them, it enters the control via `insert_header(text=None, ...)` and
    runs `type` and `insert_page_field("page"|"total")` for each piece in order.
    It replaces the section's own control of that kind and apply, so the
    section keeps one; the other kinds and applies stay. `expect` is the text
    of the one it replaces (its lines joined by `\n`, with existing `PAGE` and
    `TOTAL_PAGE` `hp:autoNum` fields read as `{page}` and `{pages}`; `""` when
    the section has none). After the edit, the saved control must hold the
    literal text pieces and `PAGE` / `TOTAL_PAGE` `hp:autoNum` controls in the
    exact positions and paragraphs requested; otherwise the edit fails and
    nothing is written. The new control gets the document's 머리말 style; a
    document without that style answers `capability_unavailable`
    (`engine_needs_style`) and nothing is written.
  - `page_number` sets the section's 쪽 번호: `pos` (`BOTTOM_CENTER`, the
    default, `BOTTOM_LEFT`, `BOTTOM_RIGHT`, `TOP_CENTER`, `TOP_LEFT`,
    `TOP_RIGHT`, `OUTSIDE_TOP`, `OUTSIDE_BOTTOM`, `INSIDE_TOP`,
    `INSIDE_BOTTOM`, or `NONE` for no number), `format` (`DIGIT`, the default,
    `ROMAN_CAPITAL`, `ROMAN_SMALL`, `CIRCLED_DIGIT`, `LATIN_CAPITAL`,
    `HANGUL_SYLLABLE` and the other 번호 모양 names) and `side_char` (the
    character on both sides of the number, `-` by default, `""` for none). It
    replaces the section's own page number. It takes no `expect`.
  - Both need hwp-engine 2077774 (PR #23) or later. An older engine, whose
    insert_header / page_number has no `replace`, answers
    `capability_unavailable` (`engine_function_missing`, with `keyword` and
    `needs` naming that engine) and nothing is written.
  - No address changes: the controls sit in the section's first paragraph and
    take no characters. `read` does not show 머리말·꼬리말 text yet.
  - Conflicts: two `header` ops on one section with the same `kind` and
    `apply`, two `page_number` ops on one section, either beside a section
    break in that section, and a `delete` of the section's first paragraph in
    the same edit.
- 각주·미주 and 캡션 (입력 > 각주/미주, 표 > 캡션 넣기) need the engine and
  change no body paragraph or table addresses.
  If the document's header has no 각주 (Footnote), 미주 (Endnote) or 캡션
  (Caption) style, the edit first adds it, based on the document's first
  style (so an auto-added note style uses that body font size rather than
  Hancom's smaller 각주 default), reports the header addition in that op's
  `applied[].warnings`, and checks that the output header holds the style.
  - `note` inserts a 각주 (`kind: "foot"`, the default) or 미주 (`kind: "end"`)
    in the paragraph at `at` with `text` (one or more lines; `\n` starts a new
    paragraph in the note). By default the note mark goes at the end of the
    paragraph; `after` places it right after that substring of the paragraph,
    which must occur once there (otherwise `bad_input` with `candidates`).
    `expect` guards the paragraph's text. After the edit, the `.hwpx` section
    must hold the new `hp:footNote` or `hp:endNote` inside that paragraph with
    `text`, and the body text of other paragraphs must stay unchanged.
  - `caption` attaches a 캡션 to the body table at `at` on `side` (`bottom`,
    the default, `top`, `left` or `right`) with `text` (one line, placed after
    Hancom's automatic `"표 N "` label). A table that already has a caption is
    refused with `bad_input`. It takes no `expect`. After the edit, the table
    must hold one `hp:caption` with that side and text, and other tables must
    stay untouched.
  - Conflicts: two `note` ops (or a `note` and a text edit) on the same
    paragraph, two `caption` ops (or a `caption` and a row, style or shape op)
    on the same table, a `delete` of that paragraph or table in the same edit,
    and a `style.create` of 각주/미주/캡션 (`Footnote`/`Endnote`/`Caption`)
    together with a `note` or `caption` that needs it auto-added. Editing or
    removing an existing note or caption has no op yet.
- 책갈피, 하이퍼링크 and 차례 만들기 (입력 > 책갈피, 하이퍼링크; 도구 > 차례
  만들기) need the engine and take no `expect`.
  `link` and `toc` need hwp-engine 1071d94 (PR #33) or later on documents
  whose header lacks the charPr children, `hh:tabProperties` or the hp/hc
  namespaces (rigorloom's own .hwpx files among them); an older engine fails
  those edits and nothing is written.
  - `bookmark` inserts a point 책갈피 (`hp:bookmark`) in the paragraph at `at`
    with `name` (1 to 64 characters on one line, no control characters). A name
    that already exists in the document (or is duplicated in the same edit) is
    refused with `bad_input`. By default the bookmark goes at the end of the
    paragraph; `after` places it right after that substring of the paragraph,
    which must occur once there (otherwise `bad_input` with `candidates`). No
    address changes. After the edit, the `.hwpx` section must hold one more
    `hp:bookmark` with `name` inside that paragraph and the body text must stay
    unchanged.
  - `link` turns `phrase` (which must occur once in the paragraph at `at`,
    otherwise `bad_input` with `candidates`) into a `HYPERLINK` field to
    `target`: an `http://`, `https://` or `mailto:` URL, or `#name` of a
    bookmark that exists in the document or is created by an earlier `bookmark`
    op in the same edit (otherwise `bad_input`). The engine replaces the
    selected phrase with a `HYPERLINK` field whose text run gets Hancom's blue
    underlined link look. No address changes. After the edit, the paragraph
    text must stay unchanged and hold one more `HYPERLINK` `fieldBegin` whose
    `Command` holds `target` and whose range text equals `phrase`.
  - `toc` inserts Hancom's 제목 차례 (`TABLEOFCONTENTS` field) as new
    top-level paragraphs right after the body paragraph at `at`, with one
    hyperlinked line per 개요 heading up to `levels` (1 to 3, default 2) and
    tab `leader` (`DASH`, the default, `DOT`, `SOLID` or `NONE`), with table,
    picture and equation lists turned off. Because `toc` adds top-level
    paragraphs, later body addresses shift and are reported in `remap`. At most
    one `toc` per edit; a document that already has a `TABLEOFCONTENTS` field
    is refused with `bad_input`. If the header lacks `차례 제목` (`TOC
    Heading`) or `차례 1..N` (`TOC 1..N`), the edit adds them from the
    document's first style, reports them in `applied[].warnings` and checks the
    output header. The page numbers in the 차례 come from rigorloom's layout,
    and 한글 updates them when the user runs 차례 새로 고침. After the edit, the section must hold one `TABLEOFCONTENTS` field
    right after `at`, and the original paragraphs' text must stay unchanged and
    in order.
  - Conflicts: two ops on the same target paragraph, a `delete` of that
    paragraph (or its table), a text edit of the same paragraph together with
    `bookmark`, `link` or `toc`, and a `style.create` of a 차례 style that
    `toc` needs auto-added in the same edit. Editing or removing an existing
    bookmark, hyperlink or table of contents has no op yet.
- 메모 넣기 (`memo`, 입력 > 메모 / 메모 넣기) needs the engine and changes no
  address.
  - `at` is a non-empty body or cell paragraph (`pN`, `tN/rR/cC/pK`, `h:"..."`;
    a table, row, cell or character range is `bad_address`, and paragraphs
    inside notes, headers/footers and memos have no address). An empty
    paragraph (or one holding an inline object when `on` is omitted) is refused
    with `bad_input`.
  - `text` is the memo body: a non-empty single-line string of at most 1000
    characters (newlines or control characters are `bad_input`).
  - `on` is an optional non-empty single-line substring of the paragraph to
    attach the memo to: if it does not occur in the paragraph, the op is
    refused with `not_found` and nearby `candidates`; if it occurs more than
    once, it is refused with `bad_input` and `candidates`. Without `on`, the
    memo attaches to the whole paragraph text. If `on` (or the whole paragraph
    when `on` is omitted) overlaps an existing field in that paragraph
    (click-here, hyperlink, memo, formula or table of contents), the op is
    refused with `bad_input` because nested fields are not supported.
  - `author` is an optional string of at most 64 characters without `/`,
    `\`, `;` or control characters, which Hancom's memo `Command` uses as
    separators (default `""`; the OS user name is never read). `expect`
    guards the paragraph's visible text.
  - The edit runs `goto(p.k, start, p.si)`, `select(end - start)` and
    `insert_memo(text=text, author=author, when=...)`, with the creation time
    fixed when the edit is planned, which wraps the anchor text in a
    `MEMO` field (`fieldid="623209829"`) whose `<hp:subList>` holds one
    paragraph with `text` in the document's `메모` (`Memo`) style when
    `header.xml` has one, or style `0` (`바탕글`) when `header.xml` has no
    `Memo` style. A memo's `<hp:subList>` paragraph is not part of the host
    paragraph's visible text, so `read`, `expect` and `remap` still see only
    the host paragraph's visible text. When 한글 shows the memo pane or balloon
    has not been checked yet.
  - Conflicts: at most one `memo` per paragraph per edit, and no `memo`
    together with any text edit (`set`, `replace`, `insert_after`, `delete`,
    `fill`) or other span/removal op on that paragraph in the same edit.
  - After the edit, `_verify_memo` checks that the output paragraph's visible
    text is unchanged, that it holds one more `MEMO` `fieldBegin` than before
    whose `subList` text equals `text`, whose `Author` parameter (and `Command`
    author slot) equals `author`, whose creation time (`Command`'s FILETIME
    and `CreateDateTime`) is the planned one, whose `<hp:p>` uses the `메모` style (or
    style `0` when the header has no `Memo` style), and whose `fieldBegin` /
    `fieldEnd` wrap the exact anchor span and text, and that every other field
    in the document is unchanged; any mismatch fails the edit and nothing is
    written. `memo` needs hwp-engine ENGINE_FLOOR or later; an older engine
    fails the edit and nothing is written. Editing or removing an existing
    memo and memo shape settings have no op yet.
- 그림 넣기 and 그림 속성 (입력 > 그림; 개체 속성 > 기본/위치) need the engine and take
  no `expect`.
  - `insert_picture` inserts an image file (`path`) at `at` (a body paragraph,
    heading, cell, cell paragraph or fill place; `offset` places it at that code
    point in the paragraph, and omitting `offset` adds a paragraph after `at` for
    it), with optional `width_mm` / `height_mm` (`1` to `1000` mm; `width_mm`
    alone keeps the image's aspect ratio, or 96-dpi size when neither is given).
    By default the picture is inline (`treatAsChar="1"`, 글자처럼 취급). Giving
    `wrap` (`SQUARE`, `TIGHT`, `THROUGH`, `TOP_AND_BOTTOM`, `BEHIND_TEXT` or
    `IN_FRONT_OF_TEXT`) makes the picture float (`treatAsChar="0"`), with
    optional `vert_rel` (`PARA`, the default, `PAGE` or `PAPER`), `horz_rel`
    (`COLUMN`, the default, `PARA`, `PAGE` or `PAPER`) and `x_mm` / `y_mm`
    offsets (`-1000` to `1000` mm, converted to HWPUNIT by truncating like
    `MiliToHwpUnit`). Giving `vert_rel`, `horz_rel`, `x_mm` or `y_mm` without
    `wrap` is `bad_input`. On a section whose `<hs:sec>` root does not declare
    `xmlns:hc` (rigorloom's own .hwpx files among them), a picture needs
    hwp-engine a6fdd06 (PR #36) or later, which adds the declaration on save; an
    older engine fails the edit and nothing is written. `insert_picture` is a
    document-layer op; the `edit` tool does not list it.
  - `picture` changes an existing picture in the body or cell paragraph at `at`
    (a table, row, cell or character range is `bad_address`, and a paragraph with
    no own `<hp:pic>` is `not_found`). `index` (0-based in XML order among the
    paragraph's own `<hp:pic>`, excluding pictures nested in a table, text box,
    caption or note inside it) defaults to `0` when the paragraph holds one
    picture; when the paragraph holds more than one and `index` is omitted, the
    op is refused with `bad_input` naming the count. `set` takes `width_mm` and
    `height_mm` (`1` to `1000` mm; one alone keeps the picture's aspect ratio
    unless `keep_ratio` is `false`), `keep_ratio` (boolean), `inline` (`true` for
    글자처럼 취급, `treatAsChar="1"`, which refuses `wrap`, `vert_rel`,
    `horz_rel`, `x_mm` and `y_mm`; `false` floats the picture), `wrap`
    (`SQUARE`, `TIGHT`, `THROUGH`, `TOP_AND_BOTTOM`, `BEHIND_TEXT` or
    `IN_FRONT_OF_TEXT`; floats the picture), `vert_rel` (`PARA`, `PAGE`,
    `PAPER`), `horz_rel` (`COLUMN`, `PARA`, `PAGE`, `PAPER`), and `x_mm` /
    `y_mm` (`-1000` to `1000` mm). `vert_rel`, `horz_rel`, `x_mm` and `y_mm`
    require the picture to be floating after the op (`bad_input` otherwise).
    Unverified engine picture properties (crop, border, effect, brightness,
    contrast, alpha, rotation and flip) are not exposed and are refused as
    unknown keys (`bad_input`). Switching a picture between inline and floating
    (`inline`, or `wrap` on an inline picture) is checked in the saved XML only;
    its 한글 rendering has not been compared yet. At most one `picture` op per picture per edit
    (`conflict` otherwise), and no address changes. After the edit,
    `_verify_picture` checks that the output `<hp:pic>` (matched by `id`) has the
    requested `hp:sz` / `hp:curSz` width and height, `textWrap`, `hp:pos`
    `treatAsChar`, `vertRelTo`, `horzRelTo`, `vertOffset` and `horzOffset`, and
    the same `hc:img/@binaryItemIDRef` before anything is written.
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
  `rect` stays `null` until the engine has `geometry`. The copy is an engine
  draft (`edit(draft=True)`): it keeps the source's thumbnail
  (`Preview/PrvImage.png`) instead of drawing page 1 again, so it is never
  the file to hand on; applying the same ops without `preview` writes the real
  one.
- Queued run edits (`set_run`, `replace_at_cell` with `mode="replace"`, and
  whole-run placeholder replacement in `preedit.py`, together with
  `PageGateway._preview` in `runtime/scripts/rt_ui_doc.py`) align the old
  queue-form run text and the new value by their common prefix `p` and common
  suffix `s` (capped so `p + s <= min(len(old), len(new))`), yielding the
  changed region `[p, len(old) - s)` in the old text and `[p, len(new) - s)` in
  the new value:
  - Inline `<hp:t>` child elements (`<hp:fwSpace/>`, `<hp:lineBreak/>`,
    `<hp:tab .../>`) at offsets in the unchanged prefix or suffix (including
    the changed-region edges) are re-emitted verbatim with their attributes in
    original order, and `PageGateway._preview` narrows the doc-core replacement
    range to the changed region so `U+3000` (`<hp:fwSpace/>`), `"\n"`
    (`<hp:lineBreak/>`) and `"\t"` (`<hp:tab/>`) outside the changed region
    survive in the preview as in the applied document.
  - Inline tags strictly inside the old changed region are dropped (and each
    dropped tag is logged to `stderr`, or recorded under `dropped_inline` on
    the scan entry when `replace_placeholders` scans occurrences with a log). If
    a single run edit changes two separate places in the same run, any inline
    tags between them sit inside the changed region `[p, len(old) - s)` and are
    dropped.
  - When there is no common prefix and no common suffix (the whole run text is
    replaced, including when the new value is empty), every boundary tag at
    offset `0` and offset `len(old)` (`<hp:fwSpace/>` included) is kept: a
    separator the editor cannot show cannot be removed through a run edit.
  - Range-mark pairs (`<hp:markpenBegin .../>` / `<hp:markpenEnd/>`,
    `<hp:insertBegin .../>` / `<hp:insertEnd .../>`, and
    `<hp:deleteBegin .../>` / `<hp:deleteEnd .../>`, paired by `Id` or `TcId`
    when present or in order otherwise) never leave a half pair or an empty
    pair: when both marks fall inside the changed region they wrap the
    replacement changed text (or both are dropped if the replacement changed
    text is empty), and when one mark is inside and one is outside the inner
    mark moves to the changed-region edge on its side. A mark whose partner
    sits in another run is treated the same way: moved to the edge, never
    dropped. A mark exactly on a changed-region edge stays on its side, so a
    range mark neither grows over nor loses the new text.

## Rendering and pages

`render(path, pages, scale=2.0, fmt="png")` asks the engine's own `png()`
first: the engine draws its PDF of those pages, rasterizes it with
pypdfium2 and writes the PNGs itself (`via: "engine_png"`). When the engine
has no `png()` or its answer is not exactly the pages asked for, rt_doc asks
the engine for a PDF of those pages and rasterizes it with pypdfium2 itself
(`via: "engine_pdf+pypdfium2"`, same pixels; optional; without pypdfium2 PNG
rendering is `capability_unavailable`). `render` and `geometry` load only the
layout, not the form analysis, so a fresh preview copy draws quickly. Pages come back in the order asked
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
