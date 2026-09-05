# Checkpoint 13 — a run that draws nothing still declares the line, and a hypothesis that didn't survive its own test

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-12`
(this branch, `docs/checkpoint-13`, is cut from `docs/checkpoint-12` and
stays unmerged). Covers #247 (`claude/engine-e2-computed-gap`: the biggest
class of computed-layout loss traced to a `hp:run` whose `hp:t` is empty
but whose `hh:charPr@height` still declares the line's height — a run that
draws nothing still sets line-height; fixed, corpus computed line IoU
0.5887→0.6339 at 144 dpi, cache byte-identical, holdout byte-identical and
unmoved), #249 (`claude/engine-e2-divergence-tool`: `layout_divergence.py`
turns #247's by-hand A/B/C classification into a repo tool so the holdout
can be classified locally and only its aggregate published; run against
the corpus it does not reproduce #247's hand table and the PR says why —
this base already carries the fix, the default tolerance also counts a
±2 HWPUNIT spacing residual, and #247's class-A population matched neither
its stated rule nor a script that was ever in the repo), and #250
(`claude/engine-e2-drift-attribution`: splits class B into `B_inherited`
(dy equals the upstream added-line count × pitch) and `B_own` — corpus
538 B total, 5 inherited / 533 own; the PR's own hypothesis from #249's
holdout comment, that most class B is downstream of class-A re-breaks, is
tested and **refuted**, then refuted again on the holdout "harder": 267 B,
0 inherited, 267 own, upstream line delta 0 for 224 of them; class-A font
substitution share 0.294 on the corpus, **0.0** on the holdout). Desktop
(#248) re-merges onto the renderer tip #245: one textual conflict kept
both sides, one semantic clash (the caret-edge test bounded by `x1`, now
rebound to `x1_advance`) fixed by measuring instead of assuming; smoke
551/0; `layout_policy` is not surfaced anywhere in the desktop UI yet —
stated as owed. Writer line (#224 → #235 → #238 → #239) and runtime line
(#204) did not move this window.

## What changed since checkpoint-12

| metric | checkpoint-12 | checkpoint-13 | moved in |
|---|---|---|---|
| renderer-line tip | #245 (converged tip, `f9a7474`) | **#250** (`219cdaa`) — a linear three-PR chain off #245: #247 (empty-run height fix), #249 (classification tool), #250 (attribution + refutation) | #247, #249, #250 |
| #245's own full gate | reported running at write time, not yet landed | **landed, confirmed by PR comment**: `tests` 482/3/0 + `pipeline/tests` 1437/8/0, total 1919/0 failed — "same count as #243's green gate"; the #240 pin failure #244 inherited is gone on this tip | #245 (comment posted after checkpoint-12) |
| computed-layout corpus line IoU (144 dpi, mean) | 0.6319 → 0.5768 at 96 dpi (#244); the gap's cause unnamed | **one mechanism found and fixed**: an `hp:run` with empty `hp:t` still carries a real `hh:charPr@height` at 200% spacing (admrul paragraph 1); reading it moves computed IoU 0.5887→**0.6339** at 144 dpi (cache stays byte-identical at 0.6458); admrul returns to `pass`; break channel unmoved (80/216) | #247 |
| holdout computed-vs-cache gap | 0.5680 → 0.2311, opened as this window's headline question | **untouched by the fix**: 96 dpi, both policies byte-identical before/after (ssim 0.6108, IoU 0.2294) — "the empty-run height mechanism does not occur in that document"; stays the open question | #247 |
| classifying where computed loses to the cache | done once, by hand, in a PR body (#244/#247) | **shipped as a repo tool**: `engine/scripts/layout_divergence.py`, per-paragraph A (break moved) / B (same breaks, y differs) / C (page changed) classes, `--iou`, `--corpus`, run locally against the private holdout | #249 |
| #247's hand-classified table | stood as the only record | **not reproduced by the tool, and the PR says why**: this base already has the empty-run fix (admrul B→0, nrf B→29); the exact default tolerance also counts a ±2 HWPUNIT spacing residual (#247's numbers appear only at `--y-tol 0.5`); #247's class-A population fits neither its stated rule nor any script in the repo — `--iou` does reproduce #247's IoU deltas exactly, confirming the render path is unchanged | #249 |
| holdout classification | not run | **run locally, aggregate published**: pages 18/18 both policies; IoU cache 0.5666 → computed 0.2294; paragraphs agree 10 / A 64 / B 267 / C 60; class-B dy dominated by exact multiples of 24 px (one body line at 96 dpi), all positive | #249 |
| "is class B downstream of class-A re-breaks?" | not asked | **asked as a hypothesis (#249's holdout comment), tested and refuted (#250)**: corpus 538 B total, only 5 `B_inherited` vs 533 `B_own` (215 with a re-break above, 318 without); holdout refutes it "harder" — 267 B, **0 inherited**, upstream line delta 0 for 224 of 267 | #250 |
| class-A cause (font substitution) | named as a partial cause, not measured | **measured, and it inverts between corpus and holdout**: corpus 40/136 class-A paragraphs carry a substituted run (0.294 share, 655 bundled + 111 system chars of 5322); holdout 3125/3125 class-A characters are on installed faces, **0 substituted** — "the bundled-fallback-advance explanation does not apply to this document at all" | #250 |
| desktop line | #234 (on #231; four renderer slices behind #245) | **re-merged onto #245** (#248): one textual conflict (line-box construction) kept both sides; one semantic clash (caret-edge test bound to `x1`, now geometry-only under #242) fixed by rebinding to `x1_advance`; smoke 551/0; now **three** slices behind the new renderer tip (#247, #249, #250 landed since) | #248 |
| `layout_policy` in the desktop UI | not addressed | **still not addressed** — #248 states plainly it is not surfaced anywhere in the desktop UI, "the badge still shows only the tier"; owed as its own slice | #248 (named, not shipped) |
| writer line | #224 → #235 → #238 → #239, tip unmoved | **unmoved this round** — no new writer-line PR | — |
| runtime line | unmoved since checkpoint-06 (#204) | **still unmoved** (#204) | — |

## 1. Branch DAG

Renderer line, now a straight three-PR chain off checkpoint-12's converged
tip — no siblings, no merge this window:

| PR | branch | base | slice |
|---|---|---|---|
| #245 | `claude/engine-e2-converge-03` | `claude/engine-e2-cache-policy` | converged tip at checkpoint-12 (`f9a7474`); its own full gate, reported running at checkpoint-12, has since landed 1919/0 |
| #247 | `claude/engine-e2-computed-gap` | `claude/engine-e2-converge-03` (#245) | the empty-run-height mechanism: corpus computed line IoU 0.5887→0.6339 at 144 dpi; cache byte-identical; holdout byte-identical and unmoved |
| #249 | `claude/engine-e2-divergence-tool` | `claude/engine-e2-computed-gap` (#247) | `layout_divergence.py`, an A/B/C classifier; does not reproduce #247's hand table and says why; holdout classified locally, aggregate published |
| **#250** | `claude/engine-e2-drift-attribution` | `claude/engine-e2-divergence-tool` (#249) | **attributes class B (`B_inherited`/`B_own`), refutes #249's own hypothesis on both corpus and holdout, names the fonts on class A. This is the renderer tip (`219cdaa`).** |

Desktop line: one PR this window.

| PR | branch | base | slice |
|---|---|---|---|
| #248 | `claude/desktop-on-renderer-245` | `claude/desktop-renderer-230` (#234) | re-merges the desktop onto renderer tip #245 (not #250 — #247/#249/#250 landed after or alongside this slice); one textual conflict kept both sides; caret-edge test rebound to `x1_advance`; `layout_policy` still not surfaced in the UI |

Writer line, unchanged from checkpoint-12 — still #224 → #235 → #238 →
#239, no new PR this window.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-12` (each
off its own window's renderer tip).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #247 — a run that draws nothing still declares the line

**Diagnosis (144 dpi, both policies rendered, per-line classes A/B/C):**
every form that loses IoU under computed layout is dominated by class B,
each drifting by one constant offset — admrul −20.00 px (14 B lines, ΔIoU
−0.400), nrf −8.00 / +102.40 px (42 B), moel-2025 +29.76 px (145 B),
saeopja (22 B, −0.091); kstartup's +0.370 is class C (239 lines change
page — computed paginates right, 21 → 22 pages).

**Mechanism.** admrul paragraph 1's inline table has a cached `spacing` of
2400 HWPUNIT against a measured 1400. The paragraph is a 14 pt run holding
the table plus a **second run at 24 pt whose `hp:t` is empty**, at 200%
spacing — `hh:charPr@height` belongs to the run, not to its characters, so
a run that draws nothing still sets the line's height. `Paragraph.
empty_runs` + `_line_metrics` now read them; cached-line `vertsize` moves
from 2365/2370 to **2370/2370** exact.

**Scoreboard, 144 dpi, corpus means.** Computed: line IoU 0.5887→**0.6339**,
ssim 0.8167→0.8243, ssim_inked 0.2490→0.2774; admrul returns to `pass`.
Cache: **byte-identical** (0.6458 / 0.8309 / 0.2762, all ten per-form
JSONs unchanged); render-check-01 byte-identical at 96 and 144 dpi (9/9
pages). Break channel unmoved (80/216 matched).

**Holdout (private, aggregate only, 96 dpi, `--layout-policy computed`,
#245 tip vs this tip): byte-identical** — ssim 0.6108, ssim_inked 0.0982,
line IoU 0.2294, pair rate 0.7793, both before and after. The empty-run
mechanism does not occur in that document; the holdout's computed-vs-cache
gap stays untouched and open.

**Evidence:** `py_compile_sweep` 105/0; engine/tests 1253 passed / 135
skipped; cleanroom + floors + pins 101 passed; archive privacy HARD=0.
**Full gate on this tip (`c16a93a`), from a PR comment:** `tests` 478
passed / 7 skipped / 0 failed (5m02s); `pipeline/tests` 1435 passed / 10
skipped / 0 failed (6m56s). 0 failed overall.

**Not proven:** one form (admrul) carried the finding; the pitch-only
reading was not ruled out by a reference render; the ±2 HWPUNIT `PERCENT`
spacing residual (883 lines) is unexplained and accumulates; nrf's
remaining +102.40 px block is undiagnosed; moel-2025's residual sits
downstream of a class-A break at its own paragraph 6; class A is partly
font substitution.

### #248 — desktop re-merged onto the renderer tip, one clash fixed by measuring

**One textual conflict, resolved keeping both sides:** the line-box
construction in `own_render.py` — the desktop's `address` / `char_x` /
`text` / `size_pt` annotation and the renderer's three right-edge
candidates selected by `LINE_BOX_END`. Cell boxes (desktop-only) kept.

**One semantic clash, named and fixed:** the desktop's caret-edge test
bounded the last `char_x` edge by `x1`. Since #242, `x1` is the geometry
box (stops at the last ink-drawing piece) while the last caret edge is a
full advance, so a trailing space pushed it past `x1` by one space cell.
Caret edges now bound against `x1_advance` — the caret box #242
introduced for exactly this — and the test also asserts `x1 <=
x1_advance`. No renderer or desktop rendering code changed.

**Evidence:** `py_compile_sweep` 131/0; engine/tests 1256 passed + the
fixed test; `tests` 1085 passed / 7 skipped; `pipeline/tests` 1437 passed
/ 10 skipped; desktop smoke `desktop/scripts/smoke.ps1` **551 passed / 0
failed** on the pre-built exe (a first run was disturbed by the agent's
own cleanup and rerun clean); archive privacy HARD=0; disk never under
2 GB. No PR comments posted.

**Stated, not done:** `layout_policy` / `layout_policy_reason` from the
new sidecar are not surfaced anywhere in the desktop UI yet — the badge
still shows only the tier. Owed as its own slice.

### #249 — the by-hand classification, now a repo tool

`engine/scripts/layout_divergence.py FORM.hwpx --out DIR [--dpi 144]
[--y-tol PX] [--no-text] [--iou --reference REF.pdf] [--corpus]` renders
both layout policies through `own_render`'s API, pairs lines per
paragraph in order, and classes each paragraph: **A** break moved, **B**
same breaks but a line's y differs beyond `--y-tol`, **C** page changed,
else agree. Output includes per-class counts, each paragraph's first
divergent line, a histogram of rounded class-B dy, and (with `--iou`) the
scoreboard IoU under both policies.

**Corpus (paragraphs agree/A/B/C, 144 dpi, default tolerance):** admrul
17/1/1/0, gianmun-1ho 27/1/0/0, gianmun-2ho 16/0/0/0, jeongbo 50/5/0/0,
jumin 110/17/2/0, kstartup 43/31/98/233, moel-2013 127/20/112/0,
moel-2025 36/43/225/0, nrf 55/2/29/0, saeopja 673/16/71/0.

**It does not reproduce #247's table, and says why rather than tuning to
match:** (1) this base already carries the empty-run fix, so admrul B is
0 at `--y-tol 0.5` and nrf B is 29 — the post-fix values; (2) the exact
default tolerance also counts the ±2 HWPUNIT spacing residual — at 0.5 px
moel-2013 B = 23 and kstartup B = 28, #247's own numbers; (3) #247's
class-A population matches neither its stated line-count rule nor text
inequality, and its script was never in the repo. `--iou` reproduces
#247's IoU deltas exactly (admrul −0.00567, nrf −0.11984, saeopja
−0.09167, kstartup +0.37000), confirming the render path is unchanged.

**Holdout classified locally (private, aggregate only), 96 dpi,
`--no-text --iou`.** Pages 18/18 both policies; IoU cache 0.5666 →
computed 0.2294 (delta −0.3373, the same gap #244 measured). Paragraphs:
agree 10 / **A 64 / B 267 / C 60** (21 both A and B). Lines: agree 13 / A
257 / B 335 / C 77. Identical at `--y-tol 0.5`, so none of it is the ±2
HWPUNIT residual.

**Class-B dy histogram, top entries:** +48.00 px × 53, +72.00 × 48,
+264.00 × 30, +24.00 × 18, +120.00 × 18, then four smaller non-integer
buckets. The five largest are exact multiples of 24 px = 18 pt at 96 dpi
— one body line of that document — and all positive (computed sits
lower): the signature of extra lines inserted upstream, not a block
measured short as on admrul.

**Hypothesis stated, not proven:** most of the holdout's class B is
downstream of its 64 class-A paragraphs — computed breaks a long
paragraph one line longer than the cache, and every following paragraph
on the page inherits the 18 pt; the first divergence in the document is
already class A at paragraph 1, line 0. If so, the real gap is the break
rule / advance width under bundled fallback fonts — the nrf mechanism
#242 costed and did not ship — and B is a symptom. Flagged for the next
slice to prove or refute with cumulative line-count drift per page.
Nothing in this PR changes a render.

**Evidence:** `test_layout_divergence` 23 passed; engine/tests 1276
passed / 135 skipped; pins + package-module 85 passed; cp949 CLI smoke
auto-discovers the script (60 passed); `py_compile_sweep` clean; archive
privacy HARD=0. **Full gate on this tip (`8459102`), from a PR comment:**
`tests` 479 passed / 7 skipped / 0 failed (5m09s); `pipeline/tests` 1435
passed / 10 skipped / 0 failed (6m42s). 0 failed overall.

### #250 — the hypothesis tested, and refuted on both samples

**Measurement only — `own_render.py` untouched.** Tests the hypothesis
#249's holdout comment made.

**What the tool now reports.** Per page, in reading order: cumulative
line-count delta (computed − cache) and cumulative dy; each class-B
paragraph split into `B_inherited` (its dy equals the upstream added-line
count × line pitch, within `--attribution-tol`, default 1.0 px) or
`B_own`, the latter tagged with whether a re-break exists above it at
all. Each class-A paragraph names the line that broke differently, its
cache-vs-computed width in px, and the declared → resolved face/source
(installed / bundled / system) of the runs on that line.

**Corpus (paragraphs, 144 dpi) — `B / inherited / own (re-break above |
none)`:** admrul 1/0/(0|1), jumin 2/1/(0|1), kstartup 98/0/(0|98),
moel-2013 112/4/(21|87), moel-2025 225/0/(**161**|64), nrf 29/0/(0|29),
saeopja 71/0/(33|38); gianmun-1ho/2ho and jeongbo have no B. **Total 538
B: 5 inherited, 533 own — 215 with a re-break above, 318 without.**

**Reading:** 318 B paragraphs have no re-break above them at all (nrf's
+102.40 px block, kstartup's spacing residual) — not inherited drift. The
215 that do have one miss the pitch prediction by a *constant per added
line* (moel-2025 clusters at −10.01 / −6.67 / −20.02 px, saeopja at
−20.22) — a rule is missing, not noise.

**Class A and fonts (136 paragraphs):** 96 all-installed, 40 with a
substituted run (37 bundled, 9 system) → **0.294** substituted; by
characters 4556 installed / 655 bundled / 111 system. Fallback advance
contributes to class A but is not most of it.

**Holdout (private, aggregate only), 96 dpi, `--no-text`. The #249
hypothesis is refuted there too, harder than on the corpus:**

- Class B: 267 paragraphs, **B_inherited 0 / B_own 267**; upstream line
  delta is **0 for 224** of them (−2: 3, −1: 11, +1: 29). Dominant
  residuals remain +48.00 px × 48, +72.00 × 42, +24.00 × 14, +264.00 ×
  23, +120.00 × 10 — whole multiples of the 24 px body pitch — with **no
  re-break above them**. Whatever adds those lines is not a line break.
- Class A: 64 paragraphs; **56 keep the same line count** (−1: 5, +1: 3).
  Breaks move by characters, not lines: computed broke earlier 35 /
  later 29; width delta median −6.67 px, mean −1.30, range −47.52 …
  +93.33.
- Fonts on class-A lines: **3125 / 3125 characters on installed faces, 0
  substituted.** The bundled-fallback-advance explanation does not apply
  to this document at all.

**What this leaves.** Every first class-B line sits a whole number of
body lines below the cache while the paragraphs above it agree in line
count — the extra height is added *between* paragraphs or at a
paragraph's bottom (last-line spacing, paragraph margin, or an anchored
object's reserve), not inside a re-broken paragraph. The tool does not
yet compare the bottom of the paragraph preceding each first-B paragraph;
that comparison (cache vs computed last-line `vertsize + spacing`,
inter-paragraph gap, anchored extent) is named as the next slice. The
24 px residual pattern also appears on moel-2025 in the corpus (−20.02 px
clusters) — the same measurement there is public and checkable.

**Evidence:** `py_compile_sweep` 106/0; engine/tests 1303 passed / 135
skipped; pins + package-module 85 passed; archive privacy HARD=0. **Gate
on this tip (`219cdaa`), reported in the same comment as the holdout
aggregate:** `tests` 479 passed / 7 skipped / 0 failed (7m30s);
`pipeline/tests` 1435 passed / 10 skipped / 0 failed (8m53s). 0 failed
overall.

**Not proven:** the constant residual is shown, not explained (needs the
added line's real `vertsize + spacing`, tagged per drawn line); "with an
upstream re-break" is correlation, not mechanism; the font share is this
machine's font stack.

## 3. Regressions (with the PR's or commit's own explanation)

**None newly introduced this window, by the PRs' own accounting.** #247's
fix moves computed IoU upward on every affected form and leaves the cache
path byte-identical; the only numbers it does not improve (nrf's
remaining +102.40 px block, moel-2025's residual) are named as pre-
existing and undiagnosed, not as something #247 broke. #248 is a merge
plus one test rebind — the caret-edge test now checks a real invariant
(`x1 <= x1_advance`) instead of a false one, and no render output changed
(desktop smoke 551/0, unchanged framing). #249 changes no render at all
("Nothing in this PR changes a render") and its own comment confirms
`--iou` reproduces #247's deltas exactly. #250 is explicitly "measurement
only — `own_render.py` untouched." The one hypothesis this window
produced (#249's "B is downstream of A") was tested and refuted by the
same team that proposed it, on both the corpus and the holdout, and is
carried forward as a refuted hypothesis, not as a regression.

## 4. Unsupported / declared elements still open

Carried from checkpoint-12, with this window's closures and new items:

- **Closed since checkpoint-12:** #245's own full gate, reported running
  at checkpoint-12 write time — a PR comment (`f9a7474`, posted after
  checkpoint-12) confirms `tests` 482/3/0 + `pipeline/tests` 1437/8/0,
  total 1919/0, matching #243's earlier green count; the admrul/nrf/
  moel-2025/saeopja class of computed-layout loss now has a named,
  fixed mechanism (#247's empty-run height read) rather than being an
  unexplained aggregate gap; the by-hand A/B/C classification is now a
  reusable, tested tool (#249) instead of a one-off PR-body table.
- **New, opened and then refuted within this same window:** #249's own
  hypothesis that class B is mostly downstream of class-A re-breaks —
  #250 tests it directly and reports it false on the corpus (533 of 538
  B paragraphs are `B_own`, not inherited) and false again, harder, on
  the holdout (all 267 B paragraphs are `B_own`, upstream line delta 0
  for 224 of them). Carried forward as a refuted hypothesis with its
  replacement question named: whether the added height sits at a
  paragraph's own bottom (last-line spacing, margin, anchored extent),
  not proven either way yet.
- **Unchanged from checkpoint-12, still fully open:** the holdout's
  computed-vs-cache line-IoU gap (0.5666→0.2294 as measured this window,
  essentially unchanged from checkpoint-12's 0.5680→0.2311) — #247's fix
  does not touch it, and the mechanism search continues; the full-width-
  advance line-box fix #242 costed and refused (nrf IoU +0.030, corpus
  IoU +0.003, but lineseg breaks 80→66/216) — no mechanism yet proposed
  to get the gain without the loss; the acceptance harness's lexical-
  reader fix for header/footer text (#235's queued item); Codex-app-
  closed sessions moved; Cursor login; `hp:ole`/`hp:chart`/
  `hp:container`/shapes/undecodable EMF-WMF placeholders; `DOUBLE_SLIM`
  border limitation; `hp:parameters` family; `hp:autoNum` inside a footer
  draws nothing (`F51`); `hh:tabPr` stops inside the MCE switch never
  read; the tier-3 raster's own `own-uncertified` status; Hancom's
  first-column endnote placement in a two-column section;
  `textpos_past_end` firing on three unedited corpus forms over an
  `hp:ctrl` given no character cell (#244, pre-existing, not fixed).
- **New this window, named and not yet done:** `layout_policy` /
  `layout_policy_reason` are computed and carried in the sidecar (#244)
  but not surfaced anywhere in the desktop UI (#248's own words: "the
  badge still shows only the tier") — owed as its own slice; the ±2
  HWPUNIT `PERCENT` spacing residual (883 lines, #247) is unexplained and
  accumulates; nrf's remaining +102.40 px block (#247, #249) and the
  constant per-added-line residual on the 215 attributed class-B
  paragraphs (#250: moel-2025 clusters at −10.01/−6.67/−20.02 px,
  saeopja at −20.22) are shown but not explained.

## 5. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #247 | engine/tests 1253/135 skipped; cleanroom+floors+pins 101 passed | **`tests` 478/7/0 + `pipeline/tests` 1435/10/0 — 0 failed overall** | `py_compile_sweep` 105/0; archive privacy HARD=0 |
| #248 | engine/tests 1256 passed + fixed test; `tests` 1085/7 skipped; `pipeline/tests` 1437/10 skipped | desktop smoke `smoke.ps1` **551 passed / 0 failed** on the pre-built exe | `py_compile_sweep` 131/0; archive privacy HARD=0; disk never under 2 GB; no full `pipeline/tests`+`tests` gate comment posted |
| #249 | `test_layout_divergence` 23; engine/tests 1276/135 skipped; pins+package-module 85; cp949 smoke 60 | **`tests` 479/7/0 + `pipeline/tests` 1435/10/0 — 0 failed overall** | `py_compile_sweep` clean; archive privacy HARD=0 |
| #250 | engine/tests 1303/135 skipped; pins+package-module 85 | **`tests` 479/7/0 + `pipeline/tests` 1435/10/0 — 0 failed overall**, reported in the same comment as the holdout aggregate (`219cdaa`) | `py_compile_sweep` 106/0; archive privacy HARD=0 |

Every renderer-line PR this window (#247, #249, #250) reports its own
landed, zero-failure full-gate comment — unlike checkpoint-12, where only
#243's fix PR had a confirmed full-gate pass and #245's converged tip was
left open. #248 (desktop) reports its own suites and a clean 551/0 smoke
but no `pipeline/tests`+`tests` comment; its dependency #245 now carries
its own confirmed 1919/0 gate (see §4).

## 6. Integration conflicts expected when lines converge

**Renderer line did not converge siblings this window — it extended
linearly.** #247, #249 and #250 each forked from the immediately
preceding PR (#245 → #247 → #249 → #250), so there was no merge to
perform and no textual or semantic conflict between them; each slice's
own gate reports 0 failed. This differs from checkpoint-11 and
checkpoint-12, both of which needed a dedicated convergence PR to
reconcile sibling claims.

**Desktop re-merged onto the renderer, with the same shape of conflict as
before.** #248 hit one textual conflict (both sides' line-box
annotations, resolved by keeping both) and one semantic clash — the
desktop's caret-edge test assumed `x1` bounded the last caret edge, which
#242's redefinition of `x1` (geometry, not advance) broke; fixed by
rebinding to `x1_advance` and asserting the ordering invariant rather
than re-deriving the old bound. This is the same pattern checkpoint-12
named for #245's trailing-space test: a sibling line's older test encoded
an assumption a newer measured definition invalidated, fixed by measuring
instead of pinning.

**Desktop merged onto #245, not onto the current tip #250 — the gap is
narrower than checkpoint-12 but did not close.** #234 → #248 catches the
desktop up through #232/#236/#240/#245; #247, #249 and #250 landed after
(or alongside) #248, so the desktop is now **three** renderer slices
behind instead of checkpoint-12's four. `layout_policy` / provenance is
in the sidecar #248 merges against but is not read by any desktop UI
code — named as owed, not attempted this window.

**Writer and renderer lines remain unconverged**, unchanged from
checkpoint-12 — no writer-line PR this window referenced the renderer
tip.

**Runtime line is untouched and unconverged with anything**, unmoved
since #204 (checkpoint-06).

## 7. Next measurable research question

**Naming the mechanism that adds a whole body line between paragraphs on
the holdout, now that "class B is downstream of class-A re-breaks" is
refuted.** #250 shows every first class-B paragraph on the holdout sits a
whole number of body-line pitches (24 px at 96 dpi) below the cache while
every paragraph above it still agrees in line count — so the added height
is not inside a re-broken paragraph, it is added between paragraphs or at
a paragraph's own bottom. #250 names the concrete next comparison and
does not run it: cache vs. computed **last-line `vertsize + spacing`**,
**inter-paragraph gap**, and **anchored-object reserve** for the
paragraph immediately preceding each first-B paragraph — on the holdout
locally, and on moel-2025 publicly, where the same 24-px-multiple
residual pattern (−20.02 px clusters) already appears in the visible
corpus and is checkable by anyone. Not yet measured in either direction.

## 8. Certification status

Every result in this checkpoint — #247 (empty-run height fix), #248
(desktop re-merge), #249 (classification tool), #250 (attribution +
refutation) — remains **own-uncertified**. #247 changes only
`own_render`'s line-metrics reading, not the renderer's certified
surface; #248 is a merge plus one test rebind; #249 and #250 add and
extend a measurement script that changes no render output. `render_cert.
py` still cannot certify this renderer absent a PDF text layer, unchanged
since checkpoint-01.

**What moved, restated plainly:** this window closed checkpoint-12's
single largest open item — the corpus-visible half of the computed-vs-
cache gap now has a named, fixed mechanism (a run that draws nothing
still declares the line's height) — while the holdout half of that same
gap stayed exactly where it was, byte-identical before and after the
fix. In its place, this window produced and then discharged its own
hypothesis inside the same three-PR chain: #249 proposed that class-B
drift is downstream of class-A re-breaks, and #250 measured it false on
both samples available, more decisively on the one that matters (the
holdout). The renderer line also changed shape: instead of parallel
siblings needing a convergence PR (checkpoint-11, checkpoint-12), this
window is a single measured chain, each link's gate landing green before
the next was cut.

**Owed, carried forward from checkpoint-12, plus this window's
additions:**

- Naming the mechanism behind the holdout's between-paragraph height
  addition — this window's own next question (last-line spacing /
  inter-paragraph gap / anchored extent), not yet measured.
- The holdout's computed-vs-cache line-IoU gap itself (0.5666→0.2294) —
  untouched by #247's fix, still the largest unexplained number in this
  line of work.
- The full-width-advance line-box fix #242 costed (nrf IoU +0.030,
  corpus IoU +0.003) and refused (lineseg breaks 80→66/216) — no
  mechanism yet proposed to get the gain without the loss.
- `layout_policy` / `layout_policy_reason` surfaced in the desktop UI
  (#248's own stated gap) — still not a branch or PR.
- Desktop line (#248) re-merged onto the renderer's current tip (#250) —
  last done at #245, now three slices stale, narrower than checkpoint-
  12's four but not zero.
- The ±2 HWPUNIT `PERCENT` spacing residual (883 lines, #247) and the
  constant per-added-line residual on attributed class-B paragraphs
  (#250) — both shown, neither explained.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved (carried, not addressed this window).
- Cursor login (carried, not addressed this window).
