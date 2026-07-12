---
name: report-pipeline
description: "Orchestrator skill for producing a fully-filled student research report from a topic and a document form. It drives the deterministic Rigorloom state machine: research (web/RAG evidence pack) -> design -> data/simulation (deterministic verification gate) -> write-to-budget -> assemble + proof loop (no blank space, figures, within length bounds) -> understanding gate -> knowledge return. Two run modes: autonomous (topic in -> finished report out) and supervised (human gates halt the run). Every gate state is recorded machine-readably in PIPELINE.md so a dropped session resumes deterministically. Deterministic gates emit an immutable verdict from code and are never post-edited.\n  - MANDATORY TRIGGERS: report pipeline, autonomous report, write a research report from scratch, just give me a topic and get a report, fill the report form"
triggers:
  - report pipeline
  - autonomous report
  - write a research report from scratch
  - fill the report form
---

# Report Pipeline — thin router (v0.6)

This skill does not do the work itself. It reads the current stage, opens that
stage's playbook, follows the playbook's EXACT commands, and advances. The
executable state machine and `pipeline/references/CONTRACT_v0.6.md` are
authoritative when this prose differs from code.

## Placeholders and paths

- `<CHECKOUT>` — the Rigorloom repository root (the pipeline kernel lives here).
- `<WS>` — a workspace absolute path, e.g. `<CHECKOUT>/workspaces/report-<slug>`.
- `<SKILLS_ROOT>` — where this skill is installed for the orchestrator.
- `<PROFILE_ROOT>` — the operator's private, Git-ignored personalization root.

Run every `pipeline_ctl.py` command from `<CHECKOUT>` root. Always pass `<WS>`
as an absolute path — the orchestrator's current directory is not assumed. Never
use a machine-specific user home path in committed artifacts; use these
placeholders.

## The loop (every turn, only this)

```sh
# 1. RESUME — the YAML header of PIPELINE.md is the single source of truth.
python pipeline/scripts/pipeline_ctl.py resume <WS>
# -> returns the stage to resume.

# 2. PLAYBOOK — open pipeline/references/playbooks/stage-<n>.md for that stage.
# 3. FOLLOW  — execute its EXACT commands; bind each role to a backend as declared.
# 4. ADVANCE — run the playbook's EXIT + gate commands, then go to 1.
```

A brand-new run starts at stage -1 (setup / scaffold / init). Because `resume`
is deterministic, a dropped or `/clear`ed session returns to the same point.

## Gate rules (never violate)

- **Script / deterministic gates are HARD.** The verdict emitted by code is the
  only truth and is never post-edited. To change a verdict, change the inputs
  and rerun the checker. Resolve these gates only through `pipeline_ctl`:

  ```sh
  python pipeline/scripts/pipeline_ctl.py gate <WS> layout --script-exit 0   # stage 2.5
  python pipeline/scripts/pipeline_ctl.py gate <WS> sane   --script-exit 0   # stage 3
  ```

  A non-zero checker exit rejects the gate. Stage 5 (assemble/proof converge +
  rubric) and stage 5.7 (scorecard) use internal deterministic verdicts that are
  equally immutable.
- **Human gates** (`design`, `draft`, `understand`) are never self-approved. In
  `supervised` mode, stop and request human approval. In `autonomous`/`night`
  mode, record `auto_approved` — never forge `approved`. Approvals are written to
  `APPROVALS.md` via the gate command.
- **State changes only through the CLI.** Hand-editing PIPELINE.md YAML is a
  contract violation. Every transition goes through `pipeline_ctl.py`, which also
  regenerates `NEXT_TASK.md` and `.pipeline/handoff.json` for the next agent.
- **Precedence for conflicts:** operator request > form instructions > pipeline
  defaults. Private personalization refines resolution without changing the
  contract.

## Stage map -> playbook

| Stage | Purpose | pipeline_ctl gate | Playbook |
|---|---|---|---|
| -1 | setup / scaffold / init | none (pre-kernel) | stage--1.md |
| 0 | form intake (inspect, freeze metrics) | none | stage-0.md |
| 1 | research / evidence pack | none | stage-1.md |
| 2 | design | human: `design` | stage-2.md |
| 2.5 | cast-off / layout plan | script: `layout` (--script-exit) | stage-2.5.md |
| 3 | simulation / validation | script: `sane` (--script-exit) | stage-3.md |
| 4 | write to budget | human: `draft` | stage-4.md |
| 5 | assemble + proof loop | internal verdict | stage-5.md |
| 5.5 | understanding | human: `understand` | stage-5.5.md |
| 5.7 | evaluation panel | internal verdict | stage-5.7.md |
| 6 | return + knowledge | none | stage-6.md |

Order: … 5 -> 5.5 -> 5.7 -> 6 (understanding gate precedes the panel). Stage keys
are fixed strings — never renumber.

## Pointer table

| Need | Document |
|---|---|
| Contract (single truth) | `pipeline/references/CONTRACT_v0.6.md` |
| Master workflow (orchestrator-neutral) | `docs/pipeline-master-v0.6.md` |
| Stage procedures | `pipeline/references/playbooks/stage-<n>.md` |
| Backend routing | `pipeline/references/playbooks/adapters.md` |
| Subagent prompts | `pipeline/references/playbooks/subagent-templates.md` |
| Composition rubric | `pipeline/references/playbooks/rubric-composition.md` |
| Stage 4↔5 interface | `pipeline/references/bundle_spec.md` |
| Registry / stage graph | `pipeline/references/agents.yaml`, `stages.yaml` |
| HWP/HWPX document stages | `adapters/claude-code/SKILL.hwp-master.pointer.md` |
| Prose style rewrite | `adapters/claude-code/agent.humanizer.template.md` |
| Report methodology | `docs/report-method.md` |

## Operating constants

- **Non-destructive:** always work on a copy of the original form. On assembly
  failure, discard the partial and rebuild from the bundle.
- **No fabrication:** every factual claim maps to a research source id or is
  marked as the student's own analysis.
- **No 1M context.** Prefer `/clear` between gates — `resume` guarantees recovery
  from the PIPELINE.md YAML header.
- **Orchestrator is the interactive session** (not headless); backends may run
  headless.
