# Renderer runtime v2 (T150)

Checked 2026-08-11. This note records the narrow platform/runtime boundary
implemented by `pipeline/scripts/renderer_runtime_v2.py`. It is a quarantine
receipt lane, not a new Stage 5 backend and not a release of the certified
proof path.

## Closed route

The only accepted adapter is `rhwp_pdf`. It stages an operator-supplied,
SHA-256-pinned executable and invokes the fixed two-command template:

```text
{binary} --version
{binary} export-pdf {input} -o {output}
```

The source is the existing workspace artifact `output/out.hwpx`. The caller
must pre-create the exact workspace leaf
`output/proof/renderer-runtime-v2`; an opaque 16- or 32-lowercase-hex run id
owns the child directory. The lane publishes only `artifact.pdf` and
`receipt.json` below that run directory. Caller-selected output paths,
arbitrary argv templates, automatic binary discovery, and fallback renderers
are outside the contract.

The receipt schema is `rigorloom/renderer-runtime-v2/v1`. It binds the
captured source, binary, opaque certificate snapshot, produced PDF, fixed
argv-template digest, version-process result, render-process result, timeout
and overflow state, minimal environment digest, private staging cwd policy,
and a platform-specific child-process policy. `execution.process_policy` is
`windows_job_kill_on_close_v1` on Windows and `posix_process_group_v1` on
POSIX. `execution.descendant_containment` and
`execution.evidence_authentication` are both `not_established`. Child
stdout/stderr are reduced to byte counts and SHA-256 values; streams, paths,
argv, source text, and certificate contents are not published.
`inspect` emits the producer host's local policy token. `verify` accepts either
closed recorded token, `windows_job_kill_on_close_v1` or
`posix_process_group_v1`, so a receipt can be checked on another host; the
legacy `contained_child_v1` token is rejected.

## Evidence ceiling

The receipt is diagnostic evidence only. `dependency_closure` is
`unknown`: hashing one executable does not bind its DLL/shared-library set,
loader, distribution, or other runtime dependencies. The certificate is
captured and hash-bound but its semantics are deliberately not validated
(`certificate.validation: not_run`). `comparison` is `unknown`, `render` is
`not_run`, `proof_grade` is `none`, `submission_grade` is `false`, and
`promotion` is `not_run`. A successful child and a readable PDF therefore do
not establish native layout, visual quality, Hancom parity, or submission
readiness. Receipt verification rebinds the current source, binary,
certificate, artifact, root, and receipt bytes, but it does not authenticate
child-process evidence; that evidence remains
`execution.evidence_authentication: not_established`.

Equation-bearing HWPX is refused before a child starts. The structural
equation preflight is only an exclusion guard; it does not interpret HwpEqn
or prove equation semantics. Malformed, unreadable, replaced, stale,
hard-linked, symlinked, or otherwise ambiguous source/output/binary/
certificate paths refuse without a receipt. A stale run directory, timeout,
non-zero child, output overflow, missing/invalid PDF, or publication race is
also a refusal.

## Containment and publication

The run root and workspace are checked for symlink/reparse ancestry and held
through the operation. Input, binary, certificate, staged output, and final
receipt are captured through bounded no-follow regular-file reads and rebound
before publication/verification. On Windows the child uses a suspended launch
assigned to a kill-on-close Job (`windows_job_kill_on_close_v1`); on POSIX it
uses a new process group (`posix_process_group_v1`). Ordinary descendants that
remain in the Job/process group are cleaned up. A POSIX descendant that calls
`setsid()` can escape, and brokered processes outside the Job/process group are
outside the claim. This lane provides no memory, process-count, CPU,
filesystem, or network isolation. Publication is receipt-first and
output-last; rollback can remove only the operation's owned inode. Verification
rechecks current source, binary, certificate, artifact, root, and receipt
generations before returning success, without authenticating child-process
evidence.

## Routing and distribution boundary

This module is not called by `doc_backend.py`, `render_probe.py`,
`submission_preflight.py`, Stage 0, Stage 5, Stage 6, or `new_report.py`.
It never writes the canonical `output/proof/backend/receipt.json`, never
replaces `output/out.hwpx`, and never supplies ingress or submission proof.
`CERTIFIED_PROOF_RELEASE_ENABLED` remains `False`; the existing
`certified_renderer` route remains `certified_runtime_unbound` with grade
`none`.

The core bundle ships the Python script and its existing stdlib dependencies
only. No rhwp executable, certificate, HWP/HWPX/PDF artifact, private
document, or corpus file is packaged. Operators provide the binary and
certificate out of tree and install no runtime automatically. `--help` must
work from a clean extracted bundle under CP949 without PyMuPDF; PDF parsing is
an optional runtime check and fails closed when unavailable.

## Reproducible operator shape

```sh
python pipeline/scripts/renderer_runtime_v2.py inspect WORKSPACE \
  --run-id 0123456789abcdef \
  --renderer-id rhwp_pdf \
  --binary RHWP_BINARY --binary-sha256 SHA256 \
  --certificate CERTIFICATE --certificate-sha256 SHA256

python pipeline/scripts/renderer_runtime_v2.py verify WORKSPACE \
  --run-id 0123456789abcdef \
  --binary RHWP_BINARY --certificate CERTIFICATE
```

The command is for an explicitly requested diagnostic run. It is not a
recommendation to install rhwp, a claim of cross-platform parity, or a path to
certified proof.
