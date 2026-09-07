# Release-train status

Compact living-train pointer. **Rematch freeze: ON.** No `main` merge.
This is not a rewrite of the Epoch 0 specification on
`codex/private-preview-epoch-0`, and it does not transplant rematch /
own_render / Claude renderer research pins.

**Updated:** 2026-09-08 ~04:45 KST

## Train head

The executable product train is the living tip:

- draft [PR #356](https://github.com/pantagram1031/rigorloom/pull/356) @
  `e927195baf5932c8d6f532b9d79bc65e5b71fea9`
- branch `cursor/epoch-desktop-onto-355-ba53`
- epoch desktop restack on prior docs tip [PR #355](https://github.com/pantagram1031/rigorloom/pull/355)
  @ `99ad234cc2af4e87da54ec4d3151e62c44c424d4` (ancestor)

`main` is unchanged. Do not merge this train to `main` without an explicit
operator order.

## Epoch source (not the living tip)

Codex private-preview epoch product commits were taken from
`origin/codex/private-preview-epoch-0` @
`5b570051905b88d30b410825adc8b21cf0c0875f` and restacked onto #355 as #356:

| Epoch source | On #356 |
| --- | --- |
| `4f214ace` draft-fence | `dc862e9` |
| `cae6ff0` partial-export aliases | `29a2757` |
| `5b57005` hash evidence collector | `4a49916` |

The epoch branch remains a separate Codex head. The living tip is #356, not
`5b57005`. Epoch `8ed2d263` docs checkpoint was not required for the product
tree and was not replayed.

The long Epoch 0 release-train prose stays on the epoch branch
(`docs/plans/codex-private-preview-release-train.md` there). It is not copied
here.

## CI

- Hung run [34152302855](https://github.com/pantagram1031/rigorloom/actions/runs/34152302855) on `4a499166` — **cancelled**.
- Green run [34155334389](https://github.com/pantagram1031/rigorloom/actions/runs/34155334389) on `e927195b` — **success**. That green run is the #356 tip SHA.

## Card evidence (previously recorded; not re-certified on `e927195b`)

Do not treat tip promotion as new Windows GUI/IME evidence. A Card 5 hash
recollect under `F:\RigorloomQA\card5-e927195b` was requested after promotion;
it is **not** recorded as PASS here.

| Card | Previously recorded | Still hold |
| --- | --- | --- |
| 1 export safety | Windows force-quit matrix PASS×3 @ `4ded110c` (#348); dest sha256 `477f26e51aa5e62b3a3cc14a39f0cf2a15ee446e8db87328d752ba8f5718f91f`; artifacts `F:\RigorloomQA\card1-export-safety\wt-4ded110c\qa\_artifacts\` | — |
| 2 draft-fence | Product tests on the ancestor stack (#339 via #352 empty-diff ancestor of #350; #356 adds `ownsDraft`). No Windows GUI PASS recorded | no GUI PASS claimed |
| 3 run-scoped edit | Windows pytest PASS @ `60e8ccd` (#350): 13 passed / 0 fail (`run_scoped` + `range_text` + `sequential_offset`); evidence `F:\RigorloomQA\card3-win\evidence-60e8ccd\` | no GUI E2E claimed |
| 4 Korean IME | prep harness only | **NOT_RUN / hold** |
| 5 install hash | script-owned hash PASS @ `99ad234` (#355): `installCandidatePass=true`, `guiImeClaimed=false`; prefixes exe `7c8be787…` sidecar `af9530c2…` installer `b518bd15…`; evidence `F:\RigorloomQA\card5-99ad234\evidence\` | **Card 5 GUI NOT_RUN / hold** |

## Freeze

- Rematch freeze **ON**.
- Do not open or restack rematch / own_render / conveyor / LayoutSnapshot / IoU
  research pins onto this train.
- Card 4 IME PASS and Card 5 GUI PASS are **not** claimed.
