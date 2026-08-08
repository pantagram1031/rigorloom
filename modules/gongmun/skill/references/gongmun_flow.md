# 공문/기안문 task flow and the check_gongmun contract

Reference for the `gongmun` distribution module's skill fragment. Everything
here is regulation-level: 「행정업무의 운영 및 혁신에 관한 규정 시행규칙」
별지 제1호서식 (기안문) and 별지 제2호서식 (보고서형 기안문) are the ground
truth, and both are in the blank-form corpus.

## 1. The four steps

1. **Inspect.** `engine/scripts/form_inspect.py FORM.hwpx --out
   blank.profile.json`. Read `anchors`, `table_map` and `guide_text` before
   deciding anything. The 기안문 frame is ONE outer table; the 직인 box and the
   발신명의 box are *nested* tables inside the 본문 cell, so they carry their own
   table indices.
2. **Identify the seats.** Four regions, and the document tells you which it
   has — 별지 제1호서식 and 제2호서식 do not have the same seats:
   - **두문**: `행정기관명` (a placeholder: replace it with the agency name),
     then `수신` / `(경유)` / `제목` — labels that stay, with the value written
     after each one.
   - **결재란**: `기안자` / `검토자` / `결재권자`, each with `직위(직급) 서명`,
     plus the `협조자` row. 제2호서식 instead carries a
     `생산등록번호 / 등록일 / 결재일 / 공개 구분` grid and an *unlabelled*
     결재란 whose size the 비고 says may be adjusted.
   - **결문**: `시행 처리과명-연도별 일련번호(시행일)`,
     `접수 처리과명-연도별 일련번호(접수일)`, `우 도로명주소`,
     `홈페이지 주소`, `전화번호( ) 팩스번호( )`,
     `공무원의 전자우편주소`, `공개 구분`.
   - **발신명의 + 직인**: the issuing name, and the red seal box beside it.
     제2호서식 uses `○○○○부(처ㆍ청 또는 위원회 등)` glyph placeholders instead
     of the `발신명의` term.
3. **Fill.** Empty form cells contain a self-closing `<hp:run/>` and no
   `<hp:t>` at all, so a text-keyed replace has nothing to match:
   `preedit.py fill-cells --table N --cell ROW,COL=TEXT` is the path to an
   empty cell. Use `preedit.py replace` for the seats where a guide term *is*
   the placeholder (`행정기관명`, `도로명주소`, …) — there the old text exists
   and must be consumed.
   **본문 takes `--cell-line` once per paragraph** (T39): the regulation puts
   `1.` / `가.` / `1)` / `가)` each on its own paragraph, indented two more
   spaces per level, so a single-paragraph 본문 is the exception rather than
   the norm. On 별지 제1호서식 the 본문 cell is (2,0) and the call also needs
   `--charpr-per-cell 2,0=14` and `--parapr-per-cell 2,0=18` — the cell shares
   itself with the 발신명의/직인 nested tables, so its own blanks are
   centre-aligned and its charPr is the 12pt/97% label face rather than the
   비고 baseline. The core skill's fill recipe carries both decisions
   (sections 1.1 and 1.2).
4. **Check, then verify.**
   `modules/gongmun/scripts/check_gongmun.py filled.hwpx --baseline FORM.hwpx`
   then `pipeline/scripts/visual_verify.py` with
   `modules/gongmun/references/visual_expectations/gongmun.json`. The checker
   judges structure; visual_verify judges the render.

## 2. Document state decides severity

The document says which state it is in, so a blank 서식 is not "a failed 공문":

| state | evidence | consequence |
|---|---|---|
| `blank` | 비고 block present and no guide term consumed | the unfilled shape is *reported*, not failed; finishing rules are `skipped: document_state_blank` |
| `draft` | 비고 present, some guide terms consumed | fill-consistency rules HARD; residue / 비고 / ○-placeholder rules WARN |
| `final` | no 비고 block | everything HARD |

`--mode blank|draft|final` forces a state. `--mode auto` (default) reads it.

## 3. Rules

Every rule is derived from the two corpus forms plus the regulation's own
structure. A rule that cannot be decided from the inputs given is listed under
`skipped` with a reason — it is never silently passed.

| finding | severity | fires when |
|---|---|---|
| `artifact_missing` | HARD | the pinned artifact path does not exist |
| `artifact_malformed` | HARD | `Contents/section*.xml` / `header.xml` is not well-formed (a malformed section renders BLANK in Hancom) |
| `gongmun_structure_absent` | HARD | fewer than two 공문 seat families recognized — the file is not a 기안문 |
| `dumun_label_missing` | HARD, needs `--baseline` | a 두문 label the blank form carries is gone: the frame was destroyed, not filled. Gated on the baseline because 별지 제2호서식 legitimately has no `수신` seat at all — absence alone is not destruction |
| `dumun_seat_unfilled` | HARD (final) / WARN (draft) | a 두문 label carries no value |
| `dumun_seat_half_filled` | HARD | `행정기관명` survives beside the written agency name |
| `gyeoljae_seat_half_filled` | HARD | an approver seat consumed part of its guide vocabulary and kept the rest |
| `gyeoljae_row_half_filled` | HARD | a 결재란 row mixes filled seats with blank or wiped ones |
| `gyeolmun_seat_half_filled` | HARD | a 결문 seat carries a value beside a surviving guide term |
| `gyeolmun_issue_number_malformed` | HARD | a 시행/접수 value is not `처리과명-일련번호(날짜)` |
| `gyeolmun_seat_unfilled` | WARN | a 결문 seat is still the blank form's guide term in a final document (a 공문 may legitimately have no 접수) |
| `balsin_myeongui_missing` | HARD | no 발신명의 seat and no issuing-organization line at all |
| `balsin_myeongui_unfilled` | HARD (final) | the 발신명의 term or a ○ placeholder still occupies the issuer seat |
| `seal_slot_overwritten` | HARD | the 직인 slot carries text other than the seal label |
| `seal_slot_removed` | HARD, needs `--baseline` | the blank form had a 직인 slot and the artifact does not |
| `guide_vocabulary_residue` | HARD (final) / WARN (draft) | a guide term the 비고 says to replace survives as literal text |
| `bigo_block_retained` | HARD (final) / WARN (draft) | the 비고 block ships in the document |
| `placeholder_glyphs_retained` | HARD (final) / WARN (draft) | unfilled `○○○○` runs survive |
| `seat_emptied` | HARD, needs `--baseline` | a seat the blank form carries is empty or gone in the artifact |
| `issuer_not_in_pack` | HARD, needs a non-empty `gongmun_org` pack | no declared organization or department appears in the document |
| `rank_not_in_pack` | WARN, needs a non-empty pack **and** `--baseline` | a 결재란 seat names an undeclared 직위. A filled seat no longer carries its role term, so the blank form is what says where the approver seats are |

Exit codes: 0 clean, 2 usage/input error, 3 HARD finding.

## 4. The seat state mechanism

Every fill rule is one function. For a seat and its guide terms:

- no term survives, a value is present → `filled`
- no term survives, nothing is present → `emptied`
- every term survives, nothing else → `blank_by_design`
- anything else → `half_filled`

`○` runs and layout punctuation are removed before "a value is present" is
decided, so a seat holding nothing but `○○○○` is unfilled, not filled. This
is why the checker carries no per-file strings: the vocabulary is data
(`modules/gongmun/references/gongmun_vocabulary.json`) and each form's own
비고 block is parsed at run time and unioned into the term list.

## 5. What stays blank for a human

- the **직인 impression** — the red box is a placement, not a fill target;
- every **서명** in the 결재란 and the 협조자 row;
- 접수 numbering, which the *receiving* agency writes.

Hand the document back naming these explicitly. Typing a name where a seal or
a signature belongs is the failure this module exists to catch.

## 6. Known boundaries

The checker is term-anchored: it finds a seat because a guide term or a
section label is still there. Three consequences, all of them visible in the
verdict rather than hidden:

- **Pass `--baseline` whenever you have the blank form.** Without it, four
  rules cannot be decided and say so (`dumun_label_missing`, `seal_slot_removed`,
  `seat_emptied`, `rank_not_in_pack` → `skipped: no_baseline`). A seat that was
  *wiped* — guide term deleted, nothing written — is otherwise invisible unless
  a filled sibling in the same 결재란 row exposes it.
- **A fully finished 결재란 reports `skipped: seat_absent`**, because none of its
  cells carries a role term any more. The row-level rule reads the table row
  directly, so a *partly* finished 결재란 is still caught; a fully finished one
  simply has nothing left to judge.
- **별지 제2호서식's 결재란 is unlabelled** to begin with, so its per-seat rules
  are `seat_absent` there too. The ○-placeholder, residue and 비고 rules still
  cover that form.

Out of scope by design: geometry preservation (row heights, merge topology,
page size) belongs to `form_inspect` plus the eval harness's `geometry` check,
and the rendered appearance belongs to `visual_verify`.
