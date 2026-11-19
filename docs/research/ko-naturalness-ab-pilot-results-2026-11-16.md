# Korean naturalness A/B pilot results, 2026-11-16

The pilot could not measure naturalness. Each condition scheduled 20 paragraphs. One fact card failed verification and was excluded, leaving 19 inputs per condition. Of those 19, 12 failed the reference-to-final guard while passing the draft-to-final guard, so only 7 pairs per condition were eligible. Most edited outputs were unchanged from the draft: 13 of 19 in condition A and 19 of 19 in condition B.

These are descriptive counts; they do not support a comparative finding.

| Condition | Judge | Reference chosen | Rewrite chosen | TIE | CANNOT_TELL | Malformed | Ineligible |
|---|---|---:|---:|---:|---:|---:|---:|
| A | Astra | 3 | 2 | 2 | 0 | 0 | 13 |
| A | GPT Sol | 4 | 2 | 1 | 0 | 0 | 13 |
| B | Astra | 4 | 1 | 2 | 0 | 0 | 13 |
| B | GPT Sol | 1 | 3 | 3 | 0 | 0 | 13 |

The judges agreed on 9 of 14 jointly valid pairs. Each condition scheduled 20 pairs, with 19 valid inputs and 7 eligible outputs. The same 12 paragraph IDs failed the reference-to-final guard in both conditions; their draft-to-final guards and model semantic verifications passed. The failed fact card omitted the actor responsible for preparing the measures.

The editor saw the checker JSON envelope, including the filename, schema and ruleset metadata, as well as the findings. The first condition A guard calls hit a file-extension mismatch and were rerun on byte-identical copies.

The strata were 정책 보도, 공개 문답, 인사 and 보조금; the first two were policy-news prose and published Q&A, not recipient-addressed official letters or real complaint replies, because such texts under 공공누리 제1유형 dated before 2020 were not found in native HTML and HWP/PDF attachments were out of scope.

19 of 21 indexed items come from korea.kr.

Sentence boundaries and personal-data screening were model-only, with no human review.

The indexed items’ publication dates range from 2015-08 to 2019-12.

Every listed role was filled by a model. No human served in the listed preparation, editing, verification, or judging roles.

The judges are from the same model family as the generator.

The corpus is a convenience sample, and publication age does not prove authorship. The `checker_doc_type` field maps each stratum to a checker type, not a genre. The protocol and run lock are in [the protocol](ko-naturalness-ab.md). Run artefacts (index, ledger, unblinded records) are kept outside the repository and are available on request.

## By stratum

**Condition A**

| Stratum | Scheduled | Card-excluded | Guard failures | Eligible | Astra reference | Astra rewrite | Astra TIE | Astra CANNOT_TELL | Sol reference | Sol rewrite | Sol TIE | Sol CANNOT_TELL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 정책 보도 | 5 | 1 | 3 | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| 공개 문답 | 5 | 0 | 3 | 2 | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 0 |
| 인사 | 5 | 0 | 3 | 2 | 1 | 1 | 0 | 0 | 1 | 1 | 0 | 0 |
| 보조금 | 5 | 0 | 3 | 2 | 1 | 0 | 1 | 0 | 1 | 0 | 1 | 0 |

**Condition B**

| Stratum | Scheduled | Card-excluded | Guard failures | Eligible | Astra reference | Astra rewrite | Astra TIE | Astra CANNOT_TELL | Sol reference | Sol rewrite | Sol TIE | Sol CANNOT_TELL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 정책 보도 | 5 | 1 | 3 | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| 공개 문답 | 5 | 0 | 3 | 2 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 0 |
| 인사 | 5 | 0 | 3 | 2 | 1 | 1 | 0 | 0 | 0 | 2 | 0 | 0 |
| 보조금 | 5 | 0 | 3 | 2 | 1 | 0 | 1 | 0 | 0 | 0 | 2 | 0 |

The per-pair data are in [pairs.csv](../../evals/ko-naturalness-ab/2026-11-16/pairs.csv).

## What this means for Rigorloom

1. For 12 paragraph IDs in each condition, the deterministic guard flagged protected-token differences (numbers, dates, quotations, negations and direction words) between the reference and the final text, although model semantic verification of the draft had passed.
2. The revised stage 2 uses a number-normalized guard comparison, verifies fact cards before generation, and gives the editor findings only.
