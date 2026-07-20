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

## Deviations and boundaries

No deviations from the plan's Codex work split. Real five-form corpus documents,
Hancom reference PDFs, and the first rhwp certificate were not generated here:
those are explicitly operator-machine work. The committed generator stops at
the required `ops.json` and pending manifest handoff and never invokes COM,
Hancom, or LibreOffice.

No extension-pack files were touched.
