# Loom W0 Ops Board

Living document. Loom updates this file after each state change.
**Rematch freeze: ON.** Do not open new renderer/rematch PRs.

---

## Snapshot

**Date:** 2026-09-07 12:41 KST

---

## Product tip stack

```
#330  fix: bind overlay edits to displayed document revision
  └─► #333  feat: run-scoped edit (card 3)
        └─► #336  fix: dest-preserving export pair (card 1)
              └─► #339  feat: generation fence for in-flight setQueue (card 2)
                    └─► #340  fix: splice run edits into displayed text (finding 1 from #338)
                          ← PRODUCT TIP  02d8ffeb9f36
```

| PR | Title | CI | Status |
| ---: | --- | --- | --- |
| #330 | fix: bind overlay edits to displayed document revision | — | merged into stack |
| #333 | feat: run-scoped edit (card 3) | — | merged into stack |
| #336 | fix: dest-preserving export pair (card 1) | — | merged into stack |
| #338 | docs: independent review for cards 2-3 safety | CI PASS (all 5) | read-only review; no product code |
| #339 | feat: generation fence for in-flight setQueue (card 2) | CI FAIL (4/5) | base of #340; superseded by #340 tip |
| #340 | fix: splice run edits into displayed text | CI FAIL (4/5) | **PRODUCT TIP** — unmerged draft |
| #337 | feat(qa): QA unattended harness contract | CI PASS (all 5) | harness only, no card execution |
| #341 | feat(qa): card 4 E2E harness prep — fixture probe, evidence manifest, runbook (NOT RUN) | CI PASS (all 5) | prep only; card 4 itself NOT_RUN |

---

## Card board

| Card | What PASS requires | Code tip | Windows evidence | Status |
| --- | --- | --- | --- | --- |
| C1 — export safety | Existing bytes preserved; crash/receipt-hash regressions covered; outside-checkout install hash | #336 ships dest-preserving export pair; Rust harness (`desktop_export_safety_harness.rs`) present | CI FAIL — `windows_sys` crate missing in GH Actions; no real install hash | **NOT_RUN** (Rust compile blocked) |
| C2 — draft fence | Stale async must not clobber latest draft | #339 ships `bumpPlanGeneration` + `currentPlanGeneration` guard | `test_desktop_revision_coherence.py` present; no Windows install evidence | **NOT_RUN** (no install-candidate evidence) |
| C3 — run-scoped edit | Edit one plain-text run (incl. wrapped lines); selected run only in multi-run paragraph; revision/run/UTF-16 source-map | #340 ships `rangeText` splice fix; `run_map.ts` UTF-16 map; harness 5/5 local | 5 harness cases locally verified; no Windows install evidence; `multi_run` still refused at caret | **NOT_RUN** (no install-candidate evidence; multi-run gap open) |
| C4 — Korean mixed E2E | Real install; mixed formatting, long paragraphs, tables; edit→undo/redo→AI review→save→reopen. Not renderer score / mock-only | #341 adds fixture probe schema + runbook | CI PASS on #341 (prep only); card itself explicitly marked NOT RUN in PR title | **NOT_RUN** |
| C5 — install hash | Source / EXE / sidecar / installer SHA-256 verified outside the checkout | No PR addresses this | Absent; checkpoint 24 self-reports sidecar line unowned | **ABSENT** |

---

## Workers

| Worker | State | Notes |
| --- | --- | --- |
| Claude (Fable 5.1 / Sonnet 5) | Active — burns | Product desktop PRs (#330–#340), engine research, this audit |
| Codex | **BLOCKED_QUOTA** until ~2026-09-07 23:52 KST | No open Codex epoch PR on GitHub; only `docs/codex-preview-regression` (#191) |
| Cursor Cloud Agent (this run) | Active | Read-only fitness audit → docs PR #342 |

---

## Monitoring

| Channel | Mode | Interval |
| --- | --- | --- |
| GitHub PR hooks | Event-first | On push / CI complete / review |
| Quiet backup poll | 15-min | When no event received |

---

## Next queue

Ordered by dependency. Each item unlocks the next.

| # | Item | Blocks | Owner |
| --- | --- | --- | --- |
| 1 | **Audit go/park** — read fitness report (#342), decide which W0–W1 bullets to execute | All | Hayul |
| 2 | **CI tip-debt** — fix two blockers on #340: register `render-check` eval family; add `windows_sys` dep or feature-gate Rust harness | C1 Rust gate, C2/C3 evidence collection | Claude or mechanical |
| 3 | **Windows Run-Cards C1 / C5** — hash real install outside checkout; run C1 export-safety matrix on that install | C4 (needs hashed install) | Windows host + Claude |
| 4 | **C4 IME** — Korean mixed E2E on hashed install: mixed formatting, long paragraph, table; edit→undo/redo→AI review→save→reopen | C4 PASS | Windows host |
| 5 | **Codex resume** — pick up after quota restores (~23:52 KST); scope: multi-run caret refusal lift (card 3 gap) or C5 outside-hash tooling | C3 multi-run completion | Codex |

---

## Freeze log

| Date KST | Action |
| --- | --- |
| 2026-09-07 | Rematch freeze declared. No new renderer research / rematch / converge / checkpoint PRs. Renderer parked at #323 SHA `eda8f60a7f94`. |
| 2026-09-07 | Fitness audit report created (`agent-era-editor-fitness-20260907.md`, PR #342). |
