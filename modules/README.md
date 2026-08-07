# Distribution modules — the contract

This directory holds rigorloom's **distribution modules**: optional capability
bundles that install on top of the core document engine and light up extra
checkers, CLI subcommands, run modes, studio panels, and skill fragments when
enabled. Core ships alone (`rigorloom-core`); each module ships as its own
installable bundle (`rigorloom-report`, `rigorloom-style`, …) at the same
version as core.

> **Naming: "distribution module" vs "stage contract".**
> This repo already uses the word "module" for a different thing:
> `modules/report/references/modules.yaml` + `modules/report/scripts/compose.py` define the
> v0.12 *pipeline stage composition* vocabulary (16 typed consumes/produces
> contracts with a mandatory-gate floor). Those are **stage contracts** — units
> of *pipeline work*. The things in this directory are **distribution
> modules** — units of *packaging and capability*. The two axes are unrelated:
> a distribution module may *declare* run modes that select stage-contract
> compositions, but nothing in this directory replaces, renames, or weakens
> the compose resolver or its gate floor. Docs and error messages must say
> "distribution module" or "stage contract", never a bare "module" where the
> reader could confuse the two.

## Layout

```
modules/
  README.md            ← this contract
  enabled.yaml         ← per-install enablement (never committed; absent = none)
  <name>/
    module.yaml        ← the module's declaration (schema below)
    scripts/           ← payload: checker/CLI scripts (paths are module-relative)
    references/        ← payload: docs, packs, playbooks
    skill/             ← payload: SKILL fragment + references
    ...                ← any other payload dirs the module needs
```

`module.yaml` is the only file core ever reads to learn what a module
contributes. Its schema is `pipeline/references/module.schema.json`
(machine-validated by `pipeline/scripts/module_registry.py`; the schema file is
the normative shape). The declaration is pure literals — no expressions, no
includes, no environment interpolation.

```yaml
schema: rigorloom-module/v1
name: report                      # kebab-case; MUST equal the directory name
requires: { rigorloom: ">=0.16" } # version range checked against pyproject
requires_modules: [style]         # optional: other distribution modules that
                                  # must ALSO be enabled (see Enablement model)
provides:
  checkers:                       # registered into the check registry
    - { name: check_saeteuk, script: scripts/check_saeteuk.py }
  cli:                            # subcommands under the main entry point
    - { command: poster, script: scripts/poster_build.py }
  pack_types:                     # personalization pack types it defines
    - saeteuk
  run_modes:                      # run-mode definitions (plan §3.2)
    - { name: night, state_policy: stage_machine, gates: [content_audit] }
  gate_kinds:                     # declared-gate kind mechanisms (declared_gates.py)
    - { kind: canonical, checker: check_canonical }
  studio_panels:                  # declarative UI contributions (plan §3.4)
    - { id: stage-progress, title: Stage progress, entry: studio/stage_panel.js }
  skill:                          # SKILL fragment merged by the installer
    fragment: skill/FRAGMENT.md
    references: [skill/references/report_rules.md]
  playbooks:                      # stage/task playbooks
    - references/playbooks/night_run.md
```

## The four rules

Verbatim from `docs/plans/v0.16-unified-core-and-modules.md` §3.1; the
registry and CI enforce them.

- **Core never imports a module.** Dependency points one way; modules register
  through the registry; core has no name-level knowledge of any module.
- **Absence is not failure.** Core's suite runs green with every module
  disabled. CI runs both matrix points (core-only, all-modules) — added
  **before** anything moves.
- **Presence is integration.** Enabling a module surfaces its checkers, CLI,
  panels, and modes with no further configuration.
- **Adding a module later requires no core change.** This covers the *test
  harness* as well as the runtime registry. Adding gongmun (PR #65) needed
  nothing from the registry but still forced two core edits — pyproject's
  `testpaths` and CI's `py_compile` glob were both hardcoded per-module lists.
  Both are now module-agnostic (`modules/*/tests`, and
  `scripts/py_compile_sweep.py`'s `modules/*/scripts/*.py`), and
  `pipeline/tests/test_module_registry.py::TestHarnessIsModuleAgnostic` proves
  the property: a brand-new module dropped into a synthetic checkout has its
  tests collected and its scripts compiled with zero files created or edited
  outside `modules/`. **If you find yourself adding a module's name to a file
  outside `modules/`, that file is the bug.**

## Provides keys

Every key under `provides:` is optional; an empty `provides: {}` is a valid
(if pointless) module. All script/file paths are relative to the module
directory and must exist at enablement time — a dangling path is a loud
enablement error, not a silent skip.

| key | shape | semantics |
|---|---|---|
| `checkers` | list of `{name, script}` | Deterministic checkers joining the check registry. `name` is the checker id (unique across all enabled modules and core); `script` follows the core checker contract (`checker_base.py`: JSON verdict on stdout, exit 0/2/3). Core discovers them via `ModuleRegistry.enabled_checkers()`, never by filename convention. |
| `cli` | list of `{command, script}` | Subcommands surfaced under the main entry point. `command` is kebab-case and unique across enabled modules; core dispatches to `script` without knowing the module's name. |
| `pack_types` | list of names | Personalization pack types the module defines. Seeds the pack-type registry that replaces the hardcoded `DATA_EXTENSION_PACK_TYPES` tuple (v0.13 extension-pack absorption). Names are unique across enabled modules and must not collide with core's general pack types. |
| `run_modes` | list of `{name, state_policy, gates}` | First-class run-mode objects (plan §3.2): `state_policy` is one of `stage_machine` / `receipts` / `stateless` / `stateless_final_pointer` (the last = stateless, plus a mandatory canonical/FINAL pointer at delivery, validated by the registry-declared `check_canonical` checker — report-module payload since W3-S2b); `gates` is either an explicit list of checker/gate names the mode enforces, or a single gate-source string — the literal `declared` (per-workspace declared gates via `declared_gates.py`) or a stage-graph filename such as `stages.yaml` whose gate table defines the mode's gates. Modes are selected per workspace and shown by the capability probe. Run modes *select* stage-contract compositions; they never redefine the gate floor. |
| `gate_kinds` | list of `{kind, checker}` | Declared-gate kind registrations for `declared_gates.py` (one runner, registry mechanisms, declared values). `kind` joins the declared-gates vocabulary (unique across enabled modules; must not shadow a core-implemented kind); `checker` names an enabled module's `provides.checkers` entry whose in-process `check(workspace, **declared_params)` implements the kind — a dangling binding is a loud enablement error. A workspace `gates.yaml` declaring a kind no enabled module registers is a loud config refusal (exit 2), never a silent pass. Core-implemented kinds (`json_equals`/`json_lt`/`json_gt`/`file_exists`/`text_absent`, `residue`, `density`) stay core. |
| `studio_panels` | list of `{id, title, entry}` | Declarative studio contributions (plan §3.4). Studio exposes enabled panels at `GET /api/panels` and serves each `entry` (an HTML/JS fragment, path-contained inside the module dir) at `GET /api/panels/<id>/entry`; a JS entry registers its renderer via `window.RigorloomStudio.register(id, render)`. Absent module, absent panel; studio never learns a module's name. |
| `skill` | `{fragment, references}` | One SKILL fragment plus its reference files, merged into the distribution bundle's router SKILL.md by the installer. A core-only install never sees the fragment's vocabulary. |
| `playbooks` | list of paths | Stage/task playbooks the module contributes. |
| `preflight` | list of `{name, script}` | Submission-preflight contributions. Core's `submission_preflight` (artifact/proof half: P1/P2/P3/P5, form-structure hash, verdict_schema) asks the registry for enabled modules' contributions via `enabled_preflight()` and subprocess-composes each script's JSON findings source-tagged into its own verdict — the same merge semantics the former in-process saeteuk composition had. `name` is unique across enabled modules; `script` honours the checker contract (`checker_base.py`: JSON verdict on stdout, exit 0/2/3) and is invoked as `python <script> <workspace>`. No modules enabled = those checks simply absent (absence is not failure). |

### Modules may contribute visual-verify expectations

`pipeline/scripts/visual_verify.py` (the render→judge loop; see
`skill/references/operations.md` §10 and `skill/references/visual-rubric.md`)
takes an optional `--expectations <json>` declaring what the render is
supposed to look like: `pages_document`, `page_budget`, `base_pt`,
`line_spacing_pct`, `margins_mm`, `fill_map`, `intentionally_blank`,
`blank_pages`, `forbidden_text`. Anything not declared is not checked, and
the verdict lists it under `deterministic.skipped`.

A distribution module is the natural author of that file — a report module
knows its own page budget and body point size; a form-family module knows
which cells are staff-only. **There is no new `provides` key for this.** A
module ships the expectations as ordinary payload (a `references/` JSON, or a
playbook/CLI step that composes one from the workspace) and the caller passes
the path. Core stays name-blind: `visual_verify` reads a JSON file, never a
module registry entry, so a core-only install runs the same loop with fewer
declarations and says so out loud in `skipped`.

## Enablement model

- Enablement is **per install**, recorded in `modules/enabled.yaml`:

  ```yaml
  schema: rigorloom-enabled-modules/v1
  enabled: [report, style]
  ```

- **Missing file = nothing enabled = core-only.** This is the repo's committed
  state; `enabled.yaml` is gitignored and written by the installer or by
  `python pipeline/scripts/module_registry.py write-enabled`.
- A module that is present on disk but not listed contributes **nothing** —
  no checkers, no CLI, no panels. Discovery still validates its `module.yaml`
  (a broken declaration is loud even when disabled, so packaging never ships a
  dud).
- Listing a name with no matching `modules/<name>/module.yaml` is a loud
  configuration error, not a skip.
- Enabling a module whose `requires.rigorloom` range does not admit the
  project version (from `pyproject.toml`) is a **load refusal** with a message
  naming the module, the required range, and the actual version.
- **Inter-module dependencies** are declared with the optional top-level
  `requires_modules: [names]` key and enforced at **enablement**: enabling a
  module whose `requires_modules` are not all enabled is a loud registry
  error naming the missing modules (same style as the version-gate refusal).
  A dependency that is present on disk but not listed in `enabled.yaml` is
  still an error — disabled means missing. A module may not depend on itself;
  dependencies are names only (no version ranges — all modules ship at the
  core version). Module payloads may additionally fail closed at run time
  when a dependency's contribution is absent (defense-in-depth), but the
  enablement check is the primary enforcement.
- Two enabled modules may not both provide the same checker `name`, CLI
  `command`, `pack_type`, run-mode `name`, or panel `id` — collisions are loud
  enablement errors.

Core code consumes modules exclusively through the typed accessors on
`pipeline/scripts/module_registry.py` (`enabled_checkers()`,
`enabled_pack_types()`, `enabled_run_modes()`, …). If a core change needs a
module's *name* to work, the change is wrong — that is the contract leaking.

## How module scripts import (the one mechanism)

Module payload scripts are plain files, not a package. A script in
`modules/<name>/scripts/` that needs a sibling script or a core helper
(`checker_base.py`, `personalization_ctl.py`, …) uses exactly this header —
the same cross-directory pattern `engine/tests` uses to reach
`engine/scripts`:

```python
SCRIPTS_DIR = Path(__file__).resolve().parent
CORE_SCRIPTS_DIR = SCRIPTS_DIR.parents[2] / "pipeline" / "scripts"
for _dir in (CORE_SCRIPTS_DIR, SCRIPTS_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
```

The module scripts dir ends up *ahead* of core on `sys.path`, so sibling
imports win by position while core helpers resolve normally. The dependency
still points one way: module scripts import core freely; no core script ever
imports from a `modules/` directory. Module tests use the same idea —
`Path(__file__).parents[1] / "scripts"` for the module payload plus the core
`pipeline/scripts` dir when they need core helpers — and
`modules/<name>/tests/conftest.py` marks the whole directory skipped unless
the module is enabled, so a core-only run collects-and-skips cleanly.
