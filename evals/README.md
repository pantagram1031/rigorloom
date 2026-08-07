# `evals/` — clean-room validation harness

This directory answers one question: **does the product work for someone who
is not us?**

Everything in the repo's own test suite runs against the checkout. That proves
the code is correct; it does not prove the *thing we ship* is complete. A
bundle can be green in CI and still be unusable, because the missing piece
lives in a directory the buyer never receives, or because a script quietly
resolves a path back to the author's machine. That failure is invisible from
inside the checkout — so this harness works from outside it, on purpose, and
treats any reference back to the source tree as a hard failure.

Contents:

| file | what it is |
|---|---|
| `cleanroom.py` | install bundles into a throwaway root, self-check, assert containment, materialize tasks, run machine checks |
| `tasks/*.yaml` | task definitions derived from `docs/research/form-eval-scenarios.md` |
| `run_record.schema.json` | the contract for what a launcher must report about one agent run |
| `score.py` | per-run scorecard + the cross-tier comparison table |

---

## 1. What a clean-room run is

A run is clean-room **only** if all five hold:

1. **Fresh temp root.** The sandbox is an empty directory outside the source
   checkout. `prepare` refuses a non-empty root, and refuses any root that
   sits inside a forbidden root.
2. **Bundles only.** Product content enters the sandbox exclusively by
   unzipping `rigorloom-<name>-<version>.zip` files built by
   `scripts/package_module.py`. There is no code path in this harness that
   copies product files out of the checkout — not as a fallback, not behind a
   flag. If a surface is missing from the bundles, the run reports a **gap**
   and fails; it does not quietly patch itself from the repo.
3. **No repo checkout reachable.** Nothing under the sandbox may name, import
   from, or resolve into the source checkout. See §3.
4. **Buyer actions only.** Install = unzip, place modules, enable through the
   shipped registry CLI, install the skill through the shipped installer. Every
   command the harness runs is a command a buyer could run, executed from the
   sandbox copy of the script.
5. **No operator intervention during the agent run.** If a human unsticks the
   agent, the run record must say so (`outcome.operator_intervened`), and the
   scorecard marks it not-a-clean-room-result.

Corpus form files are the *user's documents* in this story, not product
content. They are copied into the sandbox at task-materialization time from
`tests/corpus/forms/`, referenced by path from the task YAML. **The `evals/`
tree embeds no binaries** — that is a `privacy_scan` requirement, not a style
preference.

The Python interpreter is the operator's own (`sys.executable`); a buyer
supplies their own Python too. Everything else is sandbox-local.

## 2. Evidence a run must produce

| artifact | produced by | contents |
|---|---|---|
| `<root>/install_report.json` | `cleanroom.py prepare` | bundles + sha256, per-bundle `--verify` results, registry enable result, capability probe, CLI smoke, skill install result, gaps, containment verdict, every command executed |
| `<root>/work/<task_id>/task.json` | `cleanroom.py task` | rendered prompt, sandbox input paths + sha256, rubric, checks |
| `<root>/work/<task_id>/PROMPT.txt` | `cleanroom.py task` | exactly what the agent is given |
| `<root>/work/<task_id>/checks.json` | `cleanroom.py check` | per-check pass/fail/skip with evidence |
| `run.json` | **the launcher** (not the harness) | `run_record.schema.json` |
| `scorecard.json` | `score.py score` | joined verdict + efficiency metrics |

A run with no `install_report.json` is not a run. A run whose
`install_report.json` says `contained: false` is a *finding about the product*,
and its task results are meaningless until the breach is fixed.

## 3. Containment — the mechanism

`prepare` ends with `containment_report()`, which checks five independent axes
against a set of forbidden roots (this checkout, plus anything passed with
`--extra-forbidden-root`):

1. **Static text scan.** Every text file under the sandbox is searched for the
   forbidden root's path, in both separator flavours, case-insensitively on
   Windows. Rule `source_path_in_install`.
2. **Reported paths.** Every absolute path the shipped tools *report* —
   registry `modules_root`, each checker/CLI script, each skill fragment — must
   resolve inside the sandbox. Rule `reported_path_outside_sandbox`.
3. **Runtime import origin.** A sandbox subprocess imports `module_registry`
   and `privacy_scan` and prints their `__file__` plus its `sys.path`. Both
   must resolve inside the sandbox install, and no `sys.path` entry may sit in
   a forbidden root. Rules `import_resolved_outside_sandbox`,
   `sys_path_entry_in_forbidden_root`. This is the axis a text scan cannot see.
4. **Environment.** `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`,
   `RIGORLOOM_BACKENDS`, `RIGORLOOM_PROFILE_ROOT` are deleted; any other
   variable whose value points into a forbidden root is deleted; `PATH` is
   pruned element-wise; `TEMP`/`TMP` are redirected into the sandbox;
   `RIGORLOOM_ROOT` is *repinned* to the sandbox install (and asserted to stay
   there). Rules `env_not_scrubbed`, `path_entry_in_forbidden_root`,
   `pinned_env_outside_sandbox`.
5. **Links.** No symlink or junction under the sandbox may resolve outside it.
   Rule `symlink_escapes_sandbox`.

Any finding makes `prepare` exit 3. `cleanroom.py verify-containment --root
<root>` re-runs the same assertions over an already-prepared sandbox — use it
after an agent has run, since an agent can introduce a leak the install never
had. The test suite proves the mechanism is not decorative by planting a
source-checkout path into a prepared install and asserting the harness catches
it.

## 4. Pass / fail

**Install** (`prepare`, exit 0 required):

- every bundle passes `--verify` through the *shipped* verifier;
- the registry reports exactly the modules that were asked for, and the
  capability probe agrees with the registry;
- every core CLI and every module-registered CLI answers `--help` with exit 0
  and no traceback;
- containment is clean;
- there are no unacknowledged gaps.

**Gaps** are surfaces a buyer needs that the bundles do not carry. They are
recorded with severity HARD and fail the run unless explicitly acknowledged
with `--allow-gap <id>`. Acknowledging one does not make it disappear: it stays
in `install_report.json` as a product finding. Known ids:

| gap | meaning |
|---|---|
| `skill_surface_not_bundled` | no `SKILL.md` and/or no `scripts/sync_local.py` in the bundle set, so the skill surface cannot be installed from dist zips alone |
| `no_module_bundles` | deliberate core-only install |

> **Open finding as of v0.16.0:** `skill_surface_not_bundled` reproduces on the
> real bundles. `package_module.py`'s core component list ships `engine/`,
> `pipeline/{scripts,references}`, `studio/`, `modules/README.md`,
> `pyproject.toml` and `LICENSE` — but neither `skill/` nor
> `scripts/sync_local.py`. The skill-install step in `cleanroom.py` is written
> against the bundle tree and will start working the moment those are packaged;
> until then every clean-room run must pass
> `--allow-gap skill_surface_not_bundled`, and that acknowledgement is the
> honest statement that a buyer gets the engine but not the skill surface.

**Task** (`check`, exit 0 required): every non-skipped machine check passes.
Skipped checks carry a `blocked_on` reason and are counted separately — a
skipped check is never scored as a pass.

**Run** (`score.py score`, exit 0 required): the agent completed the task, no
operator intervention, machine checks ran and all passed, and no rubric line
was judged `fail`.

## 5. The model-invocation seam

**The harness never launches an agent.** It prepares a sandbox and a prompt,
and it consumes whatever the agent left behind. This is deliberate: hardcoding
a launcher would bind the eval to one product surface and make cross-tier
comparison impossible.

```
cleanroom.py prepare   ─┐
cleanroom.py task       ├─►  <root>/work/<id>/PROMPT.txt   +  <root>/install
                        │
        ╔═══════════════▼═══════════════╗
        ║   YOUR LAUNCHER GOES HERE     ║   Task tool / claude CLI / SDK loop /
        ║   (nothing in evals/ does it) ║   a human at a keyboard
        ╚═══════════════╤═══════════════╝
                        │  writes artifacts into <root>/work/<id>/
                        │  writes run.json per run_record.schema.json
cleanroom.py check     ─┤
score.py score         ─┘
```

The launcher's whole contract is four things:

1. Give the agent the text of `PROMPT.txt` and access to the sandbox
   (`work_dir` is the working directory; `install_root` is where the tooling
   lives). Nothing else — no hints, no repo path.
2. Let it run to completion without help.
3. Leave produced files in `work_dir` under the names the prompt asked for.
4. Write a `run.json` conforming to `run_record.schema.json`, including
   `launcher.kind` and `launcher.skill_loaded` (a no-skill baseline run sets it
   false — `docs/research/skill-efficiency-gen5.md` §5: baseline first).

If your launcher cannot report a metric (tokens, retries), leave it `null`.
The comparison table prints `—` and stays honest; it never estimates.

## 6. Task definitions

`tasks/*.yaml`, schema `rigorloom-eval-task/v1`, derived from
`docs/research/form-eval-scenarios.md`. Seven tasks, one per corpus-backed
family plus the three grant-family scenarios:

| id | family | source scenario | input |
|---|---|---|---|
| `A1-pps-recognize-fill` | grant | A1 | native `.hwpx` |
| `A2-pps-consent-checkboxes` | grant | A2 | native `.hwpx` |
| `A3-kstartup-hybrid` | grant | A3 | XC-1 converted |
| `P1-jumin-recognize-fill` | petition | P1 | XC-1 converted |
| `G1-gianmun-body-edit` | gongmun | G1 | XC-1 converted |
| `H1-labor-contract-fill` | hr | H1 | XC-1 converted |
| `R1-nrf-profile` | research | R1 | XC-1 converted |

Family ③ 학교 서식 has no task (corpus gap) and family ⑤ 기업 내부 문서 has no
task (documented capability boundary) — both are statements in
`docs/release-v0.16.0.md`, not omissions here.

Each task carries:

- `prompt` — what a user would actually type, in Korean, with concrete values
  so the rubric's "never invent unsupplied values" line is testable;
- `input_files` — repo-relative corpus paths, copied into the sandbox;
- `expected_behavior[]` — `[judgment]` rubric lines for a human or LLM judge;
- `machine_checks[]` — assertions runnable after the agent finishes.

Machine-check kinds:

| kind | asserts |
|---|---|
| `python` | run an installed CLI; `expect_exit` and `assert_json` over stdout or a produced `json_file` |
| `shell` | run a raw command (portability is the task author's problem) |
| `file` | `exists` / `absent` / `nonempty` |
| `unmodified` | a task input still hashes to what `task` recorded — the non-destructive contract |
| `geometry` | table geometry (cell addr/size/borderFill/shading, row/col counts) identical between two profiles |
| `idempotence` | two artifacts have identical zip member contents |
| `residue` | `check_residue` exit 0 **and** non-vacuous |
| `text_present` / `text_absent` | strings survive / are gone in the artifact's extracted text |

`assert_json` is a small expression language: `len(anchors) >= 29`,
`table_map[0].rowCnt == 19`, `constraints.max_pages == null`.

The `residue` kind implements the form-fill keep derivation from
form-eval-scenarios.md §"Results appendix" note 1: on a *fill*, the form's own
labels legitimately survive, so `keep` = inventory entries still present in the
artifact. That alone would be vacuous, so the kind additionally requires at
least `require_consumed` inventory entries to have **disappeared** — an agent
that does nothing scores a red residue gate, not a green one.

Checks with `blocked_on` are skipped with the reason recorded (PDF-measured
page budgets need a renderer the clean room does not have; repeat-fill
idempotence needs a second-pass artifact).

## 7. Recipes

Build bundles, then a full clean-room install:

```sh
python scripts/package_module.py --module core   --out dist
python scripts/package_module.py --module report --out dist
python scripts/package_module.py --module style  --out dist

python evals/cleanroom.py prepare \
    --bundle dist/rigorloom-core-0.16.0.zip \
    --bundle dist/rigorloom-report-0.16.0.zip \
    --bundle dist/rigorloom-style-0.16.0.zip \
    --root /tmp/rigorloom-cleanroom \
    --allow-gap skill_surface_not_bundled
```

Core-only ("absence is not failure") install:

```sh
python evals/cleanroom.py prepare --bundle dist/rigorloom-core-0.16.0.zip \
    --root /tmp/rigorloom-core-only --enable none \
    --allow-gap no_module_bundles --allow-gap skill_surface_not_bundled
```

One task, end to end:

```sh
python evals/cleanroom.py task  --root /tmp/rigorloom-cleanroom \
    --task evals/tasks/A1-pps-recognize-fill.yaml
#   ... launcher runs the agent against work/A1-pps-recognize-fill/PROMPT.txt ...
python evals/cleanroom.py check --root /tmp/rigorloom-cleanroom \
    --task evals/tasks/A1-pps-recognize-fill.yaml
python evals/cleanroom.py verify-containment --root /tmp/rigorloom-cleanroom

python evals/score.py score --run runs/A1-opus.json \
    --checks /tmp/rigorloom-cleanroom/work/A1-pps-recognize-fill/checks.json \
    --task evals/tasks/A1-pps-recognize-fill.yaml --out cards/A1-opus.json
python evals/score.py --compare cards/A1-opus.json cards/A1-sonnet.json
```

Every subcommand emits JSON on stdout and follows the repo's exit-code
convention: 0 ok, 2 usage/config refusal, 3 hard finding.
