# Checkpoint 14 — the line that justified a fit rule was never drawn, and the real bug was in our own reader

Non-merging checkpoint. Written from `origin/claude/docs-checkpoint-13`
(this branch, `claude/docs-checkpoint-14`, is cut from `claude/docs-
checkpoint-13` and stays unmerged). Covers #252
(`claude/engine-e2-paragraph-bottom`: names the paragraph before each
page's first drift as two mechanisms — a predecessor's own block growing,
or a predecessor that draws nothing displacing the seat above it — neither
fixed), #255 (`claude/engine-e2-first-seat`: a seat-level divergence pass
over every top-level paragraph; **fixes** an anchored object's reserved
extent to include `hp:outMargin`, closing nrf's one substantive seat gap;
**finds, does not fix**, that an empty paragraph with no cached lineseg
gets block height 0 from `_flow_lines`), #256
(`claude/engine-e2-page-bottom-fit`: a page-bottom fit-rule probe brackets
six candidate measures against every cached page break in the corpus —
none is refuted by public data alone, so the private development-
validation document's one page-bottom overhang is used to narrow the
band; a costed, unapplied proposal), #257
(`claude/engine-e2-usable-height`: refutes the reading that the usable
body height is short by ~600 HWPUNIT — the body box is right, a footer
band is reserved even where a form has no `hp:footer` — **and then
withdraws the fit-rule hypothesis itself**, because the development-
validation document's own Hancom-exported PDF never drew the line the
hypothesis was built on), and #258
(`claude/engine-e2-lineseg-vs-pdf`: asks whether Hancom's export
reproduces the lineseg it saved — on the ten-form corpus, yes, exactly,
411/411 paragraphs, 0 split divergences; the measurement instead exposes
that **our own cache reader** mis-slices text at control-cell characters,
mis-splitting 21 of 161 multi-line corpus paragraphs; fix named, not yet
shipped). Desktop (#248) gets one correction, no new PR: its 551/0 smoke
ran against the **pre-built** exe, which does not contain this branch's
merged renderer — not evidence the merged source builds or renders
correctly. Docs (#253) proposes a `LayoutSnapshot` contract and fixes the
`x1` glossary; no code, no level-C run. Writer line (#224 → #235 → #238 →
#239) and runtime line (#204) did not move this window.

## What changed since checkpoint-13

| metric | checkpoint-13 | checkpoint-14 | moved in |
|---|---|---|---|
| renderer-line tip | #250 (`219cdaa`) | **#258** (`8c35105`) — a linear five-PR extension: #252 → #255 → #256 → #257 → #258 | #252, #255, #256, #257, #258 |
| "why does the holdout add a whole body line between paragraphs" (checkpoint-13's own next question) | opened, not measured | **decomposed into two mechanisms, neither fixed** (#252): 10/17 pages, the predecessor's own block grew (#250's class-A tail, its −6.14 px residual now located in the last line's advance); 7/17 pages, the predecessor draws nothing and the cache seats trailing empty paragraphs past the page bottom on one seat while the flow pass paginates them — named, one boundary case (nrf), not fixed | #252 |
| anchored-object reserved extent | `vertOffset + height` only (undiagnosed gap, nrf −276 HWPUNIT seat) | **fixed**: `_anchor_extent` now reserves `vertOffset + top + height + bottom` (adds `hp:outMargin`); nrf's differing seats 10 → 7; public synthetic probe matches the expected shift exactly (141→+282, 283→+566) | #255 |
| empty paragraph with no cached lineseg | not examined | **found, not fixed**: `_flow_lines` gives it block height 0 regardless of its own line-spacing or `charPr` height | #255 |
| page-bottom fit rule | not asked | **bracketed, not fixed** (#256): six candidate measures scored against 27 kept / 5 rejected corpus page-break events; none refuted by public data alone; the private development-validation document's one overhang (a line kept at **+566** HWPUNIT past the usable bottom, another rejected at +626) narrows the band to two readings — a fractional-fit rule, or a ~600 HWPUNIT shortfall in the derived usable height | #256 |
| "is the usable body height short by ~600 HWPUNIT" | not asked | **refuted** (#257): pagePr-derived body boxes match Hancom's own PDF ink to ≤ 11 HWPUNIT inside on every checkable case, including a footer band reserved on a form with no `hp:footer`; no offset reconciles kept/rejected events on the corpus | #257 |
| the "+566 kept line" that motivated the fit-rule hypothesis | stood as the private evidence anchoring #256's band | **does not exist in that document's own Hancom-exported PDF** (#257): the cache's 7-lineseg split of that paragraph is not what Hancom exported — the PDF draws it in 6 lines, none past the body bottom; hypothesis withdrawn; the next paragraph sits at +1792 in the PDF, matching the cache's seat (1800), not computed's (3600) | #257 |
| does Hancom's export reproduce its saved lineseg | asked (#257, in flight) | **yes, exactly, on the corpus**: 411/411 paragraphs, 0 line-count or split divergences, 8566/8566 characters agree | #258 |
| our own cache reader | assumed correct | **found buggy**: `hp:lineBreak` / `hp:tab` / `hp:fwSpace` occupy a `textpos` cell that `Paragraph.chars` does not carry, so `_render_cached_lines` slices at the wrong offset — 21 of 161 corpus multi-line paragraphs drawn with a character on the wrong side of a break; fix named, in flight | #258 |
| development-validation document, save-vs-export | not compared this way | **127 paragraphs compared, aggregate only**: 122 equal line count, **5 one line shorter in the export** (genuine save-vs-export difference, cause unknown); of the 122, 40 differ in character split by exactly ±1 character — consistent with the control-cell reader bug, not export re-flow | #258 |
| desktop smoke evidence | reported 551/0 on the pre-built exe, framed as this window's smoke result | **corrected**: that exe/sidecar do not contain this branch's merged renderer; the result shows the merge did not break the checked-in harness, and is **not** evidence the merged source builds or renders correctly; open until a build from `8a56ada` runs the smoke | #248 (comment) |
| desktop line | re-merged onto #245, three renderer slices behind | **unchanged this window** — no new desktop PR; now **six** slices behind the renderer tip (#252, #255, #256, #257, #258 landed after) | — |
| docs / protocol proposal | not addressed | **`LayoutSnapshot` contract proposed** (#253): schema, glossary fixing `x1` vs `x1_advance`, support levels A/B/C kept separate, honest status "no level-C run exists"; proposal only, awaiting agreement | #253 |
| writer line | unmoved since checkpoint-06 | **still unmoved** | — |
| runtime line | unmoved since checkpoint-06 (#204) | **still unmoved** | — |

## 1. Branch DAG

Renderer line, still a straight chain off checkpoint-13's tip — no
siblings, no merge this window:

| PR | branch | base | slice |
|---|---|---|---|
| #250 | `claude/engine-e2-drift-attribution` | `claude/engine-e2-divergence-tool` | renderer tip at checkpoint-13 (`219cdaa`) |
| #252 | `claude/engine-e2-paragraph-bottom` | `claude/engine-e2-drift-attribution` (#250) | names the paragraph before each page's first drift; two mechanisms (predecessor's own block grew / predecessor draws nothing), neither fixed |
| #255 | `claude/engine-e2-first-seat` | `claude/engine-e2-paragraph-bottom` (#252) | seat-level divergence pass over every top-level paragraph; **fixes** the anchored-object `outMargin` gap; finds, does not fix, the no-lineseg empty-paragraph block-height-0 case |
| #256 | `claude/engine-e2-page-bottom-fit` | `claude/engine-e2-first-seat` (#255) | brackets six page-bottom fit-rule candidates from cached corpus breaks plus one private overhang; costed proposal, not applied |
| #257 | `claude/engine-e2-usable-height` | `claude/engine-e2-page-bottom-fit` (#256) | refutes the "usable height short by ~600" reading via PDF ink; then withdraws the fit-rule hypothesis itself — the private "+566 kept line" is not in that document's own exported PDF |
| **#258** | `claude/engine-e2-lineseg-vs-pdf` | `claude/engine-e2-usable-height` (#257) | **asks whether export reproduces saved lineseg (yes, 411/411 on the corpus); finds a control-cell mis-slicing bug in our own cache reader instead. This is the renderer tip (`8c35105`).** |

Desktop line: no new PR this window; one comment on the existing #248.

| PR | branch | base | note |
|---|---|---|---|
| #248 | `claude/desktop-on-renderer-245` | `claude/desktop-renderer-230` | unchanged since checkpoint-13; new comment **corrects** the smoke evidence: the 551/0 pre-built-exe run does not contain this branch's merged renderer and is not evidence for it |

Docs line: one new proposal PR this window, cut from checkpoint-13, not
checkpoint-14 — it does not sit on this checkpoint's own chain.

| PR | branch | base | note |
|---|---|---|---|
| #253 | `claude/docs-layout-snapshot-proposal` | `claude/docs-checkpoint-13` | `LayoutSnapshot` contract proposal + `x1` glossary fix; no code; depends on #251 (checkpoint-13 itself); no level-C run exists |

Writer line, unchanged from checkpoint-13 — still #224 → #235 → #238 →
#239, no new PR this window.

Runtime line, unmoved since checkpoint-06 (last PR #204).

Out of scope for this checkpoint: #254 (`review/revision-coherence-
20260905`, based on #248's branch), an independent cross-layer Runtime/
Desktop finding posted as #248's most recent comment after the smoke
correction; it does not touch the renderer or writer lines this window
and is not covered here.

Sibling docs branches: `docs/checkpoint-01` … `docs/checkpoint-13` (each
off its own window's renderer tip).

## 2. Real-document comparison aggregates per PR (as published in PR bodies and comments)

### #252 — the paragraph before the drift, two mechanisms, neither fixed

**Measurement only — `own_render.py` untouched.** The tool now reports,
per page, the first paragraph whose first line differs between policies
and the paragraph immediately before it: cache/computed last-line
geometry, the inter-paragraph gap under both policies, and the
predecessor's paraPr (spacing type, margins, empty text, anchored-object
kind and extent under both policies), plus a histogram over (anchor kind,
empty, spacing type).

**Corpus (144 dpi, `--y-tol 0.5`), 17 pages with a predecessor:** text
predecessor 10, empty inline-table paragraph 4, plain empty paragraph 3.

**(a) 10/17 pages — the predecessor's own block grew.** moel-2013 p4
drift +36.66 px vs block height +36.70; moel-2025 +29.76 / +32.28 /
+26.64 vs +29.88 / +32.52 / +26.76 — this is #250's class-A tail. New:
the gap from the predecessor's ink bottom shrinks by a constant −5.98 /
−6.02 px, which locates #250's −6.14 px residual in the **last line's
advance**.

**(b) 7/17 pages — the predecessor draws nothing.** nrf p2 is the
corpus's only holdout-shaped case: +102.40 px = 2 × 2560 HWPUNIT, nothing
re-broken. The cache seats two trailing empty paragraphs at vertpos 71630
against a 71436 body box — past the page bottom, both on the *same*
seat — while the flow pass paginates them. Named as "an inkless paragraph
does not force a page"; **not fixed**: one boundary on one form
(`cache_seat_past_page_bottom` is false on the other six), it does not
touch the 10/17 text pages, and pagination changes page counts.

**Scoreboard, 144 dpi, before → after identical:** cache 0.6458 / 0.8309
/ 0.2762 / 0.8362; computed 0.6339 / 0.8243 / 0.2774 / 0.8478 (IoU / ssim
/ ssim_inked / pair). All ten per-form JSONs byte-identical under both
policies; render-check-01 9/9 pages, 6·37·6·2 at 96 dpi and 14·31·4·2 at
144.

**Evidence:** `py_compile_sweep` 106/0; engine/tests 1323 passed / 135
skipped; pins + package + cleanroom + floors 170 passed; `test_layout_
divergence` 70. **Full gate on this tip (`6b62e74`):** `tests` 479 passed
/ 7 skipped / 0 failed (5m36s); `pipeline/tests` 1435 passed / 10 skipped
/ 0 failed (10m14s). 0 failed overall. archive privacy HARD=0.

**Not proven:** nrf is one boundary; the inkless rule is inferred from
its cache, not quoted from KS X 6101 / OWPML; the −6 px shortfall is
located, not explained; page membership by enclosure is an inference;
ink-vs-advance bottom readings never separated on the corpus.

### #255 — the anchored-object fix, and a new block-height-0 finding

**One hypothesis closed with a public minimal case and a test.** Path B
vs path A, 144 dpi; path C (Hancom) NOT RUN.

**Seat pass.** `layout_divergence.py` now compares the *seat* of every
top-level paragraph, inkless ones included, decomposed into Δ(previous
seat) + Δ(previous advance) + Δ(gap). Corpus carriers: page_move 16,
d_prev_advance 11, page_top 4, d_gap 1. Six forms have no first-seat
divergence; kstartup / moel-2013 / moel-2025 show ±1–3 HWPUNIT (the known
PERCENT residual); **nrf p1 para 33 −276 HWPUNIT via `d_gap`** is the
only substantive one.

**Mechanism and fix.** nrf para 0 anchors a table (height 63674,
`outMargin` 138, `vertOffset` 0); the cache seats para 33 at 63950 = 0 +
138 + 63674 + 138. `_anchor_extent` reserved `vertOffset + height` only —
it dropped `hp:outMargin`, which `_object_origin` / `_object_extent` /
`_line_metrics` already honour. **Fix:** slot = `vertOffset + top +
height + bottom`. Five own_render tests pin it. Public reproduction
(`measure_seat_probe.py`, path A absent): outMargin 141 → +282, 283 →
+566, both matching the analytic expectation exactly; five previously-
correct cases stayed unchanged.

**Measured, 144 dpi, before → after identical on the scoreboard:** cache
0.6458 / 0.8309 / 0.2762 / 0.8362, computed 0.6339 / 0.8243 / 0.2774 /
0.8478; page counts unchanged. Seat channel: nrf differing seats 10 → 7,
the −276 gone. The fix moved no ink on the corpus — the seat channel and
the synthetic probe are what confirm it.

**Found, recorded, not fixed:** an empty paragraph with **no cached
lineseg** gets block height **0** from `_flow_lines` (1600 HWPUNIT each
on the probe) — its line spacing and charPr height do nothing. No
reference measurement yet; named as the obvious next hypothesis for the
development-validation document's inkless runs.

**Development-validation document (private, reused; aggregate only), 96
dpi, seat pass, path B vs path A.** All 17 pages' first seat divergence is
`page_top` — the first paragraph seated on a page sits lower under
computed, offset accumulating: 1800, 1800, 3600, 3600, 5400, 6840, 9000,
9362 HWPUNIT on pages 2–9, then 17 000–34 000 on pages 10–18 where inkless
runs join in. **First case (page 1 → 2), in numbers only:** the last text
paragraph on page 1 has 7 lines at pitch 1800 (vertsize 1000 + spacing
800, 180 %), usable body height 70864; the cache keeps 6 lines — its
sixth line's box overhangs the body by **566 HWPUNIT** — and seats the
7th at page 2 top (1800); computed keeps 5, puts 2 on page 2, next
paragraph starts at 3600, the +1800. **Hypothesis for the next slice:** a
page-bottom fit rule where Hancom keeps a line whose overhang is smaller
than its full extent — public-spec-checkable against the corpus's many
cached page breaks first, a minimal Rigorloom probe second, path C
(Hancom) not run.

**Evidence:** engine/tests 1353 passed / 135 skipped; pins + package +
cleanroom + floors 170 passed; `py_compile_sweep` 106/0; archive privacy
HARD=0. **Full gate on this tip (`10717da`):** `tests` 483 passed / 3
skipped / 0 failed (13m15s); `pipeline/tests` 1437 passed / 8 skipped /
0 failed (13m27s). 0 failed overall.

**Not proven:** two anchored objects carry the rule (both `TOP_AND_
BOTTOM`, offset 0, `vertRelTo PARA`); path C never run; seat pass is
top-level only; 16 of 32 carriers are `page_move`, undecomposed.

### #256 — bracketing the fit rule, no fix

**Measurement and a costed proposal — no renderer code changed.** Path A
brackets, path B probe; path C NOT RUN.

**The bracket.** `page_fit_probe.py --corpus` reads every cached page
break on the ten public forms (41; none inside a paragraph) and, after
excluding forced breaks, keepWithNext, whole-table and anchored-object
pages, keeps 27 kept-line and 5 rejected-line events (kstartup 19,
moel-2013 6, moel-2025 6, saeopja 5, nrf 3, jumin 2). Six candidate fit
measures scored by largest kept overhang vs smallest rejected overhang:
`top` (kept −1368, rejected **−445**, 4 violations), `vertsize − spacing`
(−720 / +395, 0), `vertsize // 2` (−868 / +255, 0), `baseline` (−518 /
+731, 0), `vertsize` (−296 / +911, 0), `vertsize + spacing` (**+1521** /
+1427, 6 kept lines that would not fit).

**What the corpus decides.** `top` and `vertsize + spacing` are refuted;
between them the corpus is silent — no public page keeps a line whose box
crosses the margin (strictest survivor's kept max −296). The one private
page from #255 (slack 434) additionally rules out `vertsize // 2`,
`baseline` and `vertsize`, leaving `vertsize − spacing` as the only named
survivor fitting all cases — but `baseline − spacing` and any fraction
0.32–0.43 of vertsize fit the same data: it picks a band, not a formula.
Probe (45 paragraphs, margin swept): the flow pass today matches exactly
`baseline`.

**Fix not applied.** No corpus case in the ambiguous band; the upper
bound rests on one private page; no KS X 6101 / OWPML text names the
measure. Landed as a costed proposal (one return in `_row_extent`, one
assertion), not shipped.

**Development-validation document (private, reused; aggregate only),
`page_fit_probe.py`, path A only.** 18 pages, 17 cached breaks — **5
inside a paragraph** (the corpus has none), 12 between paragraphs; usable
height 70864 on every page, no header/footer/footnote, all breaks
unforced, no keepWithNext. No candidate fits every event (k!/r! = kept-
that-would-be-refused / rejected-that-would-be-kept): top 0/5,
`vertsize − spacing` 0/1, `vertsize // 2` 1/1, `baseline` 2/0, `vertsize`
2/0, `vertsize + spacing` 8/0. The two that matter: **`vertsize`**, kept
max **+566** (a 1000/800 line at 70430 stays), rejected min **+626** (a
1000/800 line whose would-be top is 70490, after a 900/720 last line at
68870, moves) — a band of 60 HWPUNIT around **+600**, not 0;
`vertsize − spacing`, kept max −234, rejected min −174 — the same two
events, contradicting by the same 60. Two readings, and the corpus alone
cannot separate them (no public page keeps an overhanging line): (1) the
fit allows a fraction ≈0.6 × vertsize (no spec basis), or (2) the usable
body height is short by ≈600 HWPUNIT for this section geometry — a
public-spec-checkable page-geometry derivation error, named as the next
slice.

**Evidence:** `py_compile_sweep` 107/0; engine/tests 1369 passed / 135
skipped; pins + package + cleanroom + floors 170 passed; new probe tests
16; archive privacy HARD=0. **Full gate on this tip (`765c5f2`):** `tests`
480 passed / 7 skipped / 0 failed (10m45s); `pipeline/tests` 1435 passed
/ 10 skipped / 0 failed (14m13s). 0 failed overall. **Disclosed:** a
first run of the same tip reported 1 failed + 36 errors (`tests`) and 10
failed (`pipeline/tests`), every one `OSError: [Errno 28] No space left
on device` (the bench's C: drive had 0.49 GB free); space was recovered
without deleting anything (a 5.7 GB Windows Remote Desktop trace folder
and one cache junction-moved to another drive); no code changed between
the two runs; the green numbers above are the rerun.

**Not proven:** no intra-paragraph break exists in the corpus; the `top`
refutation rests on 4 events from one form; one private page cannot
separate `vertsize − spacing` from `baseline − spacing`; `vertsize ==
textheight` on every corpus lineseg so those columns are indistinguish-
able; path C run nowhere.

### #257 — the body box is right, and the line that justified the fit test never existed

**Reading 2 from #256 — "usable height short by ~600 HWPUNIT" — refuted
on the public corpus. No renderer code changed.**

**pagePr per form**, top/bottom/header/footer → body_top/usable checked
against the deepest cached line bottom Hancom actually placed on all ten
forms; the three apparent overflows are non-evidence (nrf's are inkless
trailing paragraphs, moel-2013's are `pageBreak="NONE"` tables that
cannot split, saeopja's is a whole-table row taller than the page).
**Offset scan** (jointly zero violations): only kstartup bounds from
above — `vertsize` [−296, 911), `baseline` [−518, 731); the private band
[566, 626) lies inside both, so path A alone cannot decide.

**`--reference-ink` decides it.** Reading Hancom's own PDF ink against
our derived body box: saeopja page 1 (a full-page table) rules to
81343 — **11 HWPUNIT inside** our body bottom 81354; a +600 offset would
miss it by 611. Ink tops confirm `body_top = top + header` to ≥ −82 on
every form; kstartup, footer margin 2936 with **no `hp:footer`**, rules
to −152 — the footer band is reserved even without a footer, matching
spec (edge → top → header → body → footer → bottom, unconditional on
content). Alternative derivations (footer not reserved without a footer,
footer never reserved, body to bottom margin, header not reserved) are
each excluded by the same scan or by contradicting the measured ink
tops. **No fix; bands recorded.** What remains is reading 1 — Hancom's
page-bottom fit test tolerates part of a line — to be checked against the
development-validation PDF's own ink.

**Development-validation document (private, reused), Hancom ink read
directly from its PDF with PyMuPDF, numbers only.** Package saved by
Hancom Office Hangul 13.0.0.2986 at 04:20, PDF written at 04:21 — one
minute apart, same application. pagePr-derived usable height 70864,
matching the probe; the probe's text column offset (+2753 every page) is
the footer-band page number, not body text.

**The "+566 kept" event does not exist in the PDF.** The cache splits
the paragraph into 7 linesegs — 5 on page 1 (61430…68630), a 6th at
70430 (box to 71430, +566 past the body), a 7th at vertpos 0 on page 2.
The PDF draws the same paragraph in **6** lines: 5 on page 1 whose tops
match the cache to −75…−83 HWPUNIT (glyph box vs line box) and one at the
top of page 2 — no exported line sits where the cache's 6th would be.
Character counts settle it: 53+53+54+54+54 = 268 on page 1 plus 50 on
page 2 = 318, the paragraph's full count. The next paragraph then starts
at **+1792** on page 2 in the PDF — matching the **cache's** seat (1800),
not computed's (3600).

**What this means.** (1) Reading 1 ("Hancom's fit test tolerates ~0.6 ×
vertsize") rested on a line the PDF never drew — **withdrawn**. Hancom's
save-time layout placed a line box past the body bottom, but its
export-time layout broke the paragraph differently and produced no such
line. (2) For this document, the cached lineseg and the reference PDF
are **two different Hancom layout passes** of the same text (7 vs 6
lines) — path A is not a proxy for the PDF here. (3) computed's +1800
page-top drift is still wrong against the PDF: the PDF seats the next
paragraph at 1800, like the cache, not at computed's 3600.

**Next measurable question (in flight, public):** does Hancom's exported
PDF reproduce the saved lineseg, per paragraph, on the ten corpus forms —
cached line count and character split vs the PDF's text lines? The
pair-rate channel (0.836) already hints some do not.

**Evidence:** `py_compile_sweep` 107/0; engine/tests 1376 passed / 135
skipped (base 1369 + 7 new); pins + package + cleanroom + floors 170
passed; archive privacy HARD=0. A first engine run showed 2 failed / 256
errors from a concurrent pytest process in the same repo; the isolated
rerun was clean and stands. **Full gate on this tip (`5dad979`):**
`tests` 484 passed / 3 skipped / 0 failed (12m52s); `pipeline/tests` 1437
passed / 8 skipped / 0 failed (11m59s). 0 failed overall.

**Not proven:** the −11 HWPUNIT reading rests on one page (kstartup −152
is the second); it is a table's ruling, not a text line; the private
geometry was not read by the worker directly; `gutter` (0 on every form)
is unapplied and ungraded.

### #258 — the export reproduces the lineseg; our own reader miscounts control cells

**Measurement only — `own_render.py` byte-identical to base.** Does
Hancom's exported PDF reproduce its saved lineseg? On the public corpus:
yes, exactly.

`lineseg_vs_pdf.py --corpus` pairs each cached `hp:lineseg` record with
the reference PDF's text lines (PyMuPDF), matching by concatenated text,
and compares line count, per-line character split, page membership and
vertical position.

| form | paragraphs compared | equal | more cached | fewer cached | chars in agreeing lines |
|---|--:|--:|--:|--:|--:|
| admrul | 9 | 9 | 0 | 0 | 100 % |
| kstartup | 67 | 67 | 0 | 0 | 100 % |
| moel-2013 | 134 | 134 | 0 | 0 | 100 % |
| moel-2025 | 172 | 172 | 0 | 0 | 100 % |
| nrf | 29 | 29 | 0 | 0 | 100 % |
| gianmun-1ho/2ho, jeongbo, jumin, saeopja | 0 (all text in table cells) | | | | |
| **all** | **411** | **411** | **0** | **0** | **8566 / 8566** |

Zero split divergences, identical page partition on every form; `dy` is a
per-form constant (line-box top above glyph top) with a 7–21 HWPUNIT
residual. **The export does not re-flow.** render-check-01 cannot answer
the question (Rigorloom-authored, carries no `linesegarray`, 107
paragraphs skipped).

**The bug the first run exposed.** A first pass showed 18 "re-breaks,"
all at line 0, 17 by exactly one character, all one direction — too
uniform to be Hancom. `hp:lineseg@textpos` counts a stream in which
`hp:lineBreak` (× 30 in the corpus), `hp:tab` (× 15) and `hp:fwSpace`
(× 8) each occupy a cell, while `Paragraph.chars` (built from
`itertext()`) does not carry them; `OwnRenderer._render_cached_lines`
slices `chars` at those `textpos` values, so **21 of the corpus's 161
multi-line paragraphs are drawn with a character on the wrong side of a
break** (moel-2025 17, kstartup 2, admrul 1, jeongbo 1) — the same family
as the documented `textpos_past_end`. Recorded, not fixed here; named as
the next slice, with a public basis.

**Development-validation document (private, reused; aggregate only),
same tool, `--no-text`.** 127 top-level text paragraphs compared (skipped:
70 inkless, 27 table, 11 object, 8 no PDF match). Line counts: **122
equal, 5 with one MORE cached line than the PDF** (4→3, 5→4, 4→3, 7→6,
7→6; 127–274 characters each), 0 fewer — one of the five is the 7-vs-6
paragraph from #257. Of the 122 equal-count paragraphs, **40 differ in
the character split**, and every listed first divergence is ±1
character — the signature of the control-cell reader bug, so these are
**consistent with**, not yet shown to close by, the fix. Characters in
agreeing lines 3530 / 10564 (33.4 %); paired lines 309, median |dy| 59
HWPUNIT.

**What is new here versus the corpus:** the corpus has 0 line-count
mismatches in 411 paragraphs; this document has 5 in 127. A cell
miscount cannot change a line count, so these five are a genuine
save-vs-export difference for this document — Hancom's export set five
paragraphs one line shorter than the seats it saved a minute earlier.
Cause unknown; candidates are export-time font resolution (a different
face or advance table than the editor used) or a display-vs-print metric
difference. This is the first evidence in this line that path A and the
export can disagree on line count, confined so far to one private
document — **not** the re-flow the corpus ruled out for its own forms.
Next: after the cell fix, re-run here, then compare the five paragraphs'
declared faces against the PDF's embedded fonts.

**Evidence:** `py_compile_sweep` 108/0; engine/tests 1410 passed / 135
skipped; pins + package 85 passed (new file 34); archive privacy HARD=0.
**Gate on this tip (`8c35105`): the `tests` piece was reported running at
time of writing, to be appended to #258 — not claimed green here.**

**Not proven:** five forms contribute nothing (all-table) and table
cells were never compared, where most corpus text lives; 306 of 411
paragraphs come from two near-identical contracts; the visual-line
regrouping threshold is a judgement call; 100 % is a character share, not
glyph placement; one machine, one Hancom build.

### #248 — correction, no new work

No new PR. A comment on the existing #248 corrects its own evidence
line: the 551/0 desktop smoke reported at checkpoint-13 ran against the
**pre-built** desktop exe and sidecar, which do not contain this
branch's merged renderer. It proves the merge did not break the
checked-in smoke harness; it is **not** evidence that the app built from
this source combination renders or edits correctly. That claim stays
open until a build from `8a56ada` runs the smoke. The pytest lines
(engine/tests, `tests`, `pipeline/tests`) reported at checkpoint-13 ran
on the tree itself and stand unaffected.

### #253 — the LayoutSnapshot proposal

**Proposal only — no code, no protocol change**, cut from checkpoint-13
(not this checkpoint's chain). `docs/research/layout-snapshot-proposal.md`
defines a small versioned `LayoutSnapshot` (schema version, document
revision, renderer build, geometry schema id, layout policy/reason/
provenance, font manifest, page/line/cell/character mapping, skipped
elements, PNG + sidecar digests), a glossary fixing `x1` (geometry box)
vs `x1_advance` (caret box) against the #245/#248 test fixes that mixed
them, and support levels A (cached lineseg) / B (re-layout, no cache) /
C (edited candidate vs a licensed Hancom output) kept explicitly
separate — stating plainly that **no level-C run exists**. Ownership
split: renderer implementation on this line; `rt_own` / Desktop UI / IPC
named as a separate agreed task. Everything stays `own-uncertified`.

**Evidence:** `py_compile_sweep` 105/0; archive privacy HARD=0 (a first
pass flagged the leftover tarball itself; re-extracted clean). Depends
on #251 (checkpoint-13). No comments as of this checkpoint.

## 3. The development-validation document arc, across #255 → #256 → #257 → #258

Aggregate-only, no name or text from the document quoted anywhere below —
this is the same private, repeatedly-reused holdout named in prior
checkpoints, not independent unseen data.

- **#255:** first-seat divergence on all 17 pages is `page_top`,
  cumulative drift growing page over page (+1800 on page 2 up through
  +9362 on page 9, +17 000…+34 000 once inkless runs join in on pages
  10–18). The first case is traced to the cache keeping a line whose box
  overhangs the usable body by +566 HWPUNIT — the number that then drives
  #256's hypothesis.
- **#256:** that same +566 overhang (kept) sits against a +626 overhang
  (rejected) 60 HWPUNIT away — a band around +600, not 0 — motivating a
  permissive page-bottom fit rule as one reading, and a ~600 HWPUNIT
  usable-height shortfall as the other. Neither is resolvable from the
  public corpus alone.
- **#257:** the shortfall reading is refuted by reading Hancom's own PDF
  ink on the public corpus (body box right to ≤ 11 HWPUNIT). Then, reading
  the same document's own Hancom-exported PDF directly: **the +566 line
  does not exist there.** The cache's 7-lineseg split of that paragraph
  is not what Hancom exported — the PDF draws it in 6 lines, none past
  the body — so the "kept overhanging line" that motivated the entire
  fit-rule hypothesis was an artifact of comparing the cache against
  itself, not a real Hancom fit tolerance. The hypothesis is withdrawn.
  What the PDF does confirm: computed's own +1800 page-top drift is wrong
  against the PDF too (the PDF agrees with the cache's seat, not
  computed's).
- **#258:** redirects the question from "what does Hancom's fit rule
  tolerate" to "does the cache match what Hancom exported at all." On
  this document, 122 of 127 compared paragraphs agree on line count; 5
  do not (one is the #257 paragraph), a genuine save-vs-export
  difference, cause unknown. Of the 122 agreeing on line count, 40 also
  differ in character split by exactly ±1 character — the same signature
  as the control-cell reader bug #258 found and fixed the corpus's
  version of, so those 40 are **consistent with** that bug, not yet shown
  to close by it. In short: 45 of the 127 compared paragraphs show some
  divergence — 40 plausibly ours (the reader bug), 5 apparently
  Hancom's own save-vs-export difference, not export re-flow of the kind
  the corpus ruled out for its own forms.

Net effect on the standing research question: the fit-rule line of
inquiry did not fail to find an answer — it found that its own evidence
was a comparison artifact, and closing it redirected the whole chain
toward the lineseg-reading bug that #258 now has to fix first.

## 4. Regressions (with the PR's or commit's own explanation)

**None newly introduced this window, by the PRs' own accounting.** #252
changes no render code and reports its scoreboard byte-identical before
and after. #255's `outMargin` fix moves the seat channel only in the
correct direction (nrf's differing seats 10 → 7) and leaves the
raster scoreboard byte-identical; five own_render tests and a public
probe pin it. #256 is "measurement and a costed proposal — no renderer
code changed," its own words; the disk-full first run it discloses is an
environment failure with `OSError: [Errno 28]`, not a code regression,
and the PR says so explicitly before reporting the clean rerun. #257 is
"no renderer code changed" and reports its own `own_render.py` diff as 0
lines; a first engine-test run's 2 failed / 256 errors is attributed to a
concurrent pytest process in the same repo, not to this PR's change, and
the isolated rerun is clean. #258 reports `own_render.py` byte-identical
to base — its finding is a pre-existing reader bug it discovered, not one
it introduced. The fit-rule hypothesis withdrawn in #257 was never
shipped as code (#256 explicitly did not apply its proposal), so its
withdrawal closes an open question rather than reverting a regression.

## 5. Unsupported / declared elements still open

Carried from checkpoint-13, with this window's closures, redirections and
new items:

- **Closed since checkpoint-13:** the anchored-object `outMargin`
  omission that produced nrf's −276 HWPUNIT seat gap (#255, fixed and
  tested); #250's −6.14 px class-A residual is now located in the
  predecessor's last-line advance, though not itself corrected (#252).
- **Opened and then withdrawn within this same window:** the page-bottom
  fit-rule hypothesis (#256) — its private evidence, a "+566 HWPUNIT
  kept-line overhang," turned out not to exist in that document's own
  Hancom-exported PDF (#257); the usable-body-height-short-by-600 reading
  that would have explained the same overhang differently was also
  refuted, on the public corpus, before the withdrawal. Neither reading
  survives; #256's costed `_row_extent` proposal was never applied and
  should not be revisited on this basis. Replacement question named and
  taken up immediately: whether Hancom's export reproduces its own saved
  lineseg (#258).
- **New, found and partially addressed:** our own cache reader's
  control-cell mis-slicing (`hp:lineBreak` / `hp:tab` / `hp:fwSpace`
  occupying a `textpos` cell that `Paragraph.chars` does not carry),
  21 of 161 corpus multi-line paragraphs mis-split — recorded, fix named,
  **not yet shipped** (#258).
- **New, found, not fixed:** an empty paragraph with no cached lineseg
  gets block height 0 from `_flow_lines`, ignoring its own line-spacing
  and charPr height (#255) — the obvious next hypothesis for the
  development-validation document's inkless runs, still unmeasured
  against a reference.
- **New, found, not fixed:** the paragraph-before-the-drift mechanism
  where a predecessor that draws nothing (two trailing empty paragraphs
  sharing one cache seat past the page bottom) displaces pagination —
  one boundary case on one form (nrf), not generalized (#252).
- **New, named, not resolved:** computed layout's own +1800 page-top
  drift against the development-validation document disagrees with both
  the cache and Hancom's exported PDF, which agree with each other
  (#257) — still open.
- **New, named, not yet run:** the development-validation document's 5
  genuine save-vs-export line-count differences (cause unknown: export-
  time font resolution vs a display/print metric difference) — flagged
  for after the control-cell fix (#258).
- **New, corrected:** the desktop's 551/0 smoke result is not evidence
  for the merged-source build; that evidence does not exist yet (#248
  comment).
- **New, proposed, not agreed:** the `LayoutSnapshot` contract and `x1`
  glossary (#253) — awaiting response from the Codex line; no level-C run
  exists anywhere in this project.
- **Unchanged from checkpoint-13, still fully open:** the holdout's
  underlying computed-vs-cache line-IoU gap; the full-width-advance
  line-box fix #242 costed and refused (no mechanism yet to get the gain
  without the loss); the acceptance harness's lexical-reader fix for
  header/footer text (#235's queued item); Codex-app-closed sessions
  moved; Cursor login; `hp:ole`/`hp:chart`/`hp:container`/shapes/
  undecodable EMF-WMF placeholders; `DOUBLE_SLIM` border limitation;
  `hp:parameters` family; `hp:autoNum` inside a footer draws nothing
  (`F51`); `hh:tabPr` stops inside the MCE switch never read; the tier-3
  raster's own `own-uncertified` status; Hancom's first-column endnote
  placement in a two-column section; `textpos_past_end` on three
  unedited corpus forms (pre-existing, not fixed); `layout_policy` /
  `layout_policy_reason` still not surfaced in the desktop UI (#248's own
  words, unaddressed this window); the ±2 HWPUNIT `PERCENT` spacing
  residual (883 lines, #247) — unexplained and untouched this window.

## 6. Tests actually run per PR (from PR bodies and comments)

| PR | orchestrator / own suite | full gate | notes |
|---|---|---|---|
| #252 | engine/tests 1323/135 skipped; pins+package+cleanroom+floors 170; `test_layout_divergence` 70 | **`tests` 479/7/0 + `pipeline/tests` 1435/10/0 — 0 failed overall** | `py_compile_sweep` 106/0; archive privacy HARD=0 |
| #255 | engine/tests 1353/135 skipped; pins+package+cleanroom+floors 170 | **`tests` 483/3/0 + `pipeline/tests` 1437/8/0 — 0 failed overall** | `py_compile_sweep` 106/0; archive privacy HARD=0 |
| #256 | engine/tests 1369/135 skipped; pins+package+cleanroom+floors 170; new probe tests 16 | **`tests` 480/7/0 + `pipeline/tests` 1435/10/0 — 0 failed overall** (rerun; first run disk-full, disclosed) | `py_compile_sweep` 107/0; archive privacy HARD=0 |
| #257 | engine/tests 1376/135 skipped (base+7 new); pins+package+cleanroom+floors 170 | **`tests` 484/3/0 + `pipeline/tests` 1437/8/0 — 0 failed overall** (isolated rerun; first run's 2 failed/256 errors attributed to a concurrent pytest process) | `py_compile_sweep` 107/0; archive privacy HARD=0 |
| #258 | engine/tests 1410/135 skipped; pins+package 85 (new file 34) | **`tests` piece reported running at time of writing — appended to #258, not claimed green here** | `py_compile_sweep` 108/0; archive privacy HARD=0 |
| #248 (comment only) | unchanged from checkpoint-13 | unchanged from checkpoint-13 | correction is evidentiary (smoke scope), not a new test run |
| #253 | none (docs only) | none | `py_compile_sweep` 105/0; archive privacy HARD=0 |

Every renderer-line PR through #257 reports its own landed, zero-failure
full-gate comment. #258 is the first PR in this line since checkpoint-12
whose full gate is **not yet confirmed green** at the time this
checkpoint was written — its `tests` piece was still running, to be
appended to the PR itself.

## 7. Integration conflicts expected when lines converge

**Renderer line did not converge siblings this window — it extended
linearly, same shape as checkpoint-13.** #252, #255, #256, #257 and #258
each forked from the immediately preceding PR, so there was no merge to
perform and no textual or semantic conflict between them.

**Desktop did not move this window** — no new PR, only a corrective
comment on #248. It remains merged onto #245 and is now **six** renderer
slices behind the tip (#252, #255, #256, #257, #258 landed since #248),
wider than checkpoint-13's three.

**Docs branched off checkpoint-13, not this checkpoint's chain** — #253
sits beside this window's renderer work rather than on top of it; no
conflict expected until the Codex line responds and any resulting change
needs to reconcile with #258's tip.

**Writer and renderer lines remain unconverged**, unchanged from
checkpoint-13.

**Runtime line is untouched and unconverged with anything**, unmoved
since #204 (checkpoint-06).

## 8. Next measurable research question

**The control-cell reader fix, then the empty-paragraph-without-lineseg
block height, then computed's page-top drift against the PDF — in that
order, as named by the PRs themselves.** #258 found the mechanism
(`hp:lineBreak` / `hp:tab` / `hp:fwSpace` occupying a `textpos` cell that
`Paragraph.chars` does not) but did not ship the fix; the first
measurable question is whether that fix brings the corpus's cached line
splits to 411/411 exactly matching the PDF's character split (not just
line count) and moves the 21 mis-split paragraphs toward agreement.
Second, #255's empty-paragraph-with-no-cached-lineseg block-height-0
finding has no reference measurement yet and is named as the likely
explanation for some of the development-validation document's inkless-
run drift. Third, #257 leaves computed layout's own +1800 page-top drift
against the development-validation document's Hancom-exported PDF
unresolved — the PDF agrees with the cache's seat, not computed's, so
this is now a genuine computed-layout defect independent of the
withdrawn fit-rule question. None of the three is measured yet.

## 9. Certification status

Every result in this checkpoint — #252 (paragraph-bottom mechanisms),
#255 (anchored-object fix + block-height-0 finding), #256 (fit-rule
bracket, unapplied), #257 (usable-height refutation + hypothesis
withdrawal), #258 (export-reproduction measurement + reader-bug finding),
#248 (evidentiary correction only), #253 (proposal only) — remains
**own-uncertified**. #255 is the only PR this window that changes
`own_render`'s behavior (the anchored-object extent), and it changes no
certified renderer surface; #252, #256, #257 and #258 are measurement-
only by their own statements. `render_cert.py` still cannot certify this
renderer absent a PDF text layer, unchanged since checkpoint-01.

**What moved, restated plainly:** this window closed one genuine
mechanism (the anchored-object `outMargin` omission), decomposed but did
not close checkpoint-13's headline open question (the paragraph-bottom
height addition, now two named mechanisms), and then produced and
discharged its own hypothesis the same way checkpoint-13's chain did:
#256 proposed a page-bottom fit rule from a private overhang measurement,
and #257 found that the overhang itself was a comparison artifact — the
line it rested on was never in Hancom's own exported PDF — withdrawing
the hypothesis rather than shipping it. That withdrawal immediately
redirected the chain to a more basic question (does our cache reader
even read the saved lineseg correctly), and #258 answered it partially:
Hancom's export reproduces the saved lineseg exactly on the public
corpus, but our own reader has a control-cell mis-slicing bug that the
fit-rule investigation's noise had been standing in for. The renderer
line again moved as a single measured chain, not parallel siblings, with
each link's own full gate landing green — except the current tip, whose
gate was still running at write time.

**Owed, carried forward from checkpoint-13, plus this window's
additions:**

- The control-cell reader fix (#258, in flight) — bring cached splits to
  411/411 against the PDF and move the 21 mis-split paragraphs toward
  agreement.
- The empty-paragraph-with-no-cached-lineseg block-height-0 finding
  (#255) — no reference measurement yet.
- Computed layout's own +1800 page-top drift against the development-
  validation document's Hancom-exported PDF (#257) — unresolved, now
  independent of the withdrawn fit-rule question.
- The development-validation document's 5 genuine save-vs-export
  line-count differences (#258) — cause unknown, to be re-examined after
  the control-cell fix.
- The paragraph-before-the-drift "predecessor draws nothing" mechanism
  (#252) — one boundary case (nrf), not generalized.
- #258's own full gate — reported running at write time, to be appended
  to the PR; not to be treated as green until that comment lands.
- The desktop's build-from-merged-source smoke evidence (#248) — does
  not exist yet; still owed.
- The `LayoutSnapshot` proposal (#253) — awaiting the Codex line's
  agreement or amendment; no level-C run exists anywhere.
- `layout_policy` / `layout_policy_reason` surfaced in the desktop UI —
  still not a branch or PR.
- Desktop line (#248) re-merged onto the renderer's current tip (#258) —
  last done at #245, now six slices stale.
- The ±2 HWPUNIT `PERCENT` spacing residual (883 lines, #247) — shown,
  not explained, untouched this window.
- The acceptance harness's lexical-reader fix for header/footer text
  (#235's queued item) — still not a branch or PR.
- Codex-app-closed sessions moved; Cursor login — both carried, not
  addressed this window.
