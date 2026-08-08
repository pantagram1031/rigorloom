The minwon distribution module is enabled: 민원·신고 서식 documents
(법령·행정규칙 별지서식 신청서 / 청구서 / 신고서) get a deterministic gate,
`check_minwon`.

**A 민원 서식 is not a 공문, and its rules are the inverse.** A 기안문's 비고
block says its guide vocabulary must be *replaced by content*. A 민원 서식 says
the opposite: its printed text — 유의사항, 수수료 안내, 제출서류, 처리기간,
동의서 — is part of the document the applicant submits. **Fill the seats; keep
everything else.** Deleting a 유의사항 page is `guide_block_lost`, not tidying.

**Task flow** — inspect, identify seats, fill, check, verify:

```
python engine/scripts/form_inspect.py FORM.hwpx --out blank.profile.json
python engine/scripts/preedit.py fill-cells FORM.hwpx --out filled.hwpx \
    --table 0 --cell 4,3="김도현"      # empty form cells have NO hp:t
python engine/scripts/preedit.py replace filled.hwpx --out filled.hwpx \
    --map fill.json                    # '[ ]사본' → '[√]사본', '(접수 기관의 장) 귀하' → '세무서장 귀하'
python modules/minwon/scripts/check_minwon.py filled.hwpx \
    --baseline FORM.hwpx --fill-map fill.json --out minwon_verdict.json
python pipeline/scripts/visual_verify.py … \
    --expectations modules/minwon/references/visual_expectations/minwon.json
```

Work on a COPY; the blank 서식 is never edited in place. **Always pass
`--baseline`** — ten of the thirteen structural rules are preservation rules and
they say `skipped: no_baseline` without it.

**Never invent an identity number.** 주민등록번호, 생년월일,
여권ㆍ외국인등록번호, 사업자등록번호 — if the user did not supply the value, the
seat stays empty and you say so when handing the document back. A
주민등록번호-shaped value nobody declared is `identity_value_invented` (HARD,
and it fires with or without a baseline); a value written into an identity seat
the blank form left empty is `identity_seat_autofilled`. Declare what the user
gave you with `--fill-map` so the checker can tell a supplied value from a
fabricated one.

**The dark cells are not yours.** 접수번호 / 접수일 / 처리기간 / 접수부서 /
접수자 and the 접수증 block belong to the receiving office. Many forms say so in
their own words — `※ 색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다` —
and where a form says it, shading itself marks the boundary. Writing there is
`staff_seat_filled`. Watch the trap: a shaded cell that *carries checkboxes* is
an instruction block the applicant does mark, not a staff seat.

**Selection is a text toggle, not a form field.** `[ ]` → `[√]`. Keep the slot
count: turning `[ ]열람 [ ]사본` into `열람 [√]사본` deletes an option the
regulation grants (`checkbox_option_lost`). A finished document with not one box
marked is `checkbox_selection_absent` — HARD where the form carries its own
`[ ]에 √표를 합니다` line.

**What stays blank for a human**: every `(서명 또는 인)` / `(인)` marker and the
직인 impression box. The applicant's name may share the cell with the marker;
the marker itself must survive.

**The frame survives**: the `■ …시행규칙 [별지 제N호서식] <개정 …>` header line,
the `210mm×297mm[백상지…]` footer on every page, and the `귀하` addressee line.
Replacing a parenthesized addressee guide term (`(접수 기관의 장) 귀하` →
`국가유산청장 귀하`) is correct; losing the line is not.

No pack type: a 민원 서식's 접수 기관 is printed by the regulation, and
everything the applicant supplies is per-document personal data that belongs in
a fill map, never in a repository pack.

Details, per-rule findings, and the blank/draft/final state machine:
`references/minwon_flow.md`.
