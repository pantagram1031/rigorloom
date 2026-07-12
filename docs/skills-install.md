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

Install with a manifest. The manifest itself carries the absolute roots
(`install_root`, `overlay_root`); the CLI only points at the manifest and,
optionally, the checkout the base is copied from:

```sh
python scripts/sync_local.py --manifest <PROFILE_ROOT>/skill-overlay/manifest.yaml
# optional flags:
#   --checkout-root <CHECKOUT>   base 'from' paths resolve here (default: this repo root)
#   --dry-run                    print per-file actions and exit without changes
#   --force                      overwrite drifted files / steal a stale lock
#   --only <target-name>         process a single target
```

If `--manifest` is omitted it defaults to `scripts/sync_manifest.example.yaml`.

The manifest describes a **target**: an absolute `install_root`, an optional
absolute `overlay_root`, a `source_map` (checkout-relative `from` → install-relative
`to`, for a directory or a single file), and an `exclude` glob list. Overlay files
are not enumerated per-file — every file found under `overlay_root` is layered onto
the staged base by its install-relative path (replace or add). A minimal shape:

```yaml
# install_root / overlay_root are ABSOLUTE. source_map 'from' is checkout-relative,
# 'to' is install-relative. Scalars are literal, so Windows backslash paths survive.
install_root: "<SKILLS_ROOT>/report-pipeline"
overlay_root: "<PROFILE_ROOT>/skill-overlay"

source_map:
  - from: "pipeline/scripts"                                # kernel CLIs
    to: "scripts"
  - from: "pipeline/references"                             # playbooks, prompts, packs, contracts
    to: "references"
  - from: "adapters/claude-code/SKILL.report-pipeline.md"   # router skill entry
    to: "SKILL.md"
  - from: "adapters/claude-code/SKILL.hwp-master.pointer.md"
    to: "references/hwp-master-pointer.md"

exclude:
  - "__pycache__"
  - "*.pyc"
  - ".sync*"
```

A single `install_root` is one skill directory. To install files whose home is a
different root (for example the harness `agents/` directory for
`agent.humanizer.template.md`), add a `repo_targets:` list — each entry takes the
same `install_root` / `overlay_root` / `source_map` / `exclude` fields with its own
root. The overlay wins on conflict, so a private voice pack layered into the
humanizer target supplies persona content the public base never carries.

Each sync writes a per-file receipt (`.sync_receipt.json`, origin + sha256) and
swaps the install in atomically, archiving the previous tree to
`<install_root>.bak-<timestamp>`. A file hand-edited in the install since the last
sync is **refused** (`--force` to override) — edit upstream or the overlay instead.

## How the adapter files map into a skills directory

Those installed locations are just `source_map` `to` paths under each target's
`install_root`:

| Repo file (`from`) | Target `install_root` | `to` |
|---|---|---|
| `adapters/claude-code/SKILL.report-pipeline.md` | `<SKILLS_ROOT>/report-pipeline` | `SKILL.md` |
| `adapters/claude-code/SKILL.hwp-master.pointer.md` | `<SKILLS_ROOT>/report-pipeline` | `references/hwp-master-pointer.md` |
| `adapters/claude-code/agent.humanizer.template.md` | `<agents-dir>` (a `repo_targets` entry) | `humanizer.md` (overlay voice pack layered on top) |

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
