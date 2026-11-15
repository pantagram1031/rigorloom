# 공문 End-to-End Demo (`rigorloom demo gongmun`)

`rigorloom demo gongmun` runs a self-contained, Hancom-free, engine-install-free
end-to-end demonstration that fills a blank statutory 기안문 template
(`tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`) from a structured
brief (`examples/gongmun/brief.json`) through the Runtime domain layer, checks it
against both `check_residue` and `modules/gongmun/scripts/check_gongmun.py`,
enforces blocking preservation/fidelity policies, and publishes four verified
artifacts to `--out`.

The command is clean-clone safe: it never mutates the blank corpus form, never
writes `modules/enabled.yaml` in the checkout, and stages all intermediate work
in a temporary directory so any failure leaves `--out` free of unverified
outputs.

---

## Command & Flags

```text
rigorloom demo gongmun --out DIR [--brief FILE] [--form FILE] [--polished FILE] [--deterministic]
```

| Flag | Required | Default / Behavior |
|---|---|---|
| `--out DIR` | Yes | Destination directory for `filled.hwpx`, `plan.json`, `verdict.json`, `approval.json` (published only after all gates pass). |
| `--brief FILE` | No | Defaults to `<engine-root>/examples/gongmun/brief.json`. |
| `--form FILE` | No | Defaults to `<engine-root>/tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`. |
| `--polished FILE` | No | Optional polished body draft file (`.txt`/`.md`); when supplied, runs blocking Policy (ii) `draft -> polished` audit. |
| `--deterministic` | No | Equivalent to `RIGORLOOM_DETERMINISTIC=1`. Pins timestamps, UUIDs, timing fields, and staging path strings so outputs are byte-identical across runs. |

---

## Exit Codes & Staging Guarantee

| Exit Code | Meaning | `--out` Guarantee |
|---|---|---|
| `0` | All Runtime, residue, `check_gongmun`, Policy (i), and Policy (ii) (if `--polished`) checks passed. | Writes `filled.hwpx`, `plan.json`, `verdict.json`, and `approval.json`. Prints concise path-independent summary to stdout. |
| `2` | CLI usage error or invalid/missing/unparseable `--brief`, `--form`, `--polished`, or `--out` path. | Writes nothing (`filled.hwpx` and `approval.json` are absent). |
| `3` | Refused by gate or blocking policy (`plan_validate`, `plan_apply` / `check_residue`, `check_gongmun`, Policy (i), or Policy (ii)). | Staging stays in temp dir only; **no `filled.hwpx` or `approval.json` is written to `--out`**. |
| `4` | Unexpected environment or internal error (e.g., missing `engine/` or `modules/gongmun` in checkout/engine root). | Writes nothing (`filled.hwpx` and `approval.json` are absent). |

---

## Architecture & Runtime Pipeline

1. **Input validation & temporary staging**
   - Resolve `--out`, `--brief`, `--form`, optional `--polished`, and `engine_root`.
   - Load and validate the brief JSON structure (including enforcing `<= 16` paragraphs in `Table 0 (2,0)`).
   - Create an isolated temporary staging root (`runtime/`, `enabled.yaml`, `out/`).
   - Write `enabled.yaml` inside the temporary staging dir (`schema: rigorloom-enabled-modules/v1`, `enabled: [gongmun]`) and temporarily bind `RIGORLOOM_MODULES_ENABLED` (and `RIGORLOOM_MODULES_ROOT` when resolving under `engine_root`) inside a `try/finally` block, restoring environment variables afterwards. `modules/enabled.yaml` in the repository is never touched.

2. **Runtime lifecycle (`RuntimeCore`)**
   - `open_path(form)` copies the blank template into the temporary session.
   - Construct the explicit `OperationPlan` (`ops` + `declares`) for 별지 제1호서식 (`preedit` backend).
   - `plan_propose` -> `plan_validate` -> `approval_request` -> `approval_resolve(decision="approved", approver="demo-operator")` -> `plan_apply`.
   - `plan_apply` chains `preedit` subcommands (`replace-at-cell`, `fill-cells`) and runs `check_residue.py` via `visual_verify.derive_form_keep`.
   - `module_check(session_id, "gongmun", run_id=run_id)` runs `check_gongmun.py` with the staged `enabled.yaml` against both the candidate and the session baseline.
   - Verify `verdict["ranAll"] is True`, `verdict["acceptance"] is True`, `verdict["counts"]["hard"] == 0`, and `verdict["subject"]["sha256"] == sha256(candidate)`.

3. **Seat Mapping (`gianmun-byeolji-1ho.hwpx`)**
   All edits target measured addresses in `Contents/section0.xml`:
   - `Table 0 (0,0)` runs `0..3` (`[별지 제1호서식]` and blue `<개정 ...>` guide target): cleared to `""` via `replace_at_cell`.
   - `Table 0 (1,0)` 두문:
     - run `0` (`행 정 기 관 명`, `charPr="12"`): replaced with `brief["기관명"]` keeping `charPr="12"`;
     - run `1` (`수신`, `charPr="14"`): replaced with `brief["수신"]` keeping `charPr="14"`;
     - run `2` (`(경유)`): **left untouched** (byte-identical to blank form);
     - run `3` (`제목 `, `charPr="14"`): replaced with `brief["제목"]` keeping `charPr="14"`.
   - `Table 2 (0,0)` (`발신명의`, `charPr="8"`): replaced with `brief["발신명의"]` keeping `charPr="8"`.
   - `Table 0 (4,0)`, `(4,3)`, `(4,9)` (`결재란`): replaced with `brief["결재"]` (`기안자`, `검토자`, `결재권자`).
   - `Table 0 (6,1)` (`시행번호`): replaced with `brief["시행번호"]` (`과명-일련번호(시행일)`).
   - `Table 0 (6,8)` (`접수번호`): replaced with `brief["접수번호"]` (`""`).
   - `Table 0 (7,0)`, `(7,1)`, `(7,7)`: replaced with `우`/`우편번호`, `도로명주소`, `홈페이지`.
   - `Table 0 (8,0)`, `(8,2)`, `(8,7)`, `(8,12)`: replaced with `전화번호`, `팩스번호`, `이메일` (`@example.com`), `공개구분`.
   - `Table 0 (10,0)` (`비고`, runs `0..2`): cleared (`brief["비고"]` + `""`).
   - `Table 0 (2,0)` (`본문` + `붙임`): applied **last** via `fill_cell` with `charPr="14"`, `paraPr="18"`, `<= 16` lines, preserving nested `Table 1` (`직인`) and `Table 2` wrapper paragraphs intact. Applying `fill_cell` after footer replacements preserves the blank form's `charPr="23"` baseline during `replace-at-cell` prechecks.
   - `declares.fillMap` binds every filled anchor label (using `"other_occurrences": "seats"` where an anchor is a substring of another anchor such as `"시행"` / `"접수"`), and `declares.keep` preserves the static/prefix labels `["(경유)", "직인", "협조자", "시행", "접수", "우", "/", "210㎜×297㎜(백상지 80g/㎡)"]` (so ordinary Hangul prose containing `"우"` such as `"우리"` is not flagged as single-syllable residue while Policy (i) still verifies `Table 0 (7,0)#0` verbatim).

---

## Blocking Policies

### Policy (i): `form -> filled` Preservation & Completeness (Always Enforced)

Both invariants must hold on the staged candidate `filled.hwpx` before any output
is published; any violation blocks with exit `3`:

1. **Brief Value Verbatim Presence**: Every non-empty leaf string value in `brief.json` appears verbatim in the extracted `<hp:p>` text of `filled.hwpx`. Empty strings (`""` for cleared seats such as `접수번호` and `비고`) must not introduce new unexpected content, and the cleared seat paragraphs must hold `""`.
2. **Untouched Paragraph Byte-Identity**: `engine/scripts/preedit.py` (`_replace_in_paragraph`, `_edit_cell_runs`, `_fill_cell_body`) strips `<hp:linesegarray>` only on modified paragraphs and copies untouched paragraphs verbatim. Policy (i) parses `<hp:p>` spans from `Contents/section*.xml` of both the blank template and `filled.hwpx`, maps the plan's `ops` to the exact set of touched leaf paragraphs (targeted cell runs and `Table 0 (2,0)` fill-slot paragraphs before nested tables), and asserts:
   - equal paragraph count across sections;
   - **exact XML byte equality** for every leaf `<hp:p>` outside the plan's touched seats (including `<hp:linesegarray>` and run/paragraph attributes);
   - exact byte equality for non-child wrapper prefixes/suffixes of container paragraphs (`p[0]` around Table 0, `p[30]` around Table 2) and non-section XML/binary package members (`Contents/header.xml`, etc.).

### Policy (ii): `draft -> polished` Fidelity (Enforced When `--polished FILE` Is Given)

When `--polished FILE` is supplied, Policy (ii) compares the draft body text from
`brief.json` (`본문` lines plus optional `붙임`) against the polished text,
blocking with exit `3` if any of the following fail:

1. **`modules/style/scripts/prose_fidelity.py` `audit_text(draft, polished)`**: Rejects any ungrounded or altered `numbers` (with units), `dates`, `source_ids`, `citations`, `tags`, `inline_math`, `direct_quotes`, `urls`, `markdown_links`, `headings`, `qualifiers`, `quantifiers`, `causal_markers`, or `direction_words`.
2. **Additional Ungrounded Quotes & Entity Tokens**: Rejects newly introduced quoted spans (`'...'`, `「...」`, `『...』`, `《...》`) or ASCII/Latin entity identifiers (`[A-Za-z][A-Za-z0-9_-]{1,}`) absent from the brief.
3. **Forbidden Claims**: Rejects prohibited promotional accuracy guarantees, vendor model attributions, and detection-evasion/humanizer claims (including whitespace-normalized and case-insensitive variants).

Policy (ii) acts as a draft-to-polished verification gate on `--polished FILE` without altering the brief values written into `filled.hwpx` (so Policy (i) verbatim brief checks always remain invariant).

### Guard Metadata in `verdict.json`

While preserving all top-level `RuntimeCore.module_check` fields (`acceptance`, `ranAll`, `counts`, `checks`, `subject`, `baseline`, etc.), the published `verdict.json` also records a deterministic `guard` object summarizing both blocking policies and the paragraph diff:

```json
{
  "ok": true,
  "policy_i": {
    "ok": true,
    "policy": "form->filled",
    "briefValuesChecked": 23,
    "allBriefValuesVerbatim": true,
    "touchedLeafParagraphs": 28,
    "untouchedLeafParagraphs": 36,
    "untouchedBytesIdentical": true,
    "paragraphDiff": [{"paraIndex": 1, "before": "...", "after": "..."}]
  },
  "policy_ii": {
    "status": "pass | skipped",
    "ok": true,
    "policy": "draft->polished",
    "fidelityOk": true
  },
  "paragraphDiff": [{"paraIndex": 1, "before": "...", "after": "..."}]
}
```

- `paragraphDiff` lists every touched `Contents/section0.xml` leaf paragraph whose text changed, ordered by `paraIndex` (`fidelityOk` is present when `--polished FILE` runs and passes).

---

## Determinism (`--deterministic` / `RIGORLOOM_DETERMINISTIC=1`)

When `--deterministic` is passed or `RIGORLOOM_DETERMINISTIC=1` is set:

- `now_utc()` across `rt_session`, `rt_plan`, `rt_apply`, and `rt_apply_once` is fixed to `"2026-11-15T00:00:00Z"`.
- `uuid.uuid4()` returns deterministic sequential UUID4-formatted identifiers derived from a fixed counter namespace (`rigorloom-demo-gongmun`).
- If input `.hwpx` zip entries lack normalized zip metadata, a normalized copy (`date_time=(1980, 1, 1, 0, 0, 0)`, fixed external permissions) is staged before `open_path` (when already normalized, as `gianmun-byeolji-1ho.hwpx` is, the original bytes and SHA-256 are preserved identically).
- In `verdict.json`, volatile execution fields are normalized: `durationMs` is set to `0`, staged `enabledFile` is recorded as `"enabled.yaml"`, and `modulesRoot` under `engine_root` is recorded as `"modules"`.
- Running `rigorloom demo gongmun --out DIR --deterministic` twice into distinct `--out` paths produces byte-identical `filled.hwpx`, `plan.json`, `verdict.json`, and `approval.json`, and identical stdout.

---

## Testable Python Hook Interface

To keep `rigorloom demo gongmun --help` free of test-only CLI flags while allowing
in-process tests calling `cli.main` to inject post-plan faults cleanly,
`runtime/scripts/rt_demo_gongmun.py` provides:

- `post_plan_hook_context(hook_fn)`: context manager setting the module hook around `cli.main(...)` calls.
- `hook_fn(ctx)` is invoked after `plan_apply` and `module_check`, immediately before Policy (i), Policy (ii), candidate SHA-256 re-verification, and atomic publication to `--out`.
- `ctx` exposes mutable `brief`, `candidate_path` (staged HWPX), `form_path`, `plan`, `approval`, and `verdict`, enabling tests to inject:
  1. post-plan `brief` value changes;
  2. deleted seat values in `candidate_path`;
  3. modified non-seat paragraphs (including `<hp:linesegarray>` changes) in `candidate_path`.
