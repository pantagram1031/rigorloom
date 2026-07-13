# Generic orchestrator bootstrap — any coding-capable agent

Read this whole file before touching a workspace. It is the complete contract
for driving Rigorloom without any vendor-specific harness: a different
provider's CLI, an API-driven worker loop, a local model, or a human typing
commands by hand can all follow it directly.

Rigorloom turns a topic, constraints, sources, and an optional document form
into a researched, verified, typeset report through a deterministic state
machine. The machine — not any agent's memory of what it did — is the source
of truth: every stage and gate lives in a workspace's `PIPELINE.md` YAML
header, so a dropped session, a crashed process, or a handoff to a completely
different agent resumes at the exact same point. `pipeline_ctl.py` is the only
way to change that state; hand-editing the YAML is a contract violation no
matter which agent does it.

## The loop

Run every command from the repository root (`<CHECKOUT>`). `<WS>` is always
the workspace's absolute path.

```sh
python pipeline/scripts/pipeline_ctl.py resume <WS>
```

1. **RESUME** — the command above returns the stage to work on next.
2. **PLAYBOOK** — open `pipeline/references/playbooks/stage-<n>.md` for that
   stage and read it in full. It has the exact commands; do not improvise
   substitutes.
3. **FOLLOW** — execute those commands. Bind each role the playbook names to
   whatever backend your environment actually has (see the role table below).
4. **GATE** — resolve the stage's gate, if it has one (see Guardrails).
5. **ADVANCE** — run the playbook's exit/advance command, then go back to
   step 1.

A brand-new run starts at stage `-1` (`pipeline/references/playbooks/stage--1.md`,
setup/scaffold). Because `resume` is deterministic, re-reading `PIPELINE.md`
after any interruption — including handing the workspace to a different agent
or provider mid-run — reproduces the same next step. Read the regenerated
`NEXT_TASK.md` after every transition; it is the short human-readable entry
point, `WORKSPACE_INDEX.md` is the full artifact table, and
`.pipeline/handoff.json` is the machine-readable equivalent for a scripted
caller.

The authoritative stage order and gate types are in
`pipeline/references/stages.yaml` and are explained in
`docs/pipeline-master-v0.6.md` (§4). If this file and the code ever disagree,
the code and `pipeline/references/CONTRACT_v0.6.md` win.

## Absolute guardrails

These are non-negotiable regardless of which agent or provider is driving:

1. **Never self-approve a human gate.** `design`, `draft`, and `understand`
   gates require real human approval in `supervised` mode. In `autonomous` or
   `night` mode, record `auto_approved` through the gate command — never write
   or claim `approved` for a human gate; that would be forging a signature no
   agent has authority to give.
2. **Never edit `PIPELINE.md` by hand.** Every transition, gate, and
   invalidation goes through `pipeline_ctl.py`, which also regenerates
   `NEXT_TASK.md` and `.pipeline/handoff.json`.
3. **Script-gate verdicts are immutable.** `pipeline_ctl.py check <WS> <gate>`
   runs the registered checker and records its exit code, stdout hash, and
   timestamp. A non-zero exit rejects the gate. To change the outcome, change
   the inputs and rerun `check` — never edit the recorded verdict, and never
   fabricate a passing exit code. A pending script gate blocks resume and
   advance in every run mode, including `night`.
4. **Work is non-destructive on source forms.** Always operate on a copy of
   the original document form; never edit or overwrite the original. On an
   assembly failure, discard the partial output and rebuild from the frozen
   bundle rather than patching a damaged copy.
5. **No fabricated numbers.** Every numeric claim in the report must come from
   a real, re-runnable computation recorded under `sim/`, or be explicitly
   marked as the author's own analysis. Prose never introduces a number that
   the frozen results file does not contain.
6. **Text-only models must not fill visual rubrics.** Stage 5 proofing and the
   5.7 evaluation panel both require inspecting rendered pages, figures, and
   equations at high resolution. A model that cannot see images must not mark
   a visual-QA or composition check as passed from reasoning alone — escalate
   to a vision-capable worker or a human instead. This applies equally to
   every provider; there is no text-only shortcut for a visual gate.

See `docs/autonomous-orchestration.md` for the fuller unattended-run
playbook (ordering rule, verification stack, anti-patterns) that sits on top
of this contract, and its own no-vision caveat in the tooling-facts section.

## Role table (capability, not vendor)

Roles are capability labels, defined provider-neutrally in
`pipeline/references/agents.yaml`. No role name implies a specific product.

| Role | Needs | If your harness has no subagents |
|---|---|---|
| orchestrator | state tracking, file/command access | this is you — the agent reading this file |
| writer/designer | high reasoning, long-form writing | do it inline, in a focused pass with nothing else mixed in |
| researcher | source discovery or supplied-source analysis | do it inline; keep an explicit source list either way |
| simulation worker | code execution, deterministic checks | run it yourself; the gate script still validates the result |
| mechanical worker | reliable filesystem/command execution | do it inline — this role has no judgment component |
| vision judge | image/PDF inspection | you need a vision-capable pass here; a text-only model cannot substitute (see guardrail 6) |
| logic/numeric reviewer | independent critical verification | do a genuinely separate pass — different context or model, not the same reasoning re-read. If you truly cannot get a second context or model, record that gap in `TROUBLES.md`; do not present a self-review as independent |
| human | approval, escalation authority | never substitutable — only a human resolves a human gate |

A single agent may perform several roles sequentially when no parallel workers
are available, but it must record the reduced independence (e.g. in
`events.jsonl` or `TROUBLES.md`) rather than silently presenting a self-review
as independent verification. See `pipeline/references/playbooks/adapters.md`
for the fuller capability-mapping table and provider examples (all
non-normative — any backend meeting the capability qualifies).

## Document backends

Stage 5 assembly is pluggable by capability, not by requiring one product:

- A zero-dependency backend (content bundle + rendered preview) is always
  available and needs nothing beyond this checkout.
- Optional richer backends (e.g. a `.docx` writer, or an HWP/Hancom backend on
  Windows) may be selected in a workspace's `build.yaml` when their extra
  dependencies are installed.
- The HWP backend specifically requires Windows, a locally installed Hancom
  Office, and the separate `hwp-master` adapter checkout (see
  `adapters/hwp/README.md`); it is never required to run the pipeline.

Consult the current stage-5 playbook for the exact backend selection and
commands available in this checkout — do not assume a backend is present
without checking.

## Personalization

If a private profile root exists (`pipeline/scripts/personalization_ctl.py
--profile-root <ROOT> ...`), resolve it per
`pipeline/references/personalization_contract.md` — operator taste (prose
rules, figure style, report structure, backend seating) is layered
`request > form > subject > global > public defaults`, with non-overridable
policy floors on top. If no profile root exists, the public neutral defaults
in `pipeline/references/preference_packs/defaults/` apply automatically; do
not invent personalization when no profile is configured.

## Precedence for conflicting instructions

```text
operator request > form instructions > pipeline defaults
```

## Completion

A run is complete only when: every stage is done in authoritative order, every
gate (human, script, internal) is resolved honestly, the canonical output and
its proof artifacts exist, source/provenance records are intact,
`NEXT_TASK.md` reports completion, and no private workspace, form, credential,
or personal profile has been committed to the public repository. If any of
these is not true, the run is not done — regardless of what any single agent's
turn claims.
