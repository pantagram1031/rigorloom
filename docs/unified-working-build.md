# Unified working build

Branch: `codex/unified-working-build`.

The integration combines product stack #365 (`961ca3a8`) with the eight local
frontend commits through `34565bc`. Both lines are ancestors of the merge;
composer ownership, shared review controls, honest check states, subscription
ownership, approval/recovery binding, and queue/head freshness remain together.
Renderer research branches and certification work remain outside this integration.

## Verification and build

Use Node 22, Python 3.12, Rust with the Windows MSVC toolchain, and the locked
frontend dependencies. Run from the repository root:

```powershell
npm ci --prefix desktop
npm --prefix desktop run test:headless
python -m pytest -q tests/test_runtime_apply_retry.py
powershell -NoProfile -ExecutionPolicy Bypass -File desktop/sidecar/build.ps1
npm --prefix desktop run tauri -- build
```

The sidecar must be frozen before Tauri: it bundles the current Runtime, engine,
agent host, module declarations, PyMuPDF and Pillow. Keep private module enablement
outside the checkout (`RIGORLOOM_MODULES_ENABLED`); do not bundle a local
`modules/enabled.yaml`. `CARGO_TARGET_DIR` can place large Rust artifacts on a
separate drive. Run filesystem/hardlink tests with TEMP on NTFS.

To smoke an executable built outside the default Cargo target directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File desktop/scripts/smoke.ps1 -Executable <absolute-executable> -KeepRoot
```

This uses a separate app data root under `desktop/scripts/_run`. Settings smoke
writes a fake credential and should be selected deliberately. Scripted smoke is
not evidence of manual Korean IME or complete visual document acceptance.

## Retry behavior

`plan/apply` reserves one run in `<runtime-root>/apply-attempts` under an OS lock.
A repeated request, including after a server restart, re-verifies the original
receipt and candidate bytes and returns that candidate. A competing host receives
`apply_in_progress`. A handled refusal may retry only after its private run and
work directories were removed. A process interruption without a verified receipt
returns `apply_outcome_unknown` and cannot rerun the plan automatically.

Receipt publication is the commit point. A receipt published before the response
or plan-state save still recovers on retry. Existing pre-journal candidates are
also verified before replay. Multiple historical candidates, malformed journals,
and tampered artifacts are refused. Replay reconciles the plan state and unfinished completion events. Event delivery
is at least once on recovery, not an exactly-once log: a crash between an event
and the completion marker can repeat the event, so deduplicate by run ID. This covers process failures; it does not claim
power-loss durability or protection against manual deletion of runtime state.

CI installs frontend dependencies, runs all desktop behavioral regressions, builds
the frontend, and explicitly collects the QA suite in addition to the main tests.
Build/test success does not certify the renderer or establish Card4/Card5 acceptance.
