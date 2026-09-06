# Which cell-taking inline controls end a line

Measured on the ten committed public corpus forms under
`tests/corpus/forms/converted/`, from the cache alone. No licensed Hancom
output was rendered: **path C is not run, here or anywhere in this repo**, and
every own render stays `own-uncertified`.

## The question

`hp:lineseg@textpos` indexes the paragraph's TEXT STREAM, in which an inline
control occupies cells it draws no glyph for — one cell for a char-type
control, eight for an inline/extended one (`own_render.textpos_cells`, the
census in `TEXTPOS_CELLS_CHAR`). A control that ENDS the line it sits on is
therefore visible in the cache twice over: the next cached line starts at
`cell + textpos_cells(name)`, and it starts there whatever the line's width
came to.

So, for every occurrence of every cell-taking inline control inside an
`hp:t` or an `hp:run`: does the cached `hp:lineseg@textpos` sequence have a
line boundary AT that cell, or IMMEDIATELY AFTER it, or neither?

## The matrix

| control | cells | occ | line starts AT it | line starts AFTER it | ends the paragraph | one-line paragraph | neither |
|---|---|---|---|---|---|---|---|
| `lineBreak`  | 1 | 30 | 0 | **30** | 0 | 0 | 0 |
| `tbl`        | 8 | 81 | 0 | 0 | 80 | 0 | 1 |
| `colPr`      | 8 | 32 | 0 | 0 | 0 | 30 | 2 |
| `tab`        | 8 | 15 | 0 | 0 | 0 | 15 | 0 |
| `secPr`      | 8 | 10 | 0 | 0 | 0 | 10 | 0 |
| `fieldBegin` | 8 |  9 | 0 | 0 | 0 | 8 | 1 |
| `fieldEnd`   | 8 |  9 | 0 | 0 | 8 | 0 | 1 |
| `fwSpace`    | 1 |  8 | 0 | 0 | 0 | 6 | **2** |
| `rect`       | 8 |  5 | 0 | 0 | 4 | 1 | 0 |
| `newNum`     | 8 |  4 | 0 | 0 | 0 | 4 | 0 |
| `pic`        | 8 |  2 | 0 | 0 | 2 | 0 | 0 |
| `header`     | 8 |  1 | 0 | 0 | 1 | 0 | 0 |

"one-line paragraph" means the cache broke the paragraph into a single line,
so it never had to decide and the occurrence says nothing either way.
"neither" means a multi-line cached paragraph whose line boundaries fall
somewhere else entirely — a counter-example.

`hp:hyphen` and `hp:nbSpace`, the other two char-type controls, occur nowhere
on the corpus.

## What the matrix decides

**`hp:lineBreak` is a mandatory line end.** 30 of 30, no counter-example, no
occurrence that leaves the question open. The 30 sit in 20 paragraphs of three
forms — `moel-2025` 27 in 17 paragraphs, `kstartup` 2, `jeongbo` 1 — and every
one of those paragraphs is multi-line in the cache by construction.

**`hp:tab` is not, and is not refuted either.** All fifteen occurrences are in
`kstartup` 751/753/755, each of which the cache kept on one line. Unmeasured,
so untouched.

**`hp:fwSpace` is refuted.** `admrul` 13 is a two-line cached paragraph
carrying two of them, at cells 20 and 26, and the cache breaks at neither.

Everything else is either an object that ends its paragraph or a marker in a
one-line paragraph; none of them is a candidate on this corpus.

## The carrier

`moel-2025` 73 is `<hp:t>6. 임  금<hp:lineBreak/>   </hp:t>` at 13 pt followed
by an 11 pt run. Its cached `textpos` are `[0, 8]`: cell 7 is the control's own
and belongs to the line it closes, cell 8 is the first of the three spaces
after it. In `Paragraph.chars` that is `[(0, 7), (7, 59)]`. Both cached lines
are `textheight` 1300 with `spacing` 40 — the paragraph's `PERCENT` 103 % of
13 pt — because the second line opens with three 13 pt spaces before the 11 pt
run starts.

Before this slice the breaker had no notion of the control and broke that
paragraph on width at character 52, which made its second line 11 pt (1100 +
32) and left every block below it 4.16 px too high. That is
`class_b_probe`'s `text_line_height` root: 20 paragraphs, 83.20 px, all of them
`moel-2025`.

## Correction to #317

#317 reported the carrier's cached spans as `[0,7][7,59]` and its line heights
as `1300+40 / 1100+32`. The spans are right, read as `chars` indices. The
heights are not the cache's: the file gives `1300+40` for BOTH lines, and
`1100+32` is what OUR computed second line came to under the old width break.
Matching the cache therefore means both lines at 1300 + 40, which is what the
breaker now produces.
