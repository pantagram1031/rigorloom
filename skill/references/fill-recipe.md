# Filling a mixed-storage form — the canonical recipe

One worked end-to-end fill of a real form, from blank `.hwpx` to
`acceptance: true`. Follow it in order. `references/operations.md` is the
per-CLI contract reference; this file is the sequence, and it is the only
account of **which command each cell takes**.

Why it exists: three independent harnesses filling the same 조달청 협업승인
신청서 chose three different strategies for the *same* cell, and one of them
built three separate maps (one to edit with, one for the checker, one for the
residue gate) because nothing said they were one file. Both are decisions this
document makes for you.

Worked form: the 조달청 협업 승인 신청서 (우수조달물품 지정관리 규정 별지
제2호의7서식) — one page, one table, 19 empty cells. Every number and every
JSON fragment below is from an actual run against it, not an illustration.

---

## 1. The decision rule

Read `table_map` from the profile. Every cell you intend to write takes
exactly one of four branches, decided by **what the cell already stores**:

| the cell stores | command | why |
|---|---|---|
| **a genuinely empty run** — `classification: fill_target`, `<hp:run charPrIDRef="N"/>` with no `<hp:t>` | `preedit fill-cells --cell ROW,COL=값` | there is no string to key on, so a text-keyed `replace` structurally cannot reach it (T27) |
| **a printed skeleton you must KEEP**, blank at the end — `" http://"`, `" 우(     -     )"` | `preedit replace --at-cell-append 'ROW,COL=값'` | the label is a prefix of the value; keeping it is the normal shape of a labeled field, not an edge case (T31) |
| **printed text to be wholly REPLACED** — a template whose blanks are *interior*, like a date skeleton | `preedit replace --at-cell 'ROW,COL=값'` | appending would leave the empty template printed in front of the real value |
| **several text runs** | the refusal tells you: re-issue as `ROW,COL#RUN` | `exit 2`, `at_cell_run_ambiguous`, with every run's index and exact text. Neither "first run wins" nor "flatten the cell" is offered |

`classification: spacer` is a fifth answer: **do not write there at all.** It
is an empty cell the grid needs — a separator band or a matrix stub head — and
it is already excluded from `fill_target_count` (operations.md §2). On this
form 6 of the 19 empty cells are spacers.

Two rules that are not optional:

- **Never key a decision on `text_preview`.** It is `text[:30]` and it says
  when it cut (`truncated: true`). Read the seat with
  `form_inspect --full-text ROW,COL` before you choose a branch.
- **Address, never reconstruct.** `--at-cell*` keys on the `cellAddr`, so you
  never have to retype a seat's invisible internal spacing.

### The worked example: 협업기간 (11,2) — the cell that fractured

`table_map` previews it as `"20   .    .    .  ~  20   .   "`, truncated. The
30-char cut lands *inside* the skeleton and hides its second half. Ask for the
whole thing:

```
python engine/scripts/form_inspect.py FORM.hwpx --full-text 11,2
```

```
runs: [{"index": 0,
        "text": "20   .    .    .  ~  20   .    .    .   (     개월)"}]
```

**Branch: `--at-cell` (whole-run replace).** One run, so no `#RUN`. The seat is
a *template*, not a prefix: its blanks sit between `20`/`.`/`~` and inside
`(     개월)`. There is no "type into the middle" mode and there should not be
— so appending would render
`20   .    .    .  ~  20   .    .    .   (     개월)2026. 3. 1. …`, the empty
template still printed in front of the answer. You write the finished string
over the whole run, and the form's typography (`. . . ~ . . . (…개월)`) is
reproduced *by your value*:

```
--at-cell '11,2=2026. 3. 1. ~ 2027. 2. 28. (12개월)'
```

This is the field the three harnesses disagreed on — split literal replace,
whole-cell overwrite, partial skeleton — because each saw a different amount
of the seat. `--at-cell-expect '11,2=개월'` is the cheap proof that you saw all
of it: it compares with **all whitespace removed on both sides**, so the
assertion is `개월`, not a space count, and a mismatch writes nothing.

Contrast, same form, same command family:

- (4,3) 주소 `" 우(     -     )"` → `--at-cell-append`. The 우편번호 skeleton
  is *printed stationery* the recipient expects to see; the address goes after
  it.
- (5,3) 홈페이지 `" http://"` → `--at-cell-append`. Same shape.
- (15,0) 신청일 → multi-run cell. The refusal lists 8 runs; the 신청일 line is
  run 2, so `--at-cell '15,0#2=…'`. Guessing "first run" would have deleted the
  regulation sentence.

---

## 2. The artifacts, and exactly which flag eats each one

There are **four** files. Not five, and in particular not three maps.

| artifact | produced by | consumed by |
|---|---|---|
| `profile.json` | `form_inspect --out profile.json` | `visual_verify --form-profile` (which forwards it to `check_residue`), and your own reading |
| `baseline.json` | `form_inspect --baseline baseline.json` | `style_diff --baseline` (format-drift proof; optional) |
| `fill.json` — **the one map** | you write it | `visual_verify --fill-map` **and** `--expectations` (same file, twice — the blessed invocation), and any module checker's `--fill-map` |
| `form.hwpx` — the blank | the form itself | `visual_verify --baseline` (pixel diff; it converts the blank for you) |

The edits themselves are **CLI flags**, not a file: `--cell`, `--at-cell`,
`--at-cell-append`. If you find yourself writing a second map, stop — you are
about to rebuild the split that T35/T36 already cost two clean-room retries.

`fill.json` is the wrapper shape, so one file carries the map, the page count
and the blank declarations:

```json
{
  "schema": "rigorloom/fill-declaration/v1",
  "pages_document": 1,
  "fill_map": {
    "2,3": "한빛정밀(주)",
    "2,7": "110111-0001234",
    "10,2": "고정밀 서보 감속기",
    "14,2": "대한기계(주)",
    "20   .    .    .  ~  20   .    .    .   (     개월)":
        "2026. 3. 1. ~ 2027. 2. 28. (12개월)",
    "우(     -     )": "우(     -     )서울특별시 강남구 테헤란로 123",
    "http://": "http://hanbit.example.kr",
    "년      월      일": "2026 년   3 월   2 일"
  },
  "declared_blank": ["사업자등록번호", "(서명 또는 인)"]
}
```

**How to key it — this is the part that bites.** A `fill_map` key means *text
the fill CONSUMED*, because that is what the residue keep derivation reads it
as: a key matching a form anchor removes that anchor from the keep list, on the
theory that the label survives *inside* the value (T31).

- For a **seat** you rewrote or appended to, the key is the **seat text** —
  `"20   .    .    .  ~  20   .    .    .   (     개월)"`, `"http://"`. That is
  exactly the string `--full-text` handed you.
- For a **`fill-cells` target**, nothing was consumed: the label lives in a
  *different cell* and must survive. Key it by the **cell address**,
  `"2,7"`. Key it by its label instead and the derivation drops that label from
  the keep list, and the gate then HARDs on the form's own printed label —
  measured on this form: keying 협업기간 by `"협 업 기 간"` produces
  `form_residue: 협 업 기 간`, a failure on a perfectly correct fill.

`declared_blank` is how you say *"I left this blank on purpose"* — the
signature line, a staff-only box, a field you have no value for. Without it,
`empty_cell_expected_fill` fires on a correct run. It is also accepted inside
`expectations` under the older name `intentionally_blank`; both fold into one
list and the verdict records which surface each came from.

---

## 3. The command sequence

Every path below is literal. `FORM.hwpx` is the blank; `W` is your work
directory.

**0. Before any COM call, check nothing else owns Hancom.** The convert step
is serial and must never use `--kill-stale`, which would kill another
session's live instance (T21):

```
tasklist /FI "IMAGENAME eq Hwp.exe"
```

Expect `INFO: No tasks are running...`. If an `Hwp.exe` is listed and it is not
yours, wait — do not kill it.

**1. Profile the blank.**

```
python engine/scripts/form_inspect.py $W/form.hwpx \
    --out $W/profile.json --baseline $W/baseline.json
```

```
anchors=29 guide_text=1 body_baseline_charpr=7
script_anomaly_targets=1 fill_target=13 spacer=6
```

Read `script_anomaly_targets` now: it is the T30 pre-flight. Here it names
(10,2) with `charpr_suggested: "7"` — its empty run carries body formatting
*plus* `<hh:supscript/>`, and a fill that inherited it would render ~6.35pt
raised while every height-based proof passed.

**2. Read the seats you are about to edit** (per-cell opt-in; do not read
`section0.xml`):

```
python engine/scripts/form_inspect.py $W/form.hwpx \
    --full-text 11,2 --full-text 4,3 --full-text 5,3 --full-text 15,0
```

**3. Fill the empty cells** — one call, all of them, with the pre-flight's
suggestion. Omit `--charpr-per-cell` and the command refuses (exit 3) rather
than producing the raised fill:

```
python engine/scripts/preedit.py fill-cells $W/form.hwpx --out $W/step1.hwpx \
    --cell "2,3=한빛정밀(주)"      --cell "2,7=110111-0001234" \
    --cell "6,3=김한빛"            --cell "7,3=이서준" \
    --cell "7,7=02-1234-5678"      --cell "8,3=기술연구소/책임" \
    --cell "8,7=02-1234-5679"      --cell "10,2=고정밀 서보 감속기" \
    --cell "14,2=대한기계(주)"     --cell "14,4=박정우" \
    --cell "14,5=031-777-0101"     --cell "14,8=경기도 시흥시 산단로 12" \
    --charpr-per-cell 10,2=7
```

→ `{"ok": true, "filled": 12, ...}`.

**4. Write the printed seats** — a second call, because `--map` and
`--at-cell*` in one invocation is a usage error (address offsets and string
replacement would rewrite each other):

```
python engine/scripts/preedit.py replace $W/step1.hwpx --out $W/filled.hwpx \
    --at-cell        "11,2=2026. 3. 1. ~ 2027. 2. 28. (12개월)" \
    --at-cell        "15,0#2=                                          2026 년   3 월   2 일" \
    --at-cell-append "4,3=서울특별시 강남구 테헤란로 123" \
    --at-cell-append "5,3=hanbit.example.kr" \
    --at-cell-expect "11,2=개월"    --at-cell-expect "4,3=우(-)" \
    --at-cell-expect "5,3=http://"  --at-cell-expect "15,0#2=년월일"
```

→ `{"ok": true, "replaced": 4, ...}`, and each cell reports its `before`
(the seat's exact text) and `after`.

**5. Write `fill.json`** (§2).

**6. Convert to PDF.** One serial call, never `--kill-stale`:

```
python engine/scripts/com_backend.py convert \
    --file $W/filled.hwpx --to $W/filled.pdf
```

→ `{"ok": true, "converted": "...filled.pdf"}`. You may skip this step and let
`visual_verify` do the conversion itself — it runs the identical command — but
then re-running pass 2 re-converts, so converting once here and passing
`--pdf` to both passes is cheaper. With no Hancom on the machine, render on the
operator machine and bring the PDF; a verification loop that cannot render must
not report a pass.

**7. Verify, pass 1 — the machine half.** Note the one map on **both** flags:

```
python pipeline/scripts/visual_verify.py \
    --artifact $W/filled.hwpx --pdf $W/filled.pdf \
    --form-profile $W/profile.json \
    --fill-map $W/fill.json --expectations $W/fill.json \
    --baseline $W/form.hwpx \
    --out $W/visual_verdict.json
```

Exits **3** with `verdict: vision_pending` when the machine half is clean —
that is the expected result of pass 1, not a failure. It prints the pages you
owe under `vision_required`.

**8. Read the pages.** Open each PNG in `vision_required[].png` and judge it
against `references/visual-rubric.md` — a closed class vocabulary; an invented
class is a usage error, not a finding. Write the handback:

```json
{
  "schema": "rigorloom/visual-vision-verdict/v1",
  "pages_reviewed": [1],
  "findings": []
}
```

Every page listed in `vision_required` must appear in `pages_reviewed`.

**9. Verify, pass 2 — merge the handback.** Same flags plus
`--vision-verdict`:

```
python pipeline/scripts/visual_verify.py \
    --artifact $W/filled.hwpx --pdf $W/filled.pdf \
    --form-profile $W/profile.json \
    --fill-map $W/fill.json --expectations $W/fill.json \
    --baseline $W/form.hwpx \
    --vision-verdict $W/vision.json \
    --out $W/visual_verdict.json
```

---

## 4. What a correct run looks like

Exit **0**, and the verdict says all of this:

```json
{
  "verdict": "pass",
  "acceptance": true,
  "acceptance_waivers": [],
  "acceptance_blockers": [],
  "counts": {"hard": 0, "warn": 0},
  "deterministic": {
    "safety_checks": ["page_parity", "xml_wellformedness", "check_residue",
                      "empty_cell_expected_fill",
                      "fill_charpr_script_mismatch"],
    "skipped_checks": ["format_noncompliance/base_pt",
                       "format_noncompliance/line_spacing",
                       "format_noncompliance/margins",
                       "page_budget_violation"],
    "pages_document_source": "expectations",
    "fill_map_source": "cli+expectations",
    "declared_blank": ["사업자등록번호", "(서명 또는 인)"],
    "declared_blank_source": ["expectations.declared_blank",
                              "fill_map.declared_blank"]
  }
}
```

Read it as five separate claims, and check each:

1. **`acceptance: true` with `acceptance_blockers: []`** — every SAFETY check
   RAN. `true` with a non-empty blockers list is impossible; a SAFETY check
   that could not run gives `verdict: safety_incomplete`, exit 3.
2. **`acceptance_waivers: []`** — nothing was excused. A waiver
   (`--accept-without CHECK`) is legitimate but it is a *partial*: the run
   accepted without proving that check.
3. **`skipped_checks` intersected with `safety_checks` is empty.** The four
   above are tolerance legs and a budget nobody declared — declining to pin a
   tolerance is not hiding a defect class. A skipped SAFETY check is a
   different animal entirely.
4. **`pages_document_source` is named** — `conversion` (Hancom's own
   `PageCount`, when this script did the convert), `expectations` (you declared
   it), or `artifact_layout_cache` (derived from the artifact's own lineseg
   cache, and honest about under-counting). Absent means page parity did not
   run.
5. **`fill_map_source: cli+expectations`** — one map, both surfaces, agreeing.
   `cli` or `expectations` alone is fine; two *different* maps is a usage
   error, because there is no honest answer to which one the artifact was
   filled with.

And two things that should be *empty but present*: `hard: []` and, on this
form, `warn: []`. If you see `empty_cell_expected_fill` in `warn`, read its
`seat` — it names the label, not a coordinate — and either fill it or add it to
`declared_blank`. Blanks the grid owns are already suppressed and listed under
`deterministic.layout_qa.empty_cell_suppressed` with their reason.

**Partial results, so you can tell them from success:**

| what you see | what it means |
|---|---|
| exit 3, `vision_pending` | pass 1 finished; you still owe the page reading |
| exit 3, `safety_incomplete` | nothing failed, but a SAFETY check never ran — supply the missing input or waive it on the record |
| exit 0, `deterministic_pass` | `--deterministic-only`; `acceptance: false` by construction. A smoke check, never an acceptance |
| exit 0, `pass`, non-empty `acceptance_waivers` | accepted, minus whatever you waived |
| exit 2, `usage_error` | bad input; nothing was judged |
