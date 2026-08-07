# Release record — v0.16.0

Prepared on branch `w6-release` from `main` @ `630664b` (#55). This record
is the evidence trail for the v0.16.0 tag: bundle inventory, suite matrix,
privacy status, and the honest list of capability boundaries and
operator-run leftovers. The tag itself is applied separately by the
operator after reviewing this record.

## What this release is

The complete v0.16 program (`docs/plans/v0.16-unified-core-and-modules.md`):
one general HWP/HWPX core (engine, form recognition, render proof ladder,
privacy scan, module registry, base studio) plus capability shipped as
distribution modules behind one contract. Per-PR breakdown: CHANGELOG.md
"v0.16.0 — unified core and modules" (#29–#55).

## Bundle inventory

Built by `scripts/package_module.py` (staging privacy-scanned by the
packager; any HARD refuses the build with exit 3 and writes nothing) and
re-verified with `--verify` (per-file sha256 against `MANIFEST.json`;
mismatch, missing, or unlisted file is exit 3).

| bundle | files | zip sha256 |
|---|---:|---|
| `rigorloom-core-0.16.0.zip` | 85 | `9a9f5847a4eb3da83853999d8eeed744decf0443803510047ff64816e3c847e3` |
| `rigorloom-report-0.16.0.zip` | 87 | `8ea0f22a333b49550b59ec67d5a339b75cd0766103ebee7cab5deca6fd8e39f9` |
| `rigorloom-style-0.16.0.zip` | 14 | `01daa06596b9a763a991c34c044cce6bbd792a59e8d7eb2f3c8733dd0606b976` |

All three `--verify` runs: `ok: true`, zero problems. Bundles live in
`dist/` (gitignored, never committed); the hashes above bind this record
to the exact artifacts built at this commit — rebuilding after any change
produces different hashes and requires updating this table.

## Test suite (both CI matrix points, local Windows, Python 3.11)

| matrix point | result |
|---|---|
| core-only (`write-enabled --none`) | 866 passed / 565 skipped / 17 subtests, exit 0 |
| all-modules (`write-enabled --all`) | 1293 passed / 138 skipped / 35 subtests, exit 0 |

Skips are module-gating (moved module tests collect-and-skip on core-only)
plus fixture/env skips; both points collect the same 1431 tests. The
core-only point is the "absence is not failure" proof: every distribution
module disabled, suite green, report entry points refuse loudly by design.

## Privacy status

- **Repo-wide** `privacy_scan . --json`: exit 0, HARD 0, WARN 34 — all 34
  are pre-existing synthetic fixture/proximity-heuristic warnings, none
  new in this release.
- **Corpus binaries**: the 32 `tests/corpus/forms` binary members
  (originals + XC-1 converted hwpx + render PDFs) pass only via the
  sha256-pinned allowlist in the corpus `manifest.json`; allowlisted files
  are still content-scanned (`binary_pii_rrn` / `binary_pii_phone` /
  email / user-path / denylist), and unlisted or hash-drifted binaries
  stay HARD. Ruling recorded in `docs/gate-calibration.md`.
- **Bundle staging**: the packager runs `privacy_scan` over every staging
  dir with the allowlist **not** applied (bundles stay categorical); all
  three builds passed. Independently re-scanned each *extracted* bundle:
  core / report / style all HARD 0, WARN 0, total 0.
- **Corpus containment**: a regression test asserts no
  `tests/corpus/forms` member lands in any bundle
  (`tests/test_package_module.py`); module bundles carry their own module
  payload only.
- **Profile store**: `privacy_scan`'s `profile_store_content` /
  `profile_store_path` HARD markers make a bundle that stages
  personalization-store content unbuildable; the suite itself no longer
  writes the repo store (session-scoped conftest guard, #53).

## Measured capability (W6 benches)

- hwp→hwpx conversion: **10/10 OK** on the official blank-form corpus
  (Hancom 13.0.0.2986, strictly serial, zero hangs/retries) —
  `docs/research/xc1-conversion-bench.md`.
- Form recognition (`form_inspect`): **12/12** corpus members probed;
  guide-text detection **11/12** after the W6.2 mechanism-level
  generalization, with the 12th locked as a correct zero (below).
- Conversion parity: `check_convert_parity` `.hwp` leg — structural counts
  HARD, text advisory; live pairs (jumin, kstartup) pass.
- PDF export honesty: `pages_document` vs `pages_pdf` always reported;
  stored 2-up print imposition (`PrintMethod≠0`) normalized for `.hwpx`
  sources, loud WARN elsewhere.

## Known capability boundaries (shipped as statements, not gaps)

From `skill/references/forms.md` and the bench doc §8–§9:

1. **Family ⑤ (기업 내부 문서): UNSUPPORTED/UNTESTED.** No official corpus
   source exists; the skill surface says so and applies ①-family rules by
   analogy only on explicit user insistence.
2. **Family ③ (학교 서식): corpus gap.** Guide-text detector precision is
   unproven on school forms (one dead source URL, one source served an
   issued document); acquiring official blanks is operator work.
3. **admrul-gajokdolbom guide_text = 0 is a bound, not a miss** — the form
   has no removable guide text; a regression test locks the zero
   (`test_admrul_bound_locked_at_zero`).
4. **`.hwp` conversion parity is structural, not byte-level.** Text char
   totals are advisory (source/hwpx normalization mismatch is a documented
   property); no byte-parity claim exists for `.hwp` sources.
5. **Single Hancom build.** All conversion numbers are one build's
   behavior (13.0.0.2986); no cross-version fidelity data.
6. **DocSummary metadata is not stripped on conversion** (issuing-agency
   clerk names in `HwpSummaryInformation` carry into converted siblings;
   flagged in the corpus manifest privacy note).
7. **COM shape/picture classification is locale-dependent** (`UserDesc`,
   Korean install assumed — same assumption as the rest of the backend).
8. **`form_inspect` vs `content_extract` table counts disagree on 6/10
   corpus files** — recorded open item (bench §8), not root-caused; does
   not affect the pinned recognition floors.
9. **Render proof ceilings are unchanged**: LibreOffice/H2Orestart stays
   advisory and is skipped for equation-bearing documents;
   `experimental-rhwp` is hard-blocked from submission; `certified`
   requires an operator-issued HMAC certificate; `hancom` is the only
   native submission grade.

## OPERATOR-RUN leftovers (open at tag time, honestly)

- **Skill token eval**: the W5.3 acceptance's loaded-token-footprint
  measurement and the agent-in-the-loop halves of the A1/A2 eval scenarios
  are marked OPERATOR-RUN in `docs/research/form-eval-scenarios.md`; the
  machine-check halves pass (with a non-vacuous negative control).
- **Family ③ corpus acquisition** and **family ⑤ sourcing decision** (find
  an official source or keep the unsupported statement) — both are
  corpus-acquisition tasks that need a human at a browser/agency portal.
- The `dist/` bundles are local build artifacts; publishing/distribution
  mechanics (skillshop listing, update channel) were explicitly deferred
  by the plan's open-questions section.

## Positioning check (plan §6.3)

Shipped text audited: the style capability is described everywhere as
translationese removal / voice consistency / form-rule compliance — never
AI-detection evasion (`modules/style/README.md`, module docstrings,
CHANGELOG, README). Detector scores remain advisory, pinned by
`test_h2_advisory_only`.

## Tag checklist (for the operator)

- [ ] Review this record and the CHANGELOG v0.16.0 section.
- [ ] `git tag v0.16.0 && git push origin v0.16.0` (tag is NOT applied by
      the preparation branch).
- [ ] If bundles are rebuilt after further commits, refresh the sha256
      table above first.
