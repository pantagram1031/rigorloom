# Rigorloom master execution plan

Status: **PAUSED BY USER — planning handoff only**  
Updated: 2026-09-12 KST  
Planning owner: Astra  
Routine execution coordinator when resumed: Sol task `01a08756-2564-7aa1-bcc9-d6e853f372b8`

This is the top-level plan for the whole Rigorloom product, not only its CLI.
It is deliberately written so an agent can recover the product direction without
reconstructing old conversations. It does not authorize work while the status above is
paused. Resume, assignment, COM use, integration, push, release, or publication each still
requires the authority described below.

## 1. Required reading order

Before planning or changing Rigorloom, read:

1. This file.
2. The nearest `AGENTS.md` for the worktree being used.
3. `docs/plans/cli-first-product-vision.md` for detailed product requirements.
4. `docs/plans/v0.16-unified-core-and-modules.md` and
   `docs/plans/v0.16-prep-variant-audit.md` for convergence and module architecture.
5. `docs/plans/agent-continuity-protocol.md` for ownership, leases, quota handoff, and
   non-duplication rules.
6. The latest live status under
   `F:/RigorloomQA/cli-first-success-20260909/codex-review/`, especially
   `ACTING-LEAD-STATUS.md`, review receipts, and coordination outboxes.

Historical plans remain useful evidence, but this file is the routing overview. When a live
worktree or receipt disagrees with a status note, verify the current Git state and treat the
older note as stale; do not silently choose whichever claim is more convenient.

## 2. Product outcome

Rigorloom is to become an agent-first document platform for real Hancom documents. A user
should be able to install it on a supported machine, connect a supported coding/reasoning
agent, and reliably create, inspect, edit, review, validate, render, convert, and recover HWP
and HWPX documents. The platform must preserve templates and unrelated content, expose
precise document targets and typed operations, and produce evidence that distinguishes a
successful command from an accepted document.

The complete product has four user-facing surfaces backed by one implementation:

- A versioned CLI/tool API for agents and automation.
- Reusable report, edit, verify, convert, style, and form skills.
- Native and portable document backends with explicit capability/proof boundaries.
- A later local frontend for visual selection, review, history, recovery, and Korean IME,
  consuming the same operations and receipts as the CLI.

The product is not complete because one small report renders, because a source test passes,
or because an old benchmark looks good. Success means correctness, native fidelity,
coverage, reproducibility, usability, safe recovery, clean installation, and honest failure
behavior across unfamiliar documents and structurally different templates.

## 3. Non-negotiable boundaries

- Preserve originals, user data, unsaved work, settings, logins, private forms, personal
  profiles, and unrelated dirty changes. Native edits and tests operate on copies.
- One explicit Hancom COM owner at a time. An uncertain native side effect is
  recovery-required and must not be blindly replayed.
- Renderer, rematch, and certificate work stays frozen until the owner approves a narrowly
  evidenced unfreeze proposal. Do not do certificate work now.
- No remote push, main merge, release, publication, purchase, credential change, paid
  overage, or reset-credit use is implied by this plan.
- Never weaken a gate, increase a layout threshold, skip pages, or add exemptions merely to
  make the current artifact pass. Fix the cause or record the failure.
- Keep source review, focused tests, full tests, wheel/install tests, native COM evidence,
  PDF/page review, GUI/IME evidence, external-user evidence, and release status separate.
- Do not call a plumbing test a finished report. Do not call automated open/reopen proof a
  complete visible GUI no-dialog test. Do not call portable XML success native parity.
- Avoid new sessions when an existing suitable provider session can safely continue. New
  workers require a bounded card, owned paths, exact base, acceptance commands, and a stop
  condition.

## 4. Current verified baseline

The current integration candidate is the clean topic worktree
`C:/Users/user/dev/rigorloom-cli-report-essentials`, branch
`codex/cli-report-essentials`, at `3252ac7e0a17783e918dc01cb1a08a3072e1c3d7`.
It contains the accepted gate-integrity, distribution payload, residue declaration,
installed-declaration plumbing, installer, form-baseline, malformed-receipt, and loop
typeset-default changes. The exact integrated sequence and interaction checks are recorded
in `ACTING-LEAD-STATUS.md`.

At that exact integrated tip, the recorded focused verification is:

- Runtime/distribution/installer/residue sets: 146 passed, 0 skipped.
- Engine layout/form sets: 80 passed, 16 skipped; all 16 are explicitly absent real-fixture
  skips, not avoidable toolchain skips.
- The integrated worktree was clean at the last live check on 2026-09-12.

Important limits on that baseline:

- The copy-only native typeset checkpoint proved that applying the existing
  `widowOrphan` defaults removed the page-2 lone `다.` without a measured layout regression.
  The integrated automatic `--loop` path still needs a fresh native copy run before claiming
  native acceptance of the wiring itself.
- The installed declaration test proves checkout-free plumbing and truthful residue
  acceptance under a declared keep/fill map; it is not meaningful finished-report quality.
- No full repository suite, clean-machine external-user installation, broad Hancom operation
  corpus, Korean GUI/IME flow, or release acceptance is claimed here.
- `C:/Users/user/dev/rigorloom-cli-product-payload` currently has an uncommitted advisory
  follow-up in `runtime/scripts/install.py` and `tests/test_cli_installer.py` on top of
  `6e4b2af`. It is not canonical and must be preserved and reconciled against `3252ac7`
  before any reuse. Do not overwrite, discard, or integrate it by assumption.

## 5. Target architecture

Rigorloom keeps one coherent set of contracts across all surfaces:

1. **Workflow kernel and gates** — authoritative stages, prerequisites, receipts,
   approvals, recovery, and fail-closed transitions. `PIPELINE.md` remains workflow
   authority; generated handoffs do not form a competing state machine.
2. **Document model and targeting** — stable addresses for sections, paragraphs, runs,
   tables/cells, equations, images, fields, controls, and ranges; stale-target detection;
   typed preconditions; dry-run and operation plans where useful.
3. **Document backends** — native Hancom COM for supported Windows routes and a portable
   HWPX/XML route with declared limitations. Unsupported mutations preserve data or refuse
   with actionable errors.
4. **Capability catalog** — machine-readable discovery of every supported operation,
   backend, prerequisite, risk, round-trip expectation, and evidence state.
5. **Core and modules** — a lean runtime plus independently packaged report, style,
   personalization, and later capability modules. The module manifest is canonical for
   artifact routing and gate composition.
6. **Agent CLI/tool API** — structured versioned inputs/outputs, deterministic exits,
   capabilities/doctor, receipts, safe paths, resume/recovery, and compatibility migrations.
7. **Skills** — reasoning workflows that call public tools rather than embedding private
   worktree paths or pretending a stage pointer authored the document.
8. **Frontend** — a local visual client over the same operations, capabilities, gates,
   receipts, and recovery state. It must not fork semantics or bypass CLI acceptance.
9. **Evidence layer** — immutable hashes and provenance binding exact inputs, operations,
   outputs, tests, native conversions, visual reviews, and final acceptance decisions.

## 6. Product workstreams

### A. Governance, recovery, and truthful evidence

Maintain the prior-work inventory, canonical refs, task/worker/lease ledgers, immutable
receipts, and recovery rules. Detect stale async output and duplicate integration. Preserve
historical variants until their useful behavior and proof level are classified.

Exit condition: every active card has one owner, exact base and paths, a current receipt,
and an evidence-backed status; interrupted or superseded work cannot overwrite the current
head or queue.

### B. Reliable workflow and agent-facing CLI

Finish deterministic stage discovery, gate integrity, typed errors, report/edit lifecycle,
resume, verify, render/export, recovery, and stable structured schemas. Successful execution
with a rejected gate must remain visibly rejected.

Exit condition: fresh report and edit flows finish honestly, preserve existing command
contracts or document migrations, and cannot mark a stage done through pending, rejected,
forged, or stale evidence.

### C. Hancom document operation coverage

Build and maintain the operation catalog for lifecycle, Unicode text/ranges, character and
paragraph formatting, styles, pages/sections, headers/footers/numbering, tables, equations,
images/drawings, fields/references, templates/forms, review tools, embedded objects,
document/application settings, protection states, and guarded advanced actions.

Each capability progresses through distinct states: discovered, implemented, unit-tested,
native-tested, rendered, and supported in distribution. Unknown or unavailable operations
remain explicit; they are not silently counted as covered.

Exit condition: every promised operation has native or justified portable fixtures,
round-trip checks, supported-version bounds, and an honest unsupported remainder.

### D. Skills and end-to-end document quality

Develop reusable report, edit, verify/convert, and style/form workflows. Report work covers
brief intake, research and source retrieval, claims/numbers, optional analysis/simulation,
writing, Korean language quality, native assembly, page inspection, repair, and final
evidence. Editing covers inspect, target resolution, scoped preview, apply, affected-page
render, invariant checks, and recovery.

Exit condition: the skills work through installed public tools in at least two supported
agent configurations and do not require repository aliases, private profiles, or hidden
manual intervention.

### E. Benchmark and regression corpus

Recover and sanitize WindPath/Hawkes-class inputs without copying private bylines or
fabricating missing assets. Add small smoke reports plus at least three structurally
different templates, long-form scientific reports, existing-document edits, dense and
multipage tables, mixed equations, anchored images, sections/headers, Korean/Latin text,
fonts, fields, protected/unsupported controls, corrupt assets, stale targets, and
interrupted/repeated operations.

Exit condition: complete reproducible input packs generate independently reviewed native
artifacts with semantic, structural, page-by-page visual, reopen, and provenance evidence.

### F. Distribution, installation, upgrades, and recovery

Deliver an allowlisted wheel plus verified core/module bundles. Keep trusted verification in
the wheel, reject malformed/colliding/traversal archives, stage and swap on the same volume,
preserve foreign locks and operator backups, provide doctor/prerequisite checks, install
skills only by explicit request, and document upgrade/uninstall/recovery.

Exit condition: a clean supported Windows profile or VM installs without checkout paths,
runs report and edit flows through the installed command, detects Hancom/fonts/prerequisites,
survives locked/interrupted/replacement cases, and preserves user data on uninstall.

### G. Portable and cross-machine support

Keep HWPX/XML and other portable paths useful without overstating native fidelity. Define
backend capability negotiation, external-renderer contracts, conversion-loss reports, and
fixtures for parity where it is attainable.

Exit condition: portable mode works on its supported platforms, refuses unsupported native
semantics safely, and labels its proof grade throughout CLI, skills, receipts, and UI.

### H. Frontend and visual interaction

After the core operation contracts stabilize and the renderer freeze is explicitly reviewed,
build a local UI for document navigation, selection, preview, history, approvals, recovery,
and side-by-side evidence. Korean IME and selection/operation alignment are mandatory.

Exit condition: GUI actions and CLI actions produce equivalent operations and receipts;
real supported documents pass navigation, selection, Korean editing, recovery, semantic
invariants, and page-by-page fidelity checks.

### I. Security, privacy, reliability, and performance

Enforce path containment, archive safety, protection-state refusal, PII/private-profile
boundaries, no credential leakage, deterministic retries/idempotency where possible, bounded
workers, recoverable failures, and realistic performance baselines. Treat raw automation as
advanced and explicitly risky.

Exit condition: adversarial regression cases cover stale targets, tampered bundles, path
traversal, conflicting writes, interrupted native work, protected documents, privacy leaks,
and recovery; performance and resource use are measured on representative documents.

### J. External validation, documentation, and release

Create user documentation, support/version policy, migration notes, example projects,
external-user trials, and a release acceptance matrix. Licensing constraints for Hancom,
fonts, templates, and report inputs must be explicit.

Exit condition: independent users can install and complete the supported workflows, all
acceptance categories are recorded, release artifacts are reviewed, and the user separately
approves publishing.

## 7. Milestones and dependencies

Keep the established milestone names so detailed plans and receipts remain comparable:

| Milestone | Product-wide result | Exit gate |
|---|---|---|
| M0 — stable workspace and truthful evidence | Reuse inventory, canonical refs, worker/task/lease records, benchmark manifests | Reproducible state; no duplicate writers; claims bound to exact inputs and revisions |
| M1 — reliable essential CLI | Honest report/edit lifecycle, gates, discovery, layout cause fixes, deterministic errors | Fresh smoke report and edit flow; rejected gates stay rejected; no exemption hides a defect |
| M2 — long-form quality checkpoint | Recovered sanitized WindPath/Hawkes-class packs and generalized missing features | Complete native renders, semantic checks, reopen, all-page review, independent reproducibility |
| M3 — comprehensive document tooling | Classified Hancom catalog, supported operation families, report/edit/verify skills | Every promised operation has native/round-trip fixtures; unsupported remainder explicit |
| M4 — distributable product | Wheel, bundles, doctor, skills install, upgrades/uninstall/recovery, clean-machine docs | Independent supported machine completes report and edit without repo paths |
| M5 — faithful frontend | Same-core local UI, selection/review/history/recovery and Korean IME | CLI/UI operation equivalence plus semantic, visual, navigation, and IME evidence |
| M6 — release acceptance | External trials, regression and performance baselines, support policy | Acceptance matrix complete; artifacts reviewed; explicit user publishing approval |

M1 fixes can continue alongside M3 catalog discovery and M4 packaging investigation after
resume, but native COM remains serialized. M2 reveals requirements for M3/M5; M5 cannot
silently unfreeze renderer work. M6 depends on all promised earlier gates, not merely a
version number or built package.

## 8. Resume queue

When the user explicitly resumes work, the coordinator should recheck live state and then
consider this order. This is a queue proposal, not an active assignment:

1. Reconcile the two-file dirty advisory follow-up in `rigorloom-cli-product-payload`
   against integrated `3252ac7`; preserve it until reviewed, then either adapt a justified
   delta or retain it as superseded evidence.
2. Under a fresh sole-COM lease, run the integrated automatic `fill_report.py --loop` path on
   copies of the preserved second-case form, render every page, inspect all pages, and reopen
   the HWPX. This closes or honestly fails the current native wiring gap.
3. Run the broad repository suite and the installed cleanroom payload suite at the exact
   integrated tip. Do not repeat already passing focused suites unless code changed.
4. Produce the first machine-readable Hancom operation catalog and gap matrix from existing
   code, tests, documentation, and supported native APIs.
5. Reconcile WindPath/Hawkes canonical inputs, assets, sources, and build instructions into
   sanitized reproducible packs before using their artifacts as benchmarks.
6. Perform a clean-profile/VM installation trial covering doctor, wheel, core/modules,
   skills, report, edit, replacement, recovery, and uninstall preservation.
7. Validate the skills through a second supported agent configuration.
8. Prepare, but do not implement, the smallest evidence-backed renderer/frontend unfreeze
   proposal if native-versus-UI mismatch still blocks M5.

## 9. Agent execution protocol

While this plan is paused, agents may read it but must not infer an assignment from it.
After explicit resume:

- Reuse the existing named Herdr `rigorloom` sessions when suitable. Do not create several
  provider sessions merely to display parallelism.
- Read the current topic head, dirty worktrees, receipts, and ownership before prompting a
  worker. A pane label or old status is not proof that a worker is available.
- Give each implementation card one isolated worktree, one owner, exact allowed paths,
  exact base hash, inputs, acceptance commands, evidence destination, and stop condition.
- Tell every writer that other work exists and must not be reverted. Reviewers are read-only.
- Preserve task/COM/coordinator leases and fencing revisions. Timeout means inspect the same
  handle; it does not authorize a duplicate worker or repeated native apply.
- Require a receipt with base/head, dirty paths, commands, exact counts, outputs/hashes,
  unrun checks, uncertainties, and next safe action. External prose saying “done” is not
  acceptance.
- The coordinator verifies scope and tests, obtains independent review proportional to risk,
  and integrates once. Strategic acceptance disputes return to Astra; routine telemetry does
  not.
- Use fresh provider quota snapshots with account alias, window, used/remaining direction,
  capture time, and reset time. Preserve reserves and avoid busy polling or repeated long
  context reviews.

## 10. Evidence and claim matrix

Agents must state the strongest category actually proven:

| Evidence obtained | What may be claimed | What may not be claimed |
|---|---|---|
| Source inspection / diff review | Intended code behavior and scoped risks | Runtime, native, visual, installed, or user acceptance |
| Focused tests | Covered cases pass on that source revision | Full regression safety or native fidelity |
| Full repository tests | Repository suite passes in that environment | Clean installation, Hancom behavior, GUI, or release |
| Wheel/bundle cleanroom | Installed command and payload behavior under recorded environment | Finished document quality or external-user success |
| Native COM convert/reopen | Recorded Hancom route worked on exact copies and versions | No-dialog GUI proof, all-page visual quality, or broad compatibility |
| All-page render inspection | Visible pages satisfy recorded criteria | Semantic correctness not separately checked |
| GUI/IME flow | Tested UI route works on recorded build and machine | CLI/native equivalence unless compared |
| Independent external-user trial | That user completed the recorded supported workflow | General release readiness |
| Release acceptance matrix + user approval | Authorized release preparation/publication scope | Anything outside the approved release |

## 11. Canonical locations

- Master plan: `C:/Users/user/dev/rigorloom-cli-product-plan/docs/plans/rigorloom-master-execution-plan.md`
- Detailed product vision: `.../docs/plans/cli-first-product-vision.md`
- Architecture convergence: `.../docs/plans/v0.16-unified-core-and-modules.md`
- Continuity protocol: `.../docs/plans/agent-continuity-protocol.md`
- Current integrated topic: `C:/Users/user/dev/rigorloom-cli-report-essentials`
- Evidence and coordination: `F:/RigorloomQA/cli-first-success-20260909/codex-review/`
- Second-case native evidence: `F:/RigorloomQA/cli-second-case-20260910/`
- Private/native working copies: `C:/Users/user/RigorloomQA/`

Generated reports, private forms, credentials, personal profiles, and native workspaces do
not belong in the source repository.

## 12. Definition of complete product

Rigorloom is complete for a declared release only when the supported scope is explicit; the
operation catalog matches shipped behavior; report and edit workflows work through installed
public tools; native and portable proof grades are honest; complex documents and unfamiliar
templates pass semantic, structural, native, and visual regression; frontend actions match
CLI operations; recovery and privacy failures are tested; clean-machine external users
complete the documented workflows; and the user approves release publication.

Until then, individual cards and milestones may be done, but the overall product remains in
progress.
