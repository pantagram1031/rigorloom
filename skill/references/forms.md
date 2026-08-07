# Form families — recognition notes and per-family gotchas

Distilled from the W5.1 usage landscape (`docs/research/hwp-usage-landscape.md`)
and Bench-0 (`tests/corpus/forms/probe_results.json`). Corpus:
`tests/corpus/forms/` — 12 official blank templates, sha256-pinned in
`manifest.json`; corpus files are immutable inputs (fill copies only).

## Environmental fact

Since 2026-05-18 government systems accept **HWPX only**; published blanks
are still mostly `.hwp`. Expect: blank arrives as `.hwp`, deliverable must be
`.hwpx`. Conversion runs on the COM/operator machine (heavy flow, CLI-only).

## Family cheat-sheet

| family | shape | fill regime | engine notes |
|---|---|---|---|
| ① 민원/신고 서식 | one dense bordered grid per page, merged cells, ㎜-prescribed layout | text into fixed cells, zero reflow | checkbox glyphs are TEXT (□→☑); staff-only cells are shaded (접수번호/처리기간) — never write there; the fill boundary is often stated inside the form itself |
| ② 공문/기안문 | 두문/본문/결문, 결재란 table, 관인/직인 seal position | body-only edits | header/footer + 결재란 geometry must be sha-identical after body edits (T16 header-height trap); 비고 blocks ("이 난은 서식에 포함하지 아니한다") are guidance, not form |
| ③ 학교 서식 | (a) 가정통신문 letterhead+prose+절취선 (b) parent forms = messy ① | parents/students fill (b) | least disciplined tables: irregular merges, colored guide runs — T18 territory; guide-text detector precision is unproven here (corpus gap, W6) |
| ④ 연구보고서 | front-matter grid + flowing body, equations/figures | author writes prose | rigorloom home turf; the ①-vs-④ boundary can exist INSIDE one document |
| ⑤ 기업 내부 문서 | 결재란 + summary grid + 금액 cells | staff | **UNSUPPORTED/UNTESTED** — no official corpus source exists; say so, then apply ①-family rules by analogy if the user insists |
| ⑥ 지원사업 신청서 | hybrid: ①-grid front + ④-body with page budget ("N쪽 이내") | applicant, high stakes | two edit regimes in one file; template-identity verification (right year/revision) is real user value; page budget is a declared gate |
| ⑦ 인사/노무 | numbered clauses + underline blanks, two-party signature | employer fills, employee co-signs | simplest family — any machine-check failure here is a red flag, not a boundary; unfilled blanks stay blank and are listed back |

## Bench-0 pinned floors (regression values, native .hwpx members)

| file | anchors | tables | cells | guide_text |
|---|---|---|---|---|
| grant/pps-hyeopeop-seungin-sinchengseo.hwpx | 29 | 1 | 45 | 1 (W6.2, was 0) |
| grant/pps-jeongbogonggae-donguiseo.hwpx | 28 | 3 | 16 | 5 (W6.2, was 0) |

A `form_inspect` run below these floors is a regression, not noise.

## Guide-text detector: coverage after W6.2 + one bound

W6.1 (XC-1) found `guide_text = 0` on 4/12 forms (both PPS, moel-2025,
admrul). W6.2 generalized the detector with mechanism-level pattern classes
(`engine/scripts/form_inspect.py`, tests in
`engine/tests/test_guide_text_patterns.py`):

- `note_prefix`: paragraph starts with ※ ☞ ◁ ▷ ＊ * 주N) — the dominant
  black-text guide convention in government forms.
- `example`: mid-line `(예시①)`-style markers (old check was prefix-only).
- `instruction`: -십시오 polite imperatives + instructional 기재
  (descriptive 기재된/기재되어 excluded — that is report body prose).

Result: 11/12 forms now detect guide text (pps-hyeopeop 1, pps-jeongbogonggae
5, moel-2025 16; full table in `docs/research/xc1-conversion-bench.md` §9.1).

**Documented bound — admrul-gajokdolbom-hyuga-sinchengseo stays 0, and 0 is
correct**: that form has no removable guide text at all (only labels,
checkbox fill-targets, and a ○○○ signature placeholder — all must survive
assembly). A detector change that makes it non-zero has over-generalized
into form content; a regression test locks the 0.

Unchanged consequences:

- Never treat "detector says 0" as "nothing to protect" — deletion
  protection must not depend on the detector firing (admrul proves a real
  0 exists).
- On fixed-grid forms `constraints` also detects 0 (no base_pt/line-spacing/
  page-budget declarations): the fill gate is **layout immutability**, not
  prose-budget compliance.

## Cross-family invariants

- Fill never changes: page count, table cell count, merge topology, row
  heights, borderFill/shading, anchor coordinates. Only text runs differ.
- Repeat fill is content-identical (idempotence).
- Signature/seal cells stay blank, flagged to the human signer.
- □ at line start is usually a heading bullet, not a checkbox (both PPS
  forms) — read the paragraph before toggling anything.
- Values the user did not supply are never invented; report unfilled slots.
