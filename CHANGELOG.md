# Changelog

Format is loosely [Keep a Changelog](https://keepachangelog.com/); versions
correspond to Git tags. The stage-machine schema version (`pipeline/references/
stages.yaml`'s `version: "0.6"`) has not changed since v0.7 — these releases
add gates, backends, and tooling on top of a stable kernel, they do not change
the kernel's contract shape.

## Unreleased

### Added

- **T85:** added a fail-closed, standard-library HWP5 ingress boundary. The
  read-only `hwp_ingress.py inspect` route validates closed CFB v3 FAT,
  mini-FAT, directory and stream allocation; direct-root DocInfo and
  BodyText/Section structure; and its unique 256-byte `FileHeader`, exact
  `HWP Document File` signature, supported 5.0/5.1 version, and protection
  flags without exposing document text or stream names. Canonical HWP-to-HWPX
  publication is Windows Hancom-only: one named mutex covers the complete
  operation; the source and reopened output use the same privacy-safe COM
  extractor; full-text/character and table/picture/equation/shape/page/
  control/field aggregates must match; the physical ZIP plus OCF/OPF/section
  envelope must validate; and the live source hash must remain current. The
  receipt is published first and the output link is the final commit marker.
  The `verify` route closes receipt keys, types and terminal state and rebinds
  the exact HWPX bytes/counts; `new_report --ingress-receipt` verifies both the
  supplied artifact and workspace copy and retains the receipt for claimed
  binary-HWP provenance.
  The separate `rigorloom/hwp-ingress/v1` receipt is conversion-only and
  always has `proof_grade: none`; it is never native-render evidence. Missing
  Hancom, protected input, unavailable parity, or any mismatch exits 3. No
  LibreOffice or `rhwp` result may become the canonical form.
- **T79:** added the read-only `story_graph.py` HWPX inventory. It follows the
  OPF `content.hpf` manifest/spine plus actual section roots, inventories the
  bounded `header`/`footer`/`footNote`/`endNote` paragraph-list controls, and
  emits manifest-order member ordinals, role/ordinal addresses, counts,
  topology, and schema-only structural hashes (never raw-byte fingerprints).
  The physical mimetype must be the first stored, extra-free ZIP entry; every
  local header is reconciled with its central record (including version-needed
  and DOS date/time; empty extras and only flags `0` or public-corpus-proven
  DEFLATE fast flag `0x0004`); OCF rootfiles and all
  declared XML roots are closed and validated before OPF. Every section must
  occur exactly once in a nonempty spine, which references only definitions or
  sections; table-cell stories retain only closed table/cell encounter ordinals
  (never raw coordinates) and story-in-story owners refuse.
  ZIP/XML bounds, OPF grammar/media/coverage,
  supported parent grammar, exact control values, note/cell scope identity, and unsupported story
  resources are fail-closed. Fields, hidden comments, draw text, captions,
  master pages, `.hwp`, rendering, and editing are deliberately out of scope.
- **T80:** added the bounded `story_edit.py` paragraph-only structural editor.
  It accepts one private exact source SHA and one canonical
  `section/container/story/paragraph` selector, requires exactly one direct
  text-bearing run with one direct `hp:t`, and refuses text-first/raw-ID/
  `/run[n]`/ambiguous/stale/noncanonical/unsupported/CR inputs. Raw span
  splicing removes only the changed paragraph's own line-segment cache;
  semantic no-ops copy bytes exactly. Immutable-snapshot processing,
  topology-only T79 recheck, raw ZIP-record/metadata preservation verification,
  exclusive identity-safe publication, and a closed local receipt preserve the
  privacy/evidence boundary. This is structural mechanics only; render remains
  `not_run`.
- **T81:** corrected PKWARE DEFLATE flag `0x0004` handling to fast level 1,
  skipped processing instructions through exact `?>`, and refused DTD/entity
  declarations in the bounded editor lexer.
- **T82:** added a closed `visual_verify` `operation_scope: "story_edit"`
  for current native story-edit renders. It requires a `.hwpx`, explicit PDF,
  comparable baseline, hash-bound conversion record, and non-empty per-page
  `required_text`/full-string `forbidden_text`; the unbound structural T80
  receipt is never artifact evidence. Form-fill/profile/blank/waiver,
  deterministic-only, targeted-vision, unknown-scope/key, malformed XML,
  invalid conversion/page/PrintMethod, and incomparable-baseline paths fail
  closed. Fill-only checks are audited under
  `deterministic.not_applicable_checks`, never acceptance waivers or ordinary
  skips; XML/page parity, baseline diff, and all-page vision remain mandatory.
  Initial native evidence for this slice was deliberately narrower than the
  structural role coverage: one public/sanitized header was converted with
  Windows Hancom and accepted only after an all-page visual verdict. T84 later
  adds disposable donor-role execution without promoting those XML-assembled
  notes to native-authored semantics. Every independent render-quality result
  remains `unknown/unsupported_graphics_state`, not a quality pass.
- **T83:** kept the document-evidence privacy rejection regression while
  assembling its synthetic Windows profile path at runtime, so the public
  repository privacy scan remains HARD-free instead of flagging the test
  fixture itself.
- **T84:** recorded the bounded Windows-Hancom execution evidence for
  disposable `footer`, `footNote`, and `endNote` donor probes without shipping
  their HWPX/PDF bytes. All three passed T79/T80, current hash-bound conversion
  records, page parity, baseline pixel comparison, and T82 all-page vision;
  their independent render-quality result remained
  `unknown/unsupported_graphics_state`. The note controls were XML-assembled,
  not Hancom-authored anchors, so native note insertion, numbering, and
  continuation remain explicitly unproved.
- `form_inspect` now emits additive, backward-compatible `anchor_records`
  (legacy `para_idx` plus the preedit-aligned `at_para` when identity is
  proven) as internal evidence, and accepts opt-in `--full-text PARA:N`,
  returning only the requested paragraph's own exact text/runs in preedit's
  document order.

### Fixed

- **T79:** the story inventory now rejects case-fold duplicate ZIP members and
  has an explicit CLI contract: exit 0 for a passed graph, 2 for argparse or
  output/usage errors, and 3 for a refused/unknown package. Help and output are
  UTF-8-safe and never echo document text, author metadata, or absolute paths.
- **T53:** backend capability probes no longer promote XML assembly to Hancom
  proof. Every non-`none` legacy grade is derived from a terminal execution
  receipt bound to the current artifact hashes; current-host capabilities are
  informational only.
- **T54:** the XML adapter dispatch now passes its explicit `--assemble` mode
  and canonical `--out output/verdict_v06.json`, so a real adapter invocation
  cannot silently exit with usage 2 while leaving a stale verdict behind.
- **T55:** renderer failures and stale higher-grade verdicts fail closed to
  `none`; the active terminal receipt, rather than a max-grade merge, owns the
  current proof grade. Receipt invalidation now fails loudly if a stale file
  cannot be removed before a new execution.
- **T56:** flattened installs ship the pure-stdlib `document_evidence` helper
  alongside the pipeline scripts, with an installed `--help` import check.
- **T57:** XML renderer templates accept both `{out_dir}` and the historical
  `{outdir}` spelling used by the WSL probe.
- **T58:** receipt validation closes backend/evidence pairs, artifact roles and
  extensions, distinct input/output bindings, successful exit code 0, and
  canonical submission hashes; decoy artifacts cannot establish proof.
- **T59:** receipt reason/renderer metadata is bounded to machine tokens and
  capability facts are allowlisted booleans, preventing user paths or prose
  from entering evidence artifacts.
- **T60:** flattened report installs now carry the in-tree `adapters_impl`
  package required by `doc_backend.py`, with import/help and no-private-payload
  regression coverage.
- **T61:** document-evidence v1 now rejects unknown top-level, execution, and
  artifact fields; validates exact UTC-second timestamps and closed artifact
  roles; and requires native exit code 0 for successful structural as well as
  rendered evidence. Producers and the golden path now describe XML assembly
  as an artifact, not a graded proof.
- **T62:** the XML dispatcher now parses one bounded, unambiguous adapter JSON
  object even when a PDF/layout dependency adds prefix or suffix diagnostics;
  malformed, ambiguous, oversized, or non-object output fails closed without
  recording raw stdout. Renderer terminal failures use truthful
  `renderer_failed`/`renderer_output_missing` reasons. Advisory promotion stays
  behind the independent visual-quality release decision while the known
  LibreOffice tofu/layout risk is investigated.
- **T63:** successful renderer execution now records a hash-bound,
  privacy-safe Hangul glyph-quality result. Missing/insufficient glyphs fail
  closed as `missing_hangul_glyphs`; ambiguous, uninspectable Type3,
  nonembedded, or unavailable font buffers remain `unknown` (inspectable
  Type3 is covered by T72). Stage 6 reruns the checker and
  requires `converged:true`, passed quality, matching PDF bytes, and the
  existing visual/layout HARD gates before any advisory grade; extracted text
  alone is not visible-glyph proof, and advisory is not Hancom parity.
- **T64:** the Hangul quality checker now compares the complete source syllable
  set from visible section run text with the extracted PDF set before checking
  font capacity. Partial coverage is conservatively
  `unknown/source_visibility_ambiguous`; a PDF with zero extracted Hangul
  remains the definitive `failed/missing_hangul_glyphs` case. Header and
  metadata text remain outside the source boundary.
- **T65:** advisory proof release is governed by one shared, currently closed
  policy across document evidence, direct `fill_report`, dispatch, and Stage 6.
  Quality-passed LibreOffice output therefore remains terminal `none` until the
  independent visual contract is released, including for forged receipts.
- **T66:** public renderer decisions no longer expose an internal
  `proof_grade` candidate. The bounded `candidate_proof_grade` field is
  informational; the top-level terminal grade remains authoritative.
- **T67:** native Hancom provenance remains `hancom` when the bounded glyph
  checker is `unknown`/`not_applicable` (including Type3 or unavailable font
  buffers), and downgrades only on confirmed quality failure. Stage 6 still
  independently requires converged, clean layout/style evidence and canonical
  hash bindings; native provenance is not a readability certification.
- **T68:** core bundles now stage `pipeline/adapters_impl` alongside the
  dispatcher scripts. A clean extracted bundle can run both
  `doc_backend.py --help` and `submission_preflight.py --help` under CP949
  without an import failure; corpus and private payload exclusions remain
  enforced.
- **T69:** generated core `INSTALL.md` manifests now sync the sibling
  `pipeline/adapters_impl` package as well as the dispatcher scripts. The
  shipped instructions are regression-tested by syncing a freshly extracted
  bundle and running both installed help paths under CP949.
- **T70:** contradiction-only preflight fixtures now carry a current,
  hash-bound native receipt. Missing receipts remain a separate HARD regression;
  the non-`none` receipt contract is not weakened.
- **T71:** `missing_glyphs` is now a closed visual-rubric class with a HARD
  severity floor. Vision findings of that class are accepted only as HARD and
  block acceptance; unknown classes remain usage errors.
- **T72:** Hangul-used Type3 fonts now receive a bounded, code-aware quality
  check. The checker requires ToUnicode, Encoding Differences, CharProcs,
  finite nonzero metrics, path construction and paint, and distinct
  Unicode-to-code-to-program identities; `ActualText` alone cannot pass.
  Identity collapse and missing geometry fail closed, while Do/XObject,
  unsupported graphics state, malformed, oversized, duplicate, or otherwise
  uninspectable mappings remain `unknown`. Symbol-only Type3 resources are
  ignored, code 0 is valid, TTF/OTF behavior is unchanged, and coverage is
  limited to synthetic/public fixtures rather than full PDF certification.
- **T73–T76:** Type3 checks now prefer decoded streams, scope `Tf` resources
  and identity budgets per page, model only balanced finite transforms and
  closed nonzero polygon clips, and reject duplicate CMap keys or non-injective
  Unicode/code/CharProc identities. Full-page visual/layout intersection
  remains a separate HARD gate.
- **T77:** Type3 pages that use `cm` or polygon clips now require bounded
  PyMuPDF `Page.get_texttrace()`/`Page.get_bboxlog()` evidence, exact ordered
  code/trace alignment, positive in-page opacity, adjacent fill/stroke path
  boxes, and full trace-box containment in active transformed clips. Missing,
  far, zero-opacity, late/nonoverlap, and repeated-occurrence mismatches stay
  `unknown`; this is a glyph-visibility guard, not full layout certification.
- **T78:** conflicting Hangul claims in a rawdict span's `chars` and
  `text`/ActualText fields are no longer merged. Equal claims are accepted, a
  strictly longer text claim remains visible to the Type3 identity check, and
  equal/shorter disagreement is `unknown/semantic_text_ambiguous`. The
  checker still does not treat ActualText alone as visible-glyph proof.
- **T47:** guide/removal residue policy is paragraph-addressed when the
  records are structurally valid; missing, malformed, or mismatched evidence
  keeps the legacy strict all-anchor/all-guide fallback.
- **T48:** long signature seats are anchors only for the narrow
  label/colon/trailing-marker shape; arbitrary long prose remains non-anchor.
- **T49:** `--full-text PARA:N` uses preedit's global depth-first `at_para`
  order and own-run text, while retaining the table-address syntax; its
  optional `para_idx` field is only an alias for that address, not the legacy
  profile index.
- **T51:** anchor records preserve the legacy profile `para_idx` for T47
  residue identity and add a start/identity-bound preedit `at_para`; nested
  and multi-section drift refuses to guess when identity cannot be proven.
- **T52:** the PPS signature workflow now documents that fixed-padding marker
  runs must be inspected and scoped explicitly, then checked in a Hancom/PDF
  visual loop; text hit gates do not prove line fit.

## v0.17.0 — validated product: autonomous verification, clean-room proof, six modules

v0.16.0 shipped as an **alpha**: written by its authors, run on its authors'
machine, exercised on one form-family lineage, and only ever against empty
forms. v0.17 is the release that turned that into a product someone else can
install and use. The product tree contains 30 commits, PRs #57–#86; the final
release-record PR changes documentation only. Three things changed in kind:
the system now judges its own rendered output with no human in the acceptance
loop (#57, #61, #64, #75); a clean-room harness installs the product the way a
buyer would and refuses to fall back to the checkout, which is what found the
defects the repo suite structurally could not see (#58, #59); and the module
contract carried four new work types (공문, 민원, 인사, 지원사업) with zero core
edits, taking the product to **six distribution modules and seven bundles**
(#65, #68, #69, #70).

Forty defects and harness lessons were found by validation rather than by the
suite: three Claude clean-room rounds, three tiers of an independent Codex
harness, three work-type family runs, and the fresh-root G1 acceptance chain.
The ledger, and the honest limits of what those runs prove, is
`docs/release-v0.17.0.md`.

### Added

- `preedit fill-cells` writes **multiple paragraphs** into one cell (T39). A
  fill value is now a list of paragraphs: a `--map` JSON array, a newline inside
  any value, or `--cell-line ROW,COL=TEXT` (repeatable, given order = paragraph
  order) — the PowerShell-usable spelling. Korean 공문 본문 is hierarchical by
  regulation (`1.` / `가.` / `1)` / `가)`, one paragraph per level), so the
  gongmun module could not produce a regulation-shaped 본문 at all before this.
  The blank paragraphs a form already reserves in the cell are used before any
  are created; the writable run stops at the first paragraph holding a nested
  table (the 기안문 본문 cell contains the 직인/발신명의 tables); continuations
  beyond the reserved run clone the target paragraph whole, so paraPr and charPr
  are the form's own and no created paragraph carries a stale `linesegarray`.
  The T30 pre-flight now covers every paragraph a call will write.
- `--parapr-per-cell ROW,COL=ID` repoints the `paraPrIDRef` of the paragraphs a
  fill writes, for forms whose reserved blanks are not body-formatted (the
  기안문 본문 blanks are centre-aligned because they share the cell with
  발신명의). Per-cell only, never batch-wide (T32); guarded by
  `guards.assert_no_dangling_parapr`, the T22 assertion's sister.
- `fill-cells` cell reports gain `paragraphs`, `paragraphs_reused`,
  `paragraphs_created` and `parapr`.

### Documentation

- `fill-recipe.md` §1.1 distinguishes a T30 charPr **trap** from the form's own
  typography, with the 기안문 별지 제1호서식 numbers as the worked example
  (body baseline charPr 23 = 10pt/100% 비고 fine print vs the 12pt/97% label and
  본문 face) — previously any `script_anomaly` read as a defect and pasting
  `suggested_flags` unread would silently reformat the 본문.
- `fill-recipe.md` §1.2, the gongmun fragment and `gongmun_flow.md` carry the
  multi-paragraph 본문 call; T39 is in the trouble table and the shipped
  troubleshooting distillate.
### Fixed

- **T37 — self-closing XML elements do not steal a sibling's text.** Six
  shared patterns treated `<hp:run/>` as if it opened a paired run and
  captured the next sibling's body. The arity-preserving fix recognizes the
  self-closing branch explicitly. A first repair also exposed the reusable
  rule: changing a shared regex's capture-group count is an interface change
  whose blast radius is every caller in the tree, not only the edited
  directory. Fourteen regressions pin both the XML shape and group arity.
- **T38 — conversion provenance survives the step boundary.** A correctly
  filled 기안문 별지 (and every gongmun-family form whose blank stores
  `PrintInfo/PrintMethod=4`) could not reach `verdict: pass` by any shipped
  path. `com_backend.py convert` already neutralises the stored n-up print
  imposition before `SaveAs(PDF)`, but only reported it on stdout — and the
  canonical recipe converts in one process and verifies in another, so
  `visual_verify` saw no evidence, HARDed `imposition_mismatch`, and could not
  be waived (that class is deliberately outside `SAFETY_CHECKS`). A gate cannot
  tell "did not happen" from "was not told". `convert` now writes a
  `rigorloom/conversion-record/v1` sidecar at `<--to>.conversion.json` by
  default (`--record PATH`, `--no-record`), carrying what the conversion did
  plus the sha256 of both the source and the output PDF; `visual_verify`
  auto-discovers it beside `--pdf` (or takes `--conversion-record PATH`) and
  rebuilds the same `conversion` dict it would have built had it converted
  itself. The hash binding is enforced: a record that does not describe the
  files under verification is a usage error (exit 2), never a quiet accept.
  Not a relaxation — with no record and `PrintMethod != 0` the HARD stands
  verbatim, and no baseline exemption was added.
- **T40 — the T30 post-flight compares the SEAT, not just the document.** With
  T38 fixed, the last thing keeping the gongmun family from `acceptance: true`
  was two unwaivable `fill_charpr_script_mismatch` HARDs on the 수신/제목 seats
  of a demonstrably correct 기안문 별지 fill. Both said `differing: ["ratio"]`,
  97% against a baseline of 100% — and the **untouched blank form** carries 97%
  on every substantive seat it has. The detector's one baseline was the
  document's own body charPr (the id carrying the most non-fill text), which on
  a mostly-EMPTY form is boilerplate: on this form it is the 비고 fine print, so
  every real field differed from it and the check was inverted on the whole
  document class. Worse, nothing ever asked the question that decides the
  finding — *did the fill introduce this signature?* An `--at-cell-append` fill
  preserves the printed label's charPr on purpose (T31), so the fill introduced
  nothing and was being blamed for the form's design. `--baseline` (the blank
  form, which the canonical recipe already passes for the pixel diff) is now
  read a second way — offline, as XML, no renderer needed — and each
  fill-modified run is compared against the **exact blank run named by the
  fill-map key inside its own seat**. A seat is
  a structural address (`Contents/section0.xml/t1/1,0`), keyed on `cellAddr`
  because that is the coordinate the fill CLIs take and because text cannot be
  the key: the same seat reads `수신` in the blank and `수신 국가유산청장` in
  the artifact. A run HARDs only when it differs from BOTH baselines, so the
  seat can only downgrade a finding, never create one. Inherited → WARN
  `fill_charpr_script_inherited`, naming the seat and the blank form's charPr
  (never a silent drop). An empty seat in the blank form → HARD, because there
  is no typography to inherit — the trap's own shape. No `.hwpx` baseline, or a
  `.pdf`/image-directory one → HARD **and the finding says the inheritance
  question was not checked**. `fill_charpr_script_mismatch` stays in
  `SAFETY_CHECKS` and `--accept-without` was not widened.
- **T41 — an ambiguous text match refuses instead of choosing.** The HR
  module's documented `preedit replace --map` path rewrote the same clause on
  five sibling contracts because a paragraph key had no position scope, and
  every module structural gate still passed the corrupted pack. Unscoped keys
  that resolve more than once now exit 2 as `replace_key_ambiguous`, naming
  each `at_para` plus recent prior context including the variant title; use
  `{"text": V, "at_para": N}` for one paragraph or
  `{"text": V, "all_occurrences": true}` for all. Occurrences are scanned
  independently per key against the original document, so overlapping keys
  cannot erase each other's evidence. The same doctrine now guards residue
  keep derivation: a fill-map key that claims several inventory strings is a
  usage error until `other_occurrences: form_text|seats` states which semantics
  apply. Scoped maps work from either `--fill-map` or expectations-only and are
  flattened for every other consumer.
- **T42 — address-keyed reserved form runs are a strict seat baseline.** The
  canonical 기안문 body fill uses key `"2,0"` and writes into a block of 23
  blank paragraphs, all carrying the form's deliberate 12pt/97% charPr. T40
  could prove inheritance only from visible text, so this correct fill still
  HARDed. For exact `ROW,COL` keys, the post-flight now accepts at least two
  empty runs in that exact seat only when they share one defined charPr, the
  filled signature matches it exactly, and its sole body difference is
  `ratio`; the result is the existing named inheritance WARN. A single empty
  run, mixed ids, changed signature, or script/scale/offset anomaly remains
  HARD. No safety check or waiver changed.
- **T43 — residue consumption uses the gate's value spans.** A mapped payload
  appearing after a surviving form label no longer makes the keep report call
  that label consumed. The targeted occurrence itself must lie wholly inside
  a declared value span, using `check_residue`'s own span and occurrence
  primitives. Prefix-preserving or COM fills therefore declare the complete
  resulting line (`{"수신": "수신 국가유산청장"}`); payload-only declarations
  remain `unfilled` and HARD. Key-absence replacement fallback is unchanged.
- **T44 — multi-paragraph fill declarations reach T30/T42.** The authoring
  path split JSON arrays and newline strings into one run per paragraph, but
  the post-flight searched each run for the unsplit whole. That made the
  charPr safety check unavailable on the documented multi-line body shape;
  JSON arrays also failed render presence by being stringified as a Python
  list. `visual_verify` now reuses `preedit.split_fill_lines`: render presence
  compares the joined paragraphs, charPr verification checks every non-empty
  paragraph, and exact `ROW,COL` keys are scoped to that seat. Regressions pin
  array/newline inheritance and a changed-charPr multi-paragraph HARD.
- **T45 — task intent no longer requires forbidden rendered evidence.** G1
  asked for a 기안 초안 and asserted auto `document.state == "draft"`; auto
  state uses the bottom 비고 block as its draft marker, while the visual rubric
  correctly HARDs that out-of-form instruction as `guide_text_visible`. The
  task could therefore be machine-green or visually acceptable, never both.
  G1 now passes the checker's existing `--mode draft`, asserts
  `document.state_used`, and independently requires the 비고 marker absent.
  The generic checker and the visual severity are unchanged.
- **T46 — PowerShell audits capture the native checker exit.** The Codex
  desktop shell can display a generic outer exit 1 for a bare native non-zero
  command even when `$LASTEXITCODE` is the checker's documented 2 or 3. The
  installed recipe now captures `$LASTEXITCODE` immediately, prints
  `DIRECT_EXIT`, and propagates it with `exit $native`; a clean-room install
  regression pins that exact buyer-facing pattern. T36's product exit matrix
  remains unchanged and green.

### Changed

- `engine/scripts/charpr_script.py` gains the seat layer: `iter_seat_runs`,
  `iter_seat_empty_runs`, `seat_addresses`, `seat_label_runs`. `iter_runs` now
  delegates to `iter_seat_runs` and drops the seat, so the seat-aware and
  seat-blind readings of a document cannot report different runs, text or
  order. Seat resolution takes two passes on purpose: OWPML puts
  `<hp:cellAddr>` at the END of `<hp:tc>`, after the `<hp:subList>` holding the
  paragraphs, so a single forward scan reaches every run in a cell before it
  learns the cell's address.

### Autonomous verification — the machine judges the render

- **#57 — `visual_verify`, the render-judge loop, and a closed rubric
  vocabulary.** `skill/references/visual-rubric.md` is the defect-class
  vocabulary an agent applies when READING a rendered page PNG: 12 classes,
  each with what it looks like, what it is NOT (the false-positive guard), and
  which deterministic check already covers it (FULL / PARTIAL / NONE). §4
  records the rubric's own gaps (colour fidelity, font substitution,
  equation-scale overprint) rather than pretending to cover them.
  `pipeline/scripts/visual_verify.py` is the loop driver: it renders pages
  (fitz 130 dpi; hwpx goes through ONE serial `com_backend convert`, never
  `--kill-stale`) and merges every deterministic backstop into a single
  findings list — hwpx section/header XML validity (T23), zero-text document
  and zero-content page (T25), stored `PrintMethod` plus
  `pages_document`/`pages_pdf` parity (W6.2), declared page budget / base_pt /
  line spacing / margins / fill map / forbidden text, `layout_qa` mapped onto
  rubric classes, `check_residue` and `check_density` delegates, and a
  `--baseline` pixel diff reporting changed-region bboxes. **It never calls a
  model**: it prepares the vision task (`vision_required`: page, PNG, reasons,
  rubric pointer) and consumes the handback through `--vision-verdict`,
  validating every class against the rubric vocabulary — an unknown class is a
  usage error, not a finding. No vision verdict means verdict `vision_pending`;
  `--deterministic-only` can exit 0 but sets `acceptance: false`;
  `--max-fix-attempts N` + `--attempt M` adds a HARD `loop_exhausted` so a
  caller escalates instead of grinding. The ship gate is rubric calibration:
  synthetic reproductions of all four historical incidents with
  false-positive guards, and `INCIDENT_MATRIX` pins the
  deterministic-vs-vision attribution so the rubric document and
  `RUBRIC_CLASSES` cannot drift apart.
- **#61 — three defects that were invisible from inside the repo.** *V1/T29*:
  the shipped skill pointed at `docs/research/visual-rubric.md`, which was in
  no bundle — the MANDATORY vision half reached a buyer with no class
  definitions, and both clean-room agents recovered the vocabulary by reading
  `RUBRIC_CLASSES` out of source. The rubric now has ONE home inside the
  shipped surface, and the packaging guard is generalized rather than another
  filename: `package_module` extracts every doc path named by every shipped
  surface document and refuses the build (exit 3) unless it resolves inside
  the staged bundle. Four further dangling references it immediately found are
  now named in prose instead of as paths a buyer cannot open. *V2*:
  `--form-profile` could not forward a keep list, so on a form fill every
  surviving legitimate anchor read as residue and the delegate could never
  return pass — added `--keep`, `--keep-pattern` and `--fill-map` (which
  derives the standard form-fill keep list), auditable under
  `deterministic.residue_keep`. *V3/T30*: a filled value inheriting a charPr
  identical to body text except for a trailing `<hh:supscript/>` kept its
  nominal 10pt height, so `charpr_check` and `style_diff` both passed it while
  Hancom rendered it at ~6.35pt raised. `visual_verify` now compares the
  script/scale/offset profile of every FILL-MODIFIED run against the
  document's body-baseline charPr and HARDs on a difference
  (`fill_charpr_script_mismatch`); scope is the false-positive guard, so an
  intentionally superscripted footnote marker is never compared.
- **#64 — T31: the keep list treats a prefix-preserving fill as consumed.** A
  CORRECT form fill could not pass the residue gate through `--fill-map`
  alone. The derivation computed "consumed" as "the mapping named this key"
  and then relied on the key TEXT HAVING VANISHED — which is not what a
  correct fill does. Filling a labeled field semantically KEEPS the label as a
  prefix (`" http://"` → `" http://host"`; a zip field keeps its
  `" 우(     -     )"` skeleton and appends the address), so the key survives
  inside the value by construction. Now: a key is CONSUMED when its mapped
  VALUE is present (whitespace-normalized, through `check_residue`'s own
  normalization and text extractor so the derivation and the gate cannot
  disagree); a key whose value is absent while the key text is still there is
  UNFILLED and still HARDs, named in `residue_keep.unfilled`; and surviving
  key text inside a value is attributed to that value's SPAN, per occurrence,
  not suppressed document-wide (`occurrences`, `attributed`, `at_offsets`,
  `context`, plus `fill_attribution` on the verdict). Guide text is never
  attributable, for the same reason it is never keepable.
- **#75 — T36: acceptance now requires the safety set, and no path exits 1.**
  Two P0 correctness-of-VERDICT defects found by the independent Codex
  clean-room harness. First, **`acceptance: true` while safety checks sat in
  `skipped[]`**: the luna tier supplied a CLI `--fill-map` and still got
  `empty_cell_expected_fill`, `fill_charpr_script_mismatch` AND page parity
  into `deterministic.skipped[]`, then exit 0 with `acceptance: true`, because
  acceptance was computed as "no HARD finding" and never read the skip list.
  `visual_verify.SAFETY_CHECKS` now names in ONE place the five checks whose
  absence invalidates acceptance (`page_parity`, `xml_wellformedness`,
  `check_residue`, `empty_cell_expected_fill`,
  `fill_charpr_script_mismatch`); `_skipped()` returns `{check, reason}`
  records so a rule can match on them; and a skipped safety check makes the
  verdict `safety_incomplete` with a HARD `acceptance_safety_skipped` naming
  which and why, exit 3. `--accept-without CHECK` (repeatable, closed
  vocabulary) is the only way past it, recorded as `acceptance_waivers` — per
  check, never a blanket switch, and the skip is still reported. The pixel
  diff stays OUT of the set (T35: a renderer-less machine loses one check, not
  the run). Second, **`--fill-map` and `expectations.fill_map` were two inputs,
  not one concept** — the flag drove the residue keep derivation while the
  expectations member activated the declared-value presence check and the T30
  post-flight, so the flag looked sufficient and was not. The CLI map now
  SEEDS `expectations.fill_map` (`fill_map_source` records which surface it
  arrived on); two DIFFERENT maps are a usage error rather than a silent
  precedence rule. Third, **`pages_document` is no longer the caller's to
  remember**: parity takes the first of conversion → expectations → the
  artifact's own `<hp:lineseg vertpos>` layout cache (`derive_pages_document`,
  excluding cell-relative linesegs inside `hp:tc`/`hp:subList`), records
  `pages_document_source`, and skips only when all three fail. Fourth, the
  **exit-code contract, all six rows**: sol and terra both saw exit **1** for
  `vision_pending` where the contract says **3**. 1 was not a code at all but
  an unhandled path — `emit_verdict` sat outside every guard in `main`, so an
  unwritable `--out` escaped as a traceback after a perfectly good verdict.
  `--out` is validated before the run and the emission is wrapped, so **no
  path exits 1**; `test_exit_code_matrix` pins one row per terminal state
  (`pass` 0, `deterministic_pass` 0, `vision_pending` 3, `fail` 3,
  `safety_incomplete` 3, `usage_error` 2) and the docs table is asserted
  against the code.
- **#76 — `empty_cell_expected_fill` stops firing on correct runs.** Every
  accepted tier emitted the same two warns for by-design-blank or unsupplied
  cells, with a page y-coordinate as the only evidence — a warning every
  correct run emits trains people to ignore warnings. `layout_qa` now emits
  one finding per empty header cell carrying its column, its header row and a
  `label`, plus `spacer_pattern` for the two by-design shapes;
  `visual_verify` suppresses those and any seat named in **`declared_blank`**
  (in expectations or in the wrapper-shaped fill map; `intentionally_blank` is
  an accepted alias folded into one list), recording every suppression under
  `deterministic.layout_qa.empty_cell_suppressed` and the declaration under
  `deterministic.declared_blank` / `declared_blank_source`.

### Clean-room validation — does the product work for someone who is not us

- **#58 — `evals/`, the clean-room harness.** `evals/cleanroom.py` installs
  rigorloom the way a buyer would: dist zips only, into a fresh temp root
  outside the checkout; modules enabled through the shipped registry CLI; the
  skill installed through the shipped installer. It self-checks (per-bundle
  `--verify` run by the *packaged* verifier, capability probe cross-checked
  against the registry, `--help` smoke over core plus module-registered CLIs)
  and then asserts containment on five independent axes — static path scan of
  every sandbox text file, reported-path resolution, runtime import origin and
  `sys.path` of a sandbox subprocess, environment scrub, and symlink escape.
  Any finding is exit 3, and `verify-containment` re-runs the same assertions
  after an agent has been in the sandbox. **There is deliberately no code path
  that copies product files out of the checkout** — a surface missing from the
  bundles is a `gap` recorded at HARD severity, and `--allow-gap`
  acknowledges it without hiding it. `evals/tasks/*.yaml` ships task
  definitions derived from `docs/research/form-eval-scenarios.md`, one per
  corpus-backed family, referencing corpus forms by path so the eval tree
  embeds no binaries; `run_record.schema.json` + `score.py` join a launcher's
  run record with the machine-check results into a scorecard and fold several
  scorecards into a cross-tier table. The model-invocation layer is a
  documented seam, not a hardcoded launcher.
- **#59 — the first thing it found: the core bundle shipped no skill
  surface.** `rigorloom-core-0.16.0.zip` carried the document engine and no
  `skill/SKILL.md`, no `skill/references/`, no `scripts/sync_local.py`
  installer — a buyer had no way to install the router skill an agent loads,
  and the `skill:` fragments the report and style modules declare had nothing
  to merge into. The repo suite could not see it: it runs against the
  checkout, where those files simply exist. `_CORE_COMPONENTS` now includes the
  skill surface and the installer, and two staged-tree assertions (both exit 3)
  stop the gap returning through an edit to the component list. Recorded in
  full, with the corrected v0.16.0 inventory, under "Post-release fix" in
  `docs/release-v0.16.0.md`.
- **#63, #72 — cross-model measurement and a shipped routing table.**
  `skill/references/model-routing.md` ships *with the product* so a buyer can
  run the cheap tier by default and escalate only where a measurement says to.
  Three rounds of two Claude tiers each, every run built from bundles alone
  with containment verified afterwards. **Round 1 measured defect-workaround
  cost, not tiers** — both tiers completed only by working around five product
  defects. Round 2 (after #59–#62) measures tiers: identical machine verdicts,
  within 6% on tokens, so Sonnet wins decisively on price for
  inspect/fill/verify. Round 3 ran the same task against the full product with
  all six modules enabled, and produced the result that changed the table: the
  charPr pre-flight removed the one quality difference that had separated the
  tiers, so **both tiers now avoid the superscript trap on the first attempt
  without knowing it exists** — the fill class is Sonnet-sufficient by
  mechanism rather than by luck. Opus's measured advantage is diagnosis
  (it root-caused the charPr trap and found the shipped cp949 `--help` crash
  that Sonnet reported only as friction). `assemble` and `prose/humanize` are
  explicitly **unmeasured, no claim**. The document's own limits section names
  the confounds: one task, one form family, one machine, two tiers, our own
  harness, and — added in #72 — that every measured run is a Claude agent. At
  release preparation that last limit was corrected rather than left standing:
  the non-Claude axis now has **exactly one** data point (the independent Codex
  harness of #75), recorded in the document with what it does and does not
  support — luna produced an accepted document, so a second vendor *can* drive
  the shipped surface, but it needed more retries and an auditing harness to
  get there, and its numbers are not comparable with the table's.

### Four new work-type modules — six modules, seven bundles

Each ships as its own installable bundle at the same version as core, and each
was built with **zero edits outside its own directory** (plus `evals/`), which
is the module contract's rule 4 exercised for real rather than asserted.

- **#65 — `gongmun` (공문/기안문, family ②).** One deterministic checker
  (`check_gongmun`), the `gongmun_org` pack type its issuing-organization seats
  are filled from, and a skill fragment for the 공문 task flow; no
  `requires_modules`. **The rules come from the 서식, not from a string list**:
  「행정업무의 운영 및 혁신에 관한 규정 시행규칙」별지 제1호·제2호서식 state
  their own rule in the 비고 block — the guide vocabulary must not be
  displayed, its content must be. The checker carries no Korean literal it
  matches on: the vocabulary is data and each form's own 비고 block is parsed
  at run time and unioned into the term list. Seat state
  (`blank_by_design`/`filled`/`emptied`/`half_filled`) is one mechanism applied
  to 두문 / 결재란 / 결문 / 발신명의; half-filled — not "empty" — is the failure
  mode a 결재란 row must never ship as. The 직인 slot is a placement, never a
  fill target, and border colours are read only from borders whose `type` is
  not `NONE` (the corpus 발신명의 box declares `#FF0000` on an undrawn border,
  and a naive colour scan calls it a seal). A blank form is not a failed
  공문: document state is classified from the form's own evidence, so both
  corpus 기안문 forms pass untouched and report the unfilled shape. Rules that
  cannot be decided from the inputs given are listed under `skipped` with a
  reason — never silently passed.
- **#68 — `minwon` (민원·신고 서식, family ①).** The highest-prevalence HWP
  work type, and the one the fixed-grid table-fill capability was built for.
  **Its rules are the INVERSE of gongmun's**: a 기안문's 비고 declares that its
  guide vocabulary must be replaced by content, while a 민원 서식 declares the
  opposite — its printed 유의사항 / 수수료 / 제출서류 / 동의 text is part of
  the document the applicant submits. So the headline rule is
  `guide_block_lost` and there is no residue class at all. Thirteen structural
  rules in seven groups, every one derived from what the four corpus forms
  themselves declare. Two mechanisms carried the design: **shading only means
  "staff-only" where the form SAYS so** (정보공개 청구서 paints its
  접수번호/접수일/처리기간 `#B2B2B2` and prints the declaration; 주민등록
  등초본 신청서 paints cells the same colour, one of which is an instruction
  block carrying the `[ ]` boxes the applicant must mark), and **an identity
  seat is a label, not prose** (no checkbox glyph, at most 40 squeezed
  characters). R6, the privacy rule, is deliberately NOT gated behind
  `--baseline`: a 주민등록번호-shaped value the operator did not declare in
  `--fill-map` is HARD on its own evidence. **No `pack_types`, and that is a
  finding rather than an omission** — everything the applicant supplies is
  per-document personal data, so a pack here would create the very store of
  personal data the identity rules exist to prevent.
- **#69 — `hr` (계약·인사 서식, family ⑦).** Chosen third for the one thing no
  other family offers: the corpus holds a **versioned pair** of the same
  instrument (고용노동부 표준근로계약서 2013 and its 2025 revision). Every rule
  was verified against BOTH baselines before it was written, and candidates the
  corpus does not support were dropped rather than shipped half-applicable.
  This is also the one work type whose document IS the legal instrument — a
  표준근로계약서 is numbered clause prose carrying the 근로기준법 제17조 서면
  명시 의무 in its own words — so the twenty rules in eight groups are
  preservation rules over PROSE. The corpus forced the design: the `'______'`
  underline-blank premise does not hold (the 2013 pack has exactly one
  underscore run, 2025 has none; the family's blanks are runs of spaces and
  `년 월 일` skeletons); the stencil rule splits on colons as well as blank
  runs because this family letter-spaces its labels; state classification
  needs a NARROW mark class (the broad option-slot class matches 32 printed
  parentheticals on the pristine 2013 pack and 66 on 2025, so every blank form
  read as a draft); and `clause_renumbered` reads its inventory from the
  baseline, never `1..N`, because the 2013 단시간 sheet legitimately runs
  1,2,3,4,5,6,8,9 on the PRISTINE form. The 2013 → 2025 drift table is
  re-derived by a test so it cannot rot. No `pack_types`, and again that is a
  finding: a repository store of one party's 사업체명 · 대표자 ·
  사업자등록번호 would be a standing supply of exactly the half-filled
  contract `party_half_filled` exists to catch.
- **#70 — `grant` (지원사업 신청, family ⑥).** The last of the planned
  work-type set, and the one whose distinguishing property breaks an
  assumption the other three share: **a 지원사업 submission is an application
  PACKET, not a document** — one file carries a 신청서 grid, a flowing
  사업계획서, 붙임/별첨 parts cited by number, per-programme budget tables and
  standalone 동의서 sheets, and the applicant is *supposed* to change its
  shape. Seventeen rules in nine groups, six declaring `wants: [baseline]`.
  Two make this module different: the extendable-table geometry rule compares
  COLUMN structure and the header row, never a cell count (adding rows is what
  this family's applicant does — the form says `견적서 1개 초과시 표 추가`), so
  a moved row count is reported as an extension while a changed column count
  is HARD; and packet integrity needs no baseline, because whether a marker
  class is INTERNAL is read off the document (a class with at least one
  `【… N】` header is internal and every citation of it must resolve).
  `budget_total_mismatch` is this family's one genuinely numeric invariant —
  each 합계 equals the sum of its column, verified 8 times over on the
  pristine kstartup form, whose totals are Hancom `=SUM()` fields, which is
  exactly why an XML edit that skips recalculation leaves a stale printed
  total. Four candidates were dropped, each recorded as a corpus assertion
  rather than prose. `length_budget_unverified` is a declared dependency, not
  a check: it reports `not_declared` / `needs_render` / `needs_section_scoping`
  and names `visual_verify` as the owner of a page count instead of guessing
  one.

### Engine — the offline fill path becomes complete

- **#60 — T26/T27/T28, the fill defects both round-1 clean-room agents hit.**
  *T26*: `preedit replace` double-applied a value containing its own key — tier
  B (raw substring) ran over the span tier A (whole-run) had just rewritten.
  Measured with `operations.md`'s OWN documented example:
  `{" http://": " http://example.kr"}` produced `" http://example.krexample.kr"`
  with `hits: 2`, so following the shipped docs corrupted the cell.
  Replacement is now single-pass: every span a tier writes is protected for
  the rest of the call, which also restores re-run idempotence and stops a
  later key rewriting an earlier key's value. *T27*: **new `preedit
  fill-cells`, the offline path to a genuinely empty cell** — a form's empty
  cell is `<hp:run charPrIDRef="N"/>` with no `<hp:t>` at all (19 of 19 empty
  cells on the PPS 협업승인신청서), so the text-keyed `replace` could never
  reach it even though the skill routed form-filling there. `fill-cells`
  addresses cells by the `cellAddr` that `form_inspect`'s `table_map` reports,
  creates the `<hp:t>` inside the empty run preserving its charPr, refuses a
  non-empty target unless `--overwrite`, strips the modified paragraph's stale
  linesegarray (T24) and validates well-formedness before writing. Table
  scanning moved to a shared tag-stack scanner (`engine/scripts/hwpx_tables.py`)
  so `--table N` and `table_map[N]` are the same table: the old non-greedy
  `<hp:tbl>(.*?)</hp:tbl>` mis-paired nested tables and got table/cell counts
  wrong on 6 of the 12 corpus forms. *T28*: `com_backend set_cell` addressed
  cells by keypress count — `TableRightCell` wraps across rows and
  `TableLowerCell` jumps over rowSpans, so on any form with a rowspan label
  column (the norm in government forms) it wrote to the wrong cell; targeting
  cellAddr (2,3) on the PPS form landed on (2,6), the `법인등록번호` label.
  `addr: [row, col]` now means cellAddr and is translated by a wrapping
  `TableRightCell` walk that verifies `get_cell_addr()` after every move and
  aborts without writing on any mismatch; the legacy keypress mode survives
  only behind an explicit `raw_traversal: true`.
- **#62 — the 12-form recognition table re-derived after the scanner fix.**
  7 of 12 forms had reported low table/cell counts, worst case
  `gianmun-byeolji-1ho` (2 tables / 5 cells for a document carrying 3 / 34).
  Anchors and guide_text were unaffected — the defect was purely structural.
  Superseded values are retained per form under `superseded_pre_pr60`, the
  bench doc carries an explicit correction block, and the `donguiseo` floor in
  the shipped `forms.md` moved 3/16 → 4/17.
- **#66 — T30 becomes preventable (charPr pre-flight), T32, and cp949-safe
  `--help` everywhere.** T30 was detectable but not *avoidable*: `fill-cells`
  "preserves the run's charPr" is documented as the safe behavior, and finding
  the right `--charpr` id meant reading `header.xml` by hand — exactly the
  contact the shipped "structure only, never dump body" contract discourages.
  Now `form_inspect` reports `body_baseline_charpr` once and, on every
  `fill_target` cell, the charPr the fill would inherit, a `script_anomaly`
  flag and `charpr_suggested`; `fill-cells` **refuses** an anomalous target
  given no explicit id (exit 3, `fill_charpr_script_anomaly`, naming the cell,
  the anomalous charPr, the suggested id and the exact flag to pass) instead of
  silently producing the 6pt fill. The comparison itself moved to
  `engine/scripts/charpr_script.py` and is imported by BOTH the pre-flight and
  `visual_verify`, so the two halves cannot disagree. Corpus calibration is
  pinned by tests, not folklore: 6 of the 10 converted corpus forms carry at
  least one anomalous target and `jeongbo-gonggae-cheongguseo` carries 18 of
  19. T32: `--charpr` is batch-wide, an undocumented constraint the T30
  pre-flight breaks, so `--charpr-per-cell ROW,COL=ID` sets one target's id and
  wins over `--charpr`. And **`com_backend.py --help` died with
  `UnicodeEncodeError`** on a Korean-locale Windows console — the platform the
  COM path exists for — because an em-dash sat in the top-level parser
  description, and only the top-level `--help` prints it. The UTF-8 stdio guard
  now runs at entry in every shipped CLI (12 in `engine/scripts` via the new
  `engine/scripts/cli_io.py`, and in `pipeline/scripts` via
  `checker_base._utf8_stdio`, including inside `checker_base.cli_main` so every
  checker routed through it is covered by construction). 11 CLIs were broken
  and 8 more were latently unguarded; the real deliverable is
  `tests/test_cli_cp949_help.py`, which DISCOVERS every argparse entry point in
  both shipped trees and runs `--help` under `PYTHONIOENCODING=cp949`, so the
  whole class cannot be reintroduced by the next docstring.
- **#74 — T34: address-keyed replace closes the seat-text gap.** Round 3
  measured the already-fixed product and both tiers, independently, hit the
  same wall: a form's **printed seat** (a skeleton the form typeset for a
  value — `" 우(     -     )"`, `" http://"`,
  `"20   .    .    .  ~  20   .    .    .   (     개월)"`) could only be
  edited with a `replace` key reproducing the run's exact internal whitespace,
  and nothing shipped yielded that string. So both agents read
  `Contents/section0.xml` by hand — precisely the contact the shipped skill
  forbids. Fixed in three layers. **`preedit replace --at-cell
  ROW,COL[#RUN]=TEXT`** and **`--at-cell-append`** (both repeatable, plus
  `--at-cell-map JSON`) remove the need for the exact string entirely; the two
  modes are explicit, never inferred. A cell holding more than one text run
  **refuses** (exit 2, `at_cell_run_ambiguous`) and the refusal lists every run
  index with its exact text, so neither "first run wins" nor "flatten the cell"
  can silently destroy content — PPS (15,0) carries the regulation sentence,
  the 신청일 line, `신청인`, `(서명 또는 인)` and `조달청장 귀하` as separate
  runs. A cell with no text run at all routes to `fill-cells`, so the two
  operations partition "already prints something" vs "genuinely empty" (T27).
  Every guard is shared with the rest of the engine (T24 stale-lineseg strip,
  well-formedness before write, the T30 pre-flight, the T22 dangling-charPr
  assertion), and `--at-cell-expect ROW,COL[#RUN]=SUBSTRING` compares with all
  whitespace removed on both sides so an operator asserts `우(-)` without
  counting spaces. Also: **`table_map[].text_preview` now reports
  `truncated`** — the failure was not that the preview is short but that
  nothing said there was more, which is why a competent agent concluded the
  협업기간 skeleton ended at the 30-character cut and lost a second replace
  pass; and **`form_inspect --full-text [TABLE:]ROW,COL`** is the documented,
  per-cell opt-in escape from the structure-only contract, emitting exact run
  text for the cells you name and no others, whose `runs[].index` IS
  `--at-cell`'s `#RUN`.
- **#73 — T35: one `--fill-map` loader for every consumer, and `--baseline`
  takes the blank form.** `--fill-map` was one flag name with two incompatible
  payloads: each consumer had grown its own loader, so `visual_verify`
  documented the wrapper shape while the module checkers and `check_residue`
  wanted a bare `{key: value}` map, and each refusal named only its own shape —
  the caller learned one shape per retry. `check_residue` now hosts THE shape
  rule (`load_fill_map`, `normalize_fill_map`, and `FILL_MAP_SHAPES` appended
  to every shape error, naming BOTH shapes); `visual_verify.load_fill_map` IS
  that function object, asserted, so the rule cannot fork again. A wrapper
  whose `fill_map` member is not an object is now a usage error instead of
  being read as a bare map. Second nit: `--baseline` reads as "the blank form"
  but refused an `.hwpx`, so the round-3 agent dropped pixel-diff rather than
  converting — it now routes an `.hwpx`/`.hwp` through the artifact's own
  `convert_to_pdf`, and with no renderer it is a skip-with-reason (one check
  lost, not the run, and never a crash).
- **#76 — `form_inspect`: `classification: spacer`.** Six cells on the PPS
  form were reported as `fill_target` when nothing is ever written in them, so
  the Codex harness and the round-3 Opus run each reasoned them away by hand —
  classification was pushing its own job onto the reader. A spacer is empty,
  has no label neighbour, and has one of two filler geometries derived from
  the table itself: `full_width_band` (spans every column AND is shorter than
  the shortest cell in that table that prints text) or `stub_head` (the corner
  where a header row crosses a label column). No addresses, no absolute
  heights, no tuned ratios. Excluded from the new `fill_target_count`,
  reported under `spacer_cells`. PPS: 19 empty cells → 13 + 6. A corpus sweep
  over all 12 forms reclassifies only separator bands and matrix stub heads.

### Module contract — the three gaps `gongmun` exposed

Shipping the first module nobody had planned for disproved one of the four
contract rules and left two harness gaps (**#67**). All three are closed.

- **Rule 4 was false for the test harness.** "Adding a module later requires no
  core change" held for the registry and not for the suite: pyproject's
  `testpaths` and CI's `py_compile` invocation were both hardcoded per-module
  lists. `testpaths` is now one glob (`modules/*/tests`), and the compile step
  is `scripts/py_compile_sweep.py`, whose pattern set includes
  `modules/*/scripts/*.py` and names no module (it exits 2 rather than passing
  vacuously when nothing matches). The acceptance test now proves the property
  instead of the mechanism: a brand-new module dropped into a synthetic
  checkout carrying the repo's real pytest ini block *verbatim* has its tests
  collected and its scripts compiled, with `pyproject.toml` as the only file
  outside `modules/` — plus a negative control and guards against either
  configuration naming a module again.
- **Eval machine checks gained a per-module gate.** `machine_checks[]` accepts
  `requires_module: NAME`; where the sandbox's enabled set lacks it, the check
  is skipped with a recorded reason instead of failing, with `blocked_on`'s
  semantics exactly (counted in `counts.skipped`, never in `counts.pass`, so
  neither `check`'s exit code nor `score.py` can read a skip as a pass). The
  enabled set is asked of the *sandbox's own* shipped registry CLI. Before
  this, a core-only sandbox *failed* G1's two gongmun checks — a red finding
  about a configuration the contract explicitly supports.
- **A checker can declare that it needs the blank baseline.**
  `provides.checkers[].wants: [baseline]` (closed vocabulary; schema, README,
  validator and an `enabled_checkers()` accessor) says out loud what gongmun's
  preservation rules only implied. The clean-room harness is the wired
  consumer: a task declares `baseline: <input basename>` and `check` appends
  `--baseline <path>` for a declaring checker. A baseline already in the argv
  is left alone (a document is never its own baseline); a declaring checker in
  a task with *no* baseline is skipped with a reason rather than run for a
  silent pass.

### Test harness — an inventory pin is a defect class, not a nit (T33)

**#71.** Three v0.17 modules were blocked by one bug shape: a core test
asserting `== N` on something the repo GROWS, so shipping a module, an eval
task or a gated check turns a working product red. #68 was the per-module
`testpaths`/`py_compile` lists; #26 was `len(tasks) == 7`, which meant shipping
an eval task required editing a core test; #27 was
`tests/test_cleanroom_evals.py` pinning eval task A1's skipped-check count at
`1` in two places — every `requires_module` check skips by design in a
core-only sandbox, so the grant module could not put its A1 checks on A1 and
wired them onto A2/A3 instead. **A module reshaping its payload to satisfy an
integer in core is contract rule 4 inverted.** Fixed by deriving:
`declared_skips(task, enabled_modules)` mirrors the two declared gates and both
sites take the count from `len()`, and A1 gained the gated check the grant
module wanted there (verified to PASS with the grant bundle installed and SKIP
with a reason without it, taking A1's core-only skip count to 2 — which the old
`== 1` could not survive). A class sweep derived three more inventory-coupled
pins and commented the genuinely fixed-arity ones with why they are not
inventory. The durable guard is **`tests/test_no_inventory_pins.py`**, which
walks the syntax tree of every core test file and fails on `== <int>` against a
check tally, a `len()`/`count()` over an inventory identifier or a discovery
call, or a subscript on an inventory key. `>=` floors are never flagged and
`modules/*/tests` is out of scope; fixed arity is admitted only as a REASONED
allowlist row, with meta-tests refusing a thin reason, a stale row, or a row
the guard would not have flagged. Also shipped in the eval harness: the task
inventory became a property rather than a count (#26 — every shipped definition
validates against the schema, every corpus-backed family has at least one task
with the family list DERIVED from the corpus manifest, plus a non-vacuity
floor), with a negative control that plants a corpus family with no task.

### Skill surface — the product says out loud what it already knew

- **#76 — `skill/references/fill-recipe.md`, one canonical fill.** Three
  harnesses filling the same PPS 협업승인신청서 picked three different
  strategies for the *same* 협업기간 cell, one built three separate maps, and
  `operations.md` never gave the `com_backend.py convert --file … --to …`
  syntax at all. The product knew the answer; nothing said it, so every reader
  re-derived it differently. The recipe states the branch-per-cell decision
  rule first (empty run → `fill-cells`; skeleton to keep →
  `--at-cell-append`; template to replace wholly → `--at-cell`; multi-run →
  the `#RUN` the refusal hands you; `spacer` → do not write there), works
  협업기간 as the example *because* it is the field that fractured, names the
  four artifacts and the exact flag that eats each, gives the literal sequence
  including the `tasklist` check before COM, and closes with what an accepted
  verdict looks like versus each partial. It was worked end to end on the real
  form and replayed verbatim to `acceptance: true`. Linked one level deep from
  SKILL.md's routing table; the superseded "which one fills a form" table in
  `operations.md` §3 is now a pointer, not a second account. Also:
  **ragged shipped tables fail the build** — in GFM a raw `|` splits a cell
  even inside a code span, so `com_backend.py inspect|edit` gave SKILL.md's
  routing table one four-cell row among three-cell rows, in the first table a
  router reads. Escaped, and `package_module` now asserts every table in every
  shipped surface document is rectangular. `--charpr-per-cell` is documented in
  the **fill section** of `operations.md` and in the SKILL.md routing row, not
  only inside the T30/T32 prose.
- **#77 — an unsupported habit flag explains itself.** A clean-room agent
  tried `form_inspect --pretty` from habit, and the habit has an in-repo
  source: `probe.py` is the ONLY script whose default output is compact
  single-line, because SKILL.md injects it inline. Probe's flag is a justified
  exception, not an inconsistency to remove; what was missing was an error
  message saying so. `form_inspect` now answers `--pretty`/`--indent`/`--json`
  with what to use instead and states its output contract in the help epilog,
  and probe's `--pretty` help explains why it is the exception.

### Packaging — bundle builds are reproducible

- **Same tree in, same bytes out.** Found while preparing the tag: building
  `core` twice from an unchanged tree gave two different zip sha256 values,
  because `ZipFile.write` stamps each member with the staging file's mtime and
  st_mode — so a published hash table was invalidated by any rebuild, no-op
  included, and a hash a reader cannot re-derive is not evidence.
  `scripts/package_module.py` now pins everything a member records besides its
  name and content: timestamps to a fixed 1980-01-01 (a constant on purpose —
  a commit-derived stamp is unreproducible for a reader who has the tree but
  not the history), permissions to 0o644, `create_system` to Unix, deflate
  level 9, and member order sorted by path. `MANIFEST.json` was audited for the
  same failure and its `files` list is sorted by path.
  `--verify` is unaffected: it hashes member content, not the container.
  `TestBundlesAreReproducible` builds every bundle twice per run and asserts
  byte-identity, including after an mtime-only change to the payload.

### Trouble table

Rows **T26–T46** added, each with the run class that surfaced it: T26–T30 the
first clean-room cross-model round, T31–T32 the second, T33 the module-wiring
class, T34–T35 the third, T36 the independent Codex harness across three model
tiers, and T37–T46 the work-type family runs and fresh-root G1 acceptance
chain.

## v0.16.0 — unified core and modules

The whole v0.16 program (`docs/plans/v0.16-unified-core-and-modules.md`):
rigorloom becomes a general HWP/HWPX document engine — one core, with the
report, style, and personalization capability split behind a distribution-
module contract and shipped as separately installable bundles
(`rigorloom-core`, `rigorloom-report`, `rigorloom-style`) built by
`scripts/package_module.py` at this same version. Everything below landed
on `main` between `v0.15.0-alpha` and this tag.

### Wave 1 — converge (field guards, audit verdicts, packs)

- **#29** (`v0.15 follow-up: feature-classification fixes + v0.16 master
  plan`) — the first real corpus run surfaced five section-level rendering
  element names (`pageBorderFill`, `visibility`, `startNum`, `grid`,
  `lineNumberShape`) that a blanket-benign classification would have made
  fail-open in `feature_extract.py`; they now emit attribute- and
  whole-subtree-fingerprinted feature classes (`sec-config:<tag>:<fp>`), so
  a document certifies only under the exact section configuration the
  corpus measured. Also added the v0.16 master plan and its companions.
- Lane F field guards (branch `lane-f-guards`) — T16 (header-height
  double-count), T18 (guide-text deletion must protect table/secPr/ctrl
  paragraphs), T21 (per-machine lock; refuse a name-scoped `Hwp.exe` kill
  while another owner's instance is live), and T22 (charPr id guards must
  match `<hh:charPr\b[^>]*\bid="34"`, not a substring) landed as testable
  primitives, each with a failing-before/passing-after test.
- **#30** (`docs: audit performance metrics + Phase 0 judgment verdicts`) —
  variant-audit metrics section as the Lane V exit criterion; recorded the
  extension-packs ABSORB verdict (v0.13.1 conditions).
- **#31** (`research: variant-audit decision matrix (Phase 0.C complete)`)
  — `docs/research/variant-audit.md`: five differential benches over
  existing artifacts (zero pipeline reruns). Headline findings: all five
  audited variants' recorded state diverged from reality; `score_ai_tells`
  showed zero discrimination on a 25%-changed section. Verdicts: hybrid
  gate architecture with form-scan auto-derived residue lists, two run
  modes plus a mandatory provenance floor, H2 advisory-only, and five
  shared-miss mechanisms.
- **#32** (`packs: land v013 extension packs with v0.13.1 policy
  conditions`) — landed the data-only extension-pack system
  (`scripts/extension_pack.py`, `docs/extensions.md`) with
  `constants_allowlist` excluded from `DATA_EXTENSION_PACK_TYPES` (a
  confirmed relaxation vector for `check_numbers`' deterministic numeric
  checker), and fixed the `merge_pack`/`_stable_union` regression where a
  global `gloss_allowlist` pack erased the 14 W5b neutral defaults.
- Lane V engine ops (branch `lane-v-engine-ops`) — audited, idempotent
  preedit/postedit XML operations adopted per the audit's
  form-preprocessing matrix row.
- **#33** (`gates: residue auto-derivation, H5 density, canonical binding,
  verdict contradiction`) — four shared-miss checkers: `check_residue.py`
  (the form scan's anchor/guide-text inventory auto-derives the artifact's
  forbidden list; a missing pinned target is HARD), `check_density.py` (H5
  bold-subhead density per 10k bytes, WARN >= 3.0 / HARD >= 4.5),
  `check_canonical.py` (declared canonical/`FINAL` pointer must resolve),
  and `verdict_schema.py` (rejects `converged: true` +
  `status: escalate_human`, wired into `submission_preflight`).
- **#34** (`gates: malformed artifact XML is HARD in check_residue`) —
  `check_residue.py` XML-parses every hwpx section/header member before
  scanning; a parse failure is a HARD `artifact_malformed` finding. Found
  live: a corrupt `section0.xml` passed the prior regex scan while Hancom
  rendered the document blank (T23).
- Engine XML hardening from live form work (direct merges): fixed
  self-closed `<hp:t/>` corruption in tier-A replacement and added a
  post-op well-formedness invariant to every preedit chain; stale
  `linesegarray` is stripped from exactly the paragraphs whose text was
  modified (Hancom otherwise draws the old cached layout over the new
  text); paragraph-scoped charPr repoint for split-run recolor, with the
  forensic finding that **Hancom resolves `charPrIDRef` by array
  position** — clones are now appended at the end of `charProperties`
  (never mid-array) and an `id_position_mismatch` diagnostic is reported.
- Verdict-writer consistency fix (shared-miss #5, direct merge): a proof-
  phase escalation now demotes `converged` to `false` (preserving
  `phase1_converged`), so the writer can no longer emit the contradictory
  pair `verdict_schema.py` rejects.
- **#35** (`docs: reopen/amend transition design`) — append-only
  amendments, receipt-signed reopen/amend-close, and the `unrecorded_edit`
  HARD backstop on canonical-hash mismatch with no open amendment.
- **#36** (`gates: declared-values runner with canonical binding and
  holdout enforcement`) — the hybrid gate architecture's composition point:
  a declarative per-workspace gate runner (audit winner semantics) where a
  missing pinned target is HARD `target_missing`, each gate records
  mtime+sha256 staleness, `workspace_slug` holdout refusal is enforced, and
  the residue/density/canonical kinds delegate to registry mechanisms.
- **#37** (`docs: version reality sync`) — README/SUMMARY/CHANGELOG aligned
  with the v0.15.0-alpha tag and post-tag merges (Lane F item F3).
- **#38** (`humanize: tone-rulepack mechanism, H2 advisory-only,
  measurement roles doc`) — deterministic tone-rulepack regression check
  (`check_tone_rules.py`: hedge-on-measured-value and
  conclusion-pivot-density rule kinds, WARN-only by default), `tone_rules`
  as a first-class pack type with a neutral default (the corpus-derived
  rulepack stays a private profile pack), and a regression test pinning
  that no code path gates on detector scores (H2 advisory-only).
- **#39** (`docs: CHANGELOG backfill v0.11.4–v0.15.0-alpha`) — six missing
  release entries reconstructed and verified against tags.

### Wave 2 — absorb hwp-master

- **#40** (`W2: absorb hwp-master as engine/ (history-preserving) + seam
  collapse`) with **#43** (`restore subtree ancestry`) — the hwp-master
  repo (COM backend, COM-free XML assembly engine, form inspection, fill,
  tidy, layout QA, eqn converter, render calibration; its own v0.1–v0.3
  history and 246 tests) is merged into this repo at `engine/`, with the
  full 29-commit engine history restored as ancestry after a squash
  flattened it. The seam is gone: the `HWP_MASTER_SCRIPTS` delegate
  indirection collapsed into direct paths (kept only as an optional
  override), the pointer SKILL file was deleted, and hwp-master's version
  line ends — everything ships on rigorloom's single version from v0.16.
- **#41** (`ci: guard optional deps (PIL/fitz) in engine tests`) — engine
  runtime deps (pillow) joined CI installs and an `engine` extra was added
  to `pyproject.toml`.
- T25 (`engine: open_hwp fails loudly on missing input`) — a missing input
  path is an immediate error, not a silent empty document.
- **#42** (`pipeline: reopen/amend transitions`) — the #35 design
  implemented: append-only amendment records, receipt-signed
  reopen/amend-close, amending stage status with `done_at` preserved,
  canonical invalidation marker, and guards (double-open, unknown id,
  non-done reopen).

### Wave 3 — the distribution-module contract

- **#44** (`W3-S1: distribution-module contract, registry, core-only CI
  guard`) — `modules/<name>/module.yaml` + `module.schema.json` +
  `pipeline/scripts/module_registry.py`: a module declares checkers, CLI
  commands, pack types, run modes, gate kinds, studio panels, preflight
  contributions, and a skill fragment; core never imports a module; the CI
  matrix gained the core-only / all-modules points **before** anything
  moved, and a throwaway module proves zero-core-change extension. Project
  version moved to `0.16.0.dev0` (the registry's version gate reads
  `pyproject.toml`).
- **#45** (`W3-S2a`) + **#48** (`W3-S2b`) — everything report-shaped moved
  into `modules/report/`: the seven cleanly-severable report checkers +
  `source_fetch`, then the stage machine as one unit (`pipeline_ctl`,
  `compose`, `workflow_lint`, `stages*.yaml`, `aliases.yaml`, the
  stage-contract catalog `modules.yaml`, all 24 playbooks) plus the
  workspace-bound checkers and the claims/sources chain.
  `submission_preflight` split: core keeps the artifact/proof half and
  gained a generic `preflight:` composition hook; the report module
  contributes P0/P4/check_saeteuk through it. Core resolves the stage-
  machine CLI only through the registry; on a core-only install every
  report entry point is a loud, named refusal — never a silent pass.
- **#49** (`W3-S3: registry-driven studio panels + per-module packaging +
  gate-kind registration`) — studio stays the core base surface and
  enabled modules extend it declaratively (`GET /api/panels`; the report
  module's content-audit action moved into its own panel); gate kinds are
  registry-declared (`provides.gate_kinds`, params validated against the
  delegate's signature at declaration time); and
  `scripts/package_module.py` builds standalone bundles — `--module
  <name>` for module payloads, `--module core` for the engine + pipeline +
  studio + contract, with `MANIFEST.json` (per-file sha256), `INSTALL.md`,
  `privacy_scan` over the staging dir (any HARD refuses the build), and
  `--verify` tamper detection against the manifest.

### Wave 4 — style and personalization as modules

- **#50** (`W4.2: style module + requires_modules contract key`) — the
  humanization stack (`humanization_ctl`, `prose_fidelity`, `check_style`)
  consolidated into `modules/style/` with the boundary stated in its
  README: translationese removal, voice consistency, form-rule compliance
  — **not AI-detection evasion**; rules come from packs. The contract
  gained `requires_modules` (inter-module dependencies enforced at
  enablement; `report` declares `requires_modules: [style]` because
  `content_audit` composes `check_style` through the registry).
- **#51** (`personalization: general/report pack split, store portability,
  schema rename w/ compat`) — core `personalization_ctl` declares only
  general pack types (`prose_rules`, `figure_style`, `backends`,
  `policy_floors`); the report-flavored five (`saeteuk`,
  `report_structure`, `gloss_allowlist`, `constants_allowlist`,
  `tone_rules`) are report-module payload, with `PACK_TYPES` /
  `DATA_EXTENSION_PACK_TYPES` computed from core built-ins +
  `ModuleRegistry.enabled_pack_types()` and the trust-sensitive set
  (`backends`, `policy_floors`, `constants_allowlist`, `tone_rules`) never
  extension-installable, re-enforced at resolve. Store schema renamed
  `report-pipeline/personalization-v1` → `rigorloom/personalization-v1`
  (legacy accepted on read, warned once). New `export`/`import` CLI:
  manifest+sha256 zip of the profile root that never includes the privacy
  denylist; import verifies byte-for-byte and refuses tamper and non-empty
  targets. `privacy_scan` gained the profile-store leak marker classes
  (`profile_store_content` / `profile_store_path`, both HARD), so
  packaging refuses any bundle staging store content.

### Wave 5 — landscape, evals, skill surface

- **#47** (`research: HWP usage landscape (W5.1)`) —
  `docs/research/hwp-usage-landscape.md`: seven form families with
  capability priorities. Headline: 행안부 mandates HWPX-only attachments on
  government systems since 2026-05-18, making hwp→hwpx conversion fidelity
  capability priority #2.
- **#52** (`W5.2: blank-form corpus + eval scenarios + pinned privacy
  allowlist`) — `tests/corpus/forms/`: 12 blank official templates across
  5 families, sha256/source/license manifest, 5 recorded skips (school
  family = corpus gap; corp family = documented no-official-source
  boundary); `docs/research/form-eval-scenarios.md` with 10
  open→recognize→fill→verify scenarios. `privacy_scan` gained
  `--binary-allowlist` (sha256-pinned, auto-detected at the corpus
  manifest): unlisted binaries and hash drift stay HARD, allowlisted files
  are still content-scanned (`binary_pii_rrn` / `binary_pii_phone` + the
  existing nets over extracted hwpx XML or a UTF-16 harvest of binary
  hwp), and bundles never apply the allowlist — a regression test asserts
  no corpus member lands in any bundle.
- **#53** (`W5.3: skill surface`) — `skill/SKILL.md`: a 98-line-body
  router (paths-gated frontmatter, task routing table, freedom map,
  one-level-deep references: `operations.md` / `forms.md` /
  `troubleshooting.md`); `engine/scripts/probe.py` — one compact-JSON
  capability probe merging `render_probe` + module registry summary +
  optional backend precheck, never raises; report/style modules declare
  `provides.skill` fragments and `sync_local.py` merges them at install
  (a core-only buyer never sees report vocabulary); A1/A2 machine-check
  evals executed against the corpus (all pass, non-vacuous negative
  control; agent-in-the-loop half is operator-run). Suite hygiene: the
  test suite no longer writes the repo profile store (session-scoped
  guard asserts it).

### Wave 6 — prove, bound, release

- **#54** (`W6.1: XC-1 conversion bench`) — all 10 `.hwp` corpus members
  converted to `.hwpx` via the COM backend (Hancom 13.0.0.2986), strictly
  serial: **10/10 OK, zero hangs/retries**; `form_inspect` recognition
  table now covers 12/12 corpus members; converted hwpx + rendered PDFs
  folded into the pinned manifest. Full writeup with honest limitations in
  `docs/research/xc1-conversion-bench.md`.
- **#55** (`fix-or-bound: XC-1 findings`) — every XC-1 open finding fixed
  with a regression test or documented as a capability bound (bench doc
  §9): guide-text detection generalized to mechanism-level pattern classes
  (note-prefix / example-mark / instructional verbs; 11/12 forms now
  detect, and admrul's 0 is locked as a *correct* zero by a bound test);
  COM inspect no longer counts every `gso` drawing control as a picture
  (UserDesc-classified, new `shapes` field); the nrf PDF page drop was
  root-caused to the document's own stored 2-up print imposition
  (`PrintMethod=4`) — convert now stages a print-normalized copy and
  always reports `pages_document` vs `pages_pdf` with a loud WARN on
  mismatch; `check_convert_parity` gained a guarded `.hwp` source leg
  (structural counts HARD, text advisory).

### Migration

- **From a standalone hwp-master install**: the engine is bundled at
  `engine/` — point automation at `engine/scripts/` (same script names);
  `HWP_MASTER_SCRIPTS` still works as an override but is no longer
  required. The hwp-master repo is absorbed; its tags end at v0.3.0.
- **From pre-module rigorloom (≤ v0.15.0-alpha)**: report-pipeline scripts
  moved from `pipeline/scripts/` to `modules/report/scripts/` (stage
  machine, compose, report checkers) and the humanization stack to
  `modules/style/scripts/`; enable modules with
  `python pipeline/scripts/module_registry.py write-enabled --all` (an
  absent `modules/enabled.yaml` means core-only, where report entry points
  refuse loudly by design). Personalization stores using the old
  `report-pipeline/personalization-v1` schema strings are accepted on read
  and rewritten on the next lock update.

Suite at release: core-only 866 passed / 565 skipped; all-modules 1293
passed / 138 skipped; repo-wide `privacy_scan` HARD 0. Bundle inventory and
verification evidence: `docs/release-v0.16.0.md`.

## v0.15.0-alpha — renderer certification harness

- Added `feature_extract.py` + `render_cert.py`: a renderer certification
  harness that binds a document's feature envelope (train/holdout stats) to a
  corpus hash and an operator key; every section-body element is classified
  handled, explicitly known-benign, or `unknown:<local-name>` over a full
  tree walk, and unrecognized elements outside `<ctrl>` direct children fail
  closed (#28).
- Certificate trust hardened after an adversarial audit: `verify_certificate`
  re-derives the envelope and train/holdout stats from the hash-anchored
  manifest plus the certificate's embedded measurement records and refuses on
  any mismatch, and certificates are HMAC-SHA256-signed over canonical bytes
  with a private operator key (`receipt_sign.py`, 0600 owner-only key at issue
  time) — a widened or fabricated certificate with a recomputed self-hash no
  longer verifies (#28).
- Registered the Stage 2.5 layout gate: `check_layout.py` locates hwp-master's
  `layout_plan_check.py` via `HWP_MASTER_SCRIPTS` (the checker had shipped
  null in `stages.yaml`, blocking composed pipelines — found live by the
  held-out sample run); a follow-up fix corrected a wrong `cli_main` call
  signature that had crashed the delegate at CLI entry.
- docs: Linux HWP/HWPX tooling research (#26) — on WSL2 x86_64 and OCI ARM64,
  `rhwp` 0.7.19 and the hwplib+hwp2hwpx+hwpxlib Java family both convert
  HWP<->HWPX at 0.0 px displacement under Hancom re-render on sanitized
  fixtures (rhwp SVG previews at 22-87 ms/page); LibreOffice+H2Orestart stays
  advisory (645 px worst case); corrects the previously-cited 676.33 px figure
  as a render-tree metric, not a LibreOffice PDF measurement.
- docs: v0.15 renderer certification plan (#27) — Hancom as the certification
  facility.
- Suite: 634+1 passed (was 625+1); privacy scan HARD 0.

## v0.12.4 (v0.12-W5) — gate recalibration from the real-report campaign

- Measured on 13 real workspaces (39 gate runs, 0 crashes); every relaxation
  is mechanism-level and ships a still-catches adversarial test, and an
  independent overfitting audit classified all changes, resolving its one
  OVERFIT verdict here.
- H1 web-citation ban: URLs inside the recognized reference section are now
  exempt (12/12 campaign hits were bibliography lines); body URLs stay HARD.
- `unbacked_numeral`: ledgered claims (resolvable source + evidence) back
  matching numerals; added a `constants_allowlist` pack type (schema-
  validated, additive operator override) with universal-only public defaults
  (g, c, pi, absolute zero, metric conversions).
- Gloss ban: unit symbols from the shared unit dictionary are exempt; neutral
  software-name defaults (SymPy/NumPy/MATLAB/...) extend rather than replace;
  the exemption path is tightened to exact-parenthetical match. Reference-
  heading and TITLE-matcher recognition are limited to the documented section
  grammar; corpus-specific activity-sheet keys moved to an optional
  `report_structure` pack field instead of a public default.
- Root-caused and fixed `extraction_infidelity`: the EQ tag regex misparsed
  hwpeqn scripts containing square brackets (parser correctness fix, no
  tolerance widened). Added `docs/gate-calibration.md` as the aggregate
  calibration record.

## v0.12.3 (v0.12-W4) — transform modules: extraction, form conversion, taste mining

- `content_extract.py`: hwpx -> `content.md` inverse extraction (stdlib
  zip+XML) with ordered paragraphs, direct-row table walk, and cell-level
  picture/equation recursion; `--verify` cross-checks independent source
  fingerprint counts against the extracted counts and the NFC text hash, so
  textless structure can no longer vanish behind a green verify.
- `check_convert_parity.py`: a form-convert gate comparing normalized text
  hash, element counts, normalized equation SCRIPT text, and independent
  source-walk fingerprints of both hwpx files.
- `form_extract.py`: form skeleton + fill-slot inventory from multiple
  instances; on skeleton divergence the inventory is suppressed instead of
  shipping misaligned data. `style_extract.py`: corpus -> DRAFT prose/
  structure packs, schema-validated at emit, `draft:true` + corpus sha256
  provenance, never auto-installed.
- New aliases (form-convert, form-edit, taste-mine, form-mine) and fixtures
  (picture-in-cell, equation-in-cell, nested-table, extra-row) with honest-
  PASS / tampered-HARD round-trips.
- Suite: 578 passed; privacy 0 HARD.

## v0.12.2 (v0.12-W3) — claim ledger + write-through source cache

- `claims.yaml` ledger (schema + `claims_ledger.py`): every factual claim
  bound to evidence `{source_id, locator, quote}`; stable ids, duplicate and
  dangling-source detection; `claim_extract` subcommand seeds a mechanical
  skeleton for backfill.
- `check_claims` added as the 9th `content_audit` sub-checker: unledgered
  numeric/citation content WARNs (escalates to HARD under
  `--require-ledger`); a ledgered claim with a dangling source is HARD; a
  numeric/citation claim with zero evidence is HARD; URL-only sources WARN;
  no ledger at all stays a single legacy-safe WARN.
- `source_fetch.py` write-through cache CLI records DOI/ISBN verification
  into the schema `check_sources` reads; a different-title overwrite is
  refused unless `--force`.
- Closed a self-dealing hole: cache records without retrieval metadata
  (`retrieved_from` + content sha256 + timestamp) are non-authoritative — a
  title match no longer suppresses `source_unverified`.
- `topic_pick` registered as an ENFORCED stage-0 human gate; `claim_extract`
  and `retro_research` aliases activated.
- Suite: 550+ passed; privacy 0 HARD.

## v0.12.1 (v0.12-W2) — checker_base refactor

- `checker_base.py`: shared verdict skeleton, usage/exit conventions,
  `_utf8_stdio`, strict JSON (`allow_nan=False`), CLI frame; all 8 checkers
  migrated behavior-preservingly, each keeping its own logic and standalone
  CLI.
- `claim_extraction.py` unifies the previously-diverged
  check_saeteuk/check_units/check_numbers dictionaries into one subject/
  unit/number extraction pass.
- `content_audit` sub-checkers now compose in-process (no subprocess spawn);
  any checker exception becomes a hard finding with a truncated traceback,
  while `SystemExit`/`KeyboardInterrupt` still propagate.
- `check_saeteuk` added as an ADVISORY 8th `content_audit` sub-checker: its
  contradiction HARDs surface as WARN at stage 4.5 for early discovery, while
  stage 6 keeps full HARD enforcement of the same workspace-local artifacts.
- Independent opus review confirmed the refactor behavior-preserving; suite:
  524 -> 530 passed, privacy 0 HARD.

## v0.12.0 (v0.12-W1) — composable module contracts + resolver

- `pipeline/references/modules.yaml`: 16 typed module contracts (consumes/
  produces/stage/gates/os); not-yet-implemented modules are declared
  `status:planned` and refused by the resolver.
- `compose.py`: a backward DAG resolver (`--have`/`--want`/`--alias`/`--dry`/
  `--apply`/`--matrix`) with cycle detection; ambiguity is always an error,
  never a silent choice.
- Review round closed before merge: composed plans always retain gate-bearing
  stages (2.5, 5.3/5.5/5.7/6); intake gate receipts are verified via
  `workflow_lint._receipt_satisfies_h1`; recompose refuses to discard
  non-pending stage/gate state.
- `aliases.yaml`: full-report/pre-researched/verify-only/assemble-only
  active; `docs/capability-matrix.md` generated per-alias; CI smoke asserts
  chain content on ubuntu+windows.
- R3: open-source repo surface — hero README (badges, mermaid pipeline
  diagram, project-status honesty section), CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, issue/PR templates.
- Suite: 514+ passed; privacy 0 HARD.

## v0.11.4 — Linux equation-render parity P0 (experimental) + release consolidation

- Added `pipeline/scripts/hwpx_render_surrogate.py` (canonical-immutable
  render-only HWPX copy for experimental renderers, proven via SHA-256 plus a
  runtime semantic fingerprint) and `pipeline/scripts/rhwp_proof.py` (a
  fail-closed experimental SVG proof runner that always writes `receipt.json`
  with an explicit fallback reason on any failure mode).
- `render_probe.py` mandates a `RHWP_SHA256` pin at both probe and exec time
  (unpinned/mismatched binary is never surfaced as available);
  `doc_backend.py`'s proof-grade ladder becomes
  `none < experimental-rhwp < advisory < hancom`, selecting `rhwp_svg` only
  for equation docs when Hancom is unavailable (equation-free docs keep their
  `soffice` advisory grade); `submission_preflight.py` hard-blocks
  `experimental-rhwp` from submission — unlike `advisory`, it cannot be
  waived with `--allow-advisory`.
- Added `adapters/hancom-linux-sdk/README.md`: an interface-and-evaluation-
  plan-only contract for a future Hancom Linux SDK adapter (0.5 mm
  baseline/bbox error and 300 dpi SSIM >= 0.995 acceptance matrix); no
  commercial SDK, credential, or runtime integration included.
- R1: docs realigned with v0.11.3 reality — README (release version,
  kernel-schema vs release-version distinction, four-backend table with
  proof-grade ceilings, Studio read-only default), `pyproject` rename
  `agent-report-pipeline` -> `rigorloom`, `docs/golden-path.md` single
  end-to-end walkthrough, CHANGELOG backfill for v0.7.0-v0.11.3.
- R2: documented the experimental rhwp path post-P0 merge (README backend
  table + experimental section, golden-path "equation documents on Linux
  (experimental)" subsection); externally-supplied pixel metrics stayed
  tagged `provenance: external` rather than restated as repo facts.
- Honest status: `docs/plans/p0-parity-report.md` records this work as
  **PARTIAL** — canonical-preservation and semantic-fingerprint parity are
  reproduced in this repository, but pixel-level parity with Hancom rendering
  is not achieved (max displacement 676px externally reported, `provenance:
  external`, `reproducible: false`), so COM stays the submission-grade proof.

## v0.11.3 (v0.11-Z5) — anti-fabrication frontier

- Added `check_sources.py`: offline citation-reality verification against a
  local DOI/ISBN cache under `<PROFILE_ROOT>/cache/sources/`; HARD only on a
  provable-fake reference, WARN otherwise.
- Added `check_saeteuk.py`: deterministic saeteuk-to-report numeric and
  named-entity consistency checker, composed into `submission_preflight.py`.
- Added `check_units.py` as the seventh `content_audit` sub-checker: WARN-only
  unit/dimension consistency over a deterministic SI + Korean unit dictionary.
- `content_audit.py` now runs all seven sub-checkers (verify_content,
  check_style, check_numbers, check_refs, check_figdata, check_sources,
  check_units) and merges verdicts with worst-exit-wins semantics.
- Follow-up hardening passes closed 9 fail-open and 4 false-block findings
  from an adversarial review round, plus a design-review calibration pass on
  gate semantics, generic-subject handling, and cache robustness.
- Limitation: source verification is offline-cache-only — an unlisted but
  genuine reference is not distinguishable from a genuinely fabricated one
  without network access, which this checker deliberately does not use.

## v0.11.2 (v0.11-Z4) — figure/form integrity batch

- Added figure-data integrity check: a referenced PNG with a sidecar
  `<f>.sha256` or figure manifest is HARD-checked against the sim output; no
  manifest is WARN `figure_unverified` (legacy workspaces tolerated).
- Added the form-hash gate to `submission_preflight.py`: the assembled HWPX's
  FORM-owned structure hash (charPr/paraPr/secPr/tbl/tc/ctrl skeleton, text
  excluded) is recomputed and compared against `form_baseline.json` or
  `build.yaml`'s recorded digest; mismatch is HARD `form_mutated`, no baseline
  is WARN `form_baseline_absent`.
- Added corpus consistency checks and a sync orphan garbage-collection fix for
  `sync_local.py`.
- Limitation: the form baseline is trusted-on-record, not cryptographically
  proven — a baseline recorded after a mutation cannot detect that mutation.
  A signed external baseline is deferred.

## v0.11.1 (v0.11-Z3) — numbering lint, snapshots, sync stamp

- Added figure/table numbering + cross-reference lint into `content_audit`:
  scans `bundle/content.md` for monotonic 그림/표 numbering and resolves
  in-text cross-references; skipped/duplicate numbers or dangling references
  are HARD, ambiguous forms are WARN.
- Added `ws_snapshot.py`: zips `bundle/`, `output/`, `PIPELINE.md`, and
  `.pipeline/` into a rotating pre-assembly snapshot before Stage 5, with a
  symlink-safe, zip-slip-resistant `restore` command.
- Added a sync version stamp to `sync_local.py`'s per-file receipts.

## v0.11.0 (v0.11-Z2) — format gate, fabrication checks, delivery integrity

- Registered `verify_format.py` as the Stage 5.3 `format_check` script gate
  (previously advisory prose only); it hard-enforces body font size, line
  spacing, and — with `--require-output` — that `output/out.hwpx` exists,
  which makes `bundle`- and `docx`-only builds fail this gate by design.
- Added simulation seed provenance requirements (an empty RNG seed now fails
  the `sane` gate) and a prose-numeral-vs-`results.json` diff check.
- Added operator preference-pack schema validation ahead of every sub-checker,
  and pack-enforcement findings that fail closed on an invalid pack.

## v0.10.0 — typeset parity without Hancom, Studio/Linux integration

- `pipeline/scripts/render_probe.py` added: a stdlib-only, self-guarded probe
  for Hancom COM, `soffice` (local and via WSL), and the H2Orestart
  LibreOffice filter; never launches Hancom, never raises.
- `doc_backend.py`'s `hwpx` dispatch gained automatic advisory-proof wiring:
  it picks Hancom when available, otherwise a `soffice` renderer for
  equation-free documents only (equation-bearing documents get `proof_grade:
  none`, since H2Orestart's equation fidelity is unverified).
- Studio gained Linux-compatible capability probing and render-status chips.
- Recorded, in the v0.10 plan, that LibreOffice+H2Orestart equation fidelity
  is a known, deliberately excluded gap — not a bug to be silently patched
  over.

## v0.9.0 — Hancom-free document stack (hwpx tier)

- Added the `hwpx` Stage 5 document backend: an external hwp-master XML
  engine that fills a form's HWPX/OWPML XML directly, without Hancom or COM,
  on any OS. `doc_backend.py` dispatches to it via `HWP_MASTER_SCRIPTS`.
- Added Studio v2 (dashboard, provenance view, lint badges, token-guarded
  action endpoints) and an edit-workflow graph with an off-workflow
  conformance linter.
- Added humanization v3: pack-driven voice, a deterministic pre-pass, and a
  no-progress hold to stop runaway rewriting.
- Limitation, stated plainly at the time: LibreOffice+H2Orestart rendering
  fidelity for equations and complex forms was undocumented and unmeasured;
  the tier was labeled advisory proof from day one, not submission-grade.

## v0.7.0 — gate integrity convergence

- Converted the kernel from documentation-enforced to gate-enforced: the
  `check` subcommand now actually runs a stage's bound checker and records
  its verdict; the old `--script-exit` caller-supplied-integer path was
  retired, closing the "gate passed with a typed 0" hole found in an
  unattended run.
- Added the Stage 4.5 `content_audit` gate (freeze content before assembly)
  with its first deterministic checkers (content, style, format, figures,
  privacy).
- Added the preference-pack system v2 (schemas, neutral defaults, hash-only
  lock) and the `sync_local.py` base+overlay installer with drift refusal and
  atomic swap.
- Fixed POSIX portability issues (flock-based lock liveness, platform-agnostic
  figure paths) surfaced by running the pipeline outside Windows for the
  first time.
- Limitation acknowledged in the v0.7 plan: without a release attestation
  step, this is gate *integrity*, not full fail-closed — a direct-assembly
  bypass of the state machine remained possible until later waves narrowed it
  further.
