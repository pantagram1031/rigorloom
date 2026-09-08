# Release-train status

Compact living-train pointer. **Rematch freeze: ON.** No `main` merge.
This is not a rewrite of the Epoch 0 specification on
`codex/private-preview-epoch-0`, and it does not transplant rematch /
own_render / Claude renderer research pins.

**Updated:** 2026-09-08 ~10:10 KST

## Train head

The executable product train is the living tip:

- draft [PR #361](https://github.com/pantagram1031/rigorloom/pull/361) @
  `718a253bd3c35bc620c02e7e54b1deeaf50a77f9`
- branch `cursor/tip-stack-fe-state-harden-3ebe`
- FE tip-stack of [#358](https://github.com/pantagram1031/rigorloom/pull/358)
  + [#359](https://github.com/pantagram1031/rigorloom/pull/359)
  + [#360](https://github.com/pantagram1031/rigorloom/pull/360) onto epoch
  desktop [PR #356](https://github.com/pantagram1031/rigorloom/pull/356) @
  `e927195baf5932c8d6f532b9d79bc65e5b71fea9` (ancestor)

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

The epoch branch remains a separate Codex head. The living tip is #361, not
`5b57005` and not #356. Epoch `8ed2d263` docs checkpoint was not required for
the product tree and was not replayed.

The long Epoch 0 release-train prose stays on the epoch branch
(`docs/plans/codex-private-preview-release-train.md` there). It is not copied
here.

## CI

- Hung run [34152302855](https://github.com/pantagram1031/rigorloom/actions/runs/34152302855) on `4a499166` — **cancelled**.
- Green run [34155334389](https://github.com/pantagram1031/rigorloom/actions/runs/34155334389) on `e927195b` — **success**. That green run is the **#356** ancestor product SHA.
- Docs snapshot [PR #357](https://github.com/pantagram1031/rigorloom/pull/357) recorded #356 as living tip; it is **not** the living product tip. HEAD `4fac8a7b` run [34160494945](https://github.com/pantagram1031/rigorloom/actions/runs/34160494945) was **ALL PASS** after the grandchild-death poll. Prior `b69eb827` run [34156949995](https://github.com/pantagram1031/rigorloom/actions/runs/34156949995) was **ALL PASS**. `84bead93` failed all-modules ubuntu on inherited flake `test_run_child_capture_cleans_ordinary_grandchild_cross_platform` (run [34159193388](https://github.com/pantagram1031/rigorloom/actions/runs/34159193388)).
- Green run [34170712826](https://github.com/pantagram1031/rigorloom/actions/runs/34170712826) on `718a253` — **ALL PASS**. That green run is the **#361** living product tip SHA.
- This ops restack is docs/CI-flake only; it is **not** the living product tip. Do not pin this PR HEAD as the product SHA.

## Card evidence

Card 1 / 2 / 3 remain as previously recorded. Card 5 **HASH** remains certified on ancestor `#356` @ `e927195b` (hashes only; **not re-collected** on #361). Do not treat this as GUI/IME evidence.

| Card | Recorded | Still hold |
| --- | --- | --- |
| 1 export safety | Windows force-quit matrix PASS×3 @ `4ded110c` (#348); dest sha256 `477f26e51aa5e62b3a3cc14a39f0cf2a15ee446e8db87328d752ba8f5718f91f`; artifacts `F:\RigorloomQA\card1-export-safety\wt-4ded110c\qa\_artifacts\` | — |
| 2 draft-fence | Product tests on the ancestor stack (#339 via #352 empty-diff ancestor of #350; #356 adds `ownsDraft`; #361 adds `DraftOwner` + `DraftFence` + composer view-state). No Windows GUI PASS recorded | no GUI PASS claimed |
| 3 run-scoped edit | Windows pytest PASS @ `60e8ccd` (#350): 13 passed / 0 fail (`run_scoped` + `range_text` + `sequential_offset`); evidence `F:\RigorloomQA\card3-win\evidence-60e8ccd\` | no GUI E2E claimed |
| 4 Korean IME | prep harness only | **NOT_RUN / hold** |
| 5 install hash | Ancestor hash-only PASS @ `e927195b` (#356): `installCandidatePass=true`, `card5Pass=false`, `guiImeClaimed=false`; status `HASHED_BUILD_ARTIFACTS` / verify PASS for hashes only. EXE `6df95dc3564f7e5ccebc5db44a27cbf8acb2822cbbdd7b1132cc0482889635fc`; sidecar `1346fe07bcf6fc7e9d55cb29b4c9f58926073859215f669f81aa1bd4a91a313b`; NSIS `3bbc5b820c7387b0fcc9fa7aaac4bec22cc182f9b339ae1d3635672785b15ffe`. Evidence `F:\RigorloomQA\card5-e927195b\evidence\`. **Not re-collected** on #361 @ `718a253`. Prior #355 hashes @ `99ad234` (`7c8be787…` / `af9530c2…` / `b518bd15…`, `F:\RigorloomQA\card5-99ad234\evidence\`) are ancestor record only. | **Card 5 GUI NOT_RUN / hold** |

## Freeze

- Rematch freeze **ON**.
- Do not open or restack rematch / own_render / conveyor / LayoutSnapshot / IoU
  research pins onto this train.
- Card 4 IME PASS and Card 5 GUI PASS are **not** claimed.
