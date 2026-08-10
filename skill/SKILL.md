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

Read `references/platform-backends.md` before selecting a platform or claiming
render evidence. It is the shipped support/evidence matrix: supported is not
parity, unknown is not unsupported, and a capability probe never establishes
proof. Successful terminal execution must leave a current receipt at
`output/proof/backend/receipt.json`.

- `.hwpx` — offline XML engine (default, works everywhere, byte-preserving).
- `.hwp` — run the bounded `hwp_ingress.py inspect` candidate gate first.
  It parses only the CFB/FileHeader security envelope, never document content.
  Canonical conversion is Hancom COM only (`render.hancom_com: true`) and must
  pass the same-COM-extractor comparison. No COM means no canonical edit;
  ask for `.hwpx`. A workspace that claims this conversion must pass
  `hwp_ingress.py verify` and retain the receipt; a native-origin HWPX is a
  separate no-ingress-claim path. Never send raw `.hwp` bytes to the XML engine.
- T86 `hwp_diagnostic_candidate.py` is an explicitly requested, quarantined
  `rhwp` diagnostic slice only. Require a pre-created
  `work/stage-0/scratch/hwp-diagnostic` root, opaque run id, explicit binary,
  and mandatory `--rhwp-sha256`; it may never feed canonical output, Stage 0,
  `new_report --ingress-receipt`, or a backend receipt. Its comparison is
  `unknown`, render is `not_run`, and proof is `none`. It has no `pyhwp` or
  LibreOffice fallback.
- T87 `hwp_java_diagnostic_candidate.py` is a separate quarantine for one
  release-approved hwp2hwpx fat-JAR hash and fixed source bridge. Require the
  exact `hwp-java-diagnostic` leaf, explicit Java path/hash, and approved
  operator-supplied JAR. The receipt declares the surrounding runtime unbound,
  comparison unknown, render not run, proof none, and submission false. Never
  route it through T85, Stage 0, `new_report`, or backend evidence; the bundle
  contains no JAR/JRE/class/corpus bytes.
- T88 `hwp_semantic_oracle.py` is receipt-only bounded content/object agreement between one current
  T86 and one current T87 candidate. Require the exact pre-created
  `work/stage-0/scratch/hwp-semantic-oracle` leaf and both producer receipt
  paths; `verify` requires those paths again. It captures bounded snapshots,
  reruns public producer/story verifiers over those bytes, and emits only
  closed match booleans plus explicit compared/not-compared coverage and opaque
  input bindings. Agreement is
  diagnostic-only (`source_fidelity` not established, render `not_run`, proof
  `none`, submission false); never route it to T85, Stage 0, canonical output,
  rendering, or `new_report`.
- Originals are immutable: every operation writes a new file (`--out` /
  `--save-as`). Editing in place is a defect, not a shortcut.

## Task routing

For a privacy-safe story inventory, run
`python pipeline/scripts/story_graph.py FORM.hwpx --out story-graph.json`.
This is read-only and refuses unknown structure; it never reads body text into
the output. The result uses manifest-order member ordinals and role/ordinal
addresses, never source names, control IDs, raw-byte fingerprints, or template
fingerprints; it makes no edit or render claim.

For the separate T80 structural edit slice, first obtain that inventory, then
run `python pipeline/scripts/story_edit.py INPUT.hwpx --ops-file OP.json
--out OUTPUT.hwpx --receipt RECEIPT.json`. The closed selector ends at
`/paragraph[n]` and the paragraph must have one direct text-bearing run with
one direct `hp:t`; stale/private source SHA, ambiguous/text-first/raw-ID/
`/run[n]`/noncanonical selectors, unsupported XML, and raw CR refuse. The
receipt is local privacy-safe evidence only and always reports
`render: "not_run"`; no native/Hancom/PDF result is implied.

| intent | command (see references/operations.md for contracts) | freedom |
|---|---|---|
| inspect a binary HWP candidate without reading its body | `python pipeline/scripts/hwp_ingress.py inspect FORM.hwp` | LOW — CFB/FileHeader capability only |
| canonically convert HWP to HWPX | `python pipeline/scripts/hwp_ingress.py convert FORM.hwp --adapter hancom --out OUT.hwpx --manifest RECEIPT.json` | LOW — Windows Hancom only; conversion proof is never render proof |
| quarantine an explicit `rhwp` diagnostic candidate (T86) | `python pipeline/scripts/hwp_diagnostic_candidate.py run FORM.hwp --diagnostic-root work/stage-0/scratch/hwp-diagnostic --run-id HEX --rhwp BIN --rhwp-sha256 SHA256` | LOW — diagnostic only; never canonical or submission evidence |
| quarantine an approved Java diagnostic candidate (T87) | `python pipeline/scripts/hwp_java_diagnostic_candidate.py run FORM.hwp --diagnostic-root work/stage-0/scratch/hwp-java-diagnostic --run-id HEX --java JAVA --java-sha256 SHA256 --tool-jar APPROVED.jar` | LOW — diagnostic only; runtime unbound, no parity/render/submission claim |
| compare current T86/T87 candidates (T88) | `python pipeline/scripts/hwp_semantic_oracle.py compare T86_RECEIPT.json T87_RECEIPT.json --diagnostic-root work/stage-0/scratch/hwp-semantic-oracle --run-id HEX` | LOW — paired diagnostic agreement only; no canonical, render, or submission claim |
| inspect bounded HWP source coverage (T89) | `python pipeline/scripts/hwp_source_coverage.py inspect INPUT.hwp --coverage-root work/stage-0/scratch/hwp-source-coverage --run-id HEX` then `verify` with the same source/root/run | LOW — receipt-only BodyText coverage; complete coverage is not source fidelity, conversion parity, native execution, render, or submission evidence |
| edit exactly one inventoried story paragraph (T80 structural mechanics) | `python pipeline/scripts/story_edit.py INPUT.hwpx --ops-file OP.json --out OUTPUT.hwpx --receipt RECEIPT.json` | LOW — closed ops only; no render claim |
| profile a form (structure, anchors, tables, constraints) | `python engine/scripts/form_inspect.py FORM.hwpx --out profile.json [--baseline baseline.json]` | LOW — run as-is |
| **fill a form end to end** (which command per cell, one map, verify) | follow `references/fill-recipe.md` — decision rule, the four artifacts and the flags that eat them, the literal command sequence, and what `acceptance: true` looks like | LOW — run as-is |
| fill an **empty** form cell (`table_map` says `fill_target`) | `python engine/scripts/preedit.py fill-cells IN.hwpx --out OUT.hwpx --cell ROW,COL=값 [--charpr-per-cell ROW,COL=ID]` (ROW,COL = the cellAddr `table_map` reports; `--charpr-per-cell` takes the pre-flight's `charpr_suggested`, see references/operations.md §3) | LOW |
| fill a cell that needs **several paragraphs** (공문 본문 `1./가./1)`) | same command with `--cell-line ROW,COL=값` once per paragraph, in order (indent = leading spaces), plus `--parapr-per-cell ROW,COL=ID` when the form's blanks are not body-aligned — references/fill-recipe.md §1.2 | LOW |
| write over/into a **printed seat** the form typeset (`" 우(     -     )"`, `" http://"`, a date skeleton) | `python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx --at-cell 'ROW,COL=값'` — or `--at-cell-append 'ROW,COL=값'` to keep the printed prefix. Address-keyed, so you never need the seat's exact internal whitespace (T34) | LOW |
| replace a literal placeholder string that exists in the document | `python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json` | LOW |
| read a cell's **exact** text (only when a byte-exact string is genuinely needed) | `python engine/scripts/form_inspect.py FORM.hwpx --full-text ROW,COL` — per-cell opt-in escape from the structure-only contract | LOW |
| write one cell of a `.hwp` (Windows+Hancom, one session per cell) | `python engine/scripts/com_backend.py set-cell --file F.hwp --addr ROW,COL --text 값 --expect-empty --save-as OUT.hwpx` | LOW |
| delete guide text (colored 안내문) | `python engine/scripts/preedit.py delete-guides IN.hwpx --out OUT.hwpx --color ...` | LOW |
| normalize charPr clones (postedit) | `python engine/scripts/preedit.py normalize-clones ...` | LOW |
| residue gate on a filled artifact | `python pipeline/scripts/check_residue.py --form-profile profile.json --artifact OUT.hwpx [--keep TEXT ...] [--keep-pattern REGEX]` — on a FILL the form's own labels legitimately survive, so a keep list is required (see `references/operations.md` §10) | LOW |
| verify formats offline (pt/color invariants) | `python engine/scripts/charpr_check.py --file OUT.hwpx --base-pt N` | LOW |
| style drift vs form baseline | `python engine/scripts/style_diff.py OUT.hwpx --baseline baseline.json` | LOW |
| measure PDF layout (whitespace/gaps) | `python engine/scripts/layout_qa.py --file verify.pdf` | LOW |
| **verify a rendered artifact (render→judge loop)** | `python pipeline/scripts/visual_verify.py --artifact OUT.hwpx [--pdf verify.pdf] [--expectations exp.json]` then read the `vision_required` PNGs against `references/visual-rubric.md` and re-run with `--vision-verdict vision.json` | LOW (script) + HIGH (reading the pages) |
| tidy blank paragraphs near anchors | `python engine/scripts/tidy_hwpx.py FILE.hwpx --before "앵커" --out OUT.hwpx` | LOW |
| COM edit / assemble / export PDF (Windows+Hancom) | `python engine/scripts/com_backend.py inspect\|edit --file ... --ops ops.json --save-as ... --export-pdf ...` | LOW |
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

`acceptance: true` also claims that every check in the SAFETY set actually
**ran**. A run that could not run one of them (no fill map, no form profile, no
page-count source) reports `safety_incomplete` and exits 3 rather than quietly
accepting; supply the missing input, or waive that one check on the record with
`--accept-without CHECK`. Full table and vocabulary: `references/operations.md`
§10.

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

`story_graph.py` is a **read-only, structure-only** inventory. It follows
`Contents/content.hpf` manifest/spine and actual section roots (not ZIP or
filename order) and recognizes only namespace-valid nested `hp:ctrl` owners whose public OWPML
model gives them an `hp:subList`: `header`, `footer`, `footNote`, and
`endNote`. Its JSON has manifest-order member ordinals, role/ordinal addresses,
closed roles, counts, topology, and schema-only structural hashes only. It never
emits member names, control IDs, body text, author metadata, corpus content,
URLs, absolute paths, raw-byte hashes, or template fingerprints. The exact
physical mimetype is first/stored/extra-free; every local ZIP header must match
its central record, including version-needed and DOS date/time, with empty
extras and only flags `0` or corpus-proven
DEFLATE fast flag `0x0004` (PKWARE APPNOTE bit 2, DEFLATED only); OCF rootfiles and declared XML roots are
closed before bounded
ZIP/XML availability, OPF grammar/media/coverage, foreign namespaces and the
documented closed-pair transplants (including nested `hh:head`, `hh:bold`
under `head`, and `hc:img` under `hp:run`),
invalid page/bool values, duplicate note instances or same-table cells, and
unsupported `hiddenComment`/memo/field/drawText/caption/masterPage controls
refuse. Every actual section must occur exactly once in a nonempty OPF spine;
there is no manifest fallback. A spine may reference only definition/section
roles. Table-cell stories carry closed table/cell-encounter ordinals (never raw
cell coordinates), while story-in-story owners refuse; no selector, edit, or render
support is claimed. The owner boundary is grounded in the public
[Hancom OWPML model](https://github.com/hancom-io/hwpx-owpml-model), especially
its `HeaderFooterType`, `NoteType`, `hiddenComment`, `fieldBegin`, `drawText`,
and `caption` classes.

The `story_graph.py` CLI exits 0 only for a passed graph, 2 for argparse or
output/usage errors, and 3 for refused/unknown packages. Capture the native
exit directly (`$native=$LASTEXITCODE`) when running it from PowerShell; do not
pipe the result into a summary command.

- `inspect`/`form_inspect` return **structure only, never body text** — do
  not dump full document text into context. The one sanctioned exception is
  `form_inspect --full-text ROW,COL`, which emits the exact run text for the
  cells you **name** and no others; it is per-cell opt-in for that reason.
  Reading `Contents/section*.xml` by hand is still the defect it always was
  (T34: both round-3 clean-room tiers did it, for want of this flag).
- `table_map`'s `text_preview` is 30 chars and tells you when it cut
  (`truncated: true`). Never key a `replace` on a preview — the 협업기간
  skeleton's preview stops right before its `(     개월)` blank (T34).
- To **edit** a printed seat, address it: `replace --at-cell ROW,COL=값`
  (whole run) or `--at-cell-append ROW,COL=값` (keep the printed prefix — the
  normal shape of a labeled field, T31). Pick the mode explicitly. A cell with
  several text runs refuses and lists every run's index and exact text; name
  the one you mean with `ROW,COL#RUN`. Never reconstruct the seat string by
  hand to feed `--map`.
- An empty form cell has **no text to key on** — it is a self-closing
  `<hp:run charPrIDRef="N"/>` with no `<hp:t>` (all 19 empty cells on the
  PPS form). `preedit replace` is text-keyed and cannot reach it; that is what
  `preedit fill-cells` is for (T27). Routing an empty cell to `replace` is the
  defect that pushed two clean-room agents onto the COM path and into T28.
- "Preserves the run's charPr" is only safe when that charPr *is* body
  formatting. Run the pre-flight: `form_inspect` flags every `fill_target`
  whose run carries a `script_anomaly` and names the `charpr_suggested` to use
  — pass it as `fill-cells --charpr-per-cell ROW,COL=ID`. Skipping it is not
  silent: `fill-cells` refuses (exit 3) instead of producing a ~6.35pt raised
  fill that every height-based proof passes (T30). Never read `header.xml` to
  find the id — that is what `charpr_suggested` is for.
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

- `references/fill-recipe.md` — the canonical mixed-storage form
  fill, worked end to end on the real PPS form: which command each
  cell takes, the ONE fill map, and the acceptance verdict.
- `references/operations.md` — CLI contracts + JSON verdict shapes.
- `references/forms.md` — form-family notes (① 민원 … ⑦ 인사/노무), Bench-0
  floors, per-family gotchas.
- `references/troubleshooting.md` — trouble-table distillate (T-rows) for
  symptom → cause → fix matching.
- `references/visual-rubric.md` — the defect classes you apply when
  READING a rendered page image (the vision half of the verify step).

The shipped `pipeline/scripts/render_quality.py` checker is the receipt-bound
quality route for rendered PDF glyphs; text extraction alone is not visible
glyph proof, and an `advisory` grade is never Hancom parity.

Module skill fragments (report pipeline, style/humanize, gongmun/공문) are
appended below by the installer when their distribution modules are enabled.
