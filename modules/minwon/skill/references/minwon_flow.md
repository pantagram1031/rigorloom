# 민원·신고 서식 task flow and the check_minwon contract

Reference for the `minwon` distribution module's skill fragment. Everything here
is family-level: it comes from the 별지서식 convention itself, measured against
the four family-① forms in the blank-form corpus
(`tests/corpus/forms/manifest.json`):

| slug | what it contributes |
|---|---|
| `jumin-deungchobon-sinchengseo` | 주민등록법 시행규칙 별지 제7호서식 — the canonical dense grid: 41 `[ ]` slots, the `[ ]에 √표를 합니다` instruction, a 3-page 유의사항, four `(서명 또는 인)` seats, three 주민등록번호 seats |
| `jeongbo-gonggae-cheongguseo` | 정보공개법 시행규칙 별지 제1호의2서식 — the shading declaration (`색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다`), a shaded 접수번호/접수일/처리기간 block, the 접수증 block, the only 직인 slot in the family |
| `saeopja-deungnok-sinchengseo` | 부가가치세법 시행규칙 별지 제4호서식 — the densest grid (784 cells, 93 `[ ]` slots), four 별지서식 header lines and six paper-spec footers across 부표, column-header 주민등록번호 seats |
| `admrul-gajokdolbom-hyuga-sinchengseo` | 행정규칙 별지 제13호 — the sparse variant: half its seats are top-level paragraphs, `신청인 : ○○○ (인)`, a `20 . . .` date seat, **no** 유의사항 and **no** paper-spec footer |

## 1. The four steps

1. **Inspect.** `engine/scripts/form_inspect.py FORM.hwpx --out
   blank.profile.json`. Read `anchors`, `table_map` and cell shading before
   deciding anything. Family ① is one page-filling outer table per page with
   heavy merging — 주민등록 등초본 신청서 has 85 cells of which 76 are merged, so
   cell addresses are sparse and never a dense grid.
2. **Identify the seats.** Six regions, and the document tells you which it has:
   - **frame**: the `■ …시행규칙 [별지 제N호서식] <개정 …>` header line, the
     `210mm×297mm[백상지…]` footer (once per page), and the `귀하` addressee line.
     None is a fill target; the addressee's *parenthesized guide term* is
     (`(접수 기관의 장) 귀하` → the actual authority).
   - **접수·처리 (staff)**: 접수번호 / 접수일 / 처리기간 / 접수부서 / 접수자 and
     the 접수증 block. Not yours.
   - **applicant**: 성명 / 주소 / 연락처 / 대상자와의 관계 — the seats you fill.
   - **선택 항목**: `[ ]` and `□` groups.
   - **human**: `(서명 또는 인)`, `(인)`, the 직인 box.
   - **identity**: 주민등록번호 / 생년월일 / 여권ㆍ외국인등록번호 /
     사업자등록번호 — never fabricated.
   - **guide**: 유의사항 / 수수료 / 제출서류 / 작성방법 / 처리절차 / 동의 — keep.
3. **Fill.** Empty form cells contain a self-closing `<hp:run/>` and no `<hp:t>`
   at all, so a text-keyed replace has nothing to match:
   `preedit.py fill-cells --table N --cell ROW,COL=TEXT` is the path to an empty
   cell. Use `preedit.py replace` where the old text exists and must change —
   toggling `[ ]` to `[√]`, writing a value after a label, replacing the
   addressee guide term.
4. **Check, then verify.**
   `modules/minwon/scripts/check_minwon.py filled.hwpx --baseline FORM.hwpx
   --fill-map fill.json`, then `pipeline/scripts/visual_verify.py` with
   `modules/minwon/references/visual_expectations/minwon.json`. The checker
   judges structure; visual_verify judges the render.

## 2. Document state decides severity

The document says which state it is in, so a blank 서식 is not "a failed 신청서":

| state | evidence | consequence |
|---|---|---|
| `blank` | no checkbox marked, the `년 월 일` seat still unfilled, (with a baseline) no cell changed | the unfilled shape is *reported*, not failed; the finishing rules are `skipped: document_state_blank` |
| `draft` | something written, date seat still unfilled | preservation rules HARD; finishing rules (선택, ○-placeholder) WARN |
| `final` | no unfilled date seat remains | everything HARD |

`--mode blank|draft|final` forces a state. `--mode auto` (default) reads it.

## 3. Rules

Every rule is derived from the four corpus forms. **Ten of the thirteen
structural rules need `--baseline`** — the family's rules are overwhelmingly
preservation rules, and "was this destroyed?" is only decidable against the form
the artifact came from. A rule that cannot be decided from the inputs given is
listed under `skipped` with a reason — it is never silently passed.

| finding | severity | fires when |
|---|---|---|
| `artifact_missing` | HARD | the pinned artifact path does not exist |
| `artifact_malformed` | HARD | `Contents/section*.xml` / `header.xml` is not well-formed (a malformed section renders BLANK in Hancom) |
| `minwon_structure_absent` | HARD | fewer than two 민원 서식 seat families recognized — the file is not a 신청서/청구서/신고서 |
| `byeolji_header_lost` | HARD with `--baseline`, WARN without | a `[별지 제N호서식]` header line the blank form carries is gone. 사업자등록 신청서 carries four (본서식 + 부표 1 + 부표 2 + …), so dropping a page loses one |
| `paper_spec_footer_lost` | HARD, needs `--baseline` | fewer `210mm×297mm[백상지…]` footers than the blank form has. 행정규칙 서식 has none, and the rule reports `none_in_baseline` rather than inventing a requirement |
| `addressee_line_lost` | HARD, needs `--baseline` | a `귀하` line is gone. Replacing the guide term before it is *correct* and does not fire |
| `staff_seat_filled` | HARD, needs `--baseline` | a 접수·처리 기관 seat changed. Recognized by 접수/처리 label, or by dark shading **where the form declares the shading rule** |
| `staff_seat_removed` | HARD, needs `--baseline` | a 접수·처리 기관 seat cell no longer exists |
| `checkbox_selection_absent` | HARD (final, form declares `[ ]에 √표`) / WARN | the document carries 선택 항목 and not one box is marked |
| `checkbox_option_lost` | HARD, needs `--baseline` | a cell has fewer checkbox slots than the blank form's — an option was deleted rather than marked |
| `signature_marker_lost` | HARD, needs `--baseline` | a `(서명 또는 인)` marker the blank form carries is gone. Cells are compared by address; top-level paragraphs by count, because a paragraph has no stable address |
| `seal_seat_overwritten` | HARD, needs `--baseline` | the 직인 slot gained text, or is gone |
| `guide_block_lost` | HARD, needs `--baseline` | a 유의사항 / 수수료 / 제출서류 / 작성방법 / 처리절차 / 동의 block the blank form carries is gone |
| `identity_value_invented` | HARD, **no baseline needed** | a 주민등록번호-shaped value appears that no `--fill-map` value declared |
| `identity_seat_autofilled` | HARD, needs `--baseline` | an identity seat the blank form left empty now carries an undeclared value |
| `placeholder_glyphs_retained` | HARD (final) / WARN (draft) | unfilled `○○○` runs survive |

Exit codes: 0 clean, 2 usage/input error, 3 HARD finding.

## 4. The two mechanisms worth understanding

**Shading only means "staff-only" where the form says so.** 정보공개 청구서 paints
its 접수번호/접수일/처리기간 `#B2B2B2` and prints
`※ 색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다`. 주민등록 등초본 신청서
paints cells `#B2B2B2` too — but they are section headers and instruction blocks,
and **one of those instruction blocks carries the `[ ]` boxes the applicant must
mark.** So the shading recognizer is gated on the declaration, and additionally
exempts any cell carrying a checkbox glyph. The label-anchored recognizer
(접수번호 / 처리기간 / …) works with or without the declaration, which is what
covers 사업자등록 신청서's shaded-but-undeclared 접수번호 row.

**An identity seat is a label, not prose.** A cell qualifies only when it carries
no checkbox glyph and its squeezed text is at most 40 characters. The real seats
are 4–21 characters (`주민등록번호`, `생년월일(성별)()`,
`여권ㆍ외국인등록번호(외국인의경우작성)`); 주민등록 등초본 신청서's instruction
block mentions 생년월일 inside ~150 characters *and* carries checkboxes. Without
the discriminator, every legitimate checkbox mark registered as an identity
autofill.

Both thresholds are declared values in
`modules/minwon/references/minwon_vocabulary.json`
(`shaded_face_max_brightness`, `identity_seat_max_cell_chars`) with the measured
corpus numbers written down beside them. The checker carries no Korean literals
and no magic constants.

## 5. What stays blank for a human

- every **서명** — `(서명 또는 인)`, `(인)`, and the 위임장's `본 인:` line;
- the **직인 impression** — a placement, not a fill target;
- **주민등록번호 / 생년월일 / 등록번호** the user did not supply;
- the **접수·처리** block, which the receiving office writes.

Hand the document back naming these explicitly. Typing a fabricated
주민등록번호 is the failure this module exists to catch.

## 6. Known boundaries

- **`auto` is conservative about `final`.** 정보공개 청구서 has a SECOND
  `년 월 일` seat inside its staff-only 접수증 block, which the applicant must
  leave alone — so that form reads `draft` even when correctly completed, and its
  finishing rules stay WARN. Pass `--mode final` when you know the document is
  finished.
- **행정규칙 서식 has no 유의사항 and no paper-spec footer**, and the rules report
  `seat_absent` / `none_in_baseline` rather than failing it. Absence is not
  failure — the distribution-module contract says so in the modules README
  that ships with the core bundle.
- **Guide-block presence is checked at document scope, not per block.** If a form
  carries 유의사항 twice and a fill deletes one copy, the label still appears and
  the rule passes. The eval harness's `geometry` check and `visual_verify`'s page
  budget cover page-level loss.
- **No 개인정보 수집·이용 동의 rule.** That exact construct appears in none of the
  four corpus forms — 주민등록 등초본 신청서 has a 행정정보 공동이용 동의서 and
  사업자등록 신청서 has a 국세정보 수신동의. Both are covered by the guide
  keep-list (`동의`) and their signature seats by `signature_marker_lost`. A
  dedicated rule would be a guess, not a derivation.
- **No 처리절차 flow-footer rule.** The HWP usage-landscape research note
  (repo `docs/research`, family ①) lists 처리절차 footer rows as a family trait,
  and **zero of the four corpus forms carries one.** The label is in the
  keep-list so a form that has one is protected; there is no rule that presumes
  one exists.
- Out of scope by design: geometry preservation (row heights, merge topology,
  page size) belongs to `form_inspect` plus the eval harness's `geometry` check,
  and the rendered appearance belongs to `visual_verify`.
