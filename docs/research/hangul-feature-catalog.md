# Hangul (한글) feature catalog — usage-weighted renderer scoreboard

Purpose: a checklist of what real 한글/HWPX authors actually use, mapped to
OWPML/KS X 6101 elements and to `own_render`'s current fidelity, so the own
renderer's completeness can be tracked against real usage rather than against
the standard's full surface.

**Sourcing.** Renderer status and every element name marked *confirmed* come
from `engine/references/own-render-notes.md` (the renderer's own fidelity
log, 862 lines, read in full), `docs/support-matrix.md` (evidence-gated
capability claims), and — for element existence and frequency — two direct
sources fetched for this pass: `engine/references/owpml-inventory.json`
(161 elements, 12 forms; it lives on `origin/claude/engine-e3-owpml-writer`,
not this worktree, fetched via `git show`) and a direct
`grep -oh 'hp:[A-Za-z]*'`/attribute sweep over this worktree's own
`tests/corpus/forms/converted/*.hwpx` (10 forms, unzipped to scratch). The
**Corpus count** column below is the inventory JSON's element count / form
count (authoritative — real XML-parser output); attribute *values* (e.g.
`type="HYPERLINK"`) came only from the direct grep, since the inventory
schema records names and counts, not values. Where neither source shows an
element, the row says **not in corpus** rather than guessing. Element names
still unconfirmed by any source are marked **unknown**. No code was read or
touched.

## Tier 1 — in most documents

| Feature (한글 이름) | What users do with it | OWPML element(s) | Corpus count (elems/forms) | Status |
|---|---|---|---|---|
| 글자 모양 (글꼴/크기/진하게/밑줄/자간/장평) | Per-run character formatting | `hh:charPr`, `hh:bold`, `hh:underline`, `hh:ratio`/`hh:spacing`/`hh:relSz`/`hh:offset` — confirmed | 848 / 12 (`hh:charPr`, `hh:ratio`, `hh:relSz`, `hh:offset`, `hh:underline` all identical); `hh:bold` 193/12 | rendered (typography applied, slot partition is an approximation; bold-fake and font substitution are named limits) |
| 문단 모양 (정렬/줄간격/여백/첫줄들여쓰기) | Per-paragraph layout | `hh:paraPr`, `hh:lineSpacing`, `hh:margin`, `hh:align` — confirmed | 811 / 12 (`hh:paraPr`, `hh:align`); `hh:lineSpacing`/`hh:margin` 1622/12 | rendered (cached `hp:lineseg` used where valid; own breaker for edited paragraphs, see backlog #8) |
| 표 (行/列, 셀 병합, 테두리/음영) | Tabular data, forms | `hp:tbl`/`hp:tr`/`hp:tc`, `hh:borderFill`, `hc:fillBrush` — confirmed | 86 / 12 tables, 540 `hp:tr`, 1671 `hp:tc`; `hh:borderFill` 495/12 | rendered (column/row solved by `solve_tracks`; row height = max over cells, fixed in this pass) |
| 그림 삽입 (이미지) | Photos, screenshots, diagrams | `hp:pic`, `hp:imgClip`, `hp:imgDim`, `hp:flip` — confirmed | 2 / 2 forms only — pictures are rare even in this corpus of blank forms | rendered (crop, flip honoured; rotation declared, not applied; undecodable EMF/WMF stays a placeholder) |
| 쪽 설정 (용지 크기/여백/방향) | Page setup | `hp:secPr`/`hp:pagePr`, `hp:margin` — confirmed | 12 / 12 (one per section) | rendered (A4 corpus-verified; gutter side reported, not folded in) |
| 머리말/꼬리말 (header/footer) | Repeating page furniture | `hp:header` — confirmed present on one corpus form; `hp:footer` — **not in corpus** (no matching element anywhere in the 161-entry inventory) | 1 / 1 form | **declared-skipped** — grouped in named limit #9 ("not drawn"), unmeasured against a real header/footer document |
| 쪽 번호 매기기 (page numbers) | Sequential page numbers | `hp:pageNum` (own-render-notes.md's name) — **not in corpus**; the corpus's own page-number-format element is `hp:autoNumFormat type="DIGIT"` (confirmed by direct grep) but it lives inside `hp:footNotePr`, not a placed page-number stamp | 0 direct `hp:pageNum` hits; consistent with own-render-notes.md's own claim that this corpus's forms carry "no page numbers" | rendered *when present* (bottom-edge-anchored, measured against a Hancom reference to 0.07 pt; `BOTTOM_LEFT/CENTER/RIGHT` only, other `pos` declared-skipped) — but untestable against this corpus, since no form uses one |
| 각주/미주 (footnotes/endnotes) | Citations, definitions | `hp:footNotePr`/`hp:endNotePr` — confirmed (numbering settings, parsed not acted on); note-content element — **not in corpus** (no note-body element found; every form declares the *Pr* settings but places no actual note) | 12 / 12 each | **declared-skipped** — measured report document declares `hp:footNotePr`/`hp:endNotePr` but carries no actual note, so this lane is "still unmeasured against a real one" |

## Tier 2 — common in reports/official docs

| Feature (한글 이름) | What users do with it | OWPML element(s) | Corpus count (elems/forms) | Status |
|---|---|---|---|---|
| 수식 (equation editor) | Math in reports/papers | `hp:equation` — confirmed | **not in corpus** (own-render-notes.md: "No corpus form contains an `hp:equation`" — not in the 161-element inventory either) | **declared-skipped** — placeholder box at declared `hp:sz`; 14 boxes in the measured (private, non-corpus) report doc, largest unimplemented element on a real report |
| 캡션 (그림/표/글상자 번호+설명) | Auto-numbered figure/table captions that follow the object | Likely no distinct element — an ordinary paragraph combining 문단 번호 + 책갈피/상호참조 per [help.hancom.com/caption](https://help.hancom.com/hoffice/multi/ko_kr/hwp/insert/caption.htm) | **not in corpus** as a distinct tag (none found) — consistent with "no distinct element" reading | **unknown** (if the numbered text is baked into the run at save time it likely renders as plain text already, but untested) |
| 개요 번호 (다단계 번호 매기기, e.g. 1. → 1.1 → 1.1.1) | Report/paper heading numbering | Confirmed by direct grep: `hh:numbering`/`hh:numberings` (list definition, `start` attr), `hh:paraHead` (per-level format: `numFormat="DIGIT"`, `level`, `align`, `textOffset`), `hh:heading type="OUTLINE"\|"NONE" idRef="…" level="N"` (paragraph→numbering link — this is the de facto `outlineLevel`), `hh:outline type="…"` (a separate, mostly `NONE` legacy/compat marker) | `hh:numbering` 11/7, `hh:paraHead` 110/7, `hh:heading` **814/12** (every form), `hh:outline` 848/12 | **unknown** render status — outline linkage exists in every corpus form, but own-render-notes.md never discusses whether a computed numeral is drawn; untested |
| 스타일 (문단/글자 스타일 등록·일괄 적용) | Consistent formatting, easy global edits | `hh:style`/`hh:styles` — confirmed by direct grep, e.g. `<hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="4" charPrIDRef="0" .../>` (Hancom's default 15-style set: 바탕글/본문/개요 1-3/…) | `hh:style` 305/12 (every form) | likely **rendered indirectly** — the renderer reads resolved `hh:charPr`/`hh:paraPr` by ID (811/811 corpus `paraPr` carry concrete values), which is what a style application resolves to on save; the style's own name/identity is not tracked, but that shouldn't affect pixels |
| 차례/목차 (TOC) | Auto-generated table of contents | No distinct TOC element in the 161-entry inventory; `hp:fieldBegin` types actually found in this corpus are `FORMULA` (계산식, 8 of 9 instances) and `HYPERLINK` (1 instance) — **no `TOC` field type observed** | `hp:fieldBegin`/`hp:fieldEnd` 9/2 forms (kstartup, moel-2013); zero of those are TOC-typed | **not in corpus** as a distinct usage; mechanism itself (fields) is confirmed, TOC specifically is not |
| 책갈피 (bookmarks) | Cross-references, internal anchors | **not in corpus** — no `bookmark`-named element anywhere in the 161-element inventory | 0 / 0 | **not in corpus** |
| 하이퍼링크 (hyperlinks) | External/internal links | `hp:fieldBegin type="HYPERLINK"` — **confirmed** by direct grep (kstartup) | 1 instance (part of the 9/2 `fieldBegin` total above) | text is an ordinary run inside the field, so it likely renders as plain text; the link semantic itself has no visual effect either way |
| 누름틀/필드 (click-here fields, form placeholders) | Fill-in-the-blank forms, templates | Hancom's UI calls this 누름틀 with a `CLICKHERE`-style field per [help.hancom.com/madanginfo(press)](https://help.hancom.com/hoffice/multi/ko_kr/hwp/insert/madanginfo/madanginfo(press).htm), but **no `CLICKHERE`-typed `hp:fieldBegin` was found in this corpus** — only `FORMULA` and `HYPERLINK` types are present | 0 CLICKHERE of 9 `fieldBegin` instances | **not in corpus** (as this specific field type); the general field element (`hp:fieldBegin`/`hp:fieldEnd`) is confirmed, just not this variant |
| 다단 (multi-column text) | Newsletter/report layouts | `hp:colPr` — confirmed | 34/12 (inventory) — every form declares at least one, mostly default single-column | **declared-skipped** — named limit #7: "ignored — PARA and COLUMN both resolve to the paragraph's container" |
| 구역 나누기 (section breaks) | Different page setup mid-document | `hp:secPr` — confirmed | 12/12, one per form (no form has 2+) | **partial** — section0 is fully laid out; named limit #8: "Only `section0` is laid out. No corpus form has more, but the sidecar says so when one does" (untested against a real multi-section doc) |
| 바탕쪽 (master pages) | Repeating background/watermark per section | Master-page namespace `xmlns:hm="…/2011/master-page"` is declared in every corpus section, but **zero `hm:*` elements are ever used** — confirmed by direct grep across all 10 local forms | 0/10 usages despite namespace present in 10/10 | **not in corpus** (used) — grouped in named limit #9 with headers/footers as declared-skipped regardless |
| 글상자/그리기 개체 (text boxes, shapes) | Callouts, diagrams, annotations | `hp:container` (and drawing shapes generally) — confirmed | not separately itemised in the fetched inventory slice; `hp:ctrl` (generic control wrapper) 110/12 | **declared-skipped** — grey outlined placeholder box, labelled, at declared extent (or fallback size + `?` if extent unknown) |
| 글맵시 (WordArt-style shaped text) | Decorative titles/logos on forms | Best corpus candidate is `hp:drawText` (`lastWidth`/`name`/`editable` attrs, found only in kstartup) — but this reads as plain text-in-a-shape, not confirmed WordArt specifically; no distinct `textart`-named tag exists anywhere in the 161-element inventory | `hp:drawText` 5/1 form | **not in corpus** as confirmed WordArt; `hp:drawText` is real but its identity as 글맵시 vs. an ordinary text box is unconfirmed |
| 메모 (memo/comment threads) | Reviewer notes, not part of body text | `hh:memoPr`/`hh:memoProperties` confirmed (memo *style* definitions: color, line width, item count) — but no memo anchor/content element found anywhere in the inventory | 2/2 forms (style defs only) | **declared but unused** — every form that declares memo styling places zero actual memos; render status for real memo content remains **unknown** |
| 변경 내용 추적 (track changes) | Collaborative editing/redlines | `hh:trackchageConfig` confirmed (sic — that literal spelling, missing the "n", is what the corpus and spec use) — a config-only element (on/off, author color, etc.); no actual insert/delete change-mark element found anywhere in the inventory | 12/12 (every form declares the config) | **declared but unused** — config always present, no form contains an actual tracked change; render status **unknown** |

## Tier 3 — rare

| Feature | Note |
|---|---|
| 문서 끼워넣기 (insert another .hwp's content) | Hancom flattens on insert; if it introduces a new `hp:secPr` it inherits the multi-section limit above |
| 세로쓰기 (vertical text) | Not mentioned anywhere in own-render-notes.md; status unknown |
| 표 셀 대각선 (diagonal cell lines) | UI feature confirmed by [comeinsidebox.com](https://comeinsidebox.com/%ED%95%9C%EC%BB%B4-%EC%98%A4%ED%94%BC%EC%8A%A4-%ED%95%9C%EA%B8%80-%ED%91%9C-%EC%97%90%EC%84%9C-%EB%8C%80%EA%B0%81%EC%84%A0-%EA%B7%B8%EB%A6%AC%EA%B3%A0-%ED%91%9C-%EA%B8%80%EC%9E%90-%EC%A0%95%EB%A0%AC/); no renderer evidence either way |
| 개체 회전 (rotating pictures/shapes) | `hp:pic` rotation — confirmed **declared, not applied** (named limit #1 in Report-class documents, `hp:flip` list) |
| 워터마크/배경 | Typically implemented via 바탕쪽 — inherits that gap |
| 이중선/원형 등 특수 테두리 (non-solid, non-`DOUBLE_SLIM` border types) | Confirmed **stroked as solid** — named limit #4 |
| 탭 문자가 이미 박힌 문단 (literal `<hp:tab/>` in cached layout) | Confirmed **not resolved** — named limit #5; 3 corpus paragraphs affected |

## User tips and techniques → rendering-fidelity implications

| Technique (한글) | What it does | Fidelity implication | Source |
|---|---|---|---|
| 표 나누기·합치기 (split/merge table or cells) | Produces the same `hp:tbl`/`hp:tr`/`hp:tc` grid with different span structure | No new element — already exercised by `solve_tracks`, which recovers every column on the corpus including 15-column merged headers | own-render-notes.md; [samsung community table tips](https://r1.community.samsung.com/t5/%ED%83%9C%EB%B8%94%EB%A6%BF/%EC%82%BC%EC%84%B1%EB%85%B8%ED%8A%B8-%ED%95%A9%EC%B9%98%EA%B8%B0-%EA%B8%B0%EB%8A%A5/td-p/24639509) |
| 줄 간격 관행 (160% 기본값, PERCENT vs FIXED) | Sets `hh:lineSpacing@type`/`@value` | Confirmed handled — `PERCENT` relation (`vertsize+spacing == round(textheight×value/100)`) holds on every PERCENT paragraph in the corpus | own-render-notes.md; [woowell.co.kr 줄간격 가이드](https://woowell.co.kr/%ED%95%9C%EA%B8%80-%EC%A4%84%EA%B0%84%EA%B2%A9-%EB%A7%9E%EC%B6%94%EA%B8%B0-%EB%B0%A9%EB%B2%95-4%EA%B0%80%EC%A7%80/) |
| 자간 조정 (character spacing, `hh:spacing`) | Tightens/loosens letter spacing for fit | Applied and pixel-validated in em units against a Hancom reference — but the *space-adjacent* advance width is the single largest unresolved gap in line breaking (see backlog #8) | own-render-notes.md |
| 쪽 나누기 (page break) vs 구역 나누기 (section break) | Forces a new page vs a new page-setup region | `@pageBreakBefore` is **parsed and not acted on** (no block-level pagination); a real section break hits the multi-section limit (#8 above) | own-render-notes.md |
| 각주로 출처/정의 처리 | Footnotes for citations, common in 소논문/보고서 | Entirely invisible in the current render — highest-impact T1 gap for report-class documents | own-render-notes.md |
| 개요 번호로 장·절 구성 | Multi-level heading numbers (1 → 1.1 → 1.1.1) | Confirmed present in every corpus form (`hh:heading` 814/12) via `hh:numbering`/`hh:paraHead`/`hh:heading`; untested whether the renderer draws the computed numeral — if it's computed rather than baked as literal text, headings could render with **no number at all** | direct corpus grep, this pass; own-render-notes.md is silent on the mechanism |
| 서식 복사 (format painter) | Copies a run's `charPrIDRef`/paragraph's `paraPrIDRef` onto new text | No new element — transparent to the renderer, same as any other charPr/paraPr application | own-render-notes.md (ID-ref resolution mechanism) |
| 스타일 일괄 적용/수정 | Central style definition, applied across many paragraphs | Likely transparent — HWPX resolves a style to a concrete `paraPr`/`charPr` at save (774/774 corpus paragraphs carry concrete values), so visual output should be right even though the style's own name is untracked | own-render-notes.md |
| 한자 변환 (Hanja conversion, incl. 한글(漢字) 병기) | Converts or annotates text with Hanja | The `hanja` language slot is a real, declared metric slot (`hh:ratio hanja="…"` etc.) and is applied like any other slot; whether "both shown" 병기 uses a separate ruby-style element is unconfirmed | own-render-notes.md (typography slot table) |
| 캡션 자동 번호 매기기 | Auto-numbers and re-numbers figures/tables on reorder | The renumbering itself is an editing-time behavior; only the *baked* text at render time matters, and that is unverified (see Tier 2 캡션 row) | [office.safechem.co.kr](https://office.safechem.co.kr/2025/11/blog-post_242.html) |
| 그림 배치 — 글 앞으로/뒤로, 어울림(text wrap) | Anchors an image relative to text with wrap or z-order | Position honoured; **z-order and text-wrap are both unimplemented** — "text does not wrap around anchored objects" (named limit #6) | own-render-notes.md |
| 문서 끼워넣기 (insert another document) | Merges another .hwp/.hwpx's content in place | If the inserted content carries its own `hp:secPr`, it inherits the multi-section limit; otherwise transparent | own-render-notes.md (inference) |
| PDF 저장 옵션 (글자를 이미지로 저장 여부 등) | Controls whether Hancom's own PDF keeps a text layer | Directly relevant to `render_cert`: **this renderer's own PDF output has no vector text layer**, so the word-anchor certification channel cannot run yet (see backlog #10) | own-render-notes.md, *Path to render_cert certification* |

## Prioritized backlog — top 10 by (tier × visible impact)

Ranked using the renderer's own `elements_skipped`/named-limit evidence
where available; #1–#3 and #8/#10 restate items already ordered in
`own-render-notes.md`'s own "Remaining order of work," folded in here against
usage tier rather than left as a separate list.

| # | Item | Tier | Element | Test that would prove it |
|---|---|---|---|---|
| 1 | Draw footnote/endnote content | T1 | `hp:footNotePr`/`hp:endNotePr` + (unnamed) note-content element | Render a report doc with a real footnote; `text_line_pair_rate` and `ssim_inked` should move the way `hp:pageNum` did (0.8134→0.8390) when it was added |
| 2 | Draw headers/footers | T1 | `hp:header` (confirmed present on one corpus form), `hp:footer` | Re-render that corpus form with headers on; before/after `ssim_inked` on that one form isolates the effect |
| 3 | Close the line-breaker advance-width gap | T1 | line-layout metrics, not a new element | A reference-PDF measurement of Hancom's actual space advance in a Korean face (own-render-notes' own next step); target: move break-position agreement past 43/216 |
| 4 | Vector PDF text output | T1 (foundational — blocks certification for every tier) | render encoder, not an OWPML element | `render_cert.py`'s word-anchor (PyMuPDF text-extraction) channel returns non-empty text and passes on at least one document class |
| 5 | Render `hp:equation` | T2 | `hp:equation` | A committed synthetic equation fixture (none exists today) rendered and scored; 14 real boxes in the measured report doc go from placeholder to glyphs |
| 6 | Multi-section documents | T2 | `hp:secPr` (2nd+ section) | A synthetic 2-section fixture; `page_count_exact` and correct per-section page setup pass |
| 7 | Multi-column layout | T2 | `hp:colPr` | A synthetic COLUMN-type fixture; verify columns actually split instead of collapsing into one container |
| 8 | Numbered outlines / auto-numbering | T2 | `hh:numbering`/`hh:paraHead`/`hh:heading` (all confirmed, present in 12/12 corpus forms) | A doc with 개요 번호 headings; check whether the rendered numeral text is present at all, since this is currently untested |
| 9 | Text wrap around anchored images (어울림) | T2 | `hp:pos` wrap attributes | A doc with a wrap-anchored image beside text; `text_line_iou` on the wrapped paragraph vs. today's non-wrapping draw |
| 10 | Regenerate the three reduced (0.707-scale) reference PDFs | T1/T2 (blocks scoring, not rendering) | n/a — operator action on `gongmun`/`research` reference PDFs | Once regenerated, `gianmun-1ho/2ho` and `nrf` move from `pass: null` to a real scoreboard verdict |

## Sources

- `engine/references/own-render-notes.md` (repo-local, read in full — primary source for renderer status and every *confirmed* element name)
- `docs/support-matrix.md` (repo-local — evidence-gated capability claims, PDF conversion and render-probe rows)
- `engine/references/owpml-inventory.json` on `origin/claude/engine-e3-owpml-writer` (161 elements, 12 forms; fetched via `git show`, not present on this branch) — source of every **Corpus count** figure
- Direct `grep -oh 'hp:[A-Za-z]*'`/attribute sweep over this worktree's `tests/corpus/forms/converted/*.hwpx` (10 forms unzipped to scratch) — source of every confirmed attribute *value* (`type="HYPERLINK"`, `type="FORMULA"`, `type="OUTLINE"`, `numFormat="DIGIT"`, style names, and the `hm:` master-page namespace's zero real usages)
- https://tech.hancom.com/hwpxformat/ — Hancom's own HWPX format overview (`hp:p`/`hp:run`/`hp:t`)
- https://tech.hancom.com/python-hwpx-parsing-2/ — Hancom tech blog, Python HWPX parsing
- https://github.com/hancom-io/hwpx-owpml-model — Hancom's own OWPML filter model repo
- https://github.com/airmang/python-hwpx — community OWPML library (`hp:tab`, `hp:pic`, `charPrIDRef` confirmed in its docs)
- https://github.com/neolord0/hwpxlib — community Java OWPML library
- https://help.hancom.com/hoffice/multi/ko_kr/hwp/insert/caption.htm — 캡션 넣기
- https://help.hancom.com/hoffice/multi/ko_kr/hwp/insert/caption_memory.htm — 개체에 따른 캡션 위치 기억
- https://help.hancom.com/hoffice/multi/ko_kr/hwp/insert/madanginfo/madanginfo(press).htm — 누름틀 필드 입력
- https://woowell.co.kr/한글-줄간격-맞추기-방법-4가지-총정리/ — 줄간격 실무 가이드
- https://comeinsidebox.com/한컴-오피스-한글-표-에서-대각선-그리고-표-글자-정렬/ — 표 대각선/정렬 팁
- https://www.inline-ai.com/blog/hwp-table-of-contents-guide/ — 목차·책갈피·상호참조 가이드
- https://office.safechem.co.kr/2025/11/blog-post_242.html — 캡션 자동번호 오류 해결

**Gap resolved (follow-up pass):** `engine/references/owpml-inventory.json`
does not exist on this branch but lives on `origin/claude/engine-e3-owpml-writer`;
fetched via `git show` and cross-checked against a direct grep of this
worktree's own corpus XML. That closed most of the earlier "unknown" rows:
개요 번호, 스타일, 하이퍼링크 and 다단 are now element-confirmed with corpus
counts; 목차, 책갈피, 바탕쪽 (used), 누름틀 (as a `CLICKHERE` field) and 글맵시
are now confirmed **not in corpus** rather than left unguessed; 메모 and
변경추적 are confirmed **declared but never used** (their config/style
elements are present in every form, their content elements are not).
Genuinely open: whether the renderer draws a computed outline numeral at all
(no test either way), and the exact note-content element for 각주/미주 (its
*Pr* settings element is confirmed, its content element is not, in any
source consulted).
