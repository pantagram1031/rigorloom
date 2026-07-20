# Renderer-certification corpus

`manifest.json` is the canonical corpus index. Each ready entry records an id,
`train` or `holdout` split, document path, generator provenance, the exact
`feature_extract.py` feature-count map, reference PDF path and SHA-256, and the
Hancom version that produced the reference.

Windows-reference generators stop at a portable handoff. `generate.py` writes
`ops/<id>.ops.json` and a manifest entry with status
`awaiting_windows_reference`; it never imports or invokes Hancom, COM, pyhwpx,
or the Windows reference builder. The operator machine creates the HWPX and PDF,
fills their hashes/version/features, and changes the entry to `ready` before
`render_cert.py measure` may consume it.

Example stub command:

```sh
python tests/corpus/render-cert/generate.py \
  --id form-a-train --split train \
  --document form-a.hwpx --reference-pdf form-a-reference.pdf \
  --template-ref sanitized/form-a.hwpx --ops-json form-a.ops.source.json
```
