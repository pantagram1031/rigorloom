The hr distribution module is enabled: 계약·인사 서식 documents (고용노동부
표준근로계약서 pack and its kin) get a deterministic gate, `check_hr`.

**This family's document IS the legal instrument.** A 민원 서식 is a fixed grid
whose printed guide text must survive. A 기안문's 별지서식 guide vocabulary must
be *replaced* by content. A 표준근로계약서 is neither: it is numbered clause prose
that carries the 근로기준법 제17조 서면 명시 의무 in its own words. Fill the
seats; change nothing else — not a clause number, not a citation, not a word of
the sentence around the blank you are writing into.

**Task flow** — inspect, fill, check, verify:

```
python engine/scripts/form_inspect.py FORM.hwpx --out blank.profile.json
python engine/scripts/preedit.py replace FORM.hwpx --out filled.hwpx \
    --map fill.json                    # '2. 근 무 장 소 : ' → '… : 경기도 …'
python modules/hr/scripts/check_hr.py filled.hwpx \
    --baseline FORM.hwpx --fill-map fill.json --out hr_verdict.json
python pipeline/scripts/visual_verify.py … \
    --expectations modules/hr/references/visual_expectations/hr.json
```

Work on a COPY; the blank form is never edited in place. **Always pass
`--baseline`** — twelve of the twenty rules are preservation rules and they say
`skipped: no_baseline` without it.

**It is a PACK, not a form.** Both corpus revisions ship five or six contract
variants back to back — 기간의 정함이 없는/있는 경우, 연소근로자, 친권자(후견인)
동의서, 건설일용근로자, 단시간근로자 — each introduced by a one-cell banner.
Identify which variant the user means, fill only that one, and **leave the others
in the document**: deleting a sheet is `contract_variant_lost`, and dropping its
clauses is `clause_block_lost`.

**The clause skeleton comes from the blank form.** A missing clause is
`clause_lost` and a shifted number is `clause_renumbered`. Do not "tidy" the
numbering: the 2013 단시간 sheet legitimately runs 1,2,3,4,5,6,8,9 because its
clause 7 is written mid-paragraph, and renumbering it to 1..8 changes what every
later reference points at.

**The seats are runs of spaces, not underscores.** `2. 근 무 장 소 : ` ends in a
blank run; `4. 소정근로시간 :   시  분 ~   시  분` is a time skeleton; `있음 (  )`
and `[  ]` are option slots; `      년      월      일` is the date line. Write
*into* the run. The sentence on either side must survive verbatim
(`clause_text_consumed`), and marking an option turns `(  )` into `(○)` without
changing the slot count (`option_slot_lost`).

**An unfilled seat is reported, never invented.** `seat_unfilled` is a WARN, on
purpose, and it never becomes HARD. If the user gave you no 상여금, no 임금지급일
and no 수당, those seats stay empty and you say which ones when you hand the
document back. Inventing a value to make a warning disappear is the failure this
rule exists to prevent.

**Two parties, or none.** 사업주 needs 사업체명 · 주소 · 대표자; 근로자 needs
주소 · 연락처 · 성명. Filling one side and leaving the other empty is
`party_half_filled` (HARD once the document is dated). Both sides empty is
blank-by-design. Every `(서명)` / `(인)` marker stays for the human — the party's
name may share the line, the marker itself may not be replaced.

**The citations are the instrument.** 근로기준법 제17조, 제67조, 근로관계법령 —
every article the blank form cites must survive verbatim
(`statute_reference_lost`), and citing an article the form does NOT carry is
`statute_reference_invented`. A fabricated legal reference is worse than a
missing one.

**Never invent a personal number.** 주민등록번호 or 계좌번호 — if the user did not
supply the value, the seat stays empty and you say so. An RRN-shaped value nobody
declared is `identity_value_invented`; any hyphen-grouped or bare digit run of
ten or more digits nobody declared is `personal_number_invented`. Both fire with
or without a baseline. Declare what the user gave you with `--fill-map` so the
checker can tell a supplied value from a fabricated one. Note the pair's own
signal here: the 2013 revision asked for 주민등록번호 in both 인적사항 blocks and
the 2025 revision replaced every one of them with 생년월일.

**Two revisions, and they do not mix.** `check_hr` fingerprints the template from
its own vocabulary (기타급여(제수당 등) / 예금통장에 입금 → 2013; 그 밖의
수당(약정수당) / 사회보험 적용여부 / 계좌에 입금 → 2025). A document carrying
both is `template_version_mixed` — text was pasted across revisions and the
result matches no published 서식. A document whose version differs from its blank
form is `template_version_changed`. If a user gives you a 2013 contract, fill the
2013 contract; do not modernize its wording.

No pack type: a 근로계약서 is a two-party instrument, and a repository store of
one party's 사업체명 · 대표자 · 사업자등록번호 would be a standing supply of
exactly the half-filled contract `party_half_filled` exists to catch.

Details, per-rule findings, the 2013→2025 drift table, and the blank/draft/final
state machine: `references/hr_flow.md`.
