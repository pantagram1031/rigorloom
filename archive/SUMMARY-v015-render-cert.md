# v0.15 renderer-certification harness

Branch: `v015-render-cert`

## Implemented

- `pipeline/scripts/feature_extract.py`
  - deterministic sorted HWPX feature-count maps;
  - sections, columns, tables/nesting, equations, images, header/footer,
    notes, floating objects, shapes/lines, fields, hyperlinks, font variety,
    and page-size/margin classes;
  - fail-closed `unknown:<tag>` controls.
- `pipeline/scripts/render_cert.py`
  - `measure --renderer --corpus`, `certify`, and `check <doc> <certificate>`;
  - existing unique-word anchor metric, exact page counts, and raster
    changed-channel ratios;
  - certificate-owned thresholds, train/holdout aggregation, envelope removal
    on holdout failure, self-hash, manifest/binary hashes, pinned versions, and
    stable eligibility reason codes.
- `tests/corpus/render-cert/`
  - schema-v1 manifest and JSON Schema;
  - generic Windows-reference handoff generator that writes only `ops.json`
    plus a pending manifest entry and stops;
  - operator instructions describing the Windows completion boundary.
- Proof-grade integration
  - grade order `none < experimental-rhwp < advisory < certified < hancom`;
  - `render_probe` advertises certified rendering only for a fully reverified
    configured certificate;
  - `doc_backend` keeps the existing renderer as fallback and promotes a
    post-assembly certified PDF atomically only after opt-in, document check,
    successful render, and PDF reopen;
  - `submission_preflight` accepts `certified` only when `build.yaml` contains
    `certified_render: true` and `render_certificate: <path>`, the live check
    passes, and the certificate independently re-verifies.
- Documentation updated in `docs/golden-path.md` and the Stage 5/6 playbooks.
- Synthetic/mocked tests added or extended in:
  - `pipeline/tests/test_feature_extract.py`
  - `pipeline/tests/test_render_cert.py`
  - `pipeline/tests/test_render_probe.py`
  - `pipeline/tests/test_doc_backend.py`
  - `pipeline/tests/test_submission_preflight.py`
  - `pipeline/tests/test_rhwp_proof.py`

## Verification

| State | Collected | Passed | Skipped | Subtests |
|---|---:|---:|---:|---:|
| Before | 603 | 602 | 1 | 24 |
| After | 626 | 625 | 1 | 26 |

Full after command: `python -m pytest -q` — completed in 290.76 seconds.
The one skip is the pre-existing optional `python-docx` install-hint test.

Final required checks:

- `python pipeline/scripts/privacy_scan.py . --json` — HARD 0, WARN 2 (the
  pre-existing synthetic privacy-scanner fixture warnings).
- `git diff --check` — clean.

## Adversarial fix round (2026-07-20)

- Certificate trust is now externally bound:
  - certificates embed normalized per-document measurement records and a
    re-verifiable measurement hash;
  - issue and verify re-derive the envelope and split statistics from the
    hash-anchored manifest feature maps, embedded measurements, and thresholds;
  - `pipeline/scripts/receipt_sign.py` creates/loads
    `${RIGORLOOM_PROFILE_ROOT}/keys/render_cert.key` with POSIX mode 0600 or a
    Windows owner-only DACL and authenticates canonical certificate bytes with
    HMAC-SHA256;
  - missing keys, missing/stale HMACs, measurement drift, and derived-envelope
    drift all fail closed with stable reason codes.
- Feature extraction now classifies every section-body descendant by local
  name against explicit feature-handled and fixture-curated benign constants;
  every other element emits `unknown:<local-name>`. A synthetic
  `<hp:chart>` run child is therefore unknown and cannot enter an envelope.
- The certification plan now records the downward-closed envelope induction
  caveat. Operator documentation records the private key and full verification
  requirements. The audited runtime ladder wiring was not changed.
- Red-first adversarial coverage includes recomputed-self-hash envelope
  widening with absent/stale HMACs, raised thresholds with a stale HMAC,
  manifest/measurement envelope drift, embedded measurement-hash drift,
  corpus-less fabrication without a valid signature, missing verification key,
  first-use key generation, and the run-child unknown-tag path.

Fix-round verification:

- `python -m pytest -q pipeline/tests/test_feature_extract.py pipeline/tests/test_render_cert.py`
  -> 22 passed, 2 subtests passed.
- Certification/runtime integration slice
  -> 105 passed, 1 skipped, 10 subtests passed.
- `python -m pytest -q`
  -> 634 passed, 1 skipped, 28 subtests passed in 427.39 seconds.
- `python -m compileall -q pipeline/scripts`
  -> passed.
- `python pipeline/scripts/privacy_scan.py . --json`
  -> HARD 0, WARN 2 (unchanged synthetic scanner-fixture warnings).
- `git diff --check`
  -> clean.

## Deviations and boundaries

No deviations from the plan's Codex work split. Real five-form corpus documents,
Hancom reference PDFs, and the first rhwp certificate were not generated here:
those are explicitly operator-machine work. The committed generator stops at
the required `ops.json` and pending manifest handoff and never invokes COM,
Hancom, or LibreOffice.

No extension-pack files were touched.

## Post-v0.15.0-alpha additions (released in v0.16.0)

Everything after this tag shipped as **v0.16.0** — see `CHANGELOG.md`'s
"v0.16.0 — unified core and modules" section for the full per-PR breakdown
(#29–#55) and `docs/release-v0.16.0.md` for the release record (bundle
inventory, suite matrix, privacy evidence, capability boundaries).

- **Gate architecture resolved (hybrid)** — `verdict_schema.py` is wired
  into `submission_preflight`; `check_residue.py`, `check_density.py`, and
  `check_canonical.py` are reachable through the declared-values gate
  runner (#36), whose kinds delegate to registry mechanisms (`canonical`
  is declared by the report module via `gate_kinds`). The Wave 1 Lane V
  registry-vs-declarative question this file used to flag is closed:
  registry mechanisms, declared values.
- **Distribution modules** — the engine was absorbed at `engine/` (W2),
  and report/style capability moved behind the module contract
  (`modules/README.md`) with per-module bundles built by
  `scripts/package_module.py`. `constants_allowlist` remains never
  extension-installable (v0.13.1 boundary), now enforced from the
  registry-computed pack-type sets.
- **This file's own task closed** — F3 version-drift reconciliation and
  the final v0.16.0 reality pass are done; README/CHANGELOG/SUMMARY and
  the capability matrix describe the same repo.

## Post-v0.16.0 additions (released in v0.17.0)

Current version: **v0.17.0** (pending tag). Full per-PR breakdown in
`CHANGELOG.md`'s "v0.17.0 — validated product" section (#57–#77); the evidence
record — bundle inventory with hashes, the validation ledger, and the limits
stated as limits — is `docs/release-v0.17.0.md`.

v0.16.0 shipped as an alpha: written by its authors, run on the authors'
machine, exercised on one form-family lineage, empty forms only. v0.17 is the
release that validated it.

- **Autonomous verification.** `pipeline/scripts/visual_verify.py` merges every
  deterministic backstop into one findings list, then prepares a vision task
  against a closed 12-class rubric (`skill/references/visual-rubric.md`) and
  consumes the handback — it never calls a model itself, and an unknown rubric
  class is a usage error rather than a finding (#57, #61). `SAFETY_CHECKS`
  names in one place the five checks whose absence invalidates acceptance, so
  `acceptance: true` over an unwaived skip is impossible; `--accept-without`
  is per check and on the record; and the six-row exit-code contract is pinned
  by `test_exit_code_matrix` with no path exiting 1 (#75).
- **Clean-room validation.** `evals/` installs from dist zips into a throwaway
  root, self-checks through the *packaged* verifier, and asserts containment on
  five independent axes with no fallback to the checkout (#58). It immediately
  found the v0.16.0 core bundle shipping no skill surface (#59). Three measured
  cross-model rounds produced the shipped routing table at
  `skill/references/model-routing.md` (#63, #72), and an independent Codex
  harness across three tiers found the two acceptance/exit-code defects our own
  harness could not see (#75).
- **Six modules, seven bundles.** Four work-type modules added with zero core
  edits: `gongmun` (#65), `minwon` (#68), `hr` (#69), `grant` (#70). The three
  contract gaps the first unplanned module exposed are closed — the test
  harness is module-agnostic by property, eval machine checks have a
  `requires_module` gate, and a checker can declare `wants: [baseline]` (#67).
- **The offline fill path is complete.** `preedit fill-cells` reaches a
  genuinely empty cell (T27), `replace --at-cell`/`--at-cell-append` reach a
  printed seat without its exact whitespace (T34), single-pass `replace` no
  longer double-applies a value containing its own key (T26), COM `set_cell`
  addresses real `cellAddr` (T28), and the charPr pre-flight refuses an
  anomalous fill target instead of silently rendering it at ~6.35pt (T30/T32).
  One `--fill-map` shape rule for every consumer (T35), and
  `classification: spacer` stops reporting structural filler as a fill target
  (#60, #62, #66, #73, #74, #76).
- **Inventory pins are a defect class (T33).** A core test asserting `== N` on
  something the repo grows blocked three modules; `tests/test_no_inventory_pins.py`
  is the durable guard (#71).
- **Honest limits carried forward.** School and corporate form families have no
  corpus at all; the harness axis has exactly one non-Claude data point; no
  fully independent party has run this; page-budget rules ship permanently
  skipped with named reasons. All stated in `docs/release-v0.17.0.md`.
