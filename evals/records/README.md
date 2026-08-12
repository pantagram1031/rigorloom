# Committed pack records

Published results from running the eval pack. A record here is evidence a third
party can read without re-running anything, and the support matrix
(`docs/support-matrix.md`) may point at one with a `record:` pointer.

Two record kinds exist, and they are not interchangeable:

| kind | schema | what it shows |
|---|---|---|
| machine-check record | `rigorloom-pack-machine-check-record/v1` | every task materialized into a clean-room root installed from bundles, with its machine checks executed. The deterministic half. |
| agent-completion run record | `run_record.schema.json` | an agent actually solving a task: tier, launcher, transcript, judgment. |

**A machine-check record is not a run record.** It says the pack, the shipped
engine and the corpus resolve out of a clean bundle install and that the
blank-form checks agree. It says nothing about whether an agent can complete the
task, because no agent ran.

## Reading a failed check

In a record whose tasks all report `deliverable_present: false`, a failed check
means **the check had nothing to read**, not that the product misbehaved. Only
the passing checks carry information in that case.

Per-check causes are deliberately not classified. An earlier draft of the first
record classified them from failure text and got 12 of 91 wrong: several checks
report no detail at all, and `missing: [...]` or `expected JSON not produced`
say nothing about a missing file. A second draft inferred it from "did the work
directory gain files" and inverted the counts, because the checks themselves
write baseline profiles and verdicts from the blank form. The record now states
one derived fact — whether the deliverable exists — and leaves interpretation to
that.

## Privacy

A record must contain **no absolute paths**. The builder asserts this before
writing: the repository privacy gate rejects Windows user-profile paths, and the
operator's directory layout is not evidence about the product. Sandbox and
checkout paths appear as `<SANDBOX>`, `<CHECKOUT>` and `<PATH>`.

## Naming

`<YYYY-MM-DD>-<what-ran>.json`, with the `main` commit recorded inside so a
reader can tell which tree produced it.
