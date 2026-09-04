# Checkpoint 09 — the gate is green, and the ink that is left is the rasteriser's

Non-merging checkpoint. Written from `origin/claude/engine-e2-ink-residual`
(this branch, `docs/checkpoint-09`, is cut from that tip and stays
unmerged). Covers #230 (`claude/engine-e2-converge-3`: micro-convergence
of #227's eval task onto #228's last-page tip, clean merge, render-check
**9 = 9 pages, 51/51 agreement, tally 3 · 38 · 8 · 2** unchanged, two
consecutive runs byte-identical — this became the renderer tip), #231
(`claude/engine-e2-render-check-claim`: the support-matrix claim
`render-check-fidelity` the coverage-property chain demanded once #227
added an eval task — status `partially`, explicitly not a certification —
and, in a PR comment landing after the body, the **full pipeline/tests
gate on this tip: 3133 passed / 1199 skipped / 63 subtests passed, 0
failed** — the first fully green renderer full suite since #210), and the
ink-residual PR (#232, `claude/engine-e2-ink-residual`: on the five
pixel-exact-row `differs` features, the residual ink is rasteriser
weight — 1.80× the reference's coverage at 96 dpi, falling to 1.16× at
144 and ~1.0 by 192/288 — declared a floor via `RASTERISER_FLOOR`, not
tuned away; two dpi-aware `render_check` bounds adopted, both exact
no-ops at 96 dpi so the gated channels and the tally are byte-identical;
and a finding for the next slice: line breaking is not
resolution-independent — `F06` loses four to five characters per line at
144 dpi against 96). Checkpoint-08 (`docs/checkpoint-08`, off
`claude/engine-e2-last-page`) carries forward as the record of the
#227/#228 fork and the convergence it left owed.

**The fork checkpoint-08 left open is now closed and re-forked once
more.** #230 merged #227 onto #228 exactly as checkpoint-08 §6 asked;
#231 then forked from #230 to satisfy a coverage property #227's own
task addition triggered — the same "a property closes one gap and opens
the next" shape as #227 itself. #232 forks from #231 in turn, but is not
itself demanded by a coverage property — it is the ink question
checkpoint-08 §7 named as the next measurable one, now answered. All
three are still open PRs (#230, #231, #232), each depending on the one
before it; none merged to `main`.

## What changed since checkpoint-08

| metric | checkpoint-08 | checkpoint-09 | moved in |
|---|---|---|---|
| renderer-line shape | #226 forks into #227 and #228, unreconverged; a local worktree (`converge-3`) had merged them but was unmeasured and not a PR | `converge-3` **opened as #230**, measured (unchanged 3 · 38 · 8 · 2 / 9=9 / 51-51); #231 forks from #230 for the support-matrix claim; #232 forks from #231 for the ink question | #230 (opened + measured), #231 (claim), #232 (ink) |
| `test_cleanroom_evals` | fixed by #227, but #227's own full-suite result was reported "running", never appended | still not separately re-run to completion by #230's own body (cleanroom 74/74 restated); **superseded by #231's full-gate result** | #231 |
| full `pipeline/tests` gate | owed since checkpoint-05/06 through every checkpoint in this series — always "running" or unstated in the reachable PR bodies | **landed: 3133 passed / 1199 skipped / 63 subtests passed, 0 failed**, on #231's tip (2bb2531) — first fully green renderer full suite since #210 | #231 (PR comment) |
| support-matrix coverage | not tracked in checkpoint-08 as a distinct property | `render-check-fidelity` claim added, status `partially`, `test_support_matrix.py` 25/25 — closes the property `test_every_shipped_claim_validates` raised once #227 added an eval task | #231 |
| render-check `differs` queue (8 rows) | unnamed mechanism for 5 of the 8 (`F06`–`F08`, `F13`, `F15`); named for the other 3 (`F35`, `F48`, `F50`) | **5 of the 8 now attributed**: rasteriser glyph-coverage weight, measured at 1.80× (96 dpi) → 1.16× (144) → ~1.0 (192/288), multiplicative, Pearson(band ink, ssim) = −0.80 over 48 blocks — declared a floor, not a bug to fix in the renderer | #232 |
| render-check gate bounds | fixed pixel/ink thresholds, no dpi parameter | two bounds made dpi-aware (`iou_tolerance_px`, `ink_delta_bound`), both exact no-ops at 96 dpi — the ratified resolution — so nothing gated moves | #232 |
| new finding | — | **line breaking is not resolution-independent** — `F06` loses 4–5 characters per line at 144 dpi vs 96; default dpi must not move until fixed | #232 |
| desktop line | #221 (gap 34 closed, checkpoint-07 tip), unmoved through checkpoint-08 | **still #221** — no branch `claude/desktop-renderer-230` or equivalent exists yet; the re-merge onto the renderer tip is named as owed, not yet begun | — |
| writer line | #224, unmoved | **still #224** | — |
| runtime line | unmoved since checkpoint-06 | **still unmoved** since checkpoint-06 (last PR #204) | — |

## 1. Branch DAG

Renderer line: #226 (checkpoint-08 tip) forked into #227 and #228
(checkpoint-08), observed already merging in a local worktree at that
checkpoint's writing time:

| PR | branch | base | slice |
|---|---|---|---|
| #227 | `claude/engine-e2-render-check-eval` | `claude/engine-e2-converge-2` | `evals/tasks/render-check-01.yaml`, closing the `test_cleanroom_evals` regression (checkpoint-08) |
| #228 | `claude/engine-e2-last-page` | `claude/engine-e2-converge-2` | `END_OF_DOCUMENT` endnote deferred to last section, 9=9 pages, 51/51 (checkpoint-08) |
| **#230** | `claude/engine-e2-converge-3` | `claude/engine-e2-last-page` | **merges #227 onto #228, clean, no conflicts; the checkpoint-08 §6 worktree, now opened and measured — 3 · 38 · 8 · 2 / 9=9 / 51-51, two consecutive runs byte-identical, `test_cleanroom_evals` 74/74. Named in its own body as "the renderer line tip."** |
| **#231** | `claude/engine-e2-render-check-claim` | `claude/engine-e2-converge-3` | **`render-check-fidelity` claim in `pipeline/references/support-claims.yaml`, status `partially`; `test_support_matrix.py` 25/25; PR comment reports the full pipeline/tests gate at 3133/0/1199 skipped — declared "the authoritative renderer tip."** |
| **#232** | `claude/engine-e2-ink-residual` | `claude/engine-e2-render-check-claim` | **ink-residual measurement: 1.80× rasteriser coverage at 96 dpi on `F06`–`F08`/`F13`/`F15`, declared a floor; two dpi-aware bounds, both no-ops at 96 dpi; tally, pages and agreement unchanged; the dpi-independent line-breaking finding.** |

No new fork opened this window — #230 → #231 → #232 is a straight chain,
the first non-forking stretch in this checkpoint series since #219 →
#222/#223 first diverged.

Desktop line, unmoved since checkpoint-07:

| PR | branch | base | slice |
|---|---|---|---|
| #221 | `claude/desktop-own-render-edit` | `claude/desktop-own-render-converged` | gap 34 closed (checkpoint-07 tip, unmoved) |

The desktop line's last re-merge with the renderer line is still **#215**
(off checkpoint-05). The renderer tip has since moved through #218, #219,
#222, #223, #226, #227, #228, #230, #231, #232 — nine-plus slices the
desktop line has not picked up, three more than checkpoint-08 counted.
**No branch for the re-merge exists in `origin` as of this checkpoint** —
`git branch -r` shows no `claude/desktop-renderer-230` or similarly named
branch; the re-merge is owed and, per the prompt for this checkpoint,
"in flight," but not yet visible as a pushed branch or PR from here.

Writer line, unmoved since checkpoint-07 (#189 → #224). Runtime line,
unmoved since checkpoint-06 (… → #185 → #204).

Sibling docs branches: `docs/checkpoint-06` (off #219), `docs/checkpoint-07`
(off #223), `docs/checkpoint-08` (off #228).

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #230 — the fork closes, the renderer tip settles

Merge of `origin/claude/engine-e2-render-check-eval` (#227) onto the
last-page tip (#228): no conflicts, render-check report unchanged by the
merge itself. On the merged tree: **3 match · 38 close · 8 differs ·
2 unsupported**; **9 = 9 pages**; **51/51 page agreement**; two
consecutive runs of the measurement byte-identical (determinism check).
`tests/test_cleanroom_evals.py` **74/74**; engine/tests **1221 passed /
135 skipped**; `py_compile_sweep` 105/0; archive privacy gate HARD=0.
Declared in its own body: **"this is the renderer line tip; the desktop
line re-merges from here."**

### #231 — the claim the coverage-property chain demanded, and the gate lands green

**Root cause of what this PR closes:** the same coverage-property
mechanics that produced #227 fired again one property downstream —
`test_every_shipped_claim_validates` demanded a support-matrix claim
covering `eval:render-check-01` once #227 registered that eval task,
because #210 had never added one either. **Fix:** claim
`render-check-fidelity` added to `pipeline/references/support-claims.yaml`
(matrix regenerated), status **`partially`** — own_render scored
feature-by-feature against the pinned Hancom render-check-01 reference
(51 features), gated on the measured floor **3/38/8/2** with pages
**9 = 9**, so a regression is caught — and its own body states plainly
what it is **not**: a certification. Bounds are fit to one document; a
second document has not been scored; grade stays `own-uncertified`.

**Evidence in the PR body:** `tests/test_support_matrix.py` **25/25**;
cleanroom **74/74**; `py_compile_sweep` 105/0; archive privacy gate
HARD=0. The body itself reports the full suite as "running on this tip;
expected 0 failed — result appended when it lands" — the same
not-yet-landed phrasing #227's body used and checkpoint-08 flagged as
never fulfilled.

**Unlike #227, this one was fulfilled.** A PR comment posted after the
body, on tip `2bb2531`: **"Full pipeline/tests suite on this tip
(2bb2531), background run survived: 3133 passed, 1199 skipped, 63
subtests passed in 942.81s (0:15:42). Zero failures — the renderer
line's full gate is green again for the first time since #210. This is
the authoritative renderer tip."** This is the first time in this
checkpoint series that the full-suite deferral named as owed at every
prior checkpoint (checkpoint-05 through checkpoint-08) is actually
closed with a landed number rather than restated as pending.

**Process note in the PR's own body:** the agent first committed on the
wrong branch and moved the pointer back to origin's commit — recorded as
outside the standing rules, nothing lost because that branch was already
pushed.

### #232 — the ink residual, measured and declared a floor

**Question:** on the five `differs` features whose bands already agree
with Hancom to the pixel (`F06`–`F08`, `F13`, `F15` — checkpoint-08 §7's
named next question), what ink still differs, and why?

**Measurement, 1,000+ glyphs paired by character on `F06`–`F08`:** band
heights and baselines agree to 0.1 px; our glyph coverage is **1.80× the
reference's at 96 dpi** (median 1.76×, stems +78 %), falling to **1.16×
at 144 dpi** and to **≈1.0 at 192/288**. The relation is multiplicative
— delta ÷ reference-ink ≈ 1.0 on every block. `F01`, which reads `close`,
shows the same 1.71× ratio. A not-drawn block holds the same small offset
at every dpi (a scorer-noise control). Pearson(band ink fraction, `ssim`)
= **−0.80** over 48 blocks. The reference itself is not neutral here:
it is Hancom's PDF rasterised by **PyMuPDF 1.27.2**, whose own
antialiasing is therefore part of what "reference ink" means.

**Three alternative explanations tested and refuted, with numbers:**
dropped left-side bearing (line-origin dx **0.008 px**, not dropped);
face substitution (돋움 resolves to `gulim.ttc` face 2 = Dotum,
`substituted_character_share` **0.0**); scorer region/window error
(bands and baselines agree to 0.1 px, nothing straddled).

**Adopted, in `render_check` only:** a dpi-aware IoU tolerance derived
from the module's own already-stated 0.26 mm physical claim (1 px at
96 dpi, 2 at 144/192, 3 at 288); an ink-delta bound that scales as 1/dpi
(the antialias band is one pixel wide at any resolution, so its *share*
of a fixed physical region shrinks with dpi); a reported-but-not-gated
`ink.mass_*` coverage channel family; `RASTERISER_FLOOR` recorded in code
as the measured ratios and the multiplicative model. **Both bounds are
exact no-ops at 96 dpi** — pinned by a dedicated test — so every gated
channel (`ssim`, `iou`, `ink.delta`) is byte-identical on all 51
features and the #227 eval-task floor holds by construction. **Not
adopted:** any change to glyph rendering weight itself — whose
rasteriser is "right" between own_render and MuPDF-on-Hancom's-PDF is
declared unproven, not decided.

**Verdicts unchanged:** `F06`/`F07`/`F08`/`F13`/`F15` stay `differs`;
tally **3/38/8/2**; **9/9 pages**; deterministic.

**A real finding for the next slice, stated in the PR body:** **line
breaking is not resolution-independent.** At 96 dpi, `F06`'s line breaks
match Hancom's to within one character; at 144 dpi they lose **4–5
characters per line** (line 3 begins with a different word than
Hancom's). Break decisions are apparently made after the advance is
already rounded into device pixels. **Consequence stated plainly: the
default rendering dpi must not move until this is fixed**, because the
144 dpi tally otherwise measures two changes — the rasteriser floor and a
layout regression — at once.

**Evidence:** engine/tests **1228 passed**; `py_compile_sweep` 105/0;
archive privacy gate HARD=0. Holdout declared unchanged by construction
— no renderer, layout, or scoreboard code touched, only `render_check`'s
own gate module.

## 3. Regressions (with the PR's or commit's own explanation)

**None reported in this window.** #230, #231 and #232 each report the
tally, page count and agreement as unchanged from the prior tip, and each
states its own scope explicitly narrow enough to make that plausible:
#230 is a conflict-free merge with a regenerated-not-picked report
(the discipline #226 set), #231 touches only the support-matrix and
evals wiring, #232 touches only `render_check`'s gate bounds and not the
renderer or layout code. The regression streak this series has actually
found — #227's `test_cleanroom_evals` fix, checkpoint-08's headline
finding — carries no new instance in this window; the process rule it
produced ("verify a pre-existing claim against `main`, not a sibling
branch") is not tested again here because no PR in this window makes a
pre-existing claim at all.

## 4. Unsupported / declared elements still open

Carried from checkpoint-08, with this window's closures and new
attributions:

- **Closed since checkpoint-08:** the unmeasured `converge-3` worktree
  merge (§6/§8 there) — opened as #230 and measured (unchanged);
  the full `pipeline/tests` gate deferral carried since checkpoint-05 —
  landed green on #231's tip (3133/0/1199 skipped); the support-matrix
  coverage-property gap #227 opened — closed by #231's claim.
- **Newly attributed, not closed — declared a floor instead:** 5 of the 8
  `differs` rows (`F06`–`F08`, `F13`, `F15`) are now understood as
  rasteriser glyph-coverage weight (1.80× at 96 dpi), not a layout or
  metrics defect. #232's own body is explicit that this is a
  measurement, not a fix, and that ranking own_render's rasteriser
  against MuPDF-on-Hancom's-PDF is a **certification-process question**
  — whose glyph weight counts as "correct" — not a renderer bug with an
  obvious next patch.
- **Still `differs`, unattributed to the rasteriser, unchanged from
  checkpoint-08's list:**
  - `F35` (그림 — 어울림, TOP_AND_BOTTOM) — declared limit: `hp:pic@pos`
    places the anchored image without wrapping text around it.
  - `F48` (구역 나누기 — 가로 용지) — reference-side limit: Hancom's PDF
    export flattens every page to 595×841 pt portrait even when the
    section declares landscape A4; not improvable from the renderer
    side.
  - `F50` (머리말) — drawn, but positioned right of Hancom's; mechanism
    guess unchanged since checkpoint-05/06: centring against the page
    box rather than the header `hp:subList`'s own declared `textWidth`.
- **New, opened by #232 itself:** line breaking's dpi-dependence on
  `F06` (4–5 characters/line lost at 144 dpi vs 96) — named as a
  "slice in flight" for this checkpoint, not yet a branch in `origin`.
- **Unchanged from checkpoint-08:** whole-document computed layout's
  page-count/line-IoU failure (#199); writer line's default
  header/meta elements on a blank package save; `hp:ole`/`hp:chart`/
  `hp:container`/shapes/undecodable EMF-WMF placeholders;
  `DOUBLE_SLIM` border limitation; `hp:parameters` family;
  `hp:autoNum` field inside a footer draws nothing (`F51`);
  `hh:tabPr` stops inside the MCE switch never read; the tier-3
  raster's own `own-uncertified` status (gap 35); Hancom's first-column
  endnote placement in a two-column section (declared by #228, not
  fixed).

## 5. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / engine suite | full suite | notes |
|---|---|---|---|
| #230 | engine/tests **1221 passed / 135 skipped**; cleanroom **74/74** | not separately stated in this PR's own body | `py_compile_sweep` 105/0; archive privacy gate HARD=0; two consecutive render-check runs byte-identical |
| #231 | `test_support_matrix.py` **25/25**; cleanroom **74/74** | **3133 passed / 1199 skipped / 63 subtests passed, 0 failed** (PR comment, tip `2bb2531`) | `py_compile_sweep` 105/0; archive privacy gate HARD=0 |
| #232 | engine/tests **1228 passed** | holdout declared unchanged by construction (no renderer/layout/scoreboard code touched) | `py_compile_sweep` 105/0; archive privacy gate HARD=0 |

**The full-suite deferral streak that ran from checkpoint-05 through
checkpoint-08 (roughly #205 through #227, always "running" or unstated
in a reachable PR body) is closed by #231's comment.** This is the first
checkpoint in the series able to report a completed, zero-failure full
pipeline/tests run rather than restate the deferral as still owed.

## 6. Integration conflicts expected when lines converge

**The #227/#228 fork checkpoint-08 left open is fully closed.** #230's
merge was conflict-free on code; its own body reports the render-check
report as unchanged by the merge (no regeneration-vs-pick question arose,
unlike #226's merge of #222/#223). #231 and #232 are then a straight
chain off #230, not a new fork — the first stretch since checkpoint-06
without a renderer-line divergence to reconcile.

**Desktop and writer lines are untouched this window, and the desktop
re-merge gap has widened, not narrowed.** #221's last renderer re-merge
is still #215; the renderer tip has since moved through ten PRs
(#218, #219, #222, #223, #226, #227, #228, #230, #231, #232). No branch
for that re-merge exists in `origin` as of this checkpoint's writing —
searched directly (`git branch -r`) and found none named for it. The
re-merge is named again as owed, and, per this checkpoint's own prompt,
described as "in flight" — read here as work intended or underway
elsewhere that has not yet reached a pushed branch this checkpoint can
observe, not as a state this checkpoint measured.

## 7. Next measurable research question

**Is layout dpi-independent — do `F06`–`F08` and the rest of the corpus
break lines identically at 96, 144, 192 and 288 dpi?** #232 answered
checkpoint-08's question (what ink differs when rows already match) with
a floor, not a fix, and in doing so surfaced a different, sharper one:
at 144 dpi `F06` already loses 4–5 characters per line against its own
96 dpi break. That is not a rasteriser-weight question — it is a layout
decision (where a line breaks) depending on a rendering parameter (dpi)
it should be independent of. The concrete next steps, per #232's own
"not proven" section and its stated consequence:

1. Locate where an advance is rounded to device pixels before the
   line-break decision is made, on the `F06`–`F08` blocks specifically
   (already-measured pixel-exact-at-96dpi cases, so any dpi-dependence
   found there isolates cleanly from the rasteriser-weight question
   #232 just closed).
2. Fix rounding so breaks are computed in a resolution-independent unit
   and only rasterised at the end, then re-measure the 144 dpi tally —
   currently 7·38·4·2, but #232's own body warns this number conflates
   two effects and should not be read as progress until line breaking is
   fixed.
3. Only after that: revisit whether the default render dpi should move
   at all — #232 states plainly it should not move before this is fixed.

## 8. Certification status

Every own-render result in this checkpoint — the #227/#228 convergence
(#230), the support-matrix claim (#231), and the ink-residual measurement
(#232) — remains **own-uncertified**. None of the three PRs' own bodies
claims certification; #231's own body states its `render-check-fidelity`
claim as `partially` and explicitly not a certification (one document,
no second document scored). `render_cert.py` still cannot certify this
renderer absent a PDF text layer, unchanged since checkpoint-01.

**What moved, restated plainly:** the full `pipeline/tests` gate, owed
and restated as pending at every checkpoint from checkpoint-05 through
checkpoint-08, is now **landed and green** (3133 passed / 0 failed) on
#231's tip — the first time since #210 the renderer line's full suite
has been reported clean rather than deferred.

**Owed, carried forward and restated exactly, plus one addition:**

- Desktop line (#221) re-merged onto the current renderer tip — last
  done at #215, now stale by ten slices (§1, §6); no branch for this
  exists in `origin` yet despite being named "in flight."
- The dpi-independent line-breaking fix (#232's own finding, §7) — not
  yet a branch or PR.
- Codex-app-closed sessions moved (carried, not addressed by any PR in
  this window).
- Cursor login (carried, not addressed by any PR in this window).
