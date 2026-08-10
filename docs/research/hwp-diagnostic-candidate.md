# T86: quarantined `rhwp` HWP diagnostic candidate

T86 is a diagnostic-candidate path, not a canonical conversion backend. It is
intentionally separate from `rigorloom/hwp-ingress/v1`, Stage 0, the report
consumer, and native-render evidence. The runner first applies the T85 strict
HWP5 inspector, then executes one explicitly selected `rhwp` binary and places
the result only below the caller's diagnostic root:

`work/stage-0/scratch/hwp-diagnostic/<opaque-run-id>/candidate.hwpx`

The run id is schema-owned lowercase hexadecimal (16 or 32 characters). A
human label, path component, arbitrary output path, `--out`, or `--manifest`
is not accepted. A successful receipt uses the closed schema
`rigorloom/hwp-diagnostic-candidate/v1` and contains only the source descriptor,
execution result, quarantine-relative output binding, and bounded control
counts. It contains no argv, stdout, stderr, text, names, IDs, metadata, or
absolute paths.

## Upstream references (v0.8.2)

The pinned upstream reference set is the public `edwardkim/rhwp` v0.8.2 tag:

- [v0.8.2 source tree](https://github.com/edwardkim/rhwp/tree/v0.8.2)
- [v0.8.2 release and assets](https://github.com/edwardkim/rhwp/releases/tag/v0.8.2)
- [v0.8.2 English README](https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md)
- [v0.8.2 CLI usage in the README](https://github.com/edwardkim/rhwp/blob/v0.8.2/README_EN.md#cli-usage)

Those links document the upstream project and its CLI. They do not establish
format parity, native-authored semantics, or render proof for a particular
document. The upstream project is MIT-licensed; retain its `LICENSE` and
`THIRD_PARTY_LICENSES.md` attribution boundary when obtaining a binary, and do
not copy the binary or release archive into this repository. T86 therefore
requires an operator-supplied binary path and a
mandatory SHA-256 pin, stages a byte-for-byte executable snapshot, invokes the
exact list form

```text
rhwp export-hwpx INPUT OUTPUT --verify --verify-pages
```

with no shell, `PATH`, or environment fallback, and rechecks both the source
and configured binary before publication. The staged child runs with an
isolated temporary working directory so sidecars cannot land in the checkout.

## Evidence boundary

`comparison` is always `state: unknown`, `method: none`, and
`reason: independent_oracle_not_run`; this candidate route never promotes an
`rhwp` result to parity. `render` is always `not_run`, `proof_grade` is always
`none`, and `submission_grade` is always `false`. The quarantined HWPX is not a
canonical `output/form_copy.hwpx`, not a Stage-0/backend receipt, and must not
be supplied to `new_report --ingress-receipt`.

The runtime evidence recorded during the operator investigation is explicitly
operator-local and is not shipped. The official Windows archive checksum
matched `SHA256SUMS`: `d99b952ce2322d59530b86453a7314ebe18e86bdea165d2b75ef0b2af39ec6de`.
The staged binary was
`e38215daddf63b284cbe05322541b44f65efd727ce7f50b9b4ffd94930e7ab72`; the
public source form SHA-256 was
`f386eca6c327a37a2fd965a56efacc50d51e3cec178313364e184656443570c3`; and
the 26,082-byte candidate was
`23d695387304bf7a29afab382e00617f09240a4aa47fcb7f0558e29ff1d5c2a4`.
The public law.go.kr export exited 0, passed the T85 bounded HWPX validator,
and retained only tables 3, pictures 1, equations 0. The wrapper probe took
8.5 seconds including download, extraction, and validation. Comparison and
render were not run, and the candidate artifact was deleted. No corpus bytes,
source documents, private paths, or binary artifacts belong in this repository.

## Golden command

Use a disposable scratch root and a schema-owned run id. Replace the angle
bracket placeholders locally; do not record their resolved paths in receipts:

```text
python pipeline/scripts/hwp_diagnostic_candidate.py run INPUT.hwp \
  --diagnostic-root work/stage-0/scratch/hwp-diagnostic \
  --run-id 0123456789abcdef0123456789abcdef \
  --rhwp <explicit-rhwp-binary> \
  --rhwp-sha256 <64-lowercase-hex>
```

`verify` rebinds the exact receipt and current candidate bytes/counts. Any
source or binary drift, timeout, output overflow, nonzero child exit, invalid
HWPX, existing run, race, or receipt mismatch refuses with exit 3 and leaves no
owned candidate or receipt. If an ownership token cannot be established, an
empty quarantined reservation may remain; a raced foreign path is likewise
preserved rather than deleted. Neither can pass `verify` or become canonical.
Neither `pyhwp` nor LibreOffice is a fallback for this contract.
