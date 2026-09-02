---
name: Agent behavior
about: The agent proposed something wrong, refused something it should have done, or behaved unexpectedly
title: "[Agent] "
labels: agent-behavior
---

<!--
  If the agent APPLIED a change, resolved an approval, or otherwise acted
  without a human approving it, that is not this template. `approval/resolve`
  and `plan/apply` are absent from the AGENT registry by construction, so an
  agent reaching them is an authority-boundary break: report it privately per
  SECURITY.md instead of opening a public issue.
-->

## What the agent did

What was proposed, refused or attempted, and what should have happened
instead. Quote the agent's own wording where it matters — a plan that is
wrong and a plan that is right but explained badly are different bugs.

## The instruction

The prompt or instruction the agent was given, verbatim. Paraphrasing it
changes the input, and the input is half of what is being debugged.

## The plan

A proposal is a plan, and a plan is identified rather than described. Give
both identifiers and the plan itself:

- **planId**:
- **planHash**:

```sh
python runtime/scripts/cli.py --root <root> plan --plan <planId>
```

The plan payload carries `planHash`, the ops, and the addresses each op
targets. Paste it whole: an op list without its addresses cannot be checked
against the document it claims to edit.

## Review-queue state

What the queue looked like when this happened — the plan landed in the same
queue a human edit lands in, and what the queue said about it is the record.

- **approvalId**:
- State at the time (pending / approved / rejected / not opened):

```sh
python runtime/scripts/cli.py --root <root> approval --approval <approvalId>
```

If the queue refused or the approval would not resolve, the refusal payload is
the finding — paste its `code` and `data`, not a retelling.

## The ordered record

The session event log is the only account of what actually happened in order,
and it is what separates "the agent proposed this" from "the app displayed
this":

```sh
python runtime/scripts/cli.py --root <root> events --session <sessionId> --after -1
```

## Provider and build

- Provider (`mock` / `router` / Anthropic adapter):
- Model, if not `mock`:
- Surface (Desktop composer / `agenthost/scripts/host.py` directly / other):
- Rigorloom version / commit:

```sh
python runtime/scripts/cli.py --root <root> capabilities
python agenthost/scripts/host.py --capabilities --provider <provider>
```

The second command needs no root and names the tools the host actually
exposes to the model, which is the fastest way to tell a missing capability
from a misused one.

## Additional context

Please do not attach real document content or personally identifying data —
see [AGENTS.md](../../AGENTS.md). Plans, approvals, event logs and capability
payloads are built to be shareable; the document they refer to is not. If a
plan's addresses embed text you cannot share, say so and redact those fields
rather than dropping the plan.
