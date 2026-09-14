# Rigorloom: product, brand, and release plan

Status: **ACTIVE PLANNING — execution continues through release acceptance**

Updated: 2026-09-14 KST

Planning owner: Astra; execution and release lead: existing Herdr
`rigorloom-sol-coordinator` in session `rigorloom`.

Planning input: local main `6b99cdf36f71224aedcdabce1eab263152913ee3`.
This is an executable work specification, not a claim that its gates have passed.
Every future card must bind the then-current exact base, not reuse this SHA blindly.
The user requested continued delivery responsibility through release, including branding,
website, icons, premium Desktop design, fewer interruptions, and maximum useful capability.
Prepare the entire release; retain the final publishing approval and existing specific
renderer/rematch/certificate freezes and sole-COM ownership boundary.

This addendum supplies the current product-surface and launch direction alongside the
[master plan](rigorloom-master-execution-plan.md). Its Desktop-first release requirement
supersedes older descriptions of the frontend as merely a later optional surface or Studio
as the main frontend. Historical baseline numbers and staffing notes are evidence to
reconcile, not current execution instructions. Architecture adoption still follows the
[variant audit](v0.16-prep-variant-audit.md); continuity follows the
[ownership protocol](agent-continuity-protocol.md).

## 1. Product and promise

Rigorloom is an agent-first Korean HWP/HWPX document editor for agents and people.
The two primary surfaces are the versioned CLI/tool API and the local Desktop app, backed
by the same document operations, approvals, recovery, and receipts. Reusable skills make
those operations easy for supported agents to use. Studio is an internal or legacy
supporting surface; assess useful components for reuse, but do not launch it as a competing
third editor or spend launch effort on a separate Studio product.

Proposed Korean headline: **에이전트와 함께, 한글 문서를 정확하게.**
Supporting copy: **양식은 지키고, 수정은 빠르게. HWP·HWPX 편집부터 검토와 내보내기까지.**
Attach supported-version and backend limits to the actual capability description. HWP
native editing requires the supported licensed Hancom environment; portable HWPX support
does not imply universal HWP rendering or native parity.

Primary users are people completing Korean forms and reports, and developers connecting
agents to document work. Secondary users automate repeated organizational templates.
Their shared job is to finish an editable, correctly formatted document with minimal
manual repair. The differentiation to prove is precise object/range targeting, template
preservation, broad native document operations, explicit portable limits, recovery after
interruption, and a clean human review surface. Do not advertise superiority without a
matched benchmark or imply that Rigorloom supplies its own reasoning model by default.

## 2. Capability without clutter

Retain the mandatory native floor from the
[product vision](cli-first-product-vision.md): lifecycle; Korean/Unicode range editing;
character, paragraph and named styles; pages/sections; headers, footers and numbering;
merged and multipage tables; inline/display/boxed equations; embedded/anchored images;
fields/bookmarks/links; and template filling. Classify the remaining feasible Hancom
families, preserve unsupported objects, and explain refused edits before mutation.
Core must run independently of optional report/style/personalization modules.

Each capability catalog row must contain its operation ID, schema version, user job,
native/portable support, supported environment, prerequisites, effects, risk/policy rule,
fixture IDs, implementation revision, evidence category and distribution status.
Prioritize a gap by blocked user jobs, severity, frequency and recoverability. A thin
command wrapper or raw-action escape hatch does not count as tested coverage.

For every proposed control, wizard, concept or dependency, record the user task it improves
and its measured cost: clicks, interruptions, setup steps, latency or support burden.
Remove decorative dashboards, repeated confirmations, compulsory chat, unexplained scores,
redundant editors and setup questions with a reliable default. Put advanced operations in
searchable commands or contextual tools. Keep their capability available through the API.

Deprecation requires a reuse/loss ledger: source and exact revision; unique behavior and
tests; consumers; replacement; compatibility period; migration and rollback. Hide unused
UI first when safe. Delete a contract only after consumers migrate and a regression check
proves the useful behavior survives. Never remove a mandatory capability or a fidelity
check to meet a date. **“All branches” means reviewed useful, non-superseded work**, with
equivalent changes recognized and selected deltas integrated once; it never means blind
merges, forced cleanups, or retaining every historical implementation in the shipping app.

## 3. Approval experience

Implement one policy evaluator used by CLI, tools and Desktop. Evaluate typed operation
effects against a user-authorized workspace, document identity/revision, target range,
backend and rule version. A model's prose or a document's content cannot grant approval.
Store a local decision receipt; routine successful decisions need no modal or notification.
Auto-approval means an auditable policy decision, never a fabricated human signature.

| Operation class | Default behavior | Acceptance test |
|---|---|---|
| Read/inspect, local validation, preview | Proceed inside authorized scope | No mutation or network upload; zero confirmation dialogs |
| Reversible scoped edit on a working copy | Proceed when effect and target are known and recovery is ready | Ten consecutive allowed edits complete with zero repeat approvals; undo restores semantic state |
| Known native mutation on a copy | Proceed only under current sole-COM lease and applicable prior authorization | Valid lease, input hash and preconditions; saved result and reopen evidence; no extra per-action prompt |
| Overwrite original, permanent deletion, broad destructive change | Show exact affected files/content and obtain specific approval | Refusal preserves originals; stale approval cannot authorize changed targets |
| Public upload, release/publish, credential/permission or payment change | Prepare concrete result, then retain explicit applicable gate | No execution from generic project trust or a prior different approval |
| Unknown effect, ambiguous target, uncertain native completion | Stop that operation; inspect/recover | No blind replay, approval reuse or success receipt after uncertainty |

An approval names scope and expiry/revision conditions and is reusable only within them.
Batch related changes into one concise preview when approval is necessary. Show what will
change, where, and how to recover; provide one clear action and cancellation. Do not ask
again for unchanged scope already authorized. Detect target drift, external file changes,
lease loss and denied policy before writing. Test conflicting CLI/UI requests, replayed
decisions, document-borne instructions, revoked rules, crash between save and receipt, and
undo failure. Product policy does not alter provider permissions or billing settings.

## 4. Desktop design and interaction

Use a document-centered layout: restrained file/navigation rail, generous document area,
contextual properties, and an on-demand activity/recovery panel. The document remains
visually dominant. Primary journeys are open or create, select, request or make an edit,
inspect the result, undo if needed, and save/export. Agent connection is optional for
manual work. No permanent orchestration graph, model carousel, marketing card grid or
technical evidence ledger in the default editing view.

The visual direction is quiet editorial software: warm neutral surfaces, near-black type,
one muted blue accent, sharp typography and consistent spacing. Avoid neon gradients,
sparkles, robot/brain marks, glass panels, excessive rounding and generic AI slogans.
Originality must come from the mark, proportions, typography and real document imagery.

Design owner delivers versioned tokens for color (including semantic/focus states),
typography, spacing, radii, elevation, icons and motion before parallel UI/site work.
Starting candidates: canvas `#F7F6F2`, panel `#FFFFFF`, text `#20211F`, muted text
`#626760`, accent `#254B67`; validate contrast before acceptance. Use a 4 px spacing unit,
body UI type 14–16 px, restrained 6–10 px control radii, and 120–180 ms optional motion.
These are proposed values, not visually verified tokens.

Korean UI uses a reviewed, distributable Korean font with explicit license and system
fallback; document fonts remain document-owned. Test Hangul density, Korean/Latin/numeric
mixes, long filenames, punctuation and line breaking. Never change a document font to
make the app look consistent. Verify composition start/update/commit/cancel, backspace,
selection replacement, undo/redo, focus changes, clipboard, and agent edits concurrent
with active Korean IME; defer edits that would corrupt composition.

Acceptance includes keyboard-only primary journeys, visible focus, screen-reader names
and reading order, high contrast, reduced motion, 200% UI text scaling, and 100/125/150/200%
Windows display scaling. Validate text/control contrast against the declared accessibility
target and record measurements. Show text alongside consequential state icons. Test at
1280×720 and 1920×1080, light and dark surfaces if both ship, empty/loading/error/recovery
states, and missing fonts. Inspect actual screenshots; snapshot tests alone do not prove
premium appearance. CLI/UI parity compares operation payloads and final document state.
Frozen renderer work needs its existing narrow unfreeze decision before implementation.

## 5. Brand, logo and icons

Design card produces three original monochrome vector directions from document structure,
alignment or woven lines, then selects one against legibility, distinctiveness and app-scale
recognition. Use an editable vector master, Korean/Latin wordmark lockups, clear-space and
minimum-size rules, monochrome/reverse versions and a provenance/license record. Check
obvious similar marks before public use; do not invent a claim of trademark clearance.

Complete deliverables: SVG masters; transparent PNG exports at 16, 20, 24, 32, 40, 48, 64,
128, 256, 512 and 1024 px; multi-resolution Windows ICO; installer/uninstaller and shortcut
assets; taskbar/tray variants if those surfaces exist; favicon ICO/SVG and 16/32 px PNG;
180 px touch icon; 192/512 px web manifest icons with maskable safe area; social avatar and
1200×630 launch image. Derive platform package dimensions from the actual packaging
manifest, including scaled assets. An absent platform is not a reason to add another app.

Inspect tiny icons at actual size, Windows light/dark taskbars, desktop shortcut backgrounds,
installer dialogs and browser tabs. Pixel-adjust small exports if needed. Verify alpha,
color consistency, clipping, contrast, manifest paths and packaged binaries. A large logo
mockup alone cannot pass the icon gate. The asset inventory binds every export hash to its
master/version and consumer. No placeholder brand assets may remain in the RC.

## 6. Website, onboarding and launch content

Build the marketing site from the same tokens and actual Desktop captures. Lead with the
Korean promise, a real editing example, and one Windows download action when a release is
available. Before publishing that artifact, use truthful preview availability wording.
Provide an agent quickstart, three demonstrated jobs (form fill, precise existing-document
edit, long report), supported environments/backends, privacy, docs, release notes and support.
No fake customer logos, fabricated testimonials, counters or speculative features.

Website card owns responsive pages, accessible navigation, page titles/descriptions,
canonical URLs, social previews, sitemap/robots rules and useful 404/error states. Start
with Korean copy; provide reviewed English product/quickstart text where support is offered.
Record asset/font licenses. Validate mobile 360/390 px and desktop layouts, download links,
keyboard navigation, contrast, no-script core content where practical, and network payload.
Target first-load compressed transfer under 1 MB excluding explicitly played video; record
actual conditions and revise only with a documented reason. Avoid autoplay and trackers.

Onboarding: install, run prerequisite diagnosis, open a bundled synthetic sample, complete
one edit and undo, then optionally connect a supported agent. No account, API-key entry or
telemetry choice blocks local manual editing. Agent setup uses the agent's documented
credential mechanism; do not copy tokens. Explain missing Hancom with a usable portable
path and its limits. Offer advanced modules only when their job is requested.

Documentation must include installed CLI/API examples, discovery/schema reference,
copy-first editing, forms/tables/equations, native/portable limits, agent connection in two
supported configurations, recovery, migrations, update/uninstall and troubleshooting.
Examples use synthetic or permission-cleared assets and work without checkout paths.
Launch pack includes README, changelog, compatibility table, screenshots, short captioned
demo, downloadable examples, release body, installation checksums and known issues.

## 7. Privacy, packaging, security and support

Document processing and receipts are local by default. Usage telemetry is off by default;
document text, paths, profile content and credentials never enter product analytics.
Any optional crash report is previewable, redacted and explicitly sent. Define local log
retention, export and deletion; keep undo/recovery available under a clear storage policy.
Explain what an externally connected agent receives before enabling that route. Test
outbound behavior and inspect package/log contents; a policy page is not proof.

Release engineering owns one versioned set of wheel/core/module and Desktop artifacts,
dependency lock/provenance, license notices, SBOM, checksum manifest, and applicable
code-signing/notarization state. Record unsigned status honestly when signing is unavailable;
do not acquire certificates or modify credentials under this plan. Determine the actual
Windows installer and update mechanism from existing code, not an assumed new stack.
Test clean supported profile/VM install, first run, core-only/all-modules, upgrade from the
previous supported build, interrupted update, rollback, locked files, offline errors, Unicode
and space-containing paths, and uninstall/reinstall. User documents, profiles and unrelated
files survive uninstall; any optional personal-data removal is separate and explicit.

Independent security review covers archive traversal/collisions, malformed HWPX/resource
bombs, path/symlink boundaries, external resources, module trust, tool/document instruction
injection, stale-target/replay attacks, native lease conflicts, unsafe process cleanup,
receipt tampering, and secret/private-corpus leakage. Release blockers are unresolved data
loss, unauthorized effects, credential leaks and exploitable high-severity findings.
Record lesser findings with scope and disposition; never silently waive them.

Support owner prepares existing GitHub issue templates, security reporting, contribution
and conduct guidance, a compatibility/known-issues page, a minimal redacted diagnostic
bundle, and a troubleshooting decision tree. Keep reports free of private documents by
default. Propose a two-working-day initial issue-triage target for the preview; validate
staff capacity before publishing it. No guaranteed resolution time or new chat community
is required. Reuse GitHub support surfaces before adding another service.

## 8. Gate ledger: M0 through GA

Sol maintains one release ledger outside source, under the existing coordination root:
`F:/RigorloomQA/cli-first-success-20260909/codex-review/release/`.
Planned files are `cards.json`, `reuse-ledger.tsv`, `acceptance-matrix.tsv`,
`benchmarks.json`, `artifacts.json`, `release-decision.md` and per-card receipts.
These paths are specifications; this plan has not created or populated them.
Rows record owner, dependencies, exact inputs/base/head, commands, environment, output
hashes, pass/fail/blocked/unrun, reviewer, evidence category and rollback reference.
No missing evidence becomes PASS by omission. Keep private/native fixtures outside Git.

| Gate | Accountable owner; dependencies | Required artifacts and tests | Exit and rollback |
|---|---|---|---|
| M0: reconciled release baseline | Sol; current task/session/lease inspection | Branch/reuse inventory, live owners, exact candidate tree, catalog/acceptance gaps, first bounded cards | One writer per path, no stale assignments; preserve historical refs and dirty files; stale result rejected |
| M1: dependable essential editing | Core owner; M0 | Installed-public-contract smoke design; discovery, edit/report, policy, stale-target, undo/recovery and negative-gate regressions | Required flows pass with no false success; revert scoped patch to known candidate on regression |
| M2: document quality | Native QA owner; M1, authorized COM lease | Sanitized long-form pack and three distinct template families; content/control checks, all-page render inspection, visible open/save/reopen | Zero missing text/assets/controls or unintended template changes, overlap/clipping/orphan captions; retain pristine input and failed output for diagnosis |
| M3: supported breadth | Capability owner; M1 plus M2 findings | Complete classified catalog; native-floor fixtures; portable matrix; two agent configurations; unfamiliar-template holdout | Every advertised operation supported in installed artifacts with its stated proof; scope reduction of mandatory floor requires product decision; restore prior compatible contract |
| M4: distributable CLI and Desktop | Release engineering; M1, stable schema; final exit needs M3 | Hash-bound packages, clean profile/VM install/update/rollback/uninstall, docs and license/privacy scan | No checkout-only dependency, personal-data loss or unexplained skip; restore previous package/channel using tested rollback |
| M5: premium faithful Desktop and brand | Design + Desktop owner; M1 contracts, M2 fidelity, freeze decisions where needed | Same-core journeys; actual Korean IME/keyboard/accessibility runs; all-page comparisons; brand/icon inventory; site preview and visual review | Default journeys clear, safe-edit flow has zero repeated prompts, CLI/UI state equivalent; restore UI/assets independently without rewriting documents |
| M6a: release candidate | Sol; M2–M5, independent security review | Immutable RC manifest, exact-tree required regression, compatibility/performance results, five external-user trials, release/support pack | No release-blocking defect; all promised categories have current evidence; failed candidate retained and superseded explicitly |
| M6b: public launch | User publication decision; accepted M6a | Reviewable GitHub release/site/package destinations, version and artifact hashes, approval scope; post-publish download/install/link smoke | Publish only approved immutable artifacts; incident rollback disables bad download/update and restores prior release when authorized |
| GA: sustained acceptance | Sol + support owner; M6b observation | At least seven calendar days of preview observation, all five users completing core jobs, resolved blocking issues, support/incident rehearsal and final matrix | Full Definition of Done met and explicit GA publication approval; extend preview if evidence fails, never promote by elapsed time alone |

Five external users means at least two agent-oriented users and two manual Desktop users,
with at least three structurally different document families collectively exercised.
Each completes install, edit, save/reopen and recovery/undo on the supported environment
without developer intervention; record assistance, failures and retries. Preparation can
use internal dry runs, but those do not substitute for external-user evidence. Recruitment
or outreach needs the user's authorization; prepare the trial script while that is pending.

Benchmark manifest pins hardware, OS/Hancom/font versions, backend, artifact revision,
fixtures, warm/cold conditions and sample counts. Measure 1/20/100-page document open,
inspect, scoped edit, save, render, peak memory, agent tool calls and required approvals.
Use at least ten measured runs per deterministic case after explicit warmup and report
median/p95 plus failures; do not mix native and portable scores. Proposed RC budgets are
p95 local UI feedback under 100 ms, zero unbounded native waits, and no greater than 10%
regression against the accepted baseline in comparable runs. Sol records numeric timeout
and per-operation latency budgets after baseline measurement and before optimization.
Investigate failures against those fixed budgets; do not relabel slow work as fast.

Evidence ceilings remain independent: source review establishes intent; tests establish
their cases; installed checks establish that package/environment; native COM establishes
the recorded route; all-page visual checks establish visible pages; GUI/IME establishes
the tested interaction; external trials establish those users' journeys. None alone proves
release readiness. Bind all categories to the RC or document why unchanged evidence is
still applicable. Do not rerun passing checks without a relevant change or remaining risk.

## 9. Herdr staffing and dispatch

Reuse existing healthy sessions, starting with `rigorloom-sol-coordinator`. The current
[session contract](rigorloom-herdr-session-prompts.md) supplies actual session identifiers;
verify model, cwd, state and capability before assignment. Titles and provider quotas alone
are not capability or availability evidence. Match the following roles to existing workers;
record any capability-equivalent substitution without vendor lock-in.

| Card / capability role | Proposed ownership, resolved to exact paths at dispatch | Independent acceptance |
|---|---|---|
| REL-00 / Sol coordination | Release ledger, queue, leases and acceptance decisions; no overlapping implementation | Mechanical verifier checks hashes/receipts; Astra resolves strategy conflicts |
| PRODUCT-01 / Astra high-reasoning | This release plan and minimal master pointer | Read-only independent reviewer checks scope and dependencies |
| REUSE-01 / inventory | Reuse/capability inventory receipt only | Core reviewer checks unique behavior, supersession and loss entries |
| CORE-01 / implementation | One explicitly listed core/runtime slice and its focused tests | Independent reviewer plus exact-artifact verifier |
| POLICY-01 / high-reasoning implementation | Shared policy evaluator and policy regressions, separate from CORE paths | Adversarial reviewer tests stale approvals and unsafe effects |
| NATIVE-01 / native QA | Fresh private fixture copies and native receipts; sole COM lease | Vision reviewer inspects every page; mechanical verifier checks binding |
| BRAND-01 / visual design | Brand masters/tokens/export inventory only | Independent visual review at real sizes and license/provenance review |
| DESKTOP-01 / UI implementation | Named Desktop components/tests after shared tokens are accepted | Independent keyboard/IME/accessibility and CLI-equivalence verifier |
| SITE-01 / web implementation and writing | Named marketing site/copy paths consuming accepted tokens/assets | Independent responsive/accessibility/copy-and-claims review |
| DIST-01 / release engineering | Named packaging/update/uninstall manifests and tests | Independent clean-profile installer and rollback verifier |
| DOCS-01 / technical writing | Named public guides/examples/support files | Independent user follows installed examples without checkout |
| SEC-01 / independent-review | Read-only security receipt; no source ownership | Sol resolves findings through separate bounded implementation cards |
| RC-01 / mechanical verification | RC evidence inventory, checksums and missing-gate report | Sol verifies real artifacts and Astra reviews only acceptance disputes |

These are card templates, not simultaneous blanket path grants. Sol must replace every
proposed scope with exact files, base SHA, input hashes, acceptance commands, receipt path
and stop condition. Shared tokens/exports have one owner; UI/site consume a reviewed version
and request changes through that owner. Start with up to three active workers plus Sol;
increase only for independent work with actual capacity. Native work stays serialized.
Reviewers cannot write a fix under their review card. One submission per card includes all
failures/unrun checks; Sol checks the diff and artifacts independently before acceptance.

## 10. First 72 hours and subsequent release path

Time starts when Sol accepts this plan and publishes the fresh M0 snapshot. This is an
ordering and checkpoint budget, not a promise of GA in three days. Blocked native or public
actions do not stop independent design, documentation, packaging preparation or reviews.

| Window | Deliverable and owner | Dependency and decision at end |
|---|---|---|
| 0–6 h | Sol reconciles live main/worktrees/sessions/leases, old acting-lead notes and release gaps; inventory worker classifies reusable work | Publish exact baseline, owned first cards and all current blockers; no stale card replay |
| 6–18 h | Astra closes scope conflicts; design owner drafts tokens/three logo directions; core owner measures essential-flow and approval baseline | Select brand direction against written criteria; issue exact policy/core fixes from observed gaps |
| 18–36 h | Policy/core fixes and focused negatives; design owner exports accepted mark; site owner builds truthful launch preview from available assets | Independently review changed contracts; feed stable tokens/assets to Desktop/site cards |
| 36–54 h | Desktop owner implements one full open→edit→undo→save journey; release engineer prepares packages/clean-profile script; native QA uses only current authorized lease | Compare CLI/UI payloads; record actual IME/native/installed results or explicit blockers |
| 54–72 h | Independent review and package dry run; docs owner validates quickstart; Sol publishes candidate manifest, gate matrix and next five bounded cards | Demonstrate real artifacts and exact missing gates; re-estimate M2–M6 critical path from evidence |

After 72 hours, complete M2/M3 coverage and M4/M5 integration in reviewed increments; use
fresh holdouts to expose missing mechanisms. Assemble the immutable RC only when those
gates pass. Prepare external trials, release destinations and site preview before the final
publishing decision. After authorized preview publication, observe at least seven days,
fix and verify defects, and promote to GA only on accepted evidence and final approval.
Sol remains responsible for the queue, owners, recovery and release packet throughout;
idle workers or one successful package are not terminal completion. At an actual external
block, checkpoint the exact missing decision while progressing independent authorized cards.

## 11. Definition of Done

A declared release is done when CLI/tool API and Desktop ship from one coherent core;
every advertised operation matches its capability/evidence record; native and portable
limits are explicit; original content and recovery survive failures; Korean IME, accessibility
and all-page fidelity checks pass; branding/icons/site use reviewed production assets;
supported users install/update/uninstall without development paths or personal-data loss;
privacy/security and benchmark gates pass; documentation and external users demonstrate
the promised jobs; support and rollback are ready; and the approved hashes are actually
published and independently downloaded/checked. GA adds the observation and promotion
gate above. Until then report the completed gates and missing evidence, not “release done.”

Plan verification only: no product tests, native runs, visual review, external trial,
package publication or GA acceptance is claimed by this document.
