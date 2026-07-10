# Report Pipeline

An agent-neutral, resumable workflow for producing evidence-backed reports from
research through document assembly, review, and handoff.

The state machine is deterministic and provider-independent. Claude, Codex,
Gemini, local models, human operators, or any other capable agent can act as the
orchestrator or worker. Model names in examples are optional adapters, not
requirements.

## What is included

- A config-driven v0.6 pipeline kernel with hard and human gates.
- Stage playbooks and a single master workflow document.
- Automatic handoff generation and safe archival after stage transitions.
- A read-only local Studio for inspecting workspaces.
- A robust workspace scaffolder.
- An optional adapter for the separate
  [hwp-master](https://github.com/pantagram1031/hwp-master) project.

Personal reports, student data, private templates, local logs, credentials, and
model-account configuration are intentionally excluded.

## Quick start

Requirements: Python 3.10+; `pytest` for tests; Studio dependencies are optional.

```sh
git clone https://github.com/pantagram1031/report-pipeline.git
cd report-pipeline
python scripts/new_report.py --slug demo --subject math \
  --topic "A testable question" --form /absolute/path/to/form.hwpx
python pipeline/scripts/pipeline_ctl.py resume ./workspaces/report-demo
```

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
  --report-pipeline ..\report-pipeline
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
