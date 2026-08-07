# Changelog

Format is loosely [Keep a Changelog](https://keepachangelog.com/); versions
correspond to Git tags. The stage-machine schema version (`pipeline/references/
stages.yaml`'s `version: "0.6"`) has not changed since v0.7 — these releases
add gates, backends, and tooling on top of a stable kernel, they do not change
the kernel's contract shape.

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
