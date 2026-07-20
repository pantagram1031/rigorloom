# v0.15 — Renderer certification: retire Hancom from runtime to certification facility

Swap: codex stalled after finishing the fix-round edits (no commit for 35+ min);
Claude verified (634 tests green, opus re-audit READY) and committed.

Status: PLANNED. Input: docs/research/linux-hwp-edit.md (merged, PR #26).
Owner: orchestrator (Claude) plans/reviews; codex implements; opus judgment pass
on the gate integration before merge.

## Idea

We own a genuine Hancom installation. That makes it possible to *certify* an
open renderer by measured behavioral equivalence instead of trusting it: use
Hancom to generate (document, reference render) pairs over a feature-tagged
corpus, measure a candidate renderer against them, and issue a **document-scoped
certificate**. At runtime, a document whose feature set is inside the certified
envelope may accept the certified Linux render; anything outside falls back to
Hancom exactly as today. Hancom moves from a per-document runtime dependency to
a certification facility invoked when (re)issuing certificates.

Non-goals: a universal "Linux renders HWP correctly" claim (induction problem —
certificates are envelope-scoped and version-pinned); replacing the hancom
proof grade as the default submit grade in this wave.

Induction caveat: the certified envelope is downward-closed. A measured feature
ceiling admits documents containing subset combinations beneath that ceiling,
even when every subset was not independently measured; this extrapolation is
intentional, envelope-scoped, and not evidence of universal renderer fidelity.

## Components

### 1. feature_extract (new: pipeline/scripts/feature_extract.py)
Static HWPX analysis → canonical, sorted feature tag set with counts.
Minimum tag vocabulary: sections, columns, tables, nested-table-depth,
equations, images, headers/footers, footnotes/endnotes, floating objects,
shapes/lines, fields, hyperlinks, charPr variety (font count), page size/margins
class. Deterministic output (same doc → same tags). Unknown/unrecognized
controls MUST emit an `unknown:<tag>` feature — unknown features can never be
inside any envelope (fail-closed).

### 2. Certification corpus (tests/corpus/render-cert/ manifest + generators)
- Manifest lists each corpus doc: id, generator (ops.json for the COM builder or
  sanitized template ref), feature tags (verified equal to feature_extract
  output), reference PDF sha256, Hancom version string.
- Split declared in the manifest: `train` / `holdout` (calibration rule:
  mechanism fixes tuned on train only; certificate validity requires holdout
  pass — permanent no-overfit memory applies).
- First corpus target = OUR envelope: the five template forms + feature
  combinations the pipeline actually emits. General-HWP coverage is later.
- Reference renders are generated on the operator's Windows machine (Hancom
  COM). The harness must treat references as inputs (path + hash), never
  attempt to invoke COM itself on Linux/CI.

### 3. render_cert (new: pipeline/scripts/render_cert.py)
- `measure --renderer <id> --corpus <manifest>`: run the candidate renderer
  (rhwp CLI, @rhwp/core via node, or soffice) per corpus doc, compare against
  the reference with the existing word-anchor comparer and a raster
  changed-channel ratio, plus exact page count. Per-doc, per-metric JSON out.
- `certify`: aggregate measure results → certificate JSON:
  {renderer_id, renderer_version, renderer_binary_hash, hancom_version,
   corpus_manifest_hash, thresholds, envelope (feature sets with all-pass),
   train_stats, holdout_stats, issued_at}. Any holdout failure removes the
  affected feature combinations from the envelope. Metrics thresholds live in
  the certificate, not hard-coded (report Q6: page-count exact; word-anchor px;
  raster ratio — separate thresholds per metric).
- `check <doc> <certificate>`: feature_extract(doc) ⊆ envelope AND renderer +
  Hancom versions match AND manifest/binary hashes verify → eligible; every
  other outcome → not eligible with a reason code.

### 4. Runtime integration (proof-grade ladder)
- New grade `certified` sits ABOVE advisory, BELOW hancom. It never outranks a
  live hancom verdict and never silently becomes submit-grade.
- submission_preflight accepts `certified` only when (a) build.yaml explicitly
  opts in, (b) render_cert check passes at preflight time, (c) the certificate
  file itself re-verifies. Missing/mismatched/altered certificate → today's
  behavior, unchanged.
- render_probe advertises certified availability only when a valid certificate
  exists for an installed renderer.

### 5. Tests (red first)
- envelope mismatch → refused (incl. `unknown:` feature always refused)
- renderer or Hancom version mismatch → refused
- certificate file edited after issue → refused (hash re-verification)
- holdout failure → feature combo excluded from envelope at certify time
- no certificate present → all existing suites byte-identical behavior
- feature_extract determinism + unknown-control fallback

## Work split
- codex: feature_extract, render_cert, corpus manifest format + generators,
  tests with synthetic mini-fixtures and mocked references. No COM calls.
- operator machine (Claude-driven, local): generate real corpus references via
  COM, run first real measure/certify for rhwp 0.7.19, record results.
- opus review: gate integration fail-closed audit before merge (same bar as
  v0.12 waves: 598+ tests green, privacy HARD 0).

## Sequencing note
Independent of v0.13.1 (extension policy boundary) — different subsystem, can
land before or after. Feeds the Studio web-editor spike (certified rhwp SVG =
preview path with a fidelity story).
