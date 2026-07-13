# Rigorloom — Codex-style harness entrypoint

This file exists so a harness that auto-reads `AGENTS.md` at a workspace
deployment's repo root picks up the pipeline contract without extra
configuration. It is a pointer, not a second copy of the contract.

## The contract lives in one place

Read `adapters/generic/ORCHESTRATOR.md` in full before doing anything. It is
the complete, self-contained bootstrap: the resume → playbook → follow → gate
→ advance loop, the absolute guardrails (never self-approve a human gate,
never hand-edit `PIPELINE.md`, script-gate verdicts are immutable,
non-destructive on source forms, no fabricated numbers, no visual rubric from
a text-only pass), the role table, document-backend notes, and
personalization resolution. Nothing here overrides it — this file only adds
notes specific to Codex-style sandboxed harnesses.

## Harness-specific notes

- **Sandbox write restrictions.** Some Codex-style sandboxes restrict writes
  to paths outside the checked-out repository, or require explicit
  elevated-permission requests for filesystem writes. If your sandbox cannot
  write directly to a workspace path a playbook names, emit the change as a
  patch/diff instead of silently skipping the step, and say so in the
  workspace's `TROUBLES.md` — do not report a stage as advanced when a
  required write did not actually land.
- **No vision.** A Codex-style text CLI has no image or PDF inspection
  capability. Every visual-QA and composition-rubric check in stage 5 and the
  stage 5.7 evaluation panel must be escalated to a vision-capable worker or a
  human — see guardrail 6 in `adapters/generic/ORCHESTRATOR.md`. Do not infer
  a visual verdict from the text content alone.
- **Independent-review seat.** When a playbook calls for an independent
  logic/numeric review or a second council seat, "independent" means you plus
  one genuinely OTHER backend (a different model or provider), not two calls
  in the same Codex session re-reading its own output. If no second backend is
  reachable in this environment, record that gap in `TROUBLES.md` instead of
  presenting a self-review as independent verification.
- **Never self-review your own approval.** The same rule applies to Codex as
  to any other agent: a human gate (`design`, `draft`, `understand`) is never
  satisfied by this harness deciding it is satisfied. Record `auto_approved`
  in autonomous/night mode through `pipeline_ctl.py gate`/`check`; never write
  `approved` on a human gate yourself.

## Where things are

- Full contract and loop: `adapters/generic/ORCHESTRATOR.md`
- Provider-neutral master workflow: `docs/pipeline-master-v0.6.md`
- Unattended-run playbook (ordering rule, verification stack): 
  `docs/autonomous-orchestration.md`
- Stage procedures: `pipeline/references/playbooks/stage-<n>.md`
- Backend/role registry: `pipeline/references/agents.yaml`,
  `pipeline/references/stages.yaml`
