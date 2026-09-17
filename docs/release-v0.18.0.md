# Release record — v0.18.0

Prepared on the stage branch `claude/stage1-report-demo` (2026-09-16 → 2026-09-18), before merge. Per-change
breakdown: `CHANGELOG.md` "v0.18.0 — reports through the engine, com/xml Runtime, desktop revamp, newcomer path,
live agent loop". Ledgers with every run, model, wall time and what was left undone: `docs/plans/stage*.md`.
The tag is applied after the merge PR (`docs/plans/pr-stage1.md`) is green.

## What this release is

v0.17.0 validated the pipeline on empty forms. v0.18.0 is the release where the product did the job it was built
for and became usable by someone other than its authors:

1. **Real reports on the engine.** The AURALAB classroom-acoustics report went through every stage gate in
   autonomous mode; the two earlier shipped reports (Hawkes, WindPath) re-assemble on this engine with the shape of
   their shipped PDFs after porting the fork features they had depended on (boxed equations with captions, guide
   deletion order, margins, colour normalisation, converter mappings, caption and citation heuristics, widow/orphan
   following the form). AURALAB re-assembles pixel-identically on the checked pages.
2. **Runtime backends with honest receipts.** `com` (Hancom, `native_com_session`) and `xml` (any OS,
   `structural_only`, well-formedness verified by the Runtime) execute plans; finished documents are judged against
   their bound blank form so residue gates stop reporting a filled report as "form text survived".
3. **A desktop that reads as a product.** Home, one workspace with a tabbed inspector, hunk-card review bound to plan
   hashes, checkpoint timeline with reverse-plan restore, 양식 연결, pipeline status, verify / fill / poster from the
   GUI. Built-app smoke: 568 checks plus an opt-in live-agent phase.
4. **A newcomer path.** `docs/QUICKSTART.md` (EN + KO) from a recorded Linux run; all ten corpus forms edit through
   the xml backend in a clean venv.
5. **A live agent loop.** The Agent Host with a real model proposed, a human approved, the Runtime applied and
   receipted, on the 소논문 form (CLI and desktop) and on the finished AURALAB report (bound form, keep declaration,
   `acceptance: true`).

## Suite matrix at release preparation

| surface | command | result |
|---|---|---|
| Python (Windows) | `python -m pytest -q --ignore=engine/tests/test_live_com.py` | 5219 passed at 2026-09-17 03:50; suites touched since are green per ledger |
| Python (Linux, WSL) | same | 4191 passed; the 13 remaining failures also fail on `main` in that box (no Node, no CJK fonts, no wheel toolchain; CI installs all three) |
| Desktop headless | `cd desktop && npm run build && npm test` | 225 passed |
| Built app | `desktop/scripts/smoke.ps1` | SMOKE PASS 570/0 (2026-09-18); `agent-live` 13/1 opt-in (`provider_timeout` on the live bridge); `pipeline-native` 11/0 |
| Compile sweep | `python scripts/py_compile_sweep.py` | 143 files, 0 failures |

## Evidence trail

- Report reproduction: `docs/plans/stage1-report-demo.md` (Stage 1c/1d sections), `docs/demo/*.png`,
  `docs/demo/hawkes-repro-page1.png`, `docs/demo/windpath-repro-page10.png`.
- Runtime: `docs/plans/stage3-cli-com-wiring.md` (S1–S10), `docs/demo/cli-com-edit-page1.png`.
- Desktop: `docs/plans/stage4-gui.md`, `docs/plans/stage4b-gui-revamp.md`, `docs/demo/desktop/*.png`.
- Newcomer: `docs/plans/stage5-newcomer.md`, `docs/QUICKSTART.md`.
- Agent loop: `docs/plans/stage6-agent-loop.md`, `docs/demo/desktop/native-agent-*.png`.
- Pipeline in the GUI: `docs/plans/stage7-pipeline-gui.md`, `docs/demo/poster-from-gui.png`.
- Model/tooling ledger: `docs/plans/model-eval.md`.

## Honest limits

- No rendering proof anywhere: page images are views; receipts are `structural_only` unless Hancom produced a
  native session. The renderer/rematch/certificate freeze stays in force.
- macOS untested; Linux verified in WSL; Windows verified natively.
- The live agent sessions used a keyless local bridge to Cursor models; Anthropic direct is wired but its live
  smoke needs a user-entered key and is not recorded.
- The desktop app version stays `0.1.0` (its own line); the product version is `0.18.0`.
- Native fill/poster cards from the 2026-09-18 release build (`docs/demo/desktop/native-fill-result.png`, `native-poster-result.png`): fill finished **gappy** (`converged=false`, proofGrade none); poster finished **pass**. Not a render certificate.
