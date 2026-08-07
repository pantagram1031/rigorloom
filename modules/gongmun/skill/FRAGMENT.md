The gongmun distribution module is enabled: 공문/기안문 documents
(행정업무의 운영 및 혁신에 관한 규정 시행규칙 별지 제1호·제2호서식) get a
deterministic structure gate, `check_gongmun`.

**A 공문 is not a report.** It is 두문 / 본문 / 결문 with a 결재란, a 발신명의
line and a 관인·직인 slot, and the 서식 is prescribed by regulation. Fill it;
never rebuild it.

**Task flow** — inspect, identify seats, fill, check, verify:

```
python engine/scripts/form_inspect.py FORM.hwpx --out blank.profile.json
python engine/scripts/preedit.py fill-cells FORM.hwpx --out filled.hwpx \
    --table 0 --cell 1,0="…"            # empty form cells have NO hp:t: use fill-cells
python engine/scripts/preedit.py replace filled.hwpx --out filled.hwpx \
    --map guide_terms.json               # replace a surviving guide term by its content
python modules/gongmun/scripts/check_gongmun.py filled.hwpx \
    --baseline FORM.hwpx --out gongmun_verdict.json
python pipeline/scripts/visual_verify.py … \
    --expectations modules/gongmun/references/visual_expectations/gongmun.json
```

Work on a COPY; the blank 서식 is never edited in place.

**The rule that catches most drafts.** The 별지서식's own 비고 block states it:
`"행정기관명", "발신명", "기안자", "검토자", "결재권자", "직위(직급) 서명",
"처리과명-연도별 일련번호(시행일)", "도로명주소", "홈페이지 주소",
"공무원의 전자우편주소", "공개 구분"의 용어는 표시하지 아니하고 그 내용을 적는다` —
those guide terms are **placeholders to consume**, not labels to keep. The
section labels (수신 / 경유 / 제목 / 협조자 / 시행 / 접수 / 우 / 전화번호 / 직인)
legitimately stay. The 비고 block itself must not ship
(`이 난은 서식에 포함하지 아니한다`).

**The 직인 rule.** The red-bordered 직인 box is a *placement for a physical
impression*. It survives untouched and is never a fill target — writing a name
or an image caption into it is `seal_slot_overwritten`. Same for the 서명
positions in the 결재란.

**What stays blank for a human**: the 직인 impression and every signature. Say
so when handing the document back; do not type a name where a seal or a
signature belongs.

**Half-filled is the failure mode**, not "empty". A 결재란 row must be fully
filled or blank by design — `기안자` consumed but `직위(직급)` still showing is
`gyeoljae_seat_half_filled`, and a filled seat beside a wiped sibling is
`gyeoljae_row_half_filled`. 시행/접수 values must be in the regulated
`처리과명-일련번호(날짜)` shape.

Issuing 기관명 / 부서 / 직위 come from the `gongmun_org` pack, never from
memory: the shipped default is empty, so the pack rules report
`skipped: pack_vocabulary_empty` until an operator writes a real instance.

Details, per-rule findings, and the blank-vs-final state machine:
`references/gongmun_flow.md`.
