# Product direction — a verifiable HWP/HWPX desktop workbench

Status: **proposed living direction**  
Last updated: 2026-09-01

This document defines what Rigorloom should become and how the existing system
should be used to get there. It is a product and architecture direction, not a
new capability claim. Current support remains defined by
[`docs/support-matrix.md`](support-matrix.md), the release records, and executable
tests.

## 1. Decision

Rigorloom should become a **local-first, evidence-producing workbench for safe
HWP/HWPX inspection, editing, verification, and automation**.

> 한글 문서를 안전하게 열고, 구조를 이해하고, 제한적으로 수정하고, 결과를
> 검증 가능한 증거와 함께 내보내는 로컬 워크벤치.

The desktop application should become the main user product. The existing CLI,
document engine, gates, receipts, proof ladder, and module registry remain the
authoritative implementation beneath it.

The report pipeline is valuable, but it should be presented as one optional
workflow module rather than as the identity of the whole project.

Rigorloom is **not** trying to become:

- a complete clone of Hancom Office;
- a general-purpose word processor before its narrower workflows are reliable;
- a model-specific agent framework with document support attached;
- a cloud editor that uploads private documents by default;
- an autonomous system that silently applies model-generated edits;
- a product that calls an output “verified” when the relevant evidence was not
  produced.

The strategic advantage is not a blank-page editor. It is the combination of a
Korean document engine, bounded operations, deterministic checks, explicit
unknown states, render evidence, and reproducible records of what changed.

## 2. Current product reality

Rigorloom already contains most of the difficult foundations of this direction:

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

The code is therefore broader than the repository’s older description of an
“agent-neutral, resumable report workflow.” The product surface, however, is
still split between several identities:

1. the root README increasingly describes a general document engine;
2. package metadata and many operating documents still describe a report
   pipeline;
3. the engine README describes an agent skill for editing HWP/HWPX;
4. Studio is a browser dashboard for developers and operators, not an installed
   desktop product;
5. work-type modules contain user-facing domain value, but users must understand
   the module and CLI model before reaching it.

This is the main product problem now. More checkers or another document family
will not resolve it. The next work must turn the existing mechanisms into one
coherent user journey.

Engineering validation is also much stronger than product validation. The
repository has extensive tests, clean-room installation checks, corpus work,
and detailed evidence records. It has much less evidence that a new user can
install the product, understand it, complete a useful document task, and trust
the result without reading the repository. Desktop work should be judged by that
user outcome, not by test count alone.

## 3. The initial product wedge

The first desktop release should solve one narrow, high-value job end to end:

> Open an untrusted local HWP/HWPX document, understand its structure and
> fillable regions, make bounded edits without altering unrelated form
> structure, inspect the result, run the available checks, and export a new file
> with an honest evidence record.

This is deliberately narrower than “edit any Korean document.” It is broad
enough to cover the project’s strongest existing form families and narrow enough
to verify.

### Primary users

The initial audience is:

- people completing Korean government, school, HR, and grant forms where the
  original layout must survive;
- developers and advanced operators automating HWPX documents;
- teams that need reviewable, repeatable document transformations rather than
  one-off macro scripts;
- AI-agent users who want a model to propose document work while deterministic
  software remains the authority.

### Core user journey

1. **Import safely.** Open a document as an immutable source and create a
   contained working copy.
2. **Inspect.** Show format, document family, sections, tables, fields, fillable
   seats, guide text, unsupported structures, and available renderers.
3. **Plan.** Turn user input or an optional model suggestion into a typed list of
   bounded operations.
4. **Review.** Show affected addresses, before/after values, expected structural
   invariants, and checks that will or will not run.
5. **Execute.** Apply operations to a new artifact, never in place.
6. **Verify.** Run structural, family-specific, privacy, residue, and render
   checks. Preserve warnings and unavailable evidence instead of converting
   them into success.
7. **Export.** Save the document, preview or proof artifact, and a compact
   receipt binding source, operations, output, tool version, and verdicts.

The first release does not need free-form pagination, desktop publishing, track
changes, or every Hancom feature. It needs this path to be understandable and
reliable.

## 4. Product surfaces and authority

The project should expose five named surfaces with clear responsibilities.

### Rigorloom Engine

The existing Python engine and deterministic checkers remain the source of
truth for document operations. They own parsing, inspection, mutation,
verification, receipts, and proof-state vocabulary.

The engine must stay usable headlessly. The desktop application must not become
the only way to reproduce an operation or a verdict.

### Rigorloom Application Service

A new application boundary should mediate between the desktop shell and the
engine. It should expose a small, versioned protocol over an inherited pipe,
standard I/O, or another desktop-owned local channel.

Responsibilities include:

- opening and closing contained document sessions;
- enforcing resource limits and workspace boundaries;
- validating typed operation requests;
- launching parser and renderer workers;
- streaming progress and structured findings;
- owning cancellation and crash recovery;
- returning references to artifacts rather than arbitrary filesystem access.

The shell should not import the parser and renderer stack directly. A malformed
document or renderer failure should not automatically become a compromise of the
whole application process.

### Rigorloom Desktop

The desktop shell owns user interaction, project/session state, review,
preview, accessibility, and installer integration. It consumes the application
service protocol and does not invent its own document semantics.

The current Studio is useful as a diagnostic and UX-prototyping surface. It
should remain available for developers and headless operators. A shipping
Desktop product, however, must own the service lifecycle and authentication; it
should not be defined as “manually start a localhost web server and open a
browser.”

### Rigorloom Modules

The existing distribution-module contract remains the way first-party
capability is separated. Report generation, style policy, gongmun, minwon, HR,
and grant behavior should appear in the desktop application as task packs and
specialized checks.

Today these modules are trusted installation-time Python and JavaScript code.
They are **not** a sandboxed third-party plugin ecosystem. Desktop packaging
must keep that distinction explicit. Data-only packs can be admitted under a
narrower trust model; executable third-party modules require signatures,
permissions, review, and process isolation before they can be marketed as safe
plugins.

### Agent adapters

Models and agents may research, draft, classify, or propose operations. They do
not own state transitions, file access, final verification, or the meaning of a
proof grade.

The stable interface should be capabilities and typed operations, not model
brands. A model change must not change the document safety contract.

## 5. Trust and security model

Security is not an adjacent portfolio feature. A desktop document processor
must handle several untrusted inputs at once:

- HWP/HWPX files and embedded resources;
- ZIP/XML structure, images, PDFs, and other document payloads;
- external renderer behavior and output;
- model-generated text and operation proposals;
- local modules and configuration;
- update and installer artifacts.

The protected assets are the user’s source document, unrelated local files,
private document contents, credentials, output integrity, verification records,
and the update channel.

### Required principles

1. **Source immutability.** A user-opened source is never modified in place.
   Every operation produces a distinct candidate artifact.
2. **Workspace containment.** A document session receives access only to its
   own source, declared attachments, candidate outputs, and temporary area.
3. **Bounded ingestion.** Archive member counts, decompressed size, compression
   ratio, XML depth, text size, image dimensions, recursion, and processing time
   need explicit ceilings and stable refusal reasons.
4. **Process separation.** Parsing, conversion, and rendering should run in
   workers that can be terminated and constrained independently from the UI.
5. **No ambient network.** Opening or verifying a document must not require
   network access. Any future online feature is explicit, separately
   permissioned, and visibly active.
6. **Typed operations.** The default edit interface is a closed operation
   vocabulary such as replace-at-address, fill-cell, set-run, insert-approved
   object, or convert-copy. It is not unrestricted shell or Python execution.
7. **Model output is untrusted.** Document text may contain prompt injection.
   Models may propose operations, but a permission broker validates scope and
   the user can inspect consequential changes before execution.
8. **Renderer evidence is scoped.** “The renderer ran,” “the output reopened,”
   “the page looked acceptable,” and “the artifact is submission-grade” are
   separate claims. Existing proof grades should retain that distinction.
9. **Evidence binds exact bytes.** Receipts must identify the source, declared
   operations, candidate artifact, relevant configuration, and checker version.
   A receipt must not silently apply to a later file.
10. **Recovery is part of safety.** Cancellation, crashes, power loss, and a
    failed renderer must leave the source untouched and candidates either
    complete or clearly disposable.
11. **Private by default.** Telemetry, crash uploads, cloud sync, and model calls
    are off unless the user deliberately enables a clearly scoped feature.
12. **Updates are executable content.** Before public desktop distribution,
    installers and updates need signed manifests, rollback protection, pinned
    dependencies, an SBOM, and reproducible or independently verifiable build
    records.

A separate executable threat model should follow this document. It should map
each trust boundary to abuse cases, controls, tests, residual risks, and an
owner. `SECURITY.md` remains the disclosure policy; it is not a substitute for
that model.

## 6. Desktop strategy

### Windows first, architecture not Windows-only

The first complete desktop product should target Windows. The strongest current
proof path depends on locally installed Hancom Office and COM, and Windows is
where users most commonly handle native HWP workflows.

The application-service protocol and HWPX/XML engine should remain portable.
Linux and macOS can support the evidence that has actually been demonstrated,
without pretending that native Hancom proof exists there. Cross-platform
packaging follows after the Windows workflow is coherent and the relevant
platform benches exist.

### Do not choose the shell before the boundary

The immediate decision is not “Tauri, Electron, or PySide.” First define and
test the application-service protocol, lifecycle, and artifact model. Then run a
small packaging spike comparing at least:

- a Python-native shell with direct packaging simplicity;
- a lightweight webview shell with the Python engine as a sidecar;
- the current Studio wrapped only as a transitional prototype.

The spike should be scored on Korean input/accessibility, installer size,
process isolation, signed-update support, file-dialog integration, crash
recovery, renderer supervision, and the ability to keep the engine headless.
The existing codebase makes a sidecar architecture plausible, but the choice
should follow measured packaging and security results rather than preference.

### Studio’s role

Studio should continue as:

- a local developer dashboard;
- an inspection and troubleshooting surface;
- a fast place to prototype desktop information architecture;
- a headless-operator option.

It should not silently become the desktop security boundary. First-party module
panels currently execute trusted UI payloads in the same Studio origin, and the
server exposes a guarded action mode. That is acceptable for the current trusted
local installation model; it is not yet a safe marketplace-plugin model.

## 7. Roadmap and exit criteria

The roadmap is ordered by product risk, not by feature count.

### M0 — Product and protocol contract

Deliver:

- this product direction adopted or amended;
- one vocabulary for Engine, Application Service, Desktop, Studio, Modules, and
  Agent adapters;
- a versioned session/operation/finding/artifact protocol;
- a canonical operation receipt schema;
- a desktop threat model and security-test inventory;
- one source of truth for version and release status across package metadata,
  docs, bundles, tags, and GitHub Releases;
- a small end-to-end acceptance pack based on user tasks, installed outside the
  checkout.

Exit when a third party can read one short architecture document and reproduce a
headless verified edit without learning the historical report pipeline first.

### M1 — Read-only Desktop

Deliver a packaged Windows application that can:

- import a source into a contained session;
- refuse unsupported or malformed input with actionable reasons;
- inspect HWP/HWPX capabilities and form structure;
- show fillable locations, guide text, warnings, and unsupported structures;
- show existing PDF/render evidence with honest proof labels;
- close and reopen a session without depending on the repository checkout.

Exit when a new user can install the application, open the supported corpus, and
understand what the program can and cannot safely do without using a terminal.

### M2 — Verified editing

Add:

- structured field and seat editing;
- an operation review queue;
- before/after text and structure summaries;
- non-destructive save-as behavior;
- family-specific checks surfaced in plain language;
- render/preview orchestration;
- export of document, evidence, and receipt;
- cancellation and crash-recovery tests.

Exit when selected official form tasks complete from a clean installer with no
manual XML work, the source hash remains unchanged, all expected operations are
accounted for, and a false pass/false block review has been performed.

### M3 — Agent-assisted editing

Add natural-language assistance only after M2 provides a safe operation path:

- model output compiled into typed proposed operations;
- explicit capability grants;
- prompt-injection test documents;
- side-by-side review of proposed changes;
- no direct shell, arbitrary filesystem, or ambient network capability;
- deterministic post-operation verification independent of the proposing model.

Exit when a hostile document cannot make the agent read another file, contact a
network service, bypass review, or relabel unavailable evidence as success in the
published threat-model test suite.

### M4 — Secure distribution and ecosystem

Add:

- signed Windows installer and update manifests;
- rollback protection and release-channel policy;
- SBOM and dependency review;
- reproducible bundle/application evidence;
- protected release workflow with required checks;
- explicit trust tiers for built-in modules, signed executable modules, and
  data-only packs;
- a public compatibility and support policy.

Exit when a clean machine can install, update, verify the installed version, and
remove the application without requiring a repository checkout or leaving
private workspaces behind unexpectedly.

### M5 — Broader document workbench

Only after the verified form workflow is established, expand toward:

- more paragraph, table, image, equation, header/footer, note, and style editing;
- reusable templates and batch operations;
- cross-platform HWPX desktop builds;
- reviewed SDK/API surfaces;
- additional document families backed by representative corpora;
- richer visual editing where it can preserve the evidence model.

A full word-processor surface is a possible long-term result, not the first
milestone.

## 8. Measures that matter

The project should continue to report tests, but product decisions should use a
smaller set of user-facing measures:

- **clean-install task completion rate:** supported tasks completed from a
  packaged install with no checkout fallback;
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
- **recovery success:** source and workspace integrity after cancellation,
  crashes, renderer hangs, and interrupted updates;
- **independent reproduction:** results repeated from packaged artifacts by a
  different machine or operator.

Raw checker count, test count, and supported-format labels are supporting
metrics, not the product outcome.

## 9. Repository consequences

Adopting this direction implies several documentation and governance changes:

- package metadata and the repository description should identify a verifiable
  HWP/HWPX workbench, not only a report workflow;
- report-specific operating instructions should live under the report module or
  clearly identify themselves as one workflow;
- `docs/architecture.md` should grow from a stage-machine overview into the
  current runtime and trust-boundary architecture;
- `docs/threat-model.md`, `docs/desktop-architecture.md`, and
  `docs/desktop-acceptance.md` should be added before substantial shell code;
- Studio documentation should distinguish current diagnostic behavior from the
  future Desktop contract and stay synchronized with canonical verdict behavior;
- release metadata, tags, bundles, and release records should not disagree about
  the current version;
- desktop and release branches should require the relevant CI and packaging
  checks before distribution;
- roadmap work should be tracked as user journeys and threat-model closures,
  not as an unbounded list of document features.

## 10. Immediate next work

The next implementation cycle should be small and ordered:

1. Write the desktop threat model from the actual parser, renderer, module,
   Studio, update, and model boundaries.
2. Specify a versioned headless application-service protocol using existing
   engine operations and verdicts; do not duplicate document logic in a UI.
3. Define three clean-install acceptance tasks: read-only inspection, one fixed
   form fill, and one body edit with export and receipt.
4. Build a read-only Windows desktop spike that owns the child service process
   and opens a contained document session.
5. Compare desktop-shell options against the same packaging and security
   criteria, then record the decision.
6. Align public metadata and version/release truth after the direction is
   accepted.

New document families, unrestricted plugins, and autonomous model actions should
wait until these foundations are measured.

## 11. Strategic summary

Rigorloom has already built an unusually rigorous document-processing core. Its
next risk is not lack of capability; it is allowing the product to remain a
collection of excellent internal mechanisms that only repository experts can
operate.

The right next step is to make one verified HWP/HWPX workflow accessible as a
real local application while preserving the qualities that distinguish the
project: non-destructive operations, explicit limits, deterministic checks,
artifact-bound evidence, provider neutrality, and refusal to call an unmeasured
result proven.
