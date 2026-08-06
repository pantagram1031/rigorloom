# Variant audit — decision matrix (Phase 0.C output)

Executed 2026-08-06 per `docs/plans/v0.16-prep-variant-audit.md`. All five
benches ran on existing artifacts — zero pipeline reruns, zero workspace
mutations, COM leg deferred (R5, concurrent-session risk). Raw bench reports
live in the private workspace: `agenthwpx/work/bench1-gate-crossfire.md`,
`bench2-humanize-instruments.md`, `bench3-assembly-offline.md`,
`bench45-resume-provenance.md`. Operator inputs: visual verdict on three
before/after pairs (2026-08-06, approvals ledger) and the standing approvals
ledger (`agenthwpx/docs/operator-approvals.md`).

Variants: **A** pre-rigorloom v0.6 · **B** rigorloom stage machine (v0.12.4
holdout run) · **C** sambal supervised · **D** hawkes night+local toolbox ·
**E** windpath stateless. Humanization: **H1** humanizer subagent · **H2**
`score_ai_tells` · **H3** humanize_metrics v2.0 · **H4** corpus rulepack ·
**H5** manual structural fix.

## Headline measurements

- **Resume steps** (B4): B=2 · D=2-to-a-false-"done"/6-to-truth · E≈5
  (unverifiable, mtime guessing) · C=6 · A=7. **All five variants' recorded
  state diverged from reality** — each differently.
- **Provenance cold-read** (B5): B 6/6 · D 6/6 (CSV+code pack matches body
  numbers to 3 decimals, verified by recomputation) · C 3/3 · A PARTIAL
  (value-matching only) · **E 0/3 LOST** (J=0.19414, p=0.199, 672-run figure
  exist nowhere upstream of content.md).
- **Gate cross-fire** (B1): E's text_absent caught the one real live defect
  (sambal placeholder byline + abstract label) at 0 FP on clean substrates but
  missed `최선덕` (hand-list) and failed one home-turf check (pins superseded
  v5). B has **zero coverage** of residue/byline/H5 across its 9 checkers,
  plus FP noise (226 `unbacked_numeral` on windpath alone) and a hardcoded
  stale path that silently no-op'd. tone_check cross-fires cleanly but is a
  different axis. T22 dangling-charPr: clean on all four finals.
- **Assembly offline** (B3): windpath preedit→postedit chain fully idempotent
  (run1=run2 content-identical, itemCnt declared 38 = actual 38, residue 0,
  dangling 0, protected paras 3/3). Hawkes `sim/preedit_official.py` has a
  live defect (trailing-space breaks the abstract-label match) — inert only
  because production used `work/preedit_form.py` (byte-identical across the
  two reports). `sim/` vs `work/` duplication is a real hazard, not cosmetic.
- **Humanize instruments** (B2 + direct pre/post test): on the most-changed
  section of windpath (similarity 0.747 pre→post), `score_ai_tells` returns
  **interference 0.1 for both** — zero discrimination. Only micro-signals
  moved (`conclusion_pivot` 1→0: the humanizer removed a "따라서" pivot,
  consistent with rulepack rule). No instrument sees structure (H5 class).
  H3's generator does not exist in either repo (server-side snapshot).
- **Shared bug found** (B4 bonus): `converged:true` + `status:escalate_human`
  self-contradiction in both B and C verdict files — one shared bug in the
  proof-loop verdict writer. Needs a failing test before any adoption (R2).

## Decision matrix

| capability | verdict | evidence | loss ledger (R3) |
|---|---|---|---|
| **Form preprocessing** | Adopt `work/preedit_form.py` (dict-based, byte-identical across D/E) + E's normalizing postedit, into the engine with the T18 protection guard (already landed: hwp-master `guards.py`). Retire `sim/preedit_official.py` variants. | B3: work/ correct; sim/ hawkes defect; E chain idempotent | Lose: nothing — retired copy is a defective duplicate. |
| **Edit shape** | Three-phase offline XML (preedit → assemble → postedit, normalizing+idempotent) = core's supported edit shape. COM remains the render/proof oracle, not the edit path. COM leg re-verified in W2 tests when no concurrent session. | B3 all-pass; prior parity work (COM = submit grade) | Lose: COM-first in-place editing convenience; acceptable — it was the T6–T11 trap surface. |
| **Gate architecture** | **Hybrid**: mechanisms live in a registry (B's infra), *values* declared per workspace (E's gates.yaml), and residue/placeholder lists **auto-derived from the form scan** (form_profile anchors + guide-text inventory) instead of hand-written. Every gate binds to a canonical artifact pointer and **fails loudly when the pinned target is missing** (both B and E rotted silently). | B1 both-systems-rot finding; operator correction ("스캔이 아는 것 = 게이트가 검사하는 것") | Lose: E's 30-line simplicity (runner grows binding logic); accepted — silent rot cost a home-turf failure. Lose: B's central-only control; accepted — 226 FPs on one doc. |
| **State & resume** | Two run modes (R4, per plan §3.2). **unattended/night** = full stage machine — it measurably wins (resume=2 steps, receipts never silently contradicted reality). **supervised-lean** = E-shape *plus mandatory minimums*: validated `canonical_output`/FINAL pointer, auto-residue gate, provenance pack. Plus one new mechanism both modes need: a **reopen/amend transition after "done"** — every serious state lie lived in post-done work (D's 18.5 h of off-book rework v2→v17). | B4 all-diverged + steps table | Lose: pure statelessness ("conversation as state"); rejected — kill scenario erases operator memory, E took ≈5 unverifiable steps. |
| **Provenance floor** | D's bundle pattern — claim→file sidecar map + data/code pack inside `bundle/` — becomes the **non-negotiable minimum in every mode**, including supervised-lean. State-machine-independent by construction. | B5: D 6/6 verified by recomputation; E 0/3 LOST | Lose: E's zero-overhead research/; rejected — it cost 100% of evidentiary value. |
| **Humanization measurement** | H2 = advisory only, never a gate trigger (0.1→0.1 on a 25%-changed section; its own docstring agrees). H4 rulepack = pack-based pre/post regression check (its rules provably track real humanizer edits — the pivot-removal). H3 = **not adoptable** until its generator is located (server-side vs offline unresolved). Real judgment stays with humanize_review / the humanizer persona pass. | B2 + direct pre/post measurement | Lose: H3's 8-metric z-scores for now; accepted with a follow-up action (locate generator). |
| **Humanization transformation** | H1 humanizer subagent stays the transform (operator-approved, fact-invariant). H5's lesson becomes a *gate*, not a transform: subhead-density/label-echo check at mechanism level — the confirmed shared miss, operator-validated visually ("그 이상한 소제목 안 보이는 것도 좋고"). Still-catches example: windpath pre-fix state (18/40k). | B1 H5 counter; operator visual verdict | Lose: nothing; adds a gate where zero existed. |
| **Layout & density judgment** | Corpus-band structural metrics (07-layout-spec, poster_stats) + the operator visual before/after loop as final arbiter (now standing practice, memory'd). Values are per-form-family only (T17). | B1, operator loop | Lose: fully-automatic layout sign-off; accepted — vision false-alarms already needed deterministic overrule once (pendulum). |
| **Poster generation** | Keep measure-budget-first flow (corpus stats → budget table → draft approval → build). Operator-approved method. | approvals ledger | — |

## Shared-miss list → new-mechanism candidates (each needs still-catches)

1. **H5 subhead-density / guide-label-echo gate** — confirmed zero coverage in
   all systems; still-catches: windpath pre-fix.
2. **Post-done reopen/amend transition** — every variant's worst divergence
   was unrecordable post-completion work; still-catches: hawkes v2→v17.
3. **Canonical FINAL pointer, validated at write** — B wrote literal `"null"`,
   D never named its ship artifact, E marked nothing; still-catches: all three.
4. **Pinned-gate loud failure** — E's gate_result recorded `file_exists=true`
   for a file that isn't there anymore; still-catches: windpath v5 pin.
5. **Verdict-writer contradiction test** (`converged:true`+`escalate_human`) —
   shared bug in B and C; failing test first, then fix.

## Per-form-family applicability (R6)

Margins, forbidden-string lists, and residue vocabularies are family-scoped:
한마당 제본용 / 2026 공식 탐구학술한마당 / 기록지-type measured separately;
auto-derivation from the form scan makes the residue lists per-form by
construction. No numeric value learned on one family transfers (T17 proof).

## Wave 1 Lane V docket (now unblocked)

1. Engine: land `work/preedit_form.py` + normalizing postedit as core ops
   (with T18/T22 guards already merged); delete `sim/` preedit duplicates.
2. Gate runner: registry mechanisms + declared values + form-scan
   auto-derivation + canonical-artifact binding with loud failure.
3. New gates: H5 density, FINAL pointer validation, verdict-contradiction
   test, reopen/amend transition (state schema change — design first).
4. Humanize stack wiring: H1 transform, H4 pack check, H2 advisory; H3
   follow-up = locate generator (pantadex server?).
5. merge_pack/_stable_union regression fix from extension-packs (independent,
   already scheduled).

Overriding any row requires a written counter-measurement (plan rule).
