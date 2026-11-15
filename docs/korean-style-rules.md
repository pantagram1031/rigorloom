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
  here, not their measurements.
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
