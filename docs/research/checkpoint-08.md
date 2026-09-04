# Checkpoint 08 — nine pages of nine, and the regression we had been calling pre-existing

Non-merging checkpoint. Written from `origin/claude/engine-e2-last-page`
(this branch, `docs/checkpoint-08`, is cut from that tip and stays
unmerged). Covers #226 (`claude/engine-e2-converge-2`: the small
convergence checkpoint-07 named as owed — #222 (F49 document fix) and
#223 (equation extent) finally in one tree — tally **3 · 38 · 8 · 2**,
pages 10 vs Hancom's 9, page agreement **49/51**), #227 (the
`test_cleanroom_evals` regression: #210 registered the `render-check`
corpus family in the manifest with no eval task; two agents on the
renderer line called the resulting failures "pre-existing" from
sibling-branch comparisons alone; the orchestrator verified against
`main`, found the tests pass there, and bisected the failure to `68fecae`
— #210's first commit; fix is `evals/tasks/render-check-01.yaml`, 74/74
cleanroom evals green), and the last-page PR (#228,
`claude/engine-e2-last-page`, base `claude/engine-e2-converge-2`: Hancom's
own Automation reports `PageCount` 10 while the exported PDF has 9 —
both real layouts, not a suppressed page; our own extra page was an
`END_OF_DOCUMENT` endnote read as end-of-*section*; deferring it to the
last section gives **9 = 9 pages, page agreement 51/51**, tally unchanged
at 3 · 38 · 8 · 2). Checkpoint-07 (`docs/checkpoint-07`, off
`claude/engine-e2-eq-extent`) carries forward as the record of the
diverged #222/#223 siblings and the state before this window.

**#227 and the last-page PR are themselves diverged siblings**, both
based on #226 (`claude/engine-e2-converge-2`) and neither containing the
other — see §1 and §6. Unlike checkpoint-07's #222/#223 fork, this one is
already being closed: a local worktree (`claude/engine-e2-converge-3`,
not yet a PR) has merged #227's branch on top of the last-page tip. That
merge is observed here, not authored by this checkpoint, and is not yet
measured or opened as a PR — named as the needed micro-convergence in §6
and owed in §8.

## What changed since checkpoint-07

| metric | checkpoint-07 | checkpoint-08 | moved in |
|---|---|---|---|
| renderer-line shape | #219 forks into #222 and #223, unreconverged | #222 + #223 **converged** in #226 (`converge-2`); #226 then itself forks into **two new siblings**, #227 and the last-page PR, neither containing the other | #226 (convergence), #227 + last-page (new fork) |
| render-check tally (51 features) | 3 · 38 · 8 · 2 (post-#222, pre-#223 numbers not yet in the same tree) | **3 · 38 · 8 · 2**, now measured with #222 and #223 both in the tree (#226), and unchanged again by #227 and the last-page fix | #226 (first joint measurement); unchanged by #227/#228 |
| render-check page count (synthetic doc) | 10 vs Hancom's 9 (post-#223 only; not yet joint with #222) | **9 vs 9 — exact**, after #226 joined the two fixes (still 10 vs 9 there) and the last-page PR named and fixed the residual page | #226 (joint measurement, still 10), last-page PR (9 = 9) |
| render-check page agreement | 49/51 (post-#223 only) | 49/51 (#226, joint) → **51/51** (last-page PR) | #226, last-page PR |
| `test_cleanroom_evals` | not named as failing in checkpoint-07's own body (two failures noted as "pre-existing, follow-up" by #222 and #223 without a `main` comparison) | **named as a real regression, bisected and fixed** — the "pre-existing" claim is now known false; introduced at `68fecae` (#210's first commit), carried through roughly #210–#226 (~15 PRs) before being caught | #227 |
| desktop line | #217 → **#221** (gap 34 closed, checkpoint-07 tip) | **unmoved** — no PR in #226–#228 touches it; its last re-merge with the renderer line was #215, now several renderer tips behind | — |
| writer line | #189 → **#224** (checkpoint-07 tip) | **unmoved** — #224 is unchanged in this window | — |
| runtime line | unmoved since checkpoint-06 | **still unmoved** | — |
| equation-extent evidence quality | #223's own body: "engine/tests green per the agent", no count — flagged in checkpoint-07 as looser than its siblings | not independently re-stated by #226/#227/#228, which report their own numbered counts (1217, 74, 1221 passed respectively); #223's own gap in its own PR body is unchanged | — |

## 1. Branch DAG

Renderer line: #219 (checkpoint-06 tip) forked into #222 and #223
(checkpoint-07), then converged and forked again:

| PR | branch | base | slice |
|---|---|---|---|
| #222 | `claude/engine-e2-columns-f49` | `claude/engine-e2-pagination` | F49 document fix (checkpoint-07) |
| #223 | `claude/engine-e2-eq-extent` | `claude/engine-e2-pagination` | equation extent (checkpoint-07 tip) |
| **#226** | `claude/engine-e2-converge-2` | `claude/engine-e2-eq-extent` | **merges #223 + #222 conflict-free on `own_render.py`; regenerates the render-check report/JSON/strips on the merged tree rather than picking a side — the small convergence checkpoint-07 called owed. New renderer tip: 3 · 38 · 8 · 2, pages 10 vs 9, agreement 49/51.** |
| **#227** | `claude/engine-e2-render-check-eval` | `claude/engine-e2-converge-2` | **adds `evals/tasks/render-check-01.yaml` — the eval task the `render-check` corpus family (#210) never got; closes the `test_cleanroom_evals` regression** |
| **#228** | `claude/engine-e2-last-page` | `claude/engine-e2-converge-2` | **defers `END_OF_DOCUMENT` endnote placement to the last section — the residual page named in checkpoint-07 §7 is now closed, 9 = 9, agreement 51/51 (this checkpoint's own worktree)** |

#227 and #228 both branch from #226 directly; neither's PR body claims
the other. #228's body calls #226 "the renderer line; sibling of #227"
explicitly. **Not yet a PR:** a local worktree
(`claude/engine-e2-converge-3`) has already merged `origin/claude/engine-e2-render-check-eval`
(#227) onto the last-page tip (#228) — `git log` shows a plain merge
commit with no conflict resolution recorded, sitting on top of #228's
`6e8e695`. This checkpoint observed that state via the worktree's branch
pointer only; it was not entered, driven, or measured here (worktree
exclusivity — see project memory). Whether the merged tree's tally, page
count and agreement still read 3 · 38 · 8 · 2 / 9-9 / 51-51, and whether
the full `pytest`/cleanroom-eval suite is clean on it, is unmeasured as
of this checkpoint.

Desktop line, unmoved since checkpoint-07:

| PR | branch | base | slice |
|---|---|---|---|
| #221 | `claude/desktop-own-render-edit` | `claude/desktop-own-render-converged` | gap 34 closed (checkpoint-07 tip, unmoved) |

The desktop line's last re-merge with the renderer line was **#215**
(`merge(engine): converge registration, fonts, and the table rule`),
itself off checkpoint-05. The renderer tip has since moved through #218,
#219, #222, #223, #226, #227/#228 — six-plus slices the desktop line has
not picked up. A re-merge of #221 onto the current renderer tip is owed,
named again here as it was implicitly owed since checkpoint-05/06.

Writer line, unmoved since checkpoint-07 (#189 → #224). Runtime line,
unmoved since checkpoint-06 (…→ #185 → #204).

Sibling docs branches: `docs/checkpoint-06` (off #219), `docs/checkpoint-07`
(off #223).

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #226 — the small convergence lands

`own_render.py` merged conflict-free (only #223 had touched it since the
#219 fork); the render-check report, JSON and one strip conflicted
because both #222 and #223 had regenerated them independently —
resolved by regenerating fresh **on the merged tree**, not by picking
either side's numbers. Notes and manifest auto-merged with both PRs'
sections kept.

Merged render-check: **3 match · 38 close · 8 differs · 2 unsupported**;
pages **10 vs Hancom's 9**; page agreement **49/51** — the first tree to
carry both "F49 `close`" and "pages 10 vs 9" together, exactly the
measurement checkpoint-07 §6/§7 said was missing.

Evidence: engine/tests **1217 passed / 135 skipped / 0 failed**
(including all determinism tests); `py_compile_sweep` 105/0; archive
privacy gate HARD=0 (WARN 50, pre-existing fixture/font).

**Stated plainly in the PR body itself:** the F49-tip full pipeline/tests
run showed 2 failures in `test_cleanroom_evals` that pass on `main` but
fail on #215 — a real regression on the renderer line, bisect in
progress at the time this PR was opened. No renderer-line gate was
called green pending that fix. This is the regression #227 closes.

### #227 — the cleanroom-evals regression, bisected and closed

**Root cause:** #210 registered the `render-check` corpus family in the
evals manifest but shipped no eval task for it, so
`test_cleanroom_evals`'s family-coverage property fired correctly — the
tests pass on `main` and fail from `68fecae` (#210's first commit)
onward. **Process failure, named explicitly in the PR body:** two agents
working the renderer line had called these failures "pre-existing"
without checking `main` — presumably comparing against a sibling
renderer branch, where the failure was indeed already present, rather
than against the actual base of comparison. The orchestrator caught this
by verifying against `main` directly and bisecting.

**Fix:** `evals/tasks/render-check-01.yaml` — family `render-check`,
sourced from `tests/corpus/render-check/render-check-01.{hwpx,pdf,blocks.json}`.
Its machine check runs `render_check.py` (own render vs the pinned
Hancom reference) and asserts the tally does not regress below the
committed baseline: match ≥3, close ≥38, differs ≤8, unsupported ≤2,
reference pages == 9 — verified by running it, exactly 3/38/8/2, 9
pages. Two `unmodified` checks guard the document and reference against
in-place edits. The coverage property itself is not weakened.

Evidence: cleanroom suite **74 passed**; `py_compile_sweep` 105/0;
archive privacy gate HARD=0. Full pipeline/tests suite reported
"running on this tip; expected 0 failed — result appended" in the PR
body — **no result was ever appended** (no comments on #227 as of this
checkpoint). Still an open loose end, not closed by this PR's own text.

### #228 — the last page, settled by asking Hancom itself

Through official Automation, `PageCount` = 10 while the exported PDF has
9 — and **both describe a real layout**: Hancom's editing view gives page
6 to a single paragraph whose only content is F45's anchored rectangle;
the export places that rectangle on page 5 (y 675–684 pt), and the
page-number fields run 1–9 with no gap. Nine pages were laid out, none
dropped. **The "Hancom suppresses a trailing furniture-only page"
hypothesis, open since checkpoint-07 §7 as possibility 1, is falsified.**
No suppression rule was adopted.

**Our 10th page was a different, renderer-side bug**, unrelated to the
screen/print discrepancy above: page 8 held only the endnote, because
`hp:endNotePr/hp:placement@place="END_OF_DOCUMENT"` was read as
end-of-*section* rather than end-of-*document*, so section 0's note was
placed where the overflowing `F47` table left no room. Hancom sets the
note on page 9 of 9, under the last inked line (separator y=464.5,
note body y=470.5–478.5, body text ending 456.3). **Rule adopted:** defer
`END_OF_DOCUMENT` notes to the last section.

Render-check: pages 10 vs 9 → **9 = 9, exact**; page agreement 49/51 →
**51/51**; tally unchanged 3 · 38 · 8 · 2; ssim/IoU flat to three
decimals (only `F49`'s band moves, since it now ends at the endnote
rather than the body-box foot). Corpus 52/52 PNGs byte-identical;
private holdout 18/18, every channel unchanged; deterministic.

Evidence: engine/tests **1221 passed**; `py_compile_sweep` 105/0;
archive privacy gate HARD=0.

**Not proven, stated in the PR's own body:** Hancom sets the note in the
first column (x 85–298) of the two-column section where the renderer
uses full width — declared, not fixed; mixed placement across sections
untested.

## 3. Regressions (with the PR's or commit's own explanation)

**#227 fixes a real regression** — the first one in this checkpoint
series that was actually mis-diagnosed in flight rather than merely
carried forward as a known trade-off. `test_cleanroom_evals` failed on
every renderer-line commit from `68fecae` (#210) through #226 — roughly
15 PRs of renderer-line history — while two separate agent sessions
recorded it as "pre-existing" in their own PR bodies (#222's and #223's,
per checkpoint-07 §5) without checking whether it also failed on `main`.
It did not. **New process rule, recorded here for the orchestrator
memory:** a "pre-existing failure" claim is verified against `main`
before it is accepted, not against a sibling branch or the immediately
preceding commit. Neither #226, #227, nor #228 reports any other numeric
regression in its own body.

## 4. Unsupported / declared elements still open

Carried from checkpoint-07, with this window's closures:

- **Closed since checkpoint-07:** the residual render-check page (§7 of
  checkpoint-07 — last-page PR, #228, 10 → 9, both candidate hypotheses
  distinguished: it was neither Hancom-export suppression nor unnamed
  renderer over-reserve, but the endnote end-of-section/end-of-document
  conflation); the two `test_cleanroom_evals` failures long carried as
  "pre-existing" (#227 — they were a real regression, now fixed).
- **Still open, unnamed in checkpoint-07, now the checkpoint's own next
  question:** with pages (9=9) and agreement (51/51) both closed, the
  remaining **8 `differs`** rows have no single named mechanism yet — see
  §7.
- **Still `differs`, current state (post-#228, tally 3 · 38 · 8 · 2), with
  mechanism where known (unchanged from checkpoint-07's own list, since
  no PR in this window touches these features except `F49`'s band, whose
  verdict does not move):**
  - `F06`–`F08` (줄간격 PERCENT 130/160/200%) — bands agree with Hancom to
    the pixel; the `differs` verdict is `ssim`/`ink Δ` alone, attributed
    to rasteriser/hinting differences, not layout. **First candidate for
    the next measurable question (§7).**
  - `F13` (자간), `F15` (상대 크기 relSz) — same shape: bands correct,
    miss `close` on ssim/ink margin alone.
  - `F35` (그림 — 어울림, TOP_AND_BOTTOM) — declared limit: `hp:pic@pos`
    places the anchored image without wrapping text around it.
  - `F48` (구역 나누기 — 가로 용지) — reference-side limit: Hancom's PDF
    export flattens every page to 595×841 pt portrait even when the
    section declares landscape A4; not improvable from the renderer side.
  - `F50` (머리말) — drawn, but positioned right of Hancom's; mechanism
    guess unchanged since checkpoint-05/06: centring against the page box
    rather than the header `hp:subList`'s own declared `textWidth`.
- **Unchanged from checkpoint-07:** whole-document computed layout's
  page-count/line-IoU failure (#199); writer line's default header/meta
  elements on a blank package save; `hp:ole`/`hp:chart`/`hp:container`/
  shapes/undecodable EMF-WMF placeholders; `DOUBLE_SLIM` border
  limitation; `hp:parameters` family; `hp:autoNum` field inside a footer
  draws nothing (`F51`); `hh:tabPr` stops inside the MCE switch never
  read; the tier-3 raster's own `own-uncertified` status (gap 35);
  Hancom's first-column endnote placement in a two-column section
  (declared by #228, not fixed).

## 5. Tests actually run per PR (from PR bodies)

| PR | orchestrator / engine suite | full suite | notes |
|---|---|---|---|
| #226 | engine/tests **1217 passed / 135 skipped / 0 failed** | 2 `test_cleanroom_evals` failures found, pass on `main`, bisect in progress at time of writing | `py_compile_sweep` 105/0; archive privacy gate HARD=0 (WARN 50, pre-existing) |
| #227 | cleanroom suite **74 passed** | reported "running on this tip; expected 0 failed — result appended" — **never appended**, no PR comments as of this checkpoint | `py_compile_sweep` 105/0; archive privacy gate HARD=0 |
| #228 | engine/tests **1221 passed** | not separately stated in this PR's body | `py_compile_sweep` 105/0; archive privacy gate HARD=0 |

Full-suite (`pipeline/tests`) gate deferral streak, carried since
checkpoint-05/06 through #205–eq-extent (#223) at checkpoint-07, is now
**#205 through the eval-fix tip (#227)** — the fix itself is verified
(74/74 cleanroom evals), but the broader full pipeline/tests run on that
tip is described as running, with no completed result recorded in any PR
body reachable from this checkpoint. Still owed, as at every prior
checkpoint in this series.

## 6. Integration conflicts expected when lines converge

**#226 closed the convergence checkpoint-07 named as owed** (§6 there):
#222 and #223, forked from #219, are now one tree, merged conflict-free
on code with a from-scratch regeneration of the shared reference
artifacts (report/JSON/strips) rather than a side-pick.

**A new fork opened immediately after, and needs the same treatment.**
#227 (eval-fix) and #228 (last-page) both branch from #226 directly and
neither contains the other — the same shape as #222/#223 after #219.
Unlike that fork, though, **the convergence is already underway**: a
local worktree on branch `claude/engine-e2-converge-3` has merged
`origin/claude/engine-e2-render-check-eval` on top of the last-page tip,
producing a plain merge commit with no conflict markers left in the
log. This checkpoint did not enter that worktree (worktree exclusivity)
and has not re-run render-check, the cleanroom eval suite, or the full
pipeline/tests gate on the merged tree — so whether it still reads
3 · 38 · 8 · 2 / 9=9 / 51-51, and whether the `evals/tasks/render-check-01.yaml`
baseline still holds unmodified, is unmeasured. **Owed: open the
converge-3 merge as a PR (or re-derive it) and re-run render-check +
cleanroom evals on it**, the same discipline #226 applied to #222/#223.

**Desktop and writer lines are untouched this window**, so no new
conflict surface opens there — but the desktop line's last renderer
re-merge (#215) is now six-plus renderer slices stale (#218, #219, #222,
#223, #226, #227/#228), and a re-merge is owed independent of any
conflict actually appearing yet.

## 7. Next measurable research question

**With pages (9=9) and agreement (51/51) both closed, what does the
remaining 8-row `differs` queue reduce to?** Two of its members
(`F06`–`F08`, `F13`, `F15` per §4) already show bands that agree with
Hancom to the pixel and fail only on `ssim`/`ink Δ` — i.e., **the row
geometry is right and something about the ink inside a correctly-placed
row is not.** The prompt for this checkpoint names the concrete starting
point: **the ssim/ink-only residuals on the pixel-exact-row line-spacing
blocks, `F06`–`F08`.** These three (130/160/200% `PERCENT` line spacing)
already measure exact bands (121/121, 140/140, 94/94 px against Hancom's
own, per `render-check-01.md` note 1) — so the open question is purely
**what ink differs when the rows already match**: font hinting/rasteriser
differences between the two engines' glyph rendering at 96 dpi, subpixel
positioning within an already-correct line box, or a residual
character-metric error too small to move the band but large enough to
move `ssim_inked`. Distinguishing these needs a per-glyph ink-overlay
probe on `F06`–`F08` specifically (not another page- or block-level
metric), since the row-level numbers this checkpoint and the prior three
have been reporting are already exhausted for these three features.

Once `claude/engine-e2-converge-3` (§6) becomes a PR and is measured, the
same 8-row `differs` list should be re-read on that tree before the
ink-only probe starts, in case the merge itself moves any of the eight.

## 8. Certification status

Every own-render result in this checkpoint — the F49/equation-extent
convergence (#226), the cleanroom-evals regression fix (#227), and the
last-page endnote fix (#228) — remains **own-uncertified**. None of the
three PRs' own bodies claims certification; `render_cert.py` still
cannot certify this renderer absent a PDF text layer, unchanged since
checkpoint-01.

**Owed, carried forward and restated exactly:**

- Full `pipeline/tests` gate result on the eval-fix tip (#227) —
  reported running, never appended (§5).
- The `claude/engine-e2-converge-3` merge (§6) opened as a PR and
  measured — render-check, cleanroom evals, and full pipeline/tests all
  re-run on the merged tree, not assumed unchanged.
- Desktop line (#221) re-merged onto the current renderer tip — last done
  at #215, now stale by six-plus slices (§1, §6).
- Codex-app-closed sessions moved (carried, not addressed by any PR in
  this window).
- Cursor login (carried, not addressed by any PR in this window).
