# Stage 8 — Release readiness

Status: IN PROGRESS 2026-09-18. Owner: Fable. Pushing, PR closes and release publishing stay with the user.

## Checklist
- [ ] Version bump (pyproject, desktop/package.json, tauri.conf.json) and CHANGELOG release notes from the
      Unreleased section (Stage 1–6 items).
- [x] NSIS installer smoke: install the bundle from CARGO_TARGET_DIR/release/bundle/nsis into a scratch prefix,
      launch, open a corpus form, one xml edit through the GUI, uninstall.
- [x] 90-second desktop demo GIF under docs/demo (home → open → agent plan → hunk review → approve → receipt).
- [x] PR description at docs/plans/pr-stage1.md (drafted 2026-09-18 02:35; refresh numbers before opening): what changed by stage, verification evidence (tests, smokes,
      reproduced reports), what is honest-not-proven, follow-ups.
- [ ] Merge checklist: CI expectations (Node 22, fonts, wheel toolchain), branch protection, the 18 contained PRs
      to close, worktrees to prune.

## Ledger
| When | What | Result |
|---|---|---|
| 2026-09-18 05:30 | R8a sidecar rebuild (`desktop/sidecar/build.ps1`) then `npx tauri build` NSIS | sidecar published `desktop/src-tauri/resources/rigorloomd` 91.4 MiB, serve-role checks ok; exe `F:\rigorloom-build\cargo-target\release\rigorloom-desktop.exe` 8.57 MiB; NSIS `F:\rigorloom-build\cargo-target\release\bundle\nsis\Rigorloom_0.1.0_x64-setup.exe` 32.6 MiB. Second build after fill RPC timeout 180→1800 s. |
| 2026-09-18 04:43 | default built-app smoke | SMOKE PASS **570/0** (open 57, reattach 10, edit 83, agent 21, page 17, own 91, own-reattach 3, overlay 78, undo 60, packs 34, composer 31, settings 28, chrome 33, chrome-reattach 5, bound 19). First pass was 570/0 in-app plus an orphan-sidecar harness flake; rerun clean. |
| 2026-09-18 04:54 | opt-in `agent-live` vs `http://127.0.0.1:8766/v1` | 13/1. Bridge up (models list). Turn ran 280 s then `provider_timeout` on the third router request (180 s). |
| 2026-09-18 05:28 | opt-in `pipeline-native` on `work/auralab-fill-p3` | 11/0. Fill card: **gappy**, `converged=false`, proofGrade none (layout_qa fail / verify_format warn). Poster card: **pass**. Shots: `docs/demo/desktop/native-fill-result.png`, `native-poster-result.png`. Packaged sidecar has no pyhwpx; harness used child Python 3.11 + `RIGORLOOM_FILL_HANCOM=yes`. |
| 2026-09-18 05:30 | NSIS installer smoke (`desktop/scripts/installer-smoke.ps1`) | `/S /D=<scratch>` PASS; outside-prefix Start Menu/uninstall key none observed; `smoke.ps1 -Only edit` 83/0; silent uninstall PASS. |
| 2026-09-18 04:30 | demo GIF via `capture.mjs gif` + Pillow | `docs/demo/desktop/demo.gif` 6 frames, 9.0 s, 373 408 B (0.36 MiB) at 1280×800. |
| 2026-09-18 04:31 | `cd desktop && npm test` | 225 passed, 0 failed. |
