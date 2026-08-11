# Renderer-certificate composite receipt v1 (T152)

Checked 2026-08-11. T152 joins two already-captured diagnostic lanes for one
workspace run: the T150 `renderer_runtime_v2.py` receipt and the T151
exact-document certificate envelope. It closes the association between a
runtime receipt and a certificate without executing a renderer or upgrading
either lane into proof.

## Closed schema and commands

The composite schema is
`rigorloom/renderer-certificate-composite/v1`. Its canonical receipt is
written only below the workspace leaf
`output/proof/renderer-certificate-composite/<run-id>/receipt.json`; the output
cannot alias the source, the T150 runtime receipt, or another run.

The CLI has two diagnostic operations:

```text
python pipeline/scripts/renderer_certificate_composite_v1.py check WORKSPACE --run-id RUN_ID --binary BIN --certificate CERT --out RECEIPT
python pipeline/scripts/renderer_certificate_composite_v1.py verify WORKSPACE --run-id RUN_ID --binary BIN --certificate CERT
```

`check` re-runs the T150 runtime verifier, T151 certificate HMAC verifier, and
T151 exact-document check against a captured `WORKSPACE/output/out.hwpx`
snapshot, then publishes one composite receipt only after the captured
generations match. `verify` performs the same captured-snapshot joins against
the canonical composite receipt and re-runs both underlying verifiers; it
refuses replaced, unrelated, or ambiguous captured generations. It does not
claim that mutable live paths remain unchanged after their bounded capture.
A matching result is still diagnostic and cannot be used as a release or
submission decision.

## Exact joins and digest meanings

The composite accepts only this closed join:

- T150 runtime `input.sha256` and `input.bytes` equal the T151 exact-document
  source hash and byte count for the current `output/out.hwpx`;
- the T150 certificate file SHA-256 and byte count equal the current
  certificate file, while the parsed T151 `certificate_sha256` remains the
  signed certificate-body digest. These are deliberately different digests;
  file identity is not substituted for certificate-body identity;
- the T150 runtime receipt, captured PDF artifact, source, binary, and
  certificate descriptors match the generations joined by this check;
- the published receipt records only bounded hashes, byte counts, an opaque
  run/document id, PDF page count, and the joined runtime/certificate status.

The receipt declares `binding_scope: captured_snapshot_only` and
`evidence_ceiling: runtime_input_exact_document_certificate_binding_only`.
It retains `dependency_closure: unknown`, `comparison: {"state":"unknown"}`,
`render: {"state":"not_run"}`, `proof_grade: none`,
`submission_grade: false`, and `promotion: not_run`.

The composite itself is not HMAC-authenticated; its body digest is an
integrity check only. T151 validation still requires the operator key used by
the signed certificate, but that key and all private profile material remain
out of the receipt.

## Privacy and routing boundary

No document, certificate, runtime, workspace, binary, or PDF path is written
to the composite. It contains no source text, PDF bytes, command/argv,
stdout/stderr, private manifest, operator key, corpus artifact, or executable
binary. Only hashes, sizes, opaque identifiers, and closed state values are
published.

The composite does not execute a renderer, issue a certificate, write
`output/proof/backend/receipt.json`, change `output/out.hwpx`, select a
backend, auto-routes, promotes a PDF, or feeds Stage 5, Stage 6, or
`new_report`. `ADVISORY_PROOF_RELEASE_ENABLED=False` and
`CERTIFIED_PROOF_RELEASE_ENABLED=False` remain unchanged. The composite is
not a certified runtime binding and does not alter the legacy v1 quarantine.
