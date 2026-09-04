# Checkpoint 12 — where a line box ends, whose save it was, and the gap that remains

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-11`
(this branch, `docs/checkpoint-12`, is cut from `docs/checkpoint-11` and
stays unmerged). Covers #242 (`claude/engine-e2-linebox-end`: two questions
from #236 answered by measurement — a line box ends at the *visible
advance*, adopted as `LINE_BOX_END = "visible_advance"`, and nrf's
regression is not a layout regression but a font-metric mismatch on
휴먼명조/Nanum Myeongjo; a full-width-advance fix was costed and
deliberately **not shipped** because it breaks lineseg agreement 80 → 66 of
216), #243 (`claude/engine-e2-floor-pin`: fixes the one failure #240's own
full gate found — an integer inventory pin the repo's meta-test forbids —
by selecting the floor check by id instead of by count; gates 1919/0 +
engine 1240/0 on this tip), #244 (`claude/engine-e2-cache-policy`: the
policy fix #239 owed — the lineseg cache is now trusted or discarded for
the **whole document** at once, decided by `version.xml@application`
provenance: `hancom_untouched` keeps the cache, anything else (Rigorloom-
written, unknown writer, a declared edit) goes fully computed; costed at
corpus ssim 0.8006→0.7833, line IoU 0.6319→0.5768, pages exact 9/10→10/10,
and on the private holdout IoU 0.5680→**0.2311**, aggregate only), and
#245 (`claude/engine-e2-converge-03`, the renderer-line tip: converges
#242+#243+#244 into one tip with no textual conflicts and one semantic
clash — #242's pinned trailing-space hang list assumed a single paragraph
went computed, but under #244's whole-document policy every paragraph's
trailing space now hangs, so the test was rewritten to require the two
measured values without pinning the count; tip measures ssim 0.8006, line
IoU 0.6301, render-check 6/37/6/2 at 9/9 pages). Desktop (#234, still on
#231) is now four renderer slices behind (#232, #236, #240, #245). Writer
line (#224 → #235 → #238 → #239) and runtime line (#204) did not move this
window.

## What changed since checkpoint-11

| metric | checkpoint-11 | checkpoint-12 | moved in |
|---|---|---|---|
| renderer-line tip | #240 (eval floor rewritten to ordering; #231's claim merged in) | **#245** — #242 (line-box-end), #243 (floor-pin fix), #244 (provenance cache policy) converged into one tip | #242, #243, #244, #245 |
| where a line box ends | not addressed (open question from #236) | **decided by measurement**: `LINE_BOX_END = "visible_advance"` — median \|dx\| ink 2.48 pt vs advance 0.37 pt on 817 confidently paired lines; a full-width-advance alternative was costed (nrf IoU +0.030, corpus IoU +0.003) but **not shipped** because it drops lineseg breaks 80 → 66/216 | #242 |
| nrf's #236 regression | named, unexplained beyond "old rounding served it better" | **explained**: not a layout regression — 휴먼명조 resolves to bundled Nanum Myeongjo, which Hancom advances at 1.0000 em against our measured 0.9502 (old raster path measured 0.9545, coincidentally closer) | #242 |
| #240's own inventory-pin failure | reported running, not yet landed | **found and fixed**: `test_no_inventory_pins` flagged #240's own floor test for selecting a check by count; #243 selects by id instead — 1919/0 (`pipeline/tests`+`tests`) + 1240/0 (`engine/tests`) on the fix tip | #243 |
| `own_render --line-layout auto` cache policy | named as unsound, queued, no branch | **shipped**: `resolve_layout_policy` decides cache-vs-computed once per document from `version.xml@application` provenance, not per paragraph; `--layout-policy cache\|computed` pins either for measurement | #244 |
| computed-layout cost vs. cache | not measured | **measured**: corpus ssim 0.8006→0.7833, line IoU 0.6319→0.5768, pages exact 9/10→**10/10** (kstartup 21→22); private holdout IoU 0.5680→**0.2311** (aggregate only) — computed paginates better, places lines worse | #244 |
| convergence semantic clash | none this window (#240 repaired a DAG gap, not a content conflict) | **one clash**: #242's pinned exact hang list `[7.02, 8.667]` only held while a single paragraph went computed; under #244 the whole document goes computed, so the test now checks the two measured values are present and every hang is a positive ink-less space, without pinning the count | #245 |
| render-check tip result | 6/37/6/2, 9 pages (#240, unchanged from #236) | **unchanged**: 6/37/6/2, 9/9 pages (#245) | #245 |
| #245's own full gate | — | **running at time of writing; result to be appended to #245** — not yet reported as passed | #245 |
| desktop line | #234 (on #231; three renderer slices behind #240) | **unmoved — now four slices behind** (#232, #236, #240, #245 have landed since #234's merge) | — |
| writer line | #224 → #235 → #238 → #239, tip unmoved | **unmoved this round** — no new writer-line PR | — |
| runtime line | unmoved since checkpoint-06 (#204) | **still unmoved** (#204) | — |

## 1. Branch DAG

Renderer line, now converged at a single tip five PRs off checkpoint-09's tip:

| PR | branch | base | slice |
|---|---|---|---|
| #240 | `claude/engine-e2-floor-ordering` | `claude/engine-e2-dpi-independence` | eval floor rewritten to ordering; #231's claim merged in (checkpoint-11 tip) |
| #242 | `claude/engine-e2-linebox-end` | `claude/engine-e2-dpi-independence` | line box ends at the visible advance; nrf's regression explained, a costed alternative not shipped |
| #243 | `claude/engine-e2-floor-pin` | `claude/engine-e2-floor-ordering` | fixes the inventory-pin failure #240's own gate found |
| #244 | `claude/engine-e2-cache-policy` | `claude/engine-e2-floor-ordering` | lineseg cache trusted or discarded whole-document, by save provenance |
| **#245** | `claude/engine-e2-converge-03` | `claude/engine-e2-cache-policy` | **converges #242 + #243 + #244 into one tip; one semantic clash (trailing-space hang count) fixed by measuring instead of pinning; render-check unchanged 6/37/6/2, 9/9 pages. This is the renderer tip (`f9a7474`).** |

#242 and #244 both branched from `claude/engine-e2-dpi-independence` /
`claude/engine-e2-floor-ordering` as siblings of #240 and each other — #245
is the one-hop merge each PR's own body flagged as needed.

Writer line, unchanged from checkpoint-11 — still #224 → #235 → #238 → #239,
no new PR this window.

Desktop line: no PR in this window. Still #234 (`claude/desktop-renderer-
230`, on renderer #231) — checkpoint-11 measured it three slices behind the
then-tip (#240); #245 has since landed on top of #232, #236 and #240, so
the desktop is now **four** renderer slices behind, the gap widening again.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-11` (each off
its own window's renderer tip).

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #242 — where a line box ends, and a fix that was costed and refused

**Where does a line box end?** The reference is an *advance* box —
PyMuPDF's line bbox unions per-character advance quads, so a 12.96 pt
Hangul character measures exactly 12.96 pt there (1.000 em, not its ~0.95 em
ink); over 21,995 full-width characters in the ten reference PDFs the
median is 1.0000 em, 92.1% within 0.005. On the 817 confidently paired
lines: **median |dx| ink 2.48 pt / advance 0.37 pt / visible-advance
0.36 pt**; p90 5.43 / 6.24 / 5.28. Adopted `LINE_BOX_END =
"visible_advance"` — named a soft call: the two advance readings differ on
only 34 lines, and Hancom itself splits them 19 dropped / 15 kept trailing
spaces. The sidecar now carries `x1_advance` (what the caret needs),
`x1_ink`, and `x1_visible_advance` explicitly.

**nrf's regression (#236) — not a layout regression.** nrf's lineseg
agreement is identical before and after #236; only the drawing moved.
Cause: 휴먼명조 (639 of 1,063 full-width chars) resolves to the bundled
Nanum Myeongjo, which Hancom advances at 1.0000 em while it is now measured
at 0.9502 (the old raster path measured 0.9545 — neither right; the old one
was accidentally closer).

**A fix costed, and refused.** The rule "a full-width cell advances by the
declared size" was implemented and measured: nrf IoU +0.030, corpus IoU
+0.003, **but** lineseg breaks fell 80 → 66/216, exposing a pre-existing
over-measure on moel/jumin. **Not shipped**; recorded with its cost as the
next question.

**Per-form IoU from the box change alone** (ssim, pages, pair rate, lineseg
byte-identical): nrf −0.012, gianmun-1ho −0.004, jeongbo −0.004, admrul
−0.003, gianmun-2ho −0.001, kstartup −0.001, saeopja −0.001, moel-2013
+0.002, moel-2025 +0.002, jumin +0.004; mean −0.002. Render-check 9/9
pages, 6/37/6/2 unmoved; holdout 18/18, IoU 0.5852 → 0.5838. Deterministic.

**Evidence (orchestrator re-ran the renderer suite: 230 passed):**
engine/tests 1243 / 135 skipped; `py_compile_sweep` 105/0; archive privacy
gate HARD=0.

**Not proven:** no mechanism predicts Hancom's 19/15 trailing-space split;
`x1_ink` excludes the antialias fringe; the confident subset drops 1,269 of
2,086 pairs. No comment posted on this PR as of this checkpoint.

### #243 — the inventory pin #240 introduced, fixed by selecting by id

**Closes the one failure #240's full gate showed.** The new floor unit test
selected its check by count (`assert len(checks) == 1`), which the repo's
meta-test forbids as an integer inventory pin (passes on `main`; introduced
by #240). Now selected by discovery — `checks_by_id["render_check_report"]`
— with no allowlist row. Floor logic unchanged.

**Evidence, from the PR body:** `test_no_inventory_pins` 16,
`test_eval_floors_against_corpus` 11, `test_cleanroom_evals` 74;
`py_compile_sweep` 105/0; archive privacy gate HARD=0.

**Evidence, from PR comments (the gate #240 left open, now closed):**
`python -m pytest pipeline/tests tests -q` on this tip (`aa568b3`): **1919
passed / 11 skipped / 0 failed** (12m39s) — the `test_no_inventory_pins`
failure #240 showed is gone; this run covers `pipeline/tests` + `tests`
only, not `engine/tests`. A second comment reports `engine/tests` on the
same tip: **1240 passed / 135 skipped / 0 failed** (2m20s). Together, every
suite #240's gate ran is green on this tip.

### #244 — the layout cache decided by who last wrote the package

**Provenance.** `version.xml@application` is the only writer signature an
HWPX carries. `hwpx_write.blank_package` already stamped `Rigorloom`;
`HwpxDocument.save` copied Hancom's value forward verbatim, so it now
stamps too (attribute values only). The stamp self-clears on a Hancom
resave, which a `content.hpf` marker would not.

**Policy.** `--line-layout auto` now resolves once per document:
`hancom_untouched` → `cache`; `rigorloom_written` / `unknown_writer` / a
caller-declared edit → `computed`, for lines *and* flow. The sidecar
declares `layout_policy`, `layout_policy_reason`, `layout_provenance`.
`--layout-policy cache|computed` pins either for measurement.
`stale_line_width` is scanned once and only diagnoses — except that, being
sound, a hit falsifies a `cache` claim and sends the whole document
computed. `cache_absent` / `textpos_past_end` stay per-paragraph: those are
caches this reader cannot *read*, not stale ones.

**What computed costs today (96 dpi, computed − cache, corpus means):**
ssim 0.8006→0.7833, ssim_inked 0.2779→0.2449, line IoU 0.6319→**0.5768**,
pair rate 0.8362→0.8478; page-count exact 9/10 → **10/10** (kstartup
21→22); lineseg breaks 77/216. Holdout (private, aggregate only): 18/18
pages both ways, IoU 0.5680→**0.2311**. The PR's own framing: computed
paginates better and places lines worse — acceptable only because it is
chosen exactly when the cache is invalid.

**Floor:** ten corpus forms + render-check-01 byte-identical to pre-slice
HEAD (untouched Hancom packages still take the cache). engine/tests 1247
passed; orchestrator re-ran the own_render/layout subset: 254 passed;
`py_compile_sweep` clean; archive privacy gate HARD=0.

**Pre-existing, not fixed:** `textpos_past_end` fires on three unedited
corpus forms over an `hp:ctrl` given no character cell.

**Evidence, from a PR comment (the gate #244 itself found, inherited from
#240):** Full gate on tip `5a9d976`, `python -m pytest pipeline/tests tests
-q`: 1912 passed / 17 skipped / **1 failed** (12m49s) — the same
`test_no_inventory_pins` failure #240 showed, inherited because this branch
was cut from #240 before #243 fixed it; the PR's own words: "Nothing in
this slice caused or touches it. #245 (this + #243 + #242) carries the fix;
its gate is reported there."

### #245 — one renderer tip, and the clash between two measured claims

**One renderer tip again.** #244 (provenance-decided layout cache) + #243
(floor check selected by id) + #242 (line box ends at the visible advance).
Two no-ff merges, no textual conflicts, plus one commit.

**The one semantic clash, named and fixed:** #242's trailing-space test
pinned the exact hang list `[7.02, 8.667]` on the edited fixture, valid
only while an edit sent a single paragraph computed. Under #244 the whole
document goes computed, so every paragraph's trailing space hangs — the
test now requires the two measured values to be present and every hang to
be a positive ink-less space cell, without pinning the count. Both
behaviours coexist: `resolve_layout_policy` / provenance AND
`LINE_BOX_END = "visible_advance"` with `x1_advance` / `x1_ink` /
`x1_visible_advance`.

**Measured on the tip (96 dpi, cache policy):** corpus ssim 0.8006
(= #244), line IoU 0.6301 vs #244's 0.6319 — the −0.0018 is #242's
documented box-end effect (−0.00177), not a regression; pages 9/10 exact
(kstartup 21/22, the known cache-wrong case that #244's computed mode
fixes); render-check-01 6/37/6/2, 9/9 pages. No private document opened.

**Evidence:** `py_compile_sweep` 105/0; engine/tests 1249 passed + the
fixed test; cleanroom/floors/pins 101 passed; archive privacy HARD=0.

**Full `pipeline/tests` gate on this tip: reported as running at write
time. As of this checkpoint no PR comment with that result has posted —
treated here as running, not as passed.**

## 3. Regressions (with the PR's or commit's own explanation)

**None newly introduced this window, by the PRs' own accounting.** #242's
measured mean −0.002 corpus IoU from the box-end change is stated as the
cost of a deliberate convention choice, not a regression, and its own
alternative fix (full-width advance) was explicitly refused because it
regresses lineseg breaks 80 → 66/216 — refused rather than shipped, so it
does not land as a regression either. #244's computed-layout numbers
(ssim −0.0173, line IoU −0.0551, holdout IoU −0.3369) are **not framed as
a regression** — they are the declared, accepted cost of choosing computed
layout precisely on documents where the cache is already known-invalid;
the PR's own words: "acceptable only because it is chosen exactly when the
cache is invalid." #245's −0.0018 line-IoU delta from #244's own number is
identified as #242's already-documented box-end effect layered on top, not
a new regression. #243 fixes a test-selection defect #240 introduced,
already logged in checkpoint-11 as open, not a new regression here. The
`nrf` regression #236 named at checkpoint-10 is superseded by #242's
explanation (a font-metric mismatch, not a layout defect) — carried
forward as explained, not as fixed, since the full-width-advance fix that
would address the underlying over-measure was costed and not shipped.

## 4. Unsupported / declared elements still open

Carried from checkpoint-11, with this window's closures and new items:

- **Closed since checkpoint-11:** the #240 inventory-pin gate failure
  (#243 fixed it, 1919/0 + 1240/0 confirmed by PR comment); the
  `own_render --line-layout auto` cache-policy question named at
  checkpoint-11 as "queued, not yet a branch" (#244 ships it); the
  trailing-space line-box question (advance vs. ink), #236's carried-open
  item — #242 answers it (`visible_advance`), with the fuller
  full-width-advance fix explicitly costed and refused rather than left
  unaddressed.
- **New, opened by #242 itself:** the full-width-advance alternative that
  would close nrf's remaining over-measure regresses lineseg breaks 80 →
  66/216 corpus-wide — costed, not shipped, no mechanism yet proposed to
  get the IoU gain without the break-agreement loss.
- **New, opened by #244 itself, restated as this window's headline
  question:** computed layout's line-placement agreement with the cache is
  far worse on the private holdout (IoU 0.5680→0.2311) than on the visible
  corpus (0.6319→0.5768) — a much larger aggregate gap than the corpus
  alone would suggest, and whole-document computed is now the default the
  instant a document is provably non-Hancom-written or edited.
- **New, opened by #245 itself:** the full `pipeline/tests` gate result on
  the renderer tip (#245) was reported as still running at write time —
  result not yet posted as of this checkpoint. Treated as open, not as
  passed.
- **Unchanged from checkpoint-11:** desktop line's re-merge onto the
  renderer tip, now four slices stale instead of three; the acceptance
  harness's lexical-reader fix for header/footer text (#235's queued
  item); Codex-app-closed sessions moved; Cursor login; whole-document
  computed layout's page-count/line-IoU behaviour (#199, now measured
  rather than merely named — see #244); writer line's default header/meta
  elements on a blank-package save; `hp:ole`/`hp:chart`/`hp:container`/
  shapes/undecodable EMF-WMF placeholders; `DOUBLE_SLIM` border limitation;
  `hp:parameters` family; `hp:autoNum` inside a footer draws nothing
  (`F51`); `hh:tabPr` stops inside the MCE switch never read; the tier-3
  raster's own `own-uncertified` status; Hancom's first-column endnote
  placement in a two-column section; `textpos_past_end` firing on three
  unedited corpus forms over an `hp:ctrl` given no character cell (#244,
  pre-existing, not fixed).

## 5. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #242 | orchestrator re-ran renderer suite: 230 passed; engine/tests 1243/135 skipped | not a full-suite PR; scoped to the line-box-end + nrf measurement | `py_compile_sweep` 105/0; archive privacy gate HARD=0; no PR comments posted |
| #243 | `test_no_inventory_pins` 16, `test_eval_floors_against_corpus` 11, `test_cleanroom_evals` 74 | **`pipeline/tests`+`tests`: 1919 passed / 11 skipped / 0 failed**; `engine/tests`: 1240 passed / 135 skipped / 0 failed — every suite #240's gate ran is green on this tip | `py_compile_sweep` 105/0; archive privacy gate HARD=0 |
| #244 | engine/tests 1247 passed; own_render/layout subset: 254 passed | **ran, 1 failed** (`test_no_inventory_pins`, inherited from #240, pre-#243) — PR's own words: not this slice's fault, fix carried by #245 | `py_compile_sweep` clean; archive privacy gate HARD=0 |
| #245 | engine/tests 1249 passed + the fixed hang-count test; cleanroom/floors/pins 101 passed | **full `pipeline/tests` suite reported running at write time; no landed result as of this checkpoint** | `py_compile_sweep` 105/0; archive privacy gate HARD=0 |

No PR in this window reports a fresh, landed full-gate pass/fail count the
way #234's comment (3749/0/1199 skipped) did at checkpoint-10 or #243's
comments (1919/11/0 + 1240/135/0) do this window for the pin fix alone —
#245's converged-tip full-suite run is the closest to a whole-gate number,
and it is explicitly open.

## 6. Integration conflicts expected when lines converge

**Renderer line converged three sibling PRs into one tip this window, with
one semantic clash.** #242, #243 and #244 each forked from `claude/engine-
e2-floor-ordering` (or its parent `claude/engine-e2-dpi-independence`) as
siblings; #245 performs the one-hop merge each PR's own body flagged as
needed. The merges themselves carried no textual conflicts, but #242's
trailing-space test encoded an assumption — a single paragraph going
computed — that #244's whole-document policy invalidated; #245 fixed this
by loosening the test to measure rather than pin. This is the second
consecutive window (after #240's DAG-gap repair at checkpoint-11) where a
renderer-line convergence required an actual code change, not just a
merge — here because two measured claims (line-box geometry and cache
provenance) genuinely interact rather than being independent.

**Desktop is not re-merged onto the renderer tip, and the gap widened
again.** #234 still sits on #231; the renderer has since moved through
#232, #236, #240, and now #245 — four slices behind, up from three at
checkpoint-11.

**Writer and renderer lines remain unconverged**, unchanged from
checkpoint-11 — no writer-line PR this window fetched or referenced the new
renderer tip. #239's request for whole-document cache invalidation is
exactly what #244 ships, but no PR body in this window states that #244
was written in response to #239's request beyond the general framing "the
policy fix #239 owed" — the connection is functional, not a merge.

**Runtime line is untouched and unconverged with anything**, unmoved since
#204 (checkpoint-06).

## 7. Next measurable research question

**Closing the computed-layout line-IoU gap on the holdout (0.2311) against
the visible corpus (0.5768), now that computed is the default the instant
a document is provably non-Hancom-written or edited.** #244 measured that
computed layout paginates better than the cache (page-count exact 9/10 →
10/10) but places lines substantially worse, and the gap is far wider on
the private holdout than on the ten visible corpus forms — a 0.34-point
aggregate IoU drop where the corpus shows 0.055. Concretely: characterize
which holdout documents drive that gap (is it concentrated in a few forms,
the way #239's cascade only appeared on the 798-paragraph kstartup form
and not the two smaller ones, or spread evenly?), and whether the
full-width-advance fix #242 costed and refused (which improves IoU but
costs lineseg-break agreement) interacts with the computed-layout gap in
either direction. Not yet measured in either direction.

## 8. Certification status

Every result in this checkpoint — #242 (line-box-end measurement), #243
(floor-pin fix), #244 (cache policy), #245 (convergence) — remains
**own-uncertified**. #242 and #244 change only `own_render`'s geometry and
policy logic, not the renderer's certified surface; #243 changes only a
test-selection mechanism; #245 is a merge plus one test fix. `render_cert.py`
still cannot certify this renderer absent a PDF text layer, unchanged since
checkpoint-01.

**What moved, restated plainly:** this window closed three items
checkpoint-11 explicitly carried forward as open — the trailing-space
line-box question, the `auto`-mode cache-policy design, and #240's own
gate failure — while opening one new, sharper question in their place:
computed layout is now the default whenever a document cannot prove itself
untouched by Hancom, and its cost against the cache is measured for the
first time, at a scale (holdout IoU −0.34) larger than anything shown on
the visible corpus. The convergence PR (#245) also confirms a pattern
first seen at checkpoint-11: parallel renderer-line siblings do not merge
for free once their claims start to interact — #240 needed a DAG-gap
repair, #245 needed a test rewritten from a pinned count to a measured
property.

**Owed, carried forward from checkpoint-11, plus this window's additions:**

- Characterizing and closing the computed-layout line-IoU gap on the
  holdout (0.2311) vs. the corpus (0.5768) — this window's own next
  question, not yet measured.
- The full-width-advance line-box fix #242 costed (nrf IoU +0.030, corpus
  IoU +0.003) and refused (lineseg breaks 80 → 66/216) — no mechanism yet
  proposed to get the gain without the loss.
- Desktop line (#234) re-merged onto the renderer's current tip (#245) —
  last done at #231, now four slices stale, widening from three.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved (carried, not addressed this window).
- Cursor login (carried, not addressed this window).
- **New this window:** #245's own full `pipeline/tests` gate result on the
  renderer tip — reported running at write time, not yet landed as of this
  checkpoint; confirm and append before treating #245 as fully green.
