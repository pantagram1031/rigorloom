# PR draft — `claude/stage1-report-demo` → `main`

Title: **rigorloom: real reports through the engine, com/xml Runtime backends, revamped desktop, newcomer path, live agent loop**

## What this branch does

One branch, kept local until review, that takes rigorloom from "pipeline usable on main, desktop pre-alpha" to a
tool that (a) produces our Korean school reports on its own engine and (b) a stranger can install and drive,
by CLI or GUI, with an agent proposing edits and a human approving them.

### Reports through the engine (Stage 1, 1b, 1c, 1d)
- The AURALAB classroom-acoustics report went through every stage gate (0 → 6) in autonomous mode; 20 pages,
  12 figures, 8 boxed display equations, page numbers; sanitized pages and poster under `docs/demo/`.
- Fork features the shipped Hawkes/WindPath reports depended on are ported with offline tests: boxed display
  equations with captions, `delete_texts` ordering and `delete_texts_after`, `strip_guide_ws_colors`,
  `page_numbers` / `header_text`, page margins (`margin_*` and nested `margins:`), colour normalisation including
  the abstract label, LaTeX converter mappings (`\mid`, primes, `\arg`, `\operatorname*`), 코드/알고리즘 captions,
  bibliography-resolved citation markers, widow/orphan control following the form (opt-in `widow_orphan`).
- Proof: the Aug 2026 Hawkes and WindPath reports re-assemble on this engine with the same shape as the shipped
  PDFs (converged loops, verify_format and layout QA green; WindPath page 1 line-identical), and AURALAB re-assembles
  pixel-identically on checked pages. Ledgers: `docs/plans/stage1-report-demo.md` (Stage 1c/1d sections).

### Runtime backends (Stage 3)
- `propose --backend com` executes a first wave of ops through Hancom with a `native_com_session` receipt
  (Hancom post-inspect, optional PDF); `--backend xml` executes nine ops through the pure-Python editor on any OS
  with a `structural_only` receipt whose well-formedness the Runtime verifies itself; `capabilities` reports each
  backend honestly. Engine children get `ProgramData` (Hancom needs it).
- Finished documents can be judged against their real form: `open --form-profile|--form` binds the blank form's
  inventory; receipts carry `residue.profileSource` and echo the keep declaration. The AURALAB report edited through
  the CLI reaches `acceptance: true` honestly; without the binding it never could.
- Recorded on this PC: COM edit of the 20-page report rendered by Hancom (`docs/demo/cli-com-edit-page1.png`).

### Desktop (Stage 4, 4b)
- Plan review queue with IME-inert approve, receipt/compare inspector, honest on-demand page preview, structure
  tree with region source, history with reverse-plan restore; then the revamp: home with recents, one workspace
  with a tabbed inspector (선택 / 검토 / 기록 / 에이전트), collapsible rail, three-item status bar with a grouped
  자세히 popover, review as diff hunks with keyboard review and hash-bound approve-all, agent chat with plan-arrival
  card, checkpoint timeline, 양식 연결, icon set, focus states, Korean type rules, dark mode.
- Reference captures: `docs/demo/desktop/*.png`; built-app smoke passes 568 checks incl. a bound-form phase;
  headless tests 113 → 210.

### Newcomer path (Stage 5)
- `docs/QUICKSTART.md` (EN + KO) written from a recorded Linux run: wheel + three bundles, clean venv, payload
  install, all ten corpus forms opened / proposed / approved / applied on the xml backend; replayed in a second
  fresh environment. Installer refusal now tells a newcomer to leave the checkout; `doctor` returns `nextStep`.

### Live agent loop (Stage 6)
- Agent Host `router` provider works keyless against a local OpenAI-compatible bridge (prompt-mode when a bridge
  cannot take a tools array; usage surfaced). Three recorded sessions: CLI on the 소논문 form, the built desktop
  (Settings → Composer → 검토 hunks → 승인 → 적용 → 영수증, screenshots `docs/demo/desktop/native-agent-*.png`,
  opt-in smoke phase `agent-live`), and the finished AURALAB report with bound form and keep declaration →
  `acceptance: true`. Providers no longer claim streaming the host does not use; `document/inspect` advertises
  `forbidden`; Anthropic direct works once a key is entered in Settings (stored in the OS credential manager).

### Pipeline in the GUI (Stage 7)
- Read-only `workspace/pipelineStatus` and a status strip with per-stage gate states; offline verify from the
  toolbar with designed pass / warn / fail / unavailable rows; poster reachable. Ledger `docs/plans/stage7-pipeline-gui.md`.

### Release readiness (Stage 8)
- Version bump, CHANGELOG, NSIS installer smoke (silent install into a scratch prefix, edit-phase smoke, silent
  uninstall), 90-second demo GIF `docs/demo/desktop/demo.gif`, release record `docs/release-v0.18.0.md`.

### Product feel and UI kit (Stages 9, 10)
- Copy law (합니다체, one glossary, technical truth under 기술 정보), one toolbar row, outline tree with human
  addresses, before → after review cards with 승인하고 적용, folded agent chatter, motion, skeletons, palette,
  measured startup. Then a dependency-free primitive kit under `desktop/src/ui/` (shadcn anatomy, Radix ARIA)
  adopted by every surface: zero `title=` and zero raw `<details>` outside the kit; font box as a band readout
  sized by a container query. Ledgers `docs/plans/stage9-product-feel.md`, `docs/plans/stage10-modern-ui.md`.

## Verification evidence
- Windows full pytest sweep: 5219 passed (before Stage 5–7 additions; suites since then green per ledger).
- Linux (WSL): 4191 passed; the 13 remaining failures also fail on `main` in that box (no Node, CJK fonts, wheel
  toolchain) and CI installs all three.
- Desktop: 278 headless tests; built-app smoke 570/0 on the Stage 10 build (+31/0 agent-live, opt-in).
- Every slice has a ledger row with model, wall time, tokens, and what was left undone.

## What this branch does not claim
- No rendering proof anywhere: receipts are `structural_only` unless Hancom produced a native session; page images
  are views, not evidence (renderer freeze kept).
- macOS untested; the CLI path is Linux-verified, Windows-verified.
- Live Anthropic smoke is owed (needs a user-entered key).

## Follow-ups after merge
- Close the 18 draft PRs already contained in `main` (list in `docs/plans/stage2-repo-hygiene.md`).
- Prune `rigorloom-eval-c1-*` worktrees (branches kept).
- Tag v0.18.0 with the NSIS bundle after merge (`docs/release-v0.18.0.md`).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
