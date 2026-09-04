# Checkpoint 04 — fonts, borders, render-check, and the outMargin registration

Non-merging checkpoint. Written from `claude/engine-e2-registration` (this
branch, `docs/checkpoint-04`, is cut from that tip and stays unmerged).
Covers PR #202 (justify), #203 (1:1 refs), #205 (equation italics), #208
(bundled OFL fonts), #209 (dashed borders + cache-split paragraph paging;
the row-height defect disproved), #210 (render-check document: 51
features, 1/32/16/2), and #211 — the `hp:outMargin` registration fix on
`claude/engine-e2-registration` (found by `gh pr list --head
claude/engine-e2-registration`; `hp:outMargin` was never read; corpus IoU
0.517 → 0.642, ssim_inked 0.138 → 0.255). Also covers #206 (privacy
scanner JSON-escaped paths), #207 (H2Orestart vs own — own wins), #204
(runtime `renderPrepare` env fix, live leg now succeeds), and #189's live
acceptance result, recorded in a PR comment dated 2026-09-04: 21/21 checks
passed. Checkpoint-03's `docs/research/checkpoint-03.md` (PR #201) carries
forward as the record of #196/#198/#200 and the pre-fork renderer-line
state this checkpoint's #202 picks up from.

## What changed since checkpoint-03

| metric | checkpoint-03 | checkpoint-04 | moved in |
|---|---|---|---|
| holdout justified-line right-edge agreement | 29/239 (12.1%) | **208/239 (87.0%)** | #202 |
| ranked user-visible gap #1 (justification) | open, slice declared not pushed | **closed** | #202 |
| ranked user-visible gap #2 (equation italics) | open | **closed** — real cut or synthetic ~12° oblique per face | #205 |
| corpus reference scale | 3 forms at 0.707 (PrintMethod=4 two-up imposition) | **1:1 for all ten**, glyph ratio 1.003–1.004; permanent [0.97,1.03] guard test | #203, root cause found on #189's live COM leg |
| Hangul body-text rendering off-Hancom-machine | resolved-character share as low as 0.545 (admrul) | **0.624–0.993** across the five previously-degraded forms, via bundled OFL fallback faces | #208 |
| dashed border pattern | drawn solid (no dash geometry) | **period 3.53 × width, duty 0.40**, exact on 43/55 sides, ≤3% elsewhere | #209 |
| "row height" defect | suspected renderer bug | **disproved** — jeongbo 22/23, jumin 46/46 rows agree within 0.2 pt; the visible offset was a page-constant registration gap, renamed as the real target | #209 |
| the registration gap itself | unnamed, ranked "next target" | **named and closed**: `hp:outMargin`, an object's own outer margin, never read by `own_render` | #211 |
| corpus scoreboard means | ssim 0.7837, ssim_inked 0.1376, line IoU 0.5170 (post-#200, unmoved through #209) | **ssim 0.8250, ssim_inked 0.2551, line IoU 0.6423** | #211 |
| rule agreement within 1 pt (corpus) | 61/428 | **365/428** (within 0.25 pt: 28 → 335) | #211 |
| private holdout registration dx | −1.403 pt | **−0.018 pt** | #211 |
| renderer-line shape | one stack, 11 PRs deep (#166→#200) | **forks at #203** into three siblings (#208, #209, #210) plus a docs sibling (#207); #211 stacks further on #209 alone | #203 fork point |
| own renderer vs H2Orestart (LibreOffice), measured | not compared | **own wins on every scored channel** — ssim 0.784 vs 0.752, text-line IoU 0.517 vs 0.145, page_count_exact 90% vs 60%; recommendation: keep own as base | #207 |
| writer-line live acceptance | harness built, live leg "owed" (#189 title) | **live leg run 2026-09-04, 21/21 checks (7×3) passed** on Hancom, closed; acceptance remains the operator's call | #189 (comment) |
| runtime `renderPrepare` live leg | owed since #162 | **succeeds**: `ok: true`, 52,412-byte PDF, sha256 matched — root cause a missing `ProgramData` entry in the child-process env allowlist | #204 |
| privacy scanner path matching | missed doubled-backslash / forward-slash user paths | **fixed**; found live by #189's own `accept.json` output, which had passed the scanner | #206 |
| render-check instrument | did not exist | **new**: 51 labelled Hangul features, 1 match / 32 close / 16 differs / 2 unsupported against a Hancom reference | #210 |

## 1. Branch DAG

Renderer line, unforked through the fit-rule/justify/equation slices, then
**forks into three siblings at #203**:

| PR | branch | base | slice |
|---|---|---|---|
| #200 | `claude/engine-e2-kstartup-ink` | `engine-e2-sections` | (checkpoint-03 tip) |
| #202 | `claude/engine-e2-justify` | `engine-e2-kstartup-ink` | holdout gap #1: justified-line stretch |
| #205 | `claude/engine-e2-eq-italic` | `engine-e2-justify` | holdout gap #2: equation italics |
| #203 | `claude/engine-e2-refs-1to1` | `engine-e2-eq-italic` | 1:1 corpus references (**fork point**) |
| #208 | `claude/engine-e2-bundled-fonts` | `engine-e2-refs-1to1` | E2.2 bundled OFL fonts (sibling A) |
| #209 | `claude/engine-e2-borders-rows` | `engine-e2-refs-1to1` | dashed borders, cache-split paging (sibling B) |
| #211 | `claude/engine-e2-registration` | `engine-e2-borders-rows` | `hp:outMargin` registration, stacked on B |
| #210 | `claude/engine-render-check-doc` | `engine-e2-refs-1to1` | render-check document (sibling C) |

Ancestry verified directly (`git merge-base --is-ancestor`, this session):
`engine-e2-kstartup-ink → engine-e2-justify` YES; `engine-e2-justify →
engine-e2-eq-italic` YES; `engine-e2-eq-italic → engine-e2-refs-1to1` YES;
`engine-e2-refs-1to1 → engine-e2-bundled-fonts` YES; `engine-e2-refs-1to1
→ engine-e2-borders-rows` YES; `engine-e2-refs-1to1 →
engine-render-check-doc` YES; `engine-e2-borders-rows →
engine-e2-registration` YES. Confirming the fork is real, not a naming
coincidence: `engine-render-check-doc → engine-e2-registration` **NO**,
and `engine-e2-bundled-fonts → engine-e2-registration` **NO** — #211 has
neither #210's render-check tooling nor #208's bundled fonts in its tree.
**#211 (`claude/engine-e2-registration`) is the deepest single head**, and
this checkpoint is cut from it.

Sibling docs branch off the same fork point, not stacked further:

| PR | branch | base | note |
|---|---|---|---|
| #207 | `docs/research-h2orestart-vs-own` | `engine-e2-refs-1to1` | H2Orestart comparison, own kept as base |
| #201 | `docs/checkpoint-03` | `engine-e2-kstartup-ink` | prior checkpoint (this doc's predecessor) |

**Declared, not yet a branch:** #210's own body names the table-move rule
(F47 — Hancom moves an overflowing table to the next page; the own
renderer splits it in place) as "**Next**," to be followed by a re-run of
the render-check document "after #208/#209 converge." No
`claude/*table-move*` (or similarly named) branch exists on `origin` as of
this checkpoint — the same pattern checkpoint-03 recorded for
`engine-e2-justify` before it was pushed. It is recorded here as the
fourth line the convergence step must eventually absorb, not as a fourth
verified sibling.

**Convergence is the next integration step, not yet taken.** A
CONVERGENCE branch would need the union of #208 (bundled fonts), #209+#211
(borders/rows + registration), and #210 (render-check) — all three
siblings share `engine-e2-refs-1to1` as their merge-base, and none is an
ancestor of either other. Expected conflicts, from the diffs actually
inspected this session:

- **`engine/scripts/own_render.py`** is independently modified by #208
  (+208/−~30 lines), #209 (+276/−22), and #211 (+58/−4, stacked on #209) —
  three siblings editing the same file from the same base is the DAG's
  central conflict. #210 does not modify `own_render.py` itself (it is a
  read-only measurement harness against it) but its verdicts (16 differs,
  2 unsupported) describe defects that #208/#209/#211 already close in
  part (e.g. #210's F17/F28 page-count mismatch traces to the same
  table-overflow family #209 partially addressed).
- **`engine/references/own-render-notes.md`** — the renderer line's shared
  research log — is touched by every one of #202, #205, #208, #209, #211
  (each appends its own dated section); a three-way append conflict is
  likely but mechanical (non-overlapping sections, resolvable by keeping
  all).
- **`engine/scripts/hwpx_write.py`** appears fresh in #210 (1,177 new
  lines) because, per #210's own body, "the renderer line lacked it" —
  this file is otherwise owned by the writer line (#177 → #180 → #189,
  which touches `hwpx_write.py`, `xml_backend.py`, `preedit.py`,
  `tidy_hwpx.py`). Convergence therefore does not only need to reconcile
  #208/#209/#211/#210 against each other; it also needs to reconcile
  #210's carried copy of `hwpx_write.py` against whatever the writer line
  has done to that file since #189 — a second, cross-line conflict on top
  of the three-way `own_render.py` conflict.
- **`tests/corpus/forms/manifest.json`** is touched by both #203 (54-line
  change, the 1:1 re-pin) and #210 (24-line addition, the new render-check
  fixture) — both siblings edit the manifest independently from the same
  #203 base state; a straightforward two-way append, but real.

### Writer / Runtime / Desktop lines

**Writer line**, moved this window: #177 → #180 → #189
(`claude/engine-e3-hancom-accept`). The PR body itself still says "live
leg owed," but a comment on #189 dated 2026-09-04 records the leg run:
Hancom closed throughout, `hwpx_accept.py` via official Automation on
three inputs (gianmun-byeolji-1ho round-trip, a blank `hwpx_write`
package, kstartup with a baked edit) — **all 21 checks (7 × 3) passed**:
open with no repair dialog, save, close, reopen, edit preserved,
table/paragraph counts unchanged, source sha256 unmutated. The same run
also produced the 1:1-scale reference PDFs #203 later adopted (root cause:
`PrintInfo/PrintMethod=4`). The comment states plainly: **acceptance
status remains the operator's call** — the harness verdict is evidence,
not a promotion. #189 remains the writer line's tip; nothing in this
window stacks a new PR on it.

**Runtime line**, moved this window: … → #185
(`claude/runtime-e4-workspace-ops`) → #204
(`claude/runtime-renderprepare-env`). The live `renderPrepare` leg — owed
since #162 — now succeeds: `ok: true`, `prepared: true`, a 52,412-byte
PDF, sha256 recorded and matched, no orphan `Hwp.exe`. Root cause,
bisected live: `rt_engine.child_env()`'s allowlist omitted `ProgramData`,
which Hancom's security-module registration reads during `Hwp()`
construction; one entry added to `_ENV_KEYS_WINDOWS`.

**Desktop line**, moved this window: … → #184
(`claude/desktop-e1-undo`, two-tier undo + lineage panel). `origin` carries
no `claude/desktop-own-render` (or similarly named) branch as of this
checkpoint — it is referenced in this checkpoint's brief as work in
progress (own renderer shown in-app, zoom/toolbar) but, like the
render-check follow-on above, is not yet a pushed head to verify against.
#184 remains the desktop line's verified tip.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #202 — justified-line stretch (holdout gap #1)

Root cause: cached `hp:lineseg@horzsize` sat a constant 853 HWPUNIT
narrower than the paragraph's true available width on this document.
Fix: a separate `stretch_avail_hwp` sizes JUSTIFY/DISTRIBUTE slack, only
ever `max()`-widened against the cached box.

Holdout justified-line right-edge agreement (0.5 em @144dpi): **29/239
(12.1%) → 208/239 (87.0%)**. Holdout aggregate: line IoU 0.5349 → 0.5389,
ssim_inked 0.1289 → 0.1295, pages 18/18. Corpus: all ten forms change
sub-pixel on justified lines; regression-floor verdicts identical; per-form
ssim_inked moves ≤0.0003. Evidence: 5 new tests; renderer suite 213
passed; full suite 3044 passed / 1199 skipped / 0 failed (19m16s).

### #205 — equation italics (holdout gap #2)

Font index now reads OS/2 `fsSelection`, `head.macStyle`, and name-table
subfamily to record italic/bold-italic cuts per family; resolves a real
cut when one exists, else a synthetic ~12° oblique. Italic applies only to
the parser's `var` token style (bare Latin letter/word) — numbers,
operators, function names, Greek, quoted/Hangul text excluded by
construction.

A first scoring pass against the private holdout's 14 equations caught a
real bug: synthetic shear mixed Pillow's default bbox anchor with
baseline-relative paste math, pivoting on ink bottom instead of baseline —
fixed (anchor, pivot row, two-sided descender padding). Holdout
equation-region crops: ssim 0.4338 → 0.4353, ssim_inked 0.0284 → 0.0288,
ink-IoU 0.0391 → 0.0377; whole-page channels unchanged within 0.0001. Not
proven: the 12° angle against a real Hancom equation render (HancomEQN not
installed on this bench; corpus has no equations). Evidence: renderer
suite 182 passed; engine suite 1149 passed / 135 skipped / 0 failed.

### #203 — three corpus references re-pinned at 1:1

Root cause, found by #189's live COM leg: `기안문 별지 1호/2호` and the
NRF form each store `settings.xml` `PrintInfo/PrintMethod=4` (two-up
imposition), which Hancom's PDF export honours; the existing
`com_backend.py convert` normalisation (force `PrintMethod=0`) produces
true 1:1 output, glyph/charPr ratio 1.003–1.004 vs 0.704–0.711 before. A
permanent test now pins every render reference's declared-height ratio to
[0.97, 1.03]. Re-baseline named: cleaner data exposed a pre-existing
MalgunGothicBold Latin bold-advance gap, per-class bound moved 0.010 →
0.012 em for that face only (tracked, not fixed). Evidence: engine suite
1160 passed / 135 skipped / 0 failed (incl. determinism); full-suite gate
deferred (thin disk).

### #208 — bundled OFL Korean fallback faces (E2.2)

Three SIL OFL 1.1 families bundled (~14.1 MB): Nanum Myeongjo (serif
names), Nanum Gothic (sans names), Nanum Gothic Coding (돋움체/굴림체).
KoPub Batang not bundled (not OFL). Resolution order: installed exact face
→ bundled mapped fallback → system, declared per face as `source:
installed | bundled | system`.

Resolved-character share, this bench (no Hancom Office fonts installed):
admrul 0.545 → 0.624, kstartup 0.938 → 0.984, moel-2013 0.858 → 0.993,
moel-2025 0.738 → 0.968, nrf 0.572 → 0.788; five already-resolved forms
byte-identical. Line-breaker break-position matches 58 → 65 corpus-wide,
no regression. Gate note: archive privacy scan first read HARD=2 on two
`.ttf` files (the known `email_address`-on-glyph-bytes false-positive
class, `ASSET_MAGIC` fix cherry-picked in, `-x`); gate now HARD=0. Not
proven: "installed beats bundled" only by construction, not verified on a
Hancom-installed machine. Evidence: engine/tests 1163 passed / 135
skipped; scanner suite 48 passed.

### #209 — dashed borders at Hancom's measured period; cache-split paragraph paging

**Dashed borders:** no reference PDF uses a dash-array operator — Hancom
emits every dash as its own path piece. Across six DASH-carrying forms,
period 3.53× width / duty 0.40 reproduces the measured pattern exactly on
43/55 sides, ≤3% elsewhere. DOT/DASH_DOT/DASH_DOT_DOT/LONG_DASH share the
period but are declared, not measured (no corpus instance); CIRCLE
unchanged.

**Row height — the premise was wrong.** Per-row agreement against the
reference's own rules: jeongbo 22/23, jumin 46/46, mean |Δ| 0.2 pt (the
half-pixel quantum at 144 dpi). **No fix warranted.** What the eye saw was
a constant per-page registration offset (jeongbo −2.83 pt ≈ 1 mm,
identical top to bottom) — named here as the standing E2 registration gap
and handed directly to #211.

**Cache-split paragraph paging:** `vertpos` restarts per page *within* one
paragraph when the authoring engine splits it across a page break; the
paginator only checked restarts *between* paragraphs, so a tail's
near-zero `vertpos` drew at the head page's top (the holdout's stray
"있다." line the operator spotted). Fixed with `Paragraph.page_runs`
per-run views; 18 holdout pages unchanged.

Corpus means near-flat (dash metrics sit below SSIM/IoU sensitivity):
ssim 0.7837 → 0.7837, ssim_inked 0.1374 → 0.1376, IoU 0.5170 → 0.5170;
only the six DASH forms change bytes. Evidence: engine/tests 1167 passed /
135 skipped. Follow-ups named: the registration offset itself
(→ #211); gianmun-2ho rows (0/5, +11.5 pt); kstartup rows (38/67); CIRCLE
has no measurable reference.

### #210 — the render-check document (51 features)

A Rigorloom-authored synthetic HWPX
(`tests/corpus/render-check/render-check-01.hwpx`, no personal data, so
committed and manifest-pinned) with 51 labelled blocks, one per catalog
T1/T2 visual feature. Hancom reference via official Automation, 1:1
confirmed (scale 0.995). `render_check.py` scores per block and writes
`docs/research/render-check-01.md` + `.report.json` + 51 side-by-side
strips.

**Verdict tally: 1 match · 32 close · 16 differs · 2 unsupported**
(thresholds fitted to this document's spread, unratified). Top differing
mechanisms, none fixed here: F47 — a table crossing a page moves whole to
the next page in Hancom, our renderer splits it in place (confirmed by
eye; cascades into F17/F28's 10-vs-9 page-count mismatch); F49 — Hancom
renders a `colCount=2` section full width, we honour the two columns; F50
— header centred against the page box rather than the subList's declared
`textWidth`. Two catalog rows are contradicted by measurement
(headers/footers and columns ARE drawn — catalog to be corrected). Not
proven: one document, one Hancom build; F48 landscape scored against a
portrait reference because Hancom's PDF export emits every page at
595×841 regardless of declared orientation. Evidence: engine/tests 1181
passed; render_check suite 21 passed. `hwpx_write.py` carried unchanged
from the writer line "because the renderer line lacked it" — the PR's own
integration note for convergence. Next, per the PR body: the table-move
rule (F47), then re-run this document after #208/#209 converge, at which
point it becomes the standing renderer scoreboard.

### #211 — `hp:outMargin`, the whole-page offset, traced (registration)

The "constant per-page registration offset" #209 named was never the
page. It is **`hp:outMargin`** — an object's own outer margin — which
`own_render` had listed as a no-ink structural tag and never read. Hancom
gives an object a slot `left + width + right` wide and draws its box at
`(left, top)` inside it; per table the offset was exactly −outMargin/100
pt in both axes. jeongbo's −2.83 pt is its tables' `outMargin=283`; jumin
page 1 (`outMargin=0`) was already registered to +0.07 pt. Header height,
gutter/binding, 1 mm margin rounding, and raster origin are each
disproven — jumin p1 and admrul share an identical `hp:pagePr` yet
differed by 1.3 pt before the fix.

Per-form offsets (pt, both axes), before → after: jumin p2–3 −1.33 →
+0.07; admrul −1.37 → +0.04; gianmun-1ho −1.38 → +0.07; jeongbo −2.78 →
+0.06; kstartup −1.42 → −0.03; moel-2013 −2.85 → −0.01; moel-2025 −1.35 →
+0.06; nrf −1.37 → +0.02; saeopja −1.35 → +0.06.

**Corpus scoreboard means: ssim 0.7837 → 0.8250, ssim_inked 0.1376 →
0.2551, line IoU 0.5170 → 0.6423**; pair rate flat; page counts unchanged
on all 10. Rule agreement within 1 pt 61/428 → 365/428 (within 0.25 pt 28
→ 335). Private holdout dx −1.403 → −0.018 pt. Exceptions named:
gianmun-2ho rules 8/10 → 2/10 (a pre-existing row-pitch accumulation that
used to cancel the margin; its IoU still rises); kstartup pages
6/9/10/15/16 keep the E2.5 pagination residuals. No corpus form is
byte-identical (all declare a non-zero `outMargin`); the zero-margin no-op
is pinned instead. Not proven: the vertical footprint — line height was
not grown by top+bottom `outMargin`, declared as a limit (costs kstartup a
23rd page under `computed`). Evidence: engine/tests 1172 passed;
determinism stable on 12 forms. **This is the largest single fidelity gain
since the space-advance rule**, per the PR's own claim.

### #207 — H2Orestart vs the own renderer, measured (docs)

Full measurement in WSL (LibreOffice 24.2.7.2 + H2Orestart 0.7.13-1): all
10 corpus forms converted, rasterised at 144 dpi, scored with the same
scoreboard channels against the (now 1:1, post-#203) Hancom references.

| corpus means (10 forms) | own renderer | H2Orestart |
|---|---|---|
| ssim | 0.784 | 0.752 |
| text-line IoU | **0.517** | 0.145 |
| page_count_exact | **90%** | 60% |

H2Orestart's dominant defect: the WSL image has zero Korean fonts
(`fc-list :lang=ko` → 0), so Hangul body text renders as tofu, cascading
into wrong breaks and 4/10 wrong page counts; even setting that aside, its
target is an ODF round-trip, not Hancom layout reproduction. **Decision:
keep the own renderer as base**; H2Orestart is licensed GPL-3.0-or-later
(LibreOffice is MPL-2.0) — usable only as observational ground truth for
border styles, never as a code source into an MIT codebase.

### #206 — privacy scanner: JSON-escaped and forward-slash user paths

`RE_USER_PATH` now matches one-or-more `\`/`/` separators, closing a gap
found live by #189's own `accept.json`, which carried such paths and had
passed the scanner unnoticed. Seven placeholder examples the widened regex
then flagged in tracked source (`Alice`, `operator`, `<you>`, …) were
fixed at the source per repo convention (exempt `<user>` in docstrings,
runtime-assembled needles in test literals) rather than weakening the
regex. Evidence: scanner suite 52 passed (5 new); affected suites 135
passed; sweep 125/0; archive gate HARD=0 (WARN 43, pre-existing).

### #204 — runtime `renderPrepare` env fix (T130)

Bisected live, one variable at a time: `rt_engine.child_env()`'s
allowlist omitted `ProgramData`; Hancom's security-module registration
reads `%ProgramData%` during `Hwp()` construction, so
`win32com.client.Dispatch` failed inside the runtime (CO_E_SERVER_EXEC_FAILURE)
while the same convert succeeded from a normal shell.
`USERNAME`/`USERDOMAIN`/`SESSIONNAME`/`ProgramFiles(x86)`/`HOMEDRIVE`/`HOMEPATH`
were each tried and are NOT needed. Fix: one entry added to
`_ENV_KEYS_WINDOWS`. Live result: `ok: true`, `prepared: true`, 52,412-byte
PDF, sha256 matched, no orphan `Hwp.exe`. Evidence: `test_runtime_child_env.py`
4 new; `test_runtime_render_prepare.py` 28; runtime sweep 431 passed / 1
pre-existing skip. Not proven: the CLI's render-prepare JSON carries no
`grade` field — "hancom" grade is implied by the path, not stated on the
wire.

### #189 (comment) — live Hancom acceptance, 21/21

Recorded on the PR, not in its body (dated 2026-09-04, commits `a07ceb0`,
`b8a87e1` on that branch): `hwpx_accept.py` run via official Automation,
Hancom closed throughout, on three inputs — gianmun-byeolji-1ho
round-trip, a blank `hwpx_write` package, kstartup (42 tables / 798
paragraphs) — each with a baked edit. **All 21 checks (7 × 3) passed**:
open with no repair/recovery dialog, save, close, reopen, edit preserved,
table/paragraph counts unchanged, source sha256 unmutated. Findings not
fixed there: Hancom adds ~30 default header/meta elements to the blank
package on save (writer-completeness follow-up, still open); the
JSON-escaped-path scanner gap that became #206. Also produced the
1:1-scale reference PDFs #203 adopted. **Acceptance status remains the
operator's call** — the comment states this explicitly; the harness
verdict is evidence only.

## 3. Regressions (with the PR's or commit's own explanation)

| PR | metric | moved | explanation given |
|---|---|---|---|
| #203 | MalgunGothicBold Latin bold-advance bound | 0.010 → 0.012 em, that face only | "cleaner data exposed a real pre-existing" gap — re-baseline, not a new defect; tracked as a follow-up |
| #208 | nrf line-IoU | 0.660 → 0.624 | "reported, not investigated" — the only changed-form metric that moved down among otherwise flat-or-improved changes |
| #209 | (no scoreboard regression) | corpus means unchanged within measurement floor | dash metrics "sit below SSIM/IoU sensitivity — stated," not hidden |
| #211 | gianmun-2ho rule agreement | 8/10 → 2/10 | "a pre-existing accumulation that used to cancel the margin" — its own row-pitch drift (24.44 pt vs 24.09) had been coincidentally masking the registration error; IoU for that form still rises overall |
| #211 | kstartup pages 6/9/10/15/16 | unchanged, still carry E2.5 pagination residuals | not addressed by this PR; named as a carried-forward limit, not netted against the corpus-wide gain |

No corpus form regressed on sha256/page-count across #202, #205, #208
(except the one named nrf line-IoU dip), #209, or #211; each PR states
this explicitly for its unaffected forms.

## 4. Unsupported / declared elements still open

Carried from checkpoint-03, with items this checkpoint's PRs closed,
refined, or added:

- **Closed since checkpoint-03:** missing paragraph justification (#202,
  ranked gap #1) and non-italic equation variables (#205, ranked gap #2) —
  both were the holdout tracker's top two named gaps in checkpoint-03 and
  are now implemented and measured. The "constant per-page registration
  offset" #209 named but left open is closed by #211, identified as
  `hp:outMargin`. The row-height hypothesis from checkpoint-02/03 is
  formally disproved by #209's per-row measurement (jeongbo 22/23, jumin
  46/46).
- **New, implemented, machine-dependent by construction (#208):** bundled
  OFL fallback faces cover 14 named face aliases; faces outside that table
  (HCI Poppy, 한컴바탕, 신명 신문명조, HY울릉도M, 필기…) remain
  machine-dependent and declared as such.
- **New, declared not measured (#209):** DOT/DASH_DOT/DASH_DOT_DOT/LONG_DASH
  border styles share the measured period but have no corpus instance;
  CIRCLE has no measurable reference at all.
- **New, disproven this window (#211):** the vertical footprint of
  `outMargin` — line height is not grown by top+bottom `outMargin`;
  nothing measures it, and it costs kstartup a 23rd page under `computed`
  — declared as a limit, not fixed.
- **New, catalogued by #210's 51-feature check, none fixed here:** F47
  table-crosses-page (table split in place vs Hancom's whole-table move —
  cascades into two page-count-mismatch verdicts); F49 two-column section
  width; F50 header alignment against the page box vs the section's
  declared `textWidth`; 16 "differs" verdicts total, thresholds unratified.
  Two catalog rows (headers/footers, columns) are now known to be wrong in
  the *opposite* direction — the catalog claimed them unimplemented; #210
  shows they render, just not identically.
- **New axis, closed by measurement but with a residual (#203):** the
  three 0.707-scale references are now 1:1, but the guard test that
  prevents recurrence ([0.97, 1.03]) is new and this checkpoint's window
  is its first use.
- **Writer line, changed since checkpoint-03:** #189's harness itself now
  has a live-run result (21/21) — no longer purely "owed" — but
  acceptance remains explicitly the operator's decision, not a status the
  harness can grant itself. A new, separate finding from that same run:
  Hancom adds ~30 default header/meta elements to a blank `hwpx_write`
  package on save — an open writer-completeness question, not yet
  assigned a slice.
- **Runtime line, closed since checkpoint-03:** the `renderPrepare` live
  leg, owed since #162, now succeeds (#204). Open residual: the render-
  prepare JSON has no `grade` field on the wire.
- **Still open, unchanged from checkpoint-03:** line-breaker exact-position
  agreement research figure (58/216 in checkpoint-03's own text; #208
  reports break-position matches moving 58 → 65 corpus-wide as a side
  effect of font resolution, not a direct line-breaker change); whole-
  document computed layout's page-count/line-IoU failure (21/18 pages,
  0.180 line IoU, #199) — no PR in this window touched that axis;
  `hp:ole`/`hp:chart`/`hp:container`/shapes/undecodable EMF-WMF grey
  placeholders; only `DOUBLE_SLIM` draws two border strokes; text wrap
  around anchored objects; `hp:parameters` family unrendered; equations'
  declared-unsupported constructs (`size`, `color`, `bigg`/`small`,
  `binom`, `choose`, `buildrel`, `rel`, `dyad`, `col` family, unbalanced
  fences) unchanged by #205, which only added italics to the `var` token.
- **Desktop line, unmoved this window:** #184 remains the verified tip; a
  `claude/desktop-own-render` line is referenced in this checkpoint's
  brief as in progress but is not yet a pushed branch to verify.

## 5. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / engine suite | full suite | notes |
|---|---|---|---|
| #202 | renderer suite 213 passed | 3044 passed / 1199 skipped / 0 failed (19m16s, core-only) | 5 new tests; `py_compile_sweep` 103/0; privacy HARD=0 |
| #205 | renderer suite 182; engine suite 1149/135 skipped/0 failed (2m58s) | deferred (thin disk, 3 background runs killed by an external process) | one non-equation corpus form byte-identical (sha256); `py_compile_sweep` 103/0; privacy HARD=0 |
| #203 | engine suite 1160/135 skipped/0 failed (incl. determinism) | deferred (bench disk hit 0.1 GB) | `py_compile_sweep` 103/0; archive privacy HARD=0 |
| #208 | engine/tests 1163/135 skipped; scanner suite 48 passed | deferred (thin disk) | `py_compile_sweep` 103/0; archive gate HARD=0 (WARN 50, six benign `large_file` on the fonts) |
| #209 | engine/tests 1167/135 skipped | deferred (thin disk) | `py_compile_sweep` not separately cited; privacy gate HARD=0 |
| #210 | engine/tests 1181 passed; render_check suite 21 passed (eyeballed F47, F10 strips) | deferred (thin disk) | `py_compile_sweep` 105/0; archive privacy HARD=0 |
| #211 | engine/tests 1172 passed; determinism stable on 12 forms | deferred (thin disk) | `py_compile_sweep` 103/0; archive privacy HARD=0 |
| #207 | (docs-only PR) | not applicable | Sonnet-written; renders deleted from scratch; corpus untouched |
| #206 | scanner suite 52 passed (5 new); affected suites 135 passed; sweep 125/0 | deferred (thin disk) | archive gate HARD=0 (WARN 43, pre-existing) |
| #204 | `test_runtime_child_env.py` 4 new; `test_runtime_render_prepare.py` 28; `test_subprocess_bounds.py` 9; runtime sweep 431/1 pre-existing skip | deferred (bench disk) | `py_compile_sweep` 127/0; privacy HARD=0 |
| #189 (live comment) | `hwpx_accept.py`, 21 checks (7×3) passed, live Hancom | not cited in the comment | evidence at `engine/references/acceptance/*.json` + `hancom-acceptance-01.md` |

Every full-suite gate from #203 onward is explicitly **deferred** in its
own PR body — each cites the same recurring cause, the bench's disk
sitting at 0.1–6 GB during that session — and none of #203–#211's bodies
records that the deferred run was later appended. This is a new,
recurring pattern this checkpoint's window did not see in checkpoint-03:
every PR's suite evidence past #202 is an engine/renderer-suite subset
plus a stated deferral, not a fresh full-suite number.

## 6. Integration conflicts expected when lines converge

- **The renderer line forks, not just deepens, at #203.** Through
  checkpoint-03 it was one 11-PR stack; this window adds #202 and #205 in
  stack (13 deep to #203), then **splits into three independently-based
  siblings** (#208, #209→#211, #210) plus a docs sibling (#207), all
  sharing `engine-e2-refs-1to1` as merge-base. `own_render.py` is
  independently edited by #208, #209, and #211 (#211 stacked on #209, so
  effectively two independent edits — #208's and #209/#211's combined —
  against the same base) — a real three-way (not pairwise) merge
  conflict, confirmed by inspecting each PR's diff directly rather than
  inferred from titles.
- **`hwpx_write.py` crosses lines, not just PRs.** #210 introduces a fresh
  1,177-line copy because "the renderer line lacked it," but this file is
  the writer line's own (#177/#180/#189 all touch it). Convergence must
  reconcile #210's carried copy against the writer line's current state
  of the same file — a cross-line conflict the render-check PR's own body
  flags as an "integration note," not resolved here.
- **`tests/corpus/forms/manifest.json`** is touched independently by #203
  (the 1:1 re-pin, 54 lines) and #210 (the render-check fixture addition,
  24 lines) from the same base — a real two-way conflict, smaller than
  `own_render.py`'s but confirmed by diff.
- **`engine/references/own-render-notes.md`** is appended by #202, #205,
  #208, #209, and #211 — five independent dated sections off the same
  research log; mechanically resolvable (each section is additive) but a
  five-way conflict in practice, the largest fan-in of any file this
  session inspected.
- **The declared table-move branch (F47, off #210)** does not exist yet on
  `origin`; it is a fourth line convergence will eventually need once
  pushed, on top of the three siblings already diverged.
- **Renderer vs writer, beyond `hwpx_write.py`:** no other direct file
  overlap observed this window. The writer line's #189 now has a live
  21/21 result but the PR body's own "acceptance is the operator's call"
  framing means a merge to `main` still combines an evidenced-but-forking
  renderer chain with a writer chain whose promotion is a human decision,
  not a code state.
- **Runtime vs renderer/writer:** #204 touches only `rt_engine.child_env()`
  and its tests — no shared files with the renderer or writer lines this
  window; the runtime and renderer/writer lines continue to meet only at
  `main`.
- **Desktop line:** unmoved since checkpoint-03's #184 tip; not touched by
  any PR in this window. The referenced `claude/desktop-own-render` work
  (own renderer shown in-app + zoom/toolbar), once pushed, will be the
  first point where the desktop line depends on the renderer line's own
  code rather than only its output — worth flagging now, before it lands.

## 7. Next measurable research question

**Convergence is the next integration step**, not another slice on any
one sibling. Concretely: merge #208 (bundled fonts) + #211 (registration,
carrying #209's border/paging fixes) + #210 (render-check) into one tree
off `engine-e2-refs-1to1`, resolving the `own_render.py` three-way
conflict, the `hwpx_write.py` cross-line conflict against the writer
line's current state, and the `manifest.json`/`own-render-notes.md`
append conflicts named in section 6. The table-move branch (F47), once
pushed, is a fourth input to that merge, not a fifth checkpoint.

**Expected verdict shift, stated but not yet measured:** after
convergence, re-running #210's render-check document (51 features) should
move its "16 differs" bucket down, since #211's registration fix and
#209's dashed-border fix each address defect classes the render-check
document scores independently — #210's own body names this expectation
("re-run this check after #208/#209 converge — this document becomes the
standing renderer scoreboard"). Re-running the private holdout tracker
(tracker 01, #199) after convergence should likewise show a shift from
#211's dx improvement (−1.403 → −0.018 pt on the holdout already, in
isolation) compounding with #208's font-resolution gains — neither has
been measured together with the other on the holdout as of this
checkpoint. Both re-runs are the concrete next measurement, not a new
renderer feature.

Separately, two smaller open threads carried from checkpoint-03 remain
unscheduled against the convergence step: whole-document computed layout
still fails page-count and line-IoU floors (21/18 pages, 0.180 line IoU,
#199) with no PR in this window touching it; and the writer line's new
finding (Hancom adding ~30 default header/meta elements to a blank
package on save) has no assigned slice.

## 8. Certification status

Every own-render result in this checkpoint — justification (#202),
equation italics (#205), the 1:1 reference re-pin (#203), bundled fonts
(#208), dashed borders and cache-split paging (#209), the render-check
document's 51-feature tally (#210), and the `hp:outMargin` registration
fix (#211) — remains **own-uncertified**. None of the seven PRs' own
bodies claims certification; `pipeline/scripts/render_cert.py` still
cannot certify this renderer absent a PDF text layer, unchanged from
checkpoint-01 through checkpoint-03.

The writer line's #189 is the one item in this window whose framing
differs: it now carries a live, evidenced Hancom acceptance result
(21/21), which is a stronger claim than checkpoint-03's "harness exists,
live leg owed" — but the PR comment recording that result states
explicitly that acceptance is still the operator's call, not a status the
harness or this checkpoint can grant. It stays outside the
own-uncertified/certified distinction entirely: it is a writer-line
acceptance question, not a renderer-line certification one, and this
checkpoint does not conflate the two.

H2Orestart (#207) was measured as an alternative base and rejected on
numbers (own renderer's text-line IoU 0.517 vs 0.145, page_count_exact 90%
vs 60%) — this closes, rather than opens, a certification-adjacent
question: the own renderer is confirmed as the correct base to keep
pursuing certification on, not a detour to be reconsidered later.
