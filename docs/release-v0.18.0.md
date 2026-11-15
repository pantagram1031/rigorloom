# Release record — v0.18.0

Prepared from `main` @ `9940f90` (#378) plus the release commit, which changes
only the version number and documentation. This record lists what v0.18.0
contains, the bundle hashes, the CI result on the release commit and the known
limits. The tag is applied after this PR is reviewed and green.

## What this release is

v0.17.0 was a validated report pipeline. v0.18.0 changes what Rigorloom is
for: filling in and editing Korean official documents where a person approves
every edit before the file changes.

- **One owner for every edit.** `RuntimeCore` proposes, validates, requests
  approval, resolves and applies (T169). The paths that still sit outside it
  are named in [architecture.md](architecture.md).
- **Two checks with no AI in them.** `rigorloom guard` reports when an edit
  changes a number, date, quotation, negation or direction word (T162, T165);
  `rigorloom style check` points at Korean phrasing worth a second look under
  the versioned ruleset `ko-style/1` (T164).
- **A browser workspace.** `rigorloom ui` serves the review screens on
  127.0.0.1 with a per-launch token (T166); see [web-ui.md](web-ui.md).
- **An end-to-end 공문 demo** on a blank 기안문 form, without Hancom Office,
  checked byte for byte in the tests (T167); see
  [demo-gongmun.md](demo-gongmun.md).
- **An optional HWP engine adapter** that is used only when a separately
  installed engine is present (T163).
- Removed: the read-only Studio dashboard (T168). Legacy plans moved under
  `docs/archive/`.

The full list, including the hardening entries T79 to T161, is the v0.18.0
section of [CHANGELOG.md](../CHANGELOG.md).

## Bundle inventory

Built by `scripts/package_module.py` and re-verified with `--verify` (all
seven `ok: true`), on Linux with Python 3.12.

| bundle | files | zip sha256 |
|---|---:|---|
| `rigorloom-core-0.18.0.zip` | 155 | `cfc52223c1044bf39e3d05d1160cf4060400a99b91e10a1bab599c91eeb23a08` |
| `rigorloom-report-0.18.0.zip` | 88 | `30d839be4fbaaebbdb23182c277c2d029e0172cc5770412901fd8f7c21784248` |
| `rigorloom-style-0.18.0.zip` | 14 | `4bc4a46a5281b0fa3f6e9b42754208f8b7aa468fc9f69105cbc6efaf536e9ea4` |
| `rigorloom-gongmun-0.18.0.zip` | 14 | `59f4d363bf186cd7384711a6677257c0d62472d94ce8b14b06fbcea000416890` |
| `rigorloom-minwon-0.18.0.zip` | 12 | `2ca09a1eb2698239433f3ba9f3cee4dae4fd751fb08c6925a8857afa8aa1cc49` |
| `rigorloom-hr-0.18.0.zip` | 12 | `d6c8785241409342a9ba688cf3b77b321e90706e9bea2e674d8aa4953e32c31c` |
| `rigorloom-grant-0.18.0.zip` | 12 | `4bb22fae8ac05397e9a76e31b959f8559b57a425018ccce0b5c29e1ca998ed1c` |

The bundles were built twice, before and after the documentation edits in the
release commit, with identical hashes. To check a row yourself from a checkout
of the tag:

```sh
python scripts/package_module.py --module core --out dist
sha256sum dist/rigorloom-core-0.18.0.zip
```

Core went from 98 files at v0.17.0 to 155: 61 added (32 under
`engine/references`, 15 under `pipeline/scripts`, 6 under `engine/scripts`, 4
under `pipeline/references`, 3 under `pipeline/adapters_impl`, 1 under
`skill/references`) and 4 removed (the `studio/` files). `report` gained one
file; the other module bundles have the same counts as v0.17.0.

One finding, stated as found: rebuilding the v0.17.0 core bundle from the
v0.17.0 tag on this Linux machine gives `0b71131f…`, not the `f61b5bca…` in
[release-v0.17.0.md](release-v0.17.0.md), which was built on Windows. That
record already names the zlib build as the one input the packager cannot pin.
The per-file hashes in `MANIFEST.json`, which `--verify` compares, do not
depend on it. The v0.18.0 hashes above are for Linux and CPython 3.12.

## CI on the release commit

GitHub Actions run 43731757870 on commit `4ca7d86` (the release commit before
this CI record was added). All five jobs passed.

| Job | pytest |
|---|---|
| core-only, Ubuntu | 4200 passed, 1224 skipped, 0 failed |
| all modules, Ubuntu | 5272 passed, 152 skipped, 0 failed |
| core-only, Windows | 4152 passed, 1272 skipped, 0 failed |
| all modules, Windows | 5224 passed, 200 skipped, 0 failed |
| render smoke | passed |

Each test job also runs `qa/tests` (26 passed in both Windows logs), the
`py_compile` sweep (143 files, 0 failures) and the bootstrap smoke.

Skips are tests that need licensed fonts, Hancom, a renderer or real user
fixtures, none of which the CI runners have.

## Privacy status

`privacy_scan . --json` on the release tree: HARD 0, WARN 51 (42 at v0.17.0).
44 are the `korean_student_id_proximity` heuristic firing on synthetic fixture
data and examples, the same rule as at v0.17.0. 7 are `large_file`: the six
Nanum font files under `engine/references/fonts/family-map/` and the Pretendard
face the browser UI uses, all under the SIL Open Font License (`OFL.txt` next to
each). No user document, licensed Hancom font or engine source is in the tree.

## Known limits

- The HWP engine adapter is optional. The engine itself is private and not
  part of this repository; without it, Rigorloom uses its own minimal HWPX
  path.
- No claim is made about how natural or human-like any rewritten Korean is. A
  measured study is being designed; until it reports, the product says nothing
  on that point.
- `style check` rules are notices for a person to read. They have false alarms
  on careful human writing, and they do not cover every document type equally.
- 14 tests fail on the machine this release was prepared on and pass or skip
  in CI: 3 call Node with `--experimental-strip-types`, which that machine's
  Node 20 does not have; 10 compare text layout against values measured with
  the fonts the forms declare, which are licensed and not distributed; 1 is a
  .docx render test that stops on an image read error (`docx.image`
  `UnexpectedEndOfFileError`) and has not been diagnosed further.
- `rigorloom demo gongmun` runs from a clone; a plain `pip install` does not
  carry the engine scripts it needs.
- The native desktop shell under `desktop/src-tauri/` is pre-alpha. The browser
  UI is the supported way to review edits, and it is being redesigned next.
