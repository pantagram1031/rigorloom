# Loom ops status

Living ops snapshot for the product tip stack. Loom / Ledger also append
GitHub [#343](https://github.com/pantagram1031/rigorloom/issues/343).
**Rematch freeze: ON.** Do not invent metrics. Scripts own PASS.

This file supersedes the 2026-09-07 12:41 KST research snapshot from
[PR #342](https://github.com/pantagram1031/rigorloom/pull/342)
(`docs/research/loom-ops-status.md` on that branch). It does not rewrite
product PR #356.

**Updated:** 2026-09-08 ~05:22 KST

---

## Snapshot

Living product tip: draft **[PR #356](https://github.com/pantagram1031/rigorloom/pull/356)** @
`e927195baf5932c8d6f532b9d79bc65e5b71fea9`
(epoch desktop restack on prior #355 docs tip).

Prior tip **[PR #355](https://github.com/pantagram1031/rigorloom/pull/355)** @
`99ad234cc2af4e87da54ec4d3151e62c44c424d4` is an ancestor.

`main` is **not** merged.

---

## Product tip stack

```
#350  tip-stack #344+#346+#348+#349                         60e8ccd
  └─► #351 / #352  rangeText + draft-fence (empty-diff)     already ancestors
        └─► #353  card5 install-hash harness                fbc6751e
              └─► #354  QA harness + mock_approved          7341e45
                    └─► #355  docs #345 + lineage tie-break 99ad234   ← ancestor
                          └─► #356  epoch desktop restack   e927195b  ← LIVING TIP
```

| PR | Role | Tip SHA | Notes |
| ---: | --- | --- | --- |
| #350 | green tip-stack | `60e8ccdedb6fef8f9b6d0d4341c62c855ffc8305` | Card 3 Win evidence recorded here |
| #353 | Card 5 hash harness | `fbc6751ef27cd465c8b3212f4a01e02390f51d15` | superseded as living tip; hash evidence later re-collected on #355 |
| #354 | QA + `mock_approved` | `7341e45c61c444fc7e5ee6e8244bad8080fa3cf4` | ancestor of #355 |
| #355 | docs + lineage fix | `99ad234cc2af4e87da54ec4d3151e62c44c424d4` | **ancestor of #356**; prior Card 5 hash PASS (superseded for living tip) |
| #356 | epoch desktop onto #355 | `e927195baf5932c8d6f532b9d79bc65e5b71fea9` | **living product tip**; CI green run `34155334389`; Card 5 HASH now on this SHA |
| #357 | docs-only ops snapshot | `b69eb827b8f2c50ed3310b007e21a4e1ced40b6b` | **not** the product tip; CI ALL PASS run `34156949995` |

---

## Card board

| Card | Previously recorded evidence | Status now |
| --- | --- | --- |
| C1 — export safety | Windows force-quit matrix PASS×3 @ `4ded110c4509f2bb81ea459b522e211da166388d` (#348). dest sha256 `477f26e51aa5e62b3a3cc14a39f0cf2a15ee446e8db87328d752ba8f5718f91f`. Artifacts `F:\RigorloomQA\card1-export-safety\wt-4ded110c\qa\_artifacts\` (`card1-force-quit.json` sha256 `276916BF…`, `card1-matrix.json` sha256 `2EBEE183…`). | **as previously recorded** (script-owned). Not re-run on `e927195b`. |
| C2 — draft-fence | Product tests on the ancestor stack (#339 generation fence; #352 empty-diff already ancestor of #350). #356 adds `ownsDraft` (identity + session + head) on that fence. | **as previously recorded** (product tests). No Windows GUI PASS. |
| C3 — run-scoped edit | Windows pytest PASS @ `60e8ccd` (#350): 13 passed / 0 fail (`run_scoped` + `range_text` + `sequential_offset`). Worktree `F:\RigorloomQA\card3-win\wt-60e8ccd`; evidence `F:\RigorloomQA\card3-win\evidence-60e8ccd\`. | **as previously recorded** (script-owned). No GUI E2E. |
| C4 — Korean mixed E2E | Prep harness only (`qa/card4_prep.py` / #341 / #347). Fixture probe + manifest exist. | **NOT_RUN / hold**. No IME PASS. |
| C5 — install hash | Living-tip **hash-only** PASS @ `e927195b` (#356): `installCandidatePass=true`, `card5Pass=false`, `guiImeClaimed=false`; status `HASHED_BUILD_ARTIFACTS` / verify PASS for hashes only. EXE `6df95dc3564f7e5ccebc5db44a27cbf8acb2822cbbdd7b1132cc0482889635fc`; sidecar `1346fe07bcf6fc7e9d55cb29b4c9f58926073859215f669f81aa1bd4a91a313b`; NSIS `3bbc5b820c7387b0fcc9fa7aaac4bec22cc182f9b339ae1d3635672785b15ffe`. Evidence `F:\RigorloomQA\card5-e927195b\evidence\`. Prior #355 hashes @ `99ad234` (`7c8be787…` / `af9530c2…` / `b518bd15…`, `F:\RigorloomQA\card5-99ad234\evidence\`) are ancestor record only. | **HASH verify PASS** (hashes only). **GUI NOT_RUN / hold**. |

---

## CI

| Run | SHA | Result |
| --- | --- | --- |
| [34152302855](https://github.com/pantagram1031/rigorloom/actions/runs/34152302855) | `4a4991666b0c92d9e4a89e57a468525d220d4358` (#356 hang) | **cancelled** (hung windows-latest pytest) |
| [34155334389](https://github.com/pantagram1031/rigorloom/actions/runs/34155334389) | `e927195baf5932c8d6f532b9d79bc65e5b71fea9` (#356) | **success** — living-tip promotion evidence |
| [34156949995](https://github.com/pantagram1031/rigorloom/actions/runs/34156949995) | `b69eb827b8f2c50ed3310b007e21a4e1ced40b6b` (#357 docs) | **ALL PASS** (render-smoke + core/all ubuntu+windows) |

---

## Workers / freeze

| Worker | State |
| --- | --- |
| Claude rematch / renderer | **IDLE** — rematch freeze ON |
| Codex epoch | product advances restacked via #356; epoch head `5b57005` is not the living tip |
| Windows | Card 5 HASH recorded on `e927195b` (hashes only; `card5Pass=false`). Card 4 IME still needs Hayul foreground |

Standing:

- Rematch freeze **ON**. No rematch / own_render / conveyor / LayoutSnapshot / IoU pin edits.
- No `main` merge.
- No Composer.
- Scripts own PASS. No invented Card 4 IME PASS. No invented Card 5 GUI PASS.

---

## Next queue

1. Card 4 Korean IME after operator foreground — remains **NOT_RUN / hold**.
2. Card 5 GUI remains **NOT_RUN / hold** (`card5Pass=false`). Do not treat HASH verify as GUI PASS.
3. Keep the living product tip at #356 @ `e927195b`. #357 stays docs-only. Do not merge `main`.

Pointers: [living-tip.md](living-tip.md), [release-train-status.md](release-train-status.md).
