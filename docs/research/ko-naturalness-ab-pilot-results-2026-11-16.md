# Korean naturalness A/B pilot results, 2026-11-16

The pilot could not measure naturalness. In each condition, 12 of 20 outputs failed the reference-to-final guard while passing the draft-to-final guard, so only 7 pairs per condition were eligible. Most drafts were left unchanged: 13 of 20 in condition A and 19 of 20 in condition B. One fact card failed verification.

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

Dates run from 2015-08 to 2019-12.

Every role was a model and no human took part.

The judges are from the same model family as the generator.

The corpus is a convenience sample, and publication age does not prove authorship. The `checker_doc_type` field maps each stratum to a checker type, not a genre. The protocol and run lock are in [the protocol](ko-naturalness-ab.md). Run artefacts, including the index, ledger and unblinded records, live at `/home/ubuntu/hub/ax/rl-swarm-run/out/phase3/wp7/` on the server.

## What this means for Rigorloom

1. Fact-card drafts drifted in protected tokens (numbers, dates, quotations, negations and direction words); the model verifier did not catch this while the deterministic guard did.
2. The revised stage 2 uses a number-normalized guard comparison, verifies fact cards before generation, and gives the editor findings only.
