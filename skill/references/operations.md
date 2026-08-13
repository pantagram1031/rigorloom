# Operations — CLI contracts and JSON outputs

All paths are checkout-relative. Every operation is non-destructive (reads
the input, writes `--out`/`--save-as`). Exit codes follow the checker
convention where noted: 0 = pass/clean, 2 = usage/config error, 3 = finding.

Filling a form is a **sequence**, not a lookup: read
[`fill-recipe.md`](fill-recipe.md) for the branch-per-cell decision rule, the
four artifacts and the flags that consume them, and what an accepted verdict
looks like. This file is the per-CLI contract each of those steps invokes.

## TOC

0. [Text-match scoping](#0-text-match-scoping) — which surfaces refuse an ambiguous match
0B. [Inherited-property attribution](#0b-inherited-property-attribution-t100) — which gates ask the blank form first
1. [probe](#1-probe) — capability probe
2. [form_inspect](#2-form_inspect) — offline form profiling (+ `--full-text`)
3. [preedit](#3-preedit) — replace (`--map` / `--at-cell`) / fill-cells / delete-guides / normalize-clones
4. [check_residue](#4-check_residue) — scan-derived residue gate
5. [charpr_check / style_diff](#5-charpr_check--style_diff) — format proofs
6. [layout_qa / fill_report](#6-layout_qa--fill_report) — PDF measurement
7. [tidy_hwpx](#7-tidy_hwpx) — blank-paragraph cleanup
8. [com_backend / build_report / xml_backend](#8-com_backend--build_report--xml_backend) — assembly
9. [render_probe / privacy_scan](#9-render_probe--privacy_scan)
10. [visual_verify](#10-visual_verify) — the render→judge loop

## 0. Text-match scoping

Every operation that resolves a string YOU supplied against document content
has to answer "and if that string is in the document more than once?". Three
answers are legitimate — **refuse**, **scope**, **all, by name** — and one is
not: silently picking. This table says which answer each surface gives, so you
can see it without reading source (T41).

| surface | ambiguous match is | how you scope it |
|---|---|---|
| `preedit replace --map` (tier A run strip-compare, tier B raw substring) | **REFUSED** — exit 2, `replace_key_ambiguous`, payload names every occurrence with `at_para`, the paragraph's text and recent prior context | map value object: `{"text": V, "at_para": N}` for that one paragraph, or `{"text": V, "all_occurrences": true}` for every occurrence, explicitly |
| `preedit replace --at-cell` / `--at-cell-append` / `--at-cell-map` | **SCOPED by construction** — `cellAddr` + `#RUN`, no string key exists. A multi-run cell is REFUSED (exit 2, `at_cell_run_ambiguous`) | `ROW,COL#RUN` from the refusal listing |
| `preedit replace --at-cell-expect` | **SCOPED** — a precondition on the same address; it never searches the document | the address you are already editing |
| `preedit fill-cells --cell` / `--cell-line` / `--map` | **SCOPED** — `cellAddr` only, never text | `--table N` + `ROW,COL` |
| `preedit delete-guides` | **not text-keyed** — selects by guide charPr colour/id | `--color` / `--charpr-ids` |
| `preedit normalize-clones --repoint-scope TO:ANCHOR` | **ALL matching paragraphs**, and the count is reported (`paragraphs`, `runs`). Repoints a charPr; never deletes or rewrites text | use a longer anchor; check the reported count |
| `tidy_hwpx` before/after anchors | **REFUSED** — `앵커가 모호함(문단 N개에서 발견)`; the precedent this table generalizes | a longer, unique anchor |
| `com_backend edit` `goto_text` | **FIRST OCCURRENCE, by construction** — hard `MoveDocBegin()` then `find()`, so it is a defined behaviour, not a guess | this IS the scoping mechanism for paragraph packs: it structurally touches one place |
| `com_backend edit` `find_delete` | **FIRST OCCURRENCE** by the same reset; every occurrence only with `"all": true` | `"all": true` to opt in |
| `com_backend edit` other anchored ops (`delete_blank_after/before`, `insert_blank_before`, `page_break_before`, `set_para_align --anchor`) | **FIRST OCCURRENCE** — same `MoveDocBegin()` + `find()` contract | a unique anchor, or `page_break_before` + a distinct heading |
| `com_backend edit` `replace_all` / `xml_backend` `replace_all` | **ALL, by name** — the op is called `replace_all` and reports `replaced: n` | use `preedit replace --map` with `at_para` when you want one |
| `check_residue` forbidden-string scan | **EXHAUSTIVE, never resolved** — every occurrence is reported with its offset and surrounding context | nothing to scope; read `at_offsets` |
| `check_residue --expect-text` | **presence anywhere, offline** — asks "is this string in the document's text", against the same normalized haystack the residue scan uses and with the declared string normalized the same way. A miss NAMES which kind it is: `absent`, or `split_across_runs` when the string is in the document but not as one literal because the document breaks words at run boundaries. TEXT level only — `expected_text.evidence_level` says so, and it is never render evidence (T130) | declare the run-split form, or assert a fragment that does not cross a run boundary |
| `check_residue --fill-map` value attribution | **PER OCCURRENCE** — an occurrence inside a declared value's span is attributed, one outside it still HARDs (T31). Never a global suppression | `--keep` for a string that legitimately survives everywhere |
| `visual_verify` residue keep derivation (`--fill-map` key → anchor/placeholder inventory, normalized substring **either direction**) | **REFUSED when one key claims more than one inventory string** — exit 2, `usage_error`, `ambiguous_fill_keys` names each claimed string and how often it is present. A key claiming one string that repeats is NOT refused: that case is per-occurrence and honest (T31) | a key that names exactly one string, or `{"text": V, "other_occurrences": "form_text"}` (the form prints the rest) / `"seats"` (the rest must be filled or they HARD) |
| `visual_verify` `declared_blank` / `intentionally_blank` | **ALL matching seats** — normalized containment either direction, so one entry can cover several seats; every suppression is recorded in `deterministic.declared_blank` with its source | name the seat exactly; read the recorded list back |
| `visual_verify --expectations` `fill_map` presence check | **presence anywhere** — asks "is this value visible in the render", not "where" | it is an existence proof by design; location is `check_residue`'s job |
| `visual_verify --expectations` `forbidden_text` | **EXHAUSTIVE per page** — one finding per page the string appears on | nothing to scope |
| `visual_verify --expectations` `protected_text` | **WHOLE INVENTORY ENTRY** — forwarded as `--keep`, and `check_residue` matches a keep against the entire normalized entry, never a substring of it. Recorded as `deterministic.residue_keep.module_protected_keep`, apart from the operator's `explicit_keep` | ship the full paragraph; a shorter prefix keeps nothing and fails silently |
| `preedit set-runs` | **address-keyed** (`at_para,run`) — writes one run's text and never rewrites its opener, so the run's `charPrIDRef` survives. That is the point: a form's blank is a ruled run, and only a value written INTO it sits on the rule (T112). Refuses an out-of-range address with the count it found, a duplicate address, and a paragraph whose only run has no `<hp:t>` (that is `fill-cells`) | the address, from `--full-text`'s `at_para` + `runs[].index`; `runs[].ruled` says which run, and `runs[].color_anomaly` says whether writing there inherits the form's guide colour (T128 — the table pre-flight never reaches a paragraph seat) |
| `form_inspect --full-text` | **address-keyed**, read-only (`[TABLE:]ROW,COL`) | the address |

**The scoped form for paragraph text is `at_para`.** It is to a paragraph what
`--at-cell`'s `ROW,COL` is to a cell: a 0-based document-order address
(sections in name order, then every `<hp:p>` open tag in document order,
outer paragraph before the cell paragraphs inside it). You do not have to
derive it — issue the unscoped map, read the refusal, paste the number:

```json
{ "2. 근 무 장 소 : ": { "text": "2. 근 무 장 소 : 경기도 화성시", "at_para": 35 } }
```

The refusal's `context_before` is what makes that choice possible on a pack:
five occurrences of the same clause label may have the same immediately
preceding clause, so each occurrence carries recent prior non-empty paragraphs
including the variant title (`표준근로계약서(기간의 정함이 없는 경우)` vs
`단시간근로자 표준근로계약서`).
`replace` also now always reports `occurrences` (how many places each key
resolves to, before scoping) next to `hits` (how many it wrote).

**One file still serves both `--map` and `--fill-map`** (T35). The value object
accepts the union of both halves' members — `text`, `at_para`,
`all_occurrences` (engine) and `other_occurrences` (gate) — each side reads
only its own and neither rejects the other's. An unknown member is a usage
error on both sides, so a typo cannot quietly mean "unscoped". Every other
consumer of `--fill-map` (the value-presence check, `value_spans`, each
module's declared-personal-number rules) sees the flattened plain string.

## 0B. Inherited-property attribution (T100)

The sibling question to §0. There, the risk is a gate resolving an ambiguous
match; here it is a gate blaming the artifact for a property it **inherited
from the blank form**. Two shipped findings had that defect — `imposition_mismatch`
(the blank 기안문 stores `PrintMethod=4`, so the fill introduced nothing) and
`fill_charpr_script_mismatch` (that form's own seats are `ratio=97`, so its
dominant typography read as an anomaly against a fine-print body baseline).

**Attribution is not relaxation.** A declaration the document violates is still
violated, so severity does not move. What the evidence adds is whether editing
the fill could ever fix it — because "your fill is wrong" and "this form cannot
satisfy this declaration" call for opposite actions. Findings that carry it
report `inherited: yes | no | unknown`, and `unknown` names why rather than
guessing.

**One vocabulary per class.** Every finding of class `format_noncompliance` carries `inherited`, whichever leg emitted it, and
a test asserts that over a real verify run rather than over a constructed
finding. T100 first shipped the tri-state on its own legs while the T40
charPr leg answered the same question in `form_baseline_*` keys only, so a
consumer filtering the class on `inherited` silently skipped the strongest
baseline comparison in the file — and could not tell that from "nothing
was inherited". Two names for one concept is the shape T35 and T36 already
closed here, which is why it is now asserted rather than merely agreed.

`--baseline` is what makes attribution possible, and its shape decides how much
can be answered: an `.hwpx`/`.hwp`/`.pdf` baseline supports it, a directory of
page images does not (no text layer, so point size, line pitch and content bbox
are not recoverable from it).

### visual_verify deterministic legs

| leg | finding | receives the baseline | compares | verdict |
|---|---|---|---|---|
| `page_budget` | `page_budget_violation` | **yes** (T100) | page count vs the same bound | attributes. A three-page form filed under `max: 2` fails before anyone types |
| `base_pt` | `format_noncompliance` | **yes** (T100) | same metric, same page | attributes. A page's median size on a form is dominated by the form's own labels |
| `line_spacing` | `format_noncompliance` | **yes** (T100) | ratio recomputed from the baseline's own pitch and size | attributes |
| `margins` | `format_noncompliance` | **yes** (T100) | per side, independently | attributes. Margins are the form's page setup outright |
| `fill_charpr_script` | `fill_charpr_script_mismatch` / `fill_charpr_script_inherited` | yes (T40) | the blank form's signature for the same seat | compares; an inherited signature is a named WARN. Carries the same `inherited` tri-state as the legs above (T101) — `no` only when the blank form's own run in that seat was positively identified and differs, `unknown` otherwise, because failing to find the evidence is not the same as finding the fill guilty. The `form_baseline_*` keys stay as the detail behind it |
| `print_method` | `imposition_mismatch` | n/a | conversion provenance instead (T38) | closed differently: a hash-bound record proves the normalization happened |
| `page_parity` | `imposition_mismatch` | no | — | correctly isolated: both counts are of the same artifact |
| `orientation` | `imposition_mismatch` | no | — | WARN only; landscape is a form property, so attribution would help but the severity never accused the fill |
| `text_length` / `page_content` | `blank_render` | no | — | correctly isolated: a render with no text is not a render, whatever the form looked like |
| `forbidden_text` | `guide_text_visible` | no | — | declaration-driven; the blank-derived half is the module keep policy, not this leg — and since T114 that half has a name: `protected_text` |
| `protected_text` | `guide_text_visible` (the keep side) | n/a | the module's declaration | the exact opposite claim to `forbidden_text`, and a family needs both: a 지원사업 form tells the applicant to delete its own scaffolding, a 동의서 carries 고지 that must STAY (PIPA §22). Declaring one string in both is refused rather than resolved — a silent precedence rule would make one module claim a lie. `story_edit` scope refuses the key outright, because that scope never runs the residue leg and a keep nothing consumes reads as honoured |
| `required_text` | `required_text_missing` | no | — | correctly isolated: the requirement is about the edit |

### Module and pipeline checkers

Inventoried across `check_residue`, `check_gongmun`, `check_minwon`, `check_hr`
and `check_grant` — the ones that can receive a blank-form baseline.
`check_layout` is a pure delegate to the bundled engine and owns no finding
class of its own. The report and style checkers are out of this class: they
judge prose content, not form inheritance.

Most rules already compare, and the good pattern is native to the codebase
rather than imported:

- `check_minwon` `byeolji_header_lost` **downgrades to WARN** with
  `basis: artifact_only` when no baseline is available, instead of HARDing
  blind. This is the reference behaviour.
- `check_hr` `clause_lost` judges against the baseline's own clause inventory
  precisely because the 2013 standard contract numbers itself irregularly
  (`1,2,3,4,5,6,8,9`, with clause 7 written mid-paragraph). A rule that assumed
  contiguity would blame every correct fill of that form.
- `check_grant` `packet_section_lost` derives *whether a section is optional*
  from the blank form, so the required/optional split is evidence rather than a
  list.
- `check_minwon` `seal_seat_overwritten` compares a seal cell's residual text
  against **that cell's own residue in the blank form**, not against a generic
  vocabulary.

Two open gaps, both recorded rather than quietly fixed:

- **Closed as T103, and narrower than first written.** All four work-type
  checkers let `--mode` force the derived state, and all four already recorded
  the override in `document.state_used` — so the data was there and my first
  note was wrong to call the verdict traceless. What was missing was any
  statement that the two DISAGREED, visible only to a reader who compared two
  sibling keys while `document.state` is the obvious one. `resolve_state` in
  `checker_base` now applies the override and returns a
  `document_state_declared_against_evidence` WARN naming both values and the
  basis; measured on the untouched kstartup blank form, `--mode auto` is
  unchanged and `--mode final` gains that WARN beside its two HARDs.
  It is a WARN, not a HARD: a declaration disagreeing with the evidence is not
  a defect of the document, and an operator legitimately knows the intended
  state before the seats are filled. Both directions are reported — declaring
  `blank` over a filled document SUPPRESSES the rules that would have judged
  it, which is the quieter mistake.
- **`check_grant`'s residue rules are correctly baseline-independent**, and
  this is where the T100 class does NOT apply. I nearly extended baseline
  attribution to `self_deleting_guide_retained` and
  `example_placeholder_retained` before reading what they assert: the form's own
  sentence instructs the applicant to delete it, so in a final submission the
  SURVIVAL of that inherited text is precisely the defect. Inheritance is not
  exculpatory here. A gate must not blame the artifact for an inherited
  property — unless the rule is about the inheritance itself.
- **Closed as T105.** `check_gongmun` `seal_slot_overwritten` now compares each
  slot with its own residue in the blank form, keyed by `(table, addr)`, which
  is `check_minwon`'s design ported across. The baseline **excuses and never
  accuses**: with no baseline the behaviour is unchanged, and a HARD becomes an
  info only on positive proof that the blank form printed that same residue in
  that same slot. That direction was a correction — the first cut downgraded the
  no-baseline case to a WARN, and an existing test disproved it by asserting
  that a name in the seal box is caught with no baseline at all.

A structural near-miss worth knowing: every module checker HARDs
`artifact_malformed` and returns **before** the baseline is loaded, even though
each module declares `wants: [baseline]`. No corpus form is malformed, so this
is theoretical, but it is the same shape as the two defects above.

Severity gated on a derived document state (`blank` / `draft` / `final`) rather
than on a baseline comparison is the other near-miss. State classification is
sound on all ten corpus forms under `--mode auto`; the risk is that a wrong
classification has no baseline backstop behind it.


## 0A. hwp_ingress

```sh
python pipeline/scripts/hwp_ingress.py inspect FORM.hwp
python pipeline/scripts/hwp_ingress.py convert FORM.hwp --adapter hancom \
  --out output/form_copy.hwpx --manifest output/proof/ingress/receipt.json
```

`inspect` is a privacy-safe CFB/FileHeader candidate check only. It exits 0
for a supported unprotected HWP5 container, 2 for usage, and 3 for refusal.
It does not extract body text, declare editability, or create render proof.

`convert` has one canonical adapter: `hancom`. It is Windows/licensed-Hancom
only, never automatic, and never falls back to LibreOffice or `rhwp`. Before
each COM child it requires the exact `tasklist | findstr /i hwp` result that
shows no existing Hwp.exe and it never uses `--kill-stale`. A process-wide
Windows mutex stays held through receipt-first/output-last publication. The
source and reopened output must return identical privacy-safe full-text hashes,
character counts, and table/picture/equation/shape/page/control/field counts
from `com_backend inspect --privacy-safe`; the staged HWPX ZIP/OCF/OPF/section
envelope and live source hash must also remain valid. The closed v1 receipt
contains hashes, sizes, aggregate match booleans, states, and reason tokens
only. `proof_grade` is always `none`: this is conversion execution, not PDF or
native-render evidence.

When a downstream workspace claims that the HWPX came through this ingress,
verify and retain the exact receipt:

```sh
python pipeline/scripts/hwp_ingress.py verify output/form_copy.hwpx \
  --manifest output/proof/ingress/receipt.json
python scripts/new_report.py ... --form output/form_copy.hwpx \
  --ingress-receipt output/proof/ingress/receipt.json
```

The scaffolder validates the supplied artifact before workspace creation,
revalidates `output/form_copy.hwpx` after the stage-0 copy, and copies the
receipt to `output/proof/ingress/receipt.json`. Missing, refused, stale,
duplicate-key, unknown-field, or hash-drifted claimed ingress exits 3. An
ordinary native-origin HWPX can still enter without making an ingress claim.
The receipt's source hash identifies the immutable bytes captured during the
conversion run. It does not embed or retain the source HWP, so long-term source
custody is an operator/workspace responsibility rather than a property of
`verify`.

## 0A.1. T86 `rhwp` diagnostic candidate

T86 is not a second ingress adapter. Pre-create the exact leaf
`work/stage-0/scratch/hwp-diagnostic`; the runner refuses missing roots,
`output` ancestors, symlinks, and arbitrary leaves. Use an opaque lowercase
hex run id and an explicit binary plus mandatory SHA-256 pin:

```sh
python pipeline/scripts/hwp_diagnostic_candidate.py run FORM.hwp \
  --diagnostic-root work/stage-0/scratch/hwp-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef \
  --rhwp <explicit-rhwp-binary> --rhwp-sha256 <64-lowercase-hex>
python pipeline/scripts/hwp_diagnostic_candidate.py verify \
  --diagnostic-root work/stage-0/scratch/hwp-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef
```

The child argv is exactly `rhwp export-hwpx INPUT OUTPUT --verify
--verify-pages`; source and binary snapshots are immutable, execution has a
bounded timeout/output budget and isolated cwd, and source/binary/output are
rehashed before exclusive receipt-first/candidate-last publication. The only
success artifact pair is `<run-id>/candidate.hwpx` plus a closed
`rigorloom/hwp-diagnostic-candidate/v1` receipt. Its comparison is always
`unknown/independent_oracle_not_run`, render is `not_run`, and
`proof_grade`/`submission_grade` are `none`/`false`.

This receipt is quarantine evidence only. Do not copy it to
`output/form_copy.hwpx`, `output/proof/ingress/receipt.json`, or a backend
receipt, and do not pass it to `new_report --ingress-receipt`. There is no
automatic binary discovery, `pyhwp`, or LibreOffice fallback. Missing or
invalid HWP, pin mismatch, binary/source drift, timeout, overflow, child
failure, invalid HWPX, receipt race, or verification drift exits 3 and leaves
no owned candidate or receipt. If ownership cannot be proven after an
exclusive run-directory reservation, the empty reservation or raced foreign
path is preserved, blocks that run id, and cannot pass `verify`.

## 0A.2. T87 Java diagnostic candidate

T87 is also quarantine-only and is not a T85 adapter. Pre-create the exact
`work/stage-0/scratch/hwp-java-diagnostic` leaf and supply an explicit Java
launcher plus SHA-256 and the one fat JAR whose bytes match the shipped lock:

```sh
python pipeline/scripts/hwp_java_diagnostic_candidate.py run FORM.hwp \
  --diagnostic-root work/stage-0/scratch/hwp-java-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef \
  --java <explicit-java> --java-sha256 <64-lowercase-hex> \
  --tool-jar <approved-hwp2hwpx-fat-jar>
python pipeline/scripts/hwp_java_diagnostic_candidate.py verify \
  --diagnostic-root work/stage-0/scratch/hwp-java-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef
```

The fixed bridge and tool snapshot run in the shared bounded process core.
JVM option environment variables are removed. The launcher is rehashed but
its surrounding JRE remains explicitly unbound. The wrapper canonicalizes the
known hwpxlib ZIP envelope and records any pruned declared-but-missing Preview/
RDF auxiliary rootfile before the unchanged T85 HWPX validator runs.
Comparison remains `unknown`, render `not_run`, proof `none`, and submission
false. Never copy this result into canonical output, T85/backend receipts,
Stage 0, or `new_report`; do not install/download Maven/JAR/JRE dependencies as
part of this runtime command.

## 0A.3. T88 paired bounded content/object agreement oracle

T88 is a receipt-only diagnostic comparison, not a third converter and not an
ingress or render route. Pre-create the exact
`work/stage-0/scratch/hwp-semantic-oracle` leaf. Supply both current producer
receipts; `verify` requires them again so the four current receipt/candidate
inputs are rebound:

```sh
python pipeline/scripts/hwp_semantic_oracle.py compare T86_RECEIPT.json T87_RECEIPT.json \
  --diagnostic-root work/stage-0/scratch/hwp-semantic-oracle \
  --run-id 0123456789abcdef0123456789abcdef
python pipeline/scripts/hwp_semantic_oracle.py verify \
  --diagnostic-root work/stage-0/scratch/hwp-semantic-oracle \
  --run-id 0123456789abcdef0123456789abcdef \
  --rhwp-receipt T86_RECEIPT.json --java-receipt T87_RECEIPT.json
```

The oracle requires exact T85 source-descriptor equality, the release-owned
T86 `rhwp` v0.8.2 allowlist, and the T87 toolchain lock. It snapshots each
input without following replacements, runs the public T86/T87 verifiers and
T79 story grammar over private copies, then follows OPF spine order while
preserving logical text, paragraph/story/table/span/control/equation and
referenced picture content. Ordinary whitespace remains semantic; converter-only
run splitting is coalesced. Cell row/column addresses are bound in
table topology. Styles, numbering, layout/pagination, and metadata are not
compared. Unknown/future/unsupported controls, drift, races, or
unknown package grammar refuse. The success receipt is
`rigorloom/hwp-semantic-oracle/v1` with comparison
`paired_converter_bounded_content_object_v1`, coverage
`text/story_table_topology/equations/referenced_pictures/explicit_controls`,
source fidelity
`not_established`, independence `converter_code_distinct_java_runtime_unbound`,
render `not_run`, proof `none`, and submission false. It contains no document
text/equation/picture hashes, IDs, names, paths, argv, stdout/stderr, or raw
candidate. Never feed it to T85, Stage 0, canonical output, rendering,
submission, or `new_report`; `syhwp` remains deferred.

## 0A.4. T89 bounded HWP source coverage

T89 is a BodyText-only wire-coverage receipt, not a converter or semantic
oracle. Pre-create the exact `work/stage-0/scratch/hwp-source-coverage` leaf
and supply an opaque run id:

```sh
python pipeline/scripts/hwp_source_coverage.py inspect INPUT.hwp \
  --coverage-root work/stage-0/scratch/hwp-source-coverage --run-id HEX
python pipeline/scripts/hwp_source_coverage.py verify INPUT.hwp \
  --coverage-root work/stage-0/scratch/hwp-source-coverage --run-id HEX
```

Only `<root>/<run-id>/receipt.json` is published. T85 CFB/FileHeader
preflight, exact direct `BodyText/Section0..N` naming, record hierarchy,
an exact 24-byte v1 ParaHeader, canonical paragraph-child order,
UTF-16/count checks, and raw-deflate EOF (or a validated eight-byte CRC32/ISIZE
trailer) are bounded and fail closed. Paragraph-header auxiliary fields and
DocInfo reference/numbering/style graphs remain explicitly unscanned. Clean BodyText coverage remains
`eligibility: unknown` because DocInfo reference/numbering/style semantics are
not scanned; known unsupported surfaces are `ineligible`, and no v1 eligible
outcome exists. All analyzed/refused outcomes exit 3. Comparison remains
unknown, render is not_run, proof none, and submission false. Never route this
receipt to ingress, Stage 0, canonical output, rendering, or `new_report`; no
syhwp installation, execution, or download occurs.

## 0A.5. T90 bounded HWP DocInfo coverage

T90 is a second source-side receipt, not an eligibility gate. Pre-create the
exact `work/stage-0/scratch/hwp-docinfo-coverage` leaf:

```sh
python pipeline/scripts/hwp_docinfo_coverage.py inspect INPUT.hwp \
  --coverage-root work/stage-0/scratch/hwp-docinfo-coverage --run-id HEX
python pipeline/scripts/hwp_docinfo_coverage.py verify INPUT.hwp \
  --coverage-root work/stage-0/scratch/hwp-docinfo-coverage --run-id HEX
```

The scanner reuses the immutable T85/T89 source snapshot, checks the exact
DocInfo record envelope, binds IDMappings counts to physical definition groups,
and range-checks zero-based BodyText ParaShape, Style, and CharShape IDs.
ParaCharShape positions use HWP WCHAR/control-stream units; they are not visible
text offsets. Definition payload meaning, numbering/bullet state, style
redirects, split state, and versioned tails remain explicitly unscanned.
Only `<root>/<run-id>/receipt.json` is published. Eligibility and comparison
remain unknown, render not run, proof none, and submission false; analyzed and
refused results exit 3 and cannot enter ingress, Stage 0, canonical output,
rendering, `new_report`, or submission.

## 0A.6. T91 bounded HWPX equation-envelope inventory

T91 is a receipt-only structural diagnostic. Pre-create the exact
`work/stage-0/scratch/hwp-equation-diagnostic` leaf:

```sh
python pipeline/scripts/hwp_equation_diagnostic.py inspect INPUT.hwpx \
  --diagnostic-root work/stage-0/scratch/hwp-equation-diagnostic --run-id HEX
python pipeline/scripts/hwp_equation_diagnostic.py verify INPUT.hwpx \
  --diagnostic-root work/stage-0/scratch/hwp-equation-diagnostic --run-id HEX
```

The scanner validates captured bytes with the T85 HWPX package contract,
follows the OPF spine, and matches equations by the official expanded QName,
not an XML prefix or raw byte substring. Each equation must have a direct run
parent and exactly one direct, nonempty, text-only script. The receipt exposes
only a source artifact descriptor and aggregate counts. It contains no script
text, script hashes, IDs, member names, paths, argv, stdout, or stderr.
`script_semantics` remains `not_scanned`; execution, native, and render remain
`not_run`; comparison is `unknown`; proof is `none`; submission is false. All
analyzed/refused results exit 3 and never enter ingress, Stage 0, canonical
output, rendering, `new_report`, or submission.

## 0A.7. T150 quarantine-only renderer runtime v2

T150 is an explicitly requested runtime diagnostic, not a backend and not a
certified-proof switch. Pre-create the exact workspace leaf
`output/proof/renderer-runtime-v2` and provide an opaque run id, one operator
binary, and one opaque certificate with mandatory SHA-256 pins:

```sh
python pipeline/scripts/renderer_runtime_v2.py inspect WORKSPACE \
  --run-id 0123456789abcdef --renderer-id rhwp_pdf \
  --binary RHWP_BINARY --binary-sha256 SHA256 \
  --certificate CERTIFICATE --certificate-sha256 SHA256
python pipeline/scripts/renderer_runtime_v2.py verify WORKSPACE \
  --run-id 0123456789abcdef --binary RHWP_BINARY --certificate CERTIFICATE
```

The closed adapter stages `output/out.hwpx` as `input.hwpx` and invokes only
`rhwp_pdf --version` followed by `rhwp_pdf export-pdf INPUT -o OUTPUT`. It
uses a private cwd, a minimal environment, bounded no-follow regular-file
captures, and final source/binary/certificate/output/receipt rebinds. The
receipt records `windows_job_kill_on_close_v1` on Windows or
`posix_process_group_v1` on POSIX. Ordinary descendants that remain in the
Job/process group are cleaned; a POSIX `setsid()` descendant and brokered
processes outside that boundary are not claimed, and no memory, process-count,
CPU, filesystem, or network isolation is provided. Equation-bearing HWPX
refuses with `equation_input_unsupported` before either child starts. The
receipt schema is `rigorloom/renderer-runtime-v2/v1`; its only persistent files
are `<run-id>/artifact.pdf` and `<run-id>/receipt.json`.
`inspect` emits the producer host's local policy token; `verify` accepts either
closed recorded token for cross-host checking, while legacy `contained_child_v1`
is rejected.

The receipt records `dependency_closure: unknown`, certificate validation
`not_run`, comparison `unknown`, render `not_run`, proof `none`, submission
false, promotion `not_run`, `execution.descendant_containment: not_established`,
and `execution.evidence_authentication: not_established`. Verification rebinds
current source, binary, certificate, artifact, root, and receipt bytes but does
not authenticate child-process evidence. It contains no source text, paths,
argv, child streams, or certificate contents. Never route it to `doc_backend`,
Stage 0/5/6, canonical output, `new_report`, or
`output/proof/backend/receipt.json`.
`CERTIFIED_PROOF_RELEASE_ENABLED` remains false and certified routing remains
`certified_runtime_unbound`; no binary, certificate, document, or corpus bytes
are installed or shipped.

## 1. story_graph

```
python pipeline/scripts/story_graph.py FORM.hwpx --out story-graph.json
```

This is a read-only, structure-only operation. It validates the exact HWPX
physical mimetype (first/stored/extra-free), reconciling every local ZIP header
to its central record including version-needed and DOS date/time, with empty
extras and only flags `0` or the DEFLATE fast flag `0x0004` (PKWARE APPNOTE bit 2),
and safe OCF rootfiles, then reads
the OPF `Contents/content.hpf` manifest/spine
and actual section roots for deterministic
section order (every actual section exactly once in a nonempty spine; no
manifest fallback), then inventories only namespace-valid nested `hp:ctrl` `header`,
`footer`, `footNote`, and `endNote` owners with their `hp:subList` paragraphs.
The JSON contains manifest-order member ordinals, role/ordinal structural
addresses, closed roles, counts, table ancestry, and schema-only structural
hashes only. It never emits member names, control IDs, body text, author
metadata, corpus content, URLs, absolute paths, raw-byte hashes, or template
fingerprints. A spine admits only definition/section roles. Table-cell stories
retain closed table/cell-encounter ordinal ancestry; raw cell coordinates stay
internal to duplicate validation;
story-in-story owners refuse. ZIP/XML bounds, unsafe or ambiguous ZIP/OPF references/media/coverage,
foreign namespaces and the documented closed-pair transplants (including
nested `hh:head`, `hh:bold` under `head`, and `hc:img` under `hp:run`), invalid
scoped identity/value fields, and unsupported
story-bearing controls (`hiddenComment`, memo/field/drawText/caption/masterPage)
refuse; no editing, selector, or render support is implied.

The bounded owner facts are grounded in the public [Hancom OWPML
model](https://github.com/hancom-io/hwpx-owpml-model), including its
`HeaderFooterType`, `NoteType`, `hiddenComment`, `fieldBegin`, `drawText`, and
`caption` classes. The CLI exits 0 for a passed graph, 2 for argparse or
output/usage errors, and 3 for a refused/unknown package. JSON and help are
UTF-8-safe; diagnostics do not echo document text, author metadata, or paths.

## 1A. story_edit

```
python pipeline/scripts/story_edit.py INPUT.hwpx --ops-file OP.json \
    --out OUTPUT.hwpx --receipt RECEIPT.json
```

This is one bounded, structural edit over one inventoried header, footer,
footnote, or endnote paragraph. `OP.json` is a closed object containing the
private exact `expected_input_sha256`, a schema-owned selector, and the
replacement. The selector ends at `/paragraph[n]` (there is deliberately no
`/run[n]`, text selector, raw control/member ID, cell coordinate, or graph
hash); the paragraph must contain exactly one direct text-bearing `hp:run`
with exactly one direct `hp:t`. Zero/multiple candidates, unsupported XML
shapes, stale source bytes, noncanonical ordinals, raw CR, and any address
mismatch refuse without outputs. Replacement text never appears in public
diagnostics or the receipt.

The bounded raw scanner accepts UTF-8 bytes (with an optional UTF-8 BOM) or no
encoding declaration; ISO-8859-1/UTF-16 and other declarations refuse. It
skips processing instructions only through `?>` and refuses DTD/internal
subset/entity declarations because no general entity lexer is exposed.

Mutation is a raw UTF-8 byte/span splice. Only the selected text span and its
own direct `hp:linesegarray` (when the replacement changes) may differ. The
source bytes are captured once and all inventory, parse, rewrite, and
verification steps use that immutable snapshot. Before publication, the
writer verifies T79 topology equality and compares archive comment, member
order, every non-target decompressed payload, stable `ZipInfo` metadata, raw
local records, central records, and the exact expected target payload/stream.
Output and receipt are staged and published exclusively (never overwritten),
with identity-safe rollback; receipt/write/preservation failure leaves no
owned final artifacts. A semantic no-op copies the package byte-for-byte.

The ZIP flag interpretation follows [PKWARE APPNOTE bit 2](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT): `0x0004` is the DEFLATE fast hint, not maximum compression.

The local receipt is exactly `{schema,status,address,changed,inventory,
preservation,render}` with `render: "not_run"`; it contains no source or
replacement text, IDs/names, coordinates, metadata, URLs, paths, graph hashes,
or artifact SHA. This CLI contract and this structural section make no
native/Hancom/PDF render claim: the current public corpus has no text-bearing
ordinary story fixture. The separate operator-local execution evidence later
in this guide does not change the receipt's `render: "not_run"` boundary.

## 1. probe

```
python engine/scripts/probe.py --json
```

One compact JSON line: `{schema, platform, render:{hancom_com, soffice,
renderers[], pdf_capable}, modules:{discovered, enabled, cli, run_modes,
checkers}, backends:"unconfigured"|{...}}`. Never fails (exit 0); degraded
sources appear as `{"error": ...}`. Injected into SKILL.md at load.

## 2. form_inspect

```
python engine/scripts/form_inspect.py FORM.hwpx --out profile.json
    [--baseline baseline.json] [--base-pt 10] [--line-spacing 160]
    [--full-text [TABLE:]ROW,COL|PARA:N ...]
```

Offline (no Hancom), `.hwpx` only. `profile.json` keys: `form_hash`,
`anchors` (headings/labels, in scan order), `placeholders`, `guide_text`,
`constraints` is parsed from the form's own printed text — `guide_text` AND `anchors`, because a budget stated in a plain `◦` bullet lands in anchors only (T129). `constraints` (base_pt / line_spacing_pct / max_pages — 0 detected on
fixed-grid forms; the fill gate there is layout immutability, not budget),
`page_metrics`, `table_map` (per-table `index`/`depth`, per-cell
`addr`/`span`/size/borderFill/shading/classification/`text_preview` +
`truncated` — plus the T30 pre-flight fields
`charpr`/`script_anomaly`/`charpr_suggested` on `fill_target` cells),
`body_baseline_charpr`, `script_anomaly_targets`, `spacer_cells`,
`fill_target_count`,
`break_audit`. `anchor_records[].text` is descriptive legacy evidence, not an
exact edit key: it may combine several runs and its whitespace is not a layout
instruction. `--baseline` additionally writes the font/size/color/spacing
distribution `baseline.json` consumed by `style_diff`. Exit 2 on file error;
otherwise 0 (diagnostic tool, never a gate).

**`text_preview` is `text[:30]` and says when it cut** — `truncated: true`
(T34). A silent cut is worse than a short one: the 협업기간 skeleton
`"20   .    .    .  ~  20   .    .    .   (     개월)"` previews as
`"20   .    .    .  ~  20   .   "`, which HIDES the `(     개월)` blank in
its middle, and a round-3 clean-room agent reasonably concluded the skeleton
ended there. Never treat a preview as the cell's text.

**`classification` has four values, and `spacer` is the one that saves you
work.** `guide` / `static` / `fill_target` / `spacer`. A **spacer** is an
empty cell the GRID needs and no writer ever touches; it is excluded from
`fill_target_count` and listed separately under `spacer_cells`
(`{table, addr, pattern}`). Three conjunctive conditions, all read off the
table itself — there is no address list anywhere in the code:

1. **no printed content** (it would otherwise be a `fill_target`);
2. **no label neighbour** — nothing names it, so nothing can be asked for it.
   A label neighbour is a printed cell ending exactly where this one starts on
   the same row band (`법인등록번호` → the cell to its right), or a printed
   cell directly above covering **exactly** this cell's column band (a matrix
   column header). Column-band equality is the whole rule: a form title or a
   prose paragraph also sits "above" a full-width strip without delimiting a
   field, and PPS's narrow `첨부서류` at (17,0) does not own the full-width
   strip at (18,0). Two stacked full-width bands are document flow, never a
   label/value pair;
3. **filler geometry**, one of two shapes the corpus grids actually use:
   - `full_width_band` — spans every column of its table AND is shorter than
     the shortest cell in that same table that manages to print text. It spans
     the label column too, so no field can live in it, and the grid itself
     proves no text line fits at that height. PPS (1,0)/(9,0)/(12,0) at 240
     and (16,0)/(18,0) at 1280/1080 against a 1860 shortest printed cell;
   - `stub_head` — the empty corner where a header row crosses a label column:
     every other cell in its row is a printed `static`, and the cell directly
     beneath it, sharing its exact column band, prints text. PPS (13,0), above
     `협업업체` and beside `업 체 명 / 대표자 / 전 화 / 사업장주소`.

On the PPS 협업승인신청서 that is 19 empty cells → **13 `fill_target` + 6
`spacer`**. A genuinely empty fillable cell keeps its label neighbour and
stays a `fill_target`: (2,7), the blank beside `법인등록번호`, is empty, is
not thin, and is named — so it is still yours to fill. Spacers carry no T30
pre-flight fields, because nothing will ever be written into them.

**Contract: structure only.** The profile carries anchor/guide strings, not
the document body. Do not dump section XML into context.

**`--full-text [TABLE:]ROW,COL|PARA:N` is the one documented escape from that
contract** (repeatable; `TABLE:` defaults to 0). It emits `full_text` with the
**exact** run text, whitespace intact, for only the cells or paragraphs named.
For an `anchor_records` entry, use its preedit-aligned `at_para` as
`--full-text PARA:at_para`; do not treat the descriptive `anchor_records[].text`
as a complete run key. It is opt-in per address on purpose: no flag dumps the
body, and each request is a decision you can justify. When fixed-padding
furniture lives in a separate run (for example, spaces before a trailing
`(인)` marker), inspect every run in that paragraph and update the affected
run(s) explicitly with the same `at_para`, preserving the marker/charPr, then
run the Hancom/PDF visual loop. Hit counts and other text gates prove targeting
and content, not whether a line wrapped or fit; there is no automatic-fit
guarantee.

## 3. preedit

Four offline operations (`replace` has two keying modes — string and
address); all validate every modified XML member is
well-formed BEFORE writing (a malformed member renders the whole document
blank in Hancom — structurally impossible here), and all strip the cached
`<hp:linesegarray>` of any paragraph whose text changed (stale linesegs
overprint at old coordinates).

```
python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx --map MAP.json [--allow-missing]
python engine/scripts/preedit.py replace IN.hwpx --out OUT.hwpx [--table 0] --at-cell 'ROW,COL[#RUN]=TEXT' ... --at-cell-append 'ROW,COL[#RUN]=TEXT' ... [--at-cell-map AT.json] [--at-cell-expect 'ROW,COL[#RUN]=SUBSTR' ...] [--at-cell-charpr 'ROW,COL[#RUN]=ID' ...]
python engine/scripts/preedit.py fill-cells IN.hwpx --out OUT.hwpx [--table 0] --cell ROW,COL=TEXT ... [--cell-line ROW,COL=TEXT ...] [--map CELLS.json] [--overwrite] [--charpr ID] [--charpr-per-cell ROW,COL=ID ...] [--parapr-per-cell ROW,COL=ID ...]
python engine/scripts/preedit.py delete-guides IN.hwpx --out OUT.hwpx [--color '#0000FF'|blue] [--charpr-ids 5,6]
python engine/scripts/preedit.py normalize-clones IN.hwpx --out OUT.hwpx --clone SRC:NEW [--set textColor=#000000] [--repoint FROM:TO:TEXT]
```

**Which one fills a form** — the decision rule, the worked 협업기간 example
and the whole end-to-end sequence live in **`references/fill-recipe.md`**.
Read it before your first fill; do not re-derive the branch from the CLI
contracts below. In one line: genuinely empty run → `fill-cells`; printed
skeleton to keep → `replace --at-cell-append`; printed text to replace wholly →
`replace --at-cell`; multi-run cell → the `#RUN` the refusal hands you;
`classification: spacer` → do not write there at all.

- `replace`: MAP.json is `{"placeholder text": "value", ...}`. Two tiers per
  key: (A) run-text strip-compare (whole-run match, whitespace-tolerant),
  (B) raw substring over the section XML — neither has a position qualifier,
  so **a key must resolve to exactly one place or the call is refused**
  (exit 2, `replace_key_ambiguous`; a generic key like `http://` also hits
  xmlns namespace URIs — measured 15 hits on a 1-table form). Values are
  XML-escaped. Output JSON: `{"ok": true, "hits": {key: n},
  "occurrences": {key: n}}` — `hits` is what was written, `occurrences` is how
  many places the key resolves to before scoping. 0-hit key = hard error, no
  output written (`--allow-missing` reports 0 instead — idempotent re-run
  mode). Replaced text inherits the run's original charPr (possibly
  guide-colored) — color normalization is `normalize-clones`' job.
  - **A repeated key is refused, not resolved** (T41). The 표준근로계약서 pack
    holds six variant contracts in one file and prints
    `2. 근 무 장 소 : ` on five of them, so the unscoped map wrote one
    employer's terms onto five contracts and **no offline gate caught it** —
    the label survives as a prefix, so `clause_block_lost`,
    `clause_lost` and `clause_text_consumed` all pass on the corrupted
    document. The refusal payload carries `keys[].occurrences[]` with
    `at_para`, `section`, `tier`, `matched`, `para_text`, `preceded_by` and
    `context_before` (recent prior non-empty paragraphs, including the variant
    title when the immediate predecessor is the same clause on every sheet) plus a
    ready-to-paste `suggested_map`.
  - **Scope with a value object.** `{"text": V, "at_para": N}` writes that one
    paragraph — the paragraph-text analogue of `--at-cell`. `{"text": V,
    "all_occurrences": true}` writes every occurrence, which is a decision you
    state rather than a default you inherit. The two together are a usage
    error, and an `at_para` that does not carry the key (or carries it twice)
    is a usage error naming the paragraphs that do.
  - The value object also accepts the gate's `other_occurrences` member so one
    file can be passed to `--fill-map` unchanged (T35); `preedit` ignores it.
    Any member outside that union is a usage error — a typo must never read as
    "unscoped".
  **Each span is written once** (T26): a value that contains its own key
  (`{" http://": " http://example.kr"}`) is applied exactly once and re-runs
  are no-ops — tier B never rewrites what tier A (or an earlier key, or an
  earlier run of the same command) already wrote.
- `replace --at-cell` — **address-keyed, no string at all** (T34). The form's
  printed seats are exactly the strings you cannot type reliably: their
  internal spacing is invisible in a 30-char preview and absent from
  `anchors`. So key on the address instead. `ROW,COL` is the `cellAddr`
  `table_map` reports and `--table N` is the same index as `fill-cells`
  (shared scanner). `#RUN` is the 0-based text-run index within the cell, the
  same enumeration `form_inspect --full-text` reports.
  - **Two explicit modes, never guessed.** `--at-cell ROW,COL=TEXT` replaces
    the run's **whole** text. `--at-cell-append ROW,COL=TEXT` keeps the
    printed prefix and appends — `" http://"` → `" http://host.kr"`, which is
    the *normal* shape of a labeled field, not an edge case (T31). Pick the
    one you mean; the tool will not infer it.
  - **Multi-run cells refuse.** A cell with more than one text run exits 2
    with `code_name: at_cell_run_ambiguous` and a `runs` array giving every
    index with its exact text. Neither "first run wins" nor "flatten the
    cell" is offered: PPS (15,0) carries the regulation sentence, the
    `년 월 일` 신청일 line, `신청인`, `(서명 또는 인)` and `조달청장 귀하` as
    separate runs, and either guess deletes real content. That refusal
    listing is also the cheapest way to learn the indices.
  - A cell with **no** text run is refused and pointed at `fill-cells` (T27).
  - `--at-cell-map AT.json` is `{"11,2": "값", "15,0#2": {"text": "…",
    "mode": "append"}}` — a bare string means `replace`.
  - `--at-cell-expect ROW,COL[#RUN]=SUBSTR` is a pre-write precondition,
    compared with **all whitespace removed on both sides**, so you can assert
    `우(-)` or `개월` without counting spaces. A mismatch writes nothing.
  - `--at-cell-charpr ROW,COL[#RUN]=ID` repoints the run's charPr; it is also
    how you get past the T30 pre-flight refusal below (the refusal prints the
    flag with `#RUN` filled in, and that form is accepted even if your
    `--at-cell` named the cell without `#RUN`).
  - Same guards as `fill-cells`: stale-lineseg strip on changed paragraphs
    only, well-formedness of every modified member before writing, T30
    charPr pre-flight, T22 dangling-charPr assertion when a charPr is
    repointed, duplicate targets are a hard error, and a refusal anywhere
    writes nothing. Re-runs are no-ops in **both** modes (`action: "noop"`,
    `replaced: 0`), so append never doubles a value.
  - Output JSON: `{"ok": true, "mode": "at-cell", "table": n,
    "tables_total": n, "replaced": n, "body_baseline_charpr_id": "0",
    "cells": [{"addr": [r, c], "run": i, "mode": "replace"|"append",
    "hits": 0|1, "action": "replaced"|"appended"|"noop", "before": "…",
    "after": "…", "charpr": id|null}]}`. `before` is the seat's **exact**
    text — that is where you read it from, not from the section XML.
  - `--map` and `--at-cell*` in one call is a usage error (exit 2). Chain two
    calls: mixed in one, string replacement and address offsets rewrite each
    other.
- `fill-cells`: addresses cells by the `cellAddr` **`table_map` reports** —
  `--cell ROW,COL=TEXT` (repeatable) or `--map` `{"2,3": "값"}`. `--table N`
  (default 0) indexes tables in document order, nested tables included and
  counted separately (outer first; `table_map` carries the same `index` and
  a `depth`). Merged cells own the top-left coordinate only, so addresses are
  not contiguous — a coordinate a rowSpan/colSpan covers has no cell and is a
  hard error listing the real addresses. Creates the `<hp:t>` inside the empty
  run and **preserves that run's charPr**. A non-empty target is refused
  unless `--overwrite`; a refusal anywhere in the batch writes nothing at all.
  Output JSON: `{"ok": true, "table": n, "tables_total": n, "filled": n,
  "body_baseline_charpr_id": "0", "cells": [{"addr": [r, c], "hits": 1,
  "action": "filled"|"overwritten", "previous": "…", "charpr": "0"|null,
  "parapr": "18"|null, "paragraphs": n, "paragraphs_reused": n,
  "paragraphs_created": n}]}`.
  - **A value is a list of paragraphs, not a line** (T39). 공문 본문 is
    hierarchical by regulation — `1.` / `가.` / `1)` / `가)`, each level its own
    paragraph indented two spaces further — so multi-paragraph is the normal
    case for a 본문 cell and one paragraph is the exception. Three spellings,
    one rule: a `--map` value that is a **JSON array** (one element per
    paragraph), a **newline** inside any value, or **`--cell-line ROW,COL=TEXT`
    (repeatable; the order you give is the paragraph order)**. Use
    `--cell-line` from PowerShell — a literal newline inside a quoted argument
    is not typable there. `--cell` still rejects a duplicated address, so
    multi-paragraph stays an explicit opt-in; naming one address with both
    `--cell` and `--cell-line` is a usage error (their relative order is
    undefined). Indentation is **leading spaces in the value**, which is what
    the regulation describes ("2타"); it is not a paraPr setting.
  - **Where the paragraphs go.** The blank paragraphs the form already reserves
    in that cell are used first, and only the remainder is created by cloning
    the **target paragraph whole** — same `paraPrIDRef`, same run `charPrIDRef`,
    never a fabricated default, never a `linesegarray`. Reuse-first is not an
    optimization: the 기안문 본문 cell reserves 18 blank lines, so creating
    instead of reusing lengthens the cell by the reserved amount, grows the
    table and spills a page (measured: 24 paragraphs into a 20-slot cell gives
    one content page plus an empty page). The slots stop at the first paragraph
    holding a **nested table** — that same cell holds 직인 and 발신명의 as
    nested tables with more blanks after them, and counting past them would put
    a 본문 line under 발신명의. `paragraphs_reused`/`paragraphs_created` report
    which happened.
  - **The post-flight uses the same paragraph split** (T44). JSON-array and
    newline fill-map values feed every non-empty paragraph to T30/T42, and an
    exact `ROW,COL` key scopes those matches to that seat. The render-presence
    leg joins the same paragraphs, so neither spelling turns the charPr safety
    check into an unavailable skip.
  - **`--parapr-per-cell ROW,COL=ID` (repeatable)** repoints the `paraPrIDRef`
    of the paragraphs this call **writes** (indent, alignment, line spacing);
    paragraphs it does not write are untouched. You need it when the form's own
    paraPr for those blanks is not a body format: the 기안문 본문 cell's blanks
    are CENTER-aligned because they share the cell with 발신명의, so a faithful
    fill centres the whole `1./가./1)` hierarchy and the indent disappears —
    repoint to the form's justified def (id 18 on that form) and the levels read
    correctly. Per-cell only, deliberately no batch-wide form (T32). A paraPr id
    with no definition is caught before writing (the T22 assertion's sister).
  - **`--charpr-per-cell ROW,COL=ID` (repeatable) is the charPr flag you will
    actually need**, and it belongs in the fill command you type — not only in
    the T30/T32 prose below. It sets **one** target's charPr and wins over
    `--charpr`; targets it does not name keep their own. The T30 pre-flight
    emits exactly this flag list as `suggested_flags`, so the normal fill call
    is `fill-cells --cell … --charpr-per-cell ROW,COL=<charpr_suggested> …`,
    not a bare `fill-cells --cell …`. An address it names that is not in the
    fill list, or a duplicated address, is a usage error — not a silent no-op.
  - `--charpr ID` **applies to the whole batch** (T32) and is only safe when
    every target in the call shares a charPr — which is precisely what the T30
    pre-flight breaks (anomalous cells need repointing, normal ones must be
    left alone). Prefer `--charpr-per-cell`.
  - Either flag then also runs the T22 dangling-charPr assertion before
    writing.
  - **Hancom must re-layout, and that is deliberate.** Every paragraph this
    command writes or creates loses its `linesegarray` (T24), so the artifact's
    own layout cache is incomplete until Hancom opens the file. Convert with
    `com_backend.py convert` (or let `visual_verify` do it) and let page parity
    take `pages_document` from `conversion`, or declare
    `expectations.pages_document`. Do **not** rely on the
    `artifact_layout_cache` source after a multi-paragraph fill — it
    under-counts.

### The charPr pre-flight before any fill (T30)

"Preserves that run's charPr" is only safe when that run's charPr *is* body
formatting. On the PPS form, cell (10,2)'s empty run carried a charPr
identical to body text **plus** `<hh:supscript/>`: a correct-looking fill
rendered at ~6.35pt raised off the baseline, and because nominal `height`
never changed, `charpr_check --base-pt 10` and `style_diff` both passed it.
So run the pre-flight — never guess the id, and never read `header.xml` by
hand (the structure-only contract above forbids exactly that):

1. **Inspect.** `form_inspect FORM.hwpx --out profile.json` reports
   `body_baseline_charpr` (`{id, height_pt, signature}` — the document's own
   body charPr) once at the top level, and per `fill_target` cell:
   `charpr` (the id the fill would inherit), `script_anomaly`
   (`true` when that charPr differs from the baseline on any of
   `supscript`/`subscript`/`ratio`/`relSz`/`offset`; `false` = checked and
   clean; `null` = could not be judged), and `charpr_suggested` (the baseline
   id to use instead). `script_anomaly_targets` lists just the anomalies.
   Also `color_anomaly` (T127): `true` = the inherited run is not black/auto,
   so the fill would render in the form's guide colour. The five script
   properties do not include colour, so `script_anomaly: false` never covered
   it. For the remedy use the profile-level `body_black_charpr`, NOT
   `charpr_suggested` — the body baseline can itself be coloured, and on the
   kstartup form it is.
2. **Check.** `script_anomaly_targets == []` → fill normally, nothing to do.
3. **Fill with the suggested id.** For each anomalous target pass
   `--charpr-per-cell ROW,COL=<charpr_suggested>`.

If you skip step 1, `fill-cells` refuses (exit 3, `code_name`
`fill_charpr_script_anomaly`) rather than silently producing a 6pt raised
fill. The refusal names **every** anomalous target in one shot and carries
`suggested_flags` — the ready-to-paste `--charpr-per-cell` argument list — so
the loop closes without ever opening the header. `replace --at-cell` runs the
**same** pre-flight on the seat run it is about to rewrite, and its refusal
carries `--at-cell-charpr ROW,COL#RUN=<id>` instead — so T34's address-keyed
path cannot be used to route around T30. Non-target runs are never
compared, so a genuinely superscripted footnote marker, ordinal or unit
exponent is out of scope by construction.
`visual_verify`'s `fill_charpr_script_mismatch` (T30) is the post-flight half
of the same comparison — both halves share one implementation
(`engine/scripts/charpr_script.py`) so they cannot disagree, which is the
whole point: anything the pre-flight lets through, the gate lets through.

**Expect anomalies to be common, and decide per cell.** Measured over the 10
converted corpus forms: 6 forms have at least one anomalous target and
`jeongbo-gonggae-cheongguseo` has 18 of 19. Most are a 2–5 percentage-point
`ratio` (character-width) delta — the form's own typography, not the
superscript trap. So treat it as a decision, not a rubber stamp:
`suggested_flags` normalizes the cell to body formatting, and if the cell is
*meant* to carry a different style, pass that style's id instead.

Keeping the cell's own style no longer costs you the post-flight (T40). Given
`--baseline BLANK.hwpx`, `visual_verify` compares each filled run against the
blank run named by the fill-map key in the SAME seat as well as against the
document body. An exact `ROW,COL` key may also inherit from a repeated block of
reserved empty runs in that seat, but only when at least two runs share one
charPr, the filled signature matches it exactly, and its only difference from
body is `ratio` (T42); one empty run, mixed ids or any script/scale/offset trap
still HARDs. A
signature the printed form already had is a WARN
(`fill_charpr_script_inherited`) naming the seat — it HARDs only on a difference
the fill actually introduced. Without an `.hwpx` baseline the HARD stands, and
says that the inheritance question was not checked.
- `delete-guides`: deletes paragraphs referencing guide charPr (by color or
  explicit ids) with the T18 guard built in: table/secPr/ctrl/object
  paragraphs are never deleted.
- `normalize-clones`: removes all prior clones, recreates exactly one per
  spec, recomputes `itemCnt` from actuals, then asserts no dangling charPr
  (T22) before writing.

Idempotence contract (all four): applying an operation to its own output is
content-identical (zip member contents; timestamps ignored). `replace --map`
needs `--allow-missing` for the second run, `fill-cells` needs `--overwrite`;
`replace --at-cell*` needs no flag — a run already holding the final value is
reported `action: "noop"`.

Geometry contract: an `--at-cell` / `fill-cells` edit changes text runs and
the cached `<hp:linesegarray>` of the paragraphs it touched, and **nothing
else** — cell count, addresses, spans, borderFill and cellSz are byte-identical
(fixed by regression on the real PPS seats).

## 4. check_residue

```
python pipeline/scripts/check_residue.py --form-profile profile.json --artifact OUT.hwpx
    [--keep-pattern REGEX] [--keep "exact anchor"]... [--fill-map MAP.json] [--out verdict.json]
```

`MAP.json` takes **either shape, at every consumer of the flag** (T35): a bare
`{key: value}` object (the `preedit replace --map` file) or a wrapper object
carrying a `fill_map` member (a `visual_verify --expectations` file). One
loader — `check_residue.load_fill_map` — serves `check_residue`,
`visual_verify` and every module checker, so one file works for all of them. A
wrapper whose `fill_map` member is not an object is a usage error naming both
shapes; it is never read as a bare map.

For a prefix-preserving label fill, the value is the complete resulting span,
not only the appended payload (T43): `{"수신": "수신 국가유산청장"}` is
attributable; `{"수신": "국가유산청장"}` leaves `수신` outside the value span
and correctly HARDs as residue. The keep derivation and residue delegate use
the same per-occurrence span rule.

The form scan's anchor+guide inventory IS the forbidden list. Exit 0 clean,
3 residue found / artifact malformed / pinned target missing, 2 usage.
Validity precedes scanning: every `section*.xml`+`header.xml` is XML-parsed
first (`artifact_malformed` is HARD).

Keep-list semantics by document family:

- **Report finals**: default `--keep-pattern` (numbered headings) is right —
  guide/placeholder text must be gone.
- **Form fills** (labels legitimately survive): pass the label anchors as
  `--keep` entries (derive: profile anchors minus the keys your fill
  consumed). With `guide_text: 0` forms the gate then only proves consumed
  placeholders are gone — state that honestly; do not blanket-keep with a
  match-all pattern.
- **Prefix-preserving fills** need `--fill-map MAP.json`, not `--keep`
  (T31). Filling a labeled field keeps the label as a prefix, so the key text
  survives INSIDE the value: `" http://"` → `" http://hanbit.example.kr"`,
  `" 우(     -     )"` → the same skeleton plus the address. With the map
  declared, an occurrence of a forbidden string that lies wholly inside an
  occurrence of a declared value is attributed to that value's span; an
  occurrence anywhere else still HARDs. `--keep " http://"` cannot express
  that — it suppresses the string document-wide, including a second field you
  never filled. Guide text is never attributable (same reason it is never
  keepable). Matching is whitespace-normalized on both sides, so the form's
  skeleton spacing need not survive verbatim. The verdict carries
  `fill_attribution {keys, value_spans, occurrences, attributed,
  unattributed}` and every residue row carries `occurrences`, `attributed`,
  `at_offsets` and a `context` snippet per unattributed hit.

## 5. charpr_check / style_diff

```
python engine/scripts/charpr_check.py --file OUT.hwpx [--base-pt 10] [--caption-pt 9]
python engine/scripts/style_diff.py OUT.hwpx --baseline baseline.json [--build-yaml build.yaml] [--out diff.json]
```

`charpr_check`: offline charPr proof — verdict booleans `body_ok`
(body runs are base_pt+black), `caption_present`, `title_larger`.
`style_diff`: any format value in the output that is neither in the form
baseline nor declared in build.yaml is an anomaly (exit 1). Together they
replace "look at the PDF" for format invariants.

## 6. layout_qa / fill_report

```
python engine/scripts/layout_qa.py --file verify.pdf [--bottom 25] [--gap 3]
python engine/scripts/fill_report.py --measure --pdf verify.pdf --build-yaml build.yaml [--out verdict.json]
```

`layout_qa`: per-page `bottom_white_pct`, `max_gap_lines` (body-line
multiples; figure-occupied spans exempt), `flags`. Thresholds change only by
argument, never by editing the script. `fill_report --measure` is the
headless fill-loop verdict: ordered `needs` list for the writer/assembler;
it never writes prose itself. Numeric gate first, visual check second;
designed whitespace on cover/summary pages is exempt (T5).

## 7. tidy_hwpx

```
python engine/scripts/tidy_hwpx.py FILE.hwpx --before "앵커" [--after "앵커"] [--keep 1] [--out OUT.hwpx]
```

Offline blank-paragraph cleanup anchored to explicit paragraphs — the COM
collapse pass is retired (T7: heading charPr contamination). Keeps `--keep`
blanks (default 1); never over-compress (1 blank around tables/figures is
designed).

## 8. com_backend / build_report / xml_backend

Windows + Hancom only (`render.hancom_com: true`). Heavy flows — operator
CLIs, not auto-fired.

```
python engine/scripts/com_backend.py inspect --file FORM.hwp
python engine/scripts/com_backend.py edit --file FORM.hwp --ops ops.json --save-as OUT.hwpx --export-pdf verify.pdf
python engine/scripts/com_backend.py set-cell --file FORM.hwp --addr ROW,COL --text "값" [--table 0] --save-as OUT.hwpx [--expect-empty | --expect TEXT]
python engine/scripts/com_backend.py convert --file IN.hwp[x] --to OUT.hwpx|OUT.pdf [--record PATH | --no-record]   # format by --to's extension
python engine/scripts/build_report.py --content bundle/content.md --form FORM.hwp > ops.json   # --dry-run: no Hancom
```

`inspect` first, always (anchors must exist before `goto_text`). Ops in
batches of 5–8 with verification between batches.

**Cell addressing (T28).** `set_cell`'s `addr: [row, col]` is the `cellAddr`
`table_map` reports; the op walks to it and verifies with `get_cell_addr()`
after every move, aborting without writing on any mismatch. The old
`row`/`col` were **keypress counts** (`TableLowerCell` × row, then
`TableRightCell` × col) — `TableRightCell` wraps across rows and
`TableLowerCell` jumps over rowSpans, so on the PPS form targeting cellAddr
(2,3) landed on (2,6), the `법인등록번호` label cell. That mode still exists
behind an explicit `"raw_traversal": true`; the validator rejects bare
`row`/`col` before Hancom starts. Always pass `expect_empty` (or
`expect: "current text"`) so a wrong landing refuses instead of overwriting.
`get_into_nth_table(n)` drifts across repeated calls inside one Hancom
session, so prefer the `set-cell` subcommand: **one invocation = one session =
one cell**, run serially, never `--kill-stale` (T21). The walk itself is
entry-point independent (it wraps), so drift cannot silently retarget it.
`convert` is the one PDF/format path: `--to` decides the target by extension, one serial invocation, never `--kill-stale`. It is exactly what `visual_verify` shells out to when handed an `.hwpx` without a `--pdf`.

**`convert` to PDF leaves a conversion record, and the next step needs it (T38).**
Converting an `.hwpx` whose `settings.xml` stores a non-zero
`PrintInfo/PrintMethod` (n-up 모아찍기 — the gongmun family does; 기안문 별지
stores 4) first rewrites that value to 0 in a *temporary copy*, because Hancom's
`SaveAs(PDF)` honours the stored print imposition and would fold the logical
pages into the PDF. The original is never modified. That normalisation is
reported in the stdout JSON as `print_method_normalized` **and** written to a
`rigorloom/conversion-record/v1` sidecar at `<--to>.conversion.json`, by
default and with no flag to remember. The sidecar exists because the canonical
recipe converts in one process and verifies in another: `visual_verify` gates
its print-method leg on evidence that the imposition was neutralised, and with
that evidence confined to a stdout nobody captured it saw none and HARDed
`imposition_mismatch` — unwaivably, since that class is deliberately not in
`SAFETY_CHECKS`. A gate cannot tell "did not happen" from "was not told".
`visual_verify` auto-discovers the sidecar beside `--pdf`; `--record PATH`
relocates it (then pass `--conversion-record PATH` to `visual_verify`), and
`--no-record` opts out, which restores the HARD. The record carries the sha256
of both the source and the output PDF, so it cannot be pointed at a different
artifact or a stale render — a mismatch is a usage error, not a weaker check.

For `.hwpx` prefer the offline `preedit fill-cells` — no Hancom, no drift. `build_report` refuses on
any SECTION-anchor mismatch (fix content.md, never bypass). ops JSON schema:
`engine/references/ops_schema.md`; equation syntax:
`engine/references/hwpeqn_cheatsheet.md` (brace every script: `x^{2}`, T13).
`xml_backend.py` applies the COM-free core of build_report ops to `.hwpx`
directly when no Hancom is present.

## 9. render_probe / privacy_scan

```
python pipeline/scripts/render_probe.py [--json]     # renderer matrix only (probe.py wraps this)
python pipeline/scripts/privacy_scan.py DIR          # HARD-clean required before anything ships
```

`privacy_scan` exit 0 = clean; binary office documents pass only through the
sha256-pinned corpus allowlist (`tests/corpus/forms/manifest.json`).

## 10. visual_verify

The autonomous render→judge loop. Two halves: this script is the
deterministic one (never skippable, never calls a model), and the vision one
is you, reading page PNGs against `references/visual-rubric.md`.

```
# pass 1 — machine half + vision task
python pipeline/scripts/visual_verify.py --artifact OUT.hwpx \
    [--pdf verify.pdf] [--conversion-record REC.json] \
    [--expectations exp.json] [--png-dir DIR] [--dpi 130] \
    [--baseline BLANK.hwpx|BASE.pdf|DIR] \
    [--form-profile profile.json [--fill-map MAP.json] \
                    [--keep TEXT ...] [--keep-pattern REGEX]] \
    [--content bundle/content.md] [--vision-scope all|targeted] \
    [--accept-without CHECK ...] \
    [--attempt M --max-fix-attempts N] --out visual_verdict.json

# pass 2 — merge the vision verdict you wrote
python pipeline/scripts/visual_verify.py --artifact OUT.hwpx --pdf verify.pdf \
    --expectations exp.json --vision-verdict vision.json --out visual_verdict.json
```

For the bounded `story_edit.py` render, use the two-pass contract with an
explicit current-PDF, comparable baseline, and hash-bound conversion record:

```sh
python pipeline/scripts/visual_verify.py --artifact EDITED.hwpx \
    --pdf native.pdf --baseline BLANK.pdf \
    --conversion-record native.pdf.conversion.json \
    --expectations story-expectations.json --out visual_verdict.json
```

`story-expectations.json` must carry the closed
`{"operation_scope":"story_edit", "required_text":[...],
"forbidden_text":[...]}` shape. The source must be `.hwpx`; the structural
story-edit receipt is intentionally unbound and is not evidence for this
check. Pass 1 is `vision_pending` (exit 3) after deterministic checks, with
fill-only checks listed under `deterministic.not_applicable_checks` rather than
waived. Pass 2 must supply a vision verdict covering every page. A story scope
refuses form-fill/profile/blank inputs, targeted vision, deterministic-only,
and `--accept-without`; malformed XML, invalid conversion page counts/parity,
incomparable baseline pages, missing required text, or visible forbidden text
remain HARD/usage failures.

The current native execution proof covers one public/sanitized header plus
disposable synthetic-donor footer, footnote, and endnote probes edited through
this contract, converted by Windows Hancom, and reviewed on all pages. The
note probes were not Hancom-authored anchors, so they do not prove insertion,
numbering, continuation, or general native-render parity. The independent
render-quality checker returned `unknown/unsupported_graphics_state` for all
runs, so none may be reported as a quality pass. The repository-only T84
research note retains the operator-local hash/page/delta matrix; it is not part
of the installed skill surface or a reproducible fixture.

**Exit codes — the whole table, one row per terminal state.** Nothing else is
reachable; in particular **exit 1 is not in the contract** and a run that
produces it is a bug (T36).

| `verdict` | exit | meaning |
| --- | --- | --- |
| `pass` | 0 | accepted — both halves clean AND every SAFETY check ran (or was waived) |
| `deterministic_pass` | 0 | `--deterministic-only` smoke check; `acceptance: false` by construction |
| `vision_pending` | 3 | machine half clean, vision half still owed |
| `fail` | 3 | a HARD finding, deterministic or vision |
| `safety_incomplete` | 3 | nothing failed, but a SAFETY check never RAN and was not waived |
| `usage_error` | 2 | bad input, unreadable file, unwritable `--out` |

- **`acceptance: true` is a claim that every SAFETY check RAN** (T36). The
  SAFETY set is `page_parity`, `xml_wellformedness`, `check_residue`,
  `empty_cell_expected_fill`, `fill_charpr_script_mismatch` — named once, in
  `visual_verify.SAFETY_CHECKS`, and published in every verdict under
  `deterministic.safety_checks`. If any of them lands in
  `deterministic.skipped_checks`, the verdict is `safety_incomplete` (exit 3)
  with a HARD `acceptance_safety_skipped` naming which ones and why. The pixel
  diff is deliberately NOT in the set (T35: a renderer-less machine loses one
  check, not the run) and neither are the `format_noncompliance/*` tolerance
  legs — declining to pin a tolerance is not hiding a defect class.
- **T82 story scope is the bounded exception for fill-only checks, not a
   waiver.** With `expectations.operation_scope: "story_edit"`, the closed
   `required_text`/`forbidden_text` contract and explicit PDF, comparable
   baseline, and hash-bound conversion record are required. When no
   form-fill/profile inputs exist, `check_residue`,
   `empty_cell_expected_fill`, and `fill_charpr_script_mismatch` are recorded
   only under `deterministic.not_applicable_checks`; they never enter
   `acceptance_waivers` or ordinary `deterministic.skipped_checks`.
- **Waive a check only on the record.** `--accept-without CHECK` (repeatable,
  closed vocabulary = the SAFETY set) lets acceptance proceed without one, and
  the verdict carries `acceptance_waivers: [...]` plus the unwaived remainder in
  `acceptance_blockers`. Waiving is per check, never a blanket switch, and it
  hides nothing: the skip is still reported in `deterministic.skipped`.

- **Rendering.** `--pdf` if you have one; an `.hwpx` without one goes through
  ONE serial `com_backend.py convert` (never `--kill-stale`). No Hancom and
  no `--pdf` is a usage error, never a pass. Pages are rasterized to
  `--png-dir` (default `<pdf>_pages/`) at `--dpi` (default 130). Equation
  scope errors (T13) need a separate `--dpi 300` run on that page.
- **A PDF converted by an earlier step brings its provenance with it** (T38).
  `com_backend.py convert` writes a `<pdf>.conversion.json` sidecar recording
  what that conversion did — notably whether it had to normalise a stored n-up
  `PrintMethod` — and this script auto-discovers it beside `--pdf`, or takes
  `--conversion-record PATH`. The record then populates exactly the
  `conversion` dict this script would have built had it done the convert
  itself, so the print-method leg is satisfied by proof and `pages_document`
  comes from Hancom's own `PageCount` (`pages_document_source: conversion`).
  Verify it landed: `deterministic.conversion.provenance` reads
  `conversion_record`. The record is believed only when bound to the bytes
  under verification — its `source_sha256` must match `--artifact` and its
  `pdf_sha256` must match `--pdf`; a mismatch, a missing hash or a wrong schema
  is a **usage error (exit 2)**, never a quiet accept, which is also what
  catches an artifact edited after its PDF was rendered. With **no** record and
  a source storing `PrintMethod != 0`, the `imposition_mismatch` HARD stands
  unchanged: this is plumbing for evidence, not a relaxation of the check, and
  `imposition_mismatch` remains outside the SAFETY set and therefore unwaivable.
- **Deterministic backstops**, all merged into one findings list: hwpx
  section/header XML validity (T23 `artifact_malformed`); zero-text document
  and zero-content page (T25 `blank_render`); stored `PrintInfo/PrintMethod`
  plus `pages_document` vs `pages_pdf` (W6.2 `imposition_mismatch`, see the
  page-count sources below); declared
  page budget; declared `base_pt` / `line_spacing_pct` / `margins_mm`;
  declared `fill_map` values present in the render; script/scale/offset
  inheritance on fill-modified runs (T30 `fill_charpr_script_mismatch`);
  `forbidden_text`; `layout_qa` (mapped onto rubric classes, unmapped findings
  preserved verbatim); `check_residue` with `--form-profile`; `check_density`
  with `--content`; pixel diff with `--baseline` (changed-region bboxes per
  page, so a caller can assert unchanged regions stayed unchanged).
- **`pages_document` is never yours to remember** (T36). Page parity takes the
  first source it can get and records which in
  `deterministic.pages_document_source`: `conversion` (Hancom's own `PageCount`
  — from a convert this script performed, or from a hash-bound conversion
  record left by one that an earlier step performed, T38) →
  `expectations` (an explicit declaration) →
  `artifact_layout_cache` (derived here from the artifact's own
  `<hp:lineseg vertpos>` cache, counting the points where `vertpos` stops
  increasing; cell-relative linesegs inside `hp:tc`/`hp:subList` are excluded).
  Parity skips only when all three are unavailable, and the reason then names
  which leg was missing. The derived source is honest about its limits: the cache
  under-counts when the body lives inside tables and goes stale after an offline
  XML edit (T24), and n-up imposition can only FOLD pages, so on that source only
  `pages_pdf < pages_document` is HARD — the other direction is a WARN naming
  both explanations. An authoritative source keeps both directions HARD.
- **`--baseline` names the BLANK FORM, so it takes one** (T35). Pass the
  `.hwpx`/`.hwp` blank and it is converted through the same ONE serial
  `com_backend.py convert` the artifact takes (never `--kill-stale`); an
  already-rendered `.pdf` or a directory of page images is used as-is. With no
  renderer on the machine, the pixel diff is reported under
  `deterministic.skipped` with a reason (and `baseline_diff.skipped`) — one
  check lost, not the whole run, and never a crash. The converted PDF is
  recorded as `baseline_diff.baseline_pdf`. An `.hwpx` baseline feeds a SECOND
  consumer that needs no renderer at all: the T30 seat comparison (T40, below),
  reported under `deterministic.fill_charpr_script.form_baseline`. That is why
  the flag is worth passing even on a machine that cannot render.
- **Residue on a FORM FILL needs a keep list.** The residue gate's forbidden
  list is auto-derived from the form scan, so on a fill every surviving label
  reads as residue and the delegate can never return 0. Forward one:
  `--keep TEXT` (repeatable) and `--keep-pattern REGEX` go straight to
  `check_residue`, and `--fill-map MAP.json` derives the standard form-fill
  keep list for you — `(anchors ∪ placeholders)` minus the entries the fill
  mapping targeted (whitespace-normalized substring match, either direction).
  `MAP.json` is the `preedit replace --map` file (a bare `{key: value}`
  object) or a wrapper object with a `fill_map` member — either shape, here and
  at every other consumer of the flag (T35). Guide text is never keepable. The
  derivation is recorded
  under `deterministic.residue_keep` (`derived_keep`, `consumed`, `unfilled`,
  `explicit_keep`, `keep_pattern`, `keep_total`) so the invocation is
  auditable. `--keep` / `--keep-pattern` without `--form-profile` are a usage
  error.
- **`--fill-map` and `expectations.fill_map` are ONE concept, not two inputs**
  (T36). They used to be different: the flag drove the residue keep derivation,
  while the *expectations member* was what activated the declared-value presence
  check (`empty_cell_expected_fill`) and the T30 charPr post-flight — so a caller
  who passed only the flag got a verdict with both of those in `skipped[]`.
  Passing `--fill-map` now **seeds** `expectations.fill_map`, so one map drives
  all three consumers and `deterministic.fill_map_source` says where it came from
  (`cli`, `expectations`, or `cli+expectations`). Passing the same expectations
  file to both flags is the blessed invocation; passing two **different** maps is
  a usage error, because there is no honest answer to which one the artifact was
  filled with. `--fill-map` alone no longer needs `--form-profile` (it is
  meaningful without the residue delegate); `--keep`/`--keep-pattern` still do.
- **A correct fill KEEPS the label — that is the normal shape, not an edge
  case** (T31). Filling a labeled field means keeping the label as a prefix:
  a URL field goes `" http://"` → `" http://hanbit.example.kr"`, a zip field
  keeps its `" 우(     -     )"` skeleton and appends the address. The key
  text therefore survives by construction, and a derivation that assumes it
  VANISHED fails a correct fill (second clean-room run: a lost retry and a
  hand-built `--keep`). So the derivation is artifact-aware and the map is
  forwarded to the delegate:
  - a key is **consumed** when its mapped VALUE is present in the document
    (whitespace-normalized), and falls back to key-absence when the value is
    not found — no value and the key gone too is equally nothing to flag;
  - a key whose value is absent while the key text is still there is
    **unfilled**: neither kept nor consumed, so it HARDs. That is the point;
  - surviving key text inside a value is attributed to that value's SPAN, per
    occurrence — never suppressed document-wide, so a second, genuinely
    unfilled occurrence of the same key still HARDs and the finding reports
    its offset and surrounding context.
  Do not hand-build `--keep` for a prefix-preserving fill: `--keep " http://"`
  blinds the gate to every unfilled URL field in the document.
- **T30, the invisible superscript.** With an `expectations.fill_map`, every
  run whose text carries a declared value is compared against the document's
  body-baseline charPr on `supscript`/`subscript`/`ratio`/`relSz`/`offset`. A
  difference is HARD `fill_charpr_script_mismatch` (class
  `format_noncompliance`): nominal height is unchanged in this trap, so
  `charpr_check` and `style_diff` cannot see it. Only fill-modified runs are
  in scope, so intentional superscripts are never flagged. This is the
  POST-flight half; the pre-flight (`form_inspect` `script_anomaly` →
  `fill-cells --charpr-per-cell`) is under §3 and shares this comparison
  code, so a fill that passed the pre-flight cannot fail here for this reason.
  **The body baseline is not the only baseline (T40).** On a mostly-empty form
  the heaviest charPr is boilerplate — the 기안문 별지's body baseline is its
  비고 fine print — so every real seat differs from it and the check inverts.
  Pass the blank `.hwpx` as `--baseline` and each fill-modified run is also
  compared against the **exact blank run named by the fill-map key inside its
  own seat**, addressed by `cellAddr`. The seat cannot be keyed by the filled
  text because an `--at-cell-append` fill changes that text on purpose; the
  fill-map key supplies the pre-fill label. An unrelated sibling run in a
  multi-run cell is never a baseline. A run HARDs only when it differs from
  BOTH baselines, so the
  seat can only downgrade a finding, never create one:
  - the blank form's same seat already carries this signature → WARN
    `fill_charpr_script_inherited`, with `seat` and `form_baseline_charpr_id`;
  - it carries a different one → HARD, `form_baseline_differing` naming which;
  - it carries no text at all (a genuinely empty run) → HARD; an empty seat has
    nothing to inherit, which is the trap's own shape;
  - no `.hwpx` baseline (none given, or a `.pdf`/image directory) → HARD with
    `form_baseline_checked: false` and the reason. The check never weakens when
    it cannot see the form, and `fill_charpr_script_mismatch` stays in the
    SAFETY set either way.
- **A cell that is blank ON PURPOSE is declared, not inferred** —
  `declared_blank`. A form's signature line, a staff-only box and a field you
  simply have no value for look identical in the render, so before this every
  accepted tier of the clean-room run emitted the SAME two
  `empty_cell_expected_fill` warns (y=91.2 and y=350.3 on the PPS fill), and a
  warning every correct run emits trains people to ignore warnings. Three
  changes, one rule — *say it or see it, and never see it twice*:
  - **suppressed when the grid owns the blank.** A wholly blank detected
    header row (`blank_band`) or the empty corner where column headers meet
    the row labels (`stub_head`) is structure, not an omission — the same two
    shapes `form_inspect` reports as `spacer` (§2). PPS's y=350.3 was the
    협업업체 matrix stub head.
  - **suppressed when you declare the seat.** `declared_blank: [label]` in
    `expectations` — or in the wrapper-shaped `--fill-map` file, so ONE file
    still carries the whole fill. `intentionally_blank` is accepted as an
    alias and folded into the same list (two spellings of one concept is the
    T36 defect shape). Matching is whitespace-normalized and containment-based
    in either direction, so `성명` reaches the form's `성    명`. The
    declaration drives BOTH legs: the `fill_map` presence check and the layout
    one.
  - **otherwise reported by LABEL.** The finding used to carry only `at_y` — a
    page coordinate says "some table on this page has a blank header cell" and
    leaves finding it to you. It now carries `seat` (the printed cell to its
    left in the header row, else the cell beneath it), `col` and the header
    row itself. PPS's y=91.2 reads `seat: 법인등록번호`.
  Suppression is never silent: `deterministic.layout_qa.empty_cell_suppressed`
  lists `{reason, label, at_y, page}` per suppressed cell, and the verdict
  carries `deterministic.declared_blank` with `declared_blank_source` naming
  every surface it arrived on.
- **`expectations.json`** keys: `pages_document`, `page_budget {min,max}` or
  `max_pages`, `base_pt`, `line_spacing_pct`, `margins_mm {top,bottom,left,
  right}`, `fill_map {label: value}`, `declared_blank [label]`
  (alias: `intentionally_blank`), `blank_pages [n]`, `forbidden_text [str]`.
  Everything absent is listed
  under `deterministic.skipped` — the verdict says what it could NOT check.
- **`visual_verdict.json`** shape: `{schema, artifact, pdf, dpi, png_dir,
  rubric, rubric_path, acceptance, acceptance_waivers[], acceptance_blockers[],
  pages[], deterministic{}, vision{}, vision_required[], loop{}, hard[], warn[],
  counts, verdict}`. `verdict` is one of `pass`, `fail`, `vision_pending`,
  `deterministic_pass`, `safety_incomplete`, `usage_error` — see the exit table
  above. `deterministic` carries `safety_checks[]`, `declared_blank[]`,
  `declared_blank_source[]`, `skipped[]` (human
  `"check: reason"` strings), `skipped_checks[]` (the keys alone),
  `pages_document_source` and `fill_map_source`.
- **The vision handback** (`--vision-verdict`) is
  `{"schema": "rigorloom/visual-vision-verdict/v1", "pages_reviewed": [...],
  "findings": [{"page", "class", "severity", "evidence"}]}`. `class` is
  validated against the rubric's closed vocabulary — an unknown class or
  severity, or an out-of-range page, is a **usage error (exit 2)**, not a
  finding. Every page in `vision_required` must appear in `pages_reviewed`
  or you get a HARD `vision_incomplete`.
- **`--deterministic-only`** can exit 0 but sets `acceptance: false`. It is a
  smoke check. Only a run with a complete vision verdict is an acceptance.
- **`--max-fix-attempts N`** does not loop for you: the loop lives in the
  caller (fix → re-render → re-run). Pass `--attempt M` and once `M >= N`
  with the run still not accepted, the script adds a HARD `loop_exhausted`
  and you escalate to a human instead of retrying.
