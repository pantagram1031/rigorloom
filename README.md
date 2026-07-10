# Rigorloom

Rigorloom is an agent-neutral, resumable workflow for weaving evidence,
personalization, document forms, verification, and delivery into one report run.

The state machine is deterministic and provider-independent. Claude, Codex,
Gemini, local models, human operators, or any other capable agent can act as the
orchestrator or worker. Model names in examples are optional adapters, not
requirements.

## What is included

- A config-driven v0.6 pipeline kernel with hard and human gates.
- Stage playbooks and a single master workflow document.
- Automatic handoff generation and safe archival after stage transitions.
- A privacy-first local Studio for inspecting workspaces, resolved profiles,
  gates, evidence, document previews, and evaluation results.
- A robust workspace scaffolder.
- An optional adapter for the separate
  [hwp-master](https://github.com/pantagram1031/hwp-master) project.

Personal reports, student data, private templates, local logs, credentials, and
model-account configuration are intentionally excluded.

## Quick start

Requirements: Python 3.10+; `pytest` for tests; Studio dependencies are optional.

```sh
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom
python scripts/new_report.py --slug demo --subject math \
  --topic "A testable question" --form /absolute/path/to/form.hwpx \
  --profile-root /private/report-profile
python pipeline/scripts/pipeline_ctl.py resume ./workspaces/report-demo
```

Create a private local writing profile once per machine (optional but
recommended). The generated `.local/` directory is ignored by Git:

```sh
python scripts/setup_profile.py
```

For form-specific preferences and feedback candidates, see the
[personalization contract](pipeline/references/personalization_contract.md).

### HWP/HWPX output requirements

The pipeline state machine itself has no model-provider or HWP dependency.
However, the full `.hwp` document workflow requires all of the following on the
machine that runs the document stages:

- Windows with the desktop **Hancom Office HWP** application installed and licensed
- the separate [`hwp-master`](https://github.com/pantagram1031/hwp-master) checkout
- its optional COM packages: `python -m pip install ".[windows]"`
- its optional PDF-proof packages when visual gates are used: `python -m pip install ".[proof]"`

Verify the machine before starting an HWP report:

```powershell
cd ..\hwp-master
python scripts/doctor.py --require-com --require-proof `
  --report-pipeline ..\rigorloom
```

Installing these repositories does not install Hancom Office. Web Hancom Docs,
Linux, and macOS cannot run the local COM editing backend; they can still run the
pipeline and non-COM HWPX/XML stages.

Read [docs/pipeline-master-v0.6.md](docs/pipeline-master-v0.6.md) before running
a stage. Open the returned playbook and follow its entry, role, exit, and gate
contract. Every successful transition refreshes `NEXT_TASK.md` and
`.pipeline/handoff.json` inside the workspace. It also maintains
`WORKSPACE_INDEX.md`, `.pipeline/artifacts.json`, stage receipts, and a clean
stage-owned work area.

Operational knowledge distilled from previous runs is kept in
[lessons learned](docs/lessons-learned.md),
[design decisions](docs/design-decisions.md), and
[troubleshooting](docs/troubleshooting.md). These documents contain generalized
failure patterns only; personal reports and private templates are not included.

Stage 4 includes provider-neutral, rollback-safe humanization. It freezes the
verified draft, accepts paragraph-level edits from Pantadex or any capable agent,
and automatically restores the draft if protected facts change. See
[`humanization_contract.md`](pipeline/references/humanization_contract.md).

## Repository map

```text
pipeline/    state machine, contracts, stage playbooks, tests
studio/      optional read-only local viewer
scripts/     portable workspace and maintenance commands
adapters/    optional document/backend integrations
examples/    generic, non-personal examples
archive/     superseded public contracts kept for history
docs/        current architecture and operating documentation
workspaces/  local run data; ignored by Git
```

## Local Studio

The Studio never uploads report data or calls a model. It reads ignored local
workspaces and shows the live stage graph, next action, personalization lock,
evidence ledger, drafts, PDF iterations, provenance, and scorecards. Its action
rail reads the generated handoff contract to show the next playbook, work area,
missing inputs and outputs, exact gate/resume commands, and the latest normalized
FILL/proof issues. Older workspaces fall back to a read-only `PIPELINE.md` scan.

```sh
python -m pip install -r studio/requirements.txt
python studio/main.py
```

## Safety model

- Human gates cannot be approved by an agent in supervised mode.
- Script verdicts are immutable inputs to state transitions.
- Canonical artifacts are never moved by automatic housekeeping.
- Only known scratch files and run logs are archived.
- Workspace paths and slugs are validated before writes.
- Temporary agent work is isolated by stage and archived at transition.
- Artifact hashes and missing required files are visible before the next task.

## Validation

```sh
python -m pytest -q
python -m py_compile pipeline/scripts/*.py scripts/*.py studio/main.py
```

Licensed under MIT.
