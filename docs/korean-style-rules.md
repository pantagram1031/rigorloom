# Korean style rules (`ko-style/1`)

`rigorloom style check FILE` points at Korean phrasing that is often worth a
second look: double passives, phrasing carried over from Japanese or English,
and habits that stand out in reports and official documents. It reads `.txt`,
`.md` and `.hwpx`, needs no session root, and writes nothing.

```sh
rigorloom style check draft.md --format text
rigorloom style check 기안문.hwpx --doc-type gongmun
```

Each match is printed as `file:line:col severity rule-id`. For `.hwpx` the
"line" is the paragraph number, counted the same way `rigorloom guard` counts
them. Code fences in Markdown are skipped.

## What the result means

Most rules are **notices**. Plenty of careful human writers use these phrases,
and some are standard in certain documents (`~에 의해` in legal text, for
example). A notice asks "is this what you meant to say?". It is not a verdict
on the text or on who wrote it. These rules are not a detector score and are
not tuned against one.

One rule is an **error**: the double passive (`되어지다`), which 국립국어원
treats as a mistake. The command exits 3 only when an error rule matched,
0 otherwise (notices included), and 2 when the file cannot be read.

`--doc-type` picks the rules that fit the document. Report-only rules such as
summary openers and the "A가 아니라 B" frame do not apply to 공문 or contracts,
where numbered items and repeated references are normal.

## Versioning

The rule set has a version (`ko-style/1`), and every result records it.
Changing a pattern, a severity or the document types a rule applies to means a
new version. Each rule has a sentence it must flag and a close sentence it must
leave alone, both listed below and both checked by `tests/test_style_check.py`.

## Rules

| id | severity | applies to | flags | leaves alone | try instead |
|---|---|---|---|---|---|
| `ko.double-passive` | error | all | 이 방법은 널리 사용되어지고 있다. | 이 방법은 널리 사용되고 있다. | 되어진 → 된 |
| `ko.e-isseoseo` | notice | all | 교육에 있어서는 신뢰가 가장 중요하다. | 그날은 집에 있어서 행사에 못 갔다. | ~에서, ~할 때 |
| `ko.e-dareum-anida` | notice | all | 이는 포기에 다름 아니다. | 이는 포기나 다름없다. | ~이나 다름없다 |
| `ko.ji-anhumyeon-an-doenda` | notice | all | 기한 안에 제출하지 않으면 안 된다. | 기한 안에 제출해야 한다. | ~해야 한다 |
| `ko.hayeogeum` | notice | all | 참가자로 하여금 직접 고르게 했다. | 참가자가 직접 고르도록 했다. | A가 B하도록 |
| `ko.e-uihae` | notice | report, grant | 이 장치는 연구진에 의해 개발되었다. | 이 장치는 연구진이 개발했다. | 능동문 |
| `ko.gajigo-itda` | notice | report, grant | 이 재료는 높은 강도를 가지고 있다. | 그는 우산을 가지고 나갔다. | 강도가 높다 |
| `ko.geot-i-pilyohada` | notice | report, grant | 측정값을 다시 확인하는 것이 필요하다. | 측정값을 다시 확인해야 한다. | 동사로 바로 |
| `ko.para-opener-summary` | notice | report | 결론적으로 두 방법의 차이는 작았다. | 두 방법의 차이는 결론에서 다시 다룬다. | 되풀이 문단이면 줄이기 |
| `ko.filler-opener` | notice | report, grant | 또한 응답자의 절반은 같은 답을 골랐다. | 응답자의 절반은 또한 같은 답을 골랐다. | 접속어 없이 새 내용으로 |
| `ko.contrast-frame` | notice | report | 문제는 비용이 아니라 시간이다. | 비용은 문제가 되지 않았다. | B를 바로 주장 |
| `ko.md-bold` | notice | report, 공문, 민원, 계약 | 이 단계는 **반드시** 지켜야 한다. | 이 단계는 반드시 지켜야 한다. | 문장으로 강조 |
| `ko.exclamation` | notice | report, 공문, 민원, 계약, grant | 결과가 기대보다 좋았다! | 결과가 기대보다 좋았다. | 마침표 |

`ko.e-isseoseo` only matches `에 있어(서)` followed by 는, 도, 의 or a comma.
Without that ending it cannot tell 교육에 있어서 from 집에 있어서 (because I
was home), so it stays quiet rather than guess.

## Where the rules came from

- The double passive and the carried-over phrasings (`~에 있어서`, `~에 다름
  아니다`, `~지 않으면 안 된다`, `~로 하여금`) are standard examples in
  국립국어원's guidance on 번역 투.
- The report rules (`ko.para-opener-summary`, `ko.filler-opener`,
  `ko.contrast-frame`, `ko.md-bold`, `ko.exclamation`) come from research notes
  on student and research reports kept outside this repository. Those notes
  compared paragraph openers, sentence length and hedges in human and generated
  reports, and drew on public writing guides. Only their conclusions are used
  here, not their measurements. The notes are the Pentaverse research notes
  (2026-11): ask through hub mail AX-0009 and the replies from PV2, GROK and
  RPT.
- The same notes found that these signals point in opposite directions across
  genres. Fiction writers use more connectives than generated text does, and
  academic text the reverse. So every rule names the document types it applies
  to, and the result is a list of places to look, never a score for the whole
  document.

## Not in this version

- **Sentence and clause length.** Human reports vary in length too, and the
  numbers change a lot with how text is split into sentences. A later version
  may add a notice for very long sentences, never a target length.
- **`~수 있다` as a hedge.** Most uses mean ability or possibility, not
  hedging, so a pattern cannot tell them apart.
- **Inanimate subjects.** There is no measured evidence yet on how often they
  misfire in 공문 and contracts, where they are normal ("본 계약은 ...").
- **Connective density, word-frequency balance.** These flip direction between
  genres, and fixing them on the surface tends to make prose worse.
- Longer-range checks (an ending paragraph that repeats the body, the share of
  sentences with concrete numbers or sources) need the document's structure
  and belong in the report module, not this command.

## Document-type rule packs

Pass `--pack <name>` to apply a document-type pack under `runtime/style_packs/` on
top of `ko-style/1`. Unless `--doc-type` is given explicitly, `--pack` selects the
`ko-style/1` rules for the pack's `baseDocType` (`gongmun` for `hr`, and the pack's
own name for `gongmun`, `minwon`, and `grant`), so the combined ruleset header reads
`ko-style/1+<pack>/1`. Without `--pack`, no pack rule runs.

A `notice` is a question for a person to review and decide, never a verdict on who
wrote the text or on legal validity; only `error` rules fail the exit code when a
mandatory written norm cannot match correct text. These packs are narrow,
pattern-based checks and make no claim about how much of any document type they
cover. Rules marked `house` reflect internal drafting conventions rather than an
external official guide, as noted in the `minwon`, `hr`, and `grant` packs.

### gongmun

`version`: `gongmun/1` | `baseDocType`: `gongmun`

| Rule ID | Severity | Flags | Positive | Negative | Source |
| --- | --- | --- | --- | --- | --- |
| `gongmun.date-zero-pad` | `notice` | 월·일 한 자릿수 앞 불필요한 `0` 표기 | `제출 마감일은 2026. 03. 05.까지입니다.` | `제출 마감일은 2026. 3. 5.까지입니다.` | 행정업무운영 편람 (2025), 제2장 제1절 4. 가. 2) 날짜 (영 제7조제5항) 및 부록, pp. 49, 308 |
| `gongmun.time-12h` | `notice` | 오전·오후 12시간제 시각 표기 | `사전 점검 회의는 2026. 4. 8. 오후 3시 20분에 시작합니다.` | `사전 점검 회의는 2026. 4. 8. 15:20에 시작합니다.` | 행정업무운영 편람 (2025), 제2장 제1절 4. 가. 3) 시간 (영 제7조제5항) 및 부록, pp. 49, 308 |
| `gongmun.currency-no-korean` | `notice` | `금 ○○○원` 뒤 한글 금액 괄호 병기 누락 | `집행 금액은 금240,000원으로 확정하였습니다.` | `집행 금액은 금240,000원(금이십사만원)으로 확정하였습니다.` | 행정업무운영 편람 (2025), 제2장 제1절 4. 가. 4) 금액 (규칙 제2조제2항) 및 부록, pp. 49, 308 |
| `gongmun.amount-unit-awkward` | `notice` | 다섯 자릿수 이상 금액의 `천 원` 단위 표기 | `내년도 사업 소요 예산은 1,200천 원으로 산정하였습니다.` | `내년도 사업 소요 예산은 120만 원으로 산정하였습니다.` | 행정업무운영 편람 (2025), 제2장 제1절 3. 다. 공공언어 바로 쓰기 1. 가. 3), p. 37 |
| `gongmun.authoritative-ending` | `notice` | `~바람`, `~할 것` 명사형 명령 종결 | `변경된 계획서는 2026. 4. 10.까지 제출할 것.` | `변경된 계획서는 2026. 4. 10.까지 제출해 주시기 바랍니다.` | 행정업무운영 편람 (2025), 제2장 제1절 3. 다. <공공언어 바로 쓰기 참고사항> 3. 가. 1) 및 6. 나. 2) 다) (3), pp. 47-48, 68 |
| `gongmun.attachment-label` | `notice` | 비표준 첨부물 표제어 `유첨`, `별첨` | `유첨  보안 점검 자체 체크리스트 1부.  끝.` | `붙임  보안 점검 자체 체크리스트 1부.  끝.` | 행정업무운영 편람 (2025), 제2장 제1절 5. 다. 3) 첨부물의 표시 (규칙 제4조제4항) 및 부록, pp. 59-60, 310 |
| `gongmun.archaic-admin-words` | `notice` | `금번`, `금회`, `익일`, `상기의`, `적의 조치` 등 낡은 한자 행정어 | `금번 회의 안건은 익일까지 각 부서에 공유해 주시기 바랍니다.` | `이번 회의 안건은 다음 날까지 각 부서에 공유해 주시기 바랍니다.` | 행정업무운영 편람 (2025), 제2장 제1절 3. 다. 공공언어 바로 쓰기 4. 한자어보다 쉽게 다듬은 말, pp. 39-41 |
| `gongmun.yeondo-spelling` | `notice` | `회계년도`, `사업 년도` 등 `연도`로 고쳐야 하는 표기 | `차기 회계년도 예산 집행 지침을 별도로 통보합니다.` | `차기 회계연도 예산 집행 지침을 별도로 통보합니다.` | 알기 쉬운 법령 정비기준 (제10판 수정증보판 (2025)), 제2장 제2절 7. 어문 규정 나., p. 111 |
| `gongmun.saishiot-orthography` | `notice` | `갯수`, `최소값`, `하교길`, `수도물`, `칫과` 등 사이시옷 맞춤법 오류 | `제출 서류 갯수와 항목별 최소값을 표에 적어 주시기 바랍니다.` | `제출 서류 개수와 항목별 최솟값을 표에 적어 주시기 바랍니다.` | 행정업무운영 편람 (2025), 제2장 제1절 3. 문서 작성 및 처리의 일반원칙 (영 제7조제1항) 및 2. 가. 어문 규범, pp. 33, 42 |
| `gongmun.submit-receive-confusion` | `notice` | 서류를 내는 사람의 행동을 `접수하다`로 표현한 경우 | `신청자가 구비 서류를 기한 내에 온라인으로 접수하여야 합니다.` | `신청자가 구비 서류를 기한 내에 온라인으로 제출하여야 합니다.` | 행정업무운영 편람 (2025), 제2장 제1절 3. 다. <공공언어 바로 쓰기 참고사항> 2. 다. 3), p. 46 |
| `gongmun.e-uigeo` | `notice` | 쉽게 풀어 쓸 수 있는 표현 `~에 의거하여` | `관련 규정에 의거하여 점검 결과를 회신해 주시기 바랍니다.` | `관련 규정에 따라 점검 결과를 회신해 주시기 바랍니다.` | 한눈에 알아보는 공공언어 바로 쓰기 (2022 개정판), 둘째 마당 4. 안내문, pp. 99, 117 |

### minwon

`version`: `minwon/1` | `baseDocType`: `minwon` (includes `house` / 자체 rules)

| Rule ID | Severity | Flags | Positive | Negative | Source |
| --- | --- | --- | --- | --- | --- |
| `minwon.recipient-address-missing` | `notice` | 민원 회신문 수신란에 우편번호·도로명주소 누락 | `수신 ○○○ 귀하` | `수신 ○○○ (우00000 ○○시 ○○로 12)` | 행정업무운영 편람 (2025), 제2장 제1절 5. 나. 두문 (규칙 제4조제2항) — 2) 라) 민원회신문서, pp. 57-58 |
| `minwon.authoritative-tone` | `notice` | 민원인 대상 `명심하기`, `요망됨` 등 권위적 어휘 | `기한 이후에는 추가 서류 제출이 불가함을 명심하여 주시기 바랍니다.` | `기한이 지나면 추가 서류를 제출할 수 없으니 기한 내에 제출해 주시기 바랍니다.` | 한눈에 알아보는 공공언어 바로 쓰기 (2022 개정판), 둘째 마당 1. 기안문, pp. 23, 39 |
| `minwon.stiff-legal-jargon` | `notice` | `사료됨`, `득하여`, `필히`, `조속히` 등 어려운 한자어 | `신청 요건을 충족하지 못하여 지원 대상에 해당하지 않는 것으로 사료됩니다.` | `신청 요건을 충족하지 못하여 지원 대상에 해당하지 않는 것으로 판단됩니다.` | 한눈에 알아보는 공공언어 바로 쓰기 (2022 개정판), 둘째 마당 1. 기안문 및 4. 안내문, pp. 21, 37, 47, 107 |
| `minwon.internal-rule-refusal` | `notice` | 법령 조항 없이 `내부 지침상`, `관례상`으로만 거절 | `요청하신 감면 혜택은 내부 지침상 적용하기 어렵습니다.` | `관련 조례 제5조제1항은 감면 대상을 관내 거주자로 정하고 있습니다. 신청인은 관외 거주자로 확인되어 감면 대상에 해당하지 않습니다.` | `house` |
| `minwon.vague-followup` | `notice` | 일정 안내 확인이 필요한 `추후 별도 안내` 표현 | `제출하신 현장 확인 요청은 담당 부서 검토 후 추후 별도 안내드리겠습니다.` | `제출하신 현장 확인 요청은 담당 부서 확인을 거쳐 2026. 5. 15.까지 결과를 안내드리겠습니다.` | `house` |
| `minwon.blunt-closure` | `notice` | 설명 없이 `수용 불가`, `민원 종결` 등 단정적 종결 | `제출하신 이의 신청 건은 관련 요건 미충족으로 수용 불가합니다.` | `필수 증빙 서류가 제출되지 않아 이의 신청 내용을 확인하기 어렵습니다. 보완할 서류와 제출 기한은 다음과 같습니다.` | `house` |

### hr

`version`: `hr/1` | `baseDocType`: `gongmun` (includes `house` / 자체 rules)

| Rule ID | Severity | Flags | Positive | Negative | Source |
| --- | --- | --- | --- | --- | --- |
| `hr.danghae-jargon` | `notice` | 인사 문서의 관행적 한자어 `당해` | `당해 기관 인사위원회의 심의를 거쳐 전보를 발령한다.` | `해당 기관 인사위원회의 심의를 거쳐 전보를 발령한다.` | 행정업무운영 편람 (2025), 제2장 제1절 3.다.2) 국민이 이해하기 쉬운 용어 사용 (영 제7조제2항) · 4. 한자어보다 쉽게 다듬은 말, pp. 33, 40 |
| `hr.sidal-authoritative` | `notice` | 하달식 권위적 용어 `시달` | `인사 발령 통지서를 각 소속 부서에 즉시 시달하였다.` | `인사 발령 통지서를 각 소속 부서에 즉시 전달하였다.` | 알기 쉬운 법령 정비기준 (제10판 수정증보판 (2025)), 제2장 제2절 5.나. 권위적 용어의 정비 ('시달'), p. 70 |
| `hr.jinggu-authoritative` | `notice` | 강제 어감의 권위적 용어 `징구` | `신규 임용 대상자로부터 경력 증명서와 서약서를 징구한다.` | `신규 임용 대상자로부터 경력 증명서와 서약서를 제출받는다.` | 알기 쉬운 법령 정비기준 (제10판 수정증보판 (2025)), 제2장 제2절 5.나. 권위적 용어의 정비 ('징구하다'), p. 71 |
| `hr.ikwol-iknyeon` | `notice` | 시점 한자어 `익월`, `익년` | `보직 변경에 따른 수당 조정분은 익월 급여 지급일부터 반영한다.` | `보직 변경에 따른 수당 조정분은 다음 달 급여 지급일부터 반영한다.` | 행정업무운영 편람 (2025), 제2장 제1절 3.다.2) 국민이 이해하기 쉬운 용어 사용 (영 제7조제2항) · 4. 한자어보다 쉽게 다듬은 말, pp. 33, 40 |
| `hr.effective-date-vague` | `notice` | 파견·직무대리 종료일 없는 `별도 발령 시까지` | `파견 근무 기간은 2026. 4. 1.부터 별도 발령 시까지로 한다.` | `파견 근무 기간은 2026. 4. 1.부터 2026. 9. 30.까지로 한다.` | `house` |
| `hr.rank-step-vague` | `notice` | 직급·호봉·기준 확인이 필요한 `적정 호봉`, `소정의 처우` | `경력 산정 결과에 따라 적정 호봉을 획정하여 임용한다.` | `행정주사보로 임용하고, 경력 산정 결과에 따라 호봉은 7호봉으로 획정한다.` | `house` |

### grant

`version`: `grant/1` | `baseDocType`: `grant` (includes `house` / 자체 rules)

| Rule ID | Severity | Flags | Positive | Negative | Source |
| --- | --- | --- | --- | --- | --- |
| `grant.bare-foreign-abbr` | `notice` | 한글 풀이 병기 여부를 확인할 로마자 약어 (`R&D`, `MOU` 등) | `지역 대학과 산학 협력 MOU를 체결하여 R&D 과제를 공동 수행한다.` | `지역 대학과 산학 협력 업무 협약(MOU)을 체결하여 연구 개발(R&D) 과제를 공동 수행한다.` | 행정업무운영 편람 (2025), 제2장 제1절 3.다.2) (영 제7조제2항) · 2. 전문용어, pp. 33, 36, 38 |
| `grant.buzzword-foreign-loan` | `notice` | 제안서 내 외국어·외래어 유행어 (`거버넌스`, `니즈` 등) | `현장 수요자의 니즈를 반영한 민관 협력 거버넌스를 구축하여 시너지 효과를 낸다.` | `현장 수요자의 요구를 반영한 민관 협력 체계를 구축하여 상승효과를 낸다.` | 행정업무운영 편람 (2025), 제2장 제1절 3.다.2) (영 제7조제2항) · 3. 외국어보다 쉽게 다듬은 말, pp. 33, 39 |
| `grant.jego-jargon` | `notice` | 어려운 행정 한자어 `제고` | `지역 중소기업의 기술 경쟁력을 제고하여 자립 기반을 마련한다.` | `지역 중소기업의 기술 경쟁력을 높여 자립 기반을 마련한다.` | 행정업무운영 편람 (2025), 제2장 제1절 3.다.2) (영 제7조제2항) · 4. 한자어보다 쉽게 다듬은 말, pp. 33, 41 |
| `grant.archaic-grant-terms` | `notice` | 어려운 한자어 `가용한`, `차년도`, `내구 연한`, `수범 사례` | `차년도 예산에 내구 연한이 지난 시험 장비의 교체 비용을 반영한다.` | `다음 연도 예산에 정해진 사용 연수가 지난 시험 장비의 교체 비용을 반영한다.` | 행정업무운영 편람 (2025), 제2장 제1절 3.다.2) (영 제7조제2항) · 4. 한자어보다 쉽게 다듬은 말, pp. 33, 39-41 |
| `grant.progressive-jung-e-itda` | `notice` | 간결하게 다듬을 수 있는 진행 표현 `~중에 있다` | `주관 기관과 참여 기업이 공동으로 시제품을 개발 중에 있다.` | `주관 기관과 참여 기업이 공동으로 시제품을 개발하고 있다.` | 행정업무운영 편람 (2025), 제2장 제1절 3.다.2) (영 제7조제2항) · 1.가.3), pp. 33, 37 |
| `grant.e-hanhaeo-limit` | `notice` | 일본어 투 제한 표현 `~에 한하여` | `참여 자격은 공고일 기준 국내 소재 기업에 한하여 인정한다.` | `참여 자격은 공고일 기준 국내 소재 기업에만 인정한다.` | 알기 쉬운 법령 정비기준 (제10판 수정증보판 (2025)), 제3장 제2절 4.나.2)라) 직역 투 서술어의 정비 ('~에 한하여', '~에 한한다'), pp. 190-192 |
| `grant.rate-dueum-error` | `notice` | 모음·`ㄴ` 이외 받침 뒤 비율 표기 오류 (`자부담율`, `집행율` 등) | `민간 자부담율과 국비 집행율 산정 기준을 명시한다.` | `민간 자부담률과 국비 집행률 산정 기준을 명시한다.` | 행정업무운영 편람 (2025), 제2장 제1절 3. (영 제7조제1항) · 2. 가. 어문 규범, pp. 33, 41 |
| `grant.vague-impact-claim` | `notice` | 근거 확인이 필요한 성과 수식어 (`획기적`, `비약적` 등) | `이번 실증 과제를 통해 공정 효율이 비약적으로 향상되고 획기적인 성과가 나타날 것이다.` | `붙임 시험 결과를 기준으로, 이번 실증 과제를 통해 공정 처리 시간을 평균 12시간에서 9시간으로 단축할 수 있을 것으로 예상한다.` | `house` |
| `grant.deferred-plan-basis` | `notice` | 세부 예산·일정·지표를 `추후 협의/확정`으로 미룬 표현 | `핵심 성과 지표는 추후 별도 협의를 거쳐 확정한다.` | `핵심 성과 지표는 붙임 산정 기준표에 따라 1차 연도 착수 전에 확정한다.` | `house` |
