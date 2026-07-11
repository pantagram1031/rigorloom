# Rigorloom Pipeline Contract v0.6

This contract defines the enforceable behavior of the portable report pipeline.
The kernel is provider-independent and uses only Python's standard library.

## A. State authority

- The fenced header in `PIPELINE.md` is authoritative.
- The compatibility marker remains `# pipeline-state: v0.4`; the actual schema
  version is `pipeline_version: "0.6"`.
- State changes occur only through `pipeline_ctl.py`.
- `events.jsonl` is append-only operational history.

## B. Stage order

The configured order is:

```text
0, 1, 2, 2.5, 3, 4, 5, 5.5, 5.7, 6
```

Stage -1 is setup before kernel initialization. `stages.yaml` and the embedded
fallback must agree.

## C. Orchestration

Any interactive human or AI agent may orchestrate. Headless tools may be used as
bounded workers. The orchestrator must preserve state, gates, artifacts, and
handoffs regardless of provider.

## D. Request contract

`request.yaml` declares topic, subject/domain, form, mode, scope, required and
excluded content, page target, figure target, style constraints, and output
requirements. Missing required values block supervised setup; unattended modes
may choose conservative defaults and record assumptions.

## E. Form intake

Inspect the original without editing it. Freeze:

- original hash;
- anchors and placeholders;
- guide-text constraints and deletion targets;
- baseline paragraph/character formats;
- page metrics;
- table map;
- break audit.

Work only on a copy after inspection.

## F. Research

Every externally checkable factual claim must map to a structured source id.
Downloaded assets record license and origin. Analysis or hypotheses must be
clearly identified as such.

## G. Design

`01_design.md` defines scope, method, variables, comparison groups, deterministic
checks, figures, failure modes, and curriculum/domain limits. The human `design`
gate concerns intent and scope.

## H. Simulation and deterministic validation

Scripts produce machine-readable verdicts. A verdict may not be edited to pass.
Change declared inputs or code and rerun. Numeric claims require independent
verification proportional to risk.

## I. Writing

Writing consumes the approved evidence, design, and layout budget. Content keeps
source ids or paragraph provenance. The `draft` gate concerns meaning, evidence,
scope, and voice—not post-assembly formatting.

## J. Human gates

Human gates are `design`, `draft`, and `understand`.

- `supervised`: require a matching human record in `APPROVALS.md`.
- `autonomous`/`night`: record `auto_approved`, never `approved`.
- Script exit codes cannot approve human gates.

## K. Prose fidelity

Style editing may not alter numbers, citations, equations, uncertainty,
qualifications, or logical direction. General style guidance is subordinate to
the operator request and form.

Stage 4 freezes `bundle/content.raw.md` before humanization. Detector and scorer
outputs are advisory; formal-register scores cannot select paragraphs or force a
rewrite. PASS preserves the draft. On REWORK an independent local rewriter
inspects every prose paragraph and returns only actual paragraph-level changes
under `humanization_contract.md` v2.

`prose_fidelity.py` is the authoritative local check. The controller restores
unsafe paragraphs individually, emits retry ids, and runs a whole-document
audit; a global invariant failure restores the raw content. Rewriter, semantic
fidelity reviewer, and naturalness reviewer are independent roles. External
service audits can add evidence but cannot override a deterministic failure.

## L. Final evaluation

The final panel covers visual composition, logic, evidence, numerical claims,
and user value. Reviewers read source and verdict artifacts directly. The
normalized scorecard is machine-readable.

## M. Knowledge hygiene

Reusable troubleshooting and source knowledge may be distilled only after a
run. Generated prose must not become evidence for a private person's writing
style. Private forms, reports, identity data, and model credentials never enter
the public repository.

## N. Cast-off before writing

Stage 2.5 creates `bundle/layout_plan.json` from form metrics and target pages.
It allocates lines, figures, equations, tables, and breaks. The script gate
rejects plans exceeding the available budget.

## O. Typeset defaults

Document adapters apply stable widow/orphan, heading continuity, caption,
equation, and table behavior through their declared capabilities. Per-report
format knobs may not accumulate after assembly as ad hoc repair.

## P. Proof loop

Proof is contact-sheet-first. The four required binary composition checks are:

1. `mid_bottom_void`;
2. `density_uniformity`;
3. `table_proportion`;
4. `heading_plus_void`.

Only flagged pages require high-resolution inspection. Repair uses bounded
content deltas or declared table resizing. Proof exhaustion blocks and escalates.

## Q. Precedence

```text
operator explicit > form interpretation > pipeline defaults
```

Record material conflicts and the selected resolution.

## R. Agent registry and adapters

`agents.yaml` maps capability roles to ordered backend candidates. Provider
commands are local configuration, not contract requirements. Adapter failures
are recorded; an equivalent candidate may replace the failed backend without
changing stage semantics.

## S. Vision economy

Inspect a low-resolution contact sheet first. Request high-resolution renderings
only for visible anomalies. Never claim to have inspected an image that the
selected backend could not read.

## T. Document adapter

A document backend must provide equivalent operations for:

```text
inspect → assemble → tidy → measure → proof-render
```

HWP/HWPX uses the separate `hwp-master` repository. Other formats may implement
the same behavior. Capability gaps must be declared rather than silently
degrading the deliverable.

## U. Organization and handoff

After initialization and state transitions, regenerate:

- `.pipeline/handoff.json` for machines;
- `NEXT_TASK.md` for humans and agents.
- `.pipeline/artifacts.json` and `WORKSPACE_INDEX.md` for artifact readiness.

Temporary work belongs to `work/stage-<id>/`. Canonical outputs are defined by
`workspace_layout.json`; agents must not invent alternate sibling paths.

On completion or blocking, safe transient files may move to
`archive/stages/<stage>/<timestamp>/`. Canonical artifacts are never moved or
deleted. Completed-stage work areas are archived intact, and a receipt is saved
under `.pipeline/receipts/`. Derived organization files never override
`PIPELINE.md`.
