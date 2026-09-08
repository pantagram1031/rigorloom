# Living product tip

Status snapshot only. **Rematch freeze: ON.** No `main` merge.

**Updated:** 2026-09-08 ~13:30 KST

## Current tip

| Field | Value |
| --- | --- |
| Living product tip | draft [PR #365](https://github.com/pantagram1031/rigorloom/pull/365) |
| SHA | `961ca3a8fb1492270765c9a2e529ebaba53571d3` |
| Branch | `cursor/tip-stack-363-364-9b1f` |
| What it is | Tip-stack FE leftover harden ([#363](https://github.com/pantagram1031/rigorloom/pull/363)+[#364](https://github.com/pantagram1031/rigorloom/pull/364)) onto FE tip-stack [#361](https://github.com/pantagram1031/rigorloom/pull/361) |
| `main` | **not merged** (`origin/main` remains `a635289dd054341b882c8e8b3c262a7f538efa5f`) |

## Ancestor

Prior living tip **[PR #361](https://github.com/pantagram1031/rigorloom/pull/361)** @
`718a253bd3c35bc620c02e7e54b1deeaf50a77f9`
(`cursor/tip-stack-fe-state-harden-3ebe`) **is an ancestor** of #365.

Prior tip **[PR #356](https://github.com/pantagram1031/rigorloom/pull/356)** @
`e927195baf5932c8d6f532b9d79bc65e5b71fea9`
(`cursor/epoch-desktop-onto-355-ba53`) remains an ancestor of #361.

Prior tip **[PR #355](https://github.com/pantagram1031/rigorloom/pull/355)** @
`99ad234cc2af4e87da54ec4d3151e62c44c424d4` remains an ancestor of #356.

Unique commits on #365 after #361 (oldest → newest):

1. `88d3373` — `fix(desktop): fence stale head selections` ([#363](https://github.com/pantagram1031/rigorloom/pull/363))
2. `961ca3a` — `fix(desktop): compose DraftFence from DraftOwner` ([#364](https://github.com/pantagram1031/rigorloom/pull/364) cherry-pick)

Source drafts #363 / #364 stay open. They are not the living tip. Source
drafts #358 / #359 / #360 remain open on the #361 ancestor stack.

## CI on this tip

| Run | SHA | Result |
| --- | --- | --- |
| [34155334389](https://github.com/pantagram1031/rigorloom/actions/runs/34155334389) | `e927195baf5932c8d6f532b9d79bc65e5b71fea9` (#356) | **success** (ancestor product tip) |
| [34170712826](https://github.com/pantagram1031/rigorloom/actions/runs/34170712826) | `718a253bd3c35bc620c02e7e54b1deeaf50a77f9` (#361) | **ALL PASS** (ancestor product tip) |
| [34185519845](https://github.com/pantagram1031/rigorloom/actions/runs/34185519845) | `961ca3a8fb1492270765c9a2e529ebaba53571d3` (#365) | **ALL PASS** (render-smoke + core/all ubuntu+windows; 5 jobs; ~11m54s) |

Promotion of the living tip to #365 @ `961ca3a8` is this green run, not a docs SHA.

Docs-only snapshot [PR #362](https://github.com/pantagram1031/rigorloom/pull/362) (`cursor/living-tip-status-361-be7b` @ `244d7a35`) recorded the previous #361 tip. It is **not** the product tip. This file restacks that ops snapshot onto #365. Do not pin this docs PR's own HEAD as the living product SHA.

- #362 HEAD `244d7a3515d9a4b176cda22110412f1fabfca8c0` — CI **ALL PASS** run [34175571726](https://github.com/pantagram1031/rigorloom/actions/runs/34175571726)
- Prior #357 HEAD `4fac8a7bd26377adfda409819173cd3778e28cb2` — CI **ALL PASS** run [34160494945](https://github.com/pantagram1031/rigorloom/actions/runs/34160494945) after the grandchild-death poll
- `84bead9348a48cf100cc337d12d29a841dafe16c` (Card5 HASH fold; docs/ops-only vs `b69eb827`) — all-modules ubuntu **FAILED** run [34159193388](https://github.com/pantagram1031/rigorloom/actions/runs/34159193388) on inherited flake `pipeline/tests/test_diagnostic_candidate_core.py::test_run_child_capture_cleans_ordinary_grandchild_cross_platform` (`assert not _pid_is_live`). Other four jobs passed. Not docs-contract drift.

## Card 5 HASH on the ancestor tip

Script-owned **hash-only** evidence exists for ancestor #356 @ `e927195b` under
`F:\RigorloomQA\card5-e927195b\evidence\`. It was **not re-collected** on
#365 @ `961ca3a8` (FE leftover harden only; install artifacts unchanged by this
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
