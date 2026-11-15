# 공문 End-to-End Demo (`rigorloom demo gongmun`)

`rigorloom demo gongmun` runs a self-contained, Hancom-free end-to-end demo that
fills the blank statutory 기안문 template
(`tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`) from a structured
brief (`examples/gongmun/brief.json`) through `RuntimeCore`, runs
`check_residue` and `check_gongmun`, enforces blocking preservation/fidelity
policies, and writes four verified files to `--out`. Intermediate work stays in
a temporary directory, so `modules/enabled.yaml` in the checkout is untouched
and failures leave `--out` without `filled.hwpx` or `approval.json`.

## Command & Flags

```text
rigorloom demo gongmun --out DIR [--brief FILE] [--form FILE] [--polished FILE] [--deterministic]
```

| Flag | Required | Behavior |
|---|---|---|
| `--out DIR` | Yes | Destination directory for the four output files (written only after all gates pass). |
| `--brief FILE` | No | Brief JSON path (default: `<engine-root>/examples/gongmun/brief.json`). |
| `--form FILE` | No | Blank HWPX template (default: `gianmun-byeolji-1ho.hwpx`). |
| `--polished FILE` | No | Optional `.txt`/`.md` body draft; enables blocking Policy (ii) `draft -> polished` check. |
| `--deterministic` | No | Equivalent to `RIGORLOOM_DETERMINISTIC=1`; pins timestamps, UUIDs, timing fields, and paths for byte-identical output. |

Exit codes:
- `0`: Runtime, `residue`, `gongmun`, Policy (i), and Policy (ii) (if `--polished`) checks all passed.
- `2`: Invalid CLI arguments or unreadable/invalid `--brief`, `--form`, `--polished`, or `--out` (including `> 16` body lines).
- `3`: Refused by `plan_validate`, `plan_apply` / `check_residue`, `check_gongmun`, Policy (i), Policy (ii), or post-check SHA-256 check; nothing is published to `--out`.
- `4`: Missing `engine/`, `pipeline/`, or `modules/gongmun/` prerequisites under `--engine-root`.

## Output Files

- `filled.hwpx`: Filled 기안문 document copied only after candidate SHA-256 re-verification succeeds.
- `plan.json`: Applied `OperationPlan` (`preedit` ops plus `declares.fillMap` and `declares.keep`).
- `verdict.json`: `check_gongmun` verdict plus `guard` metadata (`policy_i`, `policy_ii`, and `paragraphDiff` ordered by `paraIndex`).
- `approval.json`: Human-approval record (`approver: "demo-operator"`, bound to `planId` and `planHash`).

## What the Two Checks Mean

- `residue` (`check_residue`): Verifies via `declares.fillMap` and `declares.keep` that replaced guide terms are gone while static form labels remain intact.
- `gongmun` (`check_gongmun`): Verifies 공문 seat structure against the blank session baseline. Passing requires `hard=0` (`acceptance=true`, `ranAll=true`). In the default output, `warn=1` is `dumun_seat_unfilled` on the optional `(경유)` seat in 두문 (`Table 0 (1,0)`), which intentionally keeps its label with no value.

## Blocking Policies

### Policy (i): `form -> filled` Preservation & Completeness

Always enforced before publication (exit `3` on failure):

1. **Brief Value Verbatim Presence**: Every non-empty leaf string in `brief.json` appears verbatim in the extracted `<hp:p>` text of `filled.hwpx`, and cleared seats (`접수번호`, `비고`) hold `""`.
2. **Untouched Paragraph Byte-Identity**: Across `Contents/section*.xml`, paragraph count and leaf structure match the blank template, every untouched leaf `<hp:p>` (including `<hp:linesegarray>` and attributes) is byte-identical, and wrapper prefixes/suffixes and non-section ZIP members are unchanged.

### Policy (ii): `draft -> polished` Fidelity

Enforced when `--polished FILE` is supplied (exit `3` on failure), without altering `filled.hwpx`:

1. **`prose_fidelity.audit_text(draft, polished)`**: Rejects ungrounded or altered `numbers` (with units), `dates`, `source_ids`, `citations`, `tags`, `inline_math`, `direct_quotes`, `urls`, `markdown_links`, `headings`, `qualifiers`, `quantifiers`, `causal_markers`, or `direction_words`.
2. **Ungrounded Quotes & Entities**: Rejects newly introduced quoted spans (`'...'`, `「...」`, `『...』`, `《...》`) or ASCII/Latin identifiers (`[A-Za-z][A-Za-z0-9_-]{1,}`) absent from the brief.
3. **Forbidden Claims**: Rejects prohibited accuracy guarantees, vendor model attributions, and detection-evasion/humanizer claims (case- and whitespace-normalized).

## How to Run the Tests

```sh
python -m pytest tests/test_demo_gongmun.py -q
```

In-process refusal tests use `rt_demo_gongmun.post_plan_hook_context` to inject post-plan brief drift, deleted seats, non-seat XML/lineseg mutations, or candidate SHA-256 mismatches and verify exit `3` with no files published to `--out`.
