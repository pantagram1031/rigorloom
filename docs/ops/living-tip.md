# Living product tip

Status snapshot only. **Rematch freeze: ON.** No `main` merge.

**Updated:** 2026-09-08 ~10:10 KST

## Current tip

| Field | Value |
| --- | --- |
| Living product tip | draft [PR #361](https://github.com/pantagram1031/rigorloom/pull/361) |
| SHA | `718a253bd3c35bc620c02e7e54b1deeaf50a77f9` |
| Branch | `cursor/tip-stack-fe-state-harden-3ebe` |
| What it is | Tip-stack FE state harden ([#358](https://github.com/pantagram1031/rigorloom/pull/358)+[#359](https://github.com/pantagram1031/rigorloom/pull/359)+[#360](https://github.com/pantagram1031/rigorloom/pull/360)) onto epoch desktop [#356](https://github.com/pantagram1031/rigorloom/pull/356) |
| `main` | **not merged** (`origin/main` remains `a635289dd054341b882c8e8b3c262a7f538efa5f`) |

## Ancestor

Prior living tip **[PR #356](https://github.com/pantagram1031/rigorloom/pull/356)** @
`e927195baf5932c8d6f532b9d79bc65e5b71fea9`
(`cursor/epoch-desktop-onto-355-ba53`) **is an ancestor** of #361.

Prior tip **[PR #355](https://github.com/pantagram1031/rigorloom/pull/355)** @
`99ad234cc2af4e87da54ec4d3151e62c44c424d4` remains an ancestor of #356.

Unique commits on #361 after #356 (oldest → newest):

1. `3fa5653` — `fix(desktop): unify draft ownership across views`
2. `9512e6e` — `fix(desktop): distinguish adoption errors from supersession`
3. `6509909` — `fix(desktop): fence stale approval completions`
4. `a56b7fe` — `fix(desktop): preserve agent drafts across view switches`
5. `e9e5de8` — `test(desktop): collect composer view-state regressions`
6. `6ec917d` — `fix(desktop): fence stale review and apply results`
7. `b8379f4` — `test(desktop): load exported actions in race harness`
8. `718a253` — `merge(desktop): unify #360 draft ownership onto #358+#359`

Source drafts #358 / #359 / #360 stay open. They are not the living tip.

## CI on this tip

| Run | SHA | Result |
| --- | --- | --- |
| [34155334389](https://github.com/pantagram1031/rigorloom/actions/runs/34155334389) | `e927195baf5932c8d6f532b9d79bc65e5b71fea9` (#356) | **success** (ancestor product tip) |
| [34170712826](https://github.com/pantagram1031/rigorloom/actions/runs/34170712826) | `718a253bd3c35bc620c02e7e54b1deeaf50a77f9` (#361) | **ALL PASS** (render-smoke + core/all ubuntu+windows) |

Promotion of the living tip to #361 @ `718a253` is this green run, not a docs SHA.

Docs-only snapshot [PR #357](https://github.com/pantagram1031/rigorloom/pull/357) (`cursor/living-tip-status-356-4ce5` @ `4fac8a7b`) recorded the previous #356 tip. It is **not** the product tip. This file restacks that ops snapshot onto #361. Do not pin this docs PR's own HEAD as the living product SHA.

- Prior #357 tip `b69eb827b8f2c50ed3310b007e21a4e1ced40b6b` — CI **ALL PASS** run [34156949995](https://github.com/pantagram1031/rigorloom/actions/runs/34156949995)
- `84bead9348a48cf100cc337d12d29a841dafe16c` (Card5 HASH fold; docs/ops-only vs `b69eb827`) — all-modules ubuntu **FAILED** run [34159193388](https://github.com/pantagram1031/rigorloom/actions/runs/34159193388) on inherited flake `pipeline/tests/test_diagnostic_candidate_core.py::test_run_child_capture_cleans_ordinary_grandchild_cross_platform` (`assert not _pid_is_live`). Other four jobs passed. Not docs-contract drift.
- #357 HEAD `4fac8a7bd26377adfda409819173cd3778e28cb2` — CI **ALL PASS** run [34160494945](https://github.com/pantagram1031/rigorloom/actions/runs/34160494945) after the grandchild-death poll.

## Card 5 HASH on the ancestor tip

Script-owned **hash-only** evidence exists for ancestor #356 @ `e927195b` under
`F:\RigorloomQA\card5-e927195b\evidence\`. It was **not re-collected** on
#361 @ `718a253` (FE state-harden only; install artifacts unchanged by this
stack).

| Artifact | sha256 |
| --- | --- |
| EXE | `6df95dc3564f7e5ccebc5db44a27cbf8acb2822cbbdd7b1132cc0482889635fc` |
| sidecar | `1346fe07bcf6fc7e9d55cb29b4c9f58926073859215f669f81aa1bd4a91a313b` |
| NSIS | `3bbc5b820c7387b0fcc9fa7aaac4bec22cc182f9b339ae1d3635672785b15ffe` |

- `installCandidatePass=true` (hash-only)
- `card5Pass=false`
- `guiImeClaimed=false`
- status `HASHED_BUILD_ARTIFACTS` / verify **PASS for hashes only**

Prior #355 hash evidence @ `99ad234` (`F:\RigorloomQA\card5-99ad234\evidence\`) is ancestor record only.

## Holds

- Card 4 Korean IME remains **NOT_RUN / hold**. This snapshot does not claim IME PASS.
- Card 5 GUI remains **NOT_RUN / hold**. The #356 hashes above are hashes only (`card5Pass=false`, `guiImeClaimed=false`). Do not treat HASH verify as GUI PASS.
- Rematch / own_render / Claude renderer research pins are frozen and are not modified here.

See [release-train-status.md](release-train-status.md) and [loom-ops-status.md](loom-ops-status.md) for the rest of the card board.
