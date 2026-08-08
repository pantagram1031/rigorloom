The grant distribution module is enabled: 지원사업/공모 신청 documents (K-Startup
및 지자체 공고 신청서+사업계획서, 조달청 서식) get a deterministic gate,
`check_grant`.

**This family's submission is a PACKET, not a document.** One file carries a
신청서 grid, a flowing 사업계획서, 붙임/별첨 parts cited by number, per-programme
budget tables and standalone 동의서 sheets. Two things follow, and they are the
whole module:

1. **Adding rows is allowed.** The applicant extends the budget tables and the
   rosters — the form says so itself (`견적서 1개 초과시 표 추가`). So the
   geometry rule compares the **column count and the header row**, never a cell
   count. Add rows freely; never add or drop a column (`table_column_changed`),
   and never delete a table (`table_structure_lost`).
2. **The parts reference each other.** `【별첨 2-1】` is a section of the file;
   `붙임 5` is an attachment of the 공고문. A citation of a part the file is
   supposed to contain but does not is `packet_reference_dangling`.

**Task flow** — inspect, fill, check, verify:

```
python engine/scripts/form_inspect.py FORM.hwpx --out blank.profile.json
python engine/scripts/preedit.py replace FORM.hwpx --out filled.hwpx \
    --map fill.json
python modules/grant/scripts/check_grant.py filled.hwpx \
    --baseline FORM.hwpx --fill-map fill.json --out grant_verdict.json
python pipeline/scripts/visual_verify.py … \
    --expectations modules/grant/references/visual_expectations/grant.json
```

Work on a COPY; the blank form is never edited in place. **Always pass
`--baseline`** — six of the seventeen rules are preservation rules and they say
`skipped: no_baseline` without it, and the baseline is also what makes the
document's state knowable (below).

**The form may ship pre-filled with examples, so "is this blank?" needs the blank
form.** The K-Startup packet arrives with nine budget figures and a marked
`■동의함` already in it. A marked box and a number in a cell prove nothing. With
`--baseline` the state comes from what actually changed; without it, from the date
seat alone. The verdict records which under `document.state_basis`, so never read
`blank` as "pristine" unless the basis is `baseline_diff`.

**The 합계 must add up.** `budget_total_mismatch` compares each 합계 cell against
the sum of its own column, and needs no baseline. The corpus form computes those
totals with Hancom `=SUM()` fields — meaning if you edit a budget row through XML
and do not recompute, the printed total is stale and *wrong on the page*. Update
the 합계 whenever you touch a line item. The form's own money caps
(`지원신청액의 합계액 … 30,000천원을 초과 不`) are **reported, not enforced**: two
of them name the same column with different scopes, so the checker hands you the
numbers and you honour them.

**Consent is the applicant's decision.** `consent_unmarked` fires when a consent
choice carries no mark — HARD once the packet is dated and the form calls the
consent 필수. It is a report *to the user*, not a licence to tick the box: read
the consent aloud (what is collected, why, for how long, who else receives it) and
let the person decide. Deleting the refuse option is `consent_option_lost`;
dropping a whole 동의서 is `consent_block_lost`.

**□ is usually a bullet, not a checkbox.** 28 of the K-Startup packet's 32 box
glyphs are section bullets (`□ 수집·이용 목적`, `□ 청렴서약`) or non-consent
option lists (`□ 특허 / □ 노하우`), and both of 조달청 정보공개동의서's are
headings. A real consent choice is a parenthesized group offering two or more
options. Some are unreadable by design — `(예,  아니오)` has nothing to mark — and
the checker says `skipped: no_mark_glyphs` rather than guessing.

**Remove what the form told you to remove.** This family is the inverse of 민원
here: the guidance is *meant* to go. `※ 해당 안내를 포함한, 아래 파란색 안내
문구는 참고하여 작성 후 삭제` includes itself, so its survival in a finished
packet is `self_deleting_guide_retained`; the `~~~~` and `ㅇㅇㅇ` stand-ins are
`example_placeholder_retained`. A part marked `※ 해당자에 한함 (없을 시 삭제)` may
be deleted — that one is a WARN, because dropping it is following the form.

**Every sheet's signature seat stays for a human.** A packet signs once per sheet
(six seats in the K-Startup form alone). Writing a name beside `(인)` is fine;
removing the marker is `signature_seat_lost`.

**Never invent a personal number.** This family asks for more of them than any
other — 주민등록번호, 여권번호, 생년월일, 법인등록번호, 사업자등록번호 — and
supplies a value for none. An RRN-shaped value nobody declared is
`identity_value_invented`; any hyphen-grouped or bare digit run of ten or more
digits nobody declared is `account_number_invented`. Both fire with or without a
baseline. Declare what the user gave you with `--fill-map` so the checker can tell
a supplied value from a fabricated one. Budget figures are safe: `16,000,000` is
comma-grouped and stays out.

**Page budgets need a render, and the checker says so.** If the form declares
`N쪽 이내`, `length_budget_unverified` reports `skipped: needs_render` and names
`visual_verify` as the owner — it never guesses a page count. None of the corpus
forms declares one, in which case the reason is `not_declared`.

No pack type: the seats a 지원사업 pack would cache (기업명, 대표자명,
사업자등록번호, 법인등록번호) sit directly beside the shapes the privacy rule
refuses to synthesize.

Details, per-rule findings, the three-form evidence table, and the blank/draft/
final state machine: `references/grant_flow.md`.
