# What Hancom does with a table that does not fit the page

`render-check-01`'s `F47` ([render-check-01.md](render-check-01.md), note 2)
recorded a disagreement and guessed at its mechanism: Hancom moved a 26-row
table whole onto the next page where `own_render` split it in place, even
though the table declares `hp:tbl@pageBreak="CELL"` — the value that is
supposed to *permit* a row-boundary split. This page answers it by
measurement instead.

**The rule.** A table splits at a row boundary only when it is **anchored**
(`hp:tbl/hp:pos@treatAsChar="0"`) **and** declares `pageBreak="CELL"`. An
**inline** table (`treatAsChar="1"`, 글자처럼 취급) is a character-like object
in its line and never splits, whatever `pageBreak` says: if its whole height
does not clear the room left on the page it moves whole to the next page, and
if it does not fit a whole page either it is still drawn whole from the top of
that page and allowed to overflow — Hancom lets it run past the body box, past
the footer, and off the sheet, dropping whatever falls beyond the paper edge.

`pageBreak` is therefore only half the permission. The other half is
글자처럼 취급, which nothing in the OWPML attribute name suggests.

## The measurement

Reproduce:

```sh
python tests/corpus/render-check/build_table_break_probe.py
python engine/scripts/com_backend.py convert \
    --file tests/corpus/render-check/table-break-probe.hwpx \
    --to   tests/corpus/render-check/table-break-probe.pdf
```

`table-break-probe.hwpx` carries eleven cases. Page geometry is
`render-check-01`'s: A4, body box **65 764 HWPUNIT** (657.6 pt) tall, every
row declared 2 600 HWPUNIT (26 pt), so 25 rows fit a body box and 26 do not.
Every table is inline (`treatAsChar="1"`), the shape `F47` uses. "fresh page"
means the table paragraph itself carries the page break, so the room left is
the whole body box; the other cases put 20 single-line filler paragraphs
between the label and the table, leaving ~325 pt for a 390 pt table.

| case | rows | `pageBreak` | `repeatHeader` | room left | Hancom |
|---|---|---|---|---|---|
| `T01` | 25 (650 pt) | CELL | 0 | full page | whole, fits |
| `T02` | 26 (676 pt) | CELL | 1 | full page | **whole, overflows** to 767 pt |
| `T03` | 30 (780 pt) | CELL | 0 | full page | **whole, overflows off the sheet** (rows 30+ lost) |
| `T04` | 55 (1430 pt) | CELL | 0 | full page | **whole, overflows off the sheet** (rows 30+ lost) |
| `T05` | 15 (390 pt) | CELL | 0 | ~325 pt | **moved whole** to the next page |
| `T06` | 15 (390 pt) | TABLE | 0 | ~325 pt | **moved whole** — same as `T05` |
| `T07` | 15 (390 pt) | NONE | 0 | ~325 pt | **moved whole** — same as `T05` |
| `T08` | 30 (780 pt) | TABLE | 0 | full page | identical to `T03` |
| `T09` | 30 (780 pt) | NONE | 0 | full page | identical to `T03` |
| `T10` | 30 (780 pt) | CELL | 1 | full page | identical to `T03` |
| `T11` | 27 (702 pt) | CELL | 0 | full page | **whole, overflows** to 793 pt |

Not one of the eleven is split. `T05`/`T06`/`T07` differ only in `pageBreak`
and land identically; `T03`/`T08`/`T09`/`T10` differ in `pageBreak` and
`repeatHeader` and land identically. `T02` reproduces `F47` exactly: the body
box ends at 756 pt, the table's last row is drawn at 759–767 pt, on top of the
footer.

### Two Hancom-authored controls

A synthetic writer can always be wrong in a way that disables a feature, so
the same question was put to tables Hancom itself created, through
`com_backend.py edit --ops` (`insert_table`), in a document with 20 filler
lines before the table:

| control | anchoring | rows | Hancom |
|---|---|---|---|
| inline, 41 rows | `treatAsChar="1"` | 41 (525 pt) | moved whole to the next page |
| inline, 81 rows | `treatAsChar="1"` | 81 (1040 pt) | moved whole, then overflowed off the sheet — rows 58+ lost |
| anchored, 81 rows | `treatAsChar="0"` | 81 (1040 pt) | **split at rows 23 and 72, across three pages, header row repeated at the top of each continuation** |

Hancom writes `pageBreak="CELL" repeatHeader="1"` on all three, so the
declaration is identical and only the anchoring differs. The anchored control
is what shows the rule is about 글자처럼 취급 and not about "Hancom never
splits": given an anchored table it splits, repeats the header, and splits
again as many times as it needs to.

The two controls are not committed: Hancom stamps the saving account name
into `Contents/content.hpf` (`lastsaveby`), so they are measurement inputs
only.

## What changed in the renderer

`own_render`'s flow pass had two separate faults, both visible only on `F47`:

1. **The fit test.** A line's page-bottom test uses `baseline`, not
   `vertsize` — measured in [line-fit-rule.md](line-fit-rule.md), because a
   descender may cross the margin. Applied to a line whose content is a
   table, that let 15% of the table hang past the body box: `F47`'s table
   asked for 67 600 HWPUNIT with 60 244 left on the page and was accepted,
   because `0.85 × 67 600 = 57 460` fits. A table has no descender.
   `_row_extent` now clears the whole height for a table-bearing line.
2. **The split permission.** `_split_table_row` split an inline table at a
   row boundary whenever it declared `CELL`. Deleted: `_table_may_split` now
   requires anchored *and* `CELL`, and an inline table that does not fit
   takes the move-whole path that already existed beside it.

The anchored path (`_split_anchor_overflow`,
`_auto_anchor_overflow_action`) is unchanged and is now the *only* splitter,
which the anchored control says is right. Both of its cuts record
`hp:tbl@repeatHeader` as a named limit, which the deleted inline splitter used
to be the only place to do.

> **2026-09-06.** That limit was recorded here as "Hancom repeats the header
> row on a continuation page and we do not". Measured against the reference
> PDF (`engine/scripts/table_split_probe.py`), it does not: the corpus' one
> cross-page table carries `repeatHeader="1"` and repeats nothing, because
> `repeatHeader` repeats the rows a file flags with `hp:tr@header` and no
> `hp:tr` in the corpus carries that attribute. See *The one table Hancom
> splits* in `engine/references/own-render-notes.md`.

### Effect

| | before | after |
|---|---|---|
| `F47` verdict | `differs` (IoU 0.025, ssim_inked 0.018) | `close` (IoU **0.535**, ssim_inked 0.240) |
| render-check verdicts | 1 match / 32 close / 16 differs / 2 unsupported | 1 match / **33 close** / **15 differs** / 2 unsupported |
| render-check pages | 10 (reference 9) | **11** (reference 9) |
| corpus `flow_agreement` | — | byte-identical on all ten forms |

Every other one of the 51 features is unchanged to the digit: this moves
`F47` and nothing else.

The page count getting *worse* is the honest result. Hancom also gives the
table a page of its own; before this change our extra page and our failure to
move the table cancelled out, and now the residual — the cumulative
block-height drift that is backlog item 1 of
[render-check-01.md](render-check-01.md) — is no longer hidden by a second
error. Placement is now right and the drift is now visible, which is the
order those two have to be fixed in.

## Not proven

- **One build, one geometry.** Hwp 2024 13.0.0.2986 / Hancom PDF 1.3.0.550,
  A4 portrait with one column. Nothing here is claimed for another Hancom
  build, for landscape, or for a multi-column section.
- **Anchored `TABLE` / `NONE` were not measured.** The anchored control
  declares `CELL`. The renderer still treats anchored `TABLE` and `NONE` as
  move-whole, which is the reading of the attribute name, not a measurement.
- **Where Hancom clips.** `T03`/`T04` lose their overflowing rows in the PDF
  export. Whether the rows are dropped by the layout or by the export path is
  not separated here; `own_render` draws them, which is a difference this
  page records rather than resolves.
- **Nested and merged rows.** Every probe table is a plain 3-column grid with
  uniform rows. A table whose *single row* is taller than a page, and a table
  with `rowSpan` across the cut, are untested.
- **The row-height floor is untouched.** `hp:cellSz@height` is still not a
  floor (backlog item 2), so `own_render`'s idea of a table's height comes
  from its content. On this document the two agree; on a document where they
  do not, the move-or-stay answer moves with them.
