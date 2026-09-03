# Product direction — an agent-native HWP/HWPX desktop editor and automation runtime

Status: **living product direction, aligned to the durable Goal specification**  
Last updated: 2026-09-01

This document defines what Rigorloom should become and how the existing system
should be used to get there. It is a product and architecture direction, not a
new capability claim. **Nothing below asserts that a described feature exists
today.** Current support remains defined by
[`docs/support-matrix.md`](support-matrix.md), the release records, and
executable tests.

The normative execution contract for this direction is
[`plans/agent-native-desktop-goal.md`](plans/agent-native-desktop-goal.md).
The running status, phase gates, and PR graph live in
[`plans/agent-native-desktop-program.md`](plans/agent-native-desktop-program.md).
This document is the readable middle layer: what the product is, why, and what
the boundaries are. Where this document and the Goal specification disagree,
the Goal specification wins and this document is the one that needs fixing.

## 1. Decision

Rigorloom should become:

> **An agent-native, local-first HWP/HWPX desktop editor and automation runtime
> with verifiable operations.**

Korean product sentence:

> **사람과 AI 에이전트가 같은 검증형 작업 체계로 한글 문서를 열고, 이해하고,
> 수정하고, 검증하는 로컬 데스크톱 편집기이자 자동화 런타임.**

The installed desktop application is the main user product. The same Runtime
and operation model must also be usable by the CLI, by external agent clients
through MCP, by embedded provider adapters inside Desktop, and by headless
automation with no Desktop at all.

"Agent-native" is a structural claim, not a marketing one. It means a model
proposing a document change and a person typing into a field travel the *same*
typed operation path, hit the *same* validation, and produce the *same* kind of
evidence — with different authority at the ends. It does not mean the product
is autonomous, and it does not mean a model is trusted.

The existing document engine, deterministic gates, receipts, proof ladder, and
module registry remain the authoritative implementation beneath all of it.

The report pipeline is valuable and stays supported, but it is **one optional
workflow module**, not the identity of the project. Report-specific operating
documents should say so about themselves.

Rigorloom is **not** trying to become:

- a complete clone of Hancom Office;
- a blank-page general-purpose word processor before its narrower workflows are
  reliable;
- a cloud editor that uploads private documents by default;
- a model-specific agent framework with document support attached;
- an autonomous system that silently applies model-generated edits;
- a public marketplace for executable third-party plugins;
- a product that calls an output "verified" when the relevant evidence was not
  produced.

The strategic advantage is not a blank-page editor. It is the combination of
Korean document handling, bounded operations, deterministic checks, explicit
unknown states, render evidence, agent assistance, and reproducible records of
what changed.

## 2. Current product reality

Rigorloom already contains most of the difficult foundations of this direction.
For the current, evidence-backed status of each, read
[`docs/support-matrix.md`](support-matrix.md) — it is generated from
`pipeline/references/support-claims.yaml` and refuses a `supported` row whose
evidence pointers do not resolve. The list below is orientation, not a
capability table:

- dual document backends: native Hancom COM where available and a Hancom-free
  HWPX/XML path;
- non-destructive, addressable document operations and structural inspection;
- deterministic gates that distinguish pass, warning, refusal, and unavailable
  evidence;
- a graded render-proof vocabulary instead of one misleading boolean;
- artifact hashes, receipts, provenance, and clean-room bundle validation;
- one core with separately installable capability modules;
- work-type knowledge for reports, public documents, civil forms, HR forms, and
  grant packets;
- a localhost Studio that already exposes workspaces, document structure,
  previews, verdicts, capabilities, and a small guarded action surface;
- an adversarial review discipline that treats false passes and false blocks as
  product defects.

The code is therefore broader than the repository's older description of an
"agent-neutral, resumable report workflow." The product surface, however, is
still split between several identities:

1. the root README describes a general document engine;
2. package metadata and the public repository description still describe a
   report workflow;
3. the engine README describes an agent skill for editing HWP/HWPX;
4. Studio is a browser dashboard for developers and operators, not an installed
   desktop product;
5. work-type modules contain user-facing domain value, but users must first
   understand the module and CLI model to reach it.

This is the main product problem now. More checkers or another document family
will not resolve it. The next work must turn the existing mechanisms into one
coherent user journey — and give agents a first-class, *bounded* seat in that
journey rather than an afterthought adapter.

Engineering validation is also much stronger than product validation. The
repository has extensive tests, clean-room installation checks, corpus work,
and detailed evidence records. It has much less evidence that a new user can
install the product, understand it, complete a useful document task, and trust
the result without reading the repository. Desktop work should be judged by
that user outcome, not by test count alone.

## 3. The initial product wedge

The first desktop milestone — the **Developer Preview** — should solve one
narrow, high-value job end to end:

> Open an untrusted local HWP/HWPX document, understand its structure and
> fillable regions, make bounded edits (typed by a person or proposed by an
> agent) without altering unrelated form structure, review the plan, run the
> available checks, and export a new file with an honest evidence record.

This is deliberately narrower than "edit any Korean document." It is broad
enough to cover the project's strongest existing form families and narrow
enough to verify.

### Primary users

The initial audience is:

- people completing Korean government, civil, HR, grant, and other fixed-layout
  forms where the original layout must survive;
- developers and advanced operators automating HWPX documents;
- teams that need reviewable, repeatable document transformations rather than
  one-off macro scripts;
- AI-agent users who want a model to propose document work while deterministic
  software remains the authority.

School and corporate forms remain future audiences until representative corpus
and acceptance-task evidence exist for those families.

### Core user journey

1. **Import safely.** Open a document as an immutable source and create a
   contained working copy.
2. **Inspect.** Show format, document family, sections, tables, fields, fillable
   seats, guide text, unsupported structures, and available renderers.
3. **Plan.** Turn user input or a model suggestion into a typed
   `OperationPlan` — a bounded, ordered list of operations bound to exact bytes.
4. **Review.** Show affected addresses, before/after values, expected structural
   invariants, and checks that will or will not run.
5. **Approve.** A human resolves the approval. A model cannot approve its own
   plan.
6. **Execute.** Apply operations to a new candidate artifact, never in place.
7. **Verify.** Run structural, family-specific, privacy, residue, and render
   checks. Preserve warnings and unavailable evidence instead of converting
   them into success.
8. **Export.** Save the document, preview or proof artifact, and a receipt
   binding source bytes, plan, approval, candidate bytes, tool version, and
   verdicts.

The first release does not need free-form pagination, desktop publishing, track
changes, or every Hancom feature. It needs this path to be understandable and
reliable.

## 4. One Workspace, two synchronized views

The central product object is a **Workspace**, not a file and not a chat. This
is part of the product definition, not a UI preference.

A Workspace holds the immutable imported sources, declared attachments,
sessions, agent threads, the current document and selection, proposed and
approved plans, candidates, verification reports, previews, an append-only
event log, receipts, and recoverable state.

Desktop presents that one Workspace through **two views**:

**Document view** — for working on the document.

- left: pages, document structure, tables, editable regions, warnings, and
  unsupported structures;
- center: the real page, or an honest preview-unavailable state;
- right: a contextual agent panel;
- bottom: source/candidate identity, pending changes, verification, proof
  state, and evidence that is missing.

**Agent view** — for working through the agent.

- left: workspaces, tasks/threads, documents, attachments;
- center: a document-agent timeline whose cards summarize document work, not
  raw JSON or shell logs;
- right: document preview, artifacts, plan, candidate, verification;
- a persistent instruction composer.

The two views are not two applications. They share one Workspace, one active
document session, one conversation state, one selection, one navigation state,
one plan queue, one approval state, one candidate set, and one verification
history. **Switching views must never create a new conversation or duplicate
document state.** The Document-view agent panel expands into Agent view; the
document then becomes the right-side context surface.

Navigation is bidirectional: an agent reference to a known document location
navigates Document view, and selecting a region in Document view updates agent
context.

## 5. Product surfaces and authority

The project exposes eight named surfaces. Naming them precisely is what keeps
authority from collapsing.

### 5.1 Rigorloom Engine

The existing Python engine and deterministic checkers remain the source of
truth for document operations: parsing, inspection, mutation, verification,
renderer adapters, receipts, and proof-state vocabulary.

The Engine stays headless and must not depend on Desktop. Desktop must never
become the only way to reproduce an operation or a verdict.

### 5.2 Rigorloom Runtime

> **Rename.** This surface was called **"Application Service"** in the previous
> revision of this document. It is now **Runtime**, matching the Goal
> specification and the planned `docs/runtime-protocol-v0.md`. The boundary is
> the same one; only the name changed. Treat "Application Service" in older
> documents, branches, and commit messages as referring to Runtime.

Runtime is the local application-service boundary between clients and the
Engine. It owns:

- workspaces and sessions;
- containment and resource limits;
- typed operations and their validation;
- plans and approvals;
- candidates and artifacts;
- events and progress;
- cancellation;
- crash recovery;
- artifact references instead of arbitrary filesystem access.

Runtime reuses Engine semantics rather than reimplementing them. Its initial
transport is a versioned newline-delimited JSON protocol over stdin/stdout and
requires **no network** — see the planned `docs/runtime-protocol-v0.md`.

No shell should import the parser and renderer stack directly. A malformed
document or renderer failure must not become a compromise of the whole
application process.

### 5.3 Rigorloom Desktop

The installed user product. It owns window lifecycle, native file dialogs, the
Runtime sidecar lifecycle, interaction, review, accessibility, preview,
settings, and recovery. It consumes the Runtime protocol and does not invent
its own document semantics; it does not parse HWP/HWPX and does not drive COM.

### 5.4 Rigorloom CLI

The human and automation interface over the same Runtime/domain layer, with
JSON output and stable exit semantics. It must not bypass Runtime with separate
editing semantics, and a successful exit must never imply that an unavailable
verification actually ran.

### 5.5 Rigorloom MCP

A thin local STDIO adapter exposing **only the agent-safe Runtime subset** to
Claude Code, Codex, and compatible clients. Its default policy is **inspect and
propose**.

MCP is not the internal Desktop lifecycle protocol, and it does not expose
unrestricted document write, shell, approval, arbitrary export, arbitrary file
read, or network tools. A standalone MCP server requires an explicit allowed
root or an attached host-created session, and refuses traversal,
symlink/reparse escape, and client-declared host privilege.

Claude Code and Codex use their own authentication. Rigorloom must never read
or copy another application's private token cache.

### 5.6 Rigorloom Agent Host

The separate, **network-capable** boundary for embedded providers inside
Desktop. It compiles provider requests into agent-safe Runtime calls. It does
not grant arbitrary filesystem, shell, approval, export, or proof authority.

Putting network here and nowhere else is deliberate: document processing stays
offline even when the product as a whole can talk to a model.

Provider secrets belong in the OS credential store. Ordinary settings files
contain only non-secret configuration.

### 5.7 Rigorloom Studio / Inspector

Studio remains the diagnostic and operator surface: a local developer
dashboard, an inspection and troubleshooting tool, a fast place to prototype
Desktop information architecture, and a headless-operator option.

It may supply concepts and prototypes, but it must not silently become the
shipping Desktop security boundary. First-party module panels currently execute
trusted UI payloads in the same Studio origin, and the server exposes a guarded
action mode. That is acceptable for a trusted local installation model; it is
not a safe marketplace-plugin model.

### 5.8 Rigorloom Modules

The existing distribution-module contract remains the way first-party
capability is separated (`modules/README.md`). Report, style, gongmun, minwon,
HR, and grant behavior should reach users as **task packs** and specialized
checks — 공문 본문 수정, 지원사업 신청서 작성 — not as an internal
module-management exercise.

Today these modules are trusted installation-time Python and JavaScript. They
are **not** a sandboxed third-party plugin ecosystem, and Desktop packaging must
keep that distinction explicit. Data-only packs can be admitted under a
narrower trust model; executable third-party modules require signatures,
permissions, review, and process isolation before they can be marketed as safe
plugins.

### 5.9 The authority model

Sharing one Runtime is **not** sharing one privilege level. The separation
below is the load-bearing part of this direction; method names may change after
audit, the separation may not.

| | Host authority (Desktop, and the user through it) | Agent authority (MCP clients, embedded providers, in-app agents) |
|---|---|---|
| Open an arbitrary user-chosen path | yes | no |
| Import attachment paths | yes | no |
| Inspect a scoped session, document, graph, exposed regions | yes | yes |
| Propose and validate an `OperationPlan` | yes | yes |
| Resolve an approval | yes | **no** |
| Export to a user-selected path | yes | no |
| Configure providers, change policy, delete a workspace | yes | no |
| Read candidate and verification status | yes | yes |
| Alter verification or proof state | no | no |

Four rules make that table mean something:

1. **Authority is never self-declared.** A request field such as
   `client_role: host` cannot grant privilege. Authority comes from the
   channel the request arrived on, not from its contents.
2. **Model output is untrusted.** Models cannot approve their own plans,
   overwrite sources, export arbitrarily, alter proof, or hide warnings.
   Document text and external tool results may contain prompt injection.
3. **No ambient network in document processing.** Network belongs to Agent
   Host. Runtime and Engine do not reach the network to open, edit, or verify
   a document.
4. **One path for human and agent edits.** See the invariant below.

### 5.10 Invariant: one OperationPlan path

> A direct human edit in Desktop and a model-proposed edit produce **the same
> `OperationPlan` representation** and travel the **same** validation,
> approval, candidate-generation, verification, and receipt path.

This is an architectural invariant, not an implementation convenience. It is
what makes agent work reviewable with the same tools as manual work, what keeps
a second shadow editing engine from appearing, and what makes "an agent did
this" a provenance field rather than a different code path with different
safety.

A direct user edit therefore creates or updates an `OperationPlan`; it never
silently mutates the source.

An `OperationPlan` binds at minimum: plan id, session id, the exact source or
candidate SHA-256, ordered operations with stable ids, target node ids or
addresses, before/precondition fingerprints, expected invariants, required
checks, proposer metadata, approval state, and schema/implementation version.
A stale plan refuses when bytes, target identity, before state, approval
binding, or relevant policy has changed.

## 6. Trust and security model

Security is not an adjacent portfolio feature. A desktop document processor
handles several untrusted inputs at once:

- HWP/HWPX files and embedded resources;
- ZIP/XML structure, images, PDFs, and other document payloads;
- external renderer behavior and output;
- model-generated text and operation proposals;
- external agent clients connected over MCP;
- local modules and configuration;
- update and installer artifacts.

The protected assets are the user's source document, unrelated local files,
private document contents, credentials, output integrity, verification records,
and the update channel.

### Required principles

1. **Source immutability.** A user-opened source is never modified in place.
   Every operation produces a distinct candidate artifact.
2. **Workspace containment.** A document session receives access only to its
   own source, declared attachments, candidate outputs, and temporary area.
   Agent-facing responses use scoped identifiers, not arbitrary absolute paths.
3. **Bounded ingestion.** Archive member counts, decompressed size, compression
   ratio, XML depth, text size, image dimensions, recursion, and processing
   time need explicit ceilings and stable refusal reasons.
4. **Process separation.** Parsing, conversion, and rendering should run in
   workers that can be terminated and constrained independently from the UI.
5. **No ambient network.** Opening or verifying a document must not require
   network access. Network capability lives in Agent Host, is explicit,
   separately permissioned, and visibly active.
6. **Closed operations.** The default edit interface is a schema-validated
   operation vocabulary — replace-at-address, fill-cell, set-run,
   insert-approved-object, convert-copy — not unrestricted shell, Python,
   XPath, XML, or filesystem access.
7. **Model output is untrusted.** Models may propose operations; a validator
   checks scope and a human approves consequential changes before execution.
8. **Host and agent authority differ, and authority is not self-declared.**
   See §5.9.
9. **Renderer evidence is scoped.** "The renderer ran," "the output reopened,"
   "the structure was preserved," "the page looked acceptable," and "the
   artifact is submission-grade" are separate claims. Existing proof grades
   retain that distinction.
10. **Evidence binds exact bytes.** Receipts identify the source, plan,
    approval, candidate artifact, relevant configuration, and checker version.
    A receipt must not silently apply to a later file.
11. **Fail closed at external boundaries.** Invalid requests, malformed files,
    path escape, identity drift, and missing required verification do not
    become passes.
12. **Uncertainty is explicit.** Unsupported, unknown, skipped, and unavailable
    are legitimate, visible product states — not defects to be smoothed over.
13. **Recovery is part of safety.** Cancellation, crashes, power loss, and a
    failed renderer leave the source untouched and candidates either complete
    or clearly disposable.
14. **Private by default.** Telemetry, crash uploads, cloud sync, and model
    calls are off unless the user deliberately enables a clearly scoped
    feature. What may leave the device is disclosed before it does.
15. **Updates are executable content.** Before public desktop distribution,
    installers and updates need signed manifests, rollback protection, pinned
    dependencies, an SBOM, and reproducible or independently verifiable build
    records.
16. **No secrets or private data in Git.** No credentials, private forms,
    generated reports, personal paths, or raw private document text. Security
    work uses synthetic or public documents only.

A separate executable threat model should follow this document
(`docs/threat-model.md`), mapping each trust boundary to abuse cases, controls,
tests, residual risks, and an owner. `SECURITY.md` remains the disclosure
policy; it is not a substitute for that model.

## 7. Desktop strategy

### Windows first, architecture not Windows-only

The first complete desktop product targets Windows. The strongest current proof
path depends on locally installed Hancom Office and COM, and `support-matrix.md`
records that path as demonstrated only on Windows.

The Runtime protocol and the HWPX/XML engine stay portable. Linux and macOS can
support the evidence that has actually been demonstrated, without pretending
native Hancom proof exists there. Cross-platform packaging follows after the
Windows workflow is coherent and the relevant platform benches exist.

### Measure the shell before committing to it

The preferred starting point is a Tauri 2 shell with a React + TypeScript
frontend, a packaged Python Runtime sidecar over JSONL/stdio, narrow shell
commands, native file dialogs, and OS credential storage for provider secrets.

That preference is a starting point, not a decision. Run a measured
shell/sidecar spike first, recording startup, packaging, Korean IME, high-DPI,
process cleanup, installer size, crash behavior, and signed-update support. If
Tauri has a concrete blocking problem, compare PySide6/QML on the same
criteria. Do not switch on taste, and do not rewrite the Python engine in Rust
or TypeScript.

### Quality bar

Desktop is a product, not a debug console. Korean-first typography; calm,
restrained neutral surfaces; one coherent accent system; stable layout during
streaming; motion that explains a view transition; native-language Korean UI
copy; strong keyboard navigation and focus; common Windows DPI coverage;
human-readable errors with technical evidence behind progressive disclosure.

Explicitly avoided: generic neon AI gradients, heavy glass effects, and a
dashboard-card grid as the main composition. Loading, unavailable, refused,
crashed, interrupted, and recovery states are designed states, not raw
exceptions. A fresh-context reviewer must inspect the running application and
real screenshots, not source code alone.

## 8. Roadmap and exit criteria

The roadmap is ordered by product risk, not by feature count. **There is one
ladder: Phase 0–6**, defined normatively in
[`plans/agent-native-desktop-goal.md`](plans/agent-native-desktop-goal.md) §18
and tracked with live status in
[`plans/agent-native-desktop-program.md`](plans/agent-native-desktop-program.md).

> **The earlier M0–M5 milestone ladder in this document is superseded.** It is
> retained below only as a translation table so older issues, branches, and
> commit messages remain readable. Do not plan against M-numbers.

| Superseded | Now | Note |
|---|---|---|
| M0 — Product and protocol contract | Phase 0 + Phase 1 | M0 bundled direction work and protocol work; these are now separate phases with separate exits. |
| — | Phase 2 — CLI and MCP parity | New. M0–M5 had no explicit multi-client parity gate. |
| M1 — Read-only Desktop | Phase 3 | Phase 3 adds the dual-view requirement M1 did not have. |
| M2 — Verified editing | Phase 4 | Unchanged in substance. |
| M3 — Agent-assisted editing | Phase 5 | Phase 5 is broader: embedded providers, external MCP, and router adapters, not only in-app assistance. |
| M4 — Secure distribution and ecosystem | Phase 6 | Phase 6 scopes to Developer Preview hardening; public signed distribution remains gated on user authorization. |
| M5 — Broader document workbench | (none) | Deliberately out of the ladder. See §8.2. |

### 8.1 The phase ladder

Each phase's exit is a *demonstration*, not a document.

**Phase 0 — Product truth and direction.** Repository and release truth audit,
agent-native identity, dual-view UX, surface separation, the living program
document, architecture, threat model, acceptance document, corrected docs
index.
*Exit:* an unfamiliar contributor understands the product, the authority model,
the initial flow, and current limits without reading report-pipeline history
first.

**Phase 1 — Runtime Protocol v0 and headless vertical slice.** Schemas, JSONL
protocol, strict initialization, host and agent entrypoints, contained
sessions, immutable import, real document summary and graph, one existing
engine edit, plan validation, host approval, a separate candidate, source
proof, applicable checks, honest unavailable checks, receipt, export, focused
tests.
*Exit:* the edit is reproducible headlessly.

**Phase 2 — CLI and MCP parity.** CLI with JSON output and stable exits, the
MCP adapter, allowed-root/attached-session policy, inspect-and-propose default,
setup examples, parity tests.
*Exit:* Runtime, CLI, and MCP produce compatible plans and verification for the
same task.

**Phase 3 — Read-only premium Desktop foundation.** Measured shell spike,
`desktop/`, packaged sidecar, lifecycle, native import, recovery, a shared
store, both views, synchronized state, real preview or an honest unavailable
state, real structure, proof display, a deterministic mock agent, the design
system, keyboard and DPI checks, screenshots, visual review.
*Exit:* a clean user can open, understand, switch views, and reopen without a
terminal.

**Phase 4 — Verified Desktop editing.** Bounded direct editing, plan review,
before/after, invariants, approval, candidate generation, verification,
comparison, export, a receipt/evidence viewer, crash and cancel recovery.
*Exit:* one public supported task completes from packaged Desktop with no XML
work and no checkout access.

**Phase 5 — Agent-native operation.** Contextual panel, full timeline, location
navigation, the mock flow, the external MCP flow, a custom router, one official
embedded provider, secure settings, capability negotiation, streaming,
prompt-injection cases, and disclosure of what may leave the device.
*Exit:* manual, embedded-agent, and external-agent work share the same plan and
verification path without authority collapse.

**Phase 6 — Developer Preview hardening.** Windows preview package, clean-machine
evidence, process cleanup, installer/update/uninstall planning, dependencies and
SBOM, performance, DPI, accessibility, privacy, a clean-room task, independent
architecture/security/visual reviews, coherent docs.
*Exit:* the Developer Preview criteria hold. Nothing is published publicly
without user authorization.

### 8.2 After the Developer Preview

The broader workbench that was M5 — richer paragraph, table, image, equation,
header/footer, note, and style editing; reusable templates and batch
operations; cross-platform HWPX desktop builds; reviewed SDK/API surfaces;
additional document families backed by representative corpora; richer visual
editing — is deliberately **outside** the ladder. A full word-processor surface
is a possible long-term result, not a milestone to plan against now.

Explicitly deferred until the Developer Preview is complete: Hancom Office
parity, blank-page word processing, unrestricted XML or macros, cloud sync or
real-time collaboration, public third-party executable plugins, automatic final
export by a model, unrestricted agent shell or filesystem, a machine-wide
daemon, a public auto-update service, broad new document-family expansion,
engine rewrites in another language, speculative abstractions with no current
consumer, unrelated report-pipeline features, and any fabricated page layout or
bounding box.

## 9. Measures that matter

The project should continue to report tests, but product decisions should use a
smaller set of user-facing measures:

- **clean-install task completion rate:** supported tasks completed from a
  packaged install with no checkout fallback;
- **source preservation:** the imported source byte-identical after every
  completed task;
- **exact operation accounting:** every declared operation applied, refused, or
  reported — never silently dropped;
- **verified-output rate:** completed tasks whose claimed structural and render
  evidence is actually present and bound to the exported bytes;
- **false-pass rate:** bad artifacts accepted by a gate or UI summary;
- **false-block rate:** valid artifacts rejected by a hard gate;
- **time to first verified output:** from opening the application to exporting a
  checked candidate;
- **form-family coverage:** representative documents and successful tasks, not
  merely named modules;
- **unsupported-state clarity:** whether the UI identifies why a check could not
  run and what evidence is still missing;
- **crash-recovery success:** source and workspace integrity after cancellation,
  crashes, renderer hangs, and interrupted updates;
- **independent reproduction:** results repeated from packaged artifacts by a
  different machine or operator;
- **visual and interaction quality:** judged from real screenshots of the
  running application.

Raw checker count, test count, and supported-format labels are supporting
metrics, not the product outcome. Do not invent attractive numbers; an
unmeasured metric is reported as unmeasured.

## 10. Repository consequences

Adopting this direction implies documentation and governance changes. Each is
tracked as a Phase 0 decision in
[`plans/agent-native-desktop-program.md`](plans/agent-native-desktop-program.md),
including the two that are outward-facing and need explicit user confirmation:

- package metadata and the public repository description should identify an
  agent-native HWP/HWPX editor and automation runtime, not only a report
  workflow;
- version and release truth should agree across package metadata, tags, release
  records, bundles, and published GitHub Releases;
- report-specific operating instructions should live under the report module or
  clearly identify themselves as one workflow;
- `docs/architecture.md` should grow from a stage-machine overview into the
  current Runtime and trust-boundary architecture;
- `docs/threat-model.md`, `docs/desktop-architecture.md`,
  `docs/runtime-protocol-v0.md`, and `docs/desktop-acceptance.md` should be
  added before substantial shell code;
- Studio documentation should distinguish current diagnostic behavior from the
  future Desktop contract and stay synchronized with canonical verdict
  behavior;
- desktop and release branches should require the relevant CI and packaging
  checks before distribution;
- roadmap work should be tracked as user journeys and threat-model closures,
  not as an unbounded list of document features.

Direction documents and implementation stay in separate pull requests.

## 11. Immediate next work

The next cycle should be small and ordered:

1. Finish the Phase 0 documentation set: this document, the program document,
   the desktop threat model, the desktop architecture note, and the acceptance
   document.
2. Specify Runtime Protocol v0 against existing engine operations and verdicts;
   do not duplicate document logic in a UI or invent a second editing engine.
3. Define the clean-install acceptance tasks: read-only inspection, one fixed
   form fill, one agent proposal, one external-agent proposal, one hostile
   document, and one crash/cancellation run.
4. Build the headless Phase 1 vertical slice — one real supported edit, one
   plan, one approval, one candidate, one receipt.
5. Run the shell/sidecar spike against the recorded criteria and write down the
   decision.
6. Align public metadata and version/release truth after the direction is
   accepted, with user confirmation for anything outward-facing.

New document families, unrestricted plugins, and autonomous model actions wait
until these foundations are measured.

## 12. Strategic summary

Rigorloom has already built an unusually rigorous document-processing core. Its
next risk is not lack of capability; it is allowing the product to remain a
collection of excellent internal mechanisms that only repository experts can
operate.

The right next step is to make one verified HWP/HWPX workflow reachable as a
real local application — usable the same way by a person and by an agent, with
different authority and the same evidence — while preserving the qualities that
distinguish the project: non-destructive operations, explicit limits,
deterministic checks, artifact-bound evidence, provider neutrality, and a
refusal to call an unmeasured result proven.
