# 지원사업 신청 task flow and the check_grant contract

Reference for the `grant` distribution module's skill fragment. Everything here is
family-level: it comes from the 지원사업/공모 신청 convention itself, measured
against the three blank forms in the corpus (`tests/corpus/forms/manifest.json`,
family `grant`):

| slug | what it contributes |
|---|---|
| `kstartup-jiwon-sincheongseo-saeopgyehoekseo` | the hybrid, and by far the largest corpus document: 42 tables / 366 cells, 13 record-shaped grids, 3 `【별첨 N】` sections plus 2 external `붙임` citations, 3 budget tables with 9 `합계` cells (Hancom `=SUM()` fields), 2 pre-marked required consents, 6 signature seats, 3 declared money caps |
| `pps-hyeopeop-seungin-sinchengseo` | native .hwpx. One 9×19 grid holding a 참여기업 roster, one signature seat, and a 첨부서류 block that cites a **separately published** 별지서식 (`[별지 제2호의 8서식] … 1부`) |
| `pps-jeongbogonggae-donguiseo` | native .hwpx. The consent form: two glyph-less `(예, 아니오)` choices and two `□` **section bullets** |

Three forms, three different shapes of the same family, and the module was built
by taking only what all three (or a named one) actually declare.

## 1. Why this family is different

The other three work-type modules each guard **one** document with a fixed shape,
so any structural change is damage. A 지원사업 submission is an application
**packet**: one file, many parts, and the applicant is *supposed* to change its
shape.

| property | 민원 (①) / 공문 (②) / 계약 (⑦) | 지원사업 (⑥) |
|---|---|---|
| row count | fixed — a changed cell count is damage | **a degree of freedom**; the form says `견적서 1개 초과시 표 추가` |
| printed guide text | must survive (민원) / must be consumed (공문) | **must be deleted**, and the form's own sentence says so |
| cross-references | none | `붙임`/`별첨` parts cited by number |
| numeric invariant | none | `합계` = the sum of its column |
| consent | a checkbox among others | **a document with legal effect** (the 동의서 IS one form) |

## 2. The four steps

1. **Inspect.** `engine/scripts/form_inspect.py FORM.hwpx --out
   blank.profile.json`. This family mixes both storage regimes in one file: the
   K-Startup packet keeps its 【별첨】 headers, 작성방법 block and 동의 questions
   in **top-level paragraphs** (165 of them) while 42 tables sit between them.
2. **Identify the seats.** Six regions, and the document tells you which it has:
   - **packet**: `【별첨 N】` section headers, `붙임 N` citations, the 첨부서류
     block. Not fill targets.
   - **grid**: record-shaped tables (3+ columns). Rows are yours to add;
     columns are not.
   - **budget**: the `합계` rows. Recompute them when you touch a line item.
   - **consent**: parenthesized option groups inside a 동의 block.
   - **signature**: `(인)` / `(서명 또는 인)`, once per sheet. The human's.
   - **identity**: 주민등록번호 / 여권번호 / 생년월일 / 법인등록번호 /
     사업자등록번호 / 계좌번호 — never fabricated.
3. **Fill.** `preedit.py replace FORM.hwpx --out filled.hwpx --map fill.json`
   for the prose and the paragraph seats; `fill-cells` for the grids. The front
   grid and the flowing body are two different editing regimes and mixing them
   is what A3 measures.
4. **Check, then verify.**
   `modules/grant/scripts/check_grant.py filled.hwpx --baseline FORM.hwpx
   --fill-map fill.json`, then `pipeline/scripts/visual_verify.py` with
   `modules/grant/references/visual_expectations/grant.json`. The checker judges
   structure; visual_verify judges the render — and it is visual_verify, not the
   checker, that owns a page count (§5).

## 3. Document state, and what it cannot know

| state | evidence | consequence |
|---|---|---|
| `blank` | nothing written | residue and consent rules are `skipped: document_state_blank` |
| `draft` | something written, the date seat still unfilled | preservation rules HARD, finishing rules WARN |
| `final` | no unfilled date seat remains | everything HARD |

`--mode blank|draft|final` forces a state; `--mode auto` (default) reads it.

**The honest part**: "was anything written?" is genuinely undecidable here without
the blank form. The K-Startup packet ships **pre-filled with worked examples** —
nine budget figures, `■동의함` already marked, example prose — so neither a marked
box nor a number in a cell is evidence of anything. The verdict therefore records
`document.state_basis`:

- `baseline_diff` — a blank form was supplied; `written` is what actually
  changed (set-based, never positional, because this family adds rows and
  paragraphs on purpose).
- `date_seat_only` — no blank form; state falls back to the date seat. `blank`
  here means *no evidence available*, not *pristine*. Do not read it as a pass.

## 4. Rules

Seventeen rules in nine groups. **Six need `--baseline`** (the module declares
`wants: [baseline]`); the rest are the ones that must never be gated behind an
input a caller can forget.

| rule | severity | needs baseline | what it catches |
|---|---|---|---|
| `artifact_missing` | HARD | – | a pinned path that does not exist (never a silent pass) |
| `artifact_malformed` | HARD | – | a render-critical member that is not well-formed XML; structure checks stop |
| `grant_structure_absent` | HARD | – | fewer than `family_minimum` (3) of the six seat families — this is not a 신청 packet |
| `packet_reference_dangling` | HARD | no | the packet cites `별첨 N` and carries no section for it |
| `packet_section_lost` | HARD, **WARN if optional** | yes | a `【붙임/별첨 N】` section the blank form carries is gone |
| `table_structure_lost` | HARD | yes | a record-shaped table has no counterpart: deleted or rewritten rather than filled |
| `table_column_changed` | HARD | yes | a table's **column** count moved. Rows may move; columns may not |
| `budget_total_mismatch` | HARD | no | a `합계` cell ≠ the sum of its column |
| `consent_unmarked` | HARD in `final` **when the form says 필수**, else WARN | no | a consent choice with no option marked |
| `consent_block_lost` | HARD | yes | a consent block the blank form carries is gone |
| `consent_option_lost` | HARD | yes | fewer consent options than the form offered — deleting the refuse option manufactures consent |
| `signature_seat_lost` | HARD | yes | an `(인)` / `(서명 또는 인)` seat is gone |
| `identity_value_invented` | HARD | no | a 주민등록번호-shaped value nobody declared |
| `account_number_invented` | HARD | no | any hyphen-grouped or bare digit run of ≥10 digits nobody declared |
| `self_deleting_guide_retained` | HARD in `final`, WARN in `draft` | no | the form's own "delete this guidance" sentence survived into the packet |
| `example_placeholder_retained` | HARD in `final`, WARN in `draft` | no | `~~~~` / `ㅇㅇㅇ` worked-example stand-ins survived |
| `length_budget_unverified` | **always `skipped`** | – | a declared dependency, not a check (§5) |

Everything undecidable from the inputs given is listed under `skipped` with a
reason (`no_baseline`, `seat_absent`, `document_state_blank`,
`no_internal_marker_class`, `no_addends`, `no_mark_glyphs`, `not_declared`,
`needs_render`, `needs_section_scoping`) — never silently passed.

### 4.1 The extendable-table geometry rule

The module's sharpest difference, and the rule most easily got wrong.

A table is in scope when it has **3 or more columns** and a header row (the first
row carrying at least 2 non-empty cells). Three columns is not a style
preference: an extendable table is one whose **row is a record**, and every
genuinely extendable table in the corpus has three or more (the 예산표 7, the two
사업비 편성표 7 each, 추진일정 14, 성과목표 5, 전문가 프로필 12, 기술이전 의향서
5, pps-hyeopeop's 참여기업 roster 9, 동의서's two 개인정보 tables 3 and 4).
Two-column tables are label/value pair lists, and the measured cost of admitting
them was a **false positive**: the K-Startup 사업계획서 sections are 2×N
`label | content` grids whose content column is the prose fill target the form
tells you to delete, so every row of them is a header-row candidate and a correct
fill read as `table_structure_lost`.

Pairing is by **header-label containment**, never by table index — this family
lets the applicant add whole tables, and one added table shifts every index after
it. A baseline grid pairs with the artifact grid sharing at least
`header_match_min_ratio` (0.6) of its header labels, ties broken by the closer
column count so two tables with identical headers (the 개인정보 consent row ships
twice) pair one-to-one. Signatures are mark-insensitive: marking
`□ 1. 기술이전 완료` into `■ 1. 기술이전 완료` must not look like a different
table.

Then, and only then: **column count must match, row count may differ**. A row
count that moved is reported as `rows_added` on a `grid` seat, positive or
negative. Proven on the real document in
`tests/test_grant_corpus.py::TestRulesBiteOnTheRealPacket` — one roster row added
to the 42-table packet passes with `rows_added: 1`, one column dropped is HARD.

### 4.2 Packet integrity, and how internal is told from external

`붙임`, `별첨` and `첨부` are the part markers. `별지` is deliberately **not** one:
pps-hyeopeop's own identity line is `[별지 제2호의 7서식 (제5조 제2항)]` while its
첨부서류 block cites `[별지 제2호의 8서식] … 1부` — a 별지 number names a
separately published 서식 (a different file), so admitting it would fail that
pristine form.

Which marker class is *internal* is read off the document rather than declared: a
class the document carries at least one `【… N】` header for is internal, and every
reference of that class must resolve. A class with references and no header is
**external** — it cites a separate file, and the packet cannot be asked to contain
it. On the K-Startup packet that makes 별첨 internal (headers 1, 2-1, 2-2) and
붙임 external (`붙임 3`, `붙임 5` live in the 공고문). Hardcoding either way would
have failed a pristine form.

A header is a bracketed marker-and-number at the **very start** of a seat, which
is what keeps `[별첨 2-1] 개인정보 제공 및 활용(제3자 제공)동의서 1부` — a mid-cell
citation of the same section — a reference rather than a second header.

`packet_section_lost` downgrades to WARN when the form itself licenses the
deletion (`※ 해당자에 한함 (없을 시 삭제)`, which the K-Startup packet writes on
two of its attachment placeholders). Deleting a part the form says you may delete
is following the form.

### 4.3 Budget arithmetic — the one genuinely numeric invariant

Each `합계` cell is compared against the sum of the numeric cells above it **in
its own column address**. No row is enumerated and no row count is assumed, which
is what lets the rule survive an extension. A cell joins the sum only when it *is*
a number (`11,000`, `16,000,000`, `0`) — `5,000천원`, `= 20%` and
`10,000,000 × 1건` are prose about money and stay out. A column with fewer than
`budget_min_addends` (1) numeric cells above the total reports
`skipped: no_addends` instead of asserting that an empty column sums to the
printed figure; three of the K-Startup 자부담금 columns are exactly that (all
addends are `-`).

On the pristine form all 9 totals are present and all 8 decidable ones balance.
They are Hancom `=SUM()` fields, which is the practical point of the rule: edit a
budget row through XML without recomputing and the printed total is stale — wrong
on the page a reviewer reads.

`소계` is **not** a total label. A whole-column sum would double-count a nested
subtotal; no corpus form has one, asserted in `test_grant_corpus.py`.

### 4.4 Consent

A consent CHOICE is a parenthesized option group inside a unit that carries a 동의
label, offering at least 2 options. Two counters, and the glyph one wins when it
applies:

- **glyphs** — `( ■동의함    □동의하지 않음 )` has no separator at all and is
  counted by its two box glyphs.
- **tokens** — `(예,  아니오)` has no glyph and is counted by *exact token match*
  after splitting on `,`/`·`/`/`. Exact rather than substring is load-bearing:
  `예` is a substring of 예비창업자, 예시 and 예정, and
  `(예비)창업자 부담금율(%)` is not a consent choice.

**A box glyph on its own means nothing in this family.** 28 of the K-Startup
packet's 32 are section bullets (`□ 수집·이용 목적`, `□ 청렴서약`) or non-consent
option lists (`□ 특허 / □ 노하우 / □ 특허 및 노하우`), and both of 정보공개동의서's
two are headings (`□ 개인정보 수집ㆍ이용 내역`) — which A2's judgment criteria call
out by name. A rule keyed on glyphs alone would demand that a heading be ticked.

`required` is read from the *containing unit*, because the form writes 필수항목 in
one cell of a row and the option group in the next. A glyph-less choice is
`skipped: no_mark_glyphs`: `(예, 아니오)` has nothing to mark, and inventing a
verdict for it would be worse than saying so.

## 5. The page-budget dependency, declared instead of guessed

The repo's HWP usage-landscape write-up (family ⑥) predicts per-section page budgets
for this family — *"fixed front grid + flowing body in one file, `N쪽 이내`
enforcement"*. The corpus does not carry one. The 표준사업계획서 proper was
unreachable when the corpus was assembled (`attachSn=211973` → 404) and a
same-domain 공고 attachment was substituted; `page_budget_re` and `char_budget_re`
match **zero** times across all three forms, asserted in
`test_grant_corpus.py::TestDroppedPremises`.

The detector ships anyway, and the rule it feeds is permanently a SKIP that says
which case it is:

| reason | meaning |
|---|---|
| `not_declared` | the form states no page or character budget. All three corpus forms. |
| `needs_render` | the form states `N쪽 이내`, and a page count is **not derivable from `Contents/section*.xml`**. The verdict names `pipeline/scripts/visual_verify.py --expectations (page_budget)` as the owner. |
| `needs_section_scoping` | the form states `N자 이내`. Character counting is offline-decidable, but *which section the budget binds to* is not stated anywhere in the document, and a whole-document count would answer a different question. |

This is why `references/visual_expectations/grant.json` carries no `page_budget`
key: there is no number in the corpus to put there. If a 공고 form does declare
one, that file is where it goes.

## 6. What was dropped, and the corpus fact that killed it

Four candidate rules did not survive contact with the three forms. Each one is
recorded as an assertion in `test_grant_corpus.py` so the reason cannot rot into
prose nobody re-checks.

| candidate | corpus fact that killed it |
|---|---|
| **"every 붙임/별첨 reference must resolve to a section of this document"** | The K-Startup packet cites `붙임 3` and `붙임 5`, which are attachments of the **공고문**, not sections of the file. Stated that way the rule fires 4 times on the pristine form. Replaced by the internal/external split of §4.2, which the document decides for itself. |
| **per-section page budgets (`N쪽 이내`)** | Zero matches across all three forms (§5). The landscape predicted them; the substituted corpus document does not declare them. Kept as a declared dependency rather than a rule, because a page count needs a render either way. |
| **budget caps enforced against the budget table** | The form *does* declare three (`지원신청액의 합계액 … (최대) 30,000천원을 초과 不`, `전문가 활용비 … 총 1백만원 이내`, `기술료 이전비 … 총 2천만원 이내`) and the pristine form satisfies all three. But two of them name the same column noun (지원신청액) with different scopes — one the whole 합계 row, one a single programme line — and nothing in the document says which. Binding a cap to a figure would be a guess, and the guess fails on the pristine form: the 소요예산 총액 (35,000천원) legitimately exceeds the 지원신청액 cap (30,000천원). So caps are **extracted and reported** on a `budget_cap` seat and never gated. |
| **`identity_seat_autofilled`** (minwon's and hr's third privacy rule) | It needs a stable cell address to pair a seat between two documents — and in an extendable-table family a cell address is *not* stable across a legitimate fill, because adding a row shifts every address below it. minwon can pair by `(table, addr)` because a 별지서식's grid is frozen; this family's is not. Rather than ship a rule that reports `seat_count_drift` whenever the applicant does the thing the form invites, the privacy invariant is carried by the two **value-shape** rules, which need no addressing at all. |

Two further rules were considered and are absent because the family has no seat
for them: a **paper-spec footer** preservation rule (`210mm×297mm`, which 민원's
별지서식 prescribes — none of these three carries one) and a **shading
declaration** rule (`색상이 어두운 칸은 …`, 민원's staff-seat mechanism — this
family has no receiving-office block; the 접수 side of a 공고 lives in an online
system).

## 7. The family boundary, stated honestly

`grant_structure_absent` refuses documents that are not 신청 packets at all: both
기안문 별지서식 (1 family each), the NRF 결과보고서 (2), and both 표준근로계약서
revisions (2) are below the floor of 3.

It does **not** separate family ⑥ from family ①, and that is deliberate rather
than a calibration failure. The four 민원 별지서식 in the corpus also score 3–4
(signature + addressee + grid, and 사업자등록 신청서 additionally carries a
제출서류 list). pps-hyeopeop is the proof that no threshold could: it *is* a
신청서 with a 첨부서류 block and one grid, structurally indistinguishable from a
민원 신청서, so a floor that refused 민원 forms would refuse a corpus member of
this family. The caller chooses the checker. What a 민원 서식 handed to
`check_grant` gets is a verdict whose family-specific rules all skip with a reason
— never a false HARD. Both directions are asserted in
`test_grant_corpus.py::TestFamilyBoundary`.

## 8. What this module deliberately does not do

- **No pack type.** The seats a 지원사업 pack would cache — 기업명, 대표자명,
  주소, 사업자등록번호, 법인등록번호 — sit directly beside the shapes §4's privacy
  rules refuse to synthesize, and this family asks for more identity numbers than
  any other while supplying a value for none.
- **No sibling-module import.** `identity_value_invented` is minwon's precedent
  and this module reimplements the pattern over its own vocabulary. Module →
  module imports are outside the contract.
- **No judgment about the application.** The checker never asks whether a budget
  is reasonable, whether the 사업계획서 is persuasive, or whether the applicant
  qualifies. It checks that the packet still is what the 서식 says a packet is,
  and that its arithmetic adds up. Whether the application is any good is the
  reviewer's question, not a deterministic gate's.
- **No consent on the user's behalf.** `consent_unmarked` reports an unmarked
  consent; it is not a licence to mark one. Read the consent out to the person and
  let them decide.
