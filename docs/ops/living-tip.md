# Living product tip

Status snapshot only. **Rematch freeze: ON.** No `main` merge.

**Updated:** 2026-09-08 ~04:45 KST

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

## Holds

- Card 4 Korean IME remains **NOT_RUN / hold**. This snapshot does not claim IME PASS.
- Card 5 GUI remains **NOT_RUN / hold**. Recorded hash evidence is hashes only (`guiImeClaimed=false`).
- Rematch / own_render / Claude renderer research pins are frozen and are not modified here.

See [release-train-status.md](release-train-status.md) and [loom-ops-status.md](loom-ops-status.md) for the card board and previously recorded evidence.
