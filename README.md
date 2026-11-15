# Rigorloom

Rigorloom fills in Korean official documents in `.hwpx` (보고서, 공문,
지원서, 민원 서식, 근로계약서 같은 인사 서류) without Hancom Office. An agent
or a person proposes each change, and a person approves it. The form is edited
in place rather than regenerated: parts of the package that were not edited
stay byte-identical.

Two checks can run on any edit. `rigorloom guard` names each paragraph where a
number, date, quotation or negation changed. `rigorloom style check` points to
Korean phrasing worth a second look, such as 번역 투 and template-like report
habits; most of its findings are notices, not errors. Both checks are
deterministic.

[![CI](https://github.com/pantagram1031/rigorloom/actions/workflows/ci.yml/badge.svg)](https://github.com/pantagram1031/rigorloom/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

---

## Try it in one minute

The quickest thing to run today is the fact check. No Hancom, no session root,
no network. Works on `.hwpx`, `.txt` and `.md`.

```sh
pip install git+https://github.com/pantagram1031/rigorloom
printf '응답률은 18.6%%였고, 표본이 작아 일반화할 수 없다.\n' > before.txt
printf '응답률은 19%%였고, 표본이 작지만 일반화할 수 있다.\n' > after.txt
rigorloom guard before.txt after.txt --format text
```

```text
paragraphs: 1, edited: 1, changed a protected fact: 1

¶1
  number/unit           18.6%  ->  19%
  negation/hedge/bound  없  ->  (gone)

CHANGED: restore or review the paragraphs above.
```

Exit codes follow the Runtime CLI: 0 means every protected fact is unchanged;
3 means at least one paragraph changed one, or paragraphs were added or removed
(guard refuses to guess an alignment; `result.reason` says which); 2 means the
files cannot be compared. The lower-level `prose_fidelity.py` compares two whole
texts and uses 0/1 instead. Without `--format text`
the result is one JSON document. It counts expressions; it does not read
meaning, so a swap of two values or a reversal said in other words still
passes. In the report pipeline's rewriting step such an edit is not applied,
and the paragraph keeps its original text
([`humanization_ctl.py`](modules/style/scripts/humanization_ctl.py), `apply`);
`rigorloom guard` on its own only reports. `--mode block-diff` prints each
edited paragraph's old and new text side by side
([docs/guard-block-diff.md](docs/guard-block-diff.md)).
[examples/guard/](examples/guard/) has an HWPX pair with its committed
verdict, and the rules are in
[pipeline/references/humanization_contract.md](pipeline/references/humanization_contract.md).

## What this is

Support differs by document type. Reports have a full pipeline from a research
brief and a blank form to a filled, checked, typeset document, with a gate at
every stage. For 공문, 지원서, 민원 and 인사 서류, form checkers and cell filling
are available through the Runtime CLI; end-to-end paths for these types are
being built next.
Current release: **v0.17.0**. See [CHANGELOG.md](CHANGELOG.md) for history.

The core workflow does not require Hancom Office. Linux and Windows
are practiced; macOS is unproven. Any coding-capable AI agent or a
human operator can run it.

**What it is not.** It is not a general-purpose word processor, a
cloud service, or a finished desktop application. The pipeline on `main`
is usable for report automation. A desktop Tauri editor exists on
unmerged branches and is **pre-alpha** — do not rely on it.

## Quick start

Only Python 3.10+ (standard library) is required.

```sh
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom

# Enable the distribution modules shipped in modules/
python pipeline/scripts/module_registry.py write-enabled --all

# Bootstrap: verifies interpreter, provisions profile, runs smoke test.
# It writes outside the checkout, under ~/.rigorloom (profile and workspaces).
python3 scripts/bootstrap.py

# Create and run a report workspace
python scripts/new_report.py \
  --slug demo --subject math \
  --topic "A testable question" \
  --form /path/to/form.hwpx

python modules/report/scripts/pipeline_ctl.py resume ~/.rigorloom/workspaces/report-demo
```

The pipeline drives entirely through CLIs. Stage playbooks under
`modules/report/references/playbooks/` explain each step; see
[docs/golden-path.md](docs/golden-path.md) for the full
clone-to-graded-artifact walkthrough.

### Try it: 공문

Fill and verify the blank statutory 기안문 template
([`gianmun-byeolji-1ho.hwpx`](tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx))
from [`examples/gongmun/brief.json`](examples/gongmun/brief.json) without Hancom
Office and without modifying `modules/enabled.yaml`:

```sh
python runtime/scripts/cli.py demo gongmun --out /tmp/gongmun-demo --deterministic
```

```text
rigorloom demo gongmun: PASS
form: gianmun-byeolji-1ho.hwpx
brief: brief.json
checks: residue hard=0 (acceptance=true, ranAll=true); gongmun hard=0 warn=1 (acceptance=true, ranAll=true)
policies: form->filled PASS; draft->polished skipped
sha256: 4b2972801f79843464ce0d30adf9c8ea7f433c3f6e687bc545d0bb828e33ac1d
artifacts: filled.hwpx, plan.json, verdict.json, approval.json
```

Outputs (`filled.hwpx`, `plan.json`, `verdict.json`, `approval.json`) match
[`examples/gongmun/expected/`](examples/gongmun/expected/) byte-for-byte. Pass
`--polished FILE` to also enforce Policy (ii) (`draft -> polished`) fidelity;
see [docs/demo-gongmun.md](docs/demo-gongmun.md).

### Installing the `rigorloom` command (optional)

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
`preedit`, `check_residue` and the module registry as available with paths
under the install root, and the enabled modules by name. The `xml` and `com`
backends stay unavailable with reasons — they are protocol vocabulary this
build does not execute.

What the installed command then does is cell-level document editing on the
`preedit` backend: `open`, `inspect`, `propose`, `request-approval`,
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
> **Desktop editor: pre-alpha** — a Tauri-based agent-native editor lives
> on unmerged branches (#330 → #340). It is not part of the `main` product
> and should not be evaluated as shipped software.

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

## Local Web UI

A local browser workspace served by `rigorloom ui` (`runtime/scripts/rt_ui.py`),
with no Node.js required at runtime. Open corpus forms or `.hwpx` files, queue
preedit edits, inspect guard diffs, approve plans bound to exact hashes, and
resolve human pipeline gates locally on `127.0.0.1`.

```sh
rigorloom ui
# or from a checkout:
python runtime/scripts/cli.py ui
```

See [docs/web-ui.md](docs/web-ui.md) for options, security model, and limits.

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/golden-path.md](docs/golden-path.md) | Clone-to-artifact walkthrough |
| [docs/pipeline-master-v0.6.md](docs/pipeline-master-v0.6.md) | Stage graph and gate contracts |
| [docs/architecture.md](docs/architecture.md) | System architecture |
| [docs/support-matrix.md](docs/support-matrix.md) | Per-capability status with evidence |
| [docs/extensions.md](docs/extensions.md) | Data-only local knowledge packs |
| [docs/korean-style-rules.md](docs/korean-style-rules.md) | `rigorloom style check` and its Korean phrasing rules |
| [docs/hwp-engine-adapter.md](docs/hwp-engine-adapter.md) | Optional adapter for a separately installed HWP engine |
| [docs/demo-gongmun.md](docs/demo-gongmun.md) | `rigorloom demo gongmun`: fill and verify a 기안문 end to end |
| [docs/web-ui.md](docs/web-ui.md) | `rigorloom ui`: the local browser workspace, its token model and approval binding |
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
