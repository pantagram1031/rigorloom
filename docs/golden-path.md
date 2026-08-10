# Golden path: clone to a graded artifact, without Hancom

This walks one report workspace from a fresh clone through the whole stage
graph to a Stage 6 `submission_preflight` verdict, using the Hancom-free
`hwpx` document backend. Every command below is a real script in this repo,
verified against its own `--help` output and source while writing this doc.
Paths use `<WS>` for the absolute workspace path and `<REPO_ROOT>` for this
checkout's root; run everything with `<REPO_ROOT>` as the working directory.

Two things this doc is honest about up front:

- **Content generation is out of scope here.** Stages 1–4 (research, design,
  sim, write) produce the evidence and prose that later gates check. This doc
  shows the mechanical stage-machine commands to move through them, not how
  to write a report — that is what the stage playbooks under
  `modules/report/references/playbooks/` and the `report-pipeline` skill are for.
- **Only `hwpx` and `hwp` backends can reach a graded verdict.** The `bundle`
  and `docx` backends never produce `output/out.hwpx`, so they cannot pass
  the Stage 5.3 `format_check` gate or reach Stage 6 (see the backend table
  in [README.md](../README.md)). If you just want to see the pipeline run
  anywhere with zero dependencies, stop after step 4A below.

## 0. Prerequisites

- Python 3.10+, standard library only, for everything except the `hwpx`/`hwp`
  backends.
- For the Hancom-free `hwpx` path: nothing extra — the engine is bundled at
  `engine/scripts` (`fill_report.py`, `eqn.py`, `xml_backend.py`,
  `form_inspect.py`). None of these require Hancom or Windows for the XML
  engine path.
- For the full `hwp` path (native Hancom proof): Windows + a licensed Hancom
  Office HWP install, plus the engine's optional `[windows]`/`[proof]` extras.
  This doc calls out each place that path diverges.

## 0A. Admit a binary HWP without treating it as HWPX

Binary `.hwp` is not XML. Before any native conversion, run the bounded
cross-platform candidate check:

```sh
python pipeline/scripts/hwp_ingress.py inspect FORM.hwp
```

Exit 0 means only that the input is a bounded, supported HWP5 CFB candidate:
it is not content parity, editability, or render proof. Protected, malformed,
unsupported, or unavailable input exits 3 with a closed reason. The JSON never
contains document text, stream names, command output, or an absolute path.

Canonical conversion is explicit and Windows-Hancom-only:

```sh
python pipeline/scripts/hwp_ingress.py convert FORM.hwp --adapter hancom \
  --out output/form_copy.hwpx --manifest output/proof/ingress/receipt.json
```

The converter captures immutable source bytes, holds a crash-safe Windows
named mutex across the full operation, and performs the exact Hwp.exe precheck
without killing processes before each of its three COM children. It compares
privacy-safe full-text hashes, character counts, and the closed
table/picture/equation/shape/page/control/field aggregate from the same COM
extractor on the source and reopened HWPX. It then validates the physical ZIP,
OCF, OPF/spine, and section envelope, rechecks the live source hash, writes the
hash-bound receipt first, and makes the output link the final commit marker.
The receipt schema is
`rigorloom/hwp-ingress/v1`; even a successful conversion has
`proof_grade: none` because conversion execution is not a PDF render. A
LibreOffice or `rhwp` diagnostic must never replace the canonical form.

Verify the consumer binding before claiming binary-HWP provenance:

```sh
python pipeline/scripts/hwp_ingress.py verify output/form_copy.hwpx \
  --manifest output/proof/ingress/receipt.json
python scripts/new_report.py ... --form output/form_copy.hwpx \
  --ingress-receipt output/proof/ingress/receipt.json
```

The verifier closes receipt keys/types/states and reruns the physical
ZIP/OCF/OPF/section plus exact output hash/size/count checks. The scaffolder
revalidates the workspace copy and retains the receipt; without
`--ingress-receipt`, an HWPX is treated only as an ordinary native HWPX and no
binary-ingress provenance is claimed. The receipt's source hash names the
immutable source snapshot used during conversion; it does not retain or later
re-prove the caller's original HWP bytes if that source is deleted or changed.

## 0A.1 Quarantined `rhwp` diagnostic candidate (T86)

This route is deliberately separate from canonical ingress. Create the
`hwp-diagnostic` scratch directory first, then use only an explicit binary and
its mandatory lowercase SHA-256 pin:

```sh
mkdir -p work/stage-0/scratch/hwp-diagnostic
python pipeline/scripts/hwp_diagnostic_candidate.py run FORM.hwp \
  --diagnostic-root work/stage-0/scratch/hwp-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef \
  --rhwp <explicit-rhwp-binary> --rhwp-sha256 <64-lowercase-hex>
```

The runner snapshots the source and binary, invokes the exact list
`rhwp export-hwpx INPUT OUTPUT --verify --verify-pages` with bounded timeout
and output, validates the HWPX with T85, and publishes only the quarantined
`rigorloom/hwp-diagnostic-candidate/v1` pair under
`work/stage-0/scratch/hwp-diagnostic/<opaque-run-id>/`. The receipt binds only
the run-local candidate hash, bytes, and tables/pictures/equations counts;
comparison is always `unknown/independent_oracle_not_run`, render is
`not_run`, and `proof_grade` is `none`.

Do not copy this candidate to `output/form_copy.hwpx`, do not write an ingress
or backend receipt, and do not call `new_report --ingress-receipt` with it.
T86 has no `pyhwp` or LibreOffice fallback. Source/binary drift, timeout,
overflow, invalid output, races, and receipt mismatch exit 3 and leave no
owned candidate or receipt. If ownership cannot be established after an
exclusive directory reservation, an empty quarantined reservation or a raced
foreign path may remain and blocks that run id; it never verifies or enters
canonical processing. `verify` rechecks the exact receipt and current
candidate bytes.

## 0A.2 Quarantined Java diagnostic candidate (T87)

T87 is a separate operator-supplied Java experiment, not another ingress
adapter. Create the exact leaf and use only the release-approved fat-JAR hash:

```sh
mkdir -p work/stage-0/scratch/hwp-java-diagnostic
python pipeline/scripts/hwp_java_diagnostic_candidate.py run FORM.hwp \
  --diagnostic-root work/stage-0/scratch/hwp-java-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef \
  --java <explicit-java> --java-sha256 <64-lowercase-hex> \
  --tool-jar <approved-hwp2hwpx-fat-jar>
```

The source first passes T85. The fixed source bridge runs with one staged JAR,
closed JVM flags/environment, process-tree containment, bounded output, and
no network/Maven discovery. The Java launcher is rehashed but the surrounding
runtime is deliberately labeled unbound. The wrapper canonicalizes only the
known ZIP envelope and closed absent auxiliary-rootfile defect, records that
count, then requires the unchanged T85 HWPX validator. The receipt is
`rigorloom/hwp-java-diagnostic-candidate/v1` with comparison `unknown`, render
`not_run`, proof `none`, and submission false. Both raw candidate layout and
receipt are rejected by `new_report`; no JAR/JRE/class/corpus bytes ship.

## 0A.3 Paired bounded content/object agreement (T88)

T88 compares the current T86 and T87 receipts as a separate diagnostic
artifact. It requires the pre-created `hwp-semantic-oracle` leaf and both
receipt paths; `verify` requires those paths again so all four producer inputs
are rebound before accepting an old agreement receipt. It captures immutable
bytes, invokes the public producer verifiers over those snapshots, then uses
the bounded content/object comparison in OPF spine order. It compares text,
story/table topology (including cell addresses), equations, referenced
pictures, and explicit controls; styles, numbering, pagination, and metadata
are outside coverage. An agreement is never native parity, render proof,
canonical ingress, Stage 0 input, or submission evidence, and `syhwp` is
explicitly deferred.

## 0B. Inspect story topology without reading text

When a workflow needs to understand headers, footers, notes, or nested table
ancestry before editing, run the bounded privacy-safe inventory:

```sh
python pipeline/scripts/story_graph.py FORM.hwpx --out story-graph.json
```

The inventory first validates the exact HWPX mimetype as the first stored,
extra-free ZIP entry and validates every local ZIP header against its central
record, including version-needed and DOS date/time. Its v1 ZIP envelope permits only empty extras and flags `0` or the
public-corpus-proven DEFLATE fast flag `0x0004` (PKWARE APPNOTE bit 2, only with DEFLATED); encryption,
data descriptors, all other flags, non-ASCII paths, and any mismatch refuse.
It then validates every safe, present OCF rootfile, then
derives section order from the `Contents/content.hpf` OPF spine and actual
section roots (there is no manifest-order fallback: every actual section must
appear exactly once in a nonempty spine), validates the documented closed Hancom OWPML parent pairs used
by this inventory,
and models only nested `hp:ctrl` `header`/`footer`/`footNote`/`endNote` owners
with their `hp:subList` paragraphs. A table-cell owner is represented with its
closed table ordinal and cell encounter ordinal ancestry (raw cell coordinates
remain internal for duplicate validation only); a story inside
another story refuses. Its JSON contains manifest-order member
ordinals and role/ordinal structural addresses, closed roles, counts, topology,
and schema-only structural hashes;
it never contains a source member name, control ID, body text, author metadata,
URL, corpus content, absolute path, raw byte hash, or template fingerprint.
ZIP/XML availability bounds, unsafe or
ambiguous OPF references/media/coverage, foreign namespaces and the documented
closed-pair transplants (including nested `hh:head`, `hh:bold` under `head`,
and `hc:img` under `hp:run`), invalid
`applyPageType`/`treatAsChar`, duplicate note instances or same-table cells,
and unsupported field/hidden-comment/drawText/caption/masterPage/paragraph10
structures refuse. Header/settings XML and section core vocabulary are closed;
foreign/future members refuse. A spine can reference only definition and
section roles. This T79 slice is inventory-only: it provides no selector, edit, or render
claim. Exit codes are 0 passed, 2 usage/argparse/output error, and 3
refused/unknown package. The owner facts are grounded in the public
[Hancom OWPML model](https://github.com/hancom-io/hwpx-owpml-model).

## 0C. Edit one inventoried story paragraph (T80 structural slice)

Prepare one closed `OP.json` with the private exact source SHA, the graph's
canonical `section/container/story/paragraph` address (never `/run[n]`), and
the replacement, then run:

```sh
python pipeline/scripts/story_edit.py INPUT.hwpx --ops-file OP.json \
  --out OUTPUT.hwpx --receipt RECEIPT.json
```

The paragraph must have exactly one direct text-bearing run with one direct
`hp:t`; ambiguous, stale, text-first/raw-ID, noncanonical, unsupported, or raw
CR requests refuse. The byte-preserving verifier compares ZIP records and
metadata before exclusive publication. The local receipt is privacy-safe and
`render: "not_run"`; this path makes no native/Hancom/PDF claim.

To verify that edit's current native render, use visual verification's closed
story scope. The structural receipt is intentionally unbound and is not a
render claim:

```sh
python pipeline/scripts/visual_verify.py --artifact OUTPUT.hwpx \
  --pdf native.pdf --baseline BLANK.pdf \
  --conversion-record native.pdf.conversion.json \
  --expectations story-expectations.json --out visual_verdict.json
```

`story-expectations.json` must contain only non-empty `required_text` and
`forbidden_text` lists alongside `"operation_scope": "story_edit"`. The
hash-bound conversion record must match the current HWPX/PDF bytes and page
counts; baseline pages must be comparable. Form-fill/profile/blank inputs,
targeted vision, deterministic-only, and waivers are refused. Pass 1 ends at
`vision_pending` after the deterministic checks with no acceptance waiver or
blocker; pass 2 requires an all-pages vision verdict. Missing required text,
visible forbidden text, malformed/non-empty XML, or invalid parity remains a
failure.

The current native evidence includes one public/sanitized header plus
disposable synthetic-donor footer, footnote, and endnote probes converted with
Windows Hancom and reviewed on every rendered page. The three donor probes
prove bounded story execution/render placement, not Hancom-authored note
anchors, numbering, continuation, or native insertion. The independent
render-quality checker classified all of these runs as
`unknown/unsupported_graphics_state`, never as a quality pass. Exact hashes,
page deltas, and the evidence-class boundary are recorded in
[`docs/research/story-role-native-evidence.md`](research/story-role-native-evidence.md).

## 1. Clone and bootstrap

```sh
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom
python3 scripts/bootstrap.py
```

`scripts/bootstrap.py` verifies the interpreter, creates a private
personalization profile under the Git-ignored `.local/`, registers the
default preference packs, and runs an end-to-end smoke test (`new_report` →
`resume` → a passing script gate) against a synthetic form fixture. It is
idempotent. This step alone proves the kernel is wired correctly; it does not
produce a real document.

The Hancom-free XML engine is bundled at `engine/scripts` — no external
checkout or environment variable needed. `doc_backend.py --backend hwpx`
resolves it there by default and checks that `fill_report.py`, `eqn.py`, and
`xml_backend.py` all exist before invoking anything
(`pipeline/scripts/doc_backend.py`). Operators with an external engine
checkout may still set `HWP_MASTER_SCRIPTS` as an override (deprecated).

## 2. Create an example workspace

```sh
python scripts/new_report.py --slug demo --subject math \
  --topic "A testable question" --form /absolute/path/to/form.hwpx \
  --mode night
```

`--form` must point at an existing file (`new_report.py` checks `is_file()`
only at creation time; later stages validate its actual HWPX structure). If
you don't have a real submission form handy, you can create a placeholder to
exercise the CLI wiring the same way `bootstrap.py`'s smoke test does — but
note this will not pass the content/format gates below, which expect a real
form and real content:

```sh
python3 -c "open('/tmp/placeholder-form.hwpx','wb').write(b'placeholder')"
```

`--mode night` lets `pipeline_ctl.py gate` auto-approve human gates for this
walkthrough; script gates are never auto-approved — they always run their
bound checker. This prints the workspace path and the next command:

```sh
python modules/report/scripts/pipeline_ctl.py resume ./workspaces/report-demo
```

## 3. Walk the stage graph

`pipeline_ctl.py resume <WS>` always tells you the next stage. The gate kinds
are declared in `modules/report/references/stages.yaml`:

| Stage | Name | Gate kind | Resolve with |
|---|---|---|---|
| 0 | form_intake | none | `pipeline_ctl.py advance <WS> 0 --status done` (after `engine/scripts/form_inspect.py`) |
| 1 | research | none | `pipeline_ctl.py advance <WS> 1 --status done` |
| 2 | design | human | `pipeline_ctl.py gate <WS> design --mode night` |
| 2.5 | layout_plan | script (external checker) | registered per-workspace; see `playbooks/stage-2.5.md` |
| 3 | sim | script (`{WS}/sim/gates.py`) | `pipeline_ctl.py check <WS> sane` |
| 4 | write | human | `pipeline_ctl.py gate <WS> draft --mode night` |
| 4.5 | content_audit | script | `pipeline_ctl.py check <WS> content_audit` |
| 5 | assemble | none (backend-conditional) | `pipeline/scripts/doc_backend.py <WS> --backend hwpx` |
| 5.3 | format_check | script | `pipeline_ctl.py check <WS> format_check` |
| 5.5 | understand | script | `pipeline_ctl.py check <WS> understand` |
| 5.7 | final_panel | script | `pipeline_ctl.py check <WS> final_panel` |
| 6 | return | script | `pipeline_ctl.py check <WS> submission_preflight` |

Human gates (`gate` subcommand) auto-approve in `night`/`autonomous` mode;
script gates (`check` subcommand) always run their bound checker and never
auto-approve, regardless of mode — this is the fail-closed fix from the
v0.7 hardening wave. After each resolved gate, advance the stage:

```sh
python modules/report/scripts/pipeline_ctl.py advance <WS> <stage> --status done
```

Stage 4.5's `content_audit.py` runs seven sub-checkers against
`bundle/content.md` and the figures directory (see README.md's "Content audit
and submission gates" section for the full list); write real, gate-passing
content there before continuing — this is the one step in the walkthrough
that cannot be faked with a placeholder.

## 4A. Assemble without Hancom (bundle — any machine, advisory only)

To prove the pipeline runs anywhere with zero dependencies:

```sh
python pipeline/scripts/doc_backend.py <WS> --backend bundle
```

This always succeeds if `bundle/content.md` exists, and writes
`output/deliverable/` (content, figures, `preview.html`, `manifest.json`).
It never writes `output/out.hwpx`, so Stage 5.3 `format_check` will fail HARD
with `output_missing` if you try to advance past it on a bundle-only build.
Stop here if you only wanted to see the pipeline run end to end.

## 4B. Assemble without Hancom (hwpx — assembled artifact; grade requires an executed renderer)

Set `doc_backend: hwpx` in `<WS>/build.yaml`, or pass `--backend hwpx`
explicitly:

```sh
python pipeline/scripts/ws_snapshot.py snapshot <WS>
python pipeline/scripts/doc_backend.py <WS> --backend hwpx
```

(`ws_snapshot.py snapshot` is the pre-assembly restore point the stage-5
playbook recommends before any assembly attempt.) The dispatcher invokes
the engine's `fill_report.py --engine xml` against `<WS>/output/form_copy.hwpx`
and `<WS>/bundle/content.md`, filling `output/out.hwpx` without Hancom or COM
on any OS. If the engine cannot be resolved (corrupted install, or an invalid
`HWP_MASTER_SCRIPTS` override), the dispatcher exits 4 and prints the exact
fix instead of guessing.

**Where the proof grade comes from:** read the shipped
[`platform-backends.md`](../skill/references/platform-backends.md) matrix.
`render_probe.py` reports capabilities only; it never upgrades an XML
assembly to Hancom proof. `fill_report.py` and post-assembly renderer paths
write the current, hash-bound receipt at
`<WS>/output/proof/backend/receipt.json`. Stage 6 validates that receipt and
requires its derived `proof_grade` to equal `output/verdict_v06.json`.

The XML path therefore produces `proof_grade: none` unless a named renderer
actually succeeds. Successful named LibreOffice, `rhwp`, certified, and
Windows COM executions have distinct closed evidence classes. A failed,
refused, stale, or hash-drifted execution always derives `none`; a receipt
recorded on Windows remains historically valid when inspected on Linux, while
the current host's capability probe is only informational.

The adapter's stdout is parsed as one bounded JSON object: harmless prefix or
suffix diagnostics are discarded, while malformed, truncated, oversized, or
ambiguous output fails closed. LibreOffice advisory promotion remains behind
the independent visual-quality release gate; a valid child JSON plus a PDF is
not by itself a submission claim. That release hold is shared by direct
`fill_report`, receipt derivation, dispatch, and Stage 6, so a quality-passed
LibreOffice run currently remains terminal `proof_grade: none` on every
entrypoint. Any `renderer_decision.candidate_proof_grade` is only an internal
routing candidate; the top-level terminal `proof_grade` is authoritative.

For every successful PDF renderer, the dispatcher also runs the receipt-bound
`pipeline/scripts/render_quality.py` Hangul glyph checker against the exact
assembled HWPX/PDF pair. On advisory/certified preview paths, a Hangul source
with no extracted Hangul or an insufficient embedded glyph capacity is
`failed/missing_hangul_glyphs` and retains `proof_grade: none`;
duplicate/nonembedded/unavailable mappings remain `unknown` and never promote
those preview grades. Hangul-used Type3 fonts have a narrower bounded path:
the checker parses page codes and CharProcs and requires ToUnicode, Encoding
Differences, finite nonzero metrics, path construction and paint, plus distinct
Unicode-to-code-to-program identities. Identity collapse or missing geometry
fails; unsupported graphics/Do, malformed, oversized, or otherwise
uninspectable Type3 content remains `unknown`. Symbol-only Type3 resources are
ignored, code 0 is valid, and `ActualText` alone is not proof. ASCII-only
sources are `not_applicable`. Stage 6 reruns this check, requires `converged:
true`, a matching PDF hash, and all existing deterministic visual/layout HARD
checks; extracted text is not visible-glyph proof, and `advisory` is not Hancom
parity. This bounded Type3 path is not full PDF certification.
When a rawdict span exposes both Hangul `chars` and `text`/ActualText, the
checker resolves one ordered claim: identical claims are accepted, a strictly
longer text claim is retained for the identity check, and an equal/shorter
disagreement is `unknown/semantic_text_ambiguous` rather than being unioned.
Its page clip/transform subset only guards glyph visibility; the existing
visual/layout HARD gates still own full-page intersection and composition.
When a target Type3 page uses a finite `cm` or polygon clip, the bounded gate
also requires PyMuPDF `Page.get_texttrace()` and `Page.get_bboxlog()` evidence:
the trace font must resolve to the page-local resource, have positive opacity,
finite in-page geometry, and align exactly with the ordered page code groups.
Type3 path evidence is limited to adjacent `fill-path`/`stroke-path` entries
whose boxes overlap the trace, and every active transformed clip must contain
the trace box; missing or ambiguous trace, bboxlog, matrix, or clip evidence
is `unknown`. The API references are the official
[PyMuPDF `Page.get_texttrace()` docs](https://pymupdf.readthedocs.io/en/latest/functions.html#Page.get_texttrace)
and [PyMuPDF `Page.get_bboxlog()` docs](https://pymupdf.readthedocs.io/en/latest/functions.html#Page.get_bboxlog).

The native Hancom route has a separate provenance boundary: a hash-bound
`native_render` receipt remains `hancom` when this checker is `unknown` or
`not_applicable` (for example, Type3 fonts it cannot inspect), and downgrades
only on a confirmed quality failure. This is renderer provenance, not a
readability certification; Stage 6 still requires converged assembly, clean
layout/style HARD checks, and canonical artifact hashes.

`rhwp` remains a diagnostic SVG path and `experimental-rhwp` is hard-blocked
from submission. It may write its renderer-specific diagnostic receipt under
`output/proof/rhwp/`, but the generic backend receipt is the Stage 6 authority.

## 5. Post-assembly gates

```sh
python modules/report/scripts/pipeline_ctl.py advance <WS> 5 --status done
python modules/report/scripts/pipeline_ctl.py check <WS> format_check
python modules/report/scripts/pipeline_ctl.py advance <WS> 5.3 --status done

python modules/report/scripts/pipeline_ctl.py check <WS> understand
python modules/report/scripts/pipeline_ctl.py advance <WS> 5.5 --status done

python modules/report/scripts/pipeline_ctl.py check <WS> final_panel
python modules/report/scripts/pipeline_ctl.py advance <WS> 5.7 --status done

python modules/report/scripts/pipeline_ctl.py check <WS> submission_preflight
```

- `format_check` (`verify_format.py <WS> --require-output`) hard-enforces
  body font size, line spacing, margins, and PDF page bounds, and fails HARD
  if `output/out.hwpx` is missing.
- `understand` (`check_understanding.py`) requires five questions and, in
  supervised mode, five non-empty answers in `QUESTIONS.md`.
- `final_panel` (`check_scorecard.py`) fails HARD if any stop-line field in
  `output/scorecard*.json` is true, or the scorecard is missing/malformed.
- `submission_preflight` composes `check_saeteuk.py`, checks the canonical
  artifact's identity fields against `request.yaml`, recomputes and compares
  the assembled HWPX's form-structure hash against `form_baseline.json`, and
  requires a current artifact-bound receipt for every non-`none` `proof_grade`,
  checks that the receipt derives the same grade, and for advisory proof
  reruns the hash-bound Hangul quality contract. Advisory is HARD-rejected when
  quality is missing, failed, unknown, stale, or not tied to `converged: true`.
  `certified` additionally requires the build opt-in, a passing live
  `render_cert check`, and a certificate whose operator-key HMAC, embedded
  measurements, manifest-derived envelope, corpus manifest, renderer binary,
  and pinned versions re-verify. The current host's renderer capabilities are
  reported as informational `reproducible_here` facts; a historically valid
  Windows receipt is not invalidated merely because the delivery host lacks
  Hancom.

## 6. Where you land

- Exit 0 on `submission_preflight` = a graded verdict: `proof_grade` is
  `hancom`, `certified`, or `advisory`, the form structure is unmutated, and identity
  fields are filled. This is printed as JSON and can be written with `--out`.
- An `advisory`-grade equation document, or any `proof_grade: none` run, is
  rejected by default. To record an explicit draft exception (never a silent
  pass), use `--allow-advisory --reason "<why>"` or `--allow-unproven` —
  both are logged in the verdict JSON, not hidden.

## Windows + Hancom alternative

Everything from step 4B onward has a Hancom/COM equivalent: set
`doc_backend: hwp`, ensure the engine's `.[windows]`/`.[proof]` extras and a
licensed Hancom install are present, and run
`engine/scripts/fill_report.py --loop --proof ...` per
`modules/report/references/playbooks/stage-5.md`'s §HWP section instead of
`doc_backend.py --backend hwpx`. That path reaches `proof_grade: hancom`
directly and includes the engine's own render-measured fill/tidy/typeset
loop, which the XML engine only gained (optionally, when a renderer is
configured) in the v0.10 wave.
