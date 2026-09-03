# Checkpoint 02 — advances, reflow, notes, and the fit rule

Non-merging checkpoint. Written from `claude/engine-e2-linefit` @ `34e5c84`
(this branch, `docs/checkpoint-02`, is cut from that tip and stays unmerged).
Covers PR #190 (space advance, E2.1 follow-up), PR #192 (flow pass / reflow,
E2.5), PR #194 (headers, footers, notes, E2.6), and the pending linefit work
on branch `claude/engine-e2-linefit` (2 commits, **no PR opened** — checked
by `gh pr list`/`gh pr list --search` returning empty for that head across
all states). #187 (equations) carries forward unchanged from checkpoint-01
as the ancestor these four build on.

## What changed since checkpoint-01

| metric | checkpoint-01 | checkpoint-02 | moved in |
|---|---|---|---|
| corpus break-position agreement | 43/216 | **58/216** | #190 |
| holdout break-position agreement | 37/260 | **71/260** | #190 |
| flow-pass page-assignment agreement | (not measured) | **468/590 (0.793)** | #192 |
| kstartup computed pagination | 20/22 (auto, wrong) | **22/22** | #192 |
| holdout one-page-late blocks | (not measured) | 54/243 → **7/243** | linefit branch |
| holdout page-assignment agreement | (not measured) | 189/243 → **231/243** | linefit branch |

## 1. Branch DAG

Grouped into five research lines, as in checkpoint-01, each with its
**authoritative tip**. Only the renderer line moved since checkpoint-01;
writer, runtime, desktop and standalone-docs lines are unchanged and not
re-verified here — see checkpoint-01 for their tables.

### Renderer line (`claude/engine-e2-*`, `claude/own-renderer-mvp`)

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
| *(none)* | **`claude/engine-e2-linefit`** | `engine-e2-notes-headers` | **row-fit predicate — AUTHORITATIVE TIP, unopened as a PR** |

Sibling docs branches off this line, **not stacked further** (same pattern
checkpoint-01 noted for #186):

| PR | branch | base | note |
|---|---|---|---|
| #186 | `docs/hangul-feature-catalog` | `engine-e2-report-fidelity` | scoreboard catalog |
| #191 | `docs/codex-preview-regression` | `engine-e2-advance` | Codex preview read for regression evidence |
| #193 | `docs/research-line-fit` | `engine-e2-reflow` | measured the rule the linefit branch then implemented |

Verified directly: `git merge-base --is-ancestor` returns **NO** for both
`docs/research-line-fit → engine-e2-linefit` and
`docs/codex-preview-regression → engine-e2-advance` — the docs those two
PRs wrote (`docs/research/line-fit-rule.md`,
`docs/research/codex-preview-regression.md`) exist only on their own
branches, not on this checkpoint's line. The linefit branch implements
#193's *recommendation* from its own commit, not by merging #193's docs
file — `docs/research/line-fit-rule.md` is absent from this repo's tree at
`34e5c84`.

### Writer / Runtime / Desktop / standalone-docs lines

Unchanged from checkpoint-01: writer authoritative tip #180, runtime #185
(sibling #181), desktop #184 (Fork A stale at #161, Fork B current), docs
#171. None of #190/#192/#194/linefit touches these lines' files.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #190 — space advance = half the character cell

Corpus, multi-line paragraphs: break-position agreement **43/216 → 58/216**
(jumin 9→14, saeopja 5→9, moel-2013 7→10); conditional early/late
29/142 → **82/81** (systematic late bias gone); `cached_line_fill` median
0.92 → 0.97. Corpus scoreboard: ssim 0.7627→0.7662, ssim_inked
0.1359→0.1446, line IoU 0.3281→0.3386.

**Holdout** (private report, local-only, Batang, PDF median space 0.4933):
breaks **37/260 → 71/260**, conditional exact 63→108, line count
400→407/415, fill 0.938→0.980. Every channel improved.

Per-class advance error vs reference PDFs (weighted): space
−0.1373 → +0.0028; other classes unchanged (|err| ≤ 0.006).

### #192 — flow pass / reflow

Page-assignment agreement on unedited text (`--flow-agreement`): **468/590
(0.793)**, median |dy| 0 on all ten forms — admrul 15/15, moel-2013
154/154, moel-2025 187/187, nrf 51/53, saeopja 5/6, kstartup 46/165.

**kstartup**, the real-document target handed over from #191's Codex-preview
finding: auto (cache) 20 pages / `page_count_exact` false / line IoU 0.2542
/ pair 0.7988 → **computed 22 pages / true / 0.5921 / 0.8949** (reference
22). Only `ink_delta_abs_max` (0.0621 vs 0.05 floor) still fails.

Edited document (moel-2025, one paragraph lengthened): 7→9 pages, nothing
above the edit moves, 0 overflows.

**Holdout** (aggregate only): 225/225 exact adjacent-pair advances, 18/18
pages, but 54/243 blocks land one page late (four corpus documents keep a
line past the usable box, max fill 1.068; the strict fit test doesn't) —
recorded as limit 19, no tolerance added.

### #194 — headers, footers, footnotes, endnotes

Corpus coverage: exactly one form carries `hp:header` (an empty
`hp:subList`); no corpus form carries a footer, footnote or endnote; the
private holdout has none either. Result: **all 10 forms byte-identical**
(51 page PNGs sha256-equal before/after; every scoreboard channel unchanged
to every decimal). Geometry proven only by synthetic fixtures — no
real-document (corpus or holdout) evidence exists for this feature.

### linefit branch (unopened, 2 commits) — row-fit predicate

Corpus (51 cached pages, 10 forms): old strict test (`vertpos + vertsize ≤
usable`) satisfied by 47/51; new test (`vertpos + baseline ≤ usable`)
satisfied by **50/51**, zero regression on the 47 that already fit
(auto-mode corpus render stays byte-identical, sha256-verified over all 51
PNGs). The one unresolved page is `nrf`'s empty trailing paragraph, whose
`vertpos` alone is already past `usable_height`.

**Holdout:** page count stays 18/18 exact; late-block count **54/243 →
7/243**; page-assignment agreement **189/243 → 231/243**. The arithmetic:
of the 54 previously-late blocks, 47 now agree and 7 remain late; 5 blocks
that used to agree now land one page early instead (189 − 5 + 47 = 231) —
the one cost of the more permissive rule, declared not netted away.

## 3. Regressions (with the PR's or commit's own explanation)

| PR/commit | metric | moved | explanation given |
|---|---|---|---|
| #190 | corpus paragraph line-count agreement | 2103 → 2083 | a wider space pushes some one-line paragraphs to two; stated as a cost, not netted against the break-position gains |
| #192 | kstartup `ink_delta_abs_max` | still 0.0621 vs 0.05 floor | the only channel the flow-pass fix does not resolve; not separately explained beyond "still fails" |
| #192 | (declared, not measured as a regression) | `keepLines`/`keepWithNext`/`pageBreakBefore` are 0/774 corpus `breakSetting` | implemented but unexercised by any corpus document |
| linefit (`34e5c84`) | holdout: 5 blocks move from agreeing to one page early | 189/243 agree → 231/243, net +42 | "the one cost of the more permissive rule" — traded for 47 blocks fixed from late; net positive, stated not hidden |

#194 has no regressions to report: the corpus render is byte-identical
before/after (no form exercises the new draw paths).

## 4. Unsupported / declared elements still open

Carried from checkpoint-01's list, with items this checkpoint's PRs closed
or changed removed/updated:

- **Closed since checkpoint-01:** "block layout / page reflow (E2.5): not
  implemented" — now implemented by #192, measured 468/590 corpus agreement,
  still limited (see below). "Headers, footers, footnotes, endnotes: not
  drawn at all" — now drawn by #194, but **unverified against any real
  Hancom reference** (zero corpus or holdout documents carry these
  elements).
- **Still open, unchanged:** Hancom HFT fonts substituted (declared per
  character count); paraPr items not honored (hyphenation, widow/orphan
  partially now honored by #192's flow pass — `keepLines`/`widowOrphan`/
  `keepWithNext` are implemented there, unexercised by corpus — the rest
  still open: `pageBreakBefore` implemented/unexercised too,
  `fontLineHeight`, `snapToGrid`, `BETWEEN_LINES` spacing, non-LEFT tab
  stops, pre-existing `<hp:tab/>`, hanging indent); `hp:ole`/`hp:chart`/
  `hp:container`/shapes/undecodable EMF-WMF still grey placeholders; only
  `DOUBLE_SLIM` draws two border strokes; multi-section documents (only
  section0 laid out); multi-column (`hp:colPr`) ignored by both the
  renderer and #192's flow pass (declared, not attempted); text wrap around
  anchored objects not implemented; `hp:parameters` family unrendered;
  equations' declared-unsupported constructs unchanged (`size`, `color`,
  `bigg`/`small`, `binom`, `choose`, `buildrel`, `rel`, `dyad`, `col`
  family, unbalanced fences; italic variable shaping still the largest
  named visual gap); row heights approximate (8/81 tables miss height >2%).
- **New, declared by #192:** `repeatHeader` skipped; blocks taller than the
  page handled by the existing overflow guard, not split; sections past
  section0 out of scope for the flow pass too.
- **New, declared by #194:** notes geometry checked only against synthetic
  fixtures — "the notes say plainly that none of it is checked against a
  Hancom reference render." Multi-column and sections past section0 remain
  declared there as well.
- **New, from the linefit branch:** the row-fit predicate leaves one corpus
  page (`nrf`'s empty trailing paragraph) unresolved by design — "no
  box-portion rule rescues that" — and costs 5 holdout blocks a
  one-page-early miss (see §3).
- **Line breaker:** now 58/216 (0.269) exact break-position agreement,
  up from 43/216 in checkpoint-01 — still the largest open numeric gap on
  the renderer line.
- **Pagination:** `kstartup-jiwon-sincheongseo-saeopgyehoekseo` no longer
  fails `page_count_exact` in computed mode (fixed by #192); its
  `ink_delta_abs_max` (0.0621 vs 0.05) is now the standing failure on that
  document.

## 5. Tests actually run per PR (from PR bodies)

| PR | orchestrator re-run | full suite | notes |
|---|---|---|---|
| #187 | 116 passed (own_render suite) | 4036 passed / 146 skipped / 0 failed (22m39s) | carried from checkpoint-01 |
| #190 | 120 passed (own_render suite) | 2987 passed / 1199 skipped / 0 failed (15m25s, core-only checkout) | engine 1087 |
| #192 | 131 passed (own_render suite) | 4051 passed / 146 skipped / 0 failed (20m28s, main-based) | engine 2529 tests; +15 over #190's own_render count |
| #194 | (own_render count not separately stated) | 3024 passed / 1199 skipped / 0 failed (13m35s, core-only checkout) | engine/tests 1124 / 135 skipped / 0 failed |
| linefit branch | **no PR body exists** — only the new pinned test itself (`test_the_row_fit_predicate_matches_the_measured_line_fit_research`, added in commit `7b1d6c8`) asserting the 51/47/50 corpus numbers in-repo | **not independently confirmed** | this is a gap: no orchestrator full-suite evidence has been published for this work, because no PR has been opened |

`py_compile_sweep` and the privacy gate (`HARD=0`) are reported passing on
#187/#190/#192/#194; neither is confirmed for the linefit branch absent a
PR body.

## 6. Integration conflicts expected when lines converge

Unchanged in kind from checkpoint-01, re-verified against the deeper tip:

- **Renderer vs writer:** still no direct file overlap. The renderer line
  (through the linefit branch) touches `engine/scripts/own_render.py`,
  `engine/references/own-render-notes.md`, `engine/tests/test_own_render.py`
  (plus `engine/scripts/hwpeqn_parse.py` from #187). Writer PRs (#177,
  #180) are unmoved since checkpoint-01 and still touch
  `engine/scripts/hwpx_write.py`, `xml_backend.py`, `preedit.py`,
  `tidy_hwpx.py`, `engine/references/owpml-writer-notes.md`,
  `engine/tests/test_hwpx_*.py`. Both lines share the `engine/` tree and
  corpus fixtures; a full-suite run after merge remains the actual check.
- **Desktop's mid-merge state — preserved, unchanged since checkpoint-01:**
  Fork A (#159 `desktop-foundation` → #161 `desktop-design`) was never
  closed or rebased onto Fork B; Fork B's current tip (#184
  `desktop-e1-undo`) still bases on `runtime-v0-phase3-gaps`, five PRs
  behind the runtime line's authoritative tip (#185), with sibling #181
  (`agenthost-e4-streaming`) a second unmerged head off the same #174
  ancestor. None of this checkpoint's four items touches desktop or
  runtime files, so this state is exactly as checkpoint-01 recorded it —
  still an open reconciliation, not a mechanical rebase, and still worth
  flagging precisely because nothing in this window moved it forward.
- **Renderer/writer vs runtime/desktop:** no shared files observed; these
  lines only meet at `main`.
- **The linefit branch itself is an extra unmerged head with no PR and no
  reviewer visibility** — when a PR is opened it stacks after #194, but
  until then it exists only as a local/pushed branch tip.

## 7. Next measurable research question

Two residuals stand after the linefit fix, both with numbers in hand
rather than needing a new instrument:

1. **The holdout's 12/243 remaining page-assignment misses** (7 still late,
   5 newly early — see §2/§3): is this the same "second, smaller term" #190
   flagged as unconfirmed (moel-2013/2025 filling only 0.89/0.91, guessed
   as their 한양 faces resolving worst), or a structurally different effect
   tied to the baseline-vs-vertsize row-fit boundary itself? The corpus has
   no clean instance of this shape to test against (#193 said so directly);
   only the private holdout shows it, so the next step is a targeted
   synthetic fixture reproducing the boundary case, not another corpus
   sweep.
2. **kstartup's `ink_delta_abs_max` (0.0621 vs the 0.05 floor)** is the one
   channel #192's flow-pass fix left failing on the document #191's Codex
   preview handed over as the primary real target — pagination and line
   IoU/pair rate are now correct there (22/22, 0.5921, 0.8949), so this is
   sub-pixel registration, not placement, and is the most concrete
   remaining number on that document.

Line-breaker exact-position agreement (58/216) also remains far from
resolved, but #190 already named its own next lever (per-face metrics
where substitution, not the advance rule, is the gap) — that lever hasn't
been pulled yet and stays open, not newly surfaced by this checkpoint.

## 8. Certification status

Every own-render result in this checkpoint — the space-advance numbers, the
flow-pass agreement, the kstartup pagination fix, the notes/headers
geometry, and the linefit corpus/holdout numbers — remains
**own-uncertified**. `grade` is stated as `own-uncertified` explicitly in
#187, #190, #192 and #194's own bodies; `pipeline/scripts/render_cert.py`
still cannot certify this renderer absent a PDF text layer. None of these
four PRs, nor the unopened linefit branch, claims certification, and none
is merged to `main`.

The Codex desktop preview (#191) is this checkpoint's clearest illustration
of "regression evidence, not a certified artifact": it is not wired to any
own renderer (its page shots are Hancom-staged passthroughs or honest
refusals), yet reading it surfaced kstartup's pagination-collapse mechanism
(20 pages read vs 22 real, one candidate page overlaying ~3) — a real
finding that #192 then fixed and measured (22/22 computed). The preview
changed no number in this checkpoint directly; it changed which document
#192 targeted. That is the standing distinction this checkpoint keeps: a
Codex-run preview is a signal that something moved, never a merged or
certified result.
