# Archive policy

`archive/` at repository level contains superseded, sanitized public contracts.
It is never loaded by the current kernel.

Each report workspace also has an `archive/` directory. Automatic organization
moves only:

- `scratch/` and `tmp/`;
- root `*.tmp`, `*.bak`, and `*.old` files;
- known loop stdout/stderr logs from `output/`.
- the completed or blocked stage's `work/stage-<id>/` directory.

Research, content bundles, simulation results, approvals, canonical outputs,
proofs, and source records remain in place. Nothing is deleted.

Each stage transition also records a receipt under `.pipeline/receipts/` with
the canonical output inventory and hashes observed at that moment.
