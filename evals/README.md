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

> **Closed (post-v0.16.0 packaging fix):** `skill_surface_not_bundled` was a
> real finding of this harness — the v0.16.0 core bundle shipped `engine/`,
> `pipeline/{scripts,references}`, `studio/`, `modules/README.md`,
> `pyproject.toml` and `LICENSE`, but neither `skill/` nor
> `scripts/sync_local.py`, so a buyer received the engine and no skill
> surface. The core bundle now ships `skill/SKILL.md`, `skill/references/`,
> `scripts/sync_local.py` and `scripts/sync_manifest.example.yaml`, and
> `package_module.py` refuses to build a core bundle that lacks any of them.
> **A current bundle set therefore installs with zero `--allow-gap`
> arguments.** The gap id is kept — it is a live check, not a historical note,
> and `tests/test_cleanroom_evals.py` proves both halves: a current bundle set
> trips nothing, and stripping the surface out of a prepared install brings
> the gap straight back.
>
> The only gap a healthy run still reports is `no_module_bundles`, and only
> when you deliberately install core alone.

**Task** (`check`, exit 0 required): every non-skipped machine check passes.
Skipped checks carry a reason — a `blocked_on` note or an unmet
`requires_module` (§6) — and are counted separately in `counts.skipped`. **A
skipped check is never scored as a pass**: `score.py` reads those counts, so a
skip can satisfy neither `check`'s exit 0 nor the scorecard's "machine checks
ran and all passed".

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
`docs/research/form-eval-scenarios.md`. At least one task per corpus-backed
family, plus extra scenarios where a family has more than one shape worth
exercising:

| id | family | source scenario | input |
|---|---|---|---|
| `A1-pps-recognize-fill` | grant | A1 | native `.hwpx` |
| `A2-pps-consent-checkboxes` | grant | A2 | native `.hwpx` |
| `A3-kstartup-hybrid` | grant | A3 | XC-1 converted |
| `P1-jumin-recognize-fill` | petition | P1 | XC-1 converted |
| `P2-jeongbo-staff-seats` | petition | P2 | XC-1 converted |
| `G1-gianmun-body-edit` | gongmun | G1 | XC-1 converted |
| `H1-labor-contract-fill` | hr | H1 | XC-1 converted |
| `R1-nrf-profile` | research | R1 | XC-1 converted |

**The inventory is a property, not a count.** `tests/test_cleanroom_evals.py::
TestTaskDefinitions::test_every_shipped_task_validates` asserts that every
shipped definition validates, that every family in
`tests/corpus/forms/manifest.json` `documents[]` has at least one task (the
family list is *derived* from the manifest, never listed in the test), that no
task claims a family the corpus does not back, and a non-vacuity floor so the
scan cannot pass on zero tasks. Adding a task here requires no core edit; adding
a *family* to the corpus obliges a task for it.

Three tasks additionally run a work-type distribution module's checker over the
blank form and over the produced artifact:

| task | module | checker | what it adds |
|---|---|---|---|
| `G1-gianmun-body-edit` | gongmun | `check_gongmun` | 두문/결재란/결문/발신명의/직인 seats and the 별지서식 guide vocabulary that must not survive |
| `P1-jumin-recognize-fill` | minwon | `check_minwon` | the 별지서식 frame, 선택 항목 slot preservation, the 서명 markers, the 유의사항/수수료/제출서류 blocks that must survive, and that no 주민등록번호 was invented |
| `P2-jeongbo-staff-seats` | minwon | `check_minwon` | the 접수·처리 기관 seats a citizen must not fill — the two rules P1 structurally cannot reach |

Every one of those checks declares `requires_module` (below), so a sandbox
without the module skips them with a reason instead of failing them. All three
tasks declare a `baseline`, because both checkers declare `wants: [baseline]`.

`P1`'s minwon checks are worth one note: the prompt supplies no 주민등록번호 and
the check deliberately passes **no** `--fill-map`, so any identity-number-shaped
value in the artifact is undeclared and `identity_value_invented` fires. That
turns "절대 임의 생성하지 않는다" from a judgment line into a machine check.

`P2` exists because a rule that is always `skipped` is not covered. 주민등록표
등초본 교부 신청서 has **no 접수 block at all**, so a `check_minwon` run over P1's
artifact records `staff_seat_filled: seat_absent` and neither staff rule ever
executes. 정보공개 청구서 carries three shaded 접수번호/접수일/처리기간 cells, a
four-cell 접수증 block, and the form's own
`※ 색상이 어두운 칸은 신청인(대리인)이 작성하지 않습니다` declaration — seven
recognized staff seats across **both** recognizers (label and shaded). P2's last
two checks pin that down without needing a filter expression: the rule names must
be *absent* from the verdict (present only when skipped or when they fire), while
`untouched` and `shaded` must be *present* (states only a recognized staff seat
is reported in).

Family ③ 학교 서식 has no task (corpus gap) and family ⑤ 기업 내부 문서 has no
task (documented capability boundary) — both are statements in
`docs/release-v0.16.0.md`, not omissions here.

Each task carries:

- `prompt` — what a user would actually type, in Korean, with concrete values
  so the rubric's "never invent unsupplied values" line is testable;
- `input_files` — repo-relative corpus paths, copied into the sandbox;
- `baseline` (optional) — the basename of the input that is the *blank form*,
  handed to checkers declaring `wants: [baseline]` (below) and available to
  task authors as `${BASELINE}`;
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

### `requires_module: NAME` — the per-module check gate

A machine check that calls into a distribution module's payload only means
something where that module is enabled. Declare the dependency on the check:

```yaml
  - id: gongmun_structure
    kind: python
    requires_module: gongmun
    argv: ["modules/gongmun/scripts/check_gongmun.py", "${WORK}/filled.hwpx", ...]
```

`check` asks the **sandbox's own** registry which modules are enabled (the
shipped `module_registry.py list`, not `install_report.json` — an enabled set
changed after `prepare` is still the truth) and records the answer in
`checks.json` as `enabled_modules`. When the required module is absent the
check is **skipped with a reason**, exactly as `blocked_on` behaves:

```json
{"id": "gongmun_structure", "status": "skipped",
 "requires_module": "gongmun",
 "reason": "requires_module: distribution module 'gongmun' is not enabled in this sandbox"}
```

Before this gate, a core-only sandbox *failed* those checks — a false finding
about the product, since a disabled module is a supported configuration
("absence is not failure", `modules/README.md`). The gate is the honest form of
that, and it does not soften anything: skipped is not passed, in `counts`, in
`check`'s exit code, or in the scorecard.

### `wants: [baseline]` — the harness supplies the blank form

Some checkers have rules that only exist when they are also given the **blank
form** the artifact came from. gongmun's `seat_emptied`, `seal_slot_removed`,
`dumun_label_missing` and `rank_not_in_pack` are all of that shape: without
`--baseline` they report `skipped: no_baseline` and the checker still exits 0.
Correct, and a trap — the task author had to *know*, and a task that forgot got
a thinner verdict that read as a pass.

minwon makes the point harder: **ten** of `check_minwon`'s thirteen structural
rules are
preservation rules ("was this destroyed?"), and that question is only decidable
against the form the artifact came from. A `P1` run without a baseline would
report exit 0 having decided almost nothing. The one rule deliberately *not*
gated is the privacy rule `identity_value_invented` — a fabricated identity
number is a finding on its own evidence and must never depend on an input the
caller can forget.

A checker declares the need in its `module.yaml`
(`modules/README.md` §`checkers[].wants`):

```yaml
provides:
  checkers:
    - {name: check_gongmun, script: scripts/check_gongmun.py, wants: [baseline]}
```

and a task declares the form:

```yaml
input_files:
  - tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx
baseline: gianmun-byeolji-1ho.hwpx    # a basename from input_files
```

`task` records the copied sandbox path as `baseline` in `task.json` and exposes
it as `${BASELINE}`. For every `python` check, `check` resolves `argv[0]`
**by path** against the sandbox registry's checker list — never by name or
filename convention — and if that checker declares `wants: [baseline]`:

| situation | what `check` does | recorded |
|---|---|---|
| task declares a baseline, not present in argv | appends `--baseline <path>` | `"baseline": "supplied-by-harness"` |
| the baseline path is already in argv — an explicit `--baseline`, or the check deliberately runs the checker **on** the blank form (a document is never its own baseline) | nothing | `"baseline": "already-in-argv"` |
| task declares **no** baseline | **skips the check with a reason** | `status: "skipped"` |

That last row is the point. Running anyway would produce exit 0 from a verdict
whose baseline rules had all self-skipped — a silent pass. Skipping says so out
loud, and (like `requires_module`) counts as a skip, never a pass.

A checker that declares no `wants` is untouched: its argv is exactly what the
task author wrote.

## 7. Recipes

Build bundles, then a full clean-room install:

```sh
python scripts/package_module.py --module core    --out dist
python scripts/package_module.py --module report  --out dist
python scripts/package_module.py --module style   --out dist
python scripts/package_module.py --module gongmun --out dist

python evals/cleanroom.py prepare \
    --bundle dist/rigorloom-core-0.16.0.zip \
    --bundle dist/rigorloom-report-0.16.0.zip \
    --bundle dist/rigorloom-style-0.16.0.zip \
    --bundle dist/rigorloom-gongmun-0.16.0.zip \
    --root /tmp/rigorloom-cleanroom
```

No `--allow-gap` — a full bundle set has none. The run installs the router
skill into `<root>/skills/rigorloom-hwp/` with each enabled module's fragment
merged into `SKILL.md`.

Core-only ("absence is not failure") install:

```sh
python evals/cleanroom.py prepare --bundle dist/rigorloom-core-0.16.0.zip \
    --root /tmp/rigorloom-core-only --enable none \
    --allow-gap no_module_bundles
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
