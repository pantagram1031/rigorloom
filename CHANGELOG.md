# Changelog

Format is loosely [Keep a Changelog](https://keepachangelog.com/); versions
correspond to Git tags. The stage-machine schema version (`pipeline/references/
stages.yaml`'s `version: "0.6"`) has not changed since v0.7 — these releases
add gates, backends, and tooling on top of a stable kernel, they do not change
the kernel's contract shape.

## Unreleased (main, post-v0.15.0-alpha)

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

## Unreleased — Linux equation-render parity P0 (experimental)

- Added `pipeline/scripts/hwpx_render_surrogate.py`: builds a canonical-immutable
  render-only HWPX copy for experimental renderers — strips only the XML
  backend's exact stale one-line `linesegarray` placeholder signature,
  verifies the canonical file's SHA-256 is unchanged on disk, and rejects the
  surrogate if a runtime semantic fingerprint (normalized body-text hash plus
  paragraph/table/picture/equation counts) doesn't match the canonical before
  and after.
- Added `pipeline/scripts/rhwp_proof.py`: a fail-closed experimental SVG proof
  runner — creates the surrogate, invokes `rhwp export-svg`, and always writes
  a `receipt.json` (`ok`, `proof_grade`, `page_count`, `layout_overflow`,
  `parity_verdict`) even when the binary is missing/unpinned, the run times
  out, exits nonzero, or produces zero pages, with an explicit
  `canonical_hwpx_without_render_proof` fallback reason.
- `render_probe.py`'s `verify_rhwp_binary` now mandates a `RHWP_SHA256` pin
  matching the SHA-256 of the selected `rhwp` executable file itself; an
  unpinned or mismatched binary is reported `rhwp_unpinned` /
  `rhwp_hash_mismatch` and is never surfaced as an available renderer.
- `doc_backend.py`'s `_hwpx_renderer_decision` extends the proof-grade ladder
  to `none < experimental-rhwp < advisory < hancom` and selects `rhwp_svg`
  when Hancom is unavailable and the document has equations (or no `soffice`
  renderer exists at all); `submission_preflight.py` hard-blocks
  `experimental-rhwp` from submission (`P5`: "diagnostic render evidence, not
  a submission proof grade") — unlike `advisory`, it cannot be waived with
  `--allow-advisory`.
- Added `adapters/hancom-linux-sdk/README.md`: an interface-and-evaluation-
  plan-only contract for a future Hancom Linux SDK adapter (probe/render
  receipt shape, 0.5 mm baseline/bbox error and 300 dpi SSIM ≥ 0.995
  acceptance matrix); no commercial SDK, credential, or runtime integration
  is included.
- Honest status: `docs/plans/p0-parity-report.md` records this work as
  **PARTIAL** — canonical-preservation and semantic-fingerprint parity are
  reproduced in this repository, but pixel-level parity with Hancom rendering
  is not achieved, and the largest reported displacement/mismatch figures are
  externally supplied (`provenance: external`, `reproducible: false`), not
  computed by any differ in this repository.

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
