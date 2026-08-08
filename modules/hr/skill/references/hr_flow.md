# 계약·인사 서식 task flow and the check_hr contract

Reference for the `hr` distribution module's skill fragment. Everything here is
family-level: it comes from the 고용노동부 표준근로계약서 convention itself,
measured against the **versioned pair** in the blank-form corpus
(`tests/corpus/forms/manifest.json`, family `hr`):

| slug | what it contributes |
|---|---|
| `moel-pyojun-geunrogyeyakseo-2013` | 6 variant banners, 4 numbered-clause blocks (9/10/9/8 clauses), 11 signature markers, 3 주민등록번호 seats, articles 제17조·제63조·제67조, and the bilingual EPS 표준근로계약서 as a 20×6 table — the only sheet in the family that is a grid at all |
| `moel-pyojun-geunrogyeyakseo-2025` | 6 variant banners, 5 numbered-clause blocks (11/11/12/11/10 clauses), 11 signature markers, **zero** 주민등록번호 seats (all replaced by 생년월일), articles 제17조·제67조, plus a blank 근로일별 근로시간 grid and two worked-example grids |

The pair is why this family was chosen as work-type module #3. Two revisions of
one instrument make "which template is this, and did a fill quietly migrate it"
a decidable question — see §5.

## 1. The four steps

1. **Inspect.** `engine/scripts/form_inspect.py FORM.hwpx --out
   blank.profile.json`. Family ⑦ is the inverse of family ①: almost everything
   lives in **top-level paragraphs**, not table cells. The 2025 pack has 172
   paragraphs and 99 cells, and 6 of those cells are one-line variant banners.
2. **Identify the seats.** Seven regions, and the document tells you which it
   has:
   - **contract**: the one-cell variant banners. Not fill targets; not
     deletable.
   - **clause**: `N. 라벨 :` heads, letter-spaced (`2. 근 무 장 소 :`). The number
     and the label are the form's; what follows the colon is yours.
   - **seat**: a run of ≥2 spaces, a `시  분` skeleton, a `년 월 일` date line, a
     `(  )` or `[  ]` option slot. Write *into* it.
   - **legal**: the sentences carrying the citations. Verbatim, always.
   - **party**: `(사업주) 사업체명 · 주소 · 대표자` and
     `(근로자) 주소 · 연락처 · 성명`.
   - **signature**: `(서명)` / `(인)`. The human's.
   - **identity**: 주민등록번호 / 생년월일 / 사업자등록번호 / 계좌 — never
     fabricated.
3. **Fill.** `preedit.py replace FORM.hwpx --out filled.hwpx --map fill.json`.
   Keys are run texts, and this family's runs are generous — a whole clause line
   is usually one run, so `"2. 근 무 장 소 : "` → `"2. 근 무 장 소 : 경기도 …"`
   works directly. A key that is whitespace only is refused by `preedit`, so
   anchor the key on the label or on the text that follows the blank run.
   `fill-cells` is rarely needed here: the only fillable cells are the 2025
   근로일별 근로시간 grid.
4. **Check, then verify.**
   `modules/hr/scripts/check_hr.py filled.hwpx --baseline FORM.hwpx
   --fill-map fill.json`, then `pipeline/scripts/visual_verify.py` with
   `modules/hr/references/visual_expectations/hr.json`. The checker judges
   structure; visual_verify judges the render.
   `--fill-map` takes either shape, at the checker and at `visual_verify`
   alike — a bare `{key: value}` map or a wrapper object with a `fill_map`
   member — so ONE file serves both halves (T35). `visual_verify --baseline`
   takes the blank `FORM.hwpx` directly and converts it itself.

## 2. Document state decides severity

The document says which state it is in, so a blank pack is not "a failed
contract":

| state | evidence | consequence |
|---|---|---|
| `blank` | no option slot carries a selection mark, no party seat carries a value, the `년 월 일` seat still unfilled, (with a baseline) no paragraph changed | the unfilled shape is *reported*; `seat_unfilled` is `skipped: document_state_blank` |
| `draft` | something written, date seat still unfilled | preservation rules HARD; `party_half_filled` WARN |
| `final` | no unfilled date seat remains | everything HARD |

`--mode blank|draft|final` forces a state. `--mode auto` (default) reads it.

Two calibration notes, both measured on the pair:

- **State uses a narrow mark class.** The broad option-slot class matches
  printed parentheticals — 32 of them on the pristine 2013 pack, 66 on the 2025
  pack (`(서명)`, `(인)`, `(앞쪽)`, `(만  세)`). Classifying state by it reported
  every blank form as a draft, so state reads `mark_glyph_re` (`(○)`, `[√]`, …)
  while `option_slot_lost` keeps the broad count.
- **The party-seat term is what makes the no-baseline path honest.** This family
  has no checkbox culture, so without it a completed contract with no baseline
  had no evidence of writing and read as blank-by-design.

## 3. Rules

Twenty rules in eight groups. **Twelve need `--baseline`** (the module declares
`wants: [baseline]`); the three that do not are the ones that must never be
gated behind an input a caller can forget.

| rule | severity | needs baseline | what it catches |
|---|---|---|---|
| `artifact_missing` | HARD | – | a pinned path that does not exist (never a silent pass) |
| `artifact_malformed` | HARD | – | a render-critical member that is not well-formed XML; structure checks stop |
| `hr_structure_absent` | HARD | – | fewer than `family_minimum` (4) of the seven seat families — this is not a 근로계약서 |
| `clause_block_lost` | HARD | yes | a numbered-clause block is gone: one contract of the pack was deleted |
| `clause_lost` | HARD | yes | a numbered clause the blank form carries is gone |
| `clause_renumbered` | HARD | yes | a block's number sequence changed |
| `contract_variant_lost` | HARD | yes | a variant banner is gone |
| `clause_text_consumed` | HARD | yes | text the form prints between its seats no longer appears — a fill wrote *over* the clause instead of into the seat |
| `option_slot_lost` | HARD | yes | the total `(  )` / `[  ]` count dropped: an option was deleted rather than marked |
| `seat_unfilled` | **WARN, never HARD** | – | seats still empty. A report, on purpose (§4) |
| `party_block_lost` | HARD | yes | a 사업주 / 근로자 block is gone |
| `signature_marker_lost` | HARD | yes | a `(서명)` / `(인)` marker is gone |
| `party_half_filled` | HARD in `final`, WARN in `draft` | no | one party identified, the other empty |
| `statute_reference_lost` | HARD | yes | a law term was thinned, or an article citation disappeared |
| `statute_reference_invented` | HARD | yes | the artifact cites an article the blank form does not |
| `template_version_mixed` | HARD | no | vocabulary from two revisions in one document |
| `template_version_changed` | HARD | yes | the artifact's revision differs from the blank form's |
| `identity_value_invented` | HARD | no | a 주민등록번호-shaped value nobody declared |
| `personal_number_invented` | HARD | no | any hyphen-grouped or bare digit run of ≥10 digits nobody declared — the 계좌번호 shape |
| `identity_seat_autofilled` | HARD | yes | an identity seat the blank form left empty now carries an undeclared value |

Everything undecidable from the inputs given is listed under `skipped` with a
reason (`no_baseline`, `seat_absent`, `document_state_blank`,
`seat_count_drift`, `baseline_version_undetermined`) — never silently passed.

## 4. Why an unfilled seat is not a failure

This is the family's own asymmetry and the module's one deliberate softness.
A 표준근로계약서 has seats nobody may fill on the user's behalf: 상여금,
그 밖의 수당, 임금지급일, 초과근로 가산임금률, and every identity seat. Turning
"you did not fill 임금지급일" into a HARD finding puts pressure on the filler to
make the finding go away, and the only way to do that is to invent a value. So
`seat_unfilled` is a WARN that reports the count and never escalates, and the
correct handoff is a sentence naming which seats are still open.

`party_half_filled` is the boundary case that *does* escalate, because a dated
contract with one identified party is not an incomplete contract — it is a
document that claims to be executed and is not.

## 5. What changed between 2013 and 2025

Measured programmatically over the two baselines (`tests/test_hr_corpus.py`
re-derives every number below, so this table cannot rot silently):

| axis | 2013 | 2025 | consequence for the rules |
|---|---|---|---|
| variant banners | 6 | 6 | same count, different set: 2025 splits 표준근로계약서 into 기간의 정함이 **없는**/**있는** 경우 and **drops the bilingual EPS sheet** |
| numbered-clause blocks | 4 | 5 | `clause_block_lost` compares block *counts*, so it works on both |
| clauses in the base contract | 9 | 11 | 2025 inserts 사회보험 적용여부 and 근로계약, 취업규칙 등의 성실한 이행의무 |
| clause numbering | 단시간 sheet runs 1,2,3,4,5,6,**8**,9 (clause 7 is mid-paragraph) | contiguous in every block | why `clause_renumbered` reads the inventory from the baseline instead of asserting 1..N |
| 주민등록번호 seats | 3 | **0** | 2025 replaced every one with 생년월일. The clearest privacy signal in the pair, and the reason the identity vocabulary carries both labels |
| 생년월일 seats | 1 (EPS *Birthdate*) | 2 (친권자 + 연소근로자) | — |
| account wording | 예금통장에 입금 (5) | 계좌에 입금 (5) | a version marker each way |
| allowance wording | 기타급여(제수당 등) | 그 밖의 수당(약정수당) | a version marker each way |
| fallback clause | 근로기준법령에 의함 | 근로관계법령에 따름 | a version marker each way |
| article citations | 제17조, 제63조, 제67조 | 제17조, 제67조 | 제63조 left with the EPS sheet |
| paper-spec footer | 1 (EPS page only) | **0** | **rule dropped** — a `210mm×297mm` preservation rule cannot be stated for this family, unlike 민원 |
| underscore runs | 1 (`____________  (YY/MM/DD)`, EPS) | **0** | **premise dropped** — the family's blanks are runs of *spaces*, not `______` |
| option slots | 118 total | 102 total | both non-zero, so `option_slot_lost` holds for both |
| `해당사항에 ○표` instruction | present (2) | absent | why the mark-glyph class includes ○ |
| 공휴일(대체공휴일 포함) | absent | 9 occurrences | a version marker |
| 근로일별 근로시간 grid | absent | 1 blank grid + 2 worked examples | 2025-only; no rule depends on it |

**Rules stated for one version only.** None. Every rule above was verified
against both baselines and any candidate that held for only one was dropped
rather than shipped half-applicable — the paper-spec footer and the underscore
blank run are the two that were dropped for exactly that reason, and the 별지서식
header line, the 접수·처리 block, the 직인 impression box, the 귀하 addressee line
and the shading declaration are all absent from **both** forms (a 근로계약서 is a
private two-party instrument with no receiving office), so no rule was written
for them either.

**`checkbox_selection_absent` was also dropped**, and that one is worth naming
because 민원 has it. That rule is anchored on a form declaring its own
`[ ]에 √표를 합니다` instruction; neither 표준근로계약서 revision declares
anything of the kind, and most of its slots are genuinely optional
(있음/없음 for 상여금 may legitimately end up 없음). An unanchored "you must
select something" rule would be a guess, so unmarked slots are counted under
`seat_unfilled` and reported.

## 6. Never invent a personal number

The module's headline claim, and the reason two of the three baseline-free rules
are privacy rules.

- `identity_value_invented` — a 주민등록번호-shaped value (`\d{6}-\d{7}`) that the
  operator did not declare in `--fill-map`.
- `personal_number_invented` — the 계좌번호 half. There is **no 계좌번호 seat
  anywhere in either revision**; the 지급방법 clause only names an account. So the
  rule can only be a value-shape rule: a hyphen-grouped or bare digit run
  carrying at least `personal_number_min_digits` (10) digits that nobody
  declared. `2,800,000원` is comma-grouped and stays out; `2026-09-01` (8 digits)
  stays below the floor; `110-234-567890` and `010-0000-0000` trip it. A phone
  number the user supplied is declared and passes — a phone number the tool made
  up is exactly what this catches.
- `identity_seat_autofilled` — a value in an identity seat the blank form left
  empty. Keyed by label in document order; if the seat count moved between the
  two documents the rule reports `seat_count_drift` rather than comparing the
  wrong two things.

`--fill-map` is how you declare what the user gave you. Without it, every
personal number in the artifact is undeclared by definition.

## 7. What this module deliberately does not do

- **No pack type.** A repository store of one employer's 사업체명 · 대표자 ·
  사업자등록번호 would be a standing supply of exactly the half-filled contract
  `party_half_filled` exists to catch, and it would sit next to the two shapes
  §6 refuses to synthesize.
- **No sibling-module import.** `identity_value_invented` is minwon's precedent
  and this module reimplements the pattern over its own vocabulary. Module →
  module imports are outside the contract.
- **No judgment about contract terms.** The checker never asks whether a wage
  meets 최저임금 or whether 소정근로시간 exceeds a statutory cap. It checks that
  the document still says what the 서식 says; what the terms *mean* is a lawyer's
  question, not a deterministic gate's.
