# Rigorloom v0.6 — Master Workflow

This is the single starting document for human operators and AI agents. It is
provider-neutral: Claude, Codex, Gemini, local models, CLI workers, API workers,
or a single interactive agent can operate it.

The executable state machine and `pipeline/references/CONTRACT_v0.6.md` are
authoritative when prose differs from code.

## 1. Purpose and invariants

The workflow turns a topic, constraints, sources, and an optional document form
into a researched, verified, typeset report. Its defining choice is
**typeset-first**: page and section budgets are fixed before long-form writing;
post-assembly repair is limited to small content deltas.

Non-negotiable invariants:

1. `PIPELINE.md` is the source of truth for stage and gate state.
2. State changes go through `pipeline/scripts/pipeline_ctl.py`, never manual
   YAML edits.
3. Script verdicts are immutable. Change their inputs and rerun the script.
4. A supervised human gate can only be approved by a human.
5. Work on a copy of every original form.
6. Every factual claim maps to a source or is identified as analysis.
7. Canonical artifacts stay in their declared directories.
8. Every state transition refreshes `NEXT_TASK.md` and
   `.pipeline/handoff.json` for the next agent.
9. Temporary work belongs in the active stage's `work/stage-<id>/scratch/`
   directory; canonical outputs go only to declared artifact paths.

Precedence for conflicting instructions:

```text
operator request > form instructions > pipeline defaults
```

Private personalization refines this without changing the pipeline contract:
`request explicit > form user override > form extracted conditions > subject
profile > global profile > public defaults`. Initialize it with
`python pipeline/scripts/personalization_ctl.py --profile-root <PRIVATE_ROOT> init`.
The profile root is ignored local state; generated report prose is never style
evidence. See `pipeline/references/personalization_contract.md`.

## 2. Repository and workspace layout

Reusable operating history is documented separately in
`docs/lessons-learned.md`, `docs/design-decisions.md`, and
`docs/troubleshooting.md`. Consult these before inventing a new gate exemption,
layout repair knob, backup convention, or recovery procedure.

Run commands from the repository root.

```text
pipeline/                  kernel, contract, configuration, playbooks
studio/                    optional read-only local viewer
scripts/new_report.py      atomic workspace scaffolder
adapters/                  optional document/provider integrations
docs/                      current public documentation
archive/                   superseded sanitized specifications
workspaces/report-<slug>/  local run data, ignored by Git
```

Canonical workspace structure:

```text
PIPELINE.md                authoritative stage and gate state
request.yaml               topic, scope, constraints, form, output request
build.yaml                 one declaration source for document construction
APPROVALS.md               human-only supervised approvals
NEXT_TASK.md               regenerated human-readable handoff
WORKSPACE_INDEX.md         regenerated artifact and readiness table
.pipeline/handoff.json     regenerated machine-readable handoff
.pipeline/artifacts.json   hashes, sizes, presence, and missing artifacts
.pipeline/receipts/        completion snapshots by stage
events.jsonl               append-only event stream
TROUBLES.md                run-specific failures and decisions
work/stage-<id>/scratch/   temporary files owned by the active stage
research/                  evidence lanes, source records, source assets
01_design.md               approved research and validation design
bundle/                    layout plan, content, figures, provenance
sim/                       reproducible code and immutable verdicts
output/                    canonical document, PDF, proofs, scorecards
refs/                      operator-supplied reference artifacts
archive/                   preserved scratch and superseded run outputs
```

## 3. The only orchestration loop

```sh
python pipeline/scripts/pipeline_ctl.py resume <ABSOLUTE_WORKSPACE>
```

Then:

1. Read the returned stage playbook in
   `pipeline/references/playbooks/stage-<n>.md`.
2. Satisfy its entry conditions.
3. Use the work area named in `NEXT_TASK.md` for drafts and temporary files.
4. Publish only outputs declared in
   `pipeline/references/workspace_layout.json` to canonical paths.
5. Resolve its gate, if any.
6. Advance with `pipeline_ctl.py`.
7. Read the regenerated `NEXT_TASK.md` before doing more work.

If a worker cannot complete a role, record the failure and select another
backend with equivalent capability. The stage contract does not change.

## 4. Stage map and gates

Authoritative order:

```text
-1 setup → 0 form intake → 1 research → 2 design → 2.5 layout plan
→ 3 simulation → 4 write → 5 assemble/proof → 5.5 understanding
→ 5.7 evaluation panel → 6 return/knowledge
```

| Stage | Purpose | Main output | Gate |
|---|---|---|---|
| -1 | Create job ticket and initialize | request/build/PIPELINE | none |
| 0 | Inspect the form and freeze metrics | form_profile, baseline | none |
| 1 | Build an evidence pack | evidence and sources | none |
| 2 | Design the investigation | 01_design.md | human `design` |
| 2.5 | Cast off pages before writing | layout_plan.json | script `layout` |
| 3 | Execute reproducible validation | gate_result.json | script `sane` |
| 4 | Write to the approved budget | content.md, provenance | human `draft` |
| 5 | Assemble, measure, and prove | out document/PDF, verdict | internal verdict |
| 5.5 | Check operator understanding | QUESTIONS.md | human `understand` |
| 5.7 | Independent final evaluation | scorecard.json | internal verdict |
| 6 | Return and distill knowledge | archive/knowledge record | none |

Human gates:

- In `supervised` mode, stop and request human approval.
- In `autonomous` or `night` mode, record `auto_approved`; never claim human
  approval.
- Approval records use `APPROVALS.md` and the gate command.

Script gates:

```sh
python pipeline/scripts/pipeline_ctl.py gate <WS> layout --script-exit 0
python pipeline/scripts/pipeline_ctl.py gate <WS> sane --script-exit 0
```

A non-zero checker exit rejects the gate. Never edit that result to pass.

## 5. Stage responsibilities

### Stage -1 — setup

Use the atomic scaffolder when possible:

```sh
python scripts/new_report.py --slug <slug> --subject <subject> \
  --topic "<topic>" --form <absolute-form-path> --mode supervised
```

The Studio is optional:

```sh
python studio/main.py
```

### Stage 0 — form intake

The document adapter inspects the original without modifying it. For HWP:

The full HWP path must run on Windows with the desktop Hancom Office HWP
application installed locally. The pipeline does not bundle Hancom Office.
Before Stage 0, verify the separate adapter checkout with:

```powershell
python <HWP_MASTER_ROOT>/scripts/doctor.py --require-com --require-proof `
  --report-pipeline <REPORT_PIPELINE_ROOT>
```

If this check fails, do not enter the COM assembly path. Use only provider-neutral
pipeline stages or supported non-COM HWPX/XML operations until a Windows HWP host
is available.

```sh
python <HWP_MASTER_ROOT>/scripts/form_inspect.py <form> \
  --out <WS>/form_profile.json --base-pt 10 --line-spacing 180 \
  --baseline <WS>/form_baseline.json
```

Freeze anchors, page metrics, tables, placeholders, guide text, and break state.

### Stage 1 — research

Use up to three independent lanes: concepts, data/assets, and curriculum or
domain constraints. Each produces evidence and structured source records.
Cross-examine unsupported, contradictory, or weak claims before advancing.

### Stage 2 — design

Define the question, scope, method, variables, comparison groups, expected
failure modes, deterministic checks, and output figures. A human design gate
confirms that this is the intended investigation.

### Stage 2.5 — layout plan

Allocate section line budgets, equations, tables, figures, and page breaks
before prose exists. The layout checker must confirm the plan fits the target
pages. This is a hard script gate.

### Stage 3 — simulation and validation

Place reproducible code and data contracts in `sim/`. The machine result is
`sim/gate_result.json`; explanatory prose may describe it but cannot replace it.
Numeric claims should receive two independent verification passes.

### Stage 4 — write to budget

Write `bundle/content.md` against the approved layout plan. Preserve source ids,
distinguish facts from interpretation, and record paragraph provenance. Apply
the general prose guidance in `docs/style-rules.md` only when it does not
conflict with request or form instructions. Then follow
`pipeline/references/humanization_contract.md`: freeze `content.raw.md`, create
an AI-tell review, apply only paragraph-level changes, and require the local
fidelity report to pass. Unsafe edits roll back automatically. Pantadex is an
optional adapter; any capable agent may use the same prompt and schema. The
human draft gate concerns content, not typesetting.

### Stage 5 — assemble and proof

For HWP, use the single assembly loop from the separate adapter:

```sh
python <HWP_MASTER_ROOT>/scripts/fill_report.py --loop \
  --form <WS>/output/form_copy.hwpx \
  --content <WS>/bundle/content.md --out-dir <WS>/output \
  --build-yaml <WS>/build.yaml --baseline <WS>/form_baseline.json \
  --form-profile <WS>/form_profile.json --proof --max-proof-iters 3
```

First converge deterministic page/figure/spacing metrics. Then inspect a
contact sheet using four binary composition checks:

Contact sheets are insufficient for small equation details. Any page containing
new inline equations must also receive a high-resolution equation check for
script scope, missing glyphs, and token leakage before acceptance.

1. no unexplained middle/bottom void;
2. reasonably uniform body-page density;
3. usable table proportions;
4. no heading isolated above a large void.

Repair only through bounded content rewrites or declared table resizing.
Exhausting the proof budget blocks the stage and escalates to a human.

### Ad-hoc HWP edits still require proof

The assembly loop is the normal path. If a one-off HWP/HWPX edit is necessary
outside a report workspace, preserve the source and still perform these minimum
checks before delivery:

1. Save to a new output file, then apply heading/caption continuity and
   widow-orphan defaults with the adapter's supported typeset operation.
2. Run layout QA on the exported PDF. Treat an apparent gap as a defect only
   after checking whether it is a cover margin, display-equation spacing, or
   intentional figure spacing.
3. Render and inspect every page for isolated headings, separated captions,
   blank bands, and equation damage. Pages with new inline equations need a
   high-resolution check, not just a contact sheet.

Do not use ad-hoc formatting knobs as a substitute for a bounded content or
layout correction. Rebuild from the untouched source if the output is damaged.

### Stage 5.5 — understanding

Generate five open questions without model answers. A supervised human answers
them independently; the `understand` gate records the result.

### Stage 5.7 — evaluation panel

Use independent visual, logical, source, and value reviews. Reviewers must read
machine verdicts rather than infer them from final prose. Save the normalized
scorecard under `output/scorecard.json`.

### Stage 6 — return and knowledge distillation

Return the canonical output and record remaining manual steps. Promote reusable
troubleshooting patterns and sources into non-personal knowledge records. Never
use generated report prose as evidence for a person's private writing style.

## 6. Agent routing

Roles are capability labels defined in `pipeline/references/agents.yaml`.

| Role | Required capability |
|---|---|
| orchestrator | state tracking, file and command access |
| writer/designer | high reasoning and long-form writing |
| researcher | source discovery or supplied-source analysis |
| simulation worker | code execution and deterministic checks |
| mechanical worker | reliable command and filesystem operations |
| vision judge | image/PDF inspection |
| logic/numeric reviewer | independent critical verification |
| human | approval and escalation authority |

Parallel workers are optional. A single agent may perform roles sequentially,
but must record reduced independence when reviewing its own work. No provider is
required, and no provider may bypass a gate.

## 7. Automatic organization and handoff

`pipeline_ctl.py` refreshes the handoff after initialization, gates,
invalidation, trouble reports, and stage advances. On completed or blocked
stages it also archives safe transient files.

The declarative layout is `pipeline/references/workspace_layout.json`. For each
stage it lists required inputs and expected outputs. The organizer uses that
single map to create directories, inventory artifacts, report missing files,
and prepare the next stage's work area.

The organizer never moves canonical research, bundles, simulation verdicts,
approvals, proofs, or final outputs. It archives only documented scratch paths
and run-log patterns. Run it manually when needed:

```sh
python pipeline/scripts/workspace_organizer.py <WS> --completed-stage <stage>
```

The next agent should trust `PIPELINE.md`, then use `NEXT_TASK.md` as a concise
entry point. `WORKSPACE_INDEX.md` shows the complete run at a glance, while
`.pipeline/artifacts.json` records hashes and missing artifacts.

When a stage becomes done or blocked, its `work/stage-<id>/` directory is moved
intact to `archive/stages/stage-<id>/<timestamp>/work/`. A receipt under
`.pipeline/receipts/` records the declared outputs, hashes, missing outputs, and
archived paths at that transition. Canonical artifacts never move.

## 8. Troubleshooting and completion

On failure:

1. preserve the failing artifact and exact command;
2. append a structured trouble record;
3. correct inputs or implementation, not verdict output;
4. rerun the relevant check;
5. invalidate downstream stages if their inputs changed.

Completion requires:

- all stages done in authoritative order;
- all human/script/internal gates resolved honestly;
- canonical output and proof artifacts present;
- source and provenance records intact;
- `NEXT_TASK.md` reporting workflow completion;
- no private workspaces, forms, credentials, or personal profiles committed to
  the public repository.

Historical internal notes and superseded contracts are under `archive/` and are
not part of the active workflow.
