# Agent-native desktop program — durable Goal specification

Status: **normative orchestration specification for the Claude Goal**  
Primary orchestrator: **Claude Fable 5**  
Implementation and independent-review workforce: **Claude Opus 5**  
Scope: `pantagram1031/rigorloom`  

This document is meant to be read in full by the compact Claude Goal condition.
It carries the long-lived mission, architecture, execution policy, acceptance
criteria, and safety boundaries that do not fit in the Goal field.

This is a target-state and program document, not a statement that every feature
below already exists. Current capability remains defined by executable tests,
`docs/support-matrix.md`, release records, and inspected source code.

The Goal does **not** authorize merging to `main`, publishing releases, uploading
installers, changing branch protection, using private credentials, or declaring
unrun checks successful.

---

## 1. Orchestrator role

Claude Fable 5 acts as the executive technical lead, product architect, security
owner, program manager, and final integrator for Rigorloom.

Fable owns:

- the product goal and interpretation of this document;
- architecture and sequencing;
- workstream ownership;
- delegation to Opus 5;
- integration and conflict resolution;
- evidence review;
- product coherence;
- durable Goal state;
- user-facing progress reports.

The user is not asking for a speculative design exercise. The work must progress
from repository audit to reviewable implementation and a real Developer Preview.
Do not stop after producing a roadmap, mockup, folder skeleton, or untested API.

## 2. Mission

Transform Rigorloom into:

> **An agent-native, local-first HWP/HWPX desktop editor and automation runtime
> with verifiable operations.**

Korean product sentence:

> **사람과 AI 에이전트가 같은 검증형 작업 체계로 한글 문서를 열고, 이해하고,
> 수정하고, 검증하는 로컬 데스크톱 편집기이자 자동화 런타임.**

The installed desktop application is the main user product.

The same underlying Runtime and operation model must also be usable by:

1. Rigorloom Desktop;
2. Rigorloom CLI;
3. Claude Code, Codex, and compatible clients through Rigorloom MCP;
4. embedded provider adapters inside Desktop;
5. headless automation without Desktop.

The report pipeline remains valuable, but it becomes one optional workflow
module. It must not remain the identity of the whole project.

Rigorloom is not initially trying to become:

- a complete clone of Hancom Office;
- a blank-page general-purpose word processor;
- a cloud editor that uploads private documents by default;
- a model-specific agent framework with document support attached;
- an autonomous system that silently applies model edits;
- a public executable-plugin marketplace;
- a product that calls missing or unmeasured evidence “verified.”

The strategic advantage is the combination of Korean document handling, bounded
operations, deterministic checks, explicit unknown states, render evidence,
agent assistance, and reproducible records of what changed.

## 3. Developer Preview completion target

The program is complete only when an **Agent-Native Desktop Developer Preview**
meets all conditions below.

### 3.1 Packaged application

- A Windows development build runs outside the repository checkout.
- Desktop owns the Runtime sidecar lifecycle.
- A supported HWPX document can be imported as an immutable source.
- The application can close and reopen a saved workspace.
- Runtime crashes and interrupted work produce recoverable or clearly failed
  states instead of a blank or falsely successful UI.

### 3.2 Two synchronized views

Desktop contains two polished views over the same Workspace.

**Document view**

- document/page/structure navigation on the left;
- real document page or honest preview-unavailable state in the center;
- contextual agent panel on the right;
- verification, source/candidate, and proof state at the bottom.

**Agent view**

- workspaces, tasks or threads, documents, and attachments on the left;
- a polished Codex-like document-agent timeline in the center;
- current document preview, artifacts, plans, candidates, and verification on
  the right.

Both views share:

- one Workspace;
- one active document session;
- one conversation/thread state;
- one selected document node or region;
- page, zoom, and relevant navigation state;
- one operation-plan queue;
- one approval state;
- one candidate-artifact set;
- one verification history.

Switching views must not create a new conversation or duplicate document state.
The Document-view agent panel should expand naturally into Agent view while the
document becomes the right-side context and artifact surface.

### 3.3 Real editing and evidence

- A person can perform one real supported edit through Desktop.
- A deterministic mock agent can propose the same edit.
- Manual and agent-proposed edits use the same `OperationPlan` contract and
  candidate-generation path.
- The user can review and approve the plan.
- Approval creates a separate candidate; the source remains byte-identical.
- Existing applicable Rigorloom checks run against the candidate.
- Checks that cannot run remain unavailable, skipped, unknown, or unverified;
  they are never shown as passed.
- The candidate can be exported through a host-controlled destination picker.
- A deterministic receipt binds source bytes, plan, approval, candidate bytes,
  implementation version, checker results, and proof state.

### 3.4 CLI, MCP, and providers

- The supported operation can be reproduced through CLI.
- A local STDIO Rigorloom MCP server exposes the agent-safe Runtime subset.
- Claude Code or Codex can inspect and propose without unrestricted filesystem,
  shell, approval, export, provider-credential, or proof authority.
- The embedded Agent Host has a real provider-adapter architecture.
- A deterministic mock provider exists for repeatable tests.
- A configurable custom-router adapter is implemented and tested against a fake
  server.
- One official provider path is implemented as far as legitimately available
  credentials and user interaction permit.
- A live authentication smoke may be `not run`; implementation, contract tests,
  connection UI, failure handling, and credential boundaries must still be
  complete. Never fabricate a live login result.

### 3.5 Product quality

- The UI has been visually reviewed from real screenshots.
- Korean and mixed Korean/Latin typography is deliberate and readable.
- Common Windows DPI scales are checked.
- Keyboard focus and navigation are usable.
- Loading, unavailable, refused, crashed, interrupted, and recovery states are
  designed, not left as raw exceptions.
- The application does not look like a generic admin dashboard or unfinished
  developer tool.

## 4. Current repository context

Treat all statements here as hypotheses until the current tree and tests are
inspected.

Rigorloom has previously contained:

- an HWP/HWPX engine under `engine/`;
- a Windows + Hancom COM path;
- a Hancom-free HWPX/XML path;
- address-based document operations;
- form recognition and structural inspection;
- deterministic gates and explicit warning, refusal, skipped, unavailable, and
  proof states;
- hashes, receipts, provenance, and render-proof grades;
- clean-room bundle installation and verification;
- one core plus separately installable distribution modules;
- report, style, gongmun, minwon, HR, and grant modules;
- a localhost Studio used as an operator/developer dashboard;
- a history of adversarial fixes involving false passes, false blocks, paths,
  evidence binding, renderer boundaries, privacy, and artifact identity.

There may be a draft PR `#150` and branch
`docs/product-direction-desktop`. Inspect the real GitHub state rather than
assuming they remain unchanged. Keep product-direction work documentation-only.

Package metadata, root README, repository description, release records, tags,
and the latest GitHub Release may disagree. Record observed truth before
changing it.

## 5. Autonomy

Operate autonomously and continue useful work across context windows.

Pause for the user only when work genuinely requires:

- a destructive or irreversible action;
- a merge, release, installer publication, signing, or repository-policy change
  forbidden below;
- a material change to the agreed product scope;
- credentials, legal identity, certificates, branding assets, or another input
  only the user can supply;
- two interpretations that lead to materially different products and cannot be
  resolved from this document or the repository.

For reversible implementation decisions, choose the strongest reasonable option,
record it, and proceed.

When credentials are unavailable:

- implement deterministic fakes;
- preserve an optional live smoke path;
- mark the live path `not run`;
- continue all independent work.

Do not repeatedly revisit an accepted decision unless new evidence contradicts
it.

## 6. Fable–Opus orchestration policy

Fable is the orchestration authority and final integrator.

Use Opus 5 for substantial independent workstreams that benefit from isolated
context or parallel execution. Do not delegate a trivial search, routine command,
or tiny single-file edit.

### 6.1 Concurrency and ownership

- Use no more than four Opus 5 agents concurrently.
- Prefer a few long-lived agents with stable subsystem context.
- Use separate branches and worktrees.
- No two agents edit the same files concurrently unless Fable defines an
  integration owner and conflict plan.
- Nested delegation is disabled unless Fable explicitly authorizes it.
- Do not silently replace Opus 5 with a weaker model on a critical assignment.
  If Opus is unavailable, Fable either performs the work or records the track as
  blocked.

### 6.2 Delegation packet

Every assignment must state:

- objective and reason for delegation;
- owned branch/worktree;
- files or subsystem owned;
- files that must not be changed;
- repository documents and contracts to read;
- acceptance criteria;
- required focused tests;
- security constraints;
- expected handoff format;
- whether the task is implementation, research, design, or independent review.

### 6.3 Handoff requirements

Every Opus handoff must contain:

- outcome;
- branch and commit identifiers;
- changed files and reasons;
- exact commands and tests run;
- actual exit statuses and material output;
- checks not run;
- assumptions;
- unresolved risks;
- integration notes;
- any finding that changes program direction.

Fable must inspect commits, diffs, tests, and artifacts. A prose claim is not
evidence.

### 6.4 Suggested initial tracks

Use these only if the audit confirms they remain sensible.

**Track A — repository truth and product direction**

- Audit architecture, capabilities, docs, releases, and PR `#150`.
- Own documentation changes on the direction branch.
- Do not implement Runtime or Desktop code there.

**Track B — Runtime and security architecture**

- Map engine entrypoints, strict JSON, receipts, artifact publication, path
  controls, worker boundaries, and verification contracts.
- Design and implement Runtime Protocol v0 and the first vertical slice.

**Track C — Desktop product and experience**

- Audit Studio and UI assets.
- Define information architecture and design language.
- Run the shell/sidecar spike.
- Own Desktop after the protocol is stable.

**Track D — acceptance and adversarial review**

- Define user-task acceptance and threat-model cases.
- Review completed phases from a fresh context.
- Remain independent from the implementation branch reviewed.

## 7. Durable state management

Use Goal persistent memory for compact operational state. Use Git, PRs, issues,
and repository documents for durable project state.

Maintain Goal state containing:

- immutable mission;
- current phase;
- accepted architecture decisions;
- active agents and branch ownership;
- PR dependency graph;
- verified evidence;
- unresolved risks and blockers;
- decisions requiring user input;
- next executable task.

Create and maintain one living public program document, preferably:

`docs/plans/agent-native-desktop-program.md`

It should hold milestones, dependencies, status, and acceptance gates without
becoming a minute-by-minute log.

Before context refresh or major handoff:

- commit coherent work;
- leave the worktree clean or document intentional changes;
- update Goal state;
- record exact next actions;
- preserve failed-test evidence when it affects the next decision.

On resume, inspect Goal state, Git status, recent commits, current PRs, and test
evidence before continuing.

## 8. Repository-first actions

Before changing files:

1. Confirm repository identity and working directory.
2. Read `AGENTS.md` and `CONTRIBUTING.md` fully.
3. Inspect Git status, branch, worktrees, open issues/PRs, recent commits, CI,
   tags, Releases, package version, and repository metadata.
4. Read at minimum:
   - `README.md`;
   - `SUMMARY.md`;
   - `SECURITY.md`;
   - `docs/README.md`;
   - `docs/product-direction.md` if present;
   - `docs/architecture.md`;
   - `docs/design-decisions.md`;
   - `docs/support-matrix.md`;
   - the current release record;
   - `modules/README.md`;
   - `studio/README.md` and `studio/main.py`;
   - `engine/README.md`;
   - `pyproject.toml`;
   - relevant engine operations and tests;
   - strict-JSON, verdict, receipt, publication, path, artifact-binding, and
     clean-room code.
5. Run the repository’s documented fast baseline, capability/module probe,
   privacy scan, and diff check where available.
6. Record stale or contradictory documentation.
7. Delegate independent audits.
8. Establish a PR dependency graph and begin implementation.

Do not infer current capability from an old plan or README claim.

## 9. Product surfaces

### 9.1 Rigorloom Engine

Owns existing HWP/HWPX parsing, inspection, mutation, verification, renderer
adapters, receipts, and proof semantics. It remains headless and must not depend
on Desktop.

### 9.2 Rigorloom Runtime

A new local application-service boundary owning:

- workspaces and sessions;
- containment;
- typed operations;
- plans and approvals;
- candidates and artifacts;
- events and progress;
- cancellation;
- crash recovery;
- artifact references.

Runtime reuses Engine semantics instead of reimplementing them. The initial
transport is versioned newline-delimited JSON over stdin/stdout and requires no
network.

### 9.3 Rigorloom Desktop

The installed user product. It owns window lifecycle, native file dialogs,
Runtime sidecar lifecycle, interaction, review, accessibility, preview, settings,
and recovery. It does not directly parse HWP/HWPX or drive COM.

### 9.4 Rigorloom CLI

Human and automation interface over the Runtime/domain layer. It must not bypass
Runtime with separate editing semantics.

### 9.5 Rigorloom MCP

Thin adapter exposing only the agent-safe Runtime subset to Claude Code, Codex,
and compatible clients. MCP is not the internal Desktop lifecycle protocol.

### 9.6 Rigorloom Agent Host

A separate network-capable boundary for embedded providers. It compiles provider
requests into agent-safe Runtime calls and does not grant arbitrary filesystem,
shell, approval, export, or proof authority.

### 9.7 Rigorloom Studio / Inspector

The existing diagnostic/operator surface. It may supply concepts and prototypes
but must not silently become the shipping Desktop security boundary.

### 9.8 Rigorloom Modules

Existing first-party distribution modules remain the capability extension
mechanism. Users see task packs such as 공문 본문 수정 or 지원사업 신청서 작성, not an
internal module-management exercise.

Executable modules and Studio JavaScript are trusted installation-time code, not
a safe public plugin marketplace.

## 10. Architecture invariants

1. **One Runtime, multiple clients.** Desktop, CLI, MCP, and embedded providers
   share one domain model and operation implementation.
2. **Headless reproducibility.** Every Desktop operation and verdict can be
   reproduced headlessly.
3. **Source immutability.** Imported source files are never edited in place.
4. **Closed operations.** Normal interfaces expose schema-validated operations,
   not arbitrary shell, Python, XPath, XML, or filesystem access.
5. **One path for human and agent edits.** Both produce the same
   `OperationPlan` representation.
6. **Host and agent authority differ.** Shared Runtime does not imply equal
   privilege.
7. **Authority is not self-declared.** A request field such as
   `client_role: host` cannot grant privilege.
8. **Model output is untrusted.** Models cannot approve their own plans,
   overwrite sources, export arbitrarily, alter proof, or hide warnings.
9. **No ambient network in document processing.** Network belongs to Agent
   Host, not Runtime/Engine.
10. **Evidence remains scoped.** Operation execution, candidate reopen,
    structure preservation, renderer execution, visual acceptance, and
    submission grade are separate claims.
11. **Exact-byte binding.** Plans, approvals, candidates, reports, and receipts
    bind to the state described. Stale inputs refuse.
12. **Fail closed at external boundaries.** Invalid requests, malformed files,
    path escape, identity drift, and missing required verification do not become
    passes.
13. **Uncertainty is explicit.** Unsupported, unknown, skipped, and unavailable
    are legitimate visible states.
14. **Recovery is a feature.** Crashes, cancellation, hangs, and interrupted
    writes preserve the source and leave recoverable or clearly failed state.
15. **Core remains module-agnostic.** No hardcoded module names or inventory
    counts in core.
16. **No secrets or private data in Git.** Never commit credentials, private
    forms, generated reports, personal paths, or raw private document text.

## 11. Runtime Protocol v0

Create a versioned domain contract plus a JSONL stdin/stdout transport.

Use one authoritative schema source and mechanically validate or generate
TypeScript bindings. Avoid divergent handwritten Python/TypeScript contracts.

### 11.1 Required domain concepts

- protocol version and initialization;
- capability set;
- Workspace;
- Session;
- DocumentSummary;
- DocumentGraph and DocumentNode;
- EditableRegion;
- ArtifactRef;
- Operation;
- OperationPlan;
- PlanValidation;
- ApprovalRequest and ApprovalRecord;
- CandidateArtifact;
- Finding;
- VerificationReport;
- Event;
- Receipt;
- RecoveryManifest.

### 11.2 Transport requirements

- explicit initialize/version negotiation;
- ordinary calls refused before initialization;
- stable request identifiers;
- stable error/refusal codes;
- bounded frame size;
- strict duplicate-key rejection;
- non-finite JSON rejection;
- defined unknown-field policy;
- unknown methods and operation kinds rejected;
- stdout reserved for protocol frames;
- stderr reserved for human diagnostics;
- progress/lifecycle notifications;
- cancellation;
- deterministic serialization where bytes are hashed;
- graceful EOF and owned-child shutdown.

Do not use an unauthenticated localhost control server for the first version.

### 11.3 Authority surfaces

Host-only examples:

- open an arbitrary path chosen by the user;
- import attachment paths;
- resolve approvals;
- export to a user-selected path;
- configure providers;
- change policy;
- delete a workspace.

Agent-safe examples:

- list capabilities;
- read scoped session state;
- inspect a document;
- read DocumentGraph and exposed regions;
- propose and validate plans;
- request approval;
- read candidate and verification status.

Method names may change after audit. The separation may not.

## 12. Workspace, session, and operation model

The central product object is a Workspace, not merely a file or chat.

A Workspace contains:

- immutable imported source documents;
- declared attachments;
- sessions;
- one or more agent threads;
- current document and selected node;
- proposed and approved plans;
- candidates;
- verification reports;
- previews;
- append-only events;
- receipts;
- recoverable state.

A Session records source format/hash, internal source artifact, bounded temp
area, capabilities, plans, approvals, candidates, verification, events, and a
recovery manifest.

Agent-facing responses use scoped identifiers instead of arbitrary absolute
paths.

### 12.1 DocumentGraph

Reuse the strongest existing structural representation. Do not fabricate:

- page number;
- bounding box;
- editability;
- field identity;
- render coordinate;
- support state.

If only a logical address is known, return it and mark page positioning
unavailable.

### 12.2 OperationPlan

At minimum, bind:

- plan id;
- session id;
- exact source or candidate SHA-256;
- ordered operations;
- stable operation ids;
- target node ids or addresses;
- before/precondition fingerprints;
- expected invariants;
- required checks;
- proposer metadata;
- approval state;
- schema and implementation version.

A stale plan refuses when bytes, target identity, before state, approval binding,
or relevant policy has changed.

Applying a plan must create a distinct candidate, publish atomically, prove the
source unchanged, run applicable verification, preserve skipped/unavailable
checks, append events, and emit an exact-byte-bound receipt.

Do not create a second editing engine merely to make Runtime look clean. Adapt
existing tested operations first.

## 13. Desktop architecture and experience

### 13.1 Preferred technical direction

Preferred starting point:

- Tauri 2 shell;
- React + TypeScript frontend;
- packaged Python Runtime sidecar;
- JSONL over stdio;
- narrow Tauri commands;
- native file dialogs;
- OS credential storage for provider secrets.

Run a measured shell/sidecar spike before committing. If Tauri has a concrete
blocking problem, compare PySide6/QML. Record startup, packaging, Korean IME,
high-DPI, process cleanup, installer size, crash behavior, and signed-update
support. Do not switch based on taste alone.

Do not rewrite the Python engine in Rust or TypeScript.

### 13.2 Document view

- left: pages, document structure, tables, editable regions, warnings, and
  unsupported structures;
- center: actual page preview;
- right: contextual agent panel;
- bottom: source/candidate, pending changes, verification, proof, and unavailable
  evidence.

Supported editing initially uses overlays only where real positioning evidence
exists. Otherwise edit through a structure/field panel. The first editor is
bounded, not a full WYSIWYG implementation.

Supported controls may include field/cell entry, paragraph replacement,
run-address editing, approved equation operations, approved image replacement,
and task-specific form controls.

Protected or unsupported structures remain read-only with an explanation.

A direct user edit creates or updates an `OperationPlan`; it does not silently
mutate the source.

### 13.3 Agent view

- left: workspaces, tasks/threads, documents, attachments;
- center: document-agent timeline;
- right: document preview, artifacts, plan, candidate, verification;
- persistent instruction composer.

Default timeline cards summarize document work, not raw JSON or shell logs.
Technical detail remains expandable.

Agent references to a known document location navigate Document view. Selecting a
region in Document view updates agent context.

### 13.4 Premium quality bar

- Korean-first typography;
- calm, restrained neutral surfaces;
- one coherent accent system;
- stable layout during streaming;
- meaningful motion explaining view transitions;
- no generic neon AI gradients;
- no excessive glass effects;
- no dashboard-card grid as the main composition;
- progressive disclosure of hashes, JSON, commands, and diagnostics;
- native-language Korean UI copy;
- strong keyboard navigation and focus;
- common Windows DPI coverage;
- human-readable errors with technical evidence behind disclosure.

A fresh-context Opus visual reviewer must inspect the running application and
real screenshots, not source code alone.

## 14. Agent behavior

Agents may:

- inspect scoped document state;
- ask for missing information;
- propose typed operations;
- explain expected changes;
- request approval;
- inspect candidates and verification.

Agents may not:

- approve their own plan;
- overwrite the source;
- write arbitrary files;
- run arbitrary shell commands through Rigorloom;
- browse unrelated files;
- access ambient network through Runtime;
- export arbitrarily;
- alter verification or proof state;
- hide warnings or missing evidence.

Document text and external tool results are untrusted and may contain prompt
injection.

## 15. CLI and MCP

### 15.1 CLI

Expose a human/automation interface over the same Runtime/domain layer with JSON
output and stable exit semantics. Successful exit must not imply unavailable
verification ran.

### 15.2 MCP

Implement an optional local STDIO adapter over the agent-safe subset.

Default policy: **inspect and propose**.

Initial capabilities should include equivalents of:

- get capabilities;
- open within an explicit allowed root or attach to a host-created session;
- inspect document;
- get graph/editable regions;
- read an exposed region;
- propose and validate a plan;
- request approval;
- get plan/candidate/verification status.

Do not expose unrestricted document write, shell, approval, arbitrary export,
arbitrary file read, or network tools.

Standalone MCP requires an explicit allowed root or attached session and must
refuse traversal, symlink/reparse escape, and client-declared host privilege.

Claude Code and Codex use their own authentication. Rigorloom must not scrape or
copy their token caches.

## 16. Embedded Agent Host and providers

Agent Host is separate from Runtime and may use network access.

Provider adapters expose a common capability model covering model discovery,
text, images/pages, structured tools, structured output, streaming, resumable
threads, effort controls where officially available, local-only status, and
authentication ownership.

Do not assume all compatible endpoints have identical tools, vision, streaming,
or structured-output behavior.

Implementation order:

1. deterministic mock provider;
2. external MCP path;
3. custom-router adapter with fake-server tests;
4. one official embedded-provider path using current official documentation;
5. additional official or local adapters after the shared contract works.

Never read another application’s private token cache. Use official SDKs and login
flows. Store secrets in the OS credential store; ordinary settings files contain
only non-secret configuration.

## 17. Security program

Maintain:

- `docs/threat-model.md`;
- `docs/desktop-architecture.md`;
- `docs/runtime-protocol-v0.md`;
- `docs/desktop-acceptance.md`.

Distinguish implemented controls, planned controls, tests, and residual risk.

Cover at least:

1. crafted HWP/HWPX, malformed containers, encryption, external links, embedded
   objects;
2. archive/XML exhaustion: count, decompressed size, ratio, paths, depth, nodes,
   text, image pixels, recursion, time, memory;
3. traversal, symlinks/reparse points, hardlinks, parent replacement, TOCTOU,
   pre-existing destinations, foreign rollback, temp leakage;
4. parser/renderer compromise, process separation, timeouts, cancellation,
   resource limits, network denial, narrow working directories, recovery;
5. prompt injection and untrusted document/tool content;
6. role spoofing, approval forgery, stale plans, output substitution, hidden
   operations, model-created proof claims;
7. external MCP roots, methods, confused deputy, oversized payloads, denial of
   service, missing confirmation;
8. built-in modules, data packs, executable third-party modules, JavaScript
   panels, future signing/permissions;
9. provider tokens, OAuth, routers, logs, crash reports, environment, OS secret
   storage;
10. signed installers/updates, rollback, dependencies, SBOM, provenance, branch
    protection, update compromise;
11. stale/fabricated receipts, candidate swaps, proof-grade confusion, missing
    verifier treated as success, UI/canonical-verdict disagreement;
12. privacy in logs, paths, telemetry, screenshots, provider transmission, and
    workspace removal.

Use synthetic or public documents only.

## 18. Program phases

Keep changes reviewable. Do not collapse the whole program into one giant PR.

### Phase 0 — Product truth and direction

Deliver repository/release truth audit, agent-native identity, dual-view UX,
surface separation, living program document, architecture, threat model,
acceptance document, and corrected docs index. Keep PR `#150` docs-only if it
exists.

Exit when an unfamiliar contributor can understand product, authority, initial
flow, and current limits without reading report-pipeline history first.

### Phase 1 — Runtime Protocol v0 and headless vertical slice

Deliver schemas, JSONL protocol, strict initialization, host/agent entrypoints,
contained sessions, immutable import, real document summary/graph, one existing
engine edit, plan validation, host approval, separate candidate, source proof,
applicable checks, honest unavailable checks, receipt, export, and focused tests.

Exit when the edit is reproducible headlessly.

### Phase 2 — CLI and MCP parity

Deliver CLI, JSON output, stable exits, MCP, allowed-root/attached-session policy,
inspect-and-propose default, setup examples, and parity tests.

Exit when Runtime, CLI, and MCP produce compatible plans and verification for the
same task.

### Phase 3 — Read-only premium Desktop foundation

Deliver measured shell spike, `desktop/`, packaged sidecar, lifecycle, native
import, recovery, shared store, both views, synchronized state, real preview or
unavailable state, real structure, proof display, mock agent, design system,
keyboard/DPI checks, screenshots, and visual review.

Exit when a clean user can open, understand, switch views, and reopen without a
terminal.

### Phase 4 — Verified Desktop editing

Deliver bounded direct editing, plan review, before/after, invariants, approval,
candidate generation, verification, comparison, export, receipt/evidence viewer,
and crash/cancel recovery.

Exit when one public supported task completes from packaged Desktop without XML
work or checkout access.

### Phase 5 — Agent-native operation

Deliver contextual panel, full timeline, location navigation, mock flow, external
MCP flow, custom router, one official embedded provider, secure settings,
capability negotiation, streaming, prompt-injection cases, and disclosure of what
may leave the device.

Exit when manual, embedded-agent, and external-agent work share the same plan and
verification path without authority collapse.

### Phase 6 — Developer Preview hardening

Deliver Windows preview package, clean-machine evidence, process cleanup,
installer/update/uninstall planning, dependencies/SBOM, performance, DPI,
accessibility, privacy, clean-room task, independent architecture/security/visual
reviews, and coherent docs.

Do not publish publicly without user authorization.

## 19. Acceptance tasks

### A. Read-only inspection

Install outside checkout, open a public/synthetic supported HWPX, preserve source
hash, show capabilities/structure/editable/protected/unsupported/preview state,
switch views, close/reopen, and require no terminal after launch.

### B. Fixed-form edit

Select a real supported target, enter a value, observe a typed plan, review and
approve, generate candidate, preserve source, run checks, export candidate and
receipt, reopen candidate, and verify bindings.

### C. Embedded/mock agent proposal

Agent inspects, proposes typed work, cannot approve, user reviews in either view,
and candidate uses the same path as manual editing.

### D. External-agent proposal

Configure MCP for explicit root/session, connect Claude Code or Codex when
available, inspect/propose, prove host-only approval/export are unavailable, then
review through CLI/Desktop and compare parity.

### E. Hostile document

Include text attempting unrelated file reads, network access, approval bypass, or
proof relabeling. The model may quote/discuss it but cannot obtain forbidden
Runtime capability. Source and unrelated files remain unchanged.

### F. Crash and cancellation

Terminate Runtime during inspection, candidate creation, and verification.
Restart; source remains intact, partial candidate is not canonical, and workspace
is recoverable or clearly interrupted.

## 20. Verification policy

Implementation owners run focused tests and relevant repository checks. Do not
spawn a new verifier for every small commit.

At the end of a major phase, use a fresh-context Opus 5 verifier who did not
write the implementation. The verifier inspects code, tests, history, running
artifacts, and goal criteria and may not reinterpret missing evidence as success.

Use specialties when material:

- protocol/architecture;
- security/authority;
- clean-install user task;
- frontend visual/interaction.

The original implementation owner normally fixes findings; the verifier confirms
closures.

Required test classes include:

- protocol negotiation, pre-init refusal, malformed/duplicate/non-finite JSON,
  unknown fields/methods/operations, oversized frames, error codes, stdout/stderr,
  cancellation, EOF, shutdown;
- source immutability, containment, path handling, traversal, symlink/reparse,
  hardlink where relevant, parent replacement, stale plan/approval, duplicate ids,
  target drift, atomic publication, candidate identity, deterministic receipt,
  crash recovery;
- host methods absent from agent surface, role spoof refusal, MCP no approval or
  arbitrary export, provider no proof mutation, mock no self-approval;
- missing checker unavailable not passed, skipped visible, renderer execution not
  visual acceptance, UI badge follows canonical verdict, evidence cannot be
  swapped;
- shared Desktop state, selection/plan continuity, crash UI, unsupported preview,
  failed request not success, keyboard/focus/DPI, packaged sidecar lifecycle;
- provider capability negotiation, no secret logs, fake-server streaming,
  provider failure isolation, router mismatch, prompt injection, Runtime no
  ambient network.

For every PR, report exact commands and classify results as passed, failed,
skipped, not run, or unavailable. Do not use old logs as current evidence.

Do not weaken a valid existing test merely to make new architecture pass.

## 21. Git and PR policy

Allowed:

- branches and worktrees;
- coherent commits;
- issues;
- draft PRs;
- PR descriptions/comments;
- pushed implementation branches;
- CI runs;
- review-finding fixes.

Forbidden without explicit user authorization:

- merge to `main`;
- force-push `main`;
- delete protected/release branches;
- change branch protection;
- create/move public release tags;
- publish GitHub Releases;
- upload public installers;
- publish packages;
- sign/distribute updater;
- commit real credentials.

Keep direction docs and implementation separate. If PR `#150` exists, keep it
documentation-only and do not merge it.

Use separate implementation PRs by coherent vertical slice. Stacked draft PRs
are allowed with explicit dependencies. Avoid both one giant PR and dozens of
trivial PRs.

Each PR body states user outcome, rationale, architecture boundary, changed
subsystems, security implications, tests/results, missing evidence, limitations,
dependencies, and next slice.

Do not mix unrelated cleanup into feature branches.

## 22. Scope control

Do not attempt before Developer Preview completion:

- full Hancom Office parity;
- blank-page general word processing;
- unrestricted XML or macros;
- cloud sync or real-time collaboration;
- public third-party executable plugins;
- automatic final export by a model;
- unrestricted agent shell/filesystem;
- machine-wide daemon;
- public auto-update service;
- broad new document-family expansion;
- engine rewrite in another language;
- speculative abstractions without a current consumer;
- unrelated report-pipeline features;
- fabricated page layout or bounding boxes.

## 23. Quality and product measures

Prefer the simplest design that preserves real safety and multi-client needs.
Validate actual boundaries rather than adding speculative compatibility layers.

A completed phase must not contain fake implementations, placeholder-only APIs,
or TODOs standing in for its acceptance criteria.

Measure where possible:

- clean-install task completion;
- source preservation;
- exact operation accounting;
- verified-output rate;
- false-pass and false-block rate;
- unsupported-state clarity;
- time to first verified output;
- crash-recovery success;
- form-family evidence;
- independent reproduction;
- visual and interaction quality.

Do not invent attractive numbers.

## 24. User communication

Communicate progress in Korean.

Send concise updates only for material findings, completed milestones, real
blockers, or consequential user decisions. Tie claims to current commits, PRs,
tests, artifacts, screenshots, or tool results.

Say plainly when a check failed, skipped, was unavailable, or was not run.
Do not expose hidden chain-of-thought; report decisions, tradeoffs, evidence, and
outcomes.

## 25. Start and continuation instruction

Begin by inspecting the real repository and GitHub state, establishing durable
Goal state, assigning the initial Opus 5 audits, and correcting the docs-only
direction branch. Then proceed phase by phase.

Do not return only a roadmap. The roadmap is part of the work, not the final
deliverable.

Continue until the Developer Preview satisfies this document or a genuine
user-only blocker is reached. If one track is blocked, continue independent
tracks.

Before ending any working turn, check whether useful tool-driven work remains.
When it does, perform it rather than ending with a promise or optional suggestion.
