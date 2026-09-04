# Checkpoint 06 — metrics, the object line box, and the app on the converged renderer

Non-merging checkpoint. Written from `origin/claude/engine-e2-pagination`
(this branch, `docs/checkpoint-06`, is cut from that tip and stays
unmerged). Covers #217 (desktop renders with the converged #215 renderer,
fonts bundled in the sidecar, smoke 499/0), #218 (line and character
metrics: five rules measured off the reference PDF's text layer,
render-check 1/35/13/2 → 3/37/9/2, F06–F08 pixel-exact — with a stated
regression, page agreement 45 → 41/51), and #219, the pagination PR
(`claude/engine-e2-pagination`, PR **#219**, base `claude/engine-e2-line-metrics`):
an inline object's line box is its extent plus its own `hp:outMargin`, and
an object line's leading comes from the largest declared *character* size
on the line, not the object's own extent — page agreement 41 → 47/51,
`kstartup` computed page count 27 → 22 (reference 22). Page count on the
render-check document itself is still 11 vs Hancom's 9, and the residual
is named: the four `hp:equation` blocks declare `hp:sz@height` that
exceeds what Hancom actually reserves (36.4 pt of drift across the
document), plus the known two-column section (F49). Checkpoint-05
(`docs/checkpoint-05`, off #215) carries forward as the record of the
renderer line's convergence and the state before this window.

**Operating notes this window, stated honestly.** A disk crisis hit this
bench — C: fell to 0.28 GB, caused by a co-resident Codex store — and was
fixed by junction-moving Codex archives and Grok to an external F: drive
and relocating the cargo/pip/npm caches there; Codex's own session data
was preserved throughout, never deleted. Background jobs still get killed
on this bench, so full-suite gates continue to run in foreground pieces
rather than as one job. The full-suite gate deferral carried in checkpoint-05
is **still owed** across #205–#218; no PR in this window records it being
run to completion.

## What changed since checkpoint-05

| metric | checkpoint-05 | checkpoint-06 | moved in |
|---|---|---|---|
| renderer-line shape | converges at #215 (new tip) | #215 → **#218** (line/character metrics) → **#219** (pagination, new tip) | #218, #219 |
| desktop line | …→#214, still rendering with the pre-convergence #203 renderer; re-merge of #215 named as pending integration | **#217 merged**: `origin/claude/engine-e2-converge` (#215) merged onto #214 with no conflicts — the app now renders with the converged renderer; sidecar bundles the OFL family-map fonts (86 → 98.8 MiB) and gains a role check asserting `fonts.faces[].source == "bundled"` for Hancom-only faces | #217 |
| render-check tally (51 features) | 1 · 35 · 13 · 2 | **3 · 37 · 9 · 2** — F22/F32 become `match`, F14/F16/F17/F27/F28 stay `differs`, F35 moves to `differs` (pagination); F06–F08 line-spacing bands now pixel-exact (121/121, 140/140, 94/94) | #218 |
| render-check page agreement (51 features) | 45/51 (checkpoint-05's own baseline before this window's re-measure) | **41/51 after #218** (stated regression, a pagination rule not a metric) → **47/51 after #219** | #218 (down), #219 (up) |
| render-check page count (synthetic document) | 11 vs 9 (unchanged since #213) | **still 11 vs 9** — residual now named: 4 `hp:equation` blocks over-declare `hp:sz@height` by 36.4 pt total, plus the two-column section (F49) | #219 (diagnosed, not fixed) |
| line/character metrics | grouped as one guess, "the line-metric gap" (checkpoint-05 §4) | **replaced with five measured rules**: PERCENT/FIXED pitch = value/100 × declared charPr height (already correct); `relSz`/`ratio`/`offset` excluded from line height (was wrongly multiplied in); `hh:spacing` gap = character's own advance × pct; `hh:offset` positive lowers by % of declared height (sign + reference size were wrong); paraPr MCE `default` branch is in half-HWPUNITs (`PARA_MARGIN_SCALE` deleted) | #218 |
| corpus scoreboard means | ssim 0.8266, ssim_inked 0.2579, line IoU 0.6447 (post-#215) | ssim 0.7915 → 0.7932, ssim_inked 0.2509 → 0.2598, line IoU 0.6178 → 0.6206 (#218, different baseline slice — corpus flow/lineseg terms); lineseg break matches 65 → 68/216 | #218 |
| corpus flow agreement, `computed` | not separately tracked at checkpoint-05 | 344/590 → **392/590** pages, exact `dy` 119 → **216** (#219) | #219 |
| `kstartup` computed page count | 27 (open) | **22**, matching the reference's 22 | #219 |
| object-line box rule | not yet isolated (line-metric gap grouped F06–F17 together) | **found and adopted**: line box = extent + `hp:outMargin@top` + `@bottom` (79/79 exact, extent alone 16/79); leading = largest declared character size on the line (66/79 exact, 12 more within 2 HWPUNIT) | #219 |
| desktop ↔ renderer coupling | pending integration, not yet attempted | **resolved** — #217 merges #215 into the desktop line with no conflicts | #217 |
| gap 34 (own-render geometry has positions, not text → no seats/caret) | named, not built | **unchanged this window** — no PR in #217–#219 touches it; still the next desktop-side slice once a page needs to be typed in, not only viewed | — |

## 1. Branch DAG

Renderer line, tip at #215 (checkpoint-05), now extends through two more PRs:

| PR | branch | base | slice |
|---|---|---|---|
| #215 | `claude/engine-e2-converge` | `claude/engine-e2-registration` | convergence tip (checkpoint-05) |
| #218 | `claude/engine-e2-line-metrics` | `claude/engine-e2-converge` | five line/character metric rules off the reference text layer |
| **#219** | `claude/engine-e2-pagination` | `claude/engine-e2-line-metrics` | **the inline-object line box (extent + outMargin, leading from character size) — new renderer-line tip** |

Desktop line, tip at #214 (checkpoint-05), now extends by one PR:

| PR | branch | base | slice |
|---|---|---|---|
| #214 | `claude/desktop-own-render` | `claude/desktop-e1-undo` | own-render + band + zoom (checkpoint-05 tip) |
| **#217** | `claude/desktop-own-render-converged` | `claude/desktop-own-render` | **re-merge of #215 into the desktop line — new desktop-line tip; renders with the converged renderer** |

`#217`'s own body states the merge was "with no conflicts" — the
integration checkpoint-05 flagged as pending and named as the likely
touch point (the desktop line's own-render wrapper/bridge code) landed
without the conflict materialising.

Sibling docs branch:

| PR | branch | base | note |
|---|---|---|---|
| #216 | `docs/checkpoint-05` | `claude/engine-e2-converge` | prior checkpoint (this doc's predecessor) |

### Writer / Runtime lines

**Writer line**, unmoved this window: #177 → #180 → #189. No PR in
#217–#219 touches it.

**Runtime line**, unmoved this window: … → #185 → #204. No PR in
#217–#219 touches it.

## 2. Real-document comparison aggregates per PR (as published in PR bodies)

### #217 — desktop renders with the converged renderer

`document/render`'s `own_render` fallback now runs the #215 tree. Packaged
sidecar bundles the OFL family-map fonts (86 → 98.8 MiB) and adds a role
check that renders a form declaring Hancom-only faces through the FROZEN
runtime, asserting `fonts.faces[].source == "bundled"` so a fresh install
cannot silently fall back to a generic face for a Hancom name.

Evidence: `tsc` 0; `tauri build` 0 (cargo target relocated to F: after the
bench's disk hit 320 MB from a co-resident process, confirmed external to
this repo); **smoke 499/0** across 14 phases (`own` 40, `own-reattach` 3 —
the skipped-list assertion compares entry-by-entry against the runtime's
own list); `page-own-render.png` regenerated and confirmed different from
the pre-convergence capture (the 직인 box shifts a few px as a declared
face now resolves); archive privacy gate HARD=0 (WARN 45 → 51, six new
font files flagged `large_file`, correctly not violations).

Defect found and fixed in the same PR: the new role check's
`Get-Content -Raw | ConvertFrom-Json` mis-decoded UTF-8 sidecar JSON under
the Korean console codepage; replaced with `[IO.File]::ReadAllText(…, UTF8)`.

Not proven: the bundled-font path has no fidelity number of its own (the
holdout's faces were all installed locally); the role check proves
resolution, not visual accuracy.

### #218 — the measured line and character metrics

Five rules measured off the reference PDF's text layer at a 0.12 pt grid,
four of them fixes:

- PERCENT/FIXED line pitch = value/100 × declared `charPr` height — n=24,
  worst residual 0.091 pt; face ascent+descent and a flat 1.2× were
  rejected. Already correct, unchanged.
- `relSz`/`ratio`/`offset` stay **out** of the line height — a relSz-140
  line advances 15.95 pt, not 22.4. Was wrongly multiplied in.
- `hh:spacing` gap = the character's own advance × pct — Latin and space
  discriminate (residual ≤0.16 pt vs 8.36 pt for a flat gap).
- `hh:offset`: positive **lowers**, by % of declared height — n=4, residual
  ≤0.10 pt. Code had both the sign and the reference size wrong.
- The paraPr MCE `default` branch is in **half-HWPUNITs** — 811 corpus
  paraPr, ratio exactly 2.0 on every length, 1.0 on all 806 PERCENT
  values; `PARA_MARGIN_SCALE` deleted, `left`/`right`/`intent` had been
  read doubled.

Render-check: 1 · 35 · 13 · 2 → **3 · 37 · 9 · 2**. F14/F16/F17/F27/F28
stay `differs`; F22/F32 become `match`; F35 moves to `differs`
(pagination). Line-spacing bands F06–F08 now match Hancom **to the
pixel** (121/121, 140/140, 94/94 rows) — their residual `differs` is
ssim/ink only. F13 misses `close` by 0.002, F15 by 0.008.

Corpus: ssim 0.7915 → 0.7932, ssim_inked 0.2509 → 0.2598, line IoU
0.6178 → 0.6206; page-exact and pass 9/10 unchanged; worst form −0.0009
ssim. Lineseg break matches 65 → **68**/216; flow agreement unchanged.
Determinism holds.

Evidence: engine/tests 1206 passed / 135 skipped / 0 failed;
`py_compile_sweep` 105/0; archive privacy gate HARD=0.

**Honest regressions / not proven:** render-check page agreement 45/51 →
**41/51** and page count still 11 vs 9 — the residual is a pagination
rule, not a metric (resolved partway by #219, below); `hh:spacing`
composition order vs ratio/relSz untested (F13 declares neither); the
half-HWPUNIT switch unit is measured, not read from KS X 6101;
`hh:tabPr` stops in the same switch are still never read (backlog 8).

### #219 — the inline-object line box (pagination)

Measured block by block against Hancom's text layer. The first 48 blocks
of section 0 agree to 0.05–0.50 pt. The mechanism sits at block 54: a 72 pt
inline table advanced 115.20 pt against Hancom's 80.73 — exactly
72 × 1.60. The paragraph's PERCENT leading was being applied to the
inline object's own extent, and the object's vertical `hp:outMargin` was
missing from the line box.

Adopted, off the ten corpus forms' 79 cached object-line `hp:lineseg`:
line box = extent + `outMargin@top` + `@bottom` (**79/79 exact**, residual
0; extent alone 16/79); leading for an object line = the largest declared
**character** size on the line (**66/79 exact, 12 more within 2 HWPUNIT**;
leading off the object box 4/79). Independently confirmed on the
reference PDF (n=4, worst residual 0.31 pt). Rejected by measurement:
per-pair-type margin failure (45 pairs, ≤0.10 pt), last-line spacing
tail, table row height/empty-cell padding (F27 rows 23.97 pt vs declared
2400 — already right).

Numbers: render-check page agreement 41/51 → **47/51**; line IoU
0.4104 → 0.4139; tally unchanged (3/37/9/2); F06–F08 bands still
pixel-exact. **Page count did not move (11 vs 9) — stated.** F32 lost
`match` on IoU while its band shrank to the reference's own 126 px and its
top moved from 0.088 to 0.0003 of page height (a narrower, correctly
placed band). Corpus: `auto` flow agreement unchanged 469/590;
`computed` 344 → **392/590** pages, exact dy 119 → **216**; `kstartup`
computed pages 27 → **22** (reference 22), ssim 0.8774 → 0.8794; 51 of
52 shipping corpus pages byte-identical (`kstartup` p5 moves, ssim
0.7575 → 0.7514).

Evidence: engine/tests 1209 passed; `py_compile_sweep` 105/0; archive
privacy gate HARD=0; render-check report reproduces feature-for-feature.

**Not proven / the residual, named:** the remaining extra page is the
four `hp:equation` blocks — their declared `hp:sz@height`
(2400/2400/3600/3600) exceeds what Hancom actually reserves
(2252/1304/2696/2108), 36.4 pt total, exactly what pushes F45 off page 4
— **next slice named: equation extent from content, not declaration.**
The other page is the known two-column section (F49). FIXED and
sub-100% PERCENT on object lines unmeasured; twelve ±2 HWPUNIT cache
wobbles and `admrul`'s 200% line unexplained, not fitted.

## 3. Regressions (with the PR's or commit's own explanation)

| PR | metric | moved | explanation given |
|---|---|---|---|
| #218 | render-check page agreement | 45/51 → 41/51 | stated as "a pagination rule, not a metric" — the metric fixes (relSz/ratio/offset exclusion, half-HWPUNIT margins) changed block heights enough to shift page breaks; page count itself stayed 11 vs 9 |
| #219 | (recovers most of #218's page-agreement regression) | 41/51 → 47/51; page count unchanged at 11 vs 9 | the object-line-box fix corrects the mechanism #218 exposed but does not itself change page **count** — the residual is now attributed to equations, not to this rule |
| #219 | `kstartup` p5 ssim | 0.7575 → 0.7514 | the one shipping-corpus page (of 52) that carries a stale paragraph holding an inline object moves; its block assignment comes from the cache heuristic `own-render-notes.md` limit 12 already calls wrong — on `block_layout=computed` (the pagination that is right for this form) the same form improves |

No corpus form or public-corpus page count regressed beyond the two rows
above; both #218 and #219 state their trade-offs explicitly rather than
omitting them.

## 4. Unsupported / declared elements still open

Carried from checkpoint-05, with items this window's PRs closed, refined,
or added:

- **Closed since checkpoint-05:** the desktop↔renderer pending integration
  (#217 — merged with no conflicts); F06–F08 line-spacing pixel accuracy
  (#218 — pixel-exact, remaining `differs` verdict is ssim/ink only); the
  "line-metric gap" grouping of F06–F17 (#218 replaces the guess with five
  measured, individually-verdicted rules); the object-line-box mechanism
  behind render-check's page-count gap (#219 — measured and fixed for the
  outMargin/leading half of it).
- **Partially closed:** render-check page count (synthetic document,
  11 vs Hancom's 9) — the object-line-box term is fixed; the residual is
  now two named, separate mechanisms: `hp:equation` extent-from-declaration
  vs Hancom's actual layout (36.4 pt, four blocks) and the two-column
  section (F49), neither yet fixed.
- **Still `differs`, current state, with mechanism:**
  - `F14` (장평 `hh:ratio`), `F16` (글자 위치 `hh:offset`) — #218 fixed the
    offset sign/reference-size bug but the feature remains `differs`
    on this document; not further diagnosed this window.
  - `F17` (진하게 bold), `F27`/`F28` (table row-height floor / cell merge)
    — carried unchanged from checkpoint-05's mechanism notes (page-boundary
    artefact / row-height-floor residual).
  - `F35` — newly `differs` this window, attributed to pagination shift
    from #218's metric fixes; not yet individually re-diagnosed under #219.
  - `F49` (다단 2단 구역, two-column) — unchanged: Hancom appears to require
    a column break or section restart before `hp:colPr` takes effect from
    the head of a section.
- **New, named this window:** the four `hp:equation` blocks' declared
  `hp:sz@height` overstates Hancom's actual reserved box by 36.4 pt total
  — the concrete next renderer-side measurement (§7).
- **Unchanged from checkpoint-05:** gap 34 (own-render geometry has line
  boxes, not text/addresses/seats/caret) — no PR in #217–#219 touches it;
  whole-document computed layout's page-count/line-IoU failure (#199);
  the writer line's default header/meta elements on a blank package save;
  `hp:ole`/`hp:chart`/`hp:container`/shapes/undecodable EMF-WMF
  placeholders; `DOUBLE_SLIM` border limitation; text wrap around anchored
  objects; `hp:parameters` family; equations' declared-unsupported
  constructs (now sharpened by the extent-from-content finding above,
  still not fixed).

## 5. Tests actually run per PR (from PR bodies)

| PR | orchestrator / engine suite | full suite | notes |
|---|---|---|---|
| #217 | `tsc` 0; sidecar 0 (+2 new tier-3 role checks); `tauri build` 0; **smoke 499/0** across 14 phases (`own` 40, `own-reattach` 3) | not applicable (desktop build/smoke, not the engine full suite) | archive privacy HARD=0 (WARN 45→51, font files); UTF-8 JSON decode defect found and fixed in-PR |
| #218 | engine/tests 1206 passed / 135 skipped / 0 failed | deferred | `py_compile_sweep` 105/0; archive privacy gate HARD=0; measurement script committed at `tests/corpus/render-check/measure_metrics.py` |
| #219 | engine/tests 1209 passed | deferred | `py_compile_sweep` 105/0; archive privacy gate HARD=0; render-check report reproduces feature-for-feature |

Full-suite gate deferral is now a streak spanning #205 through #218 with
no appended run recorded in any PR body through this checkpoint — carried
forward exactly as checkpoint-05 flagged it, still not resolved. This
window adds the disk-crisis root cause and its fix (junction-moving
Codex/Grok archives and relocating cargo/pip/npm caches to F:) but the
gate itself remains owed, run only in foreground pieces rather than as
one pass.

## 6. Integration conflicts expected when lines converge

Checkpoint-05's one standing pending integration — #214 (desktop)
re-merging #215's converged renderer — **is resolved**: #217 performed the
merge "with no conflicts," landing without the friction checkpoint-05
predicted at the own-render wrapper/bridge code.

**No new cross-line conflict is named this window.** #218 and #219 stack
linearly on the renderer line (`converge` → `line-metrics` → `pagination`)
with no sibling branch to reconcile against; #217 is the desktop line's
only move and it is now integrated. Writer and runtime lines continue to
meet the renderer/desktop lines only at `main`; no PR in #217–#219 touches
either.

## 7. Next measurable research question

**Would render-check reach 9/9 pages?** Two named, independent mechanisms
remain, both diagnosed but not fixed:

1. **Equation extent from content, not declaration.** The four
   `hp:equation` blocks in the render-check document claim
   `hp:sz@height` values (2400/2400/3600/3600 HWPUNIT) that exceed what
   Hancom's own layout actually reserves for the same equations
   (2252/1304/2696/2108) — 36.4 pt of cumulative drift, and it is the
   exact amount that pushes `F45`'s 글상자 off page 4. Fixing it means
   measuring `hp:equation` layout against the reference rather than
   trusting the declared box — a different subsystem from the line/object
   metrics this window closed.
2. **F49, the two-column section.** Section 2 still runs 2 pages to
   Hancom's 1; `hp:colPr` is applied from the head of the section, but
   Hancom appears to require a column break or section restart first —
   unchanged since checkpoint-05, not attempted this window.

If both land, render-check's page count on the synthetic document would
move from 11 to 9, matching the reference exactly — the natural next
measurement is whether page **agreement** (currently 47/51) also closes
the remaining 4, or whether those are independent feature-level residuals
(F14/F16/F17/F27/F28/F35) that a page-count fix does not itself resolve.

## 8. Certification status

Every own-render result in this checkpoint — the app on the converged
renderer (#217), the measured line/character metrics (#218), and the
object-line-box pagination fix (#219) — remains **own-uncertified**. None
of the three PRs' own bodies claims certification;
`pipeline/scripts/render_cert.py` still cannot certify this renderer
absent a PDF text layer, unchanged since checkpoint-01.

#217 extends the user-visible consequence checkpoint-05 first recorded:
the running desktop app now draws with the same renderer tree
(registration + fonts + table-move + line/character metrics + the
object-line box, once #219 lands on top of what #217 merged) that the
engine-side research in this document measures — the gap between "what
the renderer does" and "what the app shows" that checkpoint-05 flagged as
pending is closed, though the renderer's own fidelity ceiling (own-uncertified,
9-vs-11 pages, 9 of 51 features still `differs`) is unchanged by that
integration alone.
