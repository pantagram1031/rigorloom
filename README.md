# Rigorloom

A report-automation pipeline for Korean HWP/HWPX government forms.

[![CI](https://github.com/pantagram1031/rigorloom/actions/workflows/ci.yml/badge.svg)](https://github.com/pantagram1031/rigorloom/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

---

## What this is

Rigorloom turns a topic, a blank Korean **.hwpx form**, and your data into a
finished, natively typeset report — equations, figures, tables, captions —
and refuses to call it done until every stage gate (independent recomputation
of the numbers, content audit, format check, submission preflight) has passed.
It is built for the documents Korean schools and offices actually require, and
it drives Hancom Office when present and a pure-XML engine when not.
Current release: **v0.17.0**. See [CHANGELOG.md](CHANGELOG.md) for history.

### 30-second demo

A classroom-acoustics inquiry report (20 pages, 12 figures, 9 tables, 8 boxed
equations) produced end-to-end by the pipeline on 2026-09-16 from a simulation
data set and the standard 소논문 form, plus the poster built from the same
workspace:

| Report page 1 | Boxed equations with captions | Field maps | Poster |
|---|---|---|---|
| ![page 1](docs/demo/report-page-01.png) | ![page 3](docs/demo/report-page-03.png) | ![page 10](docs/demo/report-page-10.png) | ![poster](docs/demo/poster.png) |

All 20 pages: [docs/demo/report-all-pages.png](docs/demo/report-all-pages.png).
Every number in the body was re-derived without the engine (51 checks) before
the text was frozen; the assembled file passed the format gate with zero
guide-text residue and a native Hancom proof receipt.

### Editing a finished report

The assembly demo above starts from the blank form. The same AURALAB report can
also be opened finished and edited in place: `--backend com` applied a
`replace_all` and Hancom rendered page 1 is at
[docs/demo/cli-com-edit-page1.png](docs/demo/cli-com-edit-page1.png). On a
finished artifact, pair `open` with `--form-profile` (or `--form`) so residue
checks use the blank form's inventory, and optionally `--declares-file` to
record words that should remain; the desktop exposes the same binding as
양식 연결 ([workspace screenshot](docs/demo/desktop/workspace-1280x800-light.png)).
No apply path here claims render proof.

### Status at a glance

| Surface | State |
|---|---|
| Report pipeline (`modules/report`, stage machine 0 → 6) | usable; the demo above ran through every gate |
| Native Hancom assembly + proof (Windows) | usable; boxed equations, equation captions, poster line |
| Pure-XML assembly (any OS) | usable; structural proof only, boxed equations refused with a named reason |
| Runtime CLI for agents (`rigorloom open/inspect/propose/approve/apply/...`) | three routed apply backends with `engine/`: `preedit`, `com` (Hancom, `native_com_session` receipt), `xml` (any OS, `structural_only` with Runtime-verified well-formedness); `open --form-profile\|--form` binds the blank form; receipts carry `residue.profileSource` and `residue.declaration` |
| Desktop editor (Tauri) | single workspace on `claude/stage1-report-demo`: home, tabbed inspector (선택/검토/기록/에이전트), hunk-card review, checkpoint timeline, 양식 연결; 199 headless tests and passing release-build smoke — not on `main` yet |

The core workflow does not require Hancom Office. Linux and Windows
are practiced; macOS is unproven. Any coding-capable AI agent or a
human operator can run it.

**What it is not.** It is not a general-purpose word processor or a
cloud service. The pipeline on `main` is usable for report automation.
The Tauri desktop on `claude/stage1-report-demo` is exercised (see status
table) but not yet part of the `main` product.

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

### Installing the `rigorloom` command (optional)

Newcomer walkthrough: [docs/QUICKSTART.md](docs/QUICKSTART.md).

The clone above is the whole pipeline and needs no install. If you want the
Runtime CLI as an installed command instead, build and install the wheel from
a checkout:

```sh
python -m pip wheel --no-deps --wheel-dir dist .
python -m pip install --no-deps dist/rigorloom-0.17.0-py3-none-any.whl

rigorloom --root ./rigorloom-root capabilities
```

Add `--no-build-isolation --no-index` to both commands to build and install
offline; under `--no-build-isolation`, setuptools older than 70.1 also needs
the separate `wheel` package for `bdist_wheel`.

There is no published package index for this project — the wheel is built from
a checkout, not downloaded. It carries the Runtime layer only: no `engine/`,
`pipeline/`, or `modules/`. A wheel-only install therefore reports the engine
tools, the module checkers, and the optional render backends as unavailable,
each with a reason, in `rigorloom ... capabilities`.

### Giving the command an engine: the ZIP payload

The wheel is one half of the product. The other half is the ZIP bundles that
`scripts/package_module.py` builds — they carry `engine/`, `pipeline/scripts`,
the skill surface, and the distribution modules. Install them into a directory
of your own and point the command at it; **`--engine-root` takes an install
root, not a checkout.**

```sh
# 1. build the bundles (from a checkout, once)
python scripts/package_module.py --module core   --out dist
python scripts/package_module.py --module style  --out dist
python scripts/package_module.py --module report --out dist

# 2. install them into an INSTALL ROOT of your choosing
mkdir -p ~/rigorloom-install
cd ~/rigorloom-install
unzip /path/to/dist/rigorloom-core-0.17.0.zip
unzip /path/to/dist/rigorloom-style-0.17.0.zip  'modules/*'
unzip /path/to/dist/rigorloom-report-0.17.0.zip 'modules/*'
python pipeline/scripts/module_registry.py write-enabled --all

# 3. drive the install root with the installed command
rigorloom --root ~/rigorloom-work --engine-root ~/rigorloom-install capabilities
```

`report` declares `requires_modules: [style]`, so a report payload is three
zips; the registry refuses to enable `report` alone rather than half-enabling
it. With the payload installed, `capabilities` reports `form_inspect`,
`check_residue`, the module registry, and each apply backend's availability
(`preedit`, `xml` when scripts resolve; `com` when Hancom is present).

What the installed command then does is cell-level document editing with
`propose --backend preedit|com|xml`: `open`, `inspect`, `propose`, `request-approval`,
`approve`, `apply`, `verify`. `verify` is fail-closed on runnability — it exits
non-zero when a required checker could not run — and it reports the residue
gate's verdict rather than assuming it. That verdict measures a *finished*
artifact, so a document that has only had some cells filled will still be
reported as carrying the form's own anchor text. Finishing a document is the
full pipeline's job, not one plan's.

This is a different distribution from the module and skill ZIP bundles, not a
replacement for them: those ship module payloads and skill fragments, the
wheel ships one command, and each is built and installed on its own terms.

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
| `hwpx` | Bundled XML engine | `.hwpx` (Hancom-free; OS support: see Known limits) |
| `hwp` | Windows + Hancom Office | Native `.hwp`/`.hwpx` with COM |

Only `hwp` currently provides submission-grade render proof.
Terminal grade is `none` for XML and LibreOffice in this release.
Equation-free LibreOffice may produce an internal `advisory` candidate,
but `ADVISORY_PROOF_RELEASE_ENABLED` is false and prevents promotion.

## Project status

> **Pipeline on `main`: private-preview** — usable report automation with
> deterministic gates, tested across form families, validated by a
> clean-room harness. Not yet beta.
>
> **Desktop editor** — on `claude/stage1-report-demo`, a single-workspace
> Tauri shell (home, hunk-card review, 양식 연결) passes 199 headless tests and
> release-build smoke; not merged to `main` yet.

Exercised capabilities are tracked per-row with evidence
pointers in [`docs/support-matrix.md`](docs/support-matrix.md). The
generator refuses a `supported` row whose evidence does not resolve —
the table cannot claim more than the tree shows.

Known limits stated honestly:

- No committed per-task run record from a clean-bundle install.
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
