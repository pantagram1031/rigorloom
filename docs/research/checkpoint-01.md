# Checkpoint 01 — the renderer line after three research PRs

Non-merging checkpoint. Written from `claude/engine-e2-equations` @ `266e80e`
(this branch, `docs/checkpoint-01`, is cut from that tip and stays unmerged).
Covers PR #179 (line breaker, E2.1), PR #183 (report-class fidelity, E2),
and PR #187 (equations, E2) plus their renderer-line ancestors #166 and #173.

## 1. Branch DAG

38 open PRs, all unmerged drafts against `main`. Grouped into five research
lines by what they touch, with each line's deepest open PR as its
**authoritative tip** — the commit that supersedes everything upstream of it
in that line.

### Renderer line (`claude/engine-e2-*`, `claude/own-renderer-mvp`)

| PR | branch | base | slice |
|---|---|---|---|
| #166 | `claude/own-renderer-mvp` | `main` | tier-3 OWPML renderer MVP |
| #173 | `claude/engine-e2-typography` | `own-renderer-mvp` | E2.2/E2.3 typography + face resolution |
| #179 | `claude/engine-e2-linebreak` | `engine-e2-typography` | E2.1 line breaker from metrics |
| #183 | `claude/engine-e2-report-fidelity` | `engine-e2-linebreak` | E2 report-class fixes |
| **#187** | **`claude/engine-e2-equations`** | `engine-e2-report-fidelity` | **E2 equations — AUTHORITATIVE TIP** |
| #186 | `docs/hangul-feature-catalog` | `engine-e2-report-fidelity` | scoreboard catalog (docs side-branch, sibling of #187, not stacked further) |

### Writer line (`claude/engine-e3-*`)

| PR | branch | base | slice |
|---|---|---|---|
| #177 | `claude/engine-e3-owpml-writer` | `main` | canonical OWPML writer (E3.1) |
| **#180** | **`claude/engine-e3-writer-routing`** | `engine-e3-owpml-writer` | **one writer for every emitted HWPX — AUTHORITATIVE TIP** |

### Runtime line (`claude/runtime-*`, `claude/agenthost-*`)

`main` → #152 (`runtime-protocol-v0-design`, docs) → #154 → #155 → #157 →
#158 (`agenthost-foundation`) → #162 (`runtime-v0-phase3-gaps`) → #163
(`agenthost-anthropic`) → #165 (`runtime-page-geometry`) → #168 → #170
(`runtime-cell-seats`) → #174 (`runtime-e4-seat-coverage`), which forks:

| PR | branch | base | slice |
|---|---|---|---|
| #178 | `claude/runtime-e4-workspace-session` | `runtime-e4-seat-coverage` | E4.2 sessions |
| #182 | `claude/runtime-e4-workspace-ops` | `runtime-e4-workspace-session` | E4.2 write half |
| **#185** | **`claude/runtime-e4-workspace-read`** | `runtime-e4-workspace-ops` | **readMember/listMembers — AUTHORITATIVE TIP** |
| #181 | `claude/agenthost-e4-streaming` | `runtime-e4-seat-coverage` | E4.3 streaming — sibling tip, unmerged with #185's chain |

#153 (`threat-model-acceptance`, docs) hangs off #152 unmerged and unadvanced.

### Desktop line (`claude/desktop-*`)

Two unreconciled forks, both open:

- **Fork A (stale):** #159 `desktop-foundation` (base `runtime-v0-phase2`) →
  #161 `desktop-design`. Nothing stacks on #161; superseded in practice by
  Fork B but never closed.
- **Fork B (current):** #164 `desktop-editing` (base
  `runtime-v0-phase3-gaps`) → #167 `desktop-phase5` → #169 `desktop-overlay`
  → #172 `desktop-phase6` → #175 `desktop-e1-caret` → **#184
  `desktop-e1-undo` — AUTHORITATIVE TIP**. #176 `e5-ci-desktop-gate` also
  forks off #172 as a sibling of #175, unmerged.
- #151 `desktop-audit` (docs, base `main`) → #156 `desktop-shell-spike`:
  a dead-end spike, superseded by Fork B, never closed.

This is the "mid-merge state" flagged for convergence: Fork A was never
formally abandoned, and Fork B's own base (`runtime-v0-phase3-gaps`) predates
all of the runtime line's E4 work (#174 onward) — desktop will need to pick
up runtime E4 before or during any merge to `main`.

### Docs line (standalone, off `main`)

| PR | branch | note |
|---|---|---|
| #150 | `docs/product-direction-desktop` | earliest direction doc, superseded in spirit by later lines |
| **#171** | **`docs/hangul-editor-endgame`** | latest standalone docs draft — **AUTHORITATIVE TIP** |

#160 (`claude/t134-child-capture-bound`, base `main`) is a standalone test
fix, not part of any of the five lines.

## 2. Real-document visual comparison summary

### Corpus (public blank forms), `e2.1-line-breaking.scoreboard-summary.json`, 144 dpi, comparable-form means (7 of 10 forms; 3 excluded as blocked — see §3)

| metric | before (#173) | after (#179, auto mode) | computed (#179, own breaker only) |
|---|---|---|---|
| ssim_mean | 0.72751 | 0.727022 | 0.719804 |
| ssim_inked_mean | 0.122666 | 0.122528 | 0.110299 |
| text_line_iou_mean | 0.439395 | 0.439302 | 0.403545 |
| text_line_pair_rate_mean | 0.801423 | 0.801423 | 0.795333 |

`auto` mode (what ships) reuses cached `hp:lineseg` on unedited documents, so
it is deliberately near-identical to before; `computed` is the honest
own-breaker number and costs 0.036 IoU against the cached layout.

### Line-breaker agreement with the authoring engine (`e2.1-lineseg-agreement.json`)

| scope | line count agreement | break-sequence agreement | exact break positions |
|---|---|---|---|
| all 2148 scored paragraphs | 0.979 (2103/2148) | 0.932 (2003/2148) | — |
| 158 multi-line paragraphs only | 0.829 (131/158) | 0.196 (31/158) | **0.199 (43/216)** |

### Report-class document (18 pages, 485 paragraphs, 27 tables, 11 pictures, 14 equations, private, local-only — aggregate numbers only, as published in PR bodies)

| channel | before #183 | after #183 | after #187 (equations) |
|---|---|---|---|
| ssim_inked mean | 0.1034 | **0.1263** | (not re-stated; ink delta below moved) |
| line IoU | 0.5508 | **0.5630** | 0.5334 |
| pair rate | 0.8134 | **0.8390** | **0.9041** |
| ink_delta_abs_max | 0.0371 | **0.0085** | 0.0099 |
| ssim mean | 0.7306 | 0.7273 | 0.7280 |
| elements_skipped (distinct) | 13 | 5 | 5 |

Equations on that document: 14/14 laid out, 0 unsupported constructs, 13/14
scaled-to-fit (factor 0.812–0.995), ink stayed inside the declared box on all
14.

## 3. Regressions (with the PR's own explanation)

| PR | metric | moved | explanation given in the PR |
|---|---|---|---|
| #179 | comparable-form means, ssim_mean/ssim_inked_mean/IoU | down in the 4th decimal (0.72751→0.727022 etc.) | "four-decimal noise" — `auto` mode is designed to reuse cached boxes, so this is measurement jitter, not a real regression |
| #183 | ssim_mean | 0.7306 → 0.7273 | `DOUBLE_SLIM` now draws two thin strokes instead of one fat one; the fat stroke used to cover the reference's two strokes regardless of sub-pixel offset, so block SSIM had rewarded the wrong thing. `ssim_inked_min` also went 0.0123 → −0.0367 (still clears the −0.1 regression floor) |
| #183 | `changed_channel_ratio_mean` | 0.1060 → 0.1237 | same registration effect plus real photographs now drawn where blank boxes used to disagree less by accident |
| #187 | text_line_iou (report doc) | 0.5630 → 0.5334 | equation lines now pair with Hancom's (pair rate rose to 0.9041) but their box geometry differs from Hancom's layout — stated as the cost of a line now existing to be measured, not a fidelity loss |
| #187 | ink_delta_abs_max (report doc) | 0.0085 → 0.0099 | not separately explained beyond "regression floor passes" |

Every one of these clears its own PR's regression floor; none is a silent
degradation.

## 4. Unsupported / declared elements still open

From `engine/references/own-render-notes.md` limits 1–15 and the equations
section:

- **Fonts:** Hancom's own HFT families (휴먼명조, HCI Poppy, 한컴바탕, 신명
  신문명조, HY울릉도M, 필기) don't resolve as TrueType; substituted to Malgun
  Gothic, declared per character count. Render is machine-dependent by
  design.
- **paraPr not honored:** hyphenation, widow/orphan, keepWithNext,
  keepLines, pageBreakBefore, `fontLineHeight`, `snapToGrid`,
  `BETWEEN_LINES` spacing, non-LEFT tab stops (RIGHT/CENTER/DECIMAL advance
  as LEFT), pre-existing `<hp:tab/>` in a document (not resolved into the
  character stream), hanging indent.
- **Objects:** `hp:ole`, `hp:chart`, `hp:container`, drawing shapes, and any
  undecodable EMF/WMF `hp:pic` still draw a grey placeholder box.
- **Borders:** only `DOUBLE_SLIM` draws two strokes; `DASH`/`CIRCLE` still
  stroke solid.
- **Headers, footers, footnotes, endnotes, master pages:** not drawn at all.
  `hp:pageNum` is the one exception (stamped, `BOTTOM_LEFT/CENTER/RIGHT`
  only). The measured report declares `hp:footNotePr`/`hp:endNotePr` but
  carries no actual note, so this path is still unmeasured against a real
  one.
- **Multi-section documents:** only `section0` is laid out; untested against
  a real multi-section report (none in corpus or the measured document).
- **Multi-column (`hp:colPr`):** ignored.
- **Text wrap around anchored objects:** not implemented; objects draw over
  whatever is beneath them.
- **`hp:parameters`/`hp:stringParam`/`hp:integerParam`:** field bookkeeping,
  not rendered (no ink of their own).
- **Equations, declared unsupported constructs:** `size`, `color`,
  `bigg`/`small`, `binom`, `choose`, `buildrel`, `rel`, `dyad`, the `col`
  family, unbalanced fences — drawn as raw token text. Italic variable
  shaping is not implemented (named as the single biggest remaining visual
  gap in equations; needs italic cuts in the font index). Grids/accents are
  exercised only by synthetic fixtures — no corpus or measured-report
  equation used them.
- **Row heights:** approximate where content extent governs; 8 of 81 corpus
  tables miss declared height by >2% before residual redistribution.
- **Pagination:** `kstartup-jiwon-sincheongseo-saeopgyehoekseo` fails
  `page_count_exact` — a pagination defect, unfixed, unrelated to the line
  breaker.
- **Block layout / page reflow (E2.5):** not implemented. A relaid paragraph
  shifts siblings within its own container only; nothing moves across pages,
  overflow is drawn past the body box anyway.
- **Line breaker:** 43/216 (0.199) exact break-position agreement with the
  authoring engine — see §7.

## 5. Tests actually run per PR (from PR bodies)

| PR | orchestrator re-run | full suite | notes |
|---|---|---|---|
| #166 | 25 passed (file suite) | 3921 passed / 146 skipped / 0 failed (21m13s) | baseline |
| #173 | 68 passed (own_render + scoreboard) | 3965 passed / 146 skipped / 0 failed (34m43s) | +44 over #166 |
| #179 | 77 passed (renderer suite) | 3997 passed / 146 skipped / 0 failed (41m18s); `engine/tests` 1044 passed / 135 skipped | +32 over #173 |
| #183 | 96 passed (own_render suite) | 4016 passed / 146 skipped / 0 failed (29m35s); `engine/tests` 1063 / 135 skipped | +19 over #179 |
| #187 | 116 passed (own_render suite) | 4036 passed / 146 skipped / 0 failed (22m39s); `engine/tests` 1083 | +20 over #183 |

`py_compile_sweep` and the privacy gate (`HARD=0`) passed on all five.

## 6. Integration conflicts expected when lines converge

- **Renderer vs writer:** no direct file overlap found. Renderer PRs
  (#166–#187) touch `engine/scripts/own_render.py`,
  `engine/scripts/hwpeqn_parse.py`, `engine/references/own-render-notes.md`,
  `engine/tests/test_own_render.py`. Writer PRs (#177, #180) touch
  `engine/scripts/hwpx_write.py`, `xml_backend.py`, `preedit.py`,
  `tidy_hwpx.py`, `engine/references/owpml-writer-notes.md`,
  `engine/tests/test_hwpx_*.py`. Both share the `engine/` tree and the
  corpus fixtures — no line-level conflict expected, but a full-suite run
  after merge is the actual check, not the file diff.
- **Desktop's mid-merge state:** Fork A (#159→#161) was never closed or
  rebased onto Fork B; whichever merges last will need the other's fork
  explicitly abandoned or reconciled, not silently dropped.
- **Runtime stack vs desktop merges:** Desktop's current tip (#184) still
  bases on `runtime-v0-phase3-gaps` (pre-E4). The runtime line's
  authoritative tip (#185) is five PRs of E4 work ahead of that ancestor,
  and its sibling #181 (`agenthost-e4-streaming`) is a second unmerged head
  off the same #174 ancestor. Desktop will need runtime E4 (workspace
  read/write, and a streaming-vs-non-streaming agenthost decision) rebased
  in before or during its own merge to `main` — two runtime heads into one
  desktop base is an open reconciliation, not a mechanical rebase.
- **Renderer/writer vs runtime/desktop:** no shared files observed; these
  four lines only meet at `main`.

## 7. Next measurable research question

The line breaker agrees with the authoring engine on 43/216 (0.199) exact
multi-line break positions. Restarting the breaker at each of Hancom's own
line starts (removing compounding error) still gives only 45 exact / 29
early / 142 late — median line-box fill is 0.92 by our own advances, so the
breaker keeps fitting one more word than Hancom did. A space-advance sweep
against the 216 break positions peaks at 69/216 (0.45 em) and was explicitly
**not adopted** — it is a fit, not a reading of a real metric.

**The number that would settle it:** the actual space-glyph advance width
Hancom's line breaker uses for each resolved face — read from the font's own
`hmtx`/metrics table (or from Hancom's HFT spec, or by measuring a
Hancom-rendered 1:1 reference at the glyph level) rather than curve-fit
against the 216-position corpus. Resolved faces already agree far better
than substituted ones (38/156 vs 11/60), so the gap is plausibly resolvable
per-face once a ground-truth advance number — not a fitted one — exists.

## 8. Certification status

Every own-render result in this checkpoint — corpus scoreboards, the
report-class aggregates, the equation numbers, the 43/216 line-breaker
figure — remains **own-uncertified**. `grade` is `own-uncertified` in every
sidecar; `pipeline/scripts/render_cert.py` cannot certify this renderer
until it emits a PDF text layer (a raster backend is not certifiable by that
path). None of these five PRs claims certification, and none is merged to
`main`. Where a Codex-run renderer preview exists elsewhere in this
repository's history, it is regression evidence only — a signal that
something moved, not a merged or certified artifact, and it does not change
any number in this checkpoint.
