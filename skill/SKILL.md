---
name: rigorloom-hwp
description: >-
  Deterministic HWP/HWPX (한글, Hancom) document engine. Use this skill whenever
  the user mentions HWP, HWPX, .hwp, .hwpx, 한글 문서, 한컴, 양식, 서식,
  신청서, 공문, 근로계약서, 보고서 조립, 수식 삽입, or asks to open, profile,
  fill (채우기), verify, or convert a Korean word-processor form. It profiles
  forms offline (no Hancom needed), fills placeholders byte-safely, proves
  layout/format invariants with JSON verdicts, and drives Hancom COM when
  available. Always prefer this skill over ad-hoc XML editing of .hwpx files.
paths: ["**/*.hwp", "**/*.hwpx"]
disable-model-invocation: false
---

# rigorloom-hwp — deterministic 한글 document engine

Contracts and gotchas only. The engine already knows *how*; this file says
what is true about THIS system and what must not be modified.

## Capability probe (live, injected at load)

!`python engine/scripts/probe.py --json`

Read it before choosing a path: `render.hancom_com` gates every COM
operation; `modules.enabled` gates module vocabulary (fragments below);
`render.pdf_capable` gates PDF-measured verification.

## Backend rule

- `.hwpx` — offline XML engine (default, works everywhere, byte-preserving).
- `.hwp` — Hancom COM only (`render.hancom_com: true`). No COM → cannot edit;
  ask for `.hwpx` or convert on the operator machine. Never parse `.hwp` bytes.
- Originals are immutable: every operation writes a new file (`--out` /
  `--save-as`). Editing in place is a defect, not a shortcut.

## Task routing

| intent | command (see references/operations.md for contracts) | freedom |
|---|---|---|
| profile a form (structure, anchors, tables, constraints) | `python engine/scripts/form_inspect.py FORM.hwpx --out profile.json [--baseline baseline.json]` | LOW — run as-is |
| fill an **empty** form cell (`table_map` says `fill_target`) | `python engine/scripts/preedit.py fill-cells IN.hwpx --out OUT.hwpx --cell ROW,COL=값` (ROW,COL = the cellAddr `table_map` reports) | LOW |
| replace a literal placeholder string that exists in the document | `python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json` | LOW |
| write one cell of a `.hwp` (Windows+Hancom, one session per cell) | `python engine/scripts/com_backend.py set-cell --file F.hwp --addr ROW,COL --text 값 --expect-empty --save-as OUT.hwpx` | LOW |
| delete guide text (colored 안내문) | `python engine/scripts/preedit.py delete-guides IN.hwpx --out OUT.hwpx --color ...` | LOW |
| normalize charPr clones (postedit) | `python engine/scripts/preedit.py normalize-clones ...` | LOW |
| residue gate on a filled artifact | `python pipeline/scripts/check_residue.py --form-profile profile.json --artifact OUT.hwpx [--keep TEXT ...] [--keep-pattern REGEX]` — on a FILL the form's own labels legitimately survive, so a keep list is required (see `references/operations.md` §10) | LOW |
| verify formats offline (pt/color invariants) | `python engine/scripts/charpr_check.py --file OUT.hwpx --base-pt N` | LOW |
| style drift vs form baseline | `python engine/scripts/style_diff.py OUT.hwpx --baseline baseline.json` | LOW |
| measure PDF layout (whitespace/gaps) | `python engine/scripts/layout_qa.py --file verify.pdf` | LOW |
| **verify a rendered artifact (render→judge loop)** | `python pipeline/scripts/visual_verify.py --artifact OUT.hwpx [--pdf verify.pdf] [--expectations exp.json]` then read the `vision_required` PNGs against `references/visual-rubric.md` and re-run with `--vision-verdict vision.json` | LOW (script) + HIGH (reading the pages) |
| tidy blank paragraphs near anchors | `python engine/scripts/tidy_hwpx.py FILE.hwpx --before "앵커" --out OUT.hwpx` | LOW |
| COM edit / assemble / export PDF (Windows+Hancom) | `python engine/scripts/com_backend.py inspect|edit --file ... --ops ops.json --save-as ... --export-pdf ...` | LOW |
| decide WHAT to fill, which cells are staff-only, what the form means | read the profile + document text, judge | HIGH |
| layout judgment (is this gap designed or a defect?) | layout_qa numbers first, then judge; form families differ | HIGH |

### The verify step is two halves, and neither is optional

`visual_verify.py` is the deterministic half: it renders the pages, runs the
backstops (XML validity, blank render, page parity/imposition, budget,
declared format, fill map, fill-run script/scale inheritance, layout_qa,
residue/density, pixel diff) and
prepares the vision task. It **never** calls a model and it **never** reports
acceptance on its own — with no `--vision-verdict` the verdict is
`vision_pending` and the exit code is 3. You close the loop by opening the
listed PNGs, judging them against `references/visual-rubric.md` (a closed
class vocabulary — an invented class is a usage error), writing the vision
verdict JSON, and re-running. `--deterministic-only` is a smoke check, not an
acceptance. On repeated failure, `--attempt M --max-fix-attempts N` makes the
script escalate instead of letting you grind.

## Freedom map

- **LOW freedom** — fill, preedit/postedit, assembly ops, residue/format
  gates: use the exact CLIs above, do not modify them, do not reimplement
  their logic inline, do not post-edit their JSON verdicts. The ground truth
  (XML surgery, itemCnt recomputation, lineseg invalidation, T18 guards)
  lives inside the scripts.
- **HIGH freedom** — form diagnosis, fill-boundary reasoning, layout
  judgment, wording: the scripts return structure and numbers; interpreting
  them is your job. Recognition must come from the document (e.g. a form's
  own "색상이 어두운 칸은 작성하지 않습니다" line defines the fill boundary),
  not from priors.

## Model tier

Measured from clean-room installs on this skill (`references/model-routing.md`):

| task class | tier |
|---|---|
| inspect · fill · verify/judge | **Sonnet is sufficient** — measured, identical machine-verified result to Opus at ~1/5 the price |
| diagnosis (why is an output wrong, unfamiliar form family, unattributable failure) | **Opus** — measured advantage in causal explanation |
| assemble · prose/humanize | not measured — no claim |

Run the cheap tier by default. Escalate when the job is *understanding*
rather than *executing*. If the cheap tier struggles on a documented CLI
path, that is a surface defect to report, not a reason to escalate.

## Contracts (violations are defects)

- `inspect`/`form_inspect` return **structure only, never body text** — do
  not dump full document text into context.
- An empty form cell has **no text to key on** — it is a self-closing
  `<hp:run charPrIDRef="N"/>` with no `<hp:t>` (19 of 19 empty cells on the
  PPS form). `preedit replace` is text-keyed and cannot reach it; that is what
  `preedit fill-cells` is for (T27). Routing an empty cell to `replace` is the
  defect that pushed two clean-room agents onto the COM path and into T28.
- Cell addresses are **`cellAddr`** (`table_map`'s `addr`), never keypress
  counts. Merged cells own their top-left coordinate only, so addresses are
  not contiguous. `com_backend`'s legacy `row`/`col` keypress mode is opt-in
  (`raw_traversal`) and wrong on any form with a rowspan label column (T28).
- Fill is **idempotent**: re-running the same `preedit replace` on its own
  output (with `--allow-missing`) — or the same `fill-cells` with
  `--overwrite` — is content-identical. A second run that changes bytes is a
  bug. A `replace` value that contains its own key is applied exactly once
  (T26), not appended twice.
- A fill must not change table geometry: cell count, merges, borderFill,
  page count identical before/after — only text runs differ. Verify via
  `form_inspect` table_map diff when it matters.
- Checkbox glyphs (□ / [ ]) are **text toggles** (√/☑ insertion), never
  form-field objects. In many forms □ is a heading bullet, not a checkbox —
  read before toggling.
- Signature cells (`(서명 또는 인)`) stay blank and are flagged to the human.
  Unsupplied blanks stay blank and are listed back — never invent values.
- Instructional prose in a form is protected even when the guide-text
  detector reports 0 regions — deletion protection does not depend on the
  detector firing.
- 0-hit placeholder keys are a hard error by default (silent no-op fills
  were a real defect class); `--allow-missing` only for idempotent re-runs.

## Heavy flows are CLI-only

Report assembly, night runs, corpus benches, and hwp→hwpx conversion are
operator-triggered CLIs (documented in module fragments / operations.md).
Do not auto-start them from a casual mention of a file.

## Known boundaries

- Family ⑤ 기업 내부 문서 (품의서 etc.): **unsupported/untested** — no
  official corpus exists. If a user supplies a blank, treat it like a
  petition-family fill and say the family is untested.
- `.hwp` offline: read-only nothing — no edit path without COM.
- Guide-text detection does not fire on procurement-form instruction prose
  (Bench-0 finding); never rely on it as the only deletion guard.

## References (one level deep)

- `references/operations.md` — CLI contracts + JSON verdict shapes.
- `references/forms.md` — form-family notes (① 민원 … ⑦ 인사/노무), Bench-0
  floors, per-family gotchas.
- `references/troubleshooting.md` — trouble-table distillate (T-rows) for
  symptom → cause → fix matching.
- `references/visual-rubric.md` — the defect classes you apply when
  READING a rendered page image (the vision half of the verify step).

Module skill fragments (report pipeline, style/humanize) are appended below
by the installer when their distribution modules are enabled.
