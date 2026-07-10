# Design decisions

## DD-001 — Provider-neutral kernel

The state machine describes capabilities and roles, not model brands. Provider
commands live in adapters and may be replaced without changing stage semantics.

## DD-002 — Machine-readable state is authoritative

Stage and gate state is changed only through `pipeline_ctl.py`. Narrative notes
may explain a decision but cannot override a script verdict or approval record.

## DD-003 — Typeset-first document production

Page budgets are established before prose. Assembly starts from an untouched form
copy on every iteration. Layout corrections prefer bounded text changes over
global formatting changes.

## DD-004 — Human gates remain distinguishable

Supervised runs stop for human design, draft, and understanding approval.
Autonomous runs may record `auto_approved` only where policy permits; they do not
forge a human `approved` result.

## DD-005 — Canonical artifacts stay stable

Automatic organization archives only known scratch, temporary, and completed
stage work. Canonical research, bundles, approvals, outputs, and proofs are never
moved during housekeeping.

## DD-006 — Script verdicts are append-only evidence

When a check fails because scope or assumptions were wrong, update the declared
inputs and rerun it. Never edit the emitted verdict. Receipts retain hashes so a
later agent can detect drift.

## DD-007 — Document engines are adapters

The pipeline can run without HWP. Full `.hwp` editing is delegated to
`hwp-master` on a Windows host with locally installed Hancom Office. Other
document engines can implement the same inspect, assemble, measure, proof, and
finalize responsibilities.
