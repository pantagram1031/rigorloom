# Living product tip

Status snapshot only. **Rematch freeze: ON.** No `main` merge.

**Updated:** 2026-09-08 ~05:22 KST

## Current tip

| Field | Value |
| --- | --- |
| Living product tip | draft [PR #356](https://github.com/pantagram1031/rigorloom/pull/356) |
| SHA | `e927195baf5932c8d6f532b9d79bc65e5b71fea9` |
| Branch | `cursor/epoch-desktop-onto-355-ba53` |
| What it is | Epoch desktop restack on prior #355 docs tip |
| `main` | **not merged** (`origin/main` remains `a635289dd054341b882c8e8b3c262a7f538efa5f`) |

## Ancestor

Prior living tip **[PR #355](https://github.com/pantagram1031/rigorloom/pull/355)** @
`99ad234cc2af4e87da54ec4d3151e62c44c424d4`
(`cursor/docs-345-onto-354-a5a3`) **is an ancestor** of #356.

Unique commits on #356 after that ancestor (oldest → newest):

1. `dc862e9` — `fix(desktop): fence stale draft results`
2. `29a2757` — `test(desktop): cover partial export aliases`
3. `4a49916` — `build(preview): add hash evidence collector`
4. `e927195` — `ci: retrigger after windows-latest pytest hang on #356`

## CI on this tip

| Run | SHA | Result |
| --- | --- | --- |
| [34152302855](https://github.com/pantagram1031/rigorloom/actions/runs/34152302855) | `4a4991666b0c92d9e4a89e57a468525d220d4358` | **cancelled** (windows-latest pytest hang) |
| [34155334389](https://github.com/pantagram1031/rigorloom/actions/runs/34155334389) | `e927195baf5932c8d6f532b9d79bc65e5b71fea9` | **success** (render-smoke + core/all ubuntu+windows) |

Promotion of the living tip to #356 @ `e927195b` is this green run, not the cancelled hang.

Docs-only snapshot [PR #357](https://github.com/pantagram1031/rigorloom/pull/357) (`cursor/living-tip-status-356-4ce5` @ `b69eb827b8f2c50ed3310b007e21a4e1ced40b6b`) is **not** the product tip. Its CI run [34156949995](https://github.com/pantagram1031/rigorloom/actions/runs/34156949995) is **ALL PASS** (render-smoke + core/all ubuntu+windows).

## Card 5 HASH on this living tip

Script-owned **hash-only** evidence now exists for #356 @ `e927195b` under
`F:\RigorloomQA\card5-e927195b\evidence\`:

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
- Card 5 GUI remains **NOT_RUN / hold**. The #356 hashes above are hashes only (`card5Pass=false`, `guiImeClaimed=false`).
- Rematch / own_render / Claude renderer research pins are frozen and are not modified here.

See [release-train-status.md](release-train-status.md) and [loom-ops-status.md](loom-ops-status.md) for the rest of the card board.
