# Claude research / desktop vs the five completion cards

Read-only audit. No product code was changed. Nothing was merged to
`main`. Codex local tips were ignored unless they appear on GitHub.

**Date:** 2026-09-06  
**Auditor checkout:** `main` at `a635289dd054341b882c8e8b3c262a7f538efa5f`
(last merged PR #149, 2026-08-13). All research lives on unmerged
`claude/*` stacks.  
**GitHub author on every open Claude PR:** `pantagram1031`. Attribution to
Claude is by `claude/*` branch names and PR bodies (Opus / Sonnet / Fable
workers), not a bot login.  
**Codex on GitHub:** no open epoch-integration PR. The only open
`codex`-named PR is #191 (`docs/codex-preview-regression`), renderer-score
docs. Ignore any local Codex tip.

PASS on any card requires the same **install-candidate** evidence: a
hashed Windows install, not a renderer IoU, not a mock, not a probe.

| Card | What PASS requires |
| --- | --- |
| 1 export safety | Existing bytes preserved; fail / crash / receipt regressions |
| 2 draft-fence FE | Stale async must not clobber the latest draft |
| 3 run-scoped edit | Edit one plain-text run (including wrapped lines); selected run only in multi-run paragraphs; source-map revision / run / UTF-16 |
| 4 Korean mixed E2E | Real install; mixed formatting, long paragraphs, tables; edit → undo/redo → AI review → save → reopen. Not renderer score / mock-only |
| 5 install hash | Exact source / EXE / sidecar / installer hashes verified **outside** the checkout |

**Verdict in one line:** recent Claude motion (#301–#328 plus the
desktop rematch conveyor) is almost entirely renderer-score research and
tip thrash. It does not close cards 1–5. The last product desktop
increment is still #221 (`0211c1888ad5`, `desktop/src` frozen at
`bf80c73c3383` on 2026-09-05). The only recent PR that names cards 2 and
3 with executable counterexamples is #254, and it ships no fix.

---

## 1. Inventory

### 1.1 `main` vs the stacks

| Line | Tip PR | Head SHA (12) | Full SHA | Commits ahead of `main` | Merge status |
| --- | ---: | --- | --- | ---: | --- |
| `main` | #149 | `a635289dd054` | `a635289dd054341b882c8e8b3c262a7f538efa5f` | 0 | merged 2026-08-13 |
| Renderer | #323 (`claude/engine-e2-converge-13`); #328 already stacked on it | `eda8f60a7f94` / `af99732ca159` | `eda8f60a7f94083e3c587fc0dab2645debca8e83` / `af99732ca15903b20c049eda9ecec4465d0daa75` | ~205 on #323 | all draft, unmerged |
| Desktop rematch tip | #326 (`claude/desktop-on-renderer-323`) | `43347d74007f` | `43347d74007f3b51cc33146463af09209f2b4275` | 300 | draft, unmerged |
| Last desktop **product** commit | inside #221 | `bf80c73c3383` | `bf80c73c3383a49eccf248fd0fb5561bebf85e0a` | — | draft; `desktop/src` identical on #221 and #326 |
| Writer | #177 → #180 → #189 → #224; note #239 | `17313f260d7e` … `71e23695a36d` | see §2 | 21 on writer line | draft, unmerged |
| Revision probe | #254 | `9464fbd76891` | `9464fbd768914d7b1a452b77f02cb44052103c0a` | 1 commit on desktop #248 | draft, no fix |

Open PRs on 2026-09-06: **179**, all draft, all created in the last two
weeks of stacked research. Zero of them target `main` except the early
roots (#150–#152, #160, #166, #171, #177). Nothing from this stack has
merged since #149.

### 1.2 Open / draft PRs clearly attributable to Claude research or desktop

Grouped. Every row is `OPEN` + `isDraft=true` unless noted. Author:
`pantagram1031`.

**A. Desktop rematch conveyor (no `desktop/` files in the diff)**

| PR | Title | Base → head | Head SHA |
| ---: | --- | --- | --- |
| 248 | desktop: re-merge onto the renderer tip #245 | `claude/desktop-renderer-230` → `claude/desktop-on-renderer-245` | `8a56ada79391` |
| 262 | desktop: re-merge onto the renderer tip #261 | `…-245` → `…-261` | `af9669e76e99` |
| 266 | desktop: re-merge onto the renderer tip #265 | `…-261` → `…-265` | `38fa3f0ed7e4` |
| 271 | desktop: re-merge onto the renderer tip #268 | `…-265` → `…-268` | `5eb8e38a9183` |
| 284 | desktop: re-merge onto the renderer tip #281 | `…-268` → `…-281` | `50441a1d1020` |
| 287 | desktop: re-merge onto the renderer tip #286 | `…-281` → `…-286` | `8a0bd69a67c4` |
| 293 | desktop: re-merge onto the renderer tip #290 | `…-286` → `…-290` | `1be4e186e14f` |
| 298 | desktop: re-merge onto the renderer tip #294 | `…-290` → `…-294` | `16b31b7df58b` |
| 300 | desktop: re-merge onto the renderer tip #299 | `…-294` → `…-299` | `2ea2e0c812b9` |
| 305 | desktop: re-merge onto the renderer tip #303 | `…-299` → `…-303` | `313f07c468de` |
| 310 | desktop: re-merge onto the renderer tip #308 | `…-303` → `…-308` | `2abf2ee916dd` |
| 318 | desktop: re-merge onto the renderer tip #314 | `…-308` → `…-314` | `b451cb603f92` |
| 326 | desktop: re-merge onto the renderer tip #323 | `…-314` → `…-323` | `43347d74007f` |

Thirteen rematches, **+53,868 lines claimed**, **zero paths under
`desktop/`**. Confirmed by `gh pr view` file lists for #248, #262, #266,
#271, #284, #287, #293, #298, #300, #305, #310, #318, #326, and by
`git diff --stat` `#221` vs `#326` on `desktop/src` and
`desktop/src-tauri`: empty.

**B. Renderer research + converge + probes, last ~2 weeks (#301–#328)**

| PR | Title | Base → head | Base SHA | Head SHA | +/− | files |
| ---: | --- | --- | --- | --- | ---: | ---: |
| 301 | own_render: 96-HWPUNIT right-edge tolerance | standin-rule → right-edge | `0f96b71728` | `fd551ee295` | +1585/−5 | 5 |
| 302 | docs: checkpoint 21 | checkpoint-20 → 21 | `7a6b458de8` | `5c448f78c9` | +591/−0 | 1 |
| 303 | converge #301 onto #299 | converge-09 → 10 | `a75c330733` | `55e878f68b` | +1585/−5 | 5 |
| 304 | class_b_probe: table-origin blind spot | right-edge → table-origin | `fd551ee295` | `56c35bb65c` | +877/−17 | 3 |
| 305 | desktop rematch #303 | see table A | `2ea2e0c812` | `313f07c468` | +1585/−5 | 5 |
| 306 | page-top space-before seat | table-origin → page-top-margin | `56c35bb65c` | `831ee520ce` | +969/−10 | 5 |
| 307 | trailing 자간 / re-derive window | converge-10 → installed-residual | `55e878f68b` | `c501dadfd9` | +513/−46 | 6 |
| 308 | merge #304+#306+#307 | converge-10 → 11 | `55e878f68b` | `b6f494d105` | +2354/−69 | 8 |
| 309 | docs: checkpoint 22 | checkpoint-21 → 22 | `5c448f78c9` | `7e3d05fcd2` | +598/−0 | 1 |
| 310 | desktop rematch #308 | see table A | `313f07c468` | `2abf2ee916` | +2354/−69 | 8 |
| 311 | table_row_heights remainder (no rule ships) | converge-11 → row-height-remainder | `b6f494d105` | `96b62eb261` | +843/−3 | 3 |
| 312 | empty_paragraph remainder is a page foot | converge-11 → empty-remainder | `b6f494d105` | `914b4e2c8a` | +708/−3 | 4 |
| 313 | three over-broken cells; neither term ships | row-height-remainder → cell-rebreak | `96b62eb261` | `9133359dda` | +984/−0 | 3 |
| 314 | merge #311+#313+#312 | converge-11 → 12 | `b6f494d105` | `7a654bf859` | +2534/−6 | 8 |
| 315 | docs: checkpoint 23 | checkpoint-22 → 23 | `7e3d05fcd2` | `2ed11878c2` | +774/−0 | 1 |
| 316 | 13 syllable regressions; nothing ships | cell-rebreak → syllable-13 | `9133359dda` | `5c1e49d28d` | +1167/−0 | 3 |
| 317 | text_line_height = dropped hp:lineBreak | converge-12 → line-height-remainder | `7a654bf859` | `dee9a2b3fc` | +1040/−5 | 3 |
| 318 | desktop rematch #314 | see table A | `2abf2ee916` | `b451cb603f` | +2586/−14 | 11 |
| 319 | SeatingRenderer.table_index setter | line-height-remainder → seating-setter | `dee9a2b3fc` | `b67c3aed37` | +35/−8 | 3 |
| 320 | eleven stand-in face (휴먼명조) | syllable-13 → standin-11 | `5c1e49d28d` | `05c9dd2d69` | +3485/−6 | 6 |
| 321 | kstartup table 36 vertOffset; nothing ships | seating-setter → wrap-36 | `b67c3aed37` | `be826d9be3` | +235/−0 | 1 |
| 322 | Korean break unit is the syllable | standin-11 → syllable-switch | `05c9dd2d69` | `2199bf96b5` | +483/−55 | 5 |
| 323 | merge #321+#322 | converge-12 → 13 | `7a654bf859` | `eda8f60a7f` | +6435/−64 | 14 |
| 324 | docs: checkpoint 24 | checkpoint-23 → 24 | `2ed11878c2` | `5ef75716a0` | +874/−0 | 1 |
| 325 | hp:lineBreak ends the line | syllable-switch → line-break-control | `2199bf96b5` | `b4721fa4c1` | +339/−5 | 3 |
| 326 | desktop rematch #323 | see table A | `b451cb603f` | `43347d7400` | +6400/−56 | 13 |
| 327 | split-table continuation outer margin | line-break-control → page-top-3 | `b4721fa4c1` | `aa4f10c132` | +145/−1 | 3 |
| 328 | HFT table never read a paragraph inside a table | converge-13 → hft-digits | `eda8f60a7f` | `af99732ca1` | +4391/−252 | 8 |

#301–#328 together: **+46,469 / −704** across 28 draft PRs, created
2026-09-06 (same calendar day as this audit for #301 onward).

**C. Product desktop line (real `desktop/` work; older than the rematch
flood, still open)**

| PR | Title | Head | Notes |
| ---: | --- | --- | --- |
| 150 | docs: product direction and desktop wedge | `docs/product-direction-desktop` | roots on `main` |
| 151 | Studio audit / desktop spike plan | `claude/desktop-audit` | |
| 156 | Tauri 2 shell spike | `claude/desktop-shell-spike` | |
| 159 | Phase 3 read-only foundation | `claude/desktop-foundation` | |
| 161 | visual identity | `claude/desktop-design` | |
| 164 | Phase 4 verified editing | `claude/desktop-editing` | |
| 167 | Phase 5 composer | `claude/desktop-phase5` | |
| 169 | overlay | `claude/desktop-overlay` | |
| 172 | Phase 6 seat + pack | `claude/desktop-phase6` | |
| 175 | caret | `claude/desktop-e1-caret` | |
| 176 | CI desktop gate | `claude/e5-ci-desktop-gate` `cb89cb4417ec` | CI, not install-hash |
| 184 | undo two tiers | `claude/desktop-e1-undo` | needed later for card 4 |
| 214 | own-render when no Hancom PDF | `claude/desktop-own-render` | |
| 217 | converged renderer + fallback faces in sidecar | `claude/desktop-own-render-converged` | |
| 221 | seats, caret, chooser on own page | `0211c1888ad5` | **last product increment** |
| 234 | rematch screenshots onto renderer #231 | `3ddc32a0e3fc` | docs/shots, not FE |

**D. Writer / export-adjacent (separate stack, not the rematch tip’s
job)**

| PR | Title | Head SHA |
| ---: | --- | --- |
| 177 | canonical OWPML writer | `17313f260d7e` (base `main` `a635289dd054`) |
| 180 | one writer for every emitted HWPX | `a346083ca529` |
| 189 | Hancom acceptance harness (live leg owed) | `b8a87e1f5f53` |
| 224 | section-head control order lint | `71e23695a36d` |
| 239 | Hancom recomputes lineseg on save (docs only) | `b4553c544d18` |

`engine/scripts/hwpx_write.py` exists on the desktop rematch tip and
does **not** exist on `main`.

**E. The two PRs that actually speak the card language**

| PR | Title | Head SHA |
| ---: | --- | --- |
| 253 | LayoutSnapshot contract proposal (docs only) | `8d8b663607b9` |
| 254 | expose cross-revision edit targets and stale public-click effects | `9464fbd76891` |

**F. Docs checkpoints (1 file each, #188–#324 chain)**

#188, #195, #201, #212, #220, #225, #229, #235, #241, #246, #251, #259,
#264, #269, #274, #282, #289, #296, #302, #309, #315, #324 — twenty-four
checkpoint PRs. Plus #171 (endgame plan), #186 (feature catalog), #191
(Codex preview regression), #193/#197 (fit/residual notes), #199
(holdout), #207 (H2Orestart vs own), #253 (LayoutSnapshot).

**G. Runtime / agenthost (desktop dependencies, not last-two-weeks
research)**

#152–#155, #157–#158, #162–#163, #165, #168, #170, #174, #178, #181,
#182, #185, #204 — Runtime Protocol, seats, workspace session, streaming.
Necessary substrate for cards 2–4, already built; not what the last two
weeks spent tokens on.

### 1.3 Branches

~200 `claude/*` heads plus `docs/checkpoint-*`, `docs/research-*`,
`review/revision-coherence-20260905`. No `codex/*` or `epoch*` branch
is open. The desktop rematch series is `claude/desktop-on-renderer-{245,
261, 265, 268, 281, 286, 290, 294, 299, 303, 308, 314, 323}`. The
renderer converge series is `claude/engine-e2-converge` through
`converge-13`.

---

## 2. Judgments (material PRs, last ~2 weeks)

### Desktop rematches #248…#326 (especially #318, #326)

These PRs exist to keep a desktop branch SHA moving with the renderer
tip. Their file lists are `engine/scripts/*_probe.py`,
`engine/scripts/own_render.py`, `engine/references/own-render-notes.md`,
`engine/tests/test_*`, and (later) `docs/research/hangul-syllable-breaking.md`
/ `hft-widths.measured.json`. None of them touch `desktop/src`,
`desktop/src-tauri`, export, draft state, or an installer. Checkpoint 24
still records that `desktop/sidecar/build.ps1` was **not** updated to
ship the new HFT / stand-in JSON — so even the one desktop-adjacent
follow-through is unowned. Relative to cards 1–5 this is tip thrash:
it creates the impression of a moving “product tip” while the last
`desktop/src` commit remains `bf80c73c3383` (2026-09-05 02:27 +0900).
**STOP.** One frozen desktop SHA is enough.

### Renderer score slices #301, #306, #307, #312, #320, #322, #325, #327, #328

These change `own_render.py` or its measured tables to lift cache/computed
IoU and shrink “class B” layout divergence. Checkpoint 24 quotes computed
IoU **0.706026 → 0.728976** and cache IoU **0.736589 → 0.743520** on #323.
Card 4 forbids treating that as E2E evidence. Card 3 needs a source-map
(revision / run / UTF-16) and the ability to edit one run, including
wrapped lines and a selected run in a multi-run paragraph. The shipping
desktop still **refuses** those cases (`CaretRefusal = "multi_run" |
"run_text_differs"` in `desktop/src/actions.ts` on the current tip).
Syllable breaking (#322) and `hp:lineBreak` (#325) improve how the
research renderer wraps Korean; they do not address a run. #301’s
96-HWPUNIT error budget is an explicit open reviewer decision, not a
Hancom rule. #321’s “export ignores the wrap” is Hancom’s kstartup
`vertOffset`, not Rigorloom export safety. **STOP** as a path to the
cards; **PARK** #323 as a frozen research snapshot if the renderer must
be kept at all.

### Probe-only / “nothing ships” #304, #311, #313, #316, #317, #321

Own titles and bodies say the slice diagnoses a remainder and does not
ship a renderer term (`own_render.py` untouched, or notes-only). They
feed the next converge and the next rematch. Useful as lab notes;
zero install-candidate evidence. **STOP** new ones; **PARK** the
existing notes on the frozen tip.

### Converge PRs #303, #308, #314, #323 and integration patch #319

Mechanical merges so the rematch conveyor has a single SHA. #319 exists
because rematch #318 crashed `SeatingRenderer.table_index` on a probe
test — a collision created by the conveyor, then “fixed” so the conveyor
could continue. **STOP.**

### Checkpoints #302, #309, #315, #324 (and the 20 before them)

One markdown file each, restating IoU tables and naming the next
remainder. Checkpoint 24 is honest that most slices shipped nothing,
that the 96-unit budget is still an open product call, and that the
sidecar line is still unowned. Writing another checkpoint does not
close a card. **PARK** the existing series; **STOP** #25.

### #254 `review/revision-coherence-20260905` (`9464fbd76891`)

This is the only recent PR that states the card-2 / card-3 failure
mode in executable form. Findings, still true on today’s desktop tip
(`beginParagraphEdit` still calls `rt.readRegion(sessionId, [{ atPara }])`
with no `runId`, `claude/desktop-on-renderer-323:desktop/src/actions.ts`
around the helper at line 461):

1. Geometry for `run_id=…` maps the candidate page against the
   **source** profile, so an edit can uniquely attach to the wrong
   paragraph.
2. The next caret read repeats the source and ignores `answer.subject`,
   so a wrong unique map is corroborated.
3. A helper-only stale guard is insufficient: `clickOverlaySpan`
   writes an old overlay/selection after a superseded async reply.
   Two clicks completing in reverse order clobber the latest intent.

The probe’s last intervention (public-effect / latest-intent guard)
takes 21/21 cases. The PR **does not patch production**. It is
diagnosis for cards 2 and 3, not completion. **KEEP** the evidence;
implement the fence and the revision-scoped read on the frozen
desktop SHA. Do not wait for another rematch.

### #253 LayoutSnapshot proposal (`8d8b663607b9`)

Docs-only contract for renderer ↔ product (revision digest, geometry
schema, font manifest). Adjacent to the source-map card 3 needs, but
it is a glossary and a proposal, and it says so. Implementing a second
snapshot object before run-scoped `set_run` + UTF-16 addressing is
premature polish. **PARK.**

### #221 / #184 / #177 (older, still the product)

#221 is the last change to how a human edits a page this repo drew.
#184 is the undo/redo substrate card 4 will need. #177–#224 is the
writer that any export-safety test must sit on. None of these close
the cards today: #221 still refuses multi-run and wrapped-line edits;
export hashes a copied candidate (`desktop/src-tauri/src/digest.rs`,
`export_candidate`) but there is no published fail/crash/receipt
matrix on a real install; there is no outside-checkout hash of
EXE/sidecar/installer. **KEEP** these as the product line. Do not
rematch them again until a card moves.

---

## 3. File churn that does not move the cards

| Churn | Evidence | Why it misses 1–5 |
| --- | --- | --- |
| Desktop rematch conveyor | 13 PRs, +53,868 lines, **0** `desktop/` paths | Product FE/export/installer untouched |
| Parallel renderer experiments + converge | e.g. #311/#312/#313 → #314; #316/#317/#320/#321/#322 → #323 | Duplicate tips; merge commits exist to enable the next rematch |
| Probe script farm | 15 `*_probe.py` / divergence / width-table scripts on #323 vs a handful on `main` | Lab instrumentation, not install tests |
| Research markdown | `docs/research` **20 files on `main` → 81 on desktop tip**; 24 checkpoint PRs | Scoreboard prose |
| `own-render-notes.md` append-only | touched by almost every engine PR in #301–#328 | Same remainder diary rewritten each slice |
| HFT / stand-in JSON growth | `hft-widths.measured.json` +2599 in #326; #320 adds `standin_faces` | Sidecar `build.ps1` still does not ship the file (checkpoint 24) |
| `desktop/src` freeze | last commit `bf80c73c3383`; diff #221…#326 on `desktop/src` + `src-tauri` is empty | Cards 2–4 are FE/runtime/install work |
| Error-budget / remainder loops | #301 budget still an open call after #307/#316/#322 | Tuning a research constant is not a card |
| #319 table_index setter | +35/−8 to unblock rematch #318 probe tests | Self-inflicted integration scar |

`main` still has 20 engine scripts and 36 engine tests. Renderer tip
#323 has 40 scripts and 52 tests. The added files are probes and
raster pins, not export-safety, draft-fence, run-map, or installer
hash tests.

---

## 4. Verdict table

Legend: **KEEP** = use this SHA / implement from it.
**PARK** = freeze; do not extend. **STOP** = no further work on this
line until a card has install-candidate evidence.

| PR / branch | Helps which card(s) | Risk | Recommend |
| --- | --- | --- | --- |
| #254 `review/revision-coherence-20260905` `9464fbd76891` | **2** (names the clobber); **3** (wrong revision / wrong para) | none — diagnosis only | **KEEP** (implement; do not rematch first) |
| #221 `claude/desktop-own-render-edit` `0211c1888ad5` / `bf80c73c3383` | substrate for **2–4** (caret, `set_run`, smoke) | low — already refuses the hard cases | **KEEP** as product tip |
| #184 `claude/desktop-e1-undo` | substrate for **4** undo/redo | low | **KEEP** (already under #221) |
| #177–#224 writer stack | substrate for **1** | med — writer completeness ≠ fail-safe export | **PARK** until export-safety tests exist |
| #176 `claude/e5-ci-desktop-gate` | none of 1–5 (CI in-repo) | low | **PARK** |
| #253 LayoutSnapshot | maybe later **3** | med — extra abstraction | **PARK** |
| #234 screenshot rematch | none | low | **PARK** |
| #239 lineseg-on-save note | none (Hancom save behavior) | low | **PARK** |
| #318 desktop rematch `b451cb603f` | none (0 desktop files) | high over-eng | **STOP** |
| #326 desktop rematch `43347d7400` | none | high over-eng | **STOP** (do not treat as product tip) |
| #248–#310 rematch series | none | high over-eng | **STOP** |
| #323 renderer tip `eda8f60a7f` | none of 1–5 (IoU) | med | **PARK** one SHA; stop stacking |
| #322 syllable switch | none (renderer wrap, not run edit) | med | **PARK** inside #323 |
| #320 / #328 HFT / stand-in tables | none | med | **PARK** |
| #301 / #307 right-edge budget | none | high over-eng | **STOP** |
| #304 #311 #313 #316 #317 #321 probes | none | med | **STOP** new probes |
| #303 #308 #314 #323 converges | none | high over-eng | **STOP** |
| #319 seating setter | none | low | **STOP** |
| #312 #306 #325 #327 layout rules | none | med | **PARK** inside #323 |
| #302 #309 #315 #324 checkpoints | none | med | **STOP** further checkpoints |
| #191 Codex preview docs | none | low | **PARK** / ignore |
| Codex local / epoch tip | **not on GitHub** | — | **ignore** (per brief) |
| `main` `a635289dd054` | none of the five (report pipeline) | — | do not merge the stack |

Card coverage after this map: **1 none, 2 diagnosed / unfixed, 3
diagnosed / still refused, 4 no real-install loop, 5 absent.**

---

## 5. Top 5 next actions (close cards, cut sprawl)

1. **Freeze the conveyor.** Declare `bf80c73c3383` (desktop product)
   and optionally `eda8f60a7f` (#323 renderer) as parked SHAs. Close
   or abandon further rematch / converge / checkpoint / probe PRs
   (#326+, #328+, #324+). Do not open #329 to rematch #328 onto
   desktop. This is the highest-leverage stop.

2. **Implement #254 on the frozen desktop SHA — card 2, then the
   addressing half of card 3.** Route geometry and `readRegion` at
   the candidate revision; discard superseded `clickOverlaySpan`
   effects; bind the in-flight request id so a stale async cannot
   write `inlineEdit` / overlay / selection. Promote the #254
   21-case probe from “in-memory intervention” to a real checkout
   test. That is the draft-fence. Do not wait for Codex quota to
   write another design doc.

3. **Ship run-scoped `set_run` with a source-map (revision, run,
   UTF-16) — card 3.** Stop refusing `multi_run` and
   `run_text_differs`. Click must name one run, including a run
   that wraps onto two visual lines, and must not edit sibling runs
   in the same paragraph. #253 can stay a parked glossary; do not
   implement LayoutSnapshot first.

4. **Write the export-safety install-candidate matrix on the writer
   + `export_candidate` path — card 1.** Cases: mid-write crash,
   disk-full / refuse, receipt hash mismatch, original path bytes
   unchanged, copied destination hashed and compared. This is
   `hwpx_write.py` + `desktop/src-tauri` `export_candidate` /
   `digest.rs`, not another `class_b_probe`. #177 is the base, not
   the finish line.

5. **Hash a real Windows install outside the checkout, then run one
   Korean mixed E2E on that install — cards 5 then 4.** Record
   source / EXE / sidecar / installer SHA-256 from a machine that
   is not the agent worktree (checkpoint 24’s missing
   `hft-widths.measured.json` sidecar line is a symptom that even
   in-tree bundling is unowned). On that hashed install: mixed
   formatting, a long paragraph, a table; edit → undo/redo → AI
   review → save → reopen. Do not accept cache SSIM / computed IoU
   / `layout_divergence` as a substitute.

---

## Evidence appendix

- Open PR count: `gh pr list --state open` → 179 drafts.
- `main` last merge: #149 `a635289dd054341b882c8e8b3c262a7f538efa5f`.
- Desktop rematch file lists: `gh pr view {248,262,266,271,284,287,293,298,300,305,310,318,326} --json files`.
- Product freeze: `git log origin/claude/desktop-on-renderer-323 -1 -- desktop/src` → `bf80c73c3383` 2026-09-05; `git diff --stat` vs `claude/desktop-own-render-edit` on `desktop/src` + `desktop/src-tauri` empty.
- Still-broken fence: `beginParagraphEdit` → `rt.readRegion(sessionId, [{ atPara }])` without `runId` on `origin/claude/desktop-on-renderer-323:desktop/src/actions.ts`.
- #254 findings: `docs/research/revision-coherence-01.md` at `9464fbd76891`.
- Checkpoint 24 self-report: `docs/research/checkpoint-24.md` at `5ef75716a04a` (IoU table; “nothing shipped”; sidecar line unowned; 96-unit budget still open).
- Probe farm: 15 probe/divergence/width scripts under `engine/scripts` on #323.
- Research doc count: 20 on `main`, 81 on desktop tip.
- No Codex epoch PR: `gh pr list` headRefName `codex|epoch` → only #191 docs.
- Writer absent on `main`: `engine/scripts/hwpx_write.py` missing at `origin/main`; present on desktop tip.
