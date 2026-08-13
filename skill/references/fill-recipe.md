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
| **an empty run in a cell that must hold several lines** — a 공문 본문, a multi-item 내용 box | `preedit fill-cells --cell-line ROW,COL=… --cell-line ROW,COL=…` (once per paragraph) | one paragraph per line is the *regulated* shape of 공문 본문, not a formatting preference (T39); see §1.2 |

Some families are not grids at all. In 계약·인사 서식 almost everything lives in
**top-level paragraphs** (`2. 근 무 장 소 : `), so there is no `cellAddr` to
address and the branch is:

| the paragraph | command | why |
|---|---|---|
| **carries a clause line that occurs once in the document** | `preedit replace --map` with a plain string value | nothing to disambiguate; unchanged behaviour |
| **carries a line the form prints on several sheets** — a variant pack, 6 contracts in one file | the refusal tells you: re-issue as `{"text": 값, "at_para": N}` | `exit 2`, `replace_key_ambiguous`, with every occurrence's `at_para` and recent prior context including the variant title. Silently writing all of them destroyed the sibling sheets and no offline gate saw it (T41) |
| **must change on every sheet** (deleting a clause from the whole pack) | `{"text": 값, "all_occurrences": true}` | every-occurrence is a decision you state, not a default |
| **is reachable through Hancom and you want the first sheet only** | `com_backend edit` `goto_text` / `find_delete` | both hard-reset to `MoveDocBegin()` before searching, so "first occurrence" is a defined contract — this is the scoping mechanism for paragraph packs, not a `.hwp`-only heavy backend |

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

### 1.1b `script_anomaly: false` says nothing about colour (T127)

`script_anomaly` compares five charPr properties — `supscript`, `subscript`,
`ratio`, `relSz`, `offset`. Colour is not one of them, and before T127 nothing
in the pre-flight looked at colour at all. So a fill that inherits a guide-blue
run reported `script_anomaly: false`, which the field docs define as *checked
and clean*, and shipped text that reads as a form hint rather than an answer.

Read **`color_anomaly`** as well. Same three states: `true` = the inherited run
is not black/auto, `false` = checked and it is, `null` = could not judge. It is
decided by the same predicate that classifies a run as `guide_text`
`reason: "colored"`, so the pre-flight cannot promise something the post-flight
then contradicts. Colour needs no baseline, so it is judged even on a document
whose `script_anomaly` is `null`.

**Do not reach for `charpr_suggested` to fix a colour.** That field is the body
baseline, and the body baseline can itself be coloured. On the kstartup form it
is: guide blue is concentrated in one charPr carrying 378 characters while black
prose is spread across 144 ids whose heaviest carries 323, so blue wins the
maximum even though black is 72% of the document's body weight. Recommending the
baseline there re-ships the bug.

Use the profile-level **`body_black_charpr`** instead. It applies the same
heaviest-run rule to black/auto runs only, and prefers one at the *same nominal
height* as the baseline — swapping a 10pt blue seat for a 12pt black one fixes
the colour and breaks the size. `same_height_as_baseline` says whether that
preference was satisfiable; if it is `false`, the id still fixes the colour but
you are changing the size too, so decide deliberately.

### 1.1 `script_anomaly` is a *question*, not a verdict — and the usual answer is "the form designed it that way"

A `script_anomaly` says only *this cell's charPr differs from the body baseline
on one of five properties*. Two different things produce that, and they take
opposite actions:

| what it is | how it looks | what to pass |
|---|---|---|
| **a T30 trap** — the fill inherits body formatting *plus* a script/scale/offset modifier | `differing` is `supscript`/`subscript`/`offset`, or a `relSz` shrink; `nominal_height_pt` **equals** the baseline; `rendered_pt_estimate` is well below it | `--charpr-per-cell ROW,COL=<charpr_suggested>` — normalize to body |
| **the form's own typography** — a label, or a 본문 area the 서식 deliberately sets at another size or width | `differing` is a small `ratio` delta; `nominal_height_pt` **differs** from the baseline; the same charPr is already used by *printed* text in the blank form | `--charpr-per-cell ROW,COL=<that cell's own charpr>` — keep the design, explicitly |

The two numbers the refusal prints side by side are what separates them: a trap
keeps the baseline's nominal height and loses rendered height; a design decision
has a different nominal height to begin with.

**Worked example — the 기안문 별지 제1호서식.** Its body baseline is charPr
**23: 10pt, ratio 100%**, which is the *fine print* — the 비고 block and the
210㎜×297㎜ line carry the most characters on the page, so they win the
character-count weighting. Every visible field on the form is a different,
larger id:

```
charPr 12  16pt  ratio 97%   행정기관명
charPr 13  13pt  ratio 97%   두문 spacer line
charPr 14  12pt  ratio 97%   수신 / (경유) / 제목 labels, and the 본문 cell (2,0)
charPr 15  14pt  ratio 97%   제목 value
charPr 23  10pt  ratio 100%  ← body baseline (비고 fine print)
```

So `form_inspect` reports exactly one `script_anomaly_target`, (2,0), with
`charpr: "14"`, `differing: ["ratio"]`, `charpr_suggested: "23"`,
`nominal_height_pt: 12.0` against `baseline_height_pt: 10.0`. Pasting the
suggested flag would set the 본문 to the fine print's 10pt/100%. The 97% ratio
is the whole form's design — it is on the 행정기관명 title and every 두문 label
in the **untouched blank** — and the nominal heights differ, so this is the
second row of the table. Pass the cell's own id, and say why:

```
--charpr-per-cell 2,0=14        # the form's 12pt/97% 본문 face, not the 비고 face
```

The refusal is still right to fire. What is *not* acceptable is pasting
`suggested_flags` unread: on this form that silently reformats the 본문 to fine
print.

**The post-flight answers this for you, if you pass the blank form (T40).**
`visual_verify`'s `fill_charpr_script_mismatch` compares the same five
properties, so on its own it would flag every seat on this form — the seats are
97% and the body baseline is the 비고 face at 100%. With `--baseline
$W/form.hwpx` (which §3 step 7 already passes, for the pixel diff) it reads the
blank form's XML too and compares each filled run against **the blank run named
by the fill-map key in the same seat**, addressed by its `cellAddr`. For an
exact `ROW,COL` key whose seat has no visible text, it can instead prove the
form's typography from a repeated reserved-run block: at least two empty runs,
one shared charPr, an exact match to the fill, and no body difference except
`ratio` (T42). An
unrelated sibling run in a multi-run cell can never excuse the fill. A
signature the printed form
already had is then a WARN, `fill_charpr_script_inherited`, naming the seat and
the blank form's charPr — the fill introduced nothing, so there is nothing to
waive. `--accept-without fill_charpr_script_mismatch` on a gongmun fill is a
sign the baseline is missing, not a step in the recipe.

What still HARDs, with the baseline in hand:

| the seat, in the BLANK form | verdict |
|---|---|
| already carries this exact signature | WARN `fill_charpr_script_inherited` — read the render once to confirm the seat is legible, then move on |
| carries a *different* signature | HARD — the fill changed the seat's typography |
| exact `ROW,COL` key; at least two reserved empty runs with one matching charPr that differs from body only by `ratio` | WARN `fill_charpr_script_inherited` — the form reserved that typography (T42) |
| one empty run, mixed reserved charPr ids, a changed signature, or a reserved script/scale/offset anomaly | HARD — repetition did not prove safe inheritance |
| not available — no `--baseline`, or a `.pdf`/image-directory baseline | HARD, and the finding says so: `form_baseline_checked: false` plus the reason. The check does not weaken when it cannot see the form |

### 1.2 A multi-line cell: the 공문 본문 (T39)

`행정업무의 운영 및 혁신에 관한 규정 시행규칙` makes 공문 본문 hierarchical —
`1.`, then `가.`, then `1)`, then `가)`, each level its own paragraph indented two
more spaces ("2타"). So a 본문 cell takes **one `--cell-line` per paragraph**, in
order, and the indent is leading spaces in the value:

```
python engine/scripts/preedit.py fill-cells $W/form.hwpx --out $W/step1.hwpx \
    --cell-line "2,0=1. 관련: 국가유산청 문화유산정책과-1234(2026. 7. 30.)" \
    --cell-line "2,0=" \
    --cell-line "2,0=2. 위 호와 관련하여 다음 자료를 요청하오니 협조하여 주시기 바랍니다." \
    --cell-line "2,0=" \
    --cell-line "2,0=  가. 제출 자료" \
    --cell-line "2,0=    1) 2020년 이후 지정·등록 근대건조물 목록" \
    --cell-line "2,0=      가) 평면도·입면도·단면도" \
    --cell-line "2,0=  나. 제출 기한: 2026. 9. 30.(화)" \
    --cell-line "2,0=" \
    --cell-line "2,0=붙임  자료 제출 서식 1부.  끝." \
    --charpr-per-cell 2,0=14 --parapr-per-cell 2,0=18
```

→ `{"paragraphs": 10, "paragraphs_reused": 10, "paragraphs_created": 0}`.

Three things about that call are not optional:

- **`--cell-line`, not a newline.** From PowerShell you cannot put a literal
  newline inside a quoted argument. (A `--map` value may be a JSON **array**
  instead, and a newline inside any value works wherever your shell can produce
  one — same rule either way.) An empty `--cell-line "2,0="` is a blank line,
  which is how 공문 separates 항목. If you script this in a `.ps1`, save it as
  UTF-8 **with BOM**: Windows PowerShell 5.1 reads a BOM-less script as cp949
  and the Korean arguments fail to parse.
- **`--parapr-per-cell 2,0=18`.** The 기안문 본문 cell's reserved blank
  paragraphs are CENTER-aligned (paraPr 15) because that cell also holds
  발신명의 and 직인. Fill it faithfully and the whole hierarchy renders centred
  with the indents gone — read that off the render, then name a justified id
  (18 on this form: JUSTIFY, 100% line spacing, the form's own def).
- **`--charpr-per-cell 2,0=14`** for the reason in §1.1 — the pre-flight's
  suggestion (23) is the 비고 fine print, not the 본문 face.

`paragraphs_reused` vs `paragraphs_created` is worth reading. This form reserves
18 blank lines in that cell and they are used first; anything beyond them is a
clone of the target paragraph *appended*, which lengthens the cell — 24
paragraphs into that 20-slot run rendered as one content page **plus an empty
spill page**. If `paragraphs_created` is not 0, check the page count.

**Page parity after a multi-paragraph fill**: every paragraph written or created
loses its cached lineseg, so Hancom re-layouts on open — which is what makes it
render correctly. Take `pages_document` from the conversion, or declare
`expectations.pages_document`; the `artifact_layout_cache` source under-counts.

If the one `fill_map` declares this whole body, use the same JSON array or
newline string. The post-flight splits it with the writer's exact
`split_fill_lines` rule: every non-empty paragraph is checked for T30/T42, and
the address key limits those matches to cell `2,0` (T44). A multi-paragraph
value therefore cannot turn the charPr safety check into a skip.

---

## 2. The artifacts, and exactly which flag eats each one

There are **four** files. Not five, and in particular not three maps.

| artifact | produced by | consumed by |
|---|---|---|
| `profile.json` | `form_inspect --out profile.json` | `visual_verify --form-profile` (which forwards it to `check_residue`), and your own reading |
| `baseline.json` | `form_inspect --baseline baseline.json` | `style_diff --baseline` (format-drift proof; optional) |
| `fill.json` — **the one map** | you write it | `visual_verify --fill-map` **and** `--expectations` (same file, twice — the blessed invocation), and any module checker's `--fill-map` |
| `form.hwpx` — the blank | the form itself | `visual_verify --baseline` — two checks off one flag: the pixel diff (it converts the blank for you) and the T30 seat comparison (§1.1; reads the XML, no renderer needed). Not optional on a form whose seats are not the body face |

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

The mapped value is the **complete authored span in the artifact**, not merely
the payload inserted after a label (T43). If COM changes `수신` to
`수신 국가유산청장`, declare `"수신": "수신 국가유산청장"`, not
`"수신": "국가유산청장"`. A label counts as consumed only when that occurrence
lies wholly inside the declared value span; a payload fragment elsewhere does
not suppress surviving form text.

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

## Hancom conversion cost of this recipe

Conversions are serial, are the slowest step in the loop, and on a shared
machine they are the step another lane is waiting for. So the count is part of
the contract:

| step | conversions |
|---|---:|
| the artifact, once | 1 |
| the blank form, on the first verify pass | 1 |
| the blank form, on the second verify pass | **0 since T104** — reused |

A minimum accepted fill therefore costs **2**, not the 3 it cost before. The
saving is a proven reuse, not a cache: `com_backend convert` leaves a sidecar
binding the PDF to the exact source bytes it came from (T38), and the second
pass reuses that PDF only when both hashes still match. A different blank form,
an edited one, a regenerated PDF, a missing or foreign sidecar — each falls
through and converts, because *cannot prove* means convert. `--baseline` still
names the `.hwpx`: the T40 charPr leg reads the blank form's XML, so the PDF is
not a substitute for the document, only for the conversion of it. The verdict
reports `baseline_conversion_reused` either way, so a run never implies work it
did not do.

Measured on the 기안문 별지 1호: first conversion 22.9s, reuse 1.8s.

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
raised while every height-based proof passed. On this form the suggestion is
the right answer; on many forms it is not, so decide it with §1.1 rather than
pasting `suggested_flags` unread.

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

→ `{"ok": true, "converted": "...filled.pdf", "record": "...filled.pdf.conversion.json"}`.
You may skip this step and let `visual_verify` do the conversion itself — it
runs the identical command — but then re-running pass 2 re-converts, so
converting once here and passing `--pdf` to both passes is cheaper. With no
Hancom on the machine, render on the operator machine and bring the PDF; a
verification loop that cannot render must not report a pass.

**Keep the `.conversion.json` next to the PDF.** The convert step does more
than export: when the source stores a non-zero `PrintInfo/PrintMethod` (n-up
"모아찍기" — the whole gongmun family does, 기안문 별지 stores 4) it rewrites
that to 0 in a temporary copy first, because Hancom's `SaveAs(PDF)` otherwise
bakes the print imposition into the PDF. The sidecar is how the NEXT step
learns that this happened. Without it `visual_verify` sees a source that stores
imposition and no evidence that anything neutralised it, and HARDs
`imposition_mismatch` — correctly, on its own information, and unwaivably
(`imposition_mismatch` is not in `SAFETY_CHECKS`). That is T38: a gate cannot
tell "did not happen" from "was not told". The record is written by default, so
following this recipe verbatim is enough; move it with `--record PATH` only if
you also pass `--conversion-record` in steps 7 and 9. Copy the PDF somewhere
else and you must copy the sidecar with it.

The record is bound to the bytes it describes — it carries the sha256 of both
`filled.hwpx` and `filled.pdf`. If you edit the artifact you must re-convert;
verifying against a stale record is a usage error (exit 2), not a pass.

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

No flag names the conversion record: `visual_verify` picks up
`$W/filled.pdf.conversion.json` on its own. Confirm it did — the verdict's
`deterministic.conversion.provenance` reads `conversion_record`, and
`deterministic.pages_document_source` reads `conversion` rather than
`artifact_layout_cache`. If the sidecar lives elsewhere, add
`--conversion-record PATH` to **both** passes.

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

## 3b. Marking a consent choice (T111)

A 동의서 asks a question and expects the applicant to answer it. That is not a
fill in the sense the rest of this recipe means — the seat already contains its
final text — so the steps above do not cover it. Everything below is measured on
the corpus, not inferred.

**Two shapes, and they are not equally verifiable.** `consent_groups()` in the
grant module counts options by glyph when at least `min_options` (2) marking
glyphs are present, and otherwise by *exact* token match against the
vocabulary's `option_labels`:

| form | inner text | basis | `glyph_bearing` | `required` | `consent_unmarked` |
|---|---|---|---|---|---|
| pps-jeongbogonggae-donguiseo | `(예,  아니오)` | tokens | **false** | false | **skipped**, `no_mark_glyphs` |
| kstartup-jiwon-sincheongseo | `( ■동의함  □동의하지 않음 )` | glyphs | true | true | fires; unmarked + `required` + `final` is HARD |

Both forms carry exactly 2 groups. Exact token match rather than substring is
load-bearing: `예` is a substring of 예비창업자 / 예시 / 예정.

Every number in that table is pinned by existing regressions rather than
restated here — `test_donguiseo_offers_two_glyphless_choices`,
`test_the_glyphless_choices_are_skipped_with_a_reason`, and
`test_the_consent_choices_are_two_and_both_are_required` in
`modules/grant/tests/test_grant_corpus.py`. If this table and those tests ever
disagree, the tests are right.

**The consequence to internalize: on a glyphless form, no gate checks whether
you marked it.** R4a has nothing to count, so it skips with
`{"rule": "consent_unmarked", "reason": "no_mark_glyphs", "groups": 2}` — that
exact line appears in a passing A2 verdict whose consents *were* marked, and it
would appear identically if they were not. The mark is therefore only ever as
trustworthy as your own report of it. **Say in your summary which consents you
marked and with what value**; nothing downstream will say it for you.

**And never choose the answer yourself.** The checker's own wording is the
policy: marking a consent "is the applicant's decision to make, never the
tool's". If the operator did not supply a decision, leave the group unmarked and
report it as unanswered. An unmarked consent is a visible, correctable state; a
consent you invented is a legal declaration made on someone else's behalf.

### Finding the slots

`form_inspect` marks them, since T110:

```
python engine/scripts/form_inspect.py $W/form.hwpx --out $W/profile.json
```

Each `guide_text[]` entry that is a marking site carries `answer_slot`:
`interrogative_enumeration` (a question plus a parenthesized pair of
alternatives) or `multiple_mark_slots` (two or more empty `[ ]`/□ slots). Those
paragraphs are excluded from `removal_targets` — they are marking sites, never
deletion candidates.

Such an entry also carries **`at_para`**, which is the address an edit takes.
`para_idx` is not: it is a legacy scan counter, and the two numbers differ on
every corpus instance.

| form | slot | `para_idx` | `at_para` |
|---|---|---|---|
| pps-jeongbogonggae-donguiseo | 수집ㆍ이용 동의 | 39 | **42** |
| pps-jeongbogonggae-donguiseo | 제3자 제공 동의 | 54 | **58** |
| jumin-deungchobon-sinchengseo | 등초본 선택 필드 ×2 | 50, 73 | **52, 75** |

`--full-text PARA:N` also takes `at_para`, and it echoes the number back under
both key names — so passing a `para_idx` there returns a *different paragraph*
without complaining. `PARA:39` on this form returns an empty paragraph, not the
consent question. Read `at_para` from the profile; never retype `para_idx`.

`at_para` is omitted rather than guessed when the binding cannot be proven, so
treat its absence as "no addressable seat" and fall back to matching on text.

### Marking a glyphless group

One call does both occurrences. The two consent questions on
pps-jeongbogonggae-donguiseo share the identical seat text, so
`all_occurrences` is the correct scope rather than a shortcut:

```
python engine/scripts/preedit.py replace $W/filled.hwpx \
    --map $W/consent.json --out $W/filled2.hwpx
```

```json
{"(예,  아니오)": {"text": "(예,  아니오) ⇒ 예", "all_occurrences": true}}
```

Measured on the corpus form: `{"ok": true, "hits": {"(예,  아니오)": 2},
"scope": {"(예,  아니오)": "all_occurrences"}}`. Keep the enumeration and append
the decision — do not overwrite `(예, 아니오)` with `예`, or the question loses
the options it offered and `consent_option_lost` has a real change to report.

Running `check_grant` on that output: `verdict: pass`, `hard: 0`,
`consent_groups` still 2 with inner text `예,아니오` — the enumeration survived —
and `consent_unmarked` still
`{"reason": "no_mark_glyphs", "groups": 2}`, **byte-identical to the blank
form's row.** That is the constraint above, demonstrated end to end: the
checker's output does not move when you answer the question.

**Check where the mark lands.** The appended mark lengthens a line that the form
sized for its own text, so it can wrap. In A2's run the second consent line
ended `… (예,  아니오) ⇒` with `예` alone on the next line — legible, and the
vision half reported it as `alignment_drift` `warn`, but it reads worse than the
first line where the identical mark fit. If the render wraps, either shorten the
mark or address that paragraph on its own with `at_para` and a shorter token.

If you genuinely need to answer the two questions differently, address them per
paragraph with the `at_para` values from the table above:

```json
{"(예,  아니오)": {"text": "(예,  아니오) ⇒ 예", "at_para": 42}}
```

### What must not move

- The `□ 개인정보 수집ㆍ이용 동의` / `□ … 제3자 제공 동의` lines are **section
  headings**, not choices — `consent_groups()` does not report them. Their `□`
  is decoration. Marking or deleting one is wrong in both directions.
- The consent question paragraph itself survives, and since T110 it is no longer
  in `check_residue`'s forbidden set, so no `--keep` is needed for it.
- The statutory notice paragraphs on the same form
  (`※ … 동의를 거부할 권리가 있습니다`, PIPA §22 고지) are classified as removable
  guide text by core, so the residue gate holds their text in the forbidden set.
  Since T114 you do **not** hand-write a `--keep` for them: the grant module
  declares them in `expectations.protected_text`, and `visual_verify` forwards
  them, recording them as `deterministic.residue_keep.module_protected_keep`
  apart from your own `explicit_keep`.

  **You have to pass the module payload for that to happen.** Module
  expectations are ordinary payload the caller supplies — nothing loads them for
  you — so merge
  `modules/<family>/references/visual_expectations/<family>.json` into the
  `--expectations` file you build from your fill declaration. Measured on A2:
  with the module list the run needs **zero** hand-written keeps where it
  previously needed four, and with neither the residue gate correctly HARDs. If
  `module_protected_keep` comes back empty on a 동의서, you forgot the merge.

## 3c. A form's blank is a ruled run — put the value on the rule (T112)

The blank you write into is usually not empty space. It is a run whose charPr
carries `underline`, and that rule is what the reader sees as the line to write
on. Since T112 the profile says which run it is: a `--full-text` run record
carries **`ruled: true`** when its charPr draws a rule. The key is present only
when true, so an ordinary run record keeps its `{index, text, charpr}` shape.

Measured on `pps-jeongbogonggae-donguiseo` (2 of its 40 charPr ids are ruled):

| `at_para` | seat | runs | where the rule is |
|---|---|---|---|
| 18 | `주       소 :` | `'   '` / label / 46 spaces | run 2, **whitespace only** |
| 20 | `업체명(성명) :` | label / spaces + `(인)` | run 1, **fused with the marker** |
| 64 | `본인 성명 (서명 또는 인)` | one run: label + blank + marker | **no rule at all** |

**The rule to follow: write the value into the ruled run, not after the label.**
Extending the label run leaves the value in a run with no rule while the ruled
run survives beside it — and because the label run got longer, the rule is
pushed along and can wrap onto the next line, rendering as a stray line under
nothing.

That is not hypothetical. A2's accepted artifact filled 주소 by extending the
label run, and its own page crop shows the address on one line with an orphaned
rule below it.

**What caught it, and what did not.** Every deterministic check passed — the
run's charPr id never changed and no text went missing, so nothing text-shaped
could see it. The **vision half did catch it**, as `alignment_drift` `warn` on
page 1, and diagnosed the mechanism exactly ("the form's own trailing blank run
(46 spaces, underline charPr, never written to by the fill) wrapping onto its own
line because the label run it follows was extended"). But `alignment_drift` is
`warn`, and warns do not block: that run finished `counts: {"hard": 0, "warn":
8}`, `acceptance: true`, `acceptance_blockers: []`.

So the lesson is not "the gates are blind here" — it is that **an operator who
reads only `verdict` ships this.** Read the warns, and better, do not create the
finding: write into the ruled run.

For a rule fused with a marker (at_para 20) the fix is direct — the marker gives
the key a non-whitespace anchor, so write onto the rule and reproduce the marker
verbatim:

```json
{"                     (인)": {"text": "   테스트상사            (인)", "at_para": 20}}
```

charPr ids, run count and the single `(인)` all survive; the name sits on the
rule.

**A whitespace-only rule takes an address, not a key (T115).** For at_para 18
the ruled run is nothing but spaces, so there is no string to match, and
`preedit replace` refuses a whitespace-only key outright
(`빈(공백뿐인) 키는 치환 불가`). That refusal is right and stays: tier A compares
run text *stripped*, so a whitespace-only key is a wildcard over every
whitespace-only run — scoping it to one paragraph does not save it, because this
paragraph has two such runs, the indent and the rule.

Use `set-runs`, which addresses the run instead of matching it:

```
python engine/scripts/preedit.py set-runs $W/filled.hwpx \
    --out $W/filled2.hwpx --run "18,2=서울특별시 강남구 테헤란로 100        "
```

The address is the `at_para` and `runs[].index` the profile already reports, and
`runs[].ruled` tells you which one to name. The run's opener is never rewritten,
so its `charPrIDRef` — and therefore the rule — survives: measured on the corpus
form, the value lands in run 2 with `charpr` 19 and `ruled: true`, run count and
every charPr id unchanged.

It refuses rather than guesses: an out-of-range paragraph or run index is an
error that reports the count it found, a duplicate address is an error (no silent
last-write-wins), and a paragraph whose only run has no `<hp:t>` — an empty
cell's self-closing run — is sent to `fill-cells`, which owns that structure.
Re-applying the same value is content-identical.

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

`warn: []` is this form's number, not a rule. A gongmun-family fill accepts
with `fill_charpr_script_inherited` in `warn`, one per seat whose typography the
blank form already had (§1.1) — that WARN *is* the suppression, on the record.
Read each one's `form_baseline_charpr_id` and confirm it is the seat's own
printed face; a WARN you cannot explain is not a WARN you may ignore.

**Partial results, so you can tell them from success:**

| what you see | what it means |
|---|---|
| exit 3, `vision_pending` | pass 1 finished; you still owe the page reading |
| exit 3, `safety_incomplete` | nothing failed, but a SAFETY check never ran — supply the missing input or waive it on the record |
| exit 0, `deterministic_pass` | `--deterministic-only`; `acceptance: false` by construction. A smoke check, never an acceptance |
| exit 0, `pass`, non-empty `acceptance_waivers` | accepted, minus whatever you waived |
| exit 2, `usage_error` | bad input; nothing was judged |

**PowerShell: record the checker process, not the harness wrapper (T46).**
Some Windows agent shells display a generic outer exit `1` for any bare native
non-zero command, even when the Python checker correctly returned `2` or `3`.
Capture `$LASTEXITCODE` immediately and propagate that exact value; do not run
another command or a pipe first:

```powershell
python pipeline/scripts/visual_verify.py @args
$native=$LASTEXITCODE
Write-Output "DIRECT_EXIT=$native"
exit $native
```

The JSON verdict says *what* failed; `DIRECT_EXIT` proves the documented
0/2/3 process contract. A shell UI's uncaptured outer `1` proves neither.
