# Stage 8 — Release readiness

Status: QUEUED 2026-09-17. Owner: Fable. Pushing, PR closes and release publishing stay with the user.

## Checklist
- [ ] Version bump (pyproject, desktop/package.json, tauri.conf.json) and CHANGELOG release notes from the
      Unreleased section (Stage 1–6 items).
- [ ] NSIS installer smoke: install the bundle from CARGO_TARGET_DIR/release/bundle/nsis into a scratch prefix,
      launch, open a corpus form, one xml edit through the GUI, uninstall.
- [ ] 90-second desktop demo GIF under docs/demo (home → open → agent plan → hunk review → approve → receipt).
- [ ] PR description at docs/plans/pr-stage1.md: what changed by stage, verification evidence (tests, smokes,
      reproduced reports), what is honest-not-proven, follow-ups.
- [ ] Merge checklist: CI expectations (Node 22, fonts, wheel toolchain), branch protection, the 18 contained PRs
      to close, worktrees to prune.

## Ledger
| When | What | Result |
|---|---|---|
