# D1 — one-line pagination drift (WindPath shipped vs rigorloom reproduction)

Worktree: `C:\Users\user\dev\rigorloom-stage1` (HEAD 6161574). Read-only; no engine edits.

**PDFs.** Reproduction `C:\Users\user\dev\reproduce-windpath\output\out.pdf` vs shipped `C:\Users\user\dev\reproduce-windpath\reference\shipped.pdf` (= `agenthwpx\reports\report-windpath-hanmadang\output\v7\out.pdf`). Both 18 pages, A4 `595×841` pt.

**HWPX.** Shipped `...\output\v7\out.hwpx`. Reproduction `C:\Users\user\dev\reproduce-windpath\output\out.hwpx`.

## 1. Page-1 PDF lines (PyMuPDF)

Matching lines 000–029 are identical in text, `y0`/`y1`, `x0`/`x1`, line height, and font size. The first differing break is shipped line 030.

| | last page-1 body line | next line |
|---|---|---|
| shipped | 030 `y0=756.34` “곳이 이렇게 가까이 있다면, 두 곳을 잇는 길을 따라 나무를 심어 찬 공기가 지나는 통로를 만들자” | page 2 starts “는 것이 도시바람길숲의 발상이다. …” |
| repro | 029 `y0=738.36` “은 온도를, … 뜨거운 곳과 시원한 ” | that shipped-030 line is page 2 line 001 at `y0=70.81` |

Body metrics on every shared page-1 line (title / abstract / 서론):

- font: Batang `size=9.952` (10 pt), `h≈9.95`
- inter-line `Δy=17.98` pt = 180% of 10 pt
- full-line x: `x0=76.52`, `x1=538.15` (w=461.63) or `x1=541.58` on the slightly longer justified lines
- title 20.024 pt, 초록/저자 11.031 pt, footer Gulim 9.952 at `y0=797.09` — all match

The missing repro line would sit at shipped’s `y0=756.34` / `y1=766.29`, ~31 pt above the footer. Geometry does not forbid it. Hancom is refusing a one-line paragraph fragment at the bottom of the page.

By page 10 the one-line shift has accumulated (~2 extra body lines, ~36 pt). Shipped keeps “그림 12. 같은 추가 녹지 면적을 맞춘 공정 비교” on page 10 at `y0=735.07`; repro drops that caption to page 11 (`y0=70.79`). FILL already flags this as `figure_placement: caption_missing` at `at_y=762.2` on page 10.

## 2. HWPX: page definition and first body paragraphs

`hp:pagePr` is byte-identical:

```
landscape="WIDELY" width="59528" height="84188" gutterType="LEFT_ONLY"
margin header="2835" footer="2835" gutter="0" left="7654" right="5669" top="4252" bottom="3402"
```

`ops.json` `page_binding` uses those same HWPUNIT margins. `set_line_spacing: percent=180` matches both files’ body `lineSpacing type="PERCENT" value="180"`. Neither op is the drift.

The 서론 first body paragraph is the same 318 characters in both files. Heading text matches. What differs is the paragraph property it points at:

| | paraPrIDRef | charPrIDRef | breakSetting |
|---|---|---|---|
| shipped p019 | **24** | 20 | `widowOrphan="0"` `keepWithNext="0"` `breakNonLatinWord="KEEP_WORD"` `align=JUSTIFY` `lineSpacing PERCENT 180` |
| repro p019 | **36** (clone of 24) | 27 | same except **`widowOrphan="1"`** |

`paraPr id="24"` is identical in both `header.xml`. Repro cloned it to id 36.

Quoted attributes (repro `header.xml` `paraPr id="36"`, the only pagination-relevant delta vs 24):

```
<hh:align horizontal="JUSTIFY" vertical="BASELINE"/>
<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD"
                 widowOrphan="1" keepWithNext="0" keepLines="0"
                 pageBreakBefore="0" lineWrap="BREAK"/>
<hh:lineSpacing type="PERCENT" value="180" unit="HWPUNIT"/>
```

Shipped `paraPr id="24"` has `widowOrphan="0"`; every other listed field matches.

Body `charPr` (shipped 20 vs repro 27) is equivalent: `height="1000"`, `spacing=0`, `ratio=100`, `relSz=100`, Batang `fontRef hangul="3"`, no letter-spacing, no condense, no bold. Not a wrap-width change. That is why lines 000–029 occupy the same boxes.

Repro `header.xml` grew because `apply_typeset_defaults` cloned paraPr 33–43 (and two extra charPr). Shared ids 0–24 are unchanged; 25–32 were also rewritten as later clones, but the 서론 body does not use them.

## 3. Cause

Hancom widow/orphan protection (`widowOrphan="1"`) forbids leaving a single line of a multi-line paragraph at the bottom of a page. After line 029, two lines of the same 서론 paragraph remain. Shipped (`widowOrphan="0"`) keeps the first of those two on page 1. Repro (`widowOrphan="1"`) moves both to page 2. Downstream pages, including 그림 12’s caption, follow that one-line (then two-line) cascade.

The clone is written by **`tidy_hwpx.apply_typeset_defaults`** (`engine/scripts/tidy_hwpx.py`, function starts at line 829; `want_widow_str = "1"` at line 904; patch via `_patch_parapr_block` at 922–924). `fill_report.run_typeset_defaults` (`engine/scripts/fill_report.py` 795–819) calls it whenever `--form-profile` is set, immediately before PDF convert (loop path 1516–1517, assemble path 1762–1763). Comment at fill_report.py:54–56 / 1894–1895: “§O 조판 기본값(전 본문 widowOrphan=1)”.

`com_backend.set_line_spacing`, `page_binding`, and `build_report` op emission are not the differing attribute.

Secondary (not the page-1 break, does explain why the figure and caption can split): default caption prefixes in `apply_typeset_defaults` are `["표 ", "[그림"]` (`tidy_hwpx.py:760`). WindPath captions are `그림 12. …`, so Rule 2 does not mark the picture paragraph `keepWithNext=1`. Shipped figure `paraPr=32` / caption `paraPr=26` (RIGHT); repro figure `paraPr=38` (`widowOrphan="1"` `keepWithNext="0"`) / caption remapped onto body clone 36 (JUSTIFY). FILL’s `caption_missing` on page 10 is this cascade plus that split.

## 4. Classification

Not a port gap of fork behaviour: `agenthwpx` has no `apply_typeset_defaults`, and shipped v7 body stays on form `paraPr 24` with `widowOrphan="0"`. The form profile even records `break_audit.widowOrphan: 0`. Rigorloom added §O typeset defaults on top of the fork.

Not a Hancom version/rendering difference: the XML that Hancom paginates is different.

Not a content revision: the 서론 paragraph text is identical.

It is a **rigorloom extra default** (`widowOrphan=1` forced on every top-level body paragraph) that the shipped v7 run never applied. That default was intended to remove a page-2 lone `다.` (master plan §4); on this document it costs the last line of page 1.

**Suggested fix.** Stop forcing `widowOrphan=1` in `apply_typeset_defaults` when the form already has `widowOrphan=0` (or gate `--typeset-defaults` so a WindPath-class reproduction can keep fork pagination).

**Confidence.** High (~0.93): identical line boxes through line 029, identical paragraph text, single attribute `widowOrphan` 0→1 on the cloned body style, and that attribute’s semantics match the orphaned last line.
