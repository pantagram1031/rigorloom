# Checkpoint 11 — what Hancom does on save, and the floor that was a ceiling

Non-merging checkpoint. Written from `origin/claude/engine-e2-floor-ordering`
(this branch, `docs/checkpoint-11`, is cut from that tip and stays
unmerged). Covers #238 (`claude/engine-e3-roundtrip-render`: the
Rigorloom-authored 51-feature document, after Hancom opens and saves it,
still renders identically — 6 match/37 close/6 differs/2 unsupported, 0 of
51 verdicts changed; Hancom adds no `hp:lineseg` to this document because
neither side has one to begin with), #239 (`claude/engine-e3-lineseg-on-save`:
on a document that already carries a cached `hp:lineseg`, Hancom recomputes
layout on every save rather than copying the cache forward — deterministic
and idempotent on an untouched resave, 0/223 paragraphs changed, but a
single appended character on the 798-paragraph kstartup form perturbed a
paragraph **534 positions downstream** (`vertpos` 0 → 70884) and gave two
previously-unlaid-out paragraphs their first lineseg — with a named policy
consequence for `own_render --line-layout auto`), and #240
(`claude/engine-e2-floor-ordering`, the renderer-line tip: the eval floor
`tally.close >= 38` was failing at 37 precisely *because* #236 promoted
three blocks from `close` to `match` — a floor gating a middle bucket is a
ceiling in disguise — rewritten to gate on quality ordering
(`match >= 3`, `match + close >= 41`, `differs <= 8`, `unsupported <= 2`,
`pages.reference == 9`), plus a DAG-gap fix merging #231's claim commit;
110 tests). Also folds in #235's harness finding (E3.2 acceptance run 02:
27/28, with the one miss traced to the acceptance harness's own
`GetTextFile("TEXT")` gap on header text — a lexical-reader fix queued, not
yet a branch) and #236's full-gate result, now landed: two explained
failures, both fixed within this window (#240 itself).

## What changed since checkpoint-10

| metric | checkpoint-10 | checkpoint-11 | moved in |
|---|---|---|---|
| renderer-line tip | #236 (layout in HWPUNIT; byte-identical at every dpi) | **#240** — full-gate failures explained and fixed; eval floor rewritten to ordering; #231's claim merged in | #240 |
| #236 full-gate result | not yet run (checkpoint-10 reported engine/tests 1240 + pipeline/tests 1437 only) | **ran, found 2 failures, both explained and fixed by #240** — neither was a renderer bug | #240 |
| render-check eval floor | `tally.close >= 38` (a middle-bucket count) | **ordering**: `match >= 3`, `match + close >= 41`, `differs <= 8`, `unsupported <= 2`, `pages.reference == 9` — a genuine improvement can no longer fail it | #240 |
| writer line | #235 (acceptance run 02: 27/28, harness gap named) | **#238, #239** — the writer's own authored document survives a Hancom round-trip render-identical (0/51 verdicts changed); on documents that already carry a cache, Hancom recomputes it on every save, and an edit can perturb a paragraph hundreds of positions away | #238, #239 |
| `own_render --line-layout auto` cache policy | not addressed | **named as unsound**: per-paragraph staleness detection cannot predict which *other* paragraphs Hancom's layout pass will also touch; whole-document invalidation on any non-Hancom edit is the rule to adopt — queued as the next renderer slice | #239 |
| desktop line | #234 (renderer #231; two slices behind #236) | **unmoved — now three slices behind** (#232, #236, #240 have landed since #234's merge) | — |
| runtime line | unmoved since checkpoint-06 (#204) | **still unmoved** (#204) | — |
| new finding | line boxes report the advance, not the ink (#236) | **a floor that gates a middle bucket is a ceiling in disguise** — recorded as a general lesson, not just this one fix (#240) | #240 |

## 1. Branch DAG

Renderer line, now four PRs off checkpoint-09's tip:

| PR | branch | base | slice |
|---|---|---|---|
| #231 | `claude/engine-e2-render-check-claim` | `claude/engine-e2-converge-3` | support-matrix claim (checkpoint-09 tip) |
| #232 | `claude/engine-e2-ink-residual` | `claude/engine-e2-render-check-claim` | ink residual declared a floor (checkpoint-09) |
| #236 | `claude/engine-e2-dpi-independence` | `claude/engine-e2-ink-residual` | layout moved to HWPUNIT; byte-identical at every dpi (checkpoint-10 tip) |
| **#240** | `claude/engine-e2-floor-ordering` | `claude/engine-e2-dpi-independence` | **eval floor rewritten to match+close ordering; #231's claim commit merged in to close a DAG gap (#236 had forked from #232 before #231 landed on that line); floors + matrix + cleanroom 110 passed; render-check on this tip unchanged 6/37/6/2, 9 pages. This is the renderer tip.** |

Writer line, now three PRs deep off #224:

| PR | branch | base | slice |
|---|---|---|---|
| #224 | `claude/engine-e3-writer-colpr-order` | `claude/engine-e3-hancom-accept` | section-head control order (checkpoint-07/08) |
| #235 | `claude/engine-e3-accept-02` | `claude/engine-e3-writer-colpr-order` | acceptance run 02: 27/28, harness gap named (checkpoint-10) |
| #238 | `claude/engine-e3-roundtrip-render` | `claude/engine-e3-accept-02` | **the Hancom-saved 51-feature document renders identically — 0/51 verdicts changed. Depends on #235.** |
| **#239** | `claude/engine-e3-lineseg-on-save` | `claude/engine-e3-roundtrip-render` | **Hancom recomputes `hp:lineseg` on every save; a one-character edit perturbs a paragraph 534 positions downstream on a large corpus form; policy consequence named for `auto`-mode caching. Depends on #238. This is the writer-line research tip — still docs-only, no code branch opened for the policy fix.** |

Desktop line: no PR in this window. Still #234 (`claude/desktop-renderer-230`,
on renderer #231) — checkpoint-10 measured it two slices behind the then-tip
(#236); #240 has since landed on top of #236, so the desktop is now **three**
renderer slices behind (#232, #236, #240), the gap widening again after
checkpoint-10's narrowing to two.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-10` (each off
its own window's renderer tip). No new fork opened in the renderer line this
window — #236 → #240 is a straight continuation, save for the one DAG-repair
merge of #231's claim commit that #240 itself performs.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #238 — the authored document survives Hancom render-identical

The run-02 rerun candidate (`render-check-01.rerun.json`) no longer existed
on disk (prior session's scratchpad, deleted between sessions), so it was
regenerated: same marker-planting step run 02 used
(`RIGOROOM-E3-ROUNDTRIP-RENDER-01` in the header control's `hp:t`),
`hwpx_lint --section-order` clean, single serial COM session, `Hwp.exe`
confirmed absent before/after via `tasklist`. 7/7 acceptance checks pass,
reproducing run 02 exactly. Both the pre-Hancom source and the Hancom-saved
candidate were then rendered at 96 dpi with the renderer tip
(`origin/claude/engine-e2-dpi-independence`, fetched read-only, not merged
into the writer line) and scored against the pinned `render-check-01.pdf`.

**Result: 6 match / 37 close / 6 differs / 2 unsupported on both sides —
identical, page count 9/9 both.** 0 of 51 per-feature verdicts changed. The
one notable score shift, F50 (the header block), is the planted edit marker
itself carrying more header ink than the original — expected, not a
round-trip artefact. Two features (F44 hyperlink, F19 underline) show small
sub-threshold drift plausibly tied to charPr-id remapping in the
header.xml consolidation, but neither moved toward its bucket boundary.

**Why the verdict table is unchanged, and it matters for #239's question:**
an exhaustive `iter_local("lineseg")` scan of every section XML in both
packages found **zero `hp:lineseg` elements on either side** — this
document has no cache to begin with (the writer never emits one), so
`own_render`'s `auto` mode takes the identical CJK-aware greedy-wrap
fallback path on both the pre- and post-Hancom package. The PR's own words:
"very likely why the per-feature verdict table is unchanged: there is no
cache-vs-no-cache asymmetry for the renderer to trip on" — explicitly
naming the untested case (a document that already carries a cache before
the round trip) as the open question, which #239 answers next.

**Lexical diff:** reproduces run 02's `header.xml` style-catalog
consolidation exactly (`hh:paraHead`/`hh:heading`/`hh:border` etc. removed,
`hc:intent`/`hp:default`/`hp:switch`/`hp:case` etc. added); body
`hp:tbl`/`hp:p`/`hp:tc` counts unchanged; candidate gains
`Preview/PrvImage.png` and renames `image1.png` → `image1.PNG`.

**Evidence:** `py_compile_sweep` clean; archive privacy gate HARD=0
(synthetic document, no personal data).

### #239 — Hancom recomputes the cache on every save, and an edit can reach 534 paragraphs away

Three corpus forms already carrying near-complete `hp:lineseg` caches
(gianmun-byeolji-1ho 67 p, jeongbo-gonggae-cheongguseo 78 p,
kstartup-jiwon-sincheongseo-saeopgyehoekseo 798 p). Two Automation runs per
form: **no-edit** (open, save-as, quit) and **edit** (append one character
to a single table-cell body paragraph, save-as, quit) — single serial COM
session each, `hwpx_lint --section-order` clean afterward, source never
touched.

**No-edit: 0/223 paragraphs across all three forms show any field
difference** in the 9-field `hp:lineseg` comparison — cache comes back
byte-identical after an untouched open/save-as at every size tested.

**Edit: the edited paragraph's own lineseg never changed** (a one-character
append that doesn't push the line past its wrap point leaves the cache
untouched for that paragraph, all three forms). But on kstartup:

- **Paragraph 539** (534 positions after the edit site, same section):
  `vertpos` `0` → `70884`, all other fields on that lineseg unchanged — a
  downstream reflow cascade.
- **Paragraphs 11 and 12**: had no lineseg in the source or the no-edit
  resave (untracked-layout on both), but **gained one** in the edit resave
  (a distinct `flags` value) — went from never-laid-out to laid-out purely
  as a side effect of an edit elsewhere in the document.

The two smaller forms (67, 78 paragraphs) show zero knock-on effect — the
cascade only appeared on the 798-paragraph form, consistent with needing
a large enough document for the effect to have somewhere to go (not tested
at intermediate sizes).

`hp:sz` and `hp:outMargin`: identical index-by-index in all 6 runs.
`header.xml` qname-count delta: **empty in all 6 runs** — the opposite of
#238's finding on the Rigorloom-authored document. Not a contradiction: these
three forms are already Hancom-native (official templates already saved by
Hancom at least once), so their header catalog is already in canonical
shape with nothing left to consolidate. The PR's own conclusion: catalog
consolidation is a one-time normalization of a non-Hancom-shaped catalog,
not something every save repeats.

**The rule Hancom applies, in the PR's own words:** "Not a passive keep...
Hancom recomputes line layout on every save... the recomputation is
deterministic and idempotent — given unchanged content and structure it
reproduces byte-identical values" — closest to *rewrite from its own
layout*, never a literal keep, never an unconditional drop.

**Policy consequence for `own_render --line-layout auto`, stated directly:**
"'Trust the cache only for untouched paragraphs' is not a safe local rule.
This run shows a one-character edit perturbing a paragraph 534 positions
later... a per-paragraph 'did this paragraph's own text change' check
cannot predict which *other* paragraphs Hancom's layout pass will also
touch." The rule to adopt: trust `hp:lineseg` wholesale only when the HWPX
is provably Hancom's own most-recent save of its current XML content (no
edits applied since); the instant a non-Hancom edit lands on a Hancom-saved
package, the cache must be treated as stale for the **whole document**, not
just the touched paragraph — `own_render` should fall back to its
CJK-aware greedy-wrap path for the entire file. **Queued as the next
renderer slice, not yet a branch or PR.**

**Not proven:** whether the cascade is ever upstream of the edit site (only
tested with the cascade landing after); edits larger than one character, or
edits that do cross a wrap point in a small document; the exact mechanism
behind paragraphs 11/12 gaining a lineseg.

**Evidence:** `py_compile_sweep` clean; `hwpx_lint --section-order` — 6
files, 0 warnings; archive privacy gate HARD=0 (aggregate paragraph-index
counts and public form-template field labels only).

### #240 — the floor that gated a middle bucket, and the DAG gap it closed with it

**Closes both failures #236's full gate produced; neither was a renderer
bug.**

1. `tests/test_eval_floors_against_corpus.py`'s `tally.close >= 38` failed
   at 37 — *because #236 promoted three blocks from `close` to `match`* (3
   → 6 exact matches at 96 dpi), which necessarily drains the `close`
   bucket even as overall quality improves. The PR's own framing: "Gating a
   middle bucket is a ceiling in disguise." Rewritten to gate on quality
   **ordering**, which a genuine improvement can never violate:
   `match >= 3`, `match + close >= 41`, `differs <= 8`, `unsupported <= 2`,
   `pages.reference == 9`. `evals/cleanroom.py` gained a `+`-joined
   path-sum syntax in its assertion mini-language to express the combined
   bound; `evals/tasks/render-check-01.yaml` and
   `pipeline/references/support-claims.yaml` updated to match; a unit test
   pins the intent directly: 7/36/6/2 passes the new floor, 2/38/9/2 fails
   it (a high `close` count with a collapsed `match` count is correctly
   rejected even though it satisfies the old `close >= 38` rule).
2. The claim-coverage failure was a DAG gap: #236 forked from #232 before
   #231's claim commit landed on that same line, so #236's tree never
   carried #231's support-matrix claim for the render-check eval task.
   Resolved by merging #231 into this PR directly (`docs/support-matrix.md`
   updated).

**Evidence (orchestrator re-ran the floor suite):** floors + matrix +
cleanroom **110 passed**; render-check on this tip unchanged **6/37/6/2**,
9 pages; `py_compile_sweep` clean; archive privacy gate HARD=0. The PR's own
body states the full `pipeline/tests` suite was **running** on this tip at
write time, expected 0 failed, to be appended when it lands — **as of this
checkpoint, no PR comment with that result has posted; the full-gate run on
#240 itself is still open**, reported here as running, not as passed.

**Lesson recorded, in the PR's own words:** "floors gate on order, never on
a single middle bucket."

### #235 (carried forward from checkpoint-10, restated for completeness)

E3.2 acceptance run 02: 27/28 across four inputs (7/7, 7/7, 7/7, 6/7), the
one miss an acceptance-harness gap (`GetTextFile("TEXT")` does not export
header/footer text, though the edit marker is present byte-for-byte in the
saved XML) — not a writer defect. Fix queued: read the edited region
through the lexical reader instead of the text export. **Still not done as
of this checkpoint** — no branch for it exists in `origin`.

## 3. Regressions (with the PR's or commit's own explanation)

**None newly introduced this window.** #240 is itself the fix for the two
failures #236's full gate exposed — both explained as gate/DAG defects, not
renderer regressions, and both closed in the same PR. #238 reports 0 of 51
render-check verdicts changed (no regression, by construction — its whole
finding is stability). #239 reports no regression either; its finding is a
*characterization* of Hancom's own behavior (cache recomputation reaching
534 paragraphs away), which is new information about the external tool, not
a defect in Rigorloom's code. The `nrf` regression #236 named at
checkpoint-10 (`ssim_inked` −0.016, `text_line_iou` −0.013 at 144 dpi) is
carried forward, unaddressed by any PR in this window — no mechanism fix has
been offered since it was named.

## 4. Unsupported / declared elements still open

Carried from checkpoint-10, with this window's closures and new items:

- **Closed since checkpoint-10:** the "does a document with a pre-existing
  cache survive a Hancom round trip render-identical" question #238 left
  open — but only for the *no-cache* case (#238's own document has no
  lineseg on either side). #239 answers the cache-*present* case instead,
  and its answer is not "renders identically" but "Hancom recomputes the
  cache, and the recompute can silently diverge from the stored cache after
  any edit, reaching hundreds of paragraphs away" — a sharper, less
  reassuring result than a simple close would suggest.
- **New, opened by #239 itself:** per-paragraph cache-staleness detection in
  `own_render --line-layout auto` is unsound; whole-document invalidation
  on any non-Hancom edit is the rule to adopt, named as the next renderer
  slice, not yet a branch or PR.
- **New, opened by #240 itself:** the full `pipeline/tests` gate run on the
  renderer tip (#240) was reported as still running in the PR body — result
  not yet posted as of this checkpoint. Treated as open, not as passed.
- **Unchanged from checkpoint-10:** the trailing-space line-box question
  (advance vs. ink) #236 named — no PR in this window touches it; the
  desktop line's re-merge onto the renderer tip, now three slices stale
  instead of two; the acceptance harness's lexical-reader fix for
  header/footer text (#235's queued item); Codex-app-closed sessions moved;
  Cursor login; the `nrf` regression at 144 dpi; whole-document computed
  layout's page-count/line-IoU failure (#199); writer line's default
  header/meta elements on a blank-package save;
  `hp:ole`/`hp:chart`/`hp:container`/shapes/undecodable EMF-WMF
  placeholders; `DOUBLE_SLIM` border limitation; `hp:parameters` family;
  `hp:autoNum` inside a footer draws nothing (`F51`); `hh:tabPr` stops
  inside the MCE switch never read; the tier-3 raster's own
  `own-uncertified` status; Hancom's first-column endnote placement in a
  two-column section.

## 5. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #238 | acceptance rerun 7/7; render-check 6/37/6/2 both sides, 9/9 pages | not a full-suite PR; scoped to the round-trip render check | `py_compile_sweep` clean; archive privacy gate HARD=0 |
| #239 | 9-field lineseg comparison, 6 runs across 3 corpus forms; `hwpx_lint --section-order` 6 files/0 warnings | not a full-suite PR; scoped to the lineseg-on-save check | `py_compile_sweep` clean; archive privacy gate HARD=0 |
| #240 | floors + matrix + cleanroom **110 passed**; render-check unchanged 6/37/6/2, 9 pages | full `pipeline/tests` suite **reported running at write time; no landed result as of this checkpoint** | `py_compile_sweep` clean; archive privacy gate HARD=0 |

No PR in this window reports a fresh full-gate pass/fail count the way
#234's comment (3749/0/1199 skipped) or #236's engine/pipeline totals did at
checkpoint-10 — #240's full-suite run is the closest, and it is explicitly
open.

## 6. Integration conflicts expected when lines converge

**Renderer line repaired its own internal DAG gap this window.** #240
merges #231 directly into its branch to backfill a claim commit that #236's
fork point had skipped — not a conflict between diverging lines so much as
a missing-ancestor gap within the same line, closed by merge rather than
rebase.

**Desktop is not re-merged onto the renderer tip, and the gap widened.**
#234 still sits on #231; the renderer has since moved through #232, #236,
and now #240 — three slices behind, up from two at checkpoint-10. No branch
for that re-merge is visible in `origin`.

**Writer and renderer lines remain unconverged**, but now share evidence
indirectly: #238 and #239 both fetched the renderer tip
(`origin/claude/engine-e2-dpi-independence`) read-only into a scratchpad to
render their candidates, without merging it into the writer branch. Neither
PR touches `own_render.py` itself. The writer line's own research (#239) now
names a concrete, renderer-side code change it wants
(`own_render --line-layout auto` whole-document invalidation) — the first
time a writer-line finding has produced a specific renderer-line action
item, rather than the two lines running independently.

**Runtime line is untouched and unconverged with anything**, unmoved since
#204 (checkpoint-06).

## 7. Next measurable research question

**With the auto-mode caching policy fixed (whole-document invalidation on
any non-Hancom edit), how much does computed layout cost against the
cache on the corpus?** Concretely: for every corpus form and the private
holdout, compare `own_render`'s CJK-aware greedy-wrap computed layout
against the Hancom-authored `hp:lineseg` cache on lineseg-break agreement
and page-count agreement — the same metrics #236 already reports for the
dpi-independence fix (68 → 80/216 breaks matched at 144 dpi, corpus-wide).
The question this answers: **is computed layout good enough to be the
default for any document that has been edited outside Hancom**, given that
#239 just showed the cache cannot be trusted piecemeal after an edit? If
computed layout's agreement with the cache is close on untouched documents,
falling back to it wholesale after an edit costs little; if it is far,
whole-document invalidation is expensive and a smarter partial-invalidation
scheme (bounded, not per-paragraph) becomes worth designing. Not yet
measured in either direction.

## 8. Certification status

Every result in this checkpoint — #238 (round-trip render check), #239
(lineseg-on-save check), #240 (floor rewrite) — remains **own-uncertified**.
#238 and #239 are both explicitly research documents (`docs/research/`,
not renderer code); #240 changes only the eval-floor gate, not the renderer
itself. `render_cert.py` still cannot certify this renderer absent a PDF
text layer, unchanged since checkpoint-01.

**What moved, restated plainly:** the render-check exact-match improvement
#236 reported at checkpoint-10 (3 → 6 at 96 dpi) turned out to be strong
enough to break its own gate — the middle-bucket floor could not
distinguish "quality improved, buckets shifted" from "quality regressed,
buckets shifted the same direction," and #240 fixed the gate rather than
the (nonexistent) regression. This is the second time in this project's
history a metric bound needed rewriting *because* the renderer got
measurably better, not worse (the first being checkpoint-09's
dpi-aware `render_check` bounds, which #236's own PR body notes were exact
no-ops at 96 dpi) — worth naming as a pattern: **a numeric floor pinned to
one bucket of a multi-bucket classification is a ceiling on future
improvement, not a safety rail against regression, unless it accounts for
mass moving between adjacent buckets.**

**Owed, carried forward from checkpoint-10, plus this window's additions:**

- `own_render --line-layout auto` whole-document cache invalidation on any
  non-Hancom edit (#239's own next step) — not yet a branch or PR.
- The trailing-space line-box question (advance vs. ink), #236's next
  question, unaddressed this window.
- Desktop line (#234) re-merged onto the renderer's current tip (#240) —
  last done at #231, now three slices stale, widening from two.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved (carried, not addressed this window).
- Cursor login (carried, not addressed this window).
- The `nrf` regression at 144 dpi (#236) — still named, not explained
  beyond "the old rounding happened to serve its faces better."
- **New this window:** #240's own full `pipeline/tests` gate result on the
  renderer tip — reported running at write time, not yet landed as of this
  checkpoint; confirm and append before treating #240 as fully green.
