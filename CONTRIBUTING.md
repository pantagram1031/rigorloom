# Contributing to Rigorloom

Thanks for considering a contribution. This document covers dev setup, the
review discipline this repo follows, and what a PR is expected to include.

## Dev setup

```sh
git clone https://github.com/pantagram1031/rigorloom.git
cd rigorloom
python3 scripts/bootstrap.py
python -m pytest -q
```

Run `pytest` with no paths. `pyproject.toml`'s `testpaths` already resolves to
`tests`, `pipeline/tests`, `engine/tests` and `modules/*/tests`, and naming a
subset runs strictly less than CI does — a green `pytest pipeline/tests tests`
can sit on top of a broken engine or a broken distribution module.

`bootstrap.py` uses only the standard library and proves a fresh clone is
wired correctly (interpreter check, private profile setup, an end-to-end
smoke test). No Hancom, no Windows, and no model account are needed for this
step or for the test suite. Optional extras (`docx`, `studio`, `hwp`) are
listed with install hints at the end of `bootstrap.py`'s output; only install
what you need for the area you're changing.

Legs that need something this machine does not have — Hancom, a rasterizer, a
model account — **skip with a reason** rather than failing or quietly passing.
Run with `-rs` to read those reasons; CI runs with `-rs` for the same purpose,
so a public log can tell "skipped" from "ran".

## Review discipline

This repo treats its gates as the product, not scaffolding around it. That
shapes how changes get reviewed:

- **Adversarial review before merge.** Changes to gates, checkers, or the
  stage machine are expected to be reviewed looking for ways the new logic
  could be bypassed, fail open, or produce a false pass — not just whether it
  works on the happy path. Several changelog entries exist specifically
  because an adversarial pass found a fail-open or false-block bug after the
  initial implementation (see [CHANGELOG.md](CHANGELOG.md)).
- **Deterministic-gate philosophy.** Every gate in this pipeline is expected
  to resolve one of three ways:
  - A **provable break** (a fabricated citation, a mutated form, a missing
    required file) is **HARD** — it fails the gate, unconditionally.
  - An **uncertain** case (a reference that can't be verified offline, a
    render path with unmeasured fidelity) is **WARN** or an explicit,
    logged exception — never silently accepted as if it were verified.
  - Nothing passes silently. A gate's verdict is always visible in its
    output (exit code, JSON verdict, or both), never inferred from the
    absence of an error.
- **A false-blocking gate is worse than none.** A gate that HARD-fails valid
  work erodes trust and gets bypassed or disabled — which is worse than not
  having the check at all. If you're adding or tightening a HARD condition,
  show it doesn't fire on legitimate content (a test fixture, an existing
  workspace, or both), not just that it fires on the bad case it targets.

## The rules the program runs on

These are not aspirations; they are the rules every slice in this repository
has been held to, and a PR that breaks one gets sent back regardless of
whether the code works.

- **Honest states over silent fallbacks.** When something cannot be done, the
  answer is a named refusal carrying its reason — `needs_hancom`,
  `rasterizer_missing`, `com_busy`, `skipped` — never a substitute quietly
  swapped in. A page that could not be rendered must draw as a refusal, not as
  a blank page; a checker that could not run must report `skipped`, not
  `passed`. Most of the bugs this repo has shipped and then fixed were a
  fallback that made an absence look like a success.
- **Measured numbers over adjectives.** "Faster", "more accurate", "mostly
  works" are not claims this repo makes. Say 73 of 473, 264 ms against
  1394 ms, 552 collected — and say where the number came from, so a reader can
  re-run it. `docs/support-matrix.md` is generated from evidence pointers and
  its generator **refuses** a `supported` row whose pointers do not resolve;
  write prose to the same standard.
- **The corpus is a measuring stick, never a training target.** The blank
  forms under `tests/corpus/forms/` exist to measure what the engine can do.
  Tuning a heuristic until the corpus number goes up, without a mechanism that
  explains the gain and holds on a form the change never saw, is overfitting a
  ruler. When a gain cannot be checked as tightly as the code it replaces, it
  does not go in — see `docs/runtime-protocol-v0.md` §12.6 for a documented
  case where four extra seats were measured and then rejected on exactly that
  ground.
- **Public spec only, never Hancom binaries.** The HWP/HWPX support in this
  repository is built from the Korean public standard — OWPML / KS X 6101 —
  and from Hancom's own published model and COM API. Do not disassemble,
  decompile or otherwise reverse-engineer Hancom Office binaries or file
  formats, and do not contribute anything derived from doing so. Where Hancom
  is used, it is used as an installed application through its documented
  automation surface, and the code says so.
- **Stacked draft PRs.** Work lands as a chain of small draft PRs, each one
  based on the last, each one passing the gates below on its own. A branch
  that only makes sense once three more land is not reviewable; split it.
  Nothing merges without maintainer authorization.

## The gates a slice must pass

Every one of these runs in CI (`.github/workflows/ci.yml`) and every one can
be run locally first.

1. **Full suite green.** `python -m pytest -q` — the whole thing, both with
   distribution modules enabled and with none enabled
   (`python pipeline/scripts/module_registry.py write-enabled --all` /
   `--none`). CI runs both points on Linux and Windows because "absence is not
   failure" is part of the module contract.
2. **Privacy scan HARD=0, on a clean archive.** See the next section; the
   working-tree form is a convenience, the archive form is the ruling.
3. **The desktop gate, for anything under `desktop/`.** In this order:
   `npm ci`, `npx tsc --noEmit`, `desktop/sidecar/build.ps1`,
   `cargo test --release`, `npm run tauri build`, then
   `desktop/scripts/smoke.ps1`.

   The freeze comes before cargo because `tauri.conf.json` bundles
   `resources/rigorloomd/**/*`; on a fresh checkout that directory does not
   exist and `tauri-build` fails the build script on the unmatched glob, so
   cargo cannot even compile until the sidecar is frozen. `build.ps1` is a
   gate in its own right: it launches the frozen binary in both of its roles
   and refuses the build unless the server answers `initialize` and advertises
   the methods the shell actually calls.

   The smoke is the desktop gate. Eleven launches of the built executable
   driving a real window, with the assertions living in the app: a desktop
   change that compiles and type-checks has not been tested.

## PR expectations

- **Tests for every fix.** A bug fix without a regression test that would
  have caught it is not considered complete. New checkers or gate logic need
  both a positive (passes on good input) and negative (HARD/WARN on bad
  input) test case.
- **Full suite green.** `python -m pytest -q` must pass before requesting
  review.
- **Privacy scan clean, on a clean archive.** The scanner must report 0 HARD
  findings, and the tree it rules on is the tree a stranger would clone — not
  your working tree, which carries `node_modules/`, build output, virtualenvs
  and `workspaces/`, and therefore scans dirty:

  ```sh
  # the ruling form, and what CI runs
  d="$(mktemp -d)" && git archive HEAD | tar -x -C "$d"
  python pipeline/scripts/privacy_scan.py "$d"

  # the convenience form, while iterating
  python pipeline/scripts/privacy_scan.py .
  ```

  Read the **summary line**, not just the exit code:
  `summary: HARD=0 WARN=43 TOTAL=43`. A `-- SCAN INCOMPLETE` suffix means some
  paths could not be read, so the coverage is not total even though every
  finding it did make still holds; CI treats that as a failure.

  Binary corpus templates under `tests/corpus/forms/` pass only through the
  sha256-pinned allowlist auto-detected at `tests/corpus/forms/manifest.json`
  (`--binary-allowlist` to point elsewhere). Adding or changing a corpus file
  means re-pinning its hash in that manifest; allowlisted files are still
  content-scanned for PII, and bundles never apply the allowlist.

- **Docs updated.** If behavior, a gate contract, or a CLI flag changes,
  update the relevant doc under `docs/` (and `CHANGELOG.md`) in the same PR.

## Code style

Match the conventions of the file you're editing rather than introducing a
new style. In general:

- Standard-library-only for anything in the pipeline kernel path; optional
  dependencies belong behind the extras declared in `pyproject.toml`.
- Scripts fail closed and print an explicit, actionable error rather than
  guessing or silently defaulting.
- No personal data, credentials, private forms, or generated reports in
  commits — see [AGENTS.md](AGENTS.md) for what's intentionally excluded
  from this repository.

## Where to start

This project keeps **honest-gap registries** — written lists of what each
component cannot do yet, with the reason, kept current because a claim in this
repo has to survive its own evidence. They exist for review discipline, and
they double as the contribution funnel: every entry is a known, scoped,
already-diagnosed piece of work, which is exactly what a good first issue is
made of. Pick one, open an issue naming it, and say which entry you mean.

- [`docs/runtime-protocol-v0.md` §12.6 — "Still GAP here"](docs/runtime-protocol-v0.md):
  why 400 of 473 corpus fill regions still get no seat, broken down by cause
  (148 in tables with no anchor anywhere, truncated previews that cannot
  anchor, unruled forms that correctly place nothing, walks that stop at a gap
  or a merged cell, per-page alignment, sub-line addressing). The first block
  is named there as where the next real gain is.
- [`docs/runtime-protocol-v0.md` §13.7 — "Still GAP here"](docs/runtime-protocol-v0.md):
  distribution-module checkers on the wire — twelve of eighteen skipped for
  want of a workspace session kind, no wire surface for pack/vocabulary/mode,
  containment bounded rather than contained.
- [`desktop/README.md`](desktop/README.md) — "Runtime gaps", "Packaging gaps"
  and "Agent Host gaps": things true of the artifact the desktop build
  produces, numbered, with the closed ones struck through so you can see what
  a fix looks like when it lands.
- [`docs/support-matrix.md`](docs/support-matrix.md): the per-capability
  table. A row that is not `supported` is a gap with an evidence pointer
  attached.

Fixing an entry means the entry gets edited in the same PR. A gap list that
still lists what you closed is as wrong as one that omits what is open.

## Design docs

Read the doc for the layer you are touching before the code:

- [`docs/architecture.md`](docs/architecture.md) — the pipeline kernel, the
  stage machine, the contracts between them.
- [`docs/golden-path.md`](docs/golden-path.md) — where a change belongs in the
  stage graph, and what each gate reads.
- [`docs/runtime-protocol-v0.md`](docs/runtime-protocol-v0.md) — the Runtime
  wire protocol, its authority model, and the gap registries above.
- [`docs/desktop-architecture.md`](docs/desktop-architecture.md) and
  [`desktop/README.md`](desktop/README.md) — the Tauri shell, the packaged
  sidecar, and the evidence each slice produced.
- [`agenthost/README.md`](agenthost/README.md) — the agent boundary: what the
  model is allowed to call, and why the approve button is not in its registry.
- [`docs/design-decisions.md`](docs/design-decisions.md) and
  [`docs/lessons-learned.md`](docs/lessons-learned.md) — why things are the
  way they are, including several that were tried the other way first.

## Questions

Open an issue using the bug report, feature request or agent behavior template
under [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/), or start with
[docs/golden-path.md](docs/golden-path.md) if you're not sure where a change
belongs in the stage graph. For anything that looks like an authority-boundary
break — an agent reaching an approval or applying a plan without a human —
follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
