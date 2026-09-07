# Rigorloom

Agent-neutral document automation for Korean HWP/HWPX government forms.

[![CI](https://github.com/pantagram1031/rigorloom/actions/workflows/ci.yml/badge.svg)](https://github.com/pantagram1031/rigorloom/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

---

## What this is

Rigorloom is a **report-automation pipeline** that turns a research brief and
a blank Korean government form (.hwp/.hwpx) into a filled, verified,
typeset document — with deterministic gates at every stage.

It runs on any OS, with any coding-capable AI agent or a human operator,
and does not require Hancom Office for the core workflow.

**What it is not.** It is not a general-purpose word processor, a
cloud service, or a finished desktop application. The pipeline on `main`
is usable for report automation (private-preview maturity). A desktop
Tauri editor exists on unmerged branches and is **pre-alpha** — do not
rely on it.

## Quick start

Only Python 3.10+ (standard library) is required.

```sh
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom

# Enable the distribution modules shipped in modules/
python pipeline/scripts/module_registry.py write-enabled --all

# Bootstrap: verifies interpreter, provisions profile, runs smoke test
python3 scripts/bootstrap.py

# Create and run a report workspace
python scripts/new_report.py \
  --slug demo --subject math \
  --topic "A testable question" \
  --form /path/to/form.hwpx

python modules/report/scripts/pipeline_ctl.py resume ./workspaces/report-demo
```

The pipeline drives entirely through CLIs. Stage playbooks under
`modules/report/references/playbooks/` explain each step; see
[docs/golden-path.md](docs/golden-path.md) for the full
clone-to-graded-artifact walkthrough.

### Windows + Hancom (optional)

The full `.hwp` assembly path additionally requires Windows, a licensed
Hancom Office install, and `pip install .[engine]`. Verify with:

```powershell
python engine\scripts\probe.py
# Require "hancom_com": true before entering the COM path
```

Details: [engine/INSTALL.md](engine/INSTALL.md).

## How it works

```
research → design → data/sim → write → humanize
  → content audit (9 checkers) → assemble (4 backends) → render proof → submit preflight
```

Every gate is deterministic and fail-closed. Script verdicts are immutable
inputs to state transitions — a caller cannot override a computed result.
Two composite gates guard delivery:

- **Content audit** (stage 4.5) — nine sub-checkers covering citations,
  prose style, numerics, cross-references, figure integrity, source
  verification, units, consistency, and claim traceability. Any HARD
  finding blocks assembly.
- **Submission preflight** (stage 6) — verifies the finished artifact's
  identity, form-structure hash, and render proof grade before delivery.

Four document backends are available:

| Backend | Requirements | Output |
|---------|-------------|--------|
| `bundle` | None (stdlib) | Frozen bundle + HTML preview |
| `docx` | `pip install .[docx]` | Styled `.docx` |
| `hwpx` | Bundled XML engine | `.hwpx` (Hancom-free, any OS) |
| `hwp` | Windows + Hancom Office | Native `.hwp`/`.hwpx` with COM |

Only `hwp` currently provides submission-grade render proof.

## Project status

> **Pipeline on `main`: private-preview** — usable report automation with
> stable gates, tested across form families, validated by a clean-room
> harness. Not yet beta.
>
> **Desktop editor: pre-alpha** — a Tauri-based agent-native editor lives
> on unmerged branches (#330 → #340). It is not part of the `main` product
> and should not be evaluated as shipped software.

Stable and exercised capabilities are tracked per-row with evidence
pointers in [`docs/support-matrix.md`](docs/support-matrix.md). The
generator refuses a `supported` row whose evidence does not resolve —
the table cannot claim more than the tree shows.

Known limits stated honestly:

- No committed per-task agent-completion record from a clean-bundle install.
- The legacy v1 render-certificate custody work is unverified across lanes.
- macOS has no bench or CI job; it is inference, not evidence.
- School and corporate form families have no corpus.

For the full evidence record see
[docs/release-v0.17.0.md](docs/release-v0.17.0.md).

## Architecture

```
engine/      HWP/HWPX document engine (COM + XML backends, form inspect)
pipeline/    core contracts, checkers, registry, render proof
modules/     distribution modules: report, style, gongmun, minwon, hr, grant
evals/       clean-room validation harness (installs from dist zips only)
skill/       router skill surface + references (forms, fill-recipe, rubric)
studio/      optional read-only local workspace viewer
scripts/     bootstrap, scaffolder, installer, packaging
adapters/    provider-neutral agent entrypoints
docs/        architecture, research, and operating documentation
tests/       cross-cutting tests + blank-form corpus
```

Six distribution modules ship behind one contract (`modules/README.md`):
`report`, `style`, `gongmun` (공문/기안문), `minwon` (민원/신고),
`hr` (계약/인사), and `grant` (지원사업 신청). Modules declare their
checkers, CLI commands, and skill fragments in `module.yaml`; absence is
not failure — the suite is green with every module disabled.

See [docs/architecture.md](docs/architecture.md) for the full picture.

## Agent integration

The pipeline is provider-independent. Claude, Codex, Gemini, local
models, or any coding-capable agent can orchestrate it. Provider roles
are assigned by capability (`high-reasoning`, `research`, `vision`),
not by vendor name.

- **Agent bootstrap:** [AGENTS.md](AGENTS.md) — the entry point every
  agent reads first.
- **Adapters:** [adapters/](adapters/) — drop-in entrypoints for
  specific providers (optional).
- **Skill surface:** [skill/SKILL.md](skill/SKILL.md) — task router
  with a dynamic capability probe.
- **Model routing:** [skill/references/model-routing.md](skill/references/model-routing.md) —
  measured per-task-class tier guidance, including what is unmeasured.

## Local Studio

A read-only local viewer for inspecting workspaces, gates, evidence,
and document previews. No data leaves the machine.

```sh
pip install -r studio/requirements.txt
python studio/main.py
```

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/golden-path.md](docs/golden-path.md) | Clone-to-artifact walkthrough |
| [docs/pipeline-master-v0.6.md](docs/pipeline-master-v0.6.md) | Stage graph and gate contracts |
| [docs/architecture.md](docs/architecture.md) | System architecture |
| [docs/support-matrix.md](docs/support-matrix.md) | Per-capability status with evidence |
| [docs/extensions.md](docs/extensions.md) | Data-only local knowledge packs |
| [evals/README.md](evals/README.md) | Clean-room validation harness |
| [AGENTS.md](AGENTS.md) | Agent operating instructions |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [docs/README.md](docs/README.md) | Full docs index |

## Validation

```sh
python -m pytest -q                         # full suite
python scripts/py_compile_sweep.py          # syntax check all scripts
python pipeline/scripts/privacy_scan.py .   # privacy scan (0 HARD required)
```

CI runs the suite at two matrix points — core-only (all modules disabled)
and all-modules — so module isolation is continuously proven. Beyond the
suite, the product is validated from outside the checkout via
[evals/](evals/README.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, review discipline,
and PR expectations. Bug reports and feature requests go through
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).

## License

[MIT](LICENSE)
