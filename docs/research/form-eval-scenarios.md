# Per-family form eval scenarios (W5.2)

Status: ACTIVE (Wave 5.2 of `docs/plans/v0.16-unified-core-and-modules.md`).
These scenarios are the acceptance instrument for the 5.3 skill surface and the
seed of the Wave 6 regression benches (§6.1–6.2).

Corpus: `tests/corpus/forms/` (12 blank official templates, 5 recorded skips —
see `manifest.json`). Descriptive recognition baseline:
`tests/corpus/forms/probe_results.json` (Bench-0, not a gate).

## Protocol

- **Baseline first** (per `docs/research/skill-efficiency-gen5.md` §5): run
  every scenario once with *no* skill loaded, record outcome + tokens. The 5.3
  acceptance is "passes with skill loaded AND beats its no-skill baseline".
- Scenario shape: `{id, family, query, files, expected_behavior[]}`. Each
  expected-behavior line is tagged `[machine]` (exact command + exit/threshold)
  or `[judgment]` (rubric for a human/LLM judge).
- All fills happen on a **copy** of the corpus file; corpus files are
  immutable inputs (sha256 pinned in the manifest).
- This slice is XML-level only. `.hwp` members cannot be opened by any
  scenario until the W6 conversion scenario (XC-1) produces certified `.hwpx`
  siblings on the COM/operator machine. Scenarios on `.hwp` corpus members are
  therefore marked `blocked_on: XC-1`; their rubrics are written now so the
  benches exist the day conversion lands.

## Bench-0 facts the scenarios must respect (from probe_results.json)

- Only 2/12 corpus members are native `.hwpx` (both PPS/조달청) — the hwp-first
  reality the landscape doc predicted. Probe headline: anchors 28–29,
  tables 1–3, table cells 16–45, **guide_text 0 on both**.
- `guide_text = 0` despite both forms containing instructional prose ("내용을
  자세히 읽으신 후 …", 첨부서류 lists) is a real detector finding: the current
  heuristics (colored runs / 작성예시 patterns from report templates) do not
  fire on procurement-form instruction text. Scenarios below treat guide-text
  detection as an open capability question, not an assumed feature.
- `constraints` (base_pt / line_spacing / page budget) detected: 0 on both —
  fixed-grid forms do not declare report-style constraints. The fill gate for
  form families is *layout immutability*, not prose-budget compliance.

---

## Family ① 민원/신고 서식 (petition) — 4 corpus files, all .hwp

```json
{
  "id": "P1-recognize-fill-jumin",
  "family": "petition",
  "query": "이 신청서 양식을 열어서 신청인(개인) 칸에 채울 항목이 뭔지 알려주고, 내가 주는 값으로 채워줘. 양식 모양은 절대 바뀌면 안 돼.",
  "files": ["tests/corpus/forms/petition/jumin-deungchobon-sinchengseo.hwp (via XC-1 hwpx sibling)"],
  "blocked_on": "XC-1",
  "expected_behavior": [
    "[machine] form_inspect.py exits 0 on the converted hwpx; profile.json anchors >= 10 and table_map contains >= 1 table with >= 30 cells",
    "[machine] after fill: check_residue.py --form-profile profile.json --artifact filled.hwpx exits 0 (no guide/placeholder residue)",
    "[machine] layout_qa: grid geometry (row heights, merged-cell map, page count) byte-identical between blank and filled table_map except cell text runs",
    "[machine] repeat the same fill on the filled artifact: output sha256 unchanged (idempotence)",
    "[judgment] the model identifies the staff-only cells (접수번호/접수일/처리기간, shaded cells) and refuses to write into them",
    "[judgment] checkbox glyphs ([ ]/□) are treated as text toggles (√/☑ insertion), never replaced by form-field objects"
  ]
}
```

```json
{
  "id": "P2-fill-boundary-jeongbo",
  "family": "petition",
  "query": "정보공개 청구서를 채워줘. 청구인 정보와 청구 내용은 내가 줄게.",
  "files": ["tests/corpus/forms/petition/jeongbo-gonggae-cheongguseo.hwp (via XC-1)"],
  "blocked_on": "XC-1",
  "expected_behavior": [
    "[machine] fill touches only cells outside the shaded (borderFill 음영) region; table_map diff shows zero changed cells among shaded ones",
    "[machine] check_residue exits 0; page count unchanged",
    "[judgment] the form's own instruction line '색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다' is discovered and quoted as the reason for the fill boundary — recognition must come from the document, not from prior knowledge"
  ]
}
```

Rationale: P1 is the canonical dense-grid citizen form; P2 exists because the
fill boundary is *stated inside the form* — the recognizer must read it. The
사업자등록 신청서 (densest, multi-page) and the admrul variant join Bench-1 as
recall stress rows, same rubric as P1.

## Family ② 공문/기안문 (gongmun) — 2 corpus files, .hwp

```json
{
  "id": "G1-gianmun-body-edit",
  "family": "gongmun",
  "query": "이 기안문 서식으로 '수신 ○○부장관, 제목: 자료 제출 협조 요청' 공문 초안을 만들어줘. 결재란과 발신명의는 그대로 둬.",
  "files": ["tests/corpus/forms/gongmun/gianmun-byeolji-1ho.hwp (via XC-1)"],
  "blocked_on": "XC-1",
  "expected_behavior": [
    "[machine] header/footer XML parts and 결재란 table geometry sha256-identical before/after body edit (non-destructive guarantee, T16 territory)",
    "[machine] 직인 placeholder position (anchor coordinates in section XML) unchanged",
    "[machine] page size stays 210x297 with prescribed margins (page_metrics diff empty)",
    "[judgment] body follows 두문/본문/결문 numbering convention (1. 가. 1)) already implied by the form",
    "[judgment] the 비고 block ('이 난은 서식에 포함하지 아니한다') is recognized as non-form guidance and excluded from the produced 공문"
  ]
}
```

## Family ③ 학교 서식 (school) — CORPUS GAP (0 files)

Both listed sources failed (dead URL; the other served an issued 가정통신문,
rejected as a filled document — see manifest `skipped`). Scenario is written
against the family's known shape and marked blocked:

```json
{
  "id": "S1-messy-school-form",
  "family": "school",
  "query": "교외체험학습 신청서를 채워줘. 학생 정보와 기간, 학습 계획은 내가 줄게.",
  "files": ["(corpus gap — needs a blank school form from an official 교육청 board; re-source in W6)"],
  "blocked_on": "corpus acquisition (record in W6 backlog); then XC-1 if .hwp",
  "expected_behavior": [
    "[machine] check_residue exits 0 after fill — school forms are the T18 guide-text-in-colored-runs family, so residue MUST include colored guide runs",
    "[machine] irregular merges preserved: table_map merge topology identical before/after",
    "[judgment] guide text detection on an undisciplined table (colored runs, 예시 rows) finds >= 1 guide region — this is exactly where Bench-0's guide_text=0 result predicts failure; a miss here is a mechanism finding for 6.2, not a scenario bug"
  ]
}
```

## Family ④ 연구보고서 양식 (research) — 1 corpus file, .hwp

The report benches (v0.15 suite) already cover this family in-house; the NRF
file exists as an *external* anchor so the claim is not school-template-shaped.

```json
{
  "id": "R1-nrf-external-anchor",
  "family": "research",
  "query": "이 결과보고서 양식의 구조(과제정보 표, 섹션 목차, 분량 제약)를 프로파일링해줘.",
  "files": ["tests/corpus/forms/research/nrf-gyeolgwa-bogoseo-yangsik.hwp (via XC-1)"],
  "blocked_on": "XC-1",
  "expected_behavior": [
    "[machine] form_inspect exits 0; profile.json anchors >= 5 (front-matter grid labels + section headings)",
    "[machine] existing report pipeline (fill_report dry-run) accepts the profile without report-pack-specific assumptions erroring",
    "[judgment] the profile distinguishes the front-matter fixed grid from the flowing body — the ①-vs-④ boundary inside one document"
  ]
}
```

## Family ⑤ 기업 내부 문서 (corp) — DOCUMENTED BOUNDARY (0 files)

No official source exists (the 5.1 finding). Per §6.2 this ships as a stated
capability boundary, not a silent gap: **no eval scenario; the 5.3 skill
surface must say the family is unsupported/untested.** If a user supplies
their own 품의서 blank, the petition rubric (P1) applies by analogy.

## Family ⑥ 지원사업 신청서 (grant) — 3 corpus files (1 .hwp hybrid, 2 native .hwpx)

The only family probe-able **today**; these two scenarios are runnable in this
slice and are the W5.3 acceptance floor.

```json
{
  "id": "A1-pps-recognize-fill",
  "family": "grant",
  "query": "이 협업 승인 신청서(hwpx)를 프로파일링하고, 신청 기업 정보로 채워줘. 양식은 그대로여야 해.",
  "files": ["tests/corpus/forms/grant/pps-hyeopeop-seungin-sinchengseo.hwpx"],
  "expected_behavior": [
    "[machine] form_inspect exits 0; anchors >= 29 and table_map: 1 table / 45 cells (Bench-0 pinned floor — regression if below)",
    "[machine] after fill of a copy: check_residue --form-profile profile.json --artifact filled.hwpx exits 0",
    "[machine] table_map geometry (addr/size/borderFill per cell) identical blank-vs-filled; only text runs differ",
    "[machine] repeat fill idempotence: second run leaves sha256 unchanged",
    "[judgment] 서명 cell ('신청인: (서명 또는 인)') is left blank and flagged for the human signer, never auto-filled"
  ]
}
```

```json
{
  "id": "A2-pps-consent-checkboxes",
  "family": "grant",
  "query": "개인정보 수집·이용 동의서에 전부 '동의함'으로 체크하고 날짜를 넣어줘.",
  "files": ["tests/corpus/forms/grant/pps-jeongbogonggae-donguiseo.hwpx"],
  "expected_behavior": [
    "[machine] form_inspect exits 0; anchors >= 28; tables = 3 (Bench-0 pinned)",
    "[machine] checkbox toggles are text-run edits inside existing cells; cell count and merge map unchanged",
    "[machine] check_residue exits 0 on the filled copy",
    "[judgment] the model surfaces the consent semantics (what is being agreed to) before filling — a consent form is not a neutral grid",
    "[judgment] instructional prose ('내용을 자세히 읽으신 후 …') is not deleted even though guide_text detection reports 0 regions — deletion protection must not depend on the detector firing"
  ]
}
```

```json
{
  "id": "A3-kstartup-hybrid",
  "family": "grant",
  "query": "이 지원사업 신청서+사업계획서 양식에서 앞쪽 신청서 표를 채우고, 사업계획서 1개 섹션 초안을 써줘. 한 번의 실행으로.",
  "files": ["tests/corpus/forms/grant/kstartup-jiwon-sincheongseo-saeopgyehoekseo.hwp (via XC-1)"],
  "blocked_on": "XC-1",
  "expected_behavior": [
    "[machine] front-grid fill passes the A1 geometry rubric while body-section prose passes report-style layout_qa in the same artifact",
    "[machine] if the 공고 declares a page budget ('N쪽 이내'): final page count <= N (declared_gates style verdict)",
    "[judgment] multi-section navigation: the model addresses the fixed grid and the flowing body as different edit regimes without being told (§6.1 multi-section bench seed)"
  ]
}
```

## Family ⑦ 인사/노무 (hr) — 2 corpus files, .hwp (versioned pair)

```json
{
  "id": "H1-labor-contract-fill",
  "family": "hr",
  "query": "표준근로계약서를 채워줘. 당사자, 기간, 임금 조건은 내가 줄게.",
  "files": ["tests/corpus/forms/hr/moel-pyojun-geunrogyeyakseo-2025.hwp (via XC-1)"],
  "blocked_on": "XC-1",
  "expected_behavior": [
    "[machine] underline-blank fill: paragraph count and clause numbering unchanged; only run text inside blanks differs",
    "[machine] check_residue exits 0; single-page form stays single-page",
    "[judgment] baseline-sanity family (§6.1): ANY machine-check failure here is a red-flag finding, not a boundary",
    "[judgment] 서명란 left for both parties; the model does not invent 상여금/수당 values for blanks the user did not supply — unfilled blanks stay blank and are listed back to the user"
  ]
}
```

```json
{
  "id": "H2-template-identity",
  "family": "hr",
  "query": "이 근로계약서 양식이 최신(2025 개정)인지 확인해줘.",
  "files": [
    "tests/corpus/forms/hr/moel-pyojun-geunrogyeyakseo-2013.hwp",
    "tests/corpus/forms/hr/moel-pyojun-geunrogyeyakseo-2025.hwp"
  ],
  "blocked_on": "XC-1",
  "expected_behavior": [
    "[machine] style_diff/structure diff between the two versions is non-empty and deterministic (same diff on repeat runs)",
    "[judgment] the model identifies which is the newer revision from document content (공휴일/근로자의 날 clause present only in 2025) and says so with the evidence — template-identity verification is the family-⑥ user-value case rehearsed on the simplest family"
  ]
}
```

## Cross-cutting: XC-1 hwp→hwpx conversion (W6, COM/operator machine)

```json
{
  "id": "XC-1-convert-fidelity",
  "family": "cross",
  "query": "corpus의 모든 .hwp를 .hwpx로 변환하고 충실도를 증명해줘.",
  "files": ["tests/corpus/forms/**/*.hwp (10 files)"],
  "blocked_on": "W6 — requires Hancom COM on the operator machine; NEVER run in this slice",
  "expected_behavior": [
    "[machine] each converted hwpx: form_inspect exits 0; check_convert_parity.py (extracted vs assembled semantics) exits 0",
    "[machine] rendered page count identical hwp-vs-hwpx; layout_qa geometry diff empty per page",
    "[machine] converted siblings land as tests/corpus/forms/<family>/<slug>.converted.hwpx + manifest entries with sha256 and hancom_version (render-cert convention)",
    "[machine] privacy_scan HARD-clean over the converted set",
    "[judgment] per-family fidelity notes (which families convert clean, which drift) feed §6.2 fix-or-bound directly"
  ]
}
```

## Scenario count and gate summary

- 10 scenarios total: 2 runnable now (A1, A2 — native hwpx), 7 blocked on
  XC-1 conversion, 1 blocked on corpus re-sourcing (S1). Family ⑤ is a
  documented boundary with deliberately no scenario.
- W5.3 acceptance floor = A1 + A2 pass with skill loaded, beat no-skill
  baseline, with loaded-token footprint reported.
- W6 inherits: all XC-1-blocked scenarios + Bench-0 pinned floors
  (anchors 29/28, tables 1/3, cells 45/16) as regression values, and the
  guide_text=0 detector finding as an open 6.2 item.

---

## Results appendix — W5.3 machine-check run (2026-08-07)

Executed on the W5.3 slice (branch `w5-skill-surface`), the scripted
(`[machine]`) halves of the two runnable scenarios A1/A2 only. Fills used
`engine/scripts/preedit.py replace` with a synthetic mapping on a copy of
each corpus file (corpus untouched; artifacts written outside the repo).
**The agent-in-the-loop half (skill loaded vs no-skill baseline, loaded-token
footprint) is OPERATOR-RUN and still open** — the machine floors below are a
necessary, not sufficient, condition for the 5.3 acceptance.

### A1 pps-hyeopeop-seungin-sinchengseo.hwpx — all machine checks PASS

| check | result |
|---|---|
| form_inspect exit 0; anchors >= 29; 1 table / 45 cells | PASS (anchors 29, tables 1, cells 45 — Bench-0 floor exact) |
| fill on copy (3 synthetic keys: `우(     -     )`, `" http://"`, `년      월      일`) | PASS (hits 1/1/1) |
| check_residue exit 0 on filled copy | PASS (form-fill keep derivation, below) |
| table_map geometry identical blank-vs-filled (addr/width/height/borderFill/shaded per cell + rowCnt/colCnt/pageBreak) | PASS |
| repeat-fill idempotence (2nd run `--allow-missing`, zip member contents compared) | PASS (content-identical) |

### A2 pps-jeongbogonggae-donguiseo.hwpx — all machine checks PASS

| check | result |
|---|---|
| form_inspect exit 0; anchors >= 28; tables = 3 | PASS (anchors 28, tables 3, cells 16 — Bench-0 floor exact) |
| consent toggles as text-run edits (`(예,  아니오)` -> `(예 ☑,  아니오)`, hits=2) + dates | PASS |
| cell count and merge map unchanged | PASS (full geometry identical) |
| check_residue exit 0 on filled copy | PASS |
| repeat-fill idempotence | PASS (content-identical) |

Note: the two `□` glyphs in A2 are section-heading bullets ("□ 개인정보
수집ㆍ이용 내역"), NOT checkboxes — the fillable consent slots are the
`(예,  아니오)` text runs. Confirms the A2 judgment rubric's premise.

### Protocol notes / mechanism findings

1. **Form-fill keep derivation for check_residue.** The residue gate's
   auto-derived forbidden list = anchors + guide_text (+ placeholders); on a
   form FILL the labels legitimately survive. Honest invocation: keep =
   (anchors ∪ placeholders) minus the entries consumed by the fill mapping
   (whitespace-normalized substring match), passed as repeated `--keep`.
   The gate stays non-vacuous — **negative control**: the same invocation
   against the UNFILLED copy exits 3 on both scenarios (consumed
   placeholders detected as residue). A1's second form label
   `[별지 제2호의 8서식]` is profile `placeholders`, survives a legitimate
   fill, and must be in the keep set.
   *Refined by the second clean-room run (T31)*: "consumed" cannot mean "the
   mapping named this key", because a correct fill of a labeled field KEEPS
   the label as a prefix (`" http://"` → `" http://host"`) and the key text
   survives inside the value. A key is consumed when its mapped VALUE is in
   the document (key-absence as the fallback), and the surviving key
   occurrence is attributed to the value's span by
   `check_residue --fill-map` — per occurrence, so a second unfilled
   occurrence of the same key still exits 3.
2. **Generic replace keys are unsafe (new sharp edge, documented in
   skill/references/operations.md).** preedit tier B is a raw substring pass
   over section XML: the key `http://` scored 15 hits (14 of them inside
   xmlns namespace URIs — markup, not content). The document-unique run key
   `" http://"` (leading space) hits exactly once. Rule: keys must be
   document-unique; verify the reported hit count.
3. `guide_text = 0` and `constraints_detected = 0` reconfirmed on both
   forms (Bench-0 finding stands; W6 §6.2 item unchanged).
4. Geometry comparison method: `form_inspect` table_map with the
   text-dependent fields (`text_preview`, `truncated`, `classification`)
   stripped; everything else byte-equal. `evals/cleanroom.py`'s
   `_geometry_signature` is an allowlist of geometry keys, so a new
   text-derived field cannot leak into the comparison by accident. Idempotence: per-member sha256 of zip
   contents (timestamps excluded per the preedit contract).

### Scenario-vs-run deltas (for the operator re-run)

- A1 machine line "anchors >= 29 and 1 table / 45 cells" and A2
  "anchors >= 28; tables = 3" matched exactly — floors unchanged.
- The A1 scenario's "output sha256 unchanged" idempotence line is satisfied
  at zip-member-content level (the preedit contract's own definition);
  whole-file sha equality additionally held on this run.
