# Hancom Linux SDK adapter contract

Status: interface and evaluation plan only. No commercial SDK, credential,
license, download, or runtime integration is included.

## Capability interface

An implementation must expose two side-effect-bounded operations.

1. probe
   - Returns engine name, SDK/runtime version, supported input/output formats,
     equation support, and a machine-readable unavailable reason.
   - Must not open an interactive application or mutate a document.
2. render
   - Accepts an absolute, read-only canonical HWPX path, an output directory,
     and a timeout.
   - Writes only renderer outputs and a receipt under output/proof.
   - Never overwrites or re-saves the canonical HWPX.

The receipt contract is:

    {
      "engine": "hancom-linux-sdk",
      "version": "...",
      "proof_grade": "none",
      "submission_grade": false,
      "page_count": 0,
      "normalized_text_sha256": "...",
      "counts": {
        "tables": 0,
        "pictures": 0,
        "equations": 0
      },
      "layout_overflow": null,
      "clipping_count": null,
      "overlap_count": null,
      "missing_object_count": null,
      "baseline_max_error_mm": null,
      "object_bbox_max_error_mm": null,
      "raster_dpi": 300,
      "raster_ssim": null,
      "render_diff": {},
      "ir_diff": {},
      "fallback": null,
      "reason": "not_evaluated"
    }

The adapter must initially return proof_grade none. A future grade such as
hancom-server may be enabled only after an artifact-bound acceptance run meets
every criterion below. Product identity alone is not proof of parity.

## Evaluation plan

Evaluate the same private acceptance corpus and public synthetic fixtures with:

- the pinned Windows Hancom COM oracle;
- the candidate Hancom Linux server SDK;
- rhwp SVG as diagnostic evidence.

For each document, require:

- exact page-count, normalized-text-hash, and table/picture/equation counts;
- maximum body-baseline and object-bounding-box error of 0.5 mm;
- 300 dpi raster SSIM of at least 0.995;
- zero clipping, overlap, and missing objects;
- recorded SDK version, input/output SHA-256, timeout, and fallback reason.

Any missing metric, renderer failure, or structural mismatch remains
non-submission proof. Until the candidate passes this matrix, route final
submission proof to the existing Windows Hancom COM backend.
