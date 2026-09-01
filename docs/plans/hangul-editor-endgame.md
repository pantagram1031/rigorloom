# Rigorloom endgame — the definitive open-source Hangul editor

Status: PROPOSED (operator approval required before execution).
Author: Claude Fable 5, orchestrator of the agent-native desktop program.
Date: 2026-09-02.

This plan begins where the current program ends. It assumes the stacked draft
PRs of the agent-native desktop program (#150–#170 and the Phase 6 slice) have
been reviewed and merged; nothing here re-plans that work. It answers one
question: **what must be true for Rigorloom to be the definitive open-source
Hangul editor** — not a viewer with edit bolted on, not an automation runtime
with a face, but the editor a Korean office worker or student opens on purpose,
with an agent inside it that plays by verifiable rules no other editor has.

Written for a reader with no session context. Every claim about current state
below is a measured number from the program's evidence, not an aspiration.

## 0. Where the measured state actually is

What exists and is proven (all as draft PRs, per-slice gates green):

- A Tauri 2 desktop shell with a packaged Python runtime sidecar; open →
  inspect → edit → review queue → human approve → apply-to-candidate →
  verify → export + receipt, one OperationPlan path shared by human and agent
  (smoke: 360 checks/0 failures at Phase 6).
- Live agent loop: composer → Agent Host process (mock / OpenAI-compatible
  router / official Anthropic Messages adapter) → plan into the same review
  queue; the agent cannot approve, structurally, proven from both sides.
  Credentials live in the Windows credential store; the app keeps a reference
  name only (212-file leak sweep clean).
- Page view on real Hancom-rendered rasters, with text geometry mapped to
  editable addresses (refuse-to-guess: unique / candidates / unmapped) and
  empty-seat rects derived from the cell grid Hancom actually drew:
  73 of 473 corpus fill seats placed today, each audited against the render;
  the remaining 400 have named structural causes (§12.6).
- module/check: a distribution module's checkers run against a session in a
  scratch copy, findings/skips honest, agent-safe with the authority resting
  on operator enablement.
- Rigorloom's OWN OWPML renderer (tier 3): fixed-form pages to deterministic
  PNG from the public KS X 6101 standard, `own-uncertified` grade, honest
  skip lists, line breaks exact via the document's cached lineseg layout.
- The report-pipeline engine (the repo's original product) with its gates.

The gap between this and "definitive editor" is the subject of the phases.

## 1. Product thesis

Three claims no existing tool makes together:

1. **Open.** The only serious open-source editor whose native format IS the
   Korean public standard (OWPML / KS X 6101), with a renderer and writer
   built from the spec, never from Hancom binaries.
2. **Honest.** Every displayed page, verdict, and capability carries its
   provenance and grade (`hancom` ground truth / `advisory` / `own-uncertified`
   → `own-certified`). The editor never claims fidelity it hasn't measured.
   This is the differentiator no incumbent can copy cheaply, because their
   architecture assumes trust rather than proving it.
3. **Agent-native.** An AI agent is a first-class user with strictly less
   authority than the human: same document model, same operation plans, same
   verification, never the approve button. Editing with an agent inside is
   the normal mode, not a plugin.

Non-goals, permanent: binary .hwp write support (read-extraction only via
existing lanes); Hancom UI cloning (we build our own identity); cloud
accounts or telemetry (local-first, forever).

## 2. Phase E1 — Type on the page (the editor threshold)

The single feature that separates "editor" from "viewer with forms": free
text editing on the page surface, not just filling seats.

- E1.1 **Caret on the page.** Click any mapped line → a real caret at the
  line box (sub-line offset: measure PyMuPDF char-level spans; where chars
  aren't individually resolvable, snap to line start and say so). Typing
  produces paragraph-edit operations through the same plan path. IME-first:
  두벌식/세벌식 composition tested with real scan codes (harness exists).
- E1.2 **Layout echo.** After apply, the page re-renders from the new
  candidate: Hancom tier when available, own renderer otherwise — with its
  grade visible. The editor stays honest about which engine drew what you see.
- E1.3 **Structural edits** through the same UI: paragraph insert/delete,
  run splitting, charPr/paraPr changes surfaced as named formatting (the
  typeface-name work generalized: sizes, bold/italic, alignment).
- E1.4 **Undo/redo as plan history.** The receipt chain already orders
  operations; expose it as undo that is *provably* the inverse, not a
  parallel state machine.

Exit: a user opens a corpus form, types a sentence into a body paragraph on
the page, sees it laid out correctly, exports, and the receipt binds it —
with zero regressions in the 360-check smoke.

## 3. Phase E2 — Own layout engine (the independence threshold)

Today line boxes come from the document's cached lineseg. The moment E1 edits
text, the cache is stale — the editor needs its own line breaker to show the
result without Hancom.

- E2.1 **Line breaking from metrics:** UAX #14-class breaking with Korean
  rules (한글 음절 단위 줄바꿈, 금칙처리 exactly as the spec's
  breakLatinWord/breakNonLatinWord/lineWrap attributes declare), font metrics
  from the actual embedded/declared faces (E2.2), HWPUNIT-exact.
- E2.2 **Font fidelity:** load declared faces when present on the system,
  match by family metadata otherwise, embed-and-subset on export where the
  license allows; substitution always declared in the sidecar (as today).
- E2.3 **Character typography:** apply hh:ratio/spacing/relSz/offset — the
  measured first gap of the own renderer (발신명의 spread, 직인 overlap).
- E2.4 **render_cert as a public scoreboard:** certify the own renderer
  per document class against Hancom references (SSIM + geometry deltas,
  thresholds published); the repo README carries the current certification
  table. `own-certified` is earned per class, never global.
- E2.5 **Incremental relayout** so typing is <16ms/frame on a 22-page form.

Exit: the own renderer is certified on the fixed-form corpus, and an E1 edit
renders correctly with NO Hancom on the machine.

## 4. Phase E3 — Write the standard back (the round-trip threshold)

- E3.1 **OWPML writer completeness:** every element the parser reads, the
  writer emits; round-trip test = parse → serialize → byte-model equality
  (canonicalized), on the whole corpus plus fuzzed variants.
- E3.2 **Hancom acceptance proof:** written files open in Hancom with zero
  repair dialogs (COM-automated check where Hancom exists, corpus-wide).
- E3.3 **Interchange:** import/export DOCX and PDF (print-quality via the
  certified renderer); .hwp binary READ (existing extraction lanes) surfaced
  in the open dialog with its honest limits.

Exit: Rigorloom-authored HWPX files are indistinguishable to Hancom from
Hancom-authored ones, proven corpus-wide, and a new document can be created
from a blank page inside Rigorloom.

## 5. Phase E4 — The agent earns its keep (the killer-app threshold)

- E4.1 **Seat coverage to ~100%:** workspace/table anchoring for the 148
  anchor-less fills (labels one table over; header-row inference gated on
  page text), underline-ruled seats as a distinct derivation with its own
  honesty class. Target measured, per form, against the same corpus.
- E4.2 **Workspace sessions (GAP 20):** the runtime learns a workspace kind
  so the 12 workspace checkers run; the report pipeline becomes a first-class
  in-app product: 신청서/보고서/공문 packs end-to-end — draft, check, fix
  loop with the agent, every fix a plan.
- E4.3 **Conversation with memory:** the host keeps a session (today: N cold
  starts), streams (the dead SSE branch goes live), and can be granted
  read-scoped document context by explicit operator action, shown in the UI.
- E4.4 **Task packs as products:** one-click "이 양식 채워줘" flows where the
  agent proposes all seats, the human reviews the diff-table and approves
  once — the review queue grows a batch view.
- E4.5 **Live provider proof** with a real key (the standing owed leg).

Exit: a real user completes a real government form start-to-finish with agent
assistance in under 10 minutes, every change receipted, on camera (the demo
is the acceptance test).

## 6. Phase E5 — Ship it as a real open-source project

- E5.1 **Release engineering:** signed installers (NSIS now; MSIX evaluated),
  auto-update with staged rollout and rollback, crash reporting OFF by
  default (opt-in, local dump first), reproducible sidecar builds.
- E5.2 **Converter packaging decision (P1):** ship pyhwpx+COM bridging as an
  optional "Hancom 연동" component detected at runtime, so the base install
  never lies about what it can do.
- E5.3 **Repository as product:** LICENSE decision (recommend Apache-2.0;
  operator call), CONTRIBUTING, architecture docs from the program's design
  docs, the certification scoreboard, English+Korean READMEs, demo GIFs from
  the real screenshot harness.
- E5.4 **CI in public:** the full gate on GitHub Actions (Windows runner;
  Hancom-dependent legs marked skipped-with-reason exactly as locally),
  per-PR smoke on the built app.
- E5.5 **Community surface:** issue templates that ask for the receipt/sidecar
  (the evidence culture externalized), good-first-issues from the honest-gap
  registry — the §12.6/§13.7 lists become the contribution funnel.
- E5.6 **Security deep-work, deferred to here by operator instruction:**
  threat-model refresh, injection-hardening review of the agent boundary,
  SBOM, dependency audit, release signing policy — the full pass, before 1.0.

Exit: v1.0 tagged; a stranger can download, install, edit, and contribute
without talking to us.

## 7. Sequencing and rules of engagement

E1 → E2 → E3 are strictly ordered (each needs the last). E4 runs in parallel
lanes from the start (E4.1/E4.2 have no E1 dependency). E5 begins its cheap
items (LICENSE, CONTRIBUTING, CI) immediately and ends with E5.6.

The program's standing rules carry over unchanged: stacked draft PRs, no
merge without operator authorization, per-slice gates (full suite green,
privacy_scan HARD=0), orchestrator inspects every handoff against commits and
re-run evidence, honest states over silent fallbacks, measured numbers over
adjectives, and the corpus is a measuring stick — never a training target.

## 8. Open operator decisions

| # | Decision | Recommendation |
|---|---|---|
| D-E1 | License | Apache-2.0 (patent grant matters for an editor) |
| D-E2 | Ship optional Hancom 연동 component (E5.2) | Yes, detect-at-runtime |
| D-E3 | Public repo timing | After E1 lands (editor threshold = credibility) |
| D-E4 | Project naming/branding for 1.0 | Keep "Rigorloom", Korean tagline |
