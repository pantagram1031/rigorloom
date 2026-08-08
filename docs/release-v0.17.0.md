# Release record — v0.17.0

Prepared on branch `v17-release` from `main` @ `37400a8` (#77). This record
is the evidence trail for the v0.17.0 tag: bundle inventory with hashes, the
suite matrix, privacy status, the **validation ledger** (who ran what, and the
25 defects those runs found), and the honest list of limits. The tag itself is
applied separately by the operator after reviewing this record.

The bundle hash table below was regenerated on branch
`v17-reproducible-bundles` (from `main` @ `199f20a`, #78) once bundle builds
were made reproducible; every other section stands as prepared.

## What this release is

v0.16.0 shipped as an **alpha**, and the word was accurate: it was written by
its authors, run on its authors' machine, exercised on one form-family lineage,
and only ever against empty forms. Nothing outside the authoring loop had
touched it.

v0.17 is the release that validated it. 21 commits, PRs #57–#77, in four
movements:

1. **Autonomous verification** — the system judges its own rendered output with
   no human in the acceptance loop: a closed 12-class visual rubric, a
   deterministic render-judge driver, an acceptance safety set that makes
   `acceptance: true` impossible over an unwaived skipped safety check, and a
   pinned six-row exit-code contract (#57, #61, #64, #75, #76).
2. **Clean-room validation** — a harness that installs the product from dist
   zips into a throwaway root with no code path back to the checkout, and
   asserts containment on five independent axes (#58, #59). Three measured
   cross-model rounds produced a routing table that ships with the product
   (#63, #72); an independent Codex harness across three tiers then found two
   P0 verdict defects ours could not (#75).
3. **Four new work-type modules**, each with zero edits outside its own
   directory: `gongmun`, `minwon`, `hr`, `grant` (#65, #68, #69, #70) — six
   distribution modules and seven bundles in total. The three contract gaps the
   first unplanned module exposed are closed (#67), and the inventory-pin
   defect class that had been blocking modules is guarded against (#71).
4. **A complete offline fill path** — genuinely empty cells (T27), printed
   seats without their exact whitespace (T34), single-pass replace (T26), real
   `cellAddr` COM addressing (T28), a charPr pre-flight that refuses instead of
   rendering at 6.35pt (T30/T32), one `--fill-map` shape rule (T35), spacer
   classification, and one canonical fill recipe (#60, #62, #66, #73, #74,
   #76, #77).

Per-PR breakdown: `CHANGELOG.md` "v0.17.0 — validated product".

## Bundle inventory

Built by `scripts/package_module.py` (staging privacy-scanned by the packager;
any HARD refuses the build with exit 3 and writes nothing) and re-verified with
`--verify` (per-file sha256 against `MANIFEST.json`; mismatch, missing, or
unlisted file is exit 3).

| bundle | files | zip sha256 |
|---|---:|---|
| `rigorloom-core-0.17.0.zip` | 98 | `23758a0f24981299fd16a1a95c88dd8a9ee16207551f291c1b2930e948d8c01b` |
| `rigorloom-report-0.17.0.zip` | 87 | `03b8750fe7327b2173549b2049742b39d7b60998705cf0f35afd75d4ea98626c` |
| `rigorloom-style-0.17.0.zip` | 14 | `8fe375a2f3b73ebaa850c3010eb1a2c27c473668fa771a482a3f9f7493bcb8ed` |
| `rigorloom-gongmun-0.17.0.zip` | 14 | `199165c45de0321e98cecb3161e5cde5c471ddcef8e7018b79d08c91affc163a` |
| `rigorloom-minwon-0.17.0.zip` | 12 | `be2fb5def31f2e7f4f613ff5506638679139aeffd583a2417f51c99263c47e2b` |
| `rigorloom-hr-0.17.0.zip` | 12 | `360ac0c97eddf2b057c3b4317a286fe33408c7f36a2c99b7c7bb12d1d0172f36` |
| `rigorloom-grant-0.17.0.zip` | 12 | `8ff20755f261760f73d490d430e41165ea74b14c237d9614dc42d0d85f42e08c` |

`files` is the MANIFEST.json payload count, matching what
`package_module` prints; the zip carries one more entry (the manifest).

All seven `--verify` runs: `ok: true`, zero problems. Bundles live in `dist/`
(gitignored, never committed).

**These builds are reproducible: the same tree produces the same bytes.** To
check the table yourself, from a checkout of this commit:

```sh
python scripts/package_module.py --module core --out dist
sha256sum dist/rigorloom-core-0.17.0.zip     # certutil -hashfile … SHA256 on Windows
```

Repeat per bundle (`core`, `report`, `style`, `gongmun`, `minwon`, `hr`,
`grant`); each digest must equal the row above. You do not need this repo's git
history, only its tree.

This replaces what the earlier draft of this record said, which was accurate
when it was written: the packager stamped zip members with their staging
mtimes, so *any* rebuild — even a no-op — produced a different zip sha256, and
a hash a reader cannot re-derive is not evidence. Building `core` twice from an
unchanged tree was measured at `97092d2e…` then `71943ea9…`. Everything a zip
member records other than its name and its content is now pinned: member
timestamps to a fixed 1980-01-01 (a constant, deliberately not the commit date
— a reader with the tree but not the history would derive a different one),
permissions to 0o644, `create_system` to Unix, deflate level to 9, and member
order to sorted-by-path. `MANIFEST.json` was audited for the same problem and
carries no build time, absolute path, or iteration-order-dependent list.
`tests/test_package_module.py::TestBundlesAreReproducible` builds every bundle
twice per run and asserts byte-identity, including after an mtime-only change
to the payload.

One residual, stated rather than papered over: the compressed bytes come from
whatever zlib the building Python links. Level 9 is pinned, and every CPython
build tested here agrees, but a materially different deflate implementation
(zlib-ng, say) could emit different compressed bytes for identical input and
therefore a different zip hash. The per-file sha256 table in `MANIFEST.json`,
which is what `--verify` compares, is unaffected by this and by all of the
pinning above — it hashes member content, not the container.

Core grew from 92 files (the v0.16.0 record's corrected inventory) to 98 here.
Exactly six files, all v0.17 core surfaces:

```
engine/scripts/hwpx_tables.py        shared table scanner (T27)
engine/scripts/charpr_script.py      the charPr script/scale profile (T30)
engine/scripts/cli_io.py             cp949-safe stdio guard (#66)
skill/references/fill-recipe.md      the canonical fill (#76)
skill/references/visual-rubric.md    the rubric's one home (T29)
skill/references/model-routing.md    the shipped routing table (#63)
```

`pipeline/scripts/visual_verify.py` is not in that list: it landed before the
v0.16.0 record's corrected count was taken and is already inside the 92. The
four new module bundles are new at this version; `report` (87) and `style` (14)
carry the same payload counts as v0.16.0.

## Test suite (both CI matrix points, local Windows, Python 3.11)

| matrix point | result |
|---|---|
| core-only (`write-enabled --none`) | 1236 passed / 1171 skipped / 17 subtests, exit 0 |
| all-modules (`write-enabled --all`) | 2267 passed / 140 skipped / 35 subtests, exit 0 |

Skips are module-gating (every distribution module's tests collect-and-skip on
core-only) plus fixture/env skips; both points collect the same total. The
core-only point is the "absence is not failure" proof: every distribution
module disabled, suite green, module entry points refuse loudly by design.

## Privacy status

- **Repo-wide** `privacy_scan . --json`: exit 0, **HARD 0**, WARN 38 (34 at
  v0.16.0). All 38 are the one `korean_student_id_proximity` proximity
  heuristic firing on synthetic fixture data or docstring examples — 33 in test
  files (`engine/tests/test_preedit.py` 12,
  `pipeline/tests/test_declared_gates.py` 8,
  `engine/tests/test_build_report.py` 5,
  `pipeline/tests/test_visual_verify.py` 4,
  `pipeline/tests/test_check_residue.py` 2, and
  `pipeline/tests/test_privacy_scan.py` 2, which is the scanner's own fixture),
  and 5 in shipped code — the same five reported for the core bundle below.
  The four added since v0.16.0 are exactly the four in
  `pipeline/tests/test_visual_verify.py`, a file that did not exist at that
  tag. No HARD finding anywhere.
- **Bundle staging**: the packager runs `privacy_scan` over every staging dir
  with the allowlist **not** applied (bundles stay categorical); a HARD refuses
  the build with exit 3 and writes nothing. All seven builds exited 0, which
  *is* the gate evidence — the gate is the only thing between a staged tree and
  a written zip, so a bundle that exists on disk is a bundle whose staging
  scanned clean of HARD. Because "the build succeeded" is a weak thing to read
  in a record, each bundle was also **extracted and independently re-scanned**
  after the fact:

  | bundle | HARD | WARN | total |
  |---|---:|---:|---:|
  | core | 0 | 5 | 5 |
  | report | 0 | 0 | 0 |
  | style | 0 | 0 | 0 |
  | gongmun | 0 | 0 | 0 |
  | minwon | 0 | 0 | 0 |
  | hr | 0 | 0 | 0 |
  | grant | 0 | 0 | 0 |

  **Correction to the v0.16.0 record.** That record states the extracted core
  bundle was "HARD 0, WARN 0". It was not: the same five WARNs are present. All
  five are the `korean_student_id_proximity` heuristic firing on *docstring
  examples* in code that has shipped in core since `#40` —
  `engine/scripts/com_backend.py:742` (three overlapping matches on one
  example line), `engine/scripts/preedit.py:1326`, and
  `pipeline/scripts/check_residue.py:12`. The lines are byte-identical at
  v0.16.0's tip (`3415c3e`) and at this commit, and `privacy_scan.py` is
  unchanged across the whole v0.17 range, so this is a mis-measurement in the
  earlier record, not a regression here. HARD is 0 in every bundle, which is
  the gate that matters.
- **Corpus binaries**: the 32 `tests/corpus/forms` members (12 originals + 10
  XC-1 converted hwpx + 10 render PDFs) pass only via the sha256-pinned
  allowlist in the corpus `manifest.json`; allowlisted files are still
  content-scanned, and unlisted or hash-drifted binaries stay HARD. Ruling
  recorded in `docs/gate-calibration.md`.
- **Corpus containment**: a regression test asserts no `tests/corpus/forms`
  member lands in any bundle, and the `evals/` tree embeds no binaries at all
  (corpus files are copied into a sandbox at task-materialization time, by
  path, from the checkout).
- **Profile store**: `privacy_scan`'s `profile_store_content` /
  `profile_store_path` HARD markers make a bundle that stages personalization
  store content unbuildable.
- **`py_compile_sweep`**: `python scripts/py_compile_sweep.py` — 83 files, 0 failures, exit 0.

## The validation ledger

Four rounds, nine agent runs, two vendors — all on the same task class (A1:
profile the 조달청 협업 승인 신청서, fill 10+ fields without altering the
form's appearance, save, verify).

Rounds 1–3 are **clean-room** runs in the sense `evals/README.md` §1 defines:
fresh temp root outside the checkout, product content entering only by
unzipping dist bundles, no repo checkout reachable, buyer actions only, and no
operator intervention during the agent run — with containment re-asserted on
five independent axes afterwards, zero findings in every run. Round 4 was run
by an independent Codex harness on the same task; its install and containment
discipline is that harness's, not ours, so it is reported as an independent run
rather than as a `cleanroom.py` run.

| round | harness | tiers | what it measured | defects found |
|---|---|---|---|---:|
| 1 | Claude clean-room, `evals/` | Sonnet, Opus | **defect-workaround cost, not tiers** — it ran against v0.16.0 as released | 8 |
| 2 | Claude clean-room, `evals/` | Sonnet, Opus | tier difference on a fixed product (after #59–#62) | 4 |
| 3 | Claude clean-room, `evals/` | Sonnet, Opus | the full product, all six modules enabled | 6 |
| 4 | **independent Codex harness** | sol, terra, luna | correctness of the *verdict* itself | 7 |
| | | | | **25** |

**Round 1 measured defect-workaround cost, not tiers.** This needs saying
plainly, because the round-1 token numbers in `skill/references/model-routing.md`
look like a tier comparison and are not one. Both tiers completed the task, but
only by working around five product defects: no offline way to fill a genuinely
empty cell, `set_cell` writing to the wrong cell (both tiers destroyed label
cells), `replace` double-applying per its own documented example, the visual
rubric absent from every bundle, and the residue keep list unusable on fills.
What round 1 measured is how expensive it is to work around a broken product,
and the two tiers differ on that in ways that say nothing about their
capability on a working one. Round 2 is the first round whose numbers are a
tier comparison.

### The 25 defects, by round

**Round 1 — Claude clean-room, Sonnet + Opus, against v0.16.0 as released (8).**

| # | defect | shipped in |
|---|---|---|
| 1 | `skill_surface_not_bundled` — the core bundle carried no `skill/`, no references, no installer; a buyer got the engine and no way to install the router skill | #59 |
| 2 | T26 — `preedit replace` double-applied a value containing its own key, following the docs' own example | #60 |
| 3 | T27 — a form's genuinely empty cell (`<hp:run/>` with no `<hp:t>`) was unreachable offline; the skill routed form-filling to an operation that could never hit it | #60 |
| 4 | T28 — COM `set_cell` addressed cells by keypress count, so any rowspan label column sent the write to the wrong cell | #60 |
| 5 | the table scanner mis-paired nested tables (`<hp:tbl>(.*?)</hp:tbl>`), reporting wrong table/cell counts on 7 of 12 corpus forms | #60, #62 |
| 6 | T29 — the shipped skill pointed at a rubric document that was in no bundle: the mandatory vision half reached a buyer with no class definitions | #61 |
| 7 | V2 — `visual_verify --form-profile` could not forward a keep list, so a correct form fill could never pass the residue delegate | #61 |
| 8 | T30 — a fill inheriting a `<hh:supscript/>` charPr rendered at ~6.35pt while every offline height check passed; only the render caught it, and only one of the two tiers | #61 |

**Round 2 — Claude clean-room, Sonnet + Opus, on the fixed product (4).**

| # | defect | shipped in |
|---|---|---|
| 9 | T31 — the keep derivation read a prefix-preserving fill (`" http://"` → `" http://host"`) as unconsumed residue, so a correct fill still needed a hand-built `--keep` | #64 |
| 10 | T30 was detectable but not *preventable* — finding the right charPr id meant reading `header.xml` by hand, which the shipped contract discourages | #66 |
| 11 | T32 — `--charpr` is batch-wide, an undocumented constraint that the T30 pre-flight breaks by construction | #66 |
| 12 | `com_backend.py --help` died with `UnicodeEncodeError` on a Korean-locale console — the platform the COM path exists for. 11 CLIs broken, 8 more latently unguarded | #66 |

**Round 3 — Claude clean-room, Sonnet + Opus, full product with all six
modules (6).**

| # | defect | shipped in |
|---|---|---|
| 13 | T34 — a form's printed seat was reachable only with a `replace` key reproducing its exact internal whitespace, and nothing shipped yielded that string; both tiers read `Contents/section0.xml` by hand, which the skill forbids | #74 |
| 14 | `table_map[].text_preview` truncated at 30 characters with no flag, hiding a `(     개월)` blank in the middle of a skeleton and costing a second replace pass | #74 |
| 15 | `--charpr-per-cell` was documented only inside the T30/T32 prose, while the fill path showed a bare `fill-cells --cell` call | #74 |
| 16 | T35 — `--fill-map` was one flag name with two incompatible payloads, and each consumer's refusal named only its own shape: one shape learned per retry | #73 |
| 17 | T35 (second nit) — `--baseline` reads as "the blank form" but refused an `.hwpx`, so the agent dropped pixel-diff rather than converting | #73 |
| 18 | `form_inspect --pretty` was tried from habit and rejected with a bare argparse error that named no alternative; the habit has an in-repo source — `probe.py` is the one script with compact default output, a justified exception nobody had written down | #77 |

**Round 4 — independent Codex harness, tiers sol / terra / luna (7).**

| # | defect | shipped in |
|---|---|---|
| 19 | **`acceptance: true` returned while three safety checks sat in `deterministic.skipped[]`** — `empty_cell_expected_fill`, `fill_charpr_script_mismatch` and page parity — with exit 0. Acceptance was computed as "no HARD finding" and never read the skip list (luna) | #75 |
| 20 | `--fill-map` and `expectations.fill_map` were two different inputs with materially different effects, so the flag looked sufficient and was not (luna) | #75 |
| 21 | `pages_document` had no source at all on the `--pdf` path, so page parity skipped by default unless the caller hand-declared a number (sol) | #75 |
| 22 | **an exit-1 traceback escaping after a good verdict** — `vision_pending` exited 1 where the contract says 3, because `emit_verdict` sat outside every guard in `main` and an unwritable `--out` escaped as a traceback (sol, terra) | #75 |
| 23 | six cells on the test form were classified `fill_target` when nothing is ever written in them, so every reader had to reason them away by hand | #76 |
| 24 | `empty_cell_expected_fill` fired on every *correct* run, with a page y-coordinate as its only evidence — a warning every correct run emits | #76 |
| 25 | no canonical fill procedure existed: three harnesses filling the same cell picked three different strategies, one built three separate maps, and the `convert` syntax was undocumented | #76 |

Defects 23–25 were reported by the Codex harness and independently by the
round-3 Opus run; they are counted once, under Codex, because that is the run
that reported them as defects rather than working around them.

### The trend

8 → 4 → 6 → 7. The shape is not monotone and should not be read as one. Round
1's eight are the alpha's real gaps. Round 2's four are what a fixed product
still costs a competent agent. Round 3's six rose again because the product
grew (all six modules, a longer verification path) and because round 3 is the
first round that pushed on the *seat-text* half of filling rather than the
empty-cell half. Round 4's seven are a different **kind**: rounds 1–3 found
defects in what the product *does*, round 4 found defects in what the product
*claims* — see below.

## What the Codex run changed

This is the strongest evidence in the release, and it is worth being precise
about why.

Rounds 1–3 were run by Claude agents inside a harness we wrote, against tasks
we wrote, graded by machine checks we wrote. Every defect they found was a
defect in the product's *behaviour*: a command that could not reach a cell, a
document that was not in the bundle, a flag that took the wrong shape. Those
are real and they were worth finding — but they are all findable by someone who
trusts our verdicts and works around what breaks.

The Codex harness did not trust our verdicts. It found two things our own
harness structurally could not see:

1. **`acceptance: true` returned while three safety checks sat in
   `skipped[]`.** The luna tier passed a CLI `--fill-map`, and got
   `empty_cell_expected_fill`, `fill_charpr_script_mismatch` **and** page
   parity into `deterministic.skipped[]` — then exit 0 and `acceptance: true`.
   Our harness could not see this because our harness *reads the verdict*.
   Every one of our green runs was green by the same rule that was wrong:
   acceptance was computed as "no HARD finding", so a check that never RAN was
   indistinguishable from a check that passed, and the skip list was flat prose
   no rule could match on. A verdict that overclaims is invisible to anything
   downstream of it. The fix names the five safety checks in ONE place
   (`visual_verify.SAFETY_CHECKS`) that the waiver vocabulary, the skip
   bookkeeping and the acceptance rule all read, so they cannot drift; an
   unwaived safety skip yields the terminal state `safety_incomplete` and a
   HARD `acceptance_safety_skipped`, never a pass; and `--accept-without CHECK`
   is per check, on the record in `acceptance_waivers[]`, and never hides the
   skip.
2. **An exit-1 traceback escaping after a good verdict.** sol and terra both
   saw exit **1** for `vision_pending`, where the documented contract says
   **3**. 1 was not a code at all: `emit_verdict` sat outside every guard in
   `main`, so an `--out` naming an existing directory escaped as a traceback
   *after* a perfectly good verdict had been computed. Our own harness never
   hit it because our harness always passes a writable `--out` — the failure
   needed a caller who chose their own path. `--out` is now validated before
   the run and the emission is wrapped (an emission failure degrades to the
   usage row, 2), so **no path exits 1**, and `test_exit_code_matrix` pins one
   row per terminal state.

Both are correctness-of-verdict defects, and that is the category our own
harness is worst at. A harness written by the same people who wrote the product
inherits their assumptions about what a verdict means. Getting a second vendor
to run the thing is the only mechanism we have found that reaches this class.

The Codex harness also reported three surface defects (23–25 above) that the
round-3 Opus run had worked around rather than reported — same evidence,
different disposition. That difference is itself the finding: an agent that
does not share our folklore reports what an agent that does will silently
absorb.

## The honest limits

Each of these is a limit, not a roadmap item, and is stated here because the
tag should not be read as claiming more than the runs support.

1. **School and corporate form families have no corpus.** Family ③ (학교 서식)
   and family ⑤ (기업 내부 문서) have no blank-form corpus at all, and
   therefore nothing in this release is validated on them. For ⑤ no official
   source exists — the shipped `skill/references/forms.md` says
   UNSUPPORTED/UNTESTED and applies family-① rules by analogy only on explicit
   user insistence. For ③ two candidate sources failed corpus policy (one dead
   URL; one served an *issued* 가정통신문 rather than a blank template). Both
   are recorded in the corpus manifest's `skipped[]` with the reason. These are
   documented boundaries, not work in progress.
2. **The harness axis has exactly one non-Claude data point.** Rounds 1–3 are
   all Claude agents in our harness; round 4 is one other vendor. One data
   point is not a trend, and it does not establish that the shipped surface
   works on a third harness. The skill also still leans on at least one
   Claude-Code-specific mechanism (the capability probe is injected by an
   inline-command syntax). **The luna tier's own result carries a caveat**: it
   produced an accepted document, but it needed more retries than the Claude
   tiers on the same class of task, and it needed an auditing harness around it
   to get there. "A second vendor can drive this" is supported; "a second
   vendor can drive this as cheaply" is not.
3. **No fully independent party has run this.** Every run so far was launched
   by us, on our machine, against a task we wrote, and graded by machine checks
   we wrote — including round 4, where the vendor was independent but the
   harness, task and grading were not. A different person, on a different
   machine, with their own task, has not run this. That is the single largest
   remaining gap in the evidence and no amount of internal rounds closes it.
4. **Page-budget rules ship permanently skipped, with named reasons.**
   `check_grant`'s `length_budget_unverified` is always reported as `skipped`
   with one of three reasons — `not_declared`, `needs_render`,
   `needs_section_scoping` — and names `visual_verify` as the owner of a page
   count instead of guessing one. The reason it can never pass from inside the
   checker is structural: a page count is not derivable from
   `Contents/section*.xml`, it needs a render. The reason it has no number to
   check against is a corpus finding: the usage-landscape write-up predicts
   per-section page budgets for this family (`5쪽 이내`), and
   `page_budget_re`/`char_budget_re` match **zero** times across all three
   corpus grant forms. It ships as a declared dependency rather than being
   dropped, so a caller can see the gap; it is not a check.
5. **The derived `pages_document` is exact on 5 of 10 corpus forms.**
   `derive_pages_document` reads the artifact's own `<hp:lineseg vertpos>`
   layout cache, which is what removed the "caller must remember a number"
   failure on the `--pdf` path. Measured against the ten rendered corpus forms
   it is exact on 5. Every disagreement is an **under**-count (a form whose
   body lives entirely inside tables caches no top-level linesegs) except
   `nrf-gyeolgwa-bogoseo-yangsik`, which derives 4 against a 2-page PDF — and
   that one *is* the real W6.2 imposition incident (`PrintMethod=4`). Hence the
   directional rule that ships: for the derived source only, n-up imposition
   can only FOLD pages, so `pages_pdf < pages_document` is HARD while the
   under-count direction is a WARN naming both explanations. It is a correct
   rule over an imprecise input, not a precise input.
6. **One task, one form family, one machine, in the routing measurement.** The
   measured task (A1) is a single-page procurement form on a Korean-locale
   Windows machine with Hancom COM present. `assemble` (multi-section build,
   page budgets) and `prose/humanize` are explicitly **unmeasured** in
   `skill/references/model-routing.md` — no claim is made for either. Haiku was
   not measured at all.
7. **Carried forward from v0.16.0, unchanged**: `.hwp` conversion parity is
   structural, not byte-level; all conversion numbers are one Hancom build
   (13.0.0.2986); `DocSummary` metadata is not stripped on conversion; COM
   shape/picture classification is locale-dependent; `form_inspect` vs
   `content_extract` table counts still disagree on 6/10 corpus files (recorded
   open item, not root-caused); and the render proof ceilings are unchanged —
   LibreOffice/H2Orestart stays advisory and is skipped for equation-bearing
   documents, `experimental-rhwp` is hard-blocked from submission, `certified`
   requires an operator-issued HMAC certificate, and `hancom` is the only
   native submission grade.
8. **Skill token eval remains OPERATOR-RUN.** The loaded-token-footprint
   measurement and the agent-in-the-loop halves of the A1/A2 eval scenarios are
   still marked OPERATOR-RUN in `docs/research/form-eval-scenarios.md`; the
   machine-check halves pass, with a non-vacuous negative control.

## If you are evaluating this

Three commands, in order. Each is a buyer action — nothing here needs the
source checkout. Run them from the install root (the directory you extracted
`rigorloom-core-0.17.0.zip` into; see its `INSTALL.md`), or from the installed
skill directory, where the same two scripts land under `engine/scripts/`.

```sh
# 1. Does this machine support the paths you need? (renderers, Hancom COM,
#    enabled modules — one JSON object)
python engine/scripts/probe.py

# 2. What does this form actually contain? (tables, cells, anchors, guide
#    text, fill targets vs spacers, and the charPr each fill would inherit)
python engine/scripts/form_inspect.py <FORM.hwpx>

# 3. Fill it end to end, then verify — follow one document, not a tour:
#    skill/references/fill-recipe.md
```

`fill-recipe.md` is the third command. It states the branch-per-cell decision
rule first (genuinely empty run → `preedit fill-cells`; printed skeleton to
keep → `replace --at-cell-append`; template to replace wholly → `replace
--at-cell`; multi-run cell → the `#RUN` the refusal hands you;
`classification: spacer` → do not write there), names the four artifacts and
the one flag each feeds so nobody invents a second map, gives the literal
command sequence including the `tasklist` check before COM, and closes with
what `acceptance: true` looks like as five separate claims plus the partials it
must not be confused with. It was worked end to end on a real 조달청 form and
replayed verbatim to `acceptance: true`.

Where the rest lives:

| you want | read |
|---|---|
| which model tier to run which task class on, and what is unmeasured | `skill/references/model-routing.md` |
| per-family capability boundaries, including the two families with no corpus | `skill/references/forms.md` |
| the 12 visual defect classes and what each is NOT | `skill/references/visual-rubric.md` |
| a concrete symptom → cause → fix lookup (T1–T36) | `skill/references/troubleshooting.md`, and `docs/trouble-table.md` in the source repo |
| what a clean-room run is and what evidence it must produce | `evals/README.md` |
| the module contract, if you are writing a work-type module | `modules/README.md` |

The one thing worth checking first if you are deciding whether to trust this:
run `visual_verify` and look at `deterministic.skipped[]`. If a safety check is
in there, the verdict is `safety_incomplete` and exit 3, not a pass — that
behaviour is the direct product of the Codex finding above, and it is the
property that makes every other green verdict in this release mean something.

## Positioning check

Shipped text audited again this release: the style capability is described
everywhere as translationese removal / voice consistency / form-rule
compliance — never AI-detection evasion. Detector scores remain advisory,
pinned by `test_h2_advisory_only`. The four new work-type modules make no
claim of legal or administrative validity for the documents they check: every
rule is a structural preservation or residue rule derived from the form's own
declarations, and rules that cannot be decided from the inputs given are
listed under `skipped` with a reason rather than silently passed.

## Tag checklist (for the operator)

- [ ] Review this record and the CHANGELOG v0.17.0 section.
- [ ] `git tag v0.17.0 && git push origin v0.17.0` (the tag is NOT applied by
      the preparation branch).
- [ ] If any tracked source change lands after this commit, rebuild and
      refresh the sha256 table above. A rebuild with no source change no
      longer moves the hashes, so an unchanged tree needs no refresh.
