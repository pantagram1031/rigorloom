# Exact-document renderer certificate envelope v2 (T151)

Checked 2026-08-11. T151 is a receipt-only, snapshot-bound check for an exact
document. It is deliberately separate from renderer execution, backend
selection, and the certified proof ladder. A matching source hash does not
generalize to a feature subset, a new document, or a proof grade.

## Closed schema and commands

The public certificate schema is
`rigorloom/render-cert-envelope/v2`. The input is a private operator manifest
with schema `rigorloom/render-cert-private-manifest/v2`. The manifest may name
its relative source and reference leaves and carries the already measured
metric hashes; those private inputs are read only while issuing the envelope.

The only CLI contract is:

```text
python pipeline/scripts/render_cert_envelope_v2.py issue PRIVATE_MANIFEST --out CERT
python pipeline/scripts/render_cert_envelope_v2.py verify CERT
python pipeline/scripts/render_cert_envelope_v2.py check DOCUMENT CERT
```

`issue` publishes one canonical certificate only after rebinding the manifest,
source, and reference snapshots. `verify` validates canonical JSON, the
self-hash, and the operator HMAC. `check` captures a bounded document snapshot
and compares its exact SHA-256 and byte count with one signed measurement;
changed, replaced, or ambiguous input is refused. A successful result names
that captured digest and `binding_scope: captured_snapshot_only`; it does not
assert the future state of the mutable source or certificate paths. Even an
exact snapshot match is diagnostic: `check` returns refusal exit code 3 so a
caller cannot treat it as promotion proof.

## Pathless public payload

The certificate contains only these bounded values:

- schema and reference-renderer identity;
- manifest and threshold SHA-256 values;
- measurements containing an opaque id, source SHA-256/byte count, reference
  PDF SHA-256/byte count, and the private metric SHA-256;
- `evidence_ceiling: exact_document_measurement_only`;
  `runtime_binding: not_established`; `proof_grade: none`;
  `submission_grade: false`; `promotion: not_run`;
- `certificate_sha256` and `certificate_hmac_sha256`.

No document, reference, or candidate path is serialized. The public bytes do
not contain local paths, command/argv, stdout/stderr, source text, feature
maps, private manifest contents, operator key material, corpus bytes, or PDF
payloads. The private manifest and operator key remain out-of-tree inputs and
are never packaged or copied into a certificate.

The body hash covers the canonical fields before the two certificate fields;
the HMAC binds that body and the self-hash. Any field addition, duplicate key,
non-canonical JSON, snapshot drift, or HMAC mismatch fails closed.

## Evidence and routing boundary

This envelope ships no renderer and does not execute one; it does not call
`doc_backend.py`, `render_probe.py`, `submission_preflight.py`, Stage 0,
Stage 5, Stage 6, or `new_report.py`. It never writes
`output/proof/backend/receipt.json`, changes `output/out.hwpx`, selects a
renderer, or auto-routes a document. `ADVISORY_PROOF_RELEASE_ENABLED=False`
and `CERTIFIED_PROOF_RELEASE_ENABLED=False` remain unchanged.

The legacy `pipeline/scripts/render_cert.py` v1 certificate workflow remains
quarantined and diagnostic-only. Its external-file and inline JSON loaders now
refuse duplicate object members recursively; certificate `verify`/`check`
reports `certificate_invalid_json`, while an outer CLI operation that cannot
parse its input reports `operation_failed`. This is duplicate-member rejection
only; it does not expand canonical JSON, non-finite-value, or HMAC semantics.
T156 separately enforces finite JSON for the legacy external and inline inputs:
`NaN`, `Infinity`, and `-Infinity` are rejected recursively, while
`verify`/`check` retain `certificate_invalid_json` and an outer CLI parse failure
retains `operation_failed`; thresholds must be finite. T151 and T152 were
already strict and remain unchanged. This is finite-JSON enforcement only: no
canonical JSON, HMAC, authentication, route, proof, promotion, or privacy
expansion.

T157 closes the public boundary around the quarantined legacy v1 API without
changing its private operator artifacts. Public `verify_certificate(...)`
summaries contain exactly `ok`, `reason_code`, `reason`, and `reason_codes`;
`check_document(...)` and the `check` CLI add only `eligible`. These summaries
do not contain a raw `error`, local path, argv, feature map, certificate
payload, or renderer stdout/stderr. Successful `measure` and `certify` output
files remain private, pathful v1 operator artifacts and are never public
receipts. The legacy CLI has `measure`, `certify`, and `check` only; there is no
`verify` subcommand, although the Python verification API remains available to
quarantined consumers. `render_probe` publishes only the boolean
`render_certificate_configured` and closed `render_certificate_reason`, never
the configured path. Existing reason tokens are preserved; this boundary
changes no authentication, execution, eligibility semantics, routing, proof,
submission behavior, or release switches. T151 does not upgrade the closed
`certified_runtime_unbound` route, enable certified execution, or promote a
PDF. The result ceiling is always `proof_grade: none`,
`submission_grade: false`, `promotion: not_run`, and
`runtime_binding: not_established`; native layout, visual quality, parity,
dependency closure, and submission readiness remain unestablished.

T158 changes only custody for the legacy v1 `measure`/`certify --out` path. The
dedicated fresh private artifact publisher requires a pre-created canonical
parent that is a real directory and an absent output leaf, and publishes only
a new regular one-link file. Symlink/reparse/hardlink/pre-existing targets and
parent swaps are refused; held-parent relative staging/link/final checks bind exact bytes
and identity, while owned-only rollback preserves foreign replacements. A
refusal is the pathless `operation_failed` result. Generic `write_json`,
`check`, and `doc_backend` receipt writing remain unchanged. Legacy artifacts
remain pathful private v1 files; stdout/privacy, authentication, routing,
proof, submission, and release-switch semantics are unchanged.

T159 tightens the legacy private measurement binding without changing its
public boundary. A manifest document id is validated as one safe non-dot
segment before its candidate directory is created; `argv[0]` must resolve to
the configured renderer binary. Source, reference, and candidate snapshots
are bounded no-follow regular one-link generations captured before and after
render. The manifest reference hash must match exactly, and a fresh candidate
or alternate renderer output is refused. Certificate issuance also refuses a
`candidate_pdf` that aliases either the manifest reference PDF or source
document; `issue_certificate` revalidates the live manifest and every
document/reference/candidate path and hash, then performs a second rebind
before HMAC. The pathful measure/certify payload and stdout remain private v1
operator artifacts. Public `verify_certificate` remains exactly
`ok`/`reason_code`/`reason`/`reason_codes`, and `check_document` adds only
`eligible`; generic `write_json` and `doc_backend` behavior is unchanged.
There is no authentication, execution, eligibility, routing, proof,
submission, or promotion expansion, and both release switches remain false.

T160 hardens only the legacy producer-side measurement generation. Each
document/reference/candidate input is captured into an owned bounded
snapshot file, and feature extraction, renderer input, and PDF metrics consume
those captured files rather than rereading live paths. After metrics, the
final live document/reference/candidate generations are rebound; only non-restored
final drift refuses the private record. A mutation restored before the final
check cannot alter snapshot-derived metrics. During
`issue_certificate`, the operator key is loaded before a final immediate
rebind of the live manifest and every measurement document/reference/candidate
generation; only that final bound state is allowed into the HMAC claim. This
does not add reader-side verifier custody: public `verify_certificate` remains
the exact four-field projection and `check_document` adds only `eligible`.
Schema, routing, proof, submission, promotion, and both release switches are
unchanged. Successful measure/certify artifacts and stdout remain pathful
private v1 operator outputs; final pre-HMAC manifest drift publishes no stale
certificate artifact, while generic failure/projection semantics otherwise
remain unchanged.

T161 adds reader-side verifier custody only for the current dependencies of
legacy v1 verification: the certificate file, manifest, renderer binary, and the
`check_document` input are each captured as bounded no-follow regular one-link
snapshots. Parsing, certificate self-hash/HMAC checks, manifest claims, feature
extraction, and renderer-version checks consume those captured bytes or owned
staged copies; a final rebind immediately before return refuses symlink,
reparse, hardlink, or other identity drift with the closed
`certificate_changed`, `manifest_changed`, `renderer_binary_changed`, or
`document_changed` reasons. Historical measurement
document/reference/candidate paths are not reread and are not public
dependencies. Public `verify_certificate` remains exactly the four-field
projection and `check_document` adds only `eligible`; the private rich route
remains quarantined. Schema, routing, proof, submission, promotion, and both
release switches are unchanged.

The core bundle ships the Python entry point and its ordinary script imports
only. It ships no binary, source document, reference PDF, private manifest,
operator key, certificate, or corpus artifact. Clean extracted `--help` must
also work under a CP949 console without PyMuPDF or a configured renderer.
