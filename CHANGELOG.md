# Changelog

Format is loosely [Keep a Changelog](https://keepachangelog.com/); versions
correspond to Git tags. The stage-machine schema version (`pipeline/references/
stages.yaml`'s `version: "0.6"`) has not changed since v0.7 — these releases
add gates, backends, and tooling on top of a stable kernel, they do not change
the kernel's contract shape.

## Unreleased (main, post-v0.15.0-alpha)

- (`privacy: sha256-pinned corpus allowlist w/ content-scan still-catches`,
  branch `w5-evals`, v0.16 W5.2) — `privacy_scan` gained
  `--binary-allowlist <manifest.json>` (auto-detected at
  `tests/corpus/forms/manifest.json`): a binary document passes the
  categorical `binary_document_ext` rule only when its path is listed AND
  its sha256 matches the manifest pin; unlisted binaries and hash drift
  stay HARD (`binary_allowlist_hash_mismatch`), and allowlisted files are
  still content-scanned (new HARD rules `binary_pii_rrn` /
  `binary_pii_phone` plus the existing email/user-path/denylist nets over
  extracted hwpx XML or a stdlib UTF-16 harvest of binary hwp) so a filled
  document can never hide behind the allowlist. Bundles never apply the
  allowlist — `package_module` staging stays categorical, with a regression
  test asserting no `tests/corpus/forms` member lands in any bundle
  (module bundles carry their own tests only). Ruling recorded in
  `docs/gate-calibration.md` and the corpus manifest's `privacy` section.
- (`evals: blank-form corpus (official sources) + per-family eval
  scenarios`, branch `w5-evals`, v0.16 W5.2) — `tests/corpus/forms/`:
  12 blank official templates across 5 families with a sha256/source/license
  manifest and 5 recorded skips (school family = corpus gap, corp family =
  documented no-official-source boundary); `probe_results.json` Bench-0
  baseline (`form_inspect` over both native hwpx members; the 10 `.hwp`
  members recorded as conversion-blocked until W6 XC-1);
  `docs/research/form-eval-scenarios.md` with 10 open→recognize→fill→verify
  scenarios (machine + judgment rubrics; A1/A2 runnable today and set as
  the W5.3 acceptance floor).
- (`personalization: general/report pack split, store portability, schema
  rename w/ compat`, branch `w4-personalization`, v0.16 W4.1) — core
  `personalization_ctl` now declares only GENERAL pack types (`prose_rules`,
  `figure_style`, `backends`, `policy_floors`); the report-flavored five
  (`saeteuk`, `report_structure`, `gloss_allowlist`, `constants_allowlist`,
  `tone_rules`) are report-module payload — their schema/default files moved
  to `modules/report/references/preference_packs/`, and `PACK_TYPES` /
  `DATA_EXTENSION_PACK_TYPES` are computed at access time from core built-ins
  + `ModuleRegistry.enabled_pack_types()` (trust-sensitive types —
  `backends`, `policy_floors`, `constants_allowlist`, and per the W4.1
  ruling `tone_rules`, a deterministic-checker relaxation vector — stay
  excluded from extensions, runtime re-enforced on resolve). Using a
  module-declared pack type on a core-only install is a loud error naming
  the missing module. Store schema renamed
  `report-pipeline/personalization-v1` → `rigorloom/personalization-v1`
  (lock likewise, `lock_version` 5) with legacy strings accepted on read
  (warned once). New `export`/`import` CLI: manifest+sha256 zip of the
  profile root that NEVER includes the privacy denylist; import verifies
  byte-for-byte, refuses tamper and non-empty targets. `privacy_scan` gained
  the profile-store leak marker class (`profile_store_content` /
  `profile_store_path`, both HARD), so packaging refuses any bundle staging
  store content.
- **#29** (`v0.15 follow-up: feature-classification fixes + v0.16 master
  plan`, landed directly on `main`) — the first real corpus run (genuine
  Hancom-saved documents) surfaced five section-level rendering element
  names (`pageBorderFill`, `visibility`, `startNum`, `grid`,
  `lineNumberShape`) that a blanket-benign classification would have made
  fail-open in `feature_extract.py`; they now emit attribute- and
  whole-subtree-fingerprinted feature classes (`sec-config:<tag>:<fp>`), so
  a document certifies only under the exact section configuration the
  corpus measured. Also added the v0.16 master plan
  (`docs/plans/v0.16-unified-core-and-modules.md`,
  `docs/plans/v0.16-prep-variant-audit.md`) and
  `docs/research/skill-efficiency-gen5.md`.
- **#30** (`docs: audit performance metrics + Phase 0 judgment verdicts`,
  branch `docs/audit-metrics-and-verdicts`) — docs-only: added the
  variant-audit metrics section (gate quality / convergence cost / assembly
  fidelity / output-vs-corpus-band / ops / skill efficiency) as the Wave 1
  Lane V exit criterion, and recorded the master plan's extension-packs
  ABSORB verdict (v0.13.1 conditions).
- **#31** (`research: variant-audit decision matrix (Phase 0.C complete)`,
  branch `audit/decision-matrix`) — added `docs/research/variant-audit.md`:
  five differential benches over existing artifacts (zero pipeline reruns).
  Headline findings: all five audited variants' recorded state diverged
  from reality; `score_ai_tells` showed zero discrimination on a
  25%-changed section; a hawkes-sim pre-edit latent defect was found.
  Verdicts: hybrid gate architecture with form-scan auto-derived residue
  lists, two run modes plus a mandatory provenance floor, H2 advisory-only,
  and five shared-miss mechanisms. Unblocks the Wave 1 Lane V docket.
- **#32** (`packs: land v013 extension packs with v0.13.1 policy
  conditions`, branch `v013-packs-landing` merging
  `codex/v013-extension-packs`) — landed the data-only extension-pack
  system (`scripts/extension_pack.py`: validate/install/list/doctor/activate,
  `docs/extensions.md`) under a v0.13.1 policy boundary applied at merge:
  `constants_allowlist` is excluded from `DATA_EXTENSION_PACK_TYPES` — it
  stays a profile-level pack managed through `personalization_ctl` and is
  never installable from an extension pack, since it is a confirmed
  relaxation vector for `check_numbers`' deterministic numeric checker.
  Also fixed a `merge_pack`/`_stable_union` regression where a global
  `gloss_allowlist` pack deep-merged over defaults erased the 14 W5b
  neutral terms; the resolved terms are now the stable union. Full suite at
  merge: 662 passed, 1 skipped, 28 subtests.
- **#33** (`gates: residue auto-derivation, H5 density, canonical binding,
  verdict contradiction`, landed directly on `main`) — added four new
  checkers from the variant-audit's shared-miss findings:
  `check_residue.py` (a form's scanned anchor/guide-text inventory becomes
  the final artifact's forbidden list, auto-derived per form; a missing
  pinned target is HARD, never a silent pass), `check_density.py` (H5
  structural gate: bold-subhead count per 10k bytes of `content.md`, WARN
  at >= 3.0, HARD at >= 4.5), `check_canonical.py` (the workspace's
  declared canonical/`FINAL` pointer must exist and resolve once a delivery
  stage claims done), and `verdict_schema.py` (rejects a `converged: true`
  + `status: escalate_human` contradiction in an assembly verdict file;
  wired into `submission_preflight`). `check_residue`, `check_density`, and
  `check_canonical` are standalone, tested CLI scripts — none of the three
  is composed into `content_audit` or `submission_preflight` yet; that
  remains a pending Wave 1 Lane V gate-architecture decision.
- **#34** (`gates: malformed artifact XML is HARD in check_residue`, landed
  directly on `main`) — `check_residue.py` now XML-parses every hwpx
  section/header member before the residue text scan; a parse failure is a
  HARD `artifact_malformed` finding (member + position). Found live: a
  corrupt `section0.xml` passed the prior regex text scan while Hancom
  rendered the document blank (T23).

Full suite as of this window: 712 passed.

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
