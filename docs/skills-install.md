# Installing the Claude Code skills and adapters

This repository ships the **public base** of the report workflow. Concrete
backend commands and any private templates come from an **operator overlay** you
keep outside the repo. The installer merges the two into a skills directory.

## Base + overlay model

- **Public base** — everything under this checkout (`<CHECKOUT>`): the pipeline
  kernel, playbooks, the contract, and the Claude Code adapter files in
  `adapters/claude-code/`. Safe to commit and share.
- **Operator overlay** — a private, Git-ignored root, e.g.
  `<PROFILE_ROOT>/skill-overlay`. Holds concrete backend command bindings,
  private document templates, and any voice/persona preference packs. Never
  committed to this public repository.

The overlay wins on conflict for command bindings and templates; the base
provides the router, the contract, and the deterministic gates. This mirrors the
personalization resolution order in
`pipeline/references/personalization_contract.md`.

## Running the installer

Install with a manifest that lists the base files and the overlay root:

```sh
python scripts/sync_local.py --manifest <PROFILE_ROOT>/skill-overlay/manifest.yaml \
  --base <CHECKOUT> --overlay <PROFILE_ROOT>/skill-overlay \
  --skills-root <SKILLS_ROOT>
```

The manifest declares, per skill, which base files to copy and which overlay
files to layer on top. A minimal shape:

```yaml
skills:
  report-pipeline:
    base:
      - adapters/claude-code/SKILL.report-pipeline.md
    overlay:
      - backend-bindings.md        # concrete provider commands (private)
  hwp-master:
    base:
      - adapters/claude-code/SKILL.hwp-master.pointer.md
agents:
  humanizer:
    base:
      - adapters/claude-code/agent.humanizer.template.md
    overlay:
      - voice-pack.md              # persona/voice rules (private, never in base)
```

## How the adapter files map into a skills directory

| Repo file | Installed location |
|---|---|
| `adapters/claude-code/SKILL.report-pipeline.md` | `<SKILLS_ROOT>/report-pipeline/SKILL.md` |
| `adapters/claude-code/SKILL.hwp-master.pointer.md` | `<SKILLS_ROOT>/report-pipeline/references/hwp-master-pointer.md` |
| `adapters/claude-code/agent.humanizer.template.md` | `<agents-dir>/humanizer.md` (with the overlay voice pack merged) |

After install, the router skill's `pipeline_ctl.py` commands still run from
`<CHECKOUT>` root, and every `<WS>` argument is an absolute workspace path.
The separate `hwp-master` project is installed independently — see
`adapters/claude-code/SKILL.hwp-master.pointer.md`.

## Non-Claude orchestrators

The skill files above are the Claude Code packaging of roles that are defined
provider-neutrally in the master workflow document. A different orchestrator
(Codex, Gemini, a local model, or a single human-driven agent) does not need
these files; it covers each role inline by following
`docs/pipeline-master-v0.6.md` — in particular its orchestrator-neutral loop
(§3) and agent-routing section (§6). The stage contract, gates, and immutable
verdicts are identical regardless of which orchestrator runs them; no provider is
required and no provider may bypass a gate.
