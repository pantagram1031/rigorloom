# Checkpoint 03 — the fit rule, sections, the kstartup overflow, and what the holdout says

Non-merging checkpoint. Written from `claude/engine-e2-kstartup-ink` (this
branch, `docs/checkpoint-03`, is cut from that tip and stays unmerged).
Covers PR #196 (row-fit rule, the linefit branch checkpoint-02 saw unopened),
PR #198 (sections + equal-width columns, E2.7), PR #200 (kstartup page-6
table-overflow fix), plus the docs side-branches #197 (residual advance +
ink-delta research) and #199 (holdout tracker 01). Checkpoint-02's
`docs/checkpoint-02.md` (PR #195) carries forward as the record of #190/
#192/#194 and the pre-PR fit-rule numbers this checkpoint's #196 now
confirms with full-suite evidence.

## What changed since checkpoint-02

| metric | checkpoint-02 | checkpoint-03 | moved in |
|---|---|---|---|
| corpus row-fit predicate | 47/51 (old) → 50/51 (new, unopened branch) | **50/51, now PR #196 with full-suite evidence** | #196 |
| holdout late blocks | 54/243 → 7/243 (5 new early) | **unchanged, now independently reproduced by the tracker** | #196, confirmed by #199 |
| holdout page-assignment agreement | 189/243 → 231/243 | **231/243, exact-reproduced** | #199 |
| sections / columns | not implemented | **implemented, synthetic-fixture evidence only** | #198 |
| kstartup page-6 | glyph-on-glyph overlap (new defect, #197) | **fixed at root — declared height 70529 vs content 96966 HWPUNIT** | #200 |
| kstartup computed ssim / pair rate | 0.607 / 0.888 (pre-#200 baseline) | **0.624 / 0.933** | #200 |
| kstartup `ink_delta_abs_max` | 0.0621 (checkpoint-02) → 0.0556 (reproduced, #197) | **still 0.0556 > 0.05 floor — page-22 drift, unfixed** | open |
| holdout tracker (new instrument) | did not exist | **auto mode reproduces published numbers exactly; computed whole-doc fails (21/18 pages, line IoU 0.180)** | #199 |
| ranked user-visible gap #1 | (not ranked) | **missing paragraph justification** — slice declared for `claude/engine-e2-justify`, not yet pushed | #199 |
| ranked user-visible gap #2 | (not ranked) | **equation variables not math-italic** | #199 |

## 1. Branch DAG

Renderer line (`claude/engine-e2-*`, `claude/own-renderer-mvp`), now **11
PRs stacked deep** from the MVP:

| PR | branch | base | slice |
|---|---|---|---|
| #166 | `claude/own-renderer-mvp` | `main` | tier-3 OWPML renderer MVP |
| #173 | `claude/engine-e2-typography` | `own-renderer-mvp` | E2.2/E2.3 typography |
| #179 | `claude/engine-e2-linebreak` | `engine-e2-typography` | E2.1 line breaker |
| #183 | `claude/engine-e2-report-fidelity` | `engine-e2-linebreak` | E2 report-class fixes |
| #187 | `claude/engine-e2-equations` | `engine-e2-report-fidelity` | E2 equations |
| #190 | `claude/engine-e2-advance` | `engine-e2-equations` | E2.1 follow-up, space advance |
| #192 | `claude/engine-e2-reflow` | `engine-e2-advance` | E2.5 flow pass / reflow |
| #194 | `claude/engine-e2-notes-headers` | `engine-e2-reflow` | E2.6 headers/footers/notes |
| #196 | `claude/engine-e2-linefit` | `engine-e2-notes-headers` | row-fit predicate (baseline, not vertsize) |
| #198 | `claude/engine-e2-sections` | `engine-e2-linefit` | E2.7 sections + equal-width columns |
| #200 | `claude/engine-e2-kstartup-ink` | `engine-e2-sections` | kstartup page-6 table-overflow fix |

All stacking verified directly: `git merge-base --is-ancestor` returns YES
for notes-headers→linefit, linefit→sections, sections→kstartup-ink. #196
is the branch checkpoint-02 flagged as an authoritative tip with **no PR
opened**; it is now a merged-into-the-stack, fully evidenced PR.

Sibling docs branches off this line, **not stacked further** (same pattern
checkpoint-02 noted for #191/#193):

| PR | branch | base | note |
|---|---|---|---|
| #197 | `docs/research-residual` | `engine-e2-linefit` | residual advance term + kstartup ink delta, measured |
| #199 | `docs/holdout-scoreboard-01` | `engine-e2-sections` | holdout tracker 01 |
| #195 | `docs/checkpoint-02` | `engine-e2-linefit` | prior checkpoint (this doc's predecessor) |

Verified directly: `git merge-base --is-ancestor` returns **NO** for
`docs/research-residual → engine-e2-linefit`, `docs/holdout-scoreboard-01 →
engine-e2-sections`, and `docs/checkpoint-02 → engine-e2-sections` — none
of these docs files exist on the renderer line's tree; they remain
unmerged siblings exactly as checkpoint-02's #191/#193 pattern.

### Writer / Runtime / Desktop lines

Writer line unchanged in position since checkpoint-01/02: #177
(`engine-e3-owpml-writer`, off `main`) → #180
(`engine-e3-writer-routing`, "one writer for every HWPX the repo emits") →
#189 (`engine-e3-hancom-accept`, title states plainly **"live leg owed"**
— the Hancom acceptance harness exists, but the live Hancom leg has not
been run). That is still the writer line's authoritative tip; nothing in
this checkpoint's window touches it, and the live leg remains open on the
bench throughout. Runtime, desktop and standalone-docs lines are likewise
unmoved by #196/#198/#200/#197/#199 and are not re-verified here — see
checkpoint-01/02 for their tables.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #196 — the row-fit test lets a line's descender past the margin

Fit rule: a line fits when `vertpos + baseline ≤ usable` (baseline =
cached `hp:lineseg@baseline`, or `round(0.85 × vertsize)` for computed
lines) — replaces `vertpos + vertsize`.

Corpus (51 pages, 10 forms): old predicate 47/51, new predicate **50/51**
— zero regression on the 47 that already fit; auto mode all 51 PNGs
sha256-identical. Computed mode: page counts unchanged on all 10 forms
(kstartup 22/22); kstartup line IoU 0.5532 → 0.5544. The one unresolved
page (`nrf`'s empty trailing paragraph) matches what the research
predicted.

**Private holdout (aggregate only):** 18/18 pages before and after; blocks
landing one page late **54/243 → 7/243**; page-assignment agreement
**189/243 → 231/243**. Five blocks that used to agree now land one page
early — a new, smaller disagreement, stated not netted.

Evidence: engine/tests 1125/0 failed/135 skipped; full suite **4078
passed / 146 skipped / 0 failed** (20m54s); privacy gate HARD=0.

### #197 — the residual advance term and the kstartup ink delta (research)

**Q1 (moel-2013/2025 fill deficit 0.89/0.91):** no flat glyph-metric
mechanism confirmed — every glyph class measures inside ±0.01 em on the
unstretched-span gate; the 한양-face hypothesis from checkpoint-02 is
refuted (those faces resolve correctly and are <2% of either form's
text). The dominant unresolved face is **휴먼명조** (31% of moel-2013,
55% of moel-2025 characters), substituted with Malgun Gothic; its spans
condense below 0.98 scale 4–6× more often than a resolved face's, invisible
to the current unstretched-only gate. Next slice proposed: a condense-ratio
agreement gate, not another advance fit.

**Q2 (kstartup `ink_delta_abs_max`, 0.0621 checkpoint-02 → 0.0556
reproduced here):** three page-localized mechanisms by ink mass — (1) the
already-known page-22 block-assignment drift (dominant); (2) **a block
overflowing without a page break on page 6, literal glyph-on-glyph
overlap** (new); (3) **table cell shading drawn light-blue where Hancom
draws white** (new, later refuted by #200's measurement). Items 2 and 3
handed directly to #200.

### #198 — sections + equal-width columns (E2.7)

Every `Contents/section*.xml` read in spine order (`content.hpf`, with a
numeric fallback so `section10` doesn't sort before `section2`); each
`hp:secPr`/`hp:pagePr` applies its own size, margins, header/footer
heights, `hp:startNum@page` restart-vs-continue; a section starts a new
page. `hp:colPr` with `sameSz=true` fills column 1 then column 2 then the
page, modelled as a narrower virtual page reusing the existing overflow
sweep; `hp:colLine` separators drawn; `hp:p@columnBreak` advances a
column, not a page. Declared, not honored: unequal column widths, vertical
text, per-column footnote reserve/numbering.

**Coverage measured:** all 10 corpus forms and the private holdout declare
one section, `colCount=1` — so all render byte-identical before/after
(sha256 + page counts). 12 synthetic-fixture tests prove spine order,
section-boundary geometry, numbering restart/continue, column
fill/break/separator/no-overflow, and the declared skips. **Stated
plainly: nothing here is measured against a Hancom reference** — no
available document exercises sections or columns.

Evidence: 191 pre-existing tests unchanged + 12 new; full suite **3035
passed / 1199 skipped / 0 failed** (18m46s, core-only checkout); privacy
gate HARD=0.

### #199 — holdout tracker 01 (the recurring instrument)

**Auto mode (shipped default) reproduces the published numbers exactly:**
18/18 pages; ssim_inked 0.1289 (cited 0.1263); pair rate 0.9041; line
breaks 71/260; flow page-assignment 231/243; regression floor 6/6.

**New finding — computed mode fails on prose:** full flow relayout with
computed line layout gives **21/18 pages**, line IoU **0.180** (floor
0.20 — 2/6 checks fail), page assignment 48/243. This axis had never been
scored on this document before. It bounds today's claim precisely:
per-paragraph relayout (auto) is sound; whole-document computed layout is
not.

**Worst two pages, mechanisms (no content quoted):** (1) body text
ragged-right where the reference is fully justified — dominant,
whole-document; (2) equation variables upright, not math-italic
(declared); (3) equation-box double-rule stroke offset, sub-pixel.

**Ranked user-visible gaps:** 1) missing paragraph justification, 2)
non-italic equation variables, 3) equation border stroke. Nothing
structural (pagination, order, tables, captions) is wrong in auto mode.
Justification is named as the next renderer slice after the kstartup ink
fixes — a branch `claude/engine-e2-justify` is declared for it but is not
yet pushed to origin as of this checkpoint.

### #200 — kstartup page-6 table-overflow fix

**Root cause 1 (fixed):** kstartup's largest anchored `pageBreak="CELL"`
table declares `hh:sz@height=70529` HWPUNIT but its content needs
**96,966** (37% more) — the fit test trusted the declaration in both
`auto` and `computed`. One of its rows is one Hancom itself renders across
a page break. Fix: content-measured fit, move-or-split at the row
boundary under both block-layout policies.

**Root cause 2 (refuted, not fixed):** the cell-shading report from #197
is a measurement artifact — every `hc:winBrush` carries `alpha="0"`
uniformly, the label cells render (223,234,245) vs Hancom's (222,233,245),
a 1/255 rounding at the *correctly* aligned position; the earlier
observation was a page-22-drift misalignment artifact. No code changed;
tests pin current behaviour.

**kstartup, computed mode:** ssim **0.607 → 0.624**, pair rate **0.888 →
0.933**, line IoU 0.554 → 0.559; page count exact (22) both ways;
`ink_delta_abs_max` **unchanged at 0.0556** (>0.05 floor) — driven by the
page-22 block drift, a different bug, still open.

Evidence: engine renderer suite 196 passed; other 9 forms byte-identical
(sha256, auto + computed); full suite **4093 passed / 146 skipped / 0
failed** (24m14s); privacy WARN 42→44 (two new digit/hangul-proximity
WARNs in the new test file, non-gating); privacy gate HARD=0.

## 3. Regressions (with the PR's or commit's own explanation)

| PR | metric | moved | explanation given |
|---|---|---|---|
| #196 | holdout: 5 blocks move from agreeing to one page early | 189/243 → 231/243, net +42 | "the one cost of the more permissive rule" — traded for 47 blocks fixed from late; net positive, stated not hidden |
| #198 | (declared, not measured as a regression) | unequal column widths, vertical text, per-column footnote handling — declared unimplemented | no corpus or holdout document exercises them to measure against |
| #199 | computed whole-document layout | 21/18 pages, line IoU 0.180 (floor 0.20) | new axis, never scored before; explicitly bounds the "computed" claim rather than being netted against auto mode's pass |
| #200 | kstartup `ink_delta_abs_max` | unchanged 0.0556 vs 0.05 floor | "driven by the page-22 block drift, a different bug, still open" — root cause 1 fixed the page-6 defect cleanly without moving this number |

No corpus form regressed on sha256/page-count/scoreboard channels across
#196, #198 or #200; each PR states this explicitly for the 9-10 unaffected
forms.

## 4. Unsupported / declared elements still open

Carried from checkpoint-02, with items this checkpoint's PRs closed,
refined, or added:

- **Closed since checkpoint-02:** the row-fit predicate — was an unopened
  branch with no orchestrator evidence; now PR #196, full-suite confirmed
  (50/51 corpus, 7/243 late blocks). kstartup's page-6 glyph-on-glyph
  overlap (#197's new finding) — fixed by #200. The cell-shading
  hypothesis from #197 — refuted, not fixed, by #200's measurement.
- **New, implemented but corpus/holdout-unverified (#198):** sections past
  section0, `hp:colPr` multi-column flow. Declared: unequal column widths,
  vertical text, per-column footnote reserve/numbering. Stated plainly
  that no available document (corpus or private holdout) exercises either
  feature — the only evidence is 12 synthetic fixtures.
- **New, ranked by the holdout tracker (#199):** missing paragraph
  justification is now the #1 user-visible gap (dominant, whole-document,
  scored 0.180 line IoU on the worst axis); equation variables not
  math-italic is #2 (carried forward from checkpoint-02's own "largest
  named visual gap" note, now independently ranked by a different
  instrument); equation-box double-rule stroke offset is #3, sub-pixel.
- **New, standing open item (#200):** the kstartup page-22 block-position
  drift is now explicitly the *sole* remaining `ink_delta_abs_max`
  contributor on that document (0.0556 vs 0.05) — both other mechanisms
  #197 raised (page-6 overlap, cell shading) are closed one way or the
  other.
- **New axis, unresolved (#199):** whole-document computed layout fails
  page-count and line-IoU floors (21/18 pages, 0.180 < 0.20) on the
  private holdout — never measured before this checkpoint; per-paragraph
  auto relayout is unaffected and remains sound.
- **Still open, unchanged from checkpoint-02:** Hancom HFT fonts
  substituted (declared per character count); the 휴먼명조 substitution's
  condense-ratio behaviour (#197's new, more specific framing of the old
  "second advance term" question); line-breaker exact-position agreement
  (58/216, unmoved — no PR in this window touched the line breaker);
  `hp:ole`/`hp:chart`/`hp:container`/shapes/undecodable EMF-WMF grey
  placeholders; only `DOUBLE_SLIM` draws two border strokes; text wrap
  around anchored objects; `hp:parameters` family unrendered; equations'
  declared-unsupported constructs unchanged (`size`, `color`, `bigg`/
  `small`, `binom`, `choose`, `buildrel`, `rel`, `dyad`, `col` family,
  unbalanced fences; italic variable shaping still the largest named
  visual gap, now also the tracker's #2 ranked user-visible gap); row
  heights approximate (8/81 tables miss height >2%).
- **Writer line, unchanged since checkpoint-01/02:** #189's Hancom
  acceptance harness exists; its live leg has not been run — stated in the
  PR's own title, "live leg owed."

## 5. Tests actually run per PR (from PR bodies)

| PR | orchestrator / engine suite | full suite | notes |
|---|---|---|---|
| #196 | engine/tests 1125/0 failed/135 skipped | 4078 passed / 146 skipped / 0 failed (20m54s, main-based) | `py_compile_sweep` 103/0; privacy HARD=0 |
| #197 | (docs-only PR) | not applicable | Sonnet-written research, no private document opened |
| #198 | 191 pre-existing + 12 new | 3035 passed / 1199 skipped / 0 failed (18m46s, core-only checkout) | `py_compile_sweep` clean; privacy HARD=0; implemented by Sonnet after an Opus 529s design pass |
| #199 | (docs-only PR) | not applicable | Sonnet-written; depends on #198 |
| #200 | engine renderer suite 196 passed | 4093 passed / 146 skipped / 0 failed (24m14s, main-based) | `py_compile_sweep` 103/0; privacy WARN 42→44 (non-gating), HARD=0 |

No orchestrator or full-suite run is claimed for #197 or #199 — both are
research/tracker documents, not engine changes, and say so in their own
bodies ("docs only," "no private document opened").

## 6. Integration conflicts expected when lines converge

Unchanged in kind from checkpoint-01/02, re-verified against the deeper
tip:

- **The renderer line is now 11 PRs stacked deep** (#166 → #200), each
  base-to-head verified by `git merge-base --is-ancestor`. That depth is
  itself a review-burden concern the checkpoint records plainly: a single
  merge to `main` would need to review or re-review the full chain, since
  none of #173–#200 has landed on `main` yet — every one of them is still
  a branch tip stacked on the previous branch tip, not a merged commit.
- **Docs side-branches remain unmerged siblings**, not stacked further:
  #197 (`docs/research-residual`) and #199 (`docs/holdout-scoreboard-01`)
  each branch off a renderer-line commit but are absent from that line's
  tree going forward — `git merge-base --is-ancestor` confirms NO in both
  directions checked. This checkpoint's own predecessor, `docs/checkpoint-02`
  (#195), is the same pattern: also absent from `engine-e2-sections`'s
  tree. Three unmerged docs heads now sit off this one renderer line.
- **Renderer vs writer:** still no direct file overlap observed. The
  renderer line (through #200) continues to touch
  `engine/scripts/own_render.py`, `engine/references/own-render-notes.md`,
  `engine/tests/test_own_render.py`. The writer line (#177 → #180 → #189)
  is unmoved since checkpoint-01/02 and still touches
  `engine/scripts/hwpx_write.py`, `xml_backend.py`, `preedit.py`,
  `tidy_hwpx.py`, `engine/references/owpml-writer-notes.md`,
  `engine/tests/test_hwpx_*.py`. Both share the `engine/` tree and corpus
  fixtures; a full-suite run after any merge remains the actual check. The
  writer line's #189 (Hancom acceptance harness) is a second axis of
  incompleteness on top of the file-overlap risk: it has never run against
  live Hancom, so a merge would combine an evidenced renderer chain with a
  writer chain whose acceptance harness is itself unproven end-to-end.
- **Desktop's mid-merge state — preserved, unchanged since checkpoint-01/02:**
  not touched by any PR in this window (#196/#197/#198/#199/#200 are all
  renderer-line or renderer-line docs); still an open reconciliation
  between Fork A and Fork B, worth flagging precisely because nothing in
  this window moved it.
- **Renderer/writer vs runtime/desktop:** no shared files observed; these
  lines only meet at `main`.

## 7. Next measurable research question

Two threads stand open with numbers already in hand:

1. **The page-22 block-position drift on kstartup** is now the *sole*
   remaining contributor to `ink_delta_abs_max` (0.0556 vs the 0.05
   floor) — both alternative mechanisms #197 raised on that document
   (page-6 overflow, cell shading) are resolved one way or the other by
   #200. The next slice is a targeted diagnosis of that one drift, not
   another document-wide ink sweep.
2. **Paragraph justification** is the holdout tracker's #1 ranked
   user-visible gap, dominant and whole-document on the worst-scoring
   page (ragged-right where the reference is fully justified). A slice is
   declared for `claude/engine-e2-justify` (not yet pushed to origin as of
   this checkpoint) — the tracker names it explicitly as the next renderer
   slice, ahead of italic equation variables (#2) and the equation-box
   stroke offset (#3).

Separately, #197's reframing of the "second advance term" question — from
an unconfirmed 한양-face guess to a specific, measured 휴먼명조
condense-ratio pattern (4–6× more sub-0.98 condensing than a resolved
face, invisible to the unstretched-only gate) — is a concrete next
instrument (a condense-ratio agreement gate) rather than another blind
advance-fit sweep. It remains unscheduled against the two items above.

Also unresolved and unmoved this window: whole-document computed layout
(#199's new finding, 21/18 pages / 0.180 line IoU) has no assigned slice
yet; line-breaker exact-position agreement (58/216) is unchanged since
checkpoint-02, no PR in this window touched the line breaker.

## 8. Certification status

Every own-render result in this checkpoint — the row-fit rule, the
sections/columns geometry, the residual-advance and ink-delta research,
the holdout tracker's numbers, and the kstartup page-6 fix — remains
**own-uncertified**. `grade` is stated as `own-uncertified` explicitly in
#196, #198 and #200's own bodies; `pipeline/scripts/render_cert.py` still
cannot certify this renderer absent a PDF text layer. None of these five
items, merged or unmerged, claims certification, and none is merged to
`main`.

The holdout tracker (#199) is this checkpoint's clearest instance of the
distinction checkpoint-02 drew for the Codex preview: it is a repeatable,
aggregate-only measurement instrument, not a certified artifact. Its value
here is the same shape — it reproduced every previously-published number
exactly (auto mode) and, in the same run, surfaced a genuinely new failure
(computed whole-document layout) that no prior PR had scored. That is the
standing pattern this checkpoint keeps: a new instrument changes what gets
measured next, never what counts as certified.
