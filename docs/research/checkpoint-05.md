# Checkpoint 05 — the converged renderer, in the app

Non-merging checkpoint. Written from `claude/engine-e2-converge` (this
branch, `docs/checkpoint-05`, is cut from that tip and stays unmerged).
Covers PR #213 (the inline-table move rule — an anchored `CELL` table
splits at a row boundary, an inline table never does; it moves whole),
#214 (desktop own-render: a fresh install now shows a real page instead
of a refusal card, tier-3 `own-uncertified`, plus a usable one-band
toolbar and zoom), and #215 (convergence: registration + fonts + the
table rule re-measured together for the first time — render-check
1/35/13/2, holdout tracker 02 `ssim_inked` 0.1295 → 0.1731, line IoU
0.5389 → 0.5847, `ssim_inked_min` crosses zero). Checkpoint-04
(`docs/checkpoint-04`, off #211) carries forward as the record of the
renderer line's fork at #203 and the state before this window.

**Operating constraints this window, stated honestly:** Opus session
caps and 529 errors interrupted three slices in this period — each was
either finished by a Sonnet agent or resumed rather than lost (#215's
own body: "Opus session cap hit after the final commit; nothing left
unfinished on the branch"; #205/#206/#208 each name background runs
"killed" by a co-resident process on the bench). Full-suite gates are
deferred on every PR from #205 through #215 for the same recurring
reason — bench disk sitting at 0.1–6 GB during renders (#215: 1.9–3.6 GB)
— and none of those PRs records the deferred run being appended since.
That backlog is carried here, not resolved.

## What changed since checkpoint-04

| metric | checkpoint-04 | checkpoint-05 | moved in |
|---|---|---|---|
| renderer-line shape | forked at #203 into three siblings (#208, #209→#211, #210); #211 the deepest single head | **converged**: #208 + #211 (carrying #209) + #213 (carrying #210) merged by intent into one tree; **#215 is the new authoritative tip** — #208, #209→#211, #210→#213 are subsumed | #215 |
| table-move rule (F47) | open, ranked backlog item #1 (table split in place vs Hancom's whole-table move) | **found and fixed**: only an anchored (`treatAsChar="0"`) `CELL` table may split at a row boundary; an inline table moves whole and overflows off the sheet if the next page is still too short. Eleven probes + three Hancom-authored controls, zero exceptions | #213 |
| render-check tally (51 features) | 1 match · 32 close · 16 differs · 2 unsupported | **1 · 35 · 13 · 2** — F47 (table-move, IoU 0.025→0.535), F31 and F32 (table borders/cell-valign, registration inset acting alongside the table fix) all cross into `close` | #213, #215 |
| holdout tracker (private, aggregate only) | tracker 01: `ssim_inked_mean` 0.1295, `text_line_iou_mean` 0.5389, `ssim_inked_min` −0.0405 | **tracker 02**: `ssim_inked_mean` **0.1731**, `text_line_iou_mean` **0.5847**, `ssim_inked_min` **+0.0273** — no page is anti-correlated with Hancom's ink any more; page count 18/18 exact, unchanged | #215 |
| corpus scoreboard means (pinned by #211, re-measured with fonts + table-move present) | ssim 0.8250, ssim_inked 0.2551, line IoU 0.6423 | **ssim 0.8266, ssim_inked 0.2579, line IoU 0.6447** — the five forms whose declared faces all resolve installed are byte-identical to #211; no corpus page count moves | #215 |
| desktop line | tip #184; own-render referenced as work in progress, not yet a pushed branch | **#214 pushed and merged**: a fresh install renders via `own_render` (tier 3) behind the honest envelope (`grade: own-uncertified`, never claims `hancom`), a 자체 렌더 · 미인증 badge, real overlay line boxes from the sidecar; plus a usable one-band toolbar and page/app zoom | #214 |
| desktop ↔ renderer coupling | not yet dependent — desktop had no own-renderer code path | **#214 renders with the #203-tip renderer** (pre-#211/#208/#213); its own PR body states it "should re-merge #215" — **named here as the pending integration**, not yet attempted | #214 |
| gap 34 (new) | — | own-render geometry gives line boxes but **no addresses/seats/caret** — the sidecar carries positions, not text; an engine-side fix is sketched, not built | #214 |
| render-check page count (synthetic document only) | 10 (reference 9) | **11** (reference unchanged at 9) — moving the table whole removed the term that used to cancel the pre-existing block-height drift; a stated, not hidden, regression | #213 |
| integration conflicts checkpoint-04 forecast | `own_render.py` three-way, `hwpx_write.py` cross-line, `manifest.json` two-way, `own-render-notes.md` five-way — all *expected*, none yet attempted | **all four resolved** in #215, mechanically as forecast: "`own_render.py` keeps all three behaviours; notes keep every section; tests are the union" | #215 |

## 1. Branch DAG

Renderer line, forked at #203 (unchanged from checkpoint-04), now
**converges at #215**:

| PR | branch | base | slice |
|---|---|---|---|
| #208 | `claude/engine-e2-bundled-fonts` | `engine-e2-refs-1to1` | E2.2 bundled OFL fonts (sibling A) — subsumed |
| #209 | `claude/engine-e2-borders-rows` | `engine-e2-refs-1to1` | dashed borders, cache-split paging (sibling B) |
| #211 | `claude/engine-e2-registration` | `engine-e2-borders-rows` | `hp:outMargin` registration, stacked on B — subsumed |
| #210 | `claude/engine-render-check-doc` | `engine-e2-refs-1to1` | render-check document (sibling C) |
| #213 | `claude/engine-e2-table-move` | `engine-render-check-doc` | F47 rule, stacked on C — subsumed |
| **#215** | `claude/engine-e2-converge` | `engine-e2-registration` | **merge of #208 + #211 (carrying #209) + #213 (carrying #210) — new tip** |

`#215`'s own body states the merge is "by intent," not a mechanical
`git merge` this checkpoint re-verified byte-for-byte; every corpus and
render-check number it pins was re-measured on the merged tree rather
than assumed from the three inputs (see section 2).

Sibling docs branch, unchanged position:

| PR | branch | base | note |
|---|---|---|---|
| #212 | `docs/checkpoint-04` | `engine-e2-registration` | prior checkpoint (this doc's predecessor) |
| #207 | `docs/research-h2orestart-vs-own` | `engine-e2-refs-1to1` | H2Orestart comparison, unmoved this window |

### Writer / Runtime / Desktop lines

**Writer line**, unmoved this window: #177 → #180 → #189. No PR in
#211–#215 touches it.

**Runtime line**, unmoved this window: … → #185 → #204. No PR in
#211–#215 touches it.

**Desktop line**, moved this window: … → #184 → **#214**
(`claude/desktop-own-render`, base `claude/desktop-e1-undo`). #214's own
body: "Depends on: #184 (desktop line) + #203 (renderer line, merged
in). Renders with the #203 renderer — the convergence branch
(registration, fonts, table rule) lands next and should be re-merged
here." **This is the pending integration** carried out of this
checkpoint unresolved — #214 is the desktop line's verified tip, but it
does not yet draw with #215's renderer.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #213 — the table-move rule (F47)

Eleven probe tables plus three Hancom-authored controls, zero
exceptions: a table splits at a row boundary only when it is anchored
(`hp:pos@treatAsChar="0"`) *and* declares `CELL`; an inline
(글자처럼 취급) table never splits — it moves whole, and if a whole page
is still too short it draws from the top and overflows off the sheet.
F47 declared `CELL repeatHeader=1` but was `treatAsChar="1"`; that was
the whole answer. Two faults fixed on the way: `_row_extent`'s 0.85 ×
baseline test let 15% of a table hang past the page margin (a table has
no descender); the inline splitter is deleted outright — the anchored
splitter is the only one, and both its cuts now honour
`hp:tbl@repeatHeader`.

Render-check: F47 `differs` → `close`, IoU 0.025 → **0.535**; tally 32/16
→ **33 close / 15 differs**; every other feature unchanged to the digit.
Corpus flow agreement byte-identical on all ten forms. Probe document
renders 23 pages matching Hancom page-for-page, deterministic. **Honest
regression:** render-check page count 10 → 11 (reference 9) — the extra
page and the previously-unmoved table used to cancel; the residual is
the pre-existing cumulative block-height drift. Not proven: one Hancom
build, A4 portrait single column; anchored TABLE/NONE unmeasured;
rowSpan across a cut, nested tables, a single row taller than a page.
Evidence: engine/tests 1184 passed (both new tests fail on the pre-fix
renderer); `py_compile_sweep` 105/0; archive privacy gate HARD=0.
Full-suite gate deferred (thin disk).

### #214 — desktop own-render, plus a usable band and zoom

`document/render` falls back to `own_render` (tier 3) behind the
existing honest envelope — `grade: own-uncertified`, `source.kind:
own_render`, cached and bound to the subject digest, never claiming
`hancom`. The page carries a 자체 렌더 · 미인증 badge, a
무엇을 못 그렸나 list printed verbatim from the sidecar, and a
font-substitution row. Overlays work from the sidecar's line boxes
(`geometrySource: "own"`): real rects, no invented addresses, and a
click states that limit rather than doing nothing. Usable UI: one band —
열기 · 저장/내보내기 · 되돌리기 · 검사 · 승인 — the rest behind
disclosures; page zoom gains 폭 맞춤/쪽 맞춤; app zoom (Ctrl+=/−/0) lives
in a 화면 menu and persists; type up one step, 30 px hit targets.

Defects the evidence found, fixed in the same PR: `--hidden-import PIL`
missed `ImageDraw`/`ImageFont` (bundle present, tier dead);
`render_capability` ignored the engine root, so a frozen build would
have advertised `own.state: "no"`; the overlay's unmapped-draws-nothing
rule had erased all 30 line boxes; two build-script fixes (stderr as
terminating error; one-dir bootloader child orphaning build trees). Not
proven: no tier-1 page exists on this machine (`needs_hancom` in the
packaged sidecar), so the 한컴 렌더 badge has never been photographed;
own-render geometry gives line boxes but no addresses/seats/caret yet
(**gap 34** — the sidecar carries positions, not text; engine-side fix
sketched). Evidence: `tsc` 0; sidecar 0 (two new tier-3 role checks);
`tauri build` 0; **smoke 499/0 across 14 phases** (new: `own` 40,
`own-reattach` 3); runtime suites + agenthost compile 457 passed;
`py_compile_sweep` 0; archive privacy gate HARD=0; orchestrator eyeballed
`page-own-render.png`.

### #215 — convergence: registration + fonts + the table rule, together

`own_render.py` keeps all three behaviours (#211's `hp:outMargin` inset,
#208's bundled OFL fonts, #213's table-move rule carrying #210's
render-check tooling); notes keep every section; tests are the union;
every pinned corpus number was re-measured on the merged tree.

**Render-check (51 features), measured together for the first time:**
1 match · 33 close · 15 differs · 2 unsupported → **1 · 35 · 13 · 2**.
Two more features (F31, F32) cross into `close` from registration and
fonts acting at once.

**Corpus scoreboard, merged tree:** ssim 0.8250 → **0.8266**, ssim_inked
0.2551 → **0.2579**, line IoU 0.6423 → **0.6447**, pair rate 0.8364
unchanged. Every form that moves is a form the bundled family map
answers for, moving by exactly the amount #208 measured pre-registration
— the two slices are additive, not interacting. No corpus page count
moves (kstartup stays 21/22, its pre-existing exception). The table-move
rule fires on zero public corpus forms.

**Holdout tracker 02 (private, aggregate only):** pages 18/18 exact;
ssim_inked_mean 0.1295 → **0.1731**; ssim_inked_min −0.0405 →
**+0.0273**; line IoU_mean 0.5389 → **0.5847**; pair rate 0.9041 →
0.9122. Registration (#211) accounts for essentially all of the gain —
the holdout's tables declare non-zero `hp:outMargin`; #208 is a measured
no-op (`bundled_character_share` 0.0, every declared face installed);
#210/#213 cause no repagination (no inline table on this document fails
to fit its remaining room).

**Evidence (orchestrator re-ran own_render + render_check + scoreboard
suites: 255 passed; eyeballed page 1 side-by-side):** merged engine
suite green per the agent; determinism; regression floor;
`py_compile_sweep`; archive privacy gate HARD=0. Full-suite gate deferred
(disk 1.9–3.6 GB during renders). **Opus session cap hit after the final
commit; nothing left unfinished on the branch.**

## 3. Regressions (with the PR's or commit's own explanation)

| PR | metric | moved | explanation given |
|---|---|---|---|
| #213 | render-check page count (synthetic document only) | 10 → 11 (reference 9) | "moving the table whole pushes its rows down instead of filling the room the split used" — the extra page and the previously-split table used to cancel; the residual is pre-existing cumulative block-height drift, not new |
| #215 | (no new scoreboard regression named) | corpus/holdout channels move only the right way | `nrf` text_line_iou stays down at 0.7059 (was 0.7225 pre-#208) — same direction and cause #208 already reported and did not smooth over; registration does not rescue it, carried not fixed |

No corpus form or public-corpus page count regressed across #213 or
#215; both PRs state this explicitly. #214 introduced no scoreboard
regression — its four defects (PIL hidden-import, `render_capability`
engine root, overlay erasing line boxes, two build-script bugs) were
found and fixed within the same PR, not left open.

## 4. Unsupported / declared elements still open

Carried from checkpoint-04, with items this checkpoint's PRs closed,
refined, or added:

- **Closed since checkpoint-04:** the table start/split policy (F47,
  ranked backlog item #1) — closed by #213, measured rule with no
  exception across 11 probes + 3 controls.
- **Partially closed:** table row-height compression (F27/F28/F31/F32,
  backlog item #2). checkpoint-04 already noted half of it was the
  `hp:outMargin` offset; on the converged tree **F31 and F32 now read
  `close`** (0.376, 0.479) — the registration inset plus the table-move
  fix acting together. **F27 and F28 still `differs`** — the genuine
  row-height-ignores-declared-floor residual is unmoved.
- **The render-check 13 `differs`, current state, with mechanism (the
  renderer queue):**
  - `F06`/`F07`/`F08` — line spacing 130/160/200% (PERCENT): applied,
    but drawn with the renderer's own line heights, so the block drifts.
    Backlog item #3, the line-metric gap.
  - `F13` — 자간 (`hh:spacing=-15`): over-condenses, glyphs collide
    where Hancom only tightens — reads like a unit mismatch in the
    1/100-em conversion.
  - `F14` — 장평 (`hh:ratio`), `F15` — 상대크기 (`hh:relSz`), `F16` —
    글자 위치 (`hh:offset`): all drawn, all displaced; same line-metric
    gap as F06–F08, not a missing feature.
  - `F17` — 진하게 (bold): page-boundary artefact, not a bold-drawing
    defect — Hancom pushes the content paragraph to the next page while
    the own renderer keeps it with its label (reference band 20 px vs
    77 px).
  - `F27` — 표 기본 격자 (plain 3×3 grid), `F28` — 셀 병합
    (colSpan 2 + rowSpan 2): row-height-floor residual (F27) plus the
    same page-boundary artefact as F17 (F28).
  - `F48` — 가로 용지 (landscape section): reference-side limit, not a
    renderer defect — Hancom's PDF export always emits 595×841 pt
    (portrait) regardless of the declared landscape section; cannot be
    improved from the renderer side.
  - `F49` — 다단 2단 구역 (two-column section): `hp:colPr` is applied
    from the head of the section; Hancom appears to require a column
    break or section restart first. The catalog lists 다단 as
    declared-skipped — contradicted by measurement, needs correcting.
  - `F50` — 머리말 (header): drawn, but centred against the page box
    rather than the `hp:subList`'s own declared `textWidth`, shifting it
    right. (`F51` 꼬리말, not in the 13, has the same displacement plus a
    genuine `unsupported` verdict for the `hp:autoNum` field inside it.)
- **New, from the desktop line (#214):** **gap 34** — own-render
  geometry carries line-box positions but no text/addresses, so a
  desktop page rendered via tier 3 has no seats and no caret; an
  engine-side fix is sketched, not built.
- **New, standing pending integration:** #214 renders with the #203-tip
  renderer, not #215's converged one — none of registration, fonts, or
  the table-move rule's fidelity gains are visible in the running app
  yet.
- **Still open, unchanged from checkpoint-04:** whole-document computed
  layout's page-count/line-IoU failure (#199, 21/18 pages, 0.180 line
  IoU) — no PR in this window touches it; the writer line's ~30
  default header/meta elements Hancom adds to a blank package on save —
  still no assigned slice; `hp:ole`/`hp:chart`/`hp:container`/shapes/
  undecodable EMF-WMF grey placeholders; only `DOUBLE_SLIM` draws two
  border strokes; text wrap around anchored objects; `hp:parameters`
  family unrendered; equations' declared-unsupported constructs
  unchanged.

## 5. Tests actually run per PR (from PR bodies)

| PR | orchestrator / engine suite | full suite | notes |
|---|---|---|---|
| #213 | engine/tests 1184 passed (2 new tests fail pre-fix) | deferred (thin disk) | `py_compile_sweep` 105/0; archive privacy HARD=0 |
| #214 | `tsc` 0; sidecar 0 (+2 new tier-3 checks); `tauri build` 0; **smoke 499/0** across 14 phases (new: `own` 40, `own-reattach` 3); runtime suites + agenthost compile 457 passed | not applicable (desktop build/smoke, not the engine full suite) | `py_compile_sweep` 0; archive privacy HARD=0; orchestrator eyeballed `page-own-render.png` |
| #215 | own_render + render_check + scoreboard suites 255 passed; merged engine suite green per the agent | deferred (disk 1.9–3.6 GB during renders) | determinism; regression floor; `py_compile_sweep`; archive privacy HARD=0; Opus session cap hit after the final commit, nothing left unfinished |

Full-suite gate deferral is now a five-PR-and-counting streak
(#205/#206/#208/#209/#210/#211/#213/#215 all cite thin disk or a
disk-during-renders window) with no appended run recorded in any of
those PR bodies as of this checkpoint. This is carried forward exactly
as checkpoint-04 flagged it, not resolved by this window.

## 6. Integration conflicts expected when lines converge

**Checkpoint-04's four forecast conflicts are now resolved**, and
mechanically as predicted:

- `engine/scripts/own_render.py` (the three-way #208/#209+#211/#210
  conflict) — resolved in #215 by keeping all three behaviours in one
  file.
- `engine/references/own-render-notes.md` (the five-way append conflict)
  — resolved by keeping every dated section; the file now carries a
  dedicated "E2 convergence" section recording the merge itself.
- `tests/corpus/forms/manifest.json` (#203 vs #210's two-way append) —
  resolved; not separately flagged as a problem in #215's body.
- `engine/scripts/hwpx_write.py` (the cross-line conflict against the
  writer line's own copy) — carried through #213 (which stacks on #210)
  into #215; not named as a residual problem in #215's body, so treated
  here as resolved, though no PR body states explicitly how it was
  reconciled against the writer line's current state.

**One new conflict, not yet attempted:** #214 (desktop) currently
renders with the pre-convergence, #203-tip renderer. Its own PR body
states plainly it "should re-merge #215" here — this is the standing
pending integration this checkpoint carries out unresolved. No diff has
been inspected for this merge; following checkpoint-04's own pattern
(the renderer line's core module is the recurring point of conflict),
the desktop line's own_render wrapper/bridge code is the likely touch
point once that merge is attempted.

**Writer and runtime lines** continue to meet the renderer/desktop lines
only at `main`; no PR in #211–#215 touches either.

## 7. Next measurable research question

**After #214 re-merges #215**, two concrete measurements are outstanding,
neither yet taken:

1. **The desktop smoke's `own` phase, re-run on the converged renderer.**
   #214 measured `own` 40/0 and `own-reattach` 3/0 against the #203-tip
   renderer; once the app draws with #215's registration + fonts +
   table-move tree instead, that phase needs re-running to see whether
   the same 40/3 hold, gain (pages the pre-convergence renderer
   mis-registered now line up), or need adjustment (the table-move
   rule's page-count effects, though absent from the public corpus and
   the private holdout, are untested against whatever documents the
   desktop smoke actually opens).
2. **Gap 34** — own-render geometry carries line-box positions but no
   text or addresses, so a desktop page rendered via tier 3 has no seats
   and no caret. An engine-side fix is sketched in #214's body but not
   built; this is the next desktop-side slice once the re-merge lands,
   and it is the item that actually blocks in-app editing on a
   tier-3 page (viewing already works; typing does not).

Both are the concrete next measurement, not a new renderer feature —
consistent with checkpoint-04's own framing of convergence as an
integration step, not a slice.

## 8. Certification status

Every own-render result in this checkpoint — the table-move rule
(#213), the desktop own-render page (#214), and the convergence
re-measurement itself (#215) — remains **own-uncertified**. None of the
three PRs' own bodies claims certification; `pipeline/scripts/
render_cert.py` still cannot certify this renderer absent a PDF text
layer, unchanged from checkpoint-01 through checkpoint-04.

#214 is the first point where this status is **user-visible in the
running app**, not only in docs or PR bodies: the 자체 렌더 · 미인증
badge is drawn directly on a tier-3 page, and the honest envelope
(`grade: own-uncertified`, `source.kind: own_render`) is the value the
UI reads to decide what to show — the same distinction checkpoint-01
through checkpoint-04 tracked only as a renderer-line research finding
now has a desktop-line consumer that cannot silently claim `hancom`.
