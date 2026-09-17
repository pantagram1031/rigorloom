# Stage 2 — public repo hygiene

Status: ACTIVE 2026-09-16. Owner: Claude (Fable). Coding lanes: Cursor agent.
Branch for local work: `claude/stage1-report-demo` (continues from Stage 1) unless noted.
Outward actions (push, closing PRs, editing GitHub state) wait for the user's explicit go.

## Goals

- [ ] H1 green CI on `main`: `tests/test_cli_installer.py::...` asserts `engine_root_locked`
      but Linux CI returns `containment_breach` (run 34817074977, 2026-09-14). Root-cause and
      fix on a branch; prove with the test on Linux (WSL if available) or a faithful reasoning
      note in the commit.
- [ ] H2 stale draft PRs: classify the open PRs (#300–#366 and older) into
      contained-in-main (close with a one-line comment), superseded (close, point to the
      integration commit), and live (keep). Produce the list; the user approves before any close.
- [ ] H3 README rewritten around what the tool does for a reader who has 30 seconds:
      one-sentence purpose, the AURALAB demo (page renders + poster), install in one block,
      one-command report flow, honest status table (pipeline usable / CLI edit tools in progress /
      desktop pre-alpha), links to CHANGELOG and docs. Keep the existing detailed sections below.
- [ ] H4 CHANGELOG `Unreleased` entry for the Stage 1 engine work (boxed equations, EQ captions,
      delete order + `delete_texts_after`, `strip_residual`, `strip_guide_ws_runs` + charPr
      neutralization, poster line, optional `[poster]` extra).
- [ ] H5 demo assets committed in a public-safe form under `docs/demo/` in the repo
      (page PNGs + poster PNG; no student names, no school-specific form beyond what the
      poster header shows).

## Ledger

| When | What | Result |
|---|---|---|
| 2026-09-16 | H1 reproduced on Linux (WSL Ubuntu, clone of main, pytest user-site): `assert 'containment_breach' == 'engine_root_locked'`. Cursor H1 dispatched with the WSL commands | pending |
| 2026-09-16 | H2 classification of 100 open PRs vs `origin/main`: **18 fully contained** (0 ahead: #330 #333 #336 #339 #340 #344 #346 #348 #349 #350 #353 #354 #355 #356 #360 #361 #363 #365 → close with "content integrated into main via codex/unified-latest-20260914"); **63 renderer/desktop research line** (`engine-e2-*`, `desktop-on-renderer-*`, `docs-checkpoint-*`, kept under the renderer freeze; propose converting to one tracking issue and closing the per-round PRs); **19 other** (docs/QA/living-tip, 1–4 commits ahead; review individually). No PR touched | awaiting user go for any close |
| 2026-09-16 | H1 fix committed 22f5146 (test made deterministic on POSIX; verified on WSL ext4 and Windows). Full suite on the stage branch (4,957 passed, 189 skipped, 81 min): 2 failures — `test_hancom_operation_catalog` (new `page_numbers`/`set_header` ops not in `docs/hancom-operation-catalog.json`, line refs drifted → Cursor T8 on composer-2.5-fast) and `test_desktop_draft_fence::test_head_freshness_node_tests` (needs `desktop/node_modules` typescript; environmental, passes on main where node_modules exists) | pending T8 |
| 2026-09-16 | H3 README: new "What this is", 30-second demo table (4 images), status table. H4 CHANGELOG Unreleased entry. H5 `docs/demo/` (6 PNG, 2.1 MB). Committed b35639b | local only |

2026-09-17 03:50: full pytest sweep on claude/stage1-report-demo tip (after Stage 3 S7 and Stage 4/4b) = 5219 passed / 0 failed / 182 skipped; desktop headless 193; built-app smoke 549/0. CI-equivalent green locally; pushing and merging still need the user.

2026-09-17 13:20 Linux (WSL Ubuntu, Python 3.12, PyMuPDF user-site) full suite on the branch tip 6161574: 4191 passed, 16 failed, 1259 skipped. The same 13 environmental failures occur on main's commit ec61ea0 in this box (10 own_render font-metric tests: no Pretendard/Malgun/Noto CJK installed; 2 desktop Node-bridge tests and 1 more on the branch: no Node in WSL, CI installs Node 22; the wheel consumer e2e: no offline wheel toolchain). The one branch-only failure was tests/test_hancom_operation_catalog.py line references drifting after T11/T13 → refreshed (T17, composer-2.5-fast, 2.5 min). CI on GitHub installs Node, fonts and the wheel toolchain, so the expectation for a push is green.

