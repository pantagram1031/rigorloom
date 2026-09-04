# Checkpoint 10 — layout that no longer depends on the raster

Non-merging checkpoint. Written from `origin/claude/engine-e2-dpi-independence`
(this branch, `docs/checkpoint-10`, is cut from that tip and stays unmerged).
Covers #234 (`claude/desktop-renderer-230`: the desktop renders and edits
with renderer #231, the tip whose full gate is green — smoke **551/0** across
14 phases, the `own` phase growing **40 → 91** checks, and, in a PR comment,
the desktop line's own full `pipeline/tests` gate: **3749 passed / 1199
skipped / 63 subtests passed**, 1458.42 s, reported as surviving with zero
failures), #235 (`claude/engine-e3-accept-02`: writer acceptance run 02,
4 inputs × 7 checks, **27/28** — the new hardest case, a Rigorloom-authored
51-feature render-check document, survives a Hancom Automation round-trip at
6/7, with the one miss named as a harness gap, not a writer defect: header
text is invisible to `GetTextFile("TEXT")` though present byte-for-byte in
the saved `section0.xml`; a second finding that Hancom substantially
restructures the `header.xml` style catalog on save, unrelated to the
harness gap), and the dpi-independence PR (#236,
`claude/engine-e2-dpi-independence`: every layout advance now comes from a
face measured once at a fixed 1024 px em and scaled analytically into
HWPUNIT, instead of `draw.textlength` on an integer-pixel-sized font — layout
is byte-identical at 96/144/192/288 dpi on 11 documents; lineseg break
agreement 68 → 80/216; render-check tally at 96 dpi **3/38/8/2 → 6/37/6/2**,
9 = 9 pages both before and after; `nrf` regresses `ssim_inked` −0.016 and
`text_line_iou` −0.013 — named, not netted).

## What changed since checkpoint-09

| metric | checkpoint-09 | checkpoint-10 | moved in |
|---|---|---|---|
| renderer-line tip | #232 (ink-residual floor; next question named: dpi-independence) | **#236** — layout moved to HWPUNIT, byte-identical at every dpi tested | #236 |
| render-check tally, 96 dpi | 3 · 38 · 8 · 2 | **6 · 37 · 6 · 2** — the exact-match count doubled, from fixing the dpi-dependent break, not from tuning a bound | #236 |
| render-check tally, 144 dpi | 7 · 38 · 4 · 2 (recorded but explicitly not claimable — #232's own body warned it conflated the rasteriser floor with a layout regression) | **14 · 31 · 4 · 2** — now claimable, the better of the two dpis | #236 |
| line-break agreement vs authoring cache (144 dpi, corpus) | not measured this way at checkpoint-09 | **68 → 80/216** breaks matched; per-decision exact 65 → 77/216 | #236 |
| desktop line | still #221 (gap 34, checkpoint-07 tip); no re-merge branch existed in `origin` | **#234** — merged onto renderer #231 (the then-tip); smoke 551/0, `own` phase 40 → 91, own full gate 3749/0/1199 skipped | #234 |
| desktop ↔ renderer gap | ten renderer slices ahead of the desktop's last re-merge (#215) | **two** — #234 sits on #231; the renderer has since moved only #232 and #236 past it | #234, #236 |
| writer line | #224, unmoved | **#235** — acceptance run 02, 27/28 across four inputs, including the first render-check-document leg (6/7) | #235 |
| runtime line | unmoved since checkpoint-06 (#204) | **still unmoved** (#204) | — |
| render-check `differs` queue (8 rows) | 5 of 8 rasteriser-attributed (`F06`–`F08`, `F13`, `F15`); 3 unattributed | **6 remain**, of which **4 are rasteriser-attributed** — the line-breaking fix closed two of the previously rasteriser-adjacent rows outright rather than leaving them as floor | #236 |
| new finding | line breaking is not resolution-independent (#232) | **line boxes report the advance, not the ink** — a trailing space hangs a box past the column with no pixel drawn (7.7 px on the relayout fixture), and closing it moves `text_line_iou` on eight forms in both directions | #236 |

## 1. Branch DAG

Renderer line, now a straight chain of three off checkpoint-09's tip:

| PR | branch | base | slice |
|---|---|---|---|
| #231 | `claude/engine-e2-render-check-claim` | `claude/engine-e2-converge-3` | support-matrix claim; first fully green full suite since #210 (checkpoint-09 tip at the time) |
| #232 | `claude/engine-e2-ink-residual` | `claude/engine-e2-render-check-claim` | ink residual declared a floor; dpi-independence named as the next question (checkpoint-09) |
| **#236** | `claude/engine-e2-dpi-independence` | `claude/engine-e2-ink-residual` | **layout advances moved to HWPUNIT via a 1024 px em analytic scale; byte-identical layout at 96/144/192/288 dpi; render-check tally 3/38/8/2 → 6/37/6/2 at 96 dpi. Depends on #232 per its own body — this is the renderer tip.** |

Desktop line, re-merged for the first time since #215:

| PR | branch | base | slice |
|---|---|---|---|
| #221 | `claude/desktop-own-render-edit` | `claude/desktop-own-render-converged` | gap 34 closed (checkpoint-07 tip) |
| **#234** | `claude/desktop-renderer-230` | `claude/desktop-own-render-edit` | **merges the renderer line (through #218, #219, #222, #223, #226, #227, #228, #230, #231) onto #221; one conflict, resolved as a union of two disjoint test sections; renders and edits with #231. Depends on #221 + #231.** |

The desktop is now **two renderer slices behind** the tip (#232, #236), the
narrowest this gap has been since checkpoint-06 — checkpoint-09 measured it
at ten.

Writer line:

| PR | branch | base | slice |
|---|---|---|---|
| #224 | `claude/engine-e3-writer-colpr-order` | `claude/engine-e3-hancom-accept` | section-head control order Hancom needs (checkpoint-07/08 tip) |
| **#235** | `claude/engine-e3-accept-02` | `claude/engine-e3-writer-colpr-order` | **acceptance run 02: 27/28 across four inputs; harness gap named (`GetTextFile` skips header text), not a writer defect. Depends on #224.** |

No branch named for a lexical-reader harness fix exists in `origin` as of
this checkpoint (`git branch -r` shows none) — the fix #235 names as queued
("read the edited region through the lexical reader, not the text export")
is in flight, not yet pushed.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Sibling docs branches: `docs/checkpoint-06` … `docs/checkpoint-09` (off
#232). No new fork opened in the renderer line this window — #232 → #236 is
a straight continuation, matching the #230 → #231 → #232 stretch checkpoint-09
already reported as unforked.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #234 — the desktop renders and edits with the tip whose full gate is green

Merge of `origin/claude/engine-e2-converge-3` (#218, #219, #222, #223, #228,
#227) and `origin/claude/engine-e2-render-check-claim` (#231) onto the
gap-34 tip (#221). One conflict — `engine/tests/test_own_render.py`, two
disjoint test sections (desktop's sidecar/address tests vs the renderer's
endnote tests) — resolved as a union; `own_render.py` and the notes
auto-merged. Sidecar **0** with all 10 role checks; **99.0 MiB**; `tsc`
**0**; `tauri build` **0**; **smoke 551/0** across 14 phases, the `own`
phase growing **40 → 91** checks (9 seats, all `own_cell`; 5-of-30 spans
caret-capable with per-character offsets verified); engine/tests + geometry
**1329 passed / 135 skipped**; `py_compile_sweep` **131/0**; archive privacy
gate HARD=0. A PR comment on tip `3ddc32a` reports the desktop line's own
full `pipeline/tests` gate: **3749 passed, 1199 skipped, 63 subtests passed,
1458.42 s (0:24:18)**, the run "survived" — the desktop line's own analogue
of #231's first-green-since-#210 result, now on the merged tree.

**Defect found and fixed in-slice:** a stray orphaned `rigorloomd.exe` from
an earlier probe held a file lock, silently failing `Remove-Item` and
nesting a corrupted copy under `resources/rigorloomd/rigorloomd/` — killed,
wiped, rebuilt clean; a build-script guard is named as a follow-up, not
done. **Not proven** (the PR's own words): the `own`-phase counts are one
run with no prior identical baseline in this session; retaken screenshots
were not pixel-diffed against the previous set.

### #235 — the writer survives its hardest acceptance case, with one harness gap named

E3.2 acceptance run 02, Hancom closed, official Automation, strictly serial:
four inputs × seven checks = 28. Gianmun round-trip **7/7**, blank package
**7/7**, kstartup round-trip **7/7** (identical to run 01) — and the new
case, the Rigorloom-authored 51-feature render-check document (headers,
footers, footnotes, endnotes, columns, equations, merged cells): **6/7**.
No repair or recovery dialog on any leg. The one failure is attributed to
the harness, not the writer: the edit marker landed in a header run, and
`GetTextFile("TEXT")` does not export header/footer text at all — the
marker is present byte-for-byte in `section0.xml` of the Hancom-saved
candidate. Fix queued (read the edited region through the lexical reader),
not done here.

**Structure-preservation finding:** table/paragraph counts unchanged (6 /
227), but Hancom substantially restructures and consolidates the
`header.xml` style catalog (paraPr, charPr, borders, headings, outlines,
numbering, bullets) on save — the same normalisation the blank-package case
already showed, larger here. The PR's own body states the consequence
plainly: any future "unaffected structures preserved" claim must compare
body structure, not the style catalog verbatim. Not proven: whether all 51
features render identically after the round-trip — this harness never
re-renders to PDF, which is render-check's job on the saved candidate, next.

**Evidence:** `py_compile_sweep` 104/0; archive privacy gate HARD=0 (JSON
paths redacted; the widened scanner would have caught them).

### #236 — layout stops depending on the raster

**What was leaking, named precisely:** `_font_for` built each face at an
**integer** pixel size (`round(pt × dpi / 72)` — 10 pt is 13 px at 96 dpi,
i.e. 9.75 pt, 2.5% narrow; 20 px at 144), and every advance came from
`draw.textlength` on that hinted face, so FreeType rounded each advance to a
whole pixel — a different error at every resolution. Measured drift before
the fix: `F06`/`F07` held **50** characters on line 2 at 96 dpi and **44**
at 144/192/288; `moel-2013` re-broke 25 paragraphs and gained two pages
(9 vs 7) at 144 dpi; `kstartup` gained a page at 192. Everything downstream
(`_line_metrics`, object extents, equation extents) was already HWPUNIT and
not guilty.

**Fix:** every layout advance now comes from the face measured once at a
fixed **1024 px em** and scaled analytically into HWPUNIT — Pillow exposes
no unhinted metric, so this is the large-reference-size story, not an
unhinted one: rounding error is under 0.1% per glyph and, decisively, the
*same* 0.1% at every output resolution (stated in the constant's own
comment). Advance tables, span width, tab advance, `compute_lines`'s
avail/width/slack, the half-cell space and the (unexercised) footnote column
all moved to HWPUNIT; the raster now enters exactly once, when a glyph is
drawn.

**After — layout is byte-identical at 96/144/192/288 dpi** on the
render-check document, all ten corpus forms, and the private holdout,
asserted by `test_the_layout_is_identical_at_every_dpi` (11 parametrised
cases) plus a mechanism-only test. Line-breaker agreement against the
authoring engine's own cache, corpus-wide at 144 dpi: break positions
matched **68 → 80/216**; per-decision exact **65 → 77/216**; paragraphs with
an exact break sequence 2014 → 2030/2148. Six of eleven documents were
already dpi-independent (declared sizes landed on integer pixels at 144);
six move, `moel-2013` most (24/264 paragraphs, 9 → 7 pages — *toward* its
own cached pagination, not away from it).

**render-check-01 tally, 9 = 9 pages exact at both dpis:**

| dpi | before | after |
|---|---|---|
| 96 | 3 match · 38 close · 8 differs · 2 unsupported | **6 · 37 · 6 · 2** |
| 144 | 7 · 38 · 4 · 2 | **14 · 31 · 4 · 2** |

The 144 dpi tally #232 recorded but explicitly declined to claim (its own
body warned it conflated the rasteriser floor with a layout regression) is
now claimable, and is the better of the two.

**Corpus scoreboard, 144 dpi, `auto` layout:** every form still comparable,
every verdict still `pass`, every page count unchanged. Means: `ssim_mean`
+0.00078, `ssim_inked_mean` +0.0021, `text_line_iou_mean` +0.00024. Named
extremes: `gianmun-1ho` `ssim_inked` +0.0150 and `jumin` +0.0106 the good
way; **`nrf` `ssim_inked` −0.0160 and `text_line_iou` −0.0128 the other** —
the one regression named in this window, attributed to `nrf`'s faces
happening to be better served by the old, wrong, 144 dpi integer rounding.

**Private holdout (aggregate only):** 18/18 pages exact, before and after;
`ssim_mean` 0.8132 → 0.8206; `ssim_inked_mean` 0.2927 → 0.3158;
`text_line_iou_mean` 0.7641 → 0.7651; lineseg break recall unmoved at
59/252, but per-decision accuracy 0.4365 → 0.4603 and `late` misses collapse
38 → 15.

**Evidence:** engine/tests **1240 passed**; pipeline/tests **1437 passed**;
`py_compile_sweep` 105/0; repeat renders byte-identical; archive privacy
gate HARD=0 — reported directly in the body, not deferred as "running."

**Not proven, stated in the body:** one machine's font stack; 1024 px
hinting is not unhinted outlines; the footnote column is analytic but
unexercised by any corpus document; the dpi ladder is four rungs (96–288)
only; and — the sharpest one — `line_boxes` still reports the *advance*, not
the ink: a trailing space hangs past the column with no pixel drawn there
(7.7 px on the relayout fixture), and closing that gap moves
`text_line_iou` on eight of the ten forms in both directions.

## 3. Regressions (with the PR's or commit's own explanation)

**One, named and not netted: `nrf` at 144 dpi.** #236's corpus scoreboard
shows `ssim_inked` −0.016 and `text_line_iou` −0.013 for `nrf` while every
other form and the aggregate mean improve. The PR's own explanation:
`nrf`'s glyph faces happened to be better served by the old (wrong) integer
rounding at 144 dpi than by the new analytic advance — a face-specific
side-effect of removing a bug, not a new bug. No mechanism fix is offered in
this PR; it is stated as a known, accepted trade in exchange for
resolution-independence everywhere else. #234 and #235 report no
regressions in their own bodies — #234's is a conflict-resolved merge with
counts compared directly against #221's prior baseline where one existed,
and #235's one failure (§2 above) is attributed to the acceptance harness's
export path, not to the writer or the document it produced.

## 4. Unsupported / declared elements still open

Carried from checkpoint-09, with this window's closures and new items:

- **Closed since checkpoint-09:** the desktop line's ten-slice staleness
  behind the renderer tip — closed by #234's merge (gap narrowed to two);
  the dpi-independent line-breaking question #232 named as the next
  measurable question — answered by #236, not left as a floor.
- **Improved, not fully closed:** of the 8 `differs` rows at checkpoint-09
  (5 rasteriser-attributed: `F06`–`F08`, `F13`, `F15`; 3 unattributed:
  `F35`, `F48`, `F50`), the tally now reads 6 `differs`, **4 of which remain
  rasteriser-attributed** — two rows the line-breaking fix moved off
  `differs` outright, closing them with a correctness fix rather than
  leaving them as `RASTERISER_FLOOR`. The reference-side and
  mechanism-guess limits from checkpoint-09 (`F35` wrap-around anchoring,
  `F48` Hancom's own landscape-flattening PDF export, `F50` header
  centring) are not reported as touched by any PR in this window.
- **New, opened by #236 itself:** `line_boxes` reports the advance, not the
  ink — a trailing space hangs a box past its column with no pixel drawn
  (7.7 px on the relayout fixture); closing it is named as needing its own
  measurement, since it moves `text_line_iou` on eight forms in both
  directions.
- **New, opened by #235:** the acceptance harness's `GetTextFile("TEXT")`
  gap on header/footer text (fix queued: read via the lexical reader, not
  the text export); Hancom's header.xml style-catalog restructuring on
  save, now confirmed on a 51-feature document as well as the blank
  package.
- **Unchanged from checkpoint-09:** whole-document computed layout's
  page-count/line-IoU failure (#199); writer line's default header/meta
  elements on a blank-package save; `hp:ole`/`hp:chart`/`hp:container`/
  shapes/undecodable EMF-WMF placeholders; `DOUBLE_SLIM` border limitation;
  `hp:parameters` family; `hp:autoNum` inside a footer draws nothing
  (`F51`); `hh:tabPr` stops inside the MCE switch never read; the tier-3
  raster's own `own-uncertified` status; Hancom's first-column endnote
  placement in a two-column section.

## 5. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #234 | sidecar 0 (10/10 role checks); smoke **551/0** (14 phases, `own` 40 → 91); engine/tests + geometry **1329 / 135 skipped** | **3749 passed / 1199 skipped / 63 subtests passed** (PR comment, tip `3ddc32a`, 0:24:18) | `tsc` 0; `tauri build` 0; `py_compile_sweep` 131/0; archive privacy gate HARD=0 |
| #235 | acceptance run 02: **27/28** (7/7, 7/7, 7/7, 6/7) | not a full-suite PR; scoped to acceptance harness | `py_compile_sweep` 104/0; archive privacy gate HARD=0 |
| #236 | engine/tests **1240 passed** | **pipeline/tests 1437 passed** (reported directly, not deferred) | `py_compile_sweep` 105/0; repeat renders byte-identical; archive privacy gate HARD=0 |

**The desktop line now has its own reported full-gate green run** (#234's
comment, 3749/0/1199 skipped) — distinct from, and later than, the
renderer-line green run #231 reported at checkpoint-09 (3133/0/1199
skipped). Both report zero failures; neither is superseded by the other,
since they measure different merged trees.

## 6. Integration conflicts expected when lines converge

**Desktop ↔ renderer converged this window, with one conflict, resolved.**
#234's merge of the renderer line onto #221 hit exactly one file,
`engine/tests/test_own_render.py`, where the desktop's own sidecar/address
tests and the renderer's endnote tests occupied disjoint sections of the
same file — resolved as a union, no logic conflict. `own_render.py` itself
and its reference notes auto-merged clean. This is the same shape #230's
merge of #227 onto #228 showed at checkpoint-09 (conflict-free on code), one
level up the stack.

**The desktop is not yet re-merged onto #236.** #234 sits on #231; the
renderer has since moved through #232 and #236, so the desktop is two
slices behind again, though the smallest gap measured since checkpoint-06.
No branch for that re-merge is visible in `origin` as of this checkpoint.

**Writer and renderer lines remain unconverged.** #235 is scoped to the
writer's own acceptance harness and does not touch `own_render.py`; no PR in
this window merges the writer line onto the renderer tip or vice versa.

**Runtime line is untouched and unconverged with anything**, unmoved since
#204 (checkpoint-06).

## 7. Next measurable research question

**Does a line box end at the last glyph's ink, or at its advance?** #236's
own "not proven" section names this directly: `line_boxes` currently reports
the *advance* (where the cursor would land after a trailing space), not the
*ink* (where the last visible pixel is), and a trailing space can hang a box
7.7 px past the actual glyph on the relayout fixture with nothing drawn
there. Closing this moves `text_line_iou` on eight of the ten corpus forms
— in both directions, per #236's own body, so the direction is not
predictable from the mechanism alone. The concrete next step: settle the
question from the reference PDF (which of the two — advance-end or
ink-end — matches Hancom's own line boxes on the forms that move) before
changing `line_boxes`, rather than picking a convention and re-measuring
after.

## 8. Certification status

Every own-render result in this checkpoint — #234 (desktop merge), #235
(writer acceptance), #236 (dpi-independence) — remains **own-uncertified**.
None of the three PRs' own bodies claims certification; #236 explicitly
scopes its "not proven" list to include font-stack and hinting caveats that
a certification would need closed. `render_cert.py` still cannot certify
this renderer absent a PDF text layer, unchanged since checkpoint-01.

**What moved, restated plainly:** the desktop line now has its own green
full-gate run (3749/0/1199 skipped, #234) in addition to the renderer
line's (3133/0/1199 skipped, #231, checkpoint-09) — two independently
reported zero-failure full suites where checkpoint-08 and earlier had none.
The render-check exact-match count doubled (3 → 6) from a correctness fix
to a genuine layout bug (dpi-dependent rounding before line breaking), not
from loosening a bound — the opposite of what checkpoint-09's dpi-aware
`render_check` bounds did (both stated as exact no-ops at 96 dpi).

**Owed, carried forward and restated exactly, plus two additions:**

- The trailing-space line-box question (advance vs. ink), #236's own next
  question, §7 above — not yet a branch or PR.
- Desktop line (#234) re-merged onto the renderer's current tip (#236) —
  last done at #231, now two slices stale; no branch for this exists in
  `origin` yet.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's own queued item) — not yet a branch or PR.
- Codex-app-closed sessions moved (carried, not addressed by any PR in this
  window).
- Cursor login (carried, not addressed by any PR in this window).
- The `nrf` regression at 144 dpi (#236, §3 above) — named, not explained
  beyond "the old rounding happened to serve its faces better"; no
  mechanism-level explanation offered yet.
