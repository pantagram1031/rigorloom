# Changelog

Format is loosely [Keep a Changelog](https://keepachangelog.com/); versions
correspond to Git tags. The stage-machine schema version (`pipeline/references/
stages.yaml`'s `version: "0.6"`) has not changed since v0.7 — these releases
add gates, backends, and tooling on top of a stable kernel, they do not change
the kernel's contract shape.

## Unreleased

### Skill — one canonical fill recipe, one spacer class, one fewer permanent warning

The independent Codex harness reported three defects that share a shape: the
product knew things it never said, so every reader re-derived them.

- **`skill/references/fill-recipe.md`** — the canonical mixed-storage fill,
  worked end to end on the real PPS 협업승인신청서 and replayed verbatim to
  `acceptance: true`. Three harnesses filling that form picked three different
  strategies for the *same* 협업기간 cell, and one built three separate maps.
  So the recipe states the branch-per-cell decision rule first (empty run →
  `fill-cells`; skeleton to keep → `--at-cell-append`; template to replace
  wholly → `--at-cell`; multi-run → the `#RUN` the refusal hands you; `spacer`
  → do not write there), works 협업기간 as the example *because* it is the
  field that fractured, names the four artifacts and the exact flag that eats
  each, gives the literal sequence including the previously-undocumented
  `com_backend.py convert --file … --to …` and the `tasklist` check before COM,
  and closes with what an accepted verdict looks like versus each partial.
  Linked one level deep from SKILL.md's routing table; the superseded
  "which one fills a form" table in `operations.md` §3 is now a pointer, not a
  second account.
- **`form_inspect`: `classification: spacer`.** Six cells on the PPS form were
  reported as `fill_target` when nothing is ever written in them, so Codex and
  the round-3 Opus run each reasoned them away by hand. A spacer is empty, has
  no label neighbour, and has one of two filler geometries derived from the
  table itself — `full_width_band` (spans every column AND is shorter than the
  shortest cell in that table that prints text) or `stub_head` (the corner
  where a header row crosses a label column). No addresses, no absolute
  heights, no tuned ratios. Excluded from the new `fill_target_count`, reported
  under `spacer_cells`. PPS: 19 empty cells → 13 + 6.
- **`empty_cell_expected_fill` stops firing on correct runs.** Every accepted
  tier emitted the same two warns for by-design-blank or unsupplied cells, with
  a page y-coordinate as the only evidence. `layout_qa` now emits one finding
  per empty header cell carrying its column, its header row and a `label`, plus
  `spacer_pattern` for the two by-design shapes; `visual_verify` suppresses
  those and any seat named in **`declared_blank`** (in expectations or in the
  wrapper-shaped fill map — `intentionally_blank` is an accepted alias, folded
  into one list), recording every suppression under
  `deterministic.layout_qa.empty_cell_suppressed` and the declaration under
  `deterministic.declared_blank` / `declared_blank_source`.
- **Ragged shipped tables fail the build.** In GFM a raw `|` splits a cell even
  inside a code span, so `com_backend.py inspect|edit` gave SKILL.md's routing
  table one four-cell row among three-cell rows — in the first table a router
  reads. Escaped, and `package_module` now asserts every table in every shipped
  surface document is rectangular (core bundle and each module fragment).

### Engine — the seat-text gap the third clean-room round left open (T34)

Round 3 measured the already-fixed product and both tiers — Sonnet and Opus,
independently — hit the same wall: a form's **printed seat** (a skeleton the
form typeset for a value: `" 우(     -     )"`, `" http://"`,
`"20   .    .    .  ~  20   .    .    .   (     개월)"`) could only be edited
with a `replace` key reproducing the run's exact internal whitespace, and
nothing shipped yielded that string. So both agents read
`Contents/section0.xml` by hand — precisely the contact the shipped skill
forbids. Opus hand-assembled two keys; the Sonnet tier's 30-char
`text_preview` cut the 협업기간 skeleton right before its `(     개월)` blank
and so HID it, costing a second replace pass.

Fixed in three layers, most important first:

- **`preedit replace --at-cell ROW,COL[#RUN]=TEXT`** and
  **`--at-cell-append ROW,COL[#RUN]=TEXT`** (both repeatable, plus
  `--at-cell-map JSON` whose values are a string or `{text, mode}`): an
  address-keyed variant that removes the need for the exact string entirely.
  The two modes are explicit, never inferred — `--at-cell` replaces the run's
  whole text, `--at-cell-append` keeps the printed prefix and appends
  (`" http://"` → `" http://host"`, the normal shape of a labeled field,
  T31). A cell holding more than one text run **refuses** (exit 2,
  `at_cell_run_ambiguous`) and the refusal lists every run index with its
  exact text, so neither "first run wins" nor "flatten the cell" can silently
  destroy content — PPS (15,0) carries the regulation sentence, the
  `년 월 일` 신청일 line, `신청인`, `(서명 또는 인)` and `조달청장 귀하` as
  separate runs. A cell with no text run at all routes to `fill-cells`, so the
  two operations partition "already prints something" vs "genuinely empty"
  (T27). Addressing reuses `hwpx_tables`' scanner, so `--table N` agrees with
  `form_inspect` and `fill-cells`, and every guard is shared: stale-lineseg
  strip on changed paragraphs only (T24), well-formedness of modified members
  before writing, the T30 charPr pre-flight (its refusal names
  `--at-cell-charpr ROW,COL#RUN=ID`, accepted even when the edit was written
  without `#RUN` — a ready-to-paste flag that does not paste is worse than
  none), and the T22 dangling-charPr assertion when a charPr is repointed.
  `--at-cell-expect ROW,COL[#RUN]=SUBSTRING` is a pre-write precondition
  compared with all whitespace removed on both sides, so an operator asserts
  `우(-)` without counting spaces. Re-runs are no-ops in both modes, so append
  never doubles. `--map` together with `--at-cell*` in one call is a usage
  error. Geometry is byte-identical apart from the edited text and the touched
  paragraphs' linesegarray, fixed by regression on the real PPS seats.
- **`table_map[].text_preview` now reports `truncated`.** The failure was not
  that the preview is short but that nothing said there was more, which is why
  a competent agent concluded the skeleton ended at the cut.
- **`form_inspect --full-text [TABLE:]ROW,COL`** (repeatable): the documented,
  per-cell opt-in escape from the structure-only contract. It emits the exact
  run text for the cells you name and no others — absent from the profile
  unless requested, with no whole-body path — because a byte-exact string is
  only needed for a `replace --map` key or a `check_residue --fill-map` entry.
  Its `runs[].index` IS `--at-cell`'s `#RUN` (`form_inspect` imports
  `preedit.cell_text_runs`), and the string round-trips: fed back as a
  `replace` key it hits exactly once — the regression that proves the gap is
  closed.

Also: `--charpr-per-cell` is now documented in the **fill section** of
`skill/references/operations.md` and in the SKILL.md routing row, not only
inside the T30/T32 prose — round 3 found the fill path showing a bare
`fill-cells --cell` call while the flag it actually needs lived three
paragraphs away.

### Engine — fill defects found by the first clean-room cross-model run

Two independent clean-room agents (Sonnet and Opus) hit all three of these on
the same procurement form, so each is reproduced before it is fixed and
locked by a failing-before test.

- **T26 — `preedit replace` double-applied a value containing its own key.**
  Tier B (raw substring) ran over the span tier A (whole-run) had just
  rewritten. Measured with `operations.md`'s OWN documented example:
  `{" http://": " http://example.kr"}` produced
  `" http://example.krexample.kr"` with `hits: 2` — following the shipped
  docs corrupted the cell. Replacement is now single-pass: every span a tier
  writes is protected for the rest of the call, and spans already equal to
  the value are protected before any tier runs. This also restores re-run
  idempotence for such mappings and stops a later key from rewriting an
  earlier key's value.
- **T27 — new `preedit fill-cells`, the offline path to a genuinely empty
  cell.** A form's empty cell is `<hp:run charPrIDRef="N"/>` with no `<hp:t>`
  at all (19 of 19 empty cells on the PPS 협업승인신청서), so the text-keyed
  `replace` could never reach it even though the skill routed form-filling
  there. `fill-cells` addresses cells by the `cellAddr` that `form_inspect`'s
  `table_map` reports (`--cell ROW,COL=TEXT` / `--map`, `--table N`), creates
  the `<hp:t>` inside the empty run preserving its charPr (`--charpr`
  overrides and then asserts no dangling charPr, T22), refuses a non-empty
  target unless `--overwrite`, strips the modified paragraph's stale
  linesegarray (T24), validates well-formedness before writing, and reports
  per-cell hits. Table scanning moved to a shared tag-stack scanner
  (`engine/scripts/hwpx_tables.py`) so `--table N` and `table_map[N]` are the
  same table: the old non-greedy `<hp:tbl>(.*?)</hp:tbl>` mis-paired nested
  tables and got the table/cell counts wrong on 6 of the 12 corpus forms
  (gianmun-byeolji-1ho: 3 tables/34 cells reported as 2/6). `table_map` cells
  now also carry `span`, and tables carry `depth`.
- **T28 — `com_backend set_cell` addressed cells by keypress count.**
  `TableRightCell` wraps across rows and `TableLowerCell` jumps over
  rowSpans, so on any form with a rowspan label column (the norm in
  government forms) the old `row`/`col` wrote to the wrong cell — targeting
  cellAddr (2,3) on the PPS form landed on (2,6), the `법인등록번호` label.
  `addr: [row, col]` now means cellAddr and is translated by a wrapping
  `TableRightCell` walk that verifies `get_cell_addr()` after every move and
  aborts without writing on any mismatch; `expect_empty` / `expect TEXT`
  refuse when the target's current content disagrees; the legacy keypress
  mode survives only behind an explicit `raw_traversal: true` and the
  validator rejects bare `row`/`col` before Hancom starts. A new
  `com_backend.py set-cell --addr ROW,COL` subcommand is one session per cell
  — the documented mitigation for the observed `get_into_nth_table(n)` drift
  across repeated calls in a single Hancom session. COM-verified on the PPS
  form: (2,3) reached in 4 steps from entry `A1`, label cells untouched.

### Modules — `gongmun`, the first work-type module beyond report

`modules/gongmun/` ships the 공문/기안문 work type (HWP usage landscape family
②) as its own distribution bundle: one deterministic checker
(`check_gongmun`), the `gongmun_org` pack type its issuing-organization seats
are filled from, and a skill fragment for the 공문 task flow. No
`requires_modules` — nothing in the payload touches report or style, and
`modules/gongmun/tests/test_module_contract.py` asserts the module enables
alone.

- **The rules come from the 서식, not from a string list.** 「행정업무의 운영 및
  혁신에 관한 규정 시행규칙」별지 제1호·제2호서식 state their own rule in the
  비고 block — the guide vocabulary (`행정기관명`, `발신명`, `기안자`, `직위(직급)
  서명`, `처리과명-연도별 일련번호(시행일)`, …) must not be displayed, its content
  must be. That is the residue class; the section labels (`수신` / `경유` /
  `제목` / `협조자` / `시행` / `접수` / `직인`) are the keep-list. The checker
  carries no Korean literal it matches on: the vocabulary is data
  (`references/gongmun_vocabulary.json`) and each form's own 비고 block is
  parsed at run time and unioned into the term list.
- **Seat state is one mechanism, applied to 두문 / 결재란 / 결문 / 발신명의.**
  `blank_by_design` / `filled` / `emptied` / `half_filled` from the seat's own
  text; ○ runs and layout punctuation are stripped before "a value is present"
  is decided. Half-filled — not "empty" — is the failure mode a 결재란 row must
  never ship as, and the row check reads the table row rather than the seat
  list so a filled sibling beside a blank one is visible.
- **The 직인 slot is a placement, never a fill target.** The red-bordered 1×1
  box must survive carrying nothing but its label (`seal_slot_overwritten`,
  `seal_slot_removed`). Border colours are read only from borders whose `type`
  is not `NONE` — the corpus 발신명의 box declares `color="#FF0000"` on an
  undrawn border and a naive colour scan calls it a seal.
- **A blank form is not a failed 공문.** Document state is classified from the
  form's own evidence (비고 present + nothing written = `blank`), so both
  corpus 기안문 forms pass in their untouched state and report the unfilled
  shape. Rules that cannot be decided from the inputs given are listed under
  `skipped` with a reason (`no_baseline`, `seat_absent`,
  `pack_vocabulary_empty`) — never silently passed.
- **Evals**: `G1-gianmun-body-edit` gained two `check_gongmun` machine checks
  (blank-form shape, produced-draft structure).

### Engine — defects found by the second clean-room cross-model run (Opus)

- **T30 becomes preventable: a charPr pre-flight for fill targets.** T30 was
  detectable (`visual_verify`'s `fill_charpr_script_mismatch`) but not
  avoidable: `fill-cells` "preserves the run's charPr" is documented as the
  safe behavior, and on the PPS form cell (10,2)'s empty run carried a charPr
  identical to body text plus `<hh:supscript/>` — a correct-looking fill
  rendered at ~6.35pt raised, and finding the right `--charpr` id meant
  reading `header.xml` by hand, which the shipped "structure only, never dump
  body" contract actively discourages. Now: `form_inspect` reports
  `body_baseline_charpr` once at the top level and, on every `fill_target`
  cell, the `charpr` the fill would inherit, a `script_anomaly` flag, and
  `charpr_suggested` (plus `script_anomaly_targets` for the anomalies alone);
  `fill-cells` refuses an anomalous target that was given no explicit id
  (exit 3, `code_name` `fill_charpr_script_anomaly`, naming the cell, the
  anomalous charPr, the suggested id and the exact flag to pass) instead of
  silently producing the 6pt fill. The comparison itself — profile
  extraction, signature, body-baseline choice, difference test — moved to
  `engine/scripts/charpr_script.py` and is imported by BOTH the pre-flight
  and `visual_verify`, so the two halves cannot disagree; `preedit`'s
  `fill_target_run_charpr` is likewise shared with `form_inspect` so they
  cannot disagree about *which* run gets written. Non-target runs are never
  compared, so an intentionally superscripted footnote marker stays out of
  scope by construction. Corpus calibration (pinned by tests, not folklore):
  6 of the 10 converted corpus forms carry at least one anomalous target and
  `jeongbo-gonggae-cheongguseo` carries 18 of 19 — mostly a 2–5 pp `ratio`
  delta that is the form's own typography. The refusal stands anyway, because
  the post-flight gate compares the same five properties and would HARD on
  those fills later; loosening the pre-flight alone would produce the worst
  combination (pre-flight clean, gate refuses). To keep it workable the
  refusal names every anomalous target at once and carries `suggested_flags`,
  the ready-to-paste `--charpr-per-cell` argument list.
- **T32 — `--charpr` is batch-wide; new `--charpr-per-cell`.** `--charpr`
  applies to every target in the call, an undocumented constraint that is
  only safe when all targets share a charPr — exactly what the T30 pre-flight
  breaks. `--charpr-per-cell ROW,COL=ID` (repeatable) sets one target's id and
  wins over `--charpr`; an address it names that is not in the fill list, or a
  duplicate address, is a usage error rather than a silent no-op. The
  batch-wide scope is now stated in the CLI help, the docstring and
  `operations.md`.
- **cp949-safe `--help` on every shipped entry point.** `com_backend.py
  --help` died with `UnicodeEncodeError` (cp949, an em-dash in the top-level
  parser description) on a Korean-locale Windows console — the platform the
  COM path exists for. Subcommand help worked, which is why it went unnoticed:
  only the top-level `--help` prints the parser description. The stdout/stderr
  UTF-8 guard now runs at entry (before `parse_args`) in every shipped CLI —
  12 in `engine/scripts` via the new `engine/scripts/cli_io.py`, and in
  `pipeline/scripts` via `checker_base._utf8_stdio`, including inside
  `checker_base.cli_main` so every checker routed through it is covered by
  construction. 11 CLIs were broken and 8 more were latently unguarded. The
  real deliverable is `tests/test_cli_cp949_help.py`: it DISCOVERS every
  argparse entry point in both shipped trees and runs `--help` in a subprocess
  under `PYTHONIOENCODING=cp949`, asserting exit 0 with no traceback — so the
  whole class cannot be reintroduced by the next docstring.

### Module contract — the three gaps gongmun exposed

Shipping gongmun as the first module nobody had planned for disproved one of
the four contract rules and left two harness gaps. All three are closed.

- **Rule 4 was false for the test harness.** "Adding a module later requires no
  core change" held for the registry and not for the suite: pyproject's
  `testpaths` and CI's `py_compile` invocation were both hardcoded per-module
  lists. `testpaths` is now one glob (`modules/*/tests`), and the compile step
  is `scripts/py_compile_sweep.py`, whose pattern set includes
  `modules/*/scripts/*.py` and names no module (it also exits 2 rather than
  passing vacuously when nothing matches, and no longer needs `shell: bash` to
  get globs expanded on Windows). The W3-S1 acceptance test now proves the
  property instead of the mechanism: a brand-new module dropped into a
  synthetic checkout that carries the repo's real pytest ini block *verbatim*
  has its tests collected and its scripts compiled, with `pyproject.toml` as
  the only file outside `modules/` — plus a negative control (a broken script
  in the new module must fail the sweep) and guards against either
  configuration naming a module again.
- **Eval machine checks gained a per-module gate.** `machine_checks[]` accepts
  `requires_module: NAME`; where the sandbox's enabled set lacks it the check
  is skipped with a recorded reason instead of failing, with `blocked_on`'s
  semantics exactly (counted in `counts.skipped`, never in `counts.pass`, so
  neither `check`'s exit code nor `score.py` can read a skip as a pass). The
  enabled set is asked of the *sandbox's own* shipped registry CLI and recorded
  in `checks.json` as `enabled_modules`. Before this, a core-only sandbox
  *failed* G1's two gongmun checks — a red finding about a configuration the
  contract explicitly supports.
- **A checker can declare that it needs the blank baseline.**
  `provides.checkers[].wants: [baseline]` (closed vocabulary; schema, README,
  validator and `enabled_checkers()` accessor) says out loud what gongmun's
  `dumun_label_missing` / `seal_slot_removed` / `rank_not_in_pack` /
  `seat_emptied` rules only imply — they need the unfilled form, and without it
  they self-skip while the checker still exits 0. The clean-room eval harness is
  the wired consumer: a task declares `baseline: <input basename>`, and `check`
  resolves each `python` check's `argv[0]` by path against the sandbox registry
  and appends `--baseline <path>` for a declaring checker. A baseline already in
  the argv (explicit, or because the check targets the blank form itself — a
  document is never its own baseline) is left alone; a declaring checker in a
  task with *no* baseline is skipped with a reason rather than run for a silent
  pass. `declared_gates.py` is deliberately not wired: it only reaches checkers
  bound to a `gate_kind`, every input a delegated gate needs is already a
  declared value in the workspace's `gates.yaml`, and no module registers a gate
  kind whose checker wants a baseline.

### Engine — `visual_verify` acceptance and exit-code contract (T36)

Two P0 defects the CODEX clean-room A1 harness found across three model tiers.
Both are correctness-of-VERDICT: the verdict claimed more than it checked.

- **`acceptance: true` while safety checks were silently skipped.** The luna
  tier supplied a CLI `--fill-map` and still got `empty_cell_expected_fill`,
  `fill_charpr_script_mismatch` AND page parity into
  `deterministic.skipped[]` — then exit 0 with `acceptance: true`, because
  acceptance was computed as "no HARD finding" and never read the skip list.
  Now: `visual_verify.SAFETY_CHECKS` names, in ONE place, the five checks whose
  absence invalidates acceptance (`page_parity`, `xml_wellformedness`,
  `check_residue`, `empty_cell_expected_fill`,
  `fill_charpr_script_mismatch`); `_skipped()` returns `{check, reason}`
  records so a rule can match on them (the flat strings are still published for
  humans, plus `skipped_checks[]`); and a skipped SAFETY check makes the
  verdict `safety_incomplete` with a HARD `acceptance_safety_skipped` naming
  which and why, exit 3. `--accept-without CHECK` (repeatable, closed
  vocabulary) is the only way past it, recorded as `acceptance_waivers` — per
  check, never a blanket switch, and the skip is still reported. The pixel diff
  stays OUT of the set (T35: a renderer-less machine loses one check, not the
  run), as do the `format_noncompliance/*` tolerance legs.
- **`--fill-map` and `expectations.fill_map` were two inputs, not one
  concept.** The flag drove the residue keep derivation; the expectations
  MEMBER activated the declared-value presence check and the T30 charPr
  post-flight — so the flag looked sufficient and was not. The CLI map now
  SEEDS `expectations.fill_map` (`deterministic.fill_map_source` records which
  surface it arrived on); two DIFFERENT maps are a usage error rather than a
  silent precedence rule; `--fill-map` alone no longer requires
  `--form-profile`.
- **`pages_document` is no longer the caller's to remember.** The sol tier only
  got page parity because it hand-declared it: on the `--pdf` path there was no
  source at all. Parity now takes the first of conversion → expectations → the
  artifact's own `<hp:lineseg vertpos>` layout cache (`derive_pages_document`,
  excluding cell-relative linesegs inside `hp:tc`/`hp:subList`), records
  `pages_document_source`, and skips only when all three fail. Calibrated and
  pinned against the ten rendered corpus forms: the derived count never
  over-counts a form that stores no imposition, so on that source only the fold
  direction (`pages_pdf < pages_document`) is HARD and the under-count
  direction is a WARN naming both explanations — `nrf-gyeolgwa-bogoseo-yangsik`
  (`PrintMethod=4`, derives 4 against a 2-page PDF) is caught with nothing
  declared.
- **Exit-code contract, all six rows.** sol and terra both saw exit **1** for
  `vision_pending` where the contract says **3**. 3 is right (it is
  `checker_base.EXIT_HARD`, the finding/pending code of every checker); 1 was
  not a code at all but an unhandled path — `emit_verdict` sat outside every
  guard in `main`, so an unwritable `--out` escaped as a traceback after a
  perfectly good verdict. `--out` is now validated before the run and the
  emission is wrapped (an emission failure degrades to the usage row, 2), so
  **no path exits 1**. `test_exit_code_matrix` pins one row per terminal state
  — `pass` 0, `deterministic_pass` 0, `vision_pending` 3, `fail` 3,
  `safety_incomplete` 3, `usage_error` 2 — and the docstring/`operations.md`
  table is asserted against the code.

## v0.16.0 — unified core and modules

The whole v0.16 program (`docs/plans/v0.16-unified-core-and-modules.md`):
rigorloom becomes a general HWP/HWPX document engine — one core, with the
report, style, and personalization capability split behind a distribution-
module contract and shipped as separately installable bundles
(`rigorloom-core`, `rigorloom-report`, `rigorloom-style`) built by
`scripts/package_module.py` at this same version. Everything below landed
on `main` between `v0.15.0-alpha` and this tag.

### Wave 1 — converge (field guards, audit verdicts, packs)

- **#29** (`v0.15 follow-up: feature-classification fixes + v0.16 master
  plan`) — the first real corpus run surfaced five section-level rendering
  element names (`pageBorderFill`, `visibility`, `startNum`, `grid`,
  `lineNumberShape`) that a blanket-benign classification would have made
  fail-open in `feature_extract.py`; they now emit attribute- and
  whole-subtree-fingerprinted feature classes (`sec-config:<tag>:<fp>`), so
  a document certifies only under the exact section configuration the
  corpus measured. Also added the v0.16 master plan and its companions.
- Lane F field guards (branch `lane-f-guards`) — T16 (header-height
  double-count), T18 (guide-text deletion must protect table/secPr/ctrl
  paragraphs), T21 (per-machine lock; refuse a name-scoped `Hwp.exe` kill
  while another owner's instance is live), and T22 (charPr id guards must
  match `<hh:charPr\b[^>]*\bid="34"`, not a substring) landed as testable
  primitives, each with a failing-before/passing-after test.
- **#30** (`docs: audit performance metrics + Phase 0 judgment verdicts`) —
  variant-audit metrics section as the Lane V exit criterion; recorded the
  extension-packs ABSORB verdict (v0.13.1 conditions).
- **#31** (`research: variant-audit decision matrix (Phase 0.C complete)`)
  — `docs/research/variant-audit.md`: five differential benches over
  existing artifacts (zero pipeline reruns). Headline findings: all five
  audited variants' recorded state diverged from reality; `score_ai_tells`
  showed zero discrimination on a 25%-changed section. Verdicts: hybrid
  gate architecture with form-scan auto-derived residue lists, two run
  modes plus a mandatory provenance floor, H2 advisory-only, and five
  shared-miss mechanisms.
- **#32** (`packs: land v013 extension packs with v0.13.1 policy
  conditions`) — landed the data-only extension-pack system
  (`scripts/extension_pack.py`, `docs/extensions.md`) with
  `constants_allowlist` excluded from `DATA_EXTENSION_PACK_TYPES` (a
  confirmed relaxation vector for `check_numbers`' deterministic numeric
  checker), and fixed the `merge_pack`/`_stable_union` regression where a
  global `gloss_allowlist` pack erased the 14 W5b neutral defaults.
- Lane V engine ops (branch `lane-v-engine-ops`) — audited, idempotent
  preedit/postedit XML operations adopted per the audit's
  form-preprocessing matrix row.
- **#33** (`gates: residue auto-derivation, H5 density, canonical binding,
  verdict contradiction`) — four shared-miss checkers: `check_residue.py`
  (the form scan's anchor/guide-text inventory auto-derives the artifact's
  forbidden list; a missing pinned target is HARD), `check_density.py` (H5
  bold-subhead density per 10k bytes, WARN >= 3.0 / HARD >= 4.5),
  `check_canonical.py` (declared canonical/`FINAL` pointer must resolve),
  and `verdict_schema.py` (rejects `converged: true` +
  `status: escalate_human`, wired into `submission_preflight`).
- **#34** (`gates: malformed artifact XML is HARD in check_residue`) —
  `check_residue.py` XML-parses every hwpx section/header member before
  scanning; a parse failure is a HARD `artifact_malformed` finding. Found
  live: a corrupt `section0.xml` passed the prior regex scan while Hancom
  rendered the document blank (T23).
- Engine XML hardening from live form work (direct merges): fixed
  self-closed `<hp:t/>` corruption in tier-A replacement and added a
  post-op well-formedness invariant to every preedit chain; stale
  `linesegarray` is stripped from exactly the paragraphs whose text was
  modified (Hancom otherwise draws the old cached layout over the new
  text); paragraph-scoped charPr repoint for split-run recolor, with the
  forensic finding that **Hancom resolves `charPrIDRef` by array
  position** — clones are now appended at the end of `charProperties`
  (never mid-array) and an `id_position_mismatch` diagnostic is reported.
- Verdict-writer consistency fix (shared-miss #5, direct merge): a proof-
  phase escalation now demotes `converged` to `false` (preserving
  `phase1_converged`), so the writer can no longer emit the contradictory
  pair `verdict_schema.py` rejects.
- **#35** (`docs: reopen/amend transition design`) — append-only
  amendments, receipt-signed reopen/amend-close, and the `unrecorded_edit`
  HARD backstop on canonical-hash mismatch with no open amendment.
- **#36** (`gates: declared-values runner with canonical binding and
  holdout enforcement`) — the hybrid gate architecture's composition point:
  a declarative per-workspace gate runner (audit winner semantics) where a
  missing pinned target is HARD `target_missing`, each gate records
  mtime+sha256 staleness, `workspace_slug` holdout refusal is enforced, and
  the residue/density/canonical kinds delegate to registry mechanisms.
- **#37** (`docs: version reality sync`) — README/SUMMARY/CHANGELOG aligned
  with the v0.15.0-alpha tag and post-tag merges (Lane F item F3).
- **#38** (`humanize: tone-rulepack mechanism, H2 advisory-only,
  measurement roles doc`) — deterministic tone-rulepack regression check
  (`check_tone_rules.py`: hedge-on-measured-value and
  conclusion-pivot-density rule kinds, WARN-only by default), `tone_rules`
  as a first-class pack type with a neutral default (the corpus-derived
  rulepack stays a private profile pack), and a regression test pinning
  that no code path gates on detector scores (H2 advisory-only).
- **#39** (`docs: CHANGELOG backfill v0.11.4–v0.15.0-alpha`) — six missing
  release entries reconstructed and verified against tags.

### Wave 2 — absorb hwp-master

- **#40** (`W2: absorb hwp-master as engine/ (history-preserving) + seam
  collapse`) with **#43** (`restore subtree ancestry`) — the hwp-master
  repo (COM backend, COM-free XML assembly engine, form inspection, fill,
  tidy, layout QA, eqn converter, render calibration; its own v0.1–v0.3
  history and 246 tests) is merged into this repo at `engine/`, with the
  full 29-commit engine history restored as ancestry after a squash
  flattened it. The seam is gone: the `HWP_MASTER_SCRIPTS` delegate
  indirection collapsed into direct paths (kept only as an optional
  override), the pointer SKILL file was deleted, and hwp-master's version
  line ends — everything ships on rigorloom's single version from v0.16.
- **#41** (`ci: guard optional deps (PIL/fitz) in engine tests`) — engine
  runtime deps (pillow) joined CI installs and an `engine` extra was added
  to `pyproject.toml`.
- T25 (`engine: open_hwp fails loudly on missing input`) — a missing input
  path is an immediate error, not a silent empty document.
- **#42** (`pipeline: reopen/amend transitions`) — the #35 design
  implemented: append-only amendment records, receipt-signed
  reopen/amend-close, amending stage status with `done_at` preserved,
  canonical invalidation marker, and guards (double-open, unknown id,
  non-done reopen).

### Wave 3 — the distribution-module contract

- **#44** (`W3-S1: distribution-module contract, registry, core-only CI
  guard`) — `modules/<name>/module.yaml` + `module.schema.json` +
  `pipeline/scripts/module_registry.py`: a module declares checkers, CLI
  commands, pack types, run modes, gate kinds, studio panels, preflight
  contributions, and a skill fragment; core never imports a module; the CI
  matrix gained the core-only / all-modules points **before** anything
  moved, and a throwaway module proves zero-core-change extension. Project
  version moved to `0.16.0.dev0` (the registry's version gate reads
  `pyproject.toml`).
- **#45** (`W3-S2a`) + **#48** (`W3-S2b`) — everything report-shaped moved
  into `modules/report/`: the seven cleanly-severable report checkers +
  `source_fetch`, then the stage machine as one unit (`pipeline_ctl`,
  `compose`, `workflow_lint`, `stages*.yaml`, `aliases.yaml`, the
  stage-contract catalog `modules.yaml`, all 24 playbooks) plus the
  workspace-bound checkers and the claims/sources chain.
  `submission_preflight` split: core keeps the artifact/proof half and
  gained a generic `preflight:` composition hook; the report module
  contributes P0/P4/check_saeteuk through it. Core resolves the stage-
  machine CLI only through the registry; on a core-only install every
  report entry point is a loud, named refusal — never a silent pass.
- **#49** (`W3-S3: registry-driven studio panels + per-module packaging +
  gate-kind registration`) — studio stays the core base surface and
  enabled modules extend it declaratively (`GET /api/panels`; the report
  module's content-audit action moved into its own panel); gate kinds are
  registry-declared (`provides.gate_kinds`, params validated against the
  delegate's signature at declaration time); and
  `scripts/package_module.py` builds standalone bundles — `--module
  <name>` for module payloads, `--module core` for the engine + pipeline +
  studio + contract, with `MANIFEST.json` (per-file sha256), `INSTALL.md`,
  `privacy_scan` over the staging dir (any HARD refuses the build), and
  `--verify` tamper detection against the manifest.

### Wave 4 — style and personalization as modules

- **#50** (`W4.2: style module + requires_modules contract key`) — the
  humanization stack (`humanization_ctl`, `prose_fidelity`, `check_style`)
  consolidated into `modules/style/` with the boundary stated in its
  README: translationese removal, voice consistency, form-rule compliance
  — **not AI-detection evasion**; rules come from packs. The contract
  gained `requires_modules` (inter-module dependencies enforced at
  enablement; `report` declares `requires_modules: [style]` because
  `content_audit` composes `check_style` through the registry).
- **#51** (`personalization: general/report pack split, store portability,
  schema rename w/ compat`) — core `personalization_ctl` declares only
  general pack types (`prose_rules`, `figure_style`, `backends`,
  `policy_floors`); the report-flavored five (`saeteuk`,
  `report_structure`, `gloss_allowlist`, `constants_allowlist`,
  `tone_rules`) are report-module payload, with `PACK_TYPES` /
  `DATA_EXTENSION_PACK_TYPES` computed from core built-ins +
  `ModuleRegistry.enabled_pack_types()` and the trust-sensitive set
  (`backends`, `policy_floors`, `constants_allowlist`, `tone_rules`) never
  extension-installable, re-enforced at resolve. Store schema renamed
  `report-pipeline/personalization-v1` → `rigorloom/personalization-v1`
  (legacy accepted on read, warned once). New `export`/`import` CLI:
  manifest+sha256 zip of the profile root that never includes the privacy
  denylist; import verifies byte-for-byte and refuses tamper and non-empty
  targets. `privacy_scan` gained the profile-store leak marker classes
  (`profile_store_content` / `profile_store_path`, both HARD), so
  packaging refuses any bundle staging store content.

### Wave 5 — landscape, evals, skill surface

- **#47** (`research: HWP usage landscape (W5.1)`) —
  `docs/research/hwp-usage-landscape.md`: seven form families with
  capability priorities. Headline: 행안부 mandates HWPX-only attachments on
  government systems since 2026-05-18, making hwp→hwpx conversion fidelity
  capability priority #2.
- **#52** (`W5.2: blank-form corpus + eval scenarios + pinned privacy
  allowlist`) — `tests/corpus/forms/`: 12 blank official templates across
  5 families, sha256/source/license manifest, 5 recorded skips (school
  family = corpus gap; corp family = documented no-official-source
  boundary); `docs/research/form-eval-scenarios.md` with 10
  open→recognize→fill→verify scenarios. `privacy_scan` gained
  `--binary-allowlist` (sha256-pinned, auto-detected at the corpus
  manifest): unlisted binaries and hash drift stay HARD, allowlisted files
  are still content-scanned (`binary_pii_rrn` / `binary_pii_phone` + the
  existing nets over extracted hwpx XML or a UTF-16 harvest of binary
  hwp), and bundles never apply the allowlist — a regression test asserts
  no corpus member lands in any bundle.
- **#53** (`W5.3: skill surface`) — `skill/SKILL.md`: a 98-line-body
  router (paths-gated frontmatter, task routing table, freedom map,
  one-level-deep references: `operations.md` / `forms.md` /
  `troubleshooting.md`); `engine/scripts/probe.py` — one compact-JSON
  capability probe merging `render_probe` + module registry summary +
  optional backend precheck, never raises; report/style modules declare
  `provides.skill` fragments and `sync_local.py` merges them at install
  (a core-only buyer never sees report vocabulary); A1/A2 machine-check
  evals executed against the corpus (all pass, non-vacuous negative
  control; agent-in-the-loop half is operator-run). Suite hygiene: the
  test suite no longer writes the repo profile store (session-scoped
  guard asserts it).

### Wave 6 — prove, bound, release

- **#54** (`W6.1: XC-1 conversion bench`) — all 10 `.hwp` corpus members
  converted to `.hwpx` via the COM backend (Hancom 13.0.0.2986), strictly
  serial: **10/10 OK, zero hangs/retries**; `form_inspect` recognition
  table now covers 12/12 corpus members; converted hwpx + rendered PDFs
  folded into the pinned manifest. Full writeup with honest limitations in
  `docs/research/xc1-conversion-bench.md`.
- **#55** (`fix-or-bound: XC-1 findings`) — every XC-1 open finding fixed
  with a regression test or documented as a capability bound (bench doc
  §9): guide-text detection generalized to mechanism-level pattern classes
  (note-prefix / example-mark / instructional verbs; 11/12 forms now
  detect, and admrul's 0 is locked as a *correct* zero by a bound test);
  COM inspect no longer counts every `gso` drawing control as a picture
  (UserDesc-classified, new `shapes` field); the nrf PDF page drop was
  root-caused to the document's own stored 2-up print imposition
  (`PrintMethod=4`) — convert now stages a print-normalized copy and
  always reports `pages_document` vs `pages_pdf` with a loud WARN on
  mismatch; `check_convert_parity` gained a guarded `.hwp` source leg
  (structural counts HARD, text advisory).

### Migration

- **From a standalone hwp-master install**: the engine is bundled at
  `engine/` — point automation at `engine/scripts/` (same script names);
  `HWP_MASTER_SCRIPTS` still works as an override but is no longer
  required. The hwp-master repo is absorbed; its tags end at v0.3.0.
- **From pre-module rigorloom (≤ v0.15.0-alpha)**: report-pipeline scripts
  moved from `pipeline/scripts/` to `modules/report/scripts/` (stage
  machine, compose, report checkers) and the humanization stack to
  `modules/style/scripts/`; enable modules with
  `python pipeline/scripts/module_registry.py write-enabled --all` (an
  absent `modules/enabled.yaml` means core-only, where report entry points
  refuse loudly by design). Personalization stores using the old
  `report-pipeline/personalization-v1` schema strings are accepted on read
  and rewritten on the next lock update.

Suite at release: core-only 866 passed / 565 skipped; all-modules 1293
passed / 138 skipped; repo-wide `privacy_scan` HARD 0. Bundle inventory and
verification evidence: `docs/release-v0.16.0.md`.

## v0.15.0-alpha — renderer certification harness

- Added `feature_extract.py` + `render_cert.py`: a renderer certification
  harness that binds a document's feature envelope (train/holdout stats) to a
  corpus hash and an operator key; every section-body element is classified
  handled, explicitly known-benign, or `unknown:<local-name>` over a full
  tree walk, and unrecognized elements outside `<ctrl>` direct children fail
  closed (#28).
- Certificate trust hardened after an adversarial audit: `verify_certificate`
  re-derives the envelope and train/holdout stats from the hash-anchored
  manifest plus the certificate's embedded measurement records and refuses on
  any mismatch, and certificates are HMAC-SHA256-signed over canonical bytes
  with a private operator key (`receipt_sign.py`, 0600 owner-only key at issue
  time) — a widened or fabricated certificate with a recomputed self-hash no
  longer verifies (#28).
- Registered the Stage 2.5 layout gate: `check_layout.py` locates hwp-master's
  `layout_plan_check.py` via `HWP_MASTER_SCRIPTS` (the checker had shipped
  null in `stages.yaml`, blocking composed pipelines — found live by the
  held-out sample run); a follow-up fix corrected a wrong `cli_main` call
  signature that had crashed the delegate at CLI entry.
- docs: Linux HWP/HWPX tooling research (#26) — on WSL2 x86_64 and OCI ARM64,
  `rhwp` 0.7.19 and the hwplib+hwp2hwpx+hwpxlib Java family both convert
  HWP<->HWPX at 0.0 px displacement under Hancom re-render on sanitized
  fixtures (rhwp SVG previews at 22-87 ms/page); LibreOffice+H2Orestart stays
  advisory (645 px worst case); corrects the previously-cited 676.33 px figure
  as a render-tree metric, not a LibreOffice PDF measurement.
- docs: v0.15 renderer certification plan (#27) — Hancom as the certification
  facility.
- Suite: 634+1 passed (was 625+1); privacy scan HARD 0.

## v0.12.4 (v0.12-W5) — gate recalibration from the real-report campaign

- Measured on 13 real workspaces (39 gate runs, 0 crashes); every relaxation
  is mechanism-level and ships a still-catches adversarial test, and an
  independent overfitting audit classified all changes, resolving its one
  OVERFIT verdict here.
- H1 web-citation ban: URLs inside the recognized reference section are now
  exempt (12/12 campaign hits were bibliography lines); body URLs stay HARD.
- `unbacked_numeral`: ledgered claims (resolvable source + evidence) back
  matching numerals; added a `constants_allowlist` pack type (schema-
  validated, additive operator override) with universal-only public defaults
  (g, c, pi, absolute zero, metric conversions).
- Gloss ban: unit symbols from the shared unit dictionary are exempt; neutral
  software-name defaults (SymPy/NumPy/MATLAB/...) extend rather than replace;
  the exemption path is tightened to exact-parenthetical match. Reference-
  heading and TITLE-matcher recognition are limited to the documented section
  grammar; corpus-specific activity-sheet keys moved to an optional
  `report_structure` pack field instead of a public default.
- Root-caused and fixed `extraction_infidelity`: the EQ tag regex misparsed
  hwpeqn scripts containing square brackets (parser correctness fix, no
  tolerance widened). Added `docs/gate-calibration.md` as the aggregate
  calibration record.

## v0.12.3 (v0.12-W4) — transform modules: extraction, form conversion, taste mining

- `content_extract.py`: hwpx -> `content.md` inverse extraction (stdlib
  zip+XML) with ordered paragraphs, direct-row table walk, and cell-level
  picture/equation recursion; `--verify` cross-checks independent source
  fingerprint counts against the extracted counts and the NFC text hash, so
  textless structure can no longer vanish behind a green verify.
- `check_convert_parity.py`: a form-convert gate comparing normalized text
  hash, element counts, normalized equation SCRIPT text, and independent
  source-walk fingerprints of both hwpx files.
- `form_extract.py`: form skeleton + fill-slot inventory from multiple
  instances; on skeleton divergence the inventory is suppressed instead of
  shipping misaligned data. `style_extract.py`: corpus -> DRAFT prose/
  structure packs, schema-validated at emit, `draft:true` + corpus sha256
  provenance, never auto-installed.
- New aliases (form-convert, form-edit, taste-mine, form-mine) and fixtures
  (picture-in-cell, equation-in-cell, nested-table, extra-row) with honest-
  PASS / tampered-HARD round-trips.
- Suite: 578 passed; privacy 0 HARD.

## v0.12.2 (v0.12-W3) — claim ledger + write-through source cache

- `claims.yaml` ledger (schema + `claims_ledger.py`): every factual claim
  bound to evidence `{source_id, locator, quote}`; stable ids, duplicate and
  dangling-source detection; `claim_extract` subcommand seeds a mechanical
  skeleton for backfill.
- `check_claims` added as the 9th `content_audit` sub-checker: unledgered
  numeric/citation content WARNs (escalates to HARD under
  `--require-ledger`); a ledgered claim with a dangling source is HARD; a
  numeric/citation claim with zero evidence is HARD; URL-only sources WARN;
  no ledger at all stays a single legacy-safe WARN.
- `source_fetch.py` write-through cache CLI records DOI/ISBN verification
  into the schema `check_sources` reads; a different-title overwrite is
  refused unless `--force`.
- Closed a self-dealing hole: cache records without retrieval metadata
  (`retrieved_from` + content sha256 + timestamp) are non-authoritative — a
  title match no longer suppresses `source_unverified`.
- `topic_pick` registered as an ENFORCED stage-0 human gate; `claim_extract`
  and `retro_research` aliases activated.
- Suite: 550+ passed; privacy 0 HARD.

## v0.12.1 (v0.12-W2) — checker_base refactor

- `checker_base.py`: shared verdict skeleton, usage/exit conventions,
  `_utf8_stdio`, strict JSON (`allow_nan=False`), CLI frame; all 8 checkers
  migrated behavior-preservingly, each keeping its own logic and standalone
  CLI.
- `claim_extraction.py` unifies the previously-diverged
  check_saeteuk/check_units/check_numbers dictionaries into one subject/
  unit/number extraction pass.
- `content_audit` sub-checkers now compose in-process (no subprocess spawn);
  any checker exception becomes a hard finding with a truncated traceback,
  while `SystemExit`/`KeyboardInterrupt` still propagate.
- `check_saeteuk` added as an ADVISORY 8th `content_audit` sub-checker: its
  contradiction HARDs surface as WARN at stage 4.5 for early discovery, while
  stage 6 keeps full HARD enforcement of the same workspace-local artifacts.
- Independent opus review confirmed the refactor behavior-preserving; suite:
  524 -> 530 passed, privacy 0 HARD.

## v0.12.0 (v0.12-W1) — composable module contracts + resolver

- `pipeline/references/modules.yaml`: 16 typed module contracts (consumes/
  produces/stage/gates/os); not-yet-implemented modules are declared
  `status:planned` and refused by the resolver.
- `compose.py`: a backward DAG resolver (`--have`/`--want`/`--alias`/`--dry`/
  `--apply`/`--matrix`) with cycle detection; ambiguity is always an error,
  never a silent choice.
- Review round closed before merge: composed plans always retain gate-bearing
  stages (2.5, 5.3/5.5/5.7/6); intake gate receipts are verified via
  `workflow_lint._receipt_satisfies_h1`; recompose refuses to discard
  non-pending stage/gate state.
- `aliases.yaml`: full-report/pre-researched/verify-only/assemble-only
  active; `docs/capability-matrix.md` generated per-alias; CI smoke asserts
  chain content on ubuntu+windows.
- R3: open-source repo surface — hero README (badges, mermaid pipeline
  diagram, project-status honesty section), CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, issue/PR templates.
- Suite: 514+ passed; privacy 0 HARD.

## v0.11.4 — Linux equation-render parity P0 (experimental) + release consolidation

- Added `pipeline/scripts/hwpx_render_surrogate.py` (canonical-immutable
  render-only HWPX copy for experimental renderers, proven via SHA-256 plus a
  runtime semantic fingerprint) and `pipeline/scripts/rhwp_proof.py` (a
  fail-closed experimental SVG proof runner that always writes `receipt.json`
  with an explicit fallback reason on any failure mode).
- `render_probe.py` mandates a `RHWP_SHA256` pin at both probe and exec time
  (unpinned/mismatched binary is never surfaced as available);
  `doc_backend.py`'s proof-grade ladder becomes
  `none < experimental-rhwp < advisory < hancom`, selecting `rhwp_svg` only
  for equation docs when Hancom is unavailable (equation-free docs keep their
  `soffice` advisory grade); `submission_preflight.py` hard-blocks
  `experimental-rhwp` from submission — unlike `advisory`, it cannot be
  waived with `--allow-advisory`.
- Added `adapters/hancom-linux-sdk/README.md`: an interface-and-evaluation-
  plan-only contract for a future Hancom Linux SDK adapter (0.5 mm
  baseline/bbox error and 300 dpi SSIM >= 0.995 acceptance matrix); no
  commercial SDK, credential, or runtime integration included.
- R1: docs realigned with v0.11.3 reality — README (release version,
  kernel-schema vs release-version distinction, four-backend table with
  proof-grade ceilings, Studio read-only default), `pyproject` rename
  `agent-report-pipeline` -> `rigorloom`, `docs/golden-path.md` single
  end-to-end walkthrough, CHANGELOG backfill for v0.7.0-v0.11.3.
- R2: documented the experimental rhwp path post-P0 merge (README backend
  table + experimental section, golden-path "equation documents on Linux
  (experimental)" subsection); externally-supplied pixel metrics stayed
  tagged `provenance: external` rather than restated as repo facts.
- Honest status: `docs/plans/p0-parity-report.md` records this work as
  **PARTIAL** — canonical-preservation and semantic-fingerprint parity are
  reproduced in this repository, but pixel-level parity with Hancom rendering
  is not achieved (max displacement 676px externally reported, `provenance:
  external`, `reproducible: false`), so COM stays the submission-grade proof.

## v0.11.3 (v0.11-Z5) — anti-fabrication frontier

- Added `check_sources.py`: offline citation-reality verification against a
  local DOI/ISBN cache under `<PROFILE_ROOT>/cache/sources/`; HARD only on a
  provable-fake reference, WARN otherwise.
- Added `check_saeteuk.py`: deterministic saeteuk-to-report numeric and
  named-entity consistency checker, composed into `submission_preflight.py`.
- Added `check_units.py` as the seventh `content_audit` sub-checker: WARN-only
  unit/dimension consistency over a deterministic SI + Korean unit dictionary.
- `content_audit.py` now runs all seven sub-checkers (verify_content,
  check_style, check_numbers, check_refs, check_figdata, check_sources,
  check_units) and merges verdicts with worst-exit-wins semantics.
- Follow-up hardening passes closed 9 fail-open and 4 false-block findings
  from an adversarial review round, plus a design-review calibration pass on
  gate semantics, generic-subject handling, and cache robustness.
- Limitation: source verification is offline-cache-only — an unlisted but
  genuine reference is not distinguishable from a genuinely fabricated one
  without network access, which this checker deliberately does not use.

## v0.11.2 (v0.11-Z4) — figure/form integrity batch

- Added figure-data integrity check: a referenced PNG with a sidecar
  `<f>.sha256` or figure manifest is HARD-checked against the sim output; no
  manifest is WARN `figure_unverified` (legacy workspaces tolerated).
- Added the form-hash gate to `submission_preflight.py`: the assembled HWPX's
  FORM-owned structure hash (charPr/paraPr/secPr/tbl/tc/ctrl skeleton, text
  excluded) is recomputed and compared against `form_baseline.json` or
  `build.yaml`'s recorded digest; mismatch is HARD `form_mutated`, no baseline
  is WARN `form_baseline_absent`.
- Added corpus consistency checks and a sync orphan garbage-collection fix for
  `sync_local.py`.
- Limitation: the form baseline is trusted-on-record, not cryptographically
  proven — a baseline recorded after a mutation cannot detect that mutation.
  A signed external baseline is deferred.

## v0.11.1 (v0.11-Z3) — numbering lint, snapshots, sync stamp

- Added figure/table numbering + cross-reference lint into `content_audit`:
  scans `bundle/content.md` for monotonic 그림/표 numbering and resolves
  in-text cross-references; skipped/duplicate numbers or dangling references
  are HARD, ambiguous forms are WARN.
- Added `ws_snapshot.py`: zips `bundle/`, `output/`, `PIPELINE.md`, and
  `.pipeline/` into a rotating pre-assembly snapshot before Stage 5, with a
  symlink-safe, zip-slip-resistant `restore` command.
- Added a sync version stamp to `sync_local.py`'s per-file receipts.

## v0.11.0 (v0.11-Z2) — format gate, fabrication checks, delivery integrity

- Registered `verify_format.py` as the Stage 5.3 `format_check` script gate
  (previously advisory prose only); it hard-enforces body font size, line
  spacing, and — with `--require-output` — that `output/out.hwpx` exists,
  which makes `bundle`- and `docx`-only builds fail this gate by design.
- Added simulation seed provenance requirements (an empty RNG seed now fails
  the `sane` gate) and a prose-numeral-vs-`results.json` diff check.
- Added operator preference-pack schema validation ahead of every sub-checker,
  and pack-enforcement findings that fail closed on an invalid pack.

## v0.10.0 — typeset parity without Hancom, Studio/Linux integration

- `pipeline/scripts/render_probe.py` added: a stdlib-only, self-guarded probe
  for Hancom COM, `soffice` (local and via WSL), and the H2Orestart
  LibreOffice filter; never launches Hancom, never raises.
- `doc_backend.py`'s `hwpx` dispatch gained automatic advisory-proof wiring:
  it picks Hancom when available, otherwise a `soffice` renderer for
  equation-free documents only (equation-bearing documents get `proof_grade:
  none`, since H2Orestart's equation fidelity is unverified).
- Studio gained Linux-compatible capability probing and render-status chips.
- Recorded, in the v0.10 plan, that LibreOffice+H2Orestart equation fidelity
  is a known, deliberately excluded gap — not a bug to be silently patched
  over.

## v0.9.0 — Hancom-free document stack (hwpx tier)

- Added the `hwpx` Stage 5 document backend: an external hwp-master XML
  engine that fills a form's HWPX/OWPML XML directly, without Hancom or COM,
  on any OS. `doc_backend.py` dispatches to it via `HWP_MASTER_SCRIPTS`.
- Added Studio v2 (dashboard, provenance view, lint badges, token-guarded
  action endpoints) and an edit-workflow graph with an off-workflow
  conformance linter.
- Added humanization v3: pack-driven voice, a deterministic pre-pass, and a
  no-progress hold to stop runaway rewriting.
- Limitation, stated plainly at the time: LibreOffice+H2Orestart rendering
  fidelity for equations and complex forms was undocumented and unmeasured;
  the tier was labeled advisory proof from day one, not submission-grade.

## v0.7.0 — gate integrity convergence

- Converted the kernel from documentation-enforced to gate-enforced: the
  `check` subcommand now actually runs a stage's bound checker and records
  its verdict; the old `--script-exit` caller-supplied-integer path was
  retired, closing the "gate passed with a typed 0" hole found in an
  unattended run.
- Added the Stage 4.5 `content_audit` gate (freeze content before assembly)
  with its first deterministic checkers (content, style, format, figures,
  privacy).
- Added the preference-pack system v2 (schemas, neutral defaults, hash-only
  lock) and the `sync_local.py` base+overlay installer with drift refusal and
  atomic swap.
- Fixed POSIX portability issues (flock-based lock liveness, platform-agnostic
  figure paths) surfaced by running the pipeline outside Windows for the
  first time.
- Limitation acknowledged in the v0.7 plan: without a release attestation
  step, this is gate *integrity*, not full fail-closed — a direct-assembly
  bypass of the state machine remained possible until later waves narrowed it
  further.
