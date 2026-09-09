# Rigorloom product execution plan

Status: active plan, not a completion claim. Owner: Astra (product planning and acceptance). Execution lead: separate Codex Sol High task. Updated 2026-09-10.

## 1. Product outcome

Build the best practical agent-first Hancom document platform: a user installs Rigorloom, connects a supported agent, and can create, inspect, revise, validate and export real documents through documented CLI tools and reusable skills. Agents must be able to discover capabilities, target document objects precisely, preserve templates and recover safely. A later frontend visualizes and invokes the same core, making review and editing convenient without becoming a second implementation.

WindPath and Hawkes are demanding checkpoints, not the ceiling or the sole use case. The small pendulum/projectile reports are smoke tests. The long-term quality bar includes unfamiliar documents, multiple templates, edits to existing complex documents, reproducible long reports, and independent-user installation. Success is measured by correctness, fidelity, coverage, usability and reproducibility; a claim of being universally better than competitors is not an acceptance test.

User priorities: preserve useful previous effort; CLI first; full feasible Hancom editing/settings coverage; report/edit skills; faithful eventual rendering; no significant agent-facing formatting defects; efficient use of existing subscriptions. Do not replace these with an XML-only demo, GUI-only progress, or one successful report.

## 2. Authoritative workspace and ownership

Planning worktree: `C:/Users/user/dev/rigorloom-cli-product-plan`, branch `codex/cli-product-plan`, created from `8e1a1ea`. This document is versioned here. It does not overwrite existing plans or generated capability tables.

| Responsibility | Location / owner | Rule |
|---|---|---|
| Product plan and acceptance changes | this branch / Astra | Major tradeoffs and milestone acceptance; brief reviews |
| Routine orchestration | separate Sol task `01a08756-2564-7aa1-bcc9-d6e853f372b8` | Own queue, usage routing, review and local integration |
| Current report integration candidate | `C:/Users/user/dev/rigorloom-cli-report-essentials`, `codex/cli-report-essentials` | Clean `8e1a1ea` at planning baseline; recheck before each integration |
| Gate integrity card | `C:/Users/user/dev/rigorloom-cli-gate-integrity` | Existing Cursor owner; no concurrent edits to its two files |
| Historical unified preview | `C:/Users/user/dev/rigorloom-unified-working`, `ea02604` | Preserve; do not describe as finished CLI product |
| Historical report checkpoints | `C:/Users/user/Downloads/agenthwpx/reports/` | Originals immutable; sanitize new fixtures; no personal identifiers in repository |
| Native report workspaces | `C:/Users/user/RigorloomQA/` | NTFS for link-sensitive operations; one COM writer at a time |
| Evidence / live coordination | `F:/RigorloomQA/cli-first-success-20260909/codex-review/` | Logs, routing ledger, Herdr board and handoffs; not product source |

Each implementation card gets one owner and an isolated `codex/` worktree. Before integration: verify exact source SHA, clean target, ownership, patch scope and dependencies; review full diff and targeted tests; locally integrate only accepted commits. Preserve dirty or unrelated work. No remote push, release, main merge, credential change or paid overage is implied by this plan.

## 3. Preserve and recover prior work before replacement

Maintain a reuse inventory with feature, source branch/commit, relevant paths, proof level, dependencies and decision: reuse unchanged / adapt / retain historical / superseded with reason. Do not delete a historical variant merely because another variant looks newer.

Start with current engine/pipeline/module architecture and existing design/support/runtime documents. Inventory the renderer, writer, offset, agenthost, catalog, desktop, private-preview and QA branches visible in `git worktree list`, then remaining local/remote refs and relevant PRs. A branch existing is not evidence of integration. Explicitly record equivalent/cherry-picked changes and divergent contracts before bringing them together.

Current benchmark recovery is advisory evidence: WindPath v7 has an 18-page artifact but gate records pin v5; Hawkes has multiple claimed finals and a v17 20-page native verdict that remains unconverged. Missing research/figure assets or conflicting canonical pointers must be resolved rather than fabricating a reproducible pack. Preserve visual strengths and production mechanisms without copying private bylines or topic-specific code into generic product tools.

Reusable candidates include generic build/fill/COM/XML adapters, form preprocessing, paragraph/style normalization, existing module aliases, workflow gates/events/amendments, source checks, and proven desktop guards. Bespoke WindPath/Hawkes scripts become generalized operations only after their preconditions and side effects are understood.

## 4. Core architecture and contracts

Retain the existing separation: workflow kernel, capability-based agent adapters, document adapters, optional services. `PIPELINE.md` remains stage/gate authority; generated handoff state is not an independent state machine. The module layout manifest remains canonical artifact routing authority.

The product needs five coherent interfaces:

1. Document model and targeting: stable document/object addresses, selections/ranges, typed operations and explicit support boundaries. Detect stale targets before applying edits.
2. Backend capabilities: inspect, edit, assemble, measure, render and export with declared OS/Hancom/version prerequisites. Preserve unknown content or refuse unsupported mutations with actionable detail.
3. Agent-facing CLI/tool API: versioned structured input/output, discoverable schemas, deterministic exits, dry-run/plan where meaningful, operation receipts, safe path handling and resumable execution. Existing commands stay compatible or receive explicit migrations.
4. Workflow/skills: report, edit, verify, convert and style/form extraction use these public tools. The external agent performs reasoning/research; the CLI must not pretend that a stage pointer alone is an autonomous writer.
5. Frontend: consume the same document operations, receipts, capabilities and approval/recovery state. It must not silently bypass CLI gates or maintain divergent document semantics.

Proposed user-facing command groups, not claims that they already exist: doctor, capabilities, document inspect/edit, report init/resume, verify, render/export, recovery, and skills install. First reconcile with existing entrypoints rather than introduce duplicate wrappers. Tool errors must distinguish invalid arguments, unsupported capabilities, failed validation and successful command execution reporting a rejected gate.

## 5. Hancom coverage catalog

Build a machine-readable catalog from supported Hancom automation/action/parameter documentation and existing Rigorloom adapters. For each operation record read/write/settings scope, native API, portable behavior, preconditions, destructive potential, round-trip expectations, relevant Hancom versions and fixture/test IDs. A raw action escape hatch is advanced functionality, not proof of tested semantic coverage.

| Capability family | Required coverage | Acceptance evidence |
|---|---|---|
| Files and lifecycle | create/open/save/save-as/close, HWP/HWPX imports, supported exports, copies | Native reopen, file integrity, original preservation, explicit conversion loss |
| Text and selection | Unicode/Korean, find/replace, range/run edits, insertion/deletion, navigation | Exact intended text and stable target behavior after intervening edits |
| Character formatting | fonts/fallback, size, color, emphasis, underline, spacing, superscript/subscript | Native property readback and rendered samples; no style bleed |
| Paragraphs | alignment, indents, tabs, line/before/after spacing, keep/widow controls | Property and layout fixtures; form headers distinct from body text |
| Styles | named styles, inheritance, clone/deduplicate, scoped application | No unintended global mutation; deterministic repeated application |
| Pages and sections | paper size/orientation/margins, columns, sections, page/section breaks, binding | Native page metrics and rendered boundary cases |
| Headers and numbering | headers/footers, page numbers, lists/multilevel numbering, captions | Continuity across sections/edits and field refresh |
| Tables | create/edit, rows/columns/cells, merge/split, size, borders/fill, repeat headers, page splitting | Nested/merged/multipage fixtures; content retained and no clipping |
| Equations | inline/display, native syntax conversion, boxing, numbering, alignment | Semantic/script preservation plus native visual proof; boxed checkpoint recovery |
| Pictures and drawing | embed/replace/crop/size/anchor/wrap, shapes/text boxes/grouping where supported | Asset hashes, positions/wrap and native visual fixtures |
| Fields and references | bookmarks, hyperlinks, cross-references, TOC, footnotes/endnotes and metadata | Update/readback after edits; links and references resolve |
| Forms and templates | inspect anchors/guides, fill fields/cells, locked form regions, reusable maps | Pristine original hash; preserve fixed layout and unrelated controls |
| Review tools | comments, tracked changes, accept/reject and comparison where exposed | Native fixture coverage or explicit unsupported status |
| Charts/embedded objects | chart/OLE/media/object preservation and supported edits | Preservation fixtures; refuse unsupported internals rather than flatten silently |
| Document/application settings | supported document properties, language, printing/export settings and other exposed parameters | Read/change/readback/restore; separate document settings from persistent user settings |
| Protection/security | inspect protected/encrypted/signature states; authorized supported operations | Never bypass protection; edits invalidate signatures explicitly where applicable |
| Automation extension | discover and invoke additional documented actions with typed parameters | Validated schemas, guarded effects, logging; untested actions labelled untested |

Coverage states are separate: discovered, implemented, unit-tested, native-tested, rendered, supported-in-distribution. Unsupported or inaccessible Hancom features remain visible in the catalog with a reason and roadmap; do not call partial coverage every feature. Completion of the broad coverage milestone requires the entire feasible catalog classified and all promised supported operations verified.

## 6. Skills and report-quality contract

Report skill: brief intake and clarification; template inspection; research with source retrieval; design; simulations/data analysis when appropriate; source/claim/number provenance; writing; Korean style/humanization; native assembly; page inspection; iterative repair; final evidence and explanations. Support reports without simulations as well as data-heavy scientific reports. Do not require a simulation merely because Hawkes had one.

Editing skill: inspect before edit; resolve targets; preview scoped changes; apply safely; re-render affected pages; verify invariants and undo/recovery. Support both precise user-directed edits and agent-proposed revisions, with approval semantics tied to actual scope.

Verify/convert skills: structural and semantic checks, resource/font diagnostics, layout proof, conversion-loss report and canonical artifact binding. Never downgrade a native failure into portable success without stating the loss of proof.

Style/form skills: reusable private profiles outside source control, extraction with provenance, explicit scope, no silent copying of personal identifiers. Install instructions should work in at least two independently configured supported CLI agents.

Quality is not a page-count contest. Check accurate claims/calculations, complete brief fulfillment, coherent argument, language quality, sources, appropriate visual hierarchy, readable tables/equations, template fidelity and editability. WindPath/Hawkes checkpoint: sanitized long-form scientific document of comparable complexity (roughly18–20 pages, many figures, tables and display equations), reproducible from a complete input pack, independently reviewed and actually rendered. An xfail, structural control count, or old gate pass cannot satisfy this checkpoint.

## 7. Staged delivery and dependencies

| Milestone | Deliverables | Exit condition |
|---|---|---|
| M0: stable workspace and truthful evidence | reuse inventory, worker/tool receipts, ownership queue, fresh usage snapshots, benchmark manifests | Reproducible setup; no duplicate writers; all status claims bound to exact sources |
| M1: reliable essential CLI | gate-integrity fix, source syntax fix integration, scoped layout diagnosis/repair, discoverable stage metadata, deterministic errors | Fresh CLI report + edit flow finishes honestly; rejected gates cannot become finished delivery; no broad page exemption conceals defects |
| M2: long-form quality checkpoint | recovered/sanitized WindPath/Hawkes packs, generic boxed-equation/form features, provenance and canonical version fixes | Complete native renders, page-by-page review, semantic checks and reopen on copies; independently repeatable long-form report |
| M3: comprehensive document tooling | operation catalog and family-by-family supported implementations; report/edit/verify skills | Every promised operation has native/round-trip fixtures; unfamiliar-template edit corpus passes; unsupported remainder explicit |
| M4: distributable CLI product | packaging, doctor/prerequisites, skill installation, versioned tool schema, upgrades/uninstall/recovery, docs | Clean Windows machine installs and completes report+edit without repo paths/dev-only files; second supported agent can use it |
| M5: faithful frontend | same-core UI, selection/review, rendered feedback, history/recovery and local installation | End-to-end GUI tests including Korean IME; operation equivalence with CLI; real supported-document rendering fidelity |
| M6: release acceptance | external-user trials, regression corpus, performance/reliability baselines, support policy | Acceptance matrix complete; release artifacts reviewed; user approves publishing |

M3 catalog discovery and M4 packaging investigation can run alongside M1/M2, but they cannot steal ownership of active files or imply native parity. Frontend implementation follows a stable CLI contract. Renderer/rematch/certificate freezes remain current boundaries: M5 may require a narrowly defined, evidence-backed unfreeze decision from the owner; do not silently omit frontend fidelity from the final vision or violate the freeze now.

## 8. Initial implementation cards

| Card | Scope / suggested executor | Required verification and dependency |
|---|---|---|
| CLI-GATE-01 | Existing Cursor worker: report controller and controller tests only | RED temporary-fixture regression then GREEN; pending/rejected own script gates block done; preserve human/autonomous and legacy gate:null contracts |
| CLI-SOURCE-01 | Sol independently accepts existing8e1a1ea | Review DOI/tag normalization and focused tests; no new implementation if already proven |
| CLI-LAYOUT-01 | New isolated worker, QA measurement/checking layer only | Establish form-owned vs generated gap evidence; targeted form-zone rule or actionable repair needs; malformed body-spacing negative tests; native second-case rerun; no whole-page suppression |
| CLI-DISCOVERY-01 | CLI metadata/hand-off adapter owner | Current stage name/playbook/required artifacts discoverable through documented interface; agree with graph; no auto-approving missing human work |
| DOC-EQN-01 | Engine owner after reuse audit | Recover boxed display-equation intent from historical implementation; unit+native round-trip and rendered samples; unboxed behavior unchanged |
| DOC-FORM-01 | Form preprocessing owner | Generalized PII-free mapping, guide removal and clone normalization; idempotence; fixed-content preservation; native form check |
| EVIDENCE-01 | Pipeline artifact/receipt owner, after gate card | Canonical exact file/version/hash binding; stale receipt and off-book edits detected; explicit legacy migration, not retrospective false approval |
| BENCH-LONG-01 | Benchmark curator + independent native reviewer | Complete sanitized inputs/assets/sources/build command; no missing assets papered over; compare complexity and quality, not copied roster/text |
| TOOL-CATALOG-01 | Antigravity advisory inventory, Sol reconciles | Map documented Hancom API/action families to existing paths/tests and unsupported reasons; no feature implementation claims from docs |
| DIST-DOCTOR-01 | Packaging owner in isolated tree | Clean-environment dependency discovery, Hancom availability/version, fonts and portable limits; install smoke without developer paths |

Only CLI-GATE-01 is already assigned to an active implementation worker at plan creation. Sol assigns other cards after checking current ownership and dependencies, records exact worktree/base/allowed files and stops workers at reviewed milestones. Advisory worker recommendations do not alter acceptance criteria by themselves.

## 9. Verification and regression corpus

Keep source, unit/integration tests, native COM operations, PDF/image review, GUI, installation and release evidence separate. Every fixture manifest records input/output hashes, command/version/backend, dependency versions, status, exceptions and reviewer. Record failures/unrun checks explicitly.

Corpus must span small/long reports; at least three structurally distinct templates; plain prose; dense and multipage tables; boxed/inline/display equations; anchored/wrapped figures; section headers/footers; Korean/Latin mixed text and IME editing; fonts/fallback; fields; protected/unsupported controls; legacy documents; missing/corrupt assets; stale targets; interrupted apply and repeated requests. Grow fixtures from actual defects, not just mirrored implementation.

Native acceptance: open a copy, inspect repair prompts with an actual visible supported screen surface, edit/save/close/reopen, confirm content/control invariants and pages. Headless open=true is useful but is not no-dialog evidence. Inspect all pages for clipping, overlap, missing objects, orphan captions, unexpected spacing and template drift. Define layout tolerances by fixture/operation before adjusting code; never tune a checker solely to make a current output green.

Install acceptance: clean user profile/VM, documented licensed prerequisites, no local worktree aliases/private profile required, offline error behavior and uninstall preservation. Do not redistribute Hancom, proprietary fonts or private report inputs without rights. Portable mode must declare its feature/proof limits; whether Hancom-free perfect rendering is attainable remains a separate measured engineering question.

## 10. Agent roster and Herdr coordination

Astra owns this plan and strategic reviews. Separate Codex Sol High owns routine orchestration, card assignment, integration and acceptance preparation. Claude Code is reserved for high-value difficult implementation/review and native workflow reasoning, in fresh bounded sessions after a durable handoff. Cursor Grok handles scoped implementation/recovery; other Cursor models are selected by verified capabilities. SuperGrok Build handles useful independent research/review/implementation once its tool loop is verified. Antigravity CLI adds Google-backed advisory research, catalog extraction and independent reviews through supported sandbox mode.

Herdr named session `rigorloom` is the only authorized coordination surface. CLI workers should run in actual managed panes, with model/account label, assigned card and tool-access acknowledgement. Existing external jobs are mirrored until they finish safely. Sol and Astra app tasks use honestly labelled bridge panes unless an actual supported native session attachment is established. A dashboard/process existing is not proof of user-visible UI or working tool calls.

Every worker receives bounded context, owned paths, input artifacts, expected deliverable, acceptance commands and stop condition. Read shared coordination files before writes. Separate native COM execution from parallel source work: one COM owner at a time. External text saying done is not accepted without artifacts/tests. Do not restart on a mere observation timeout. Investigate terminal/cancelled/progress-only results before reusing a failing route.

## 11. Usage and operational controls

Use actual quota snapshots with service, redacted account label, window, direction (used vs remaining), capture time and reset time. File mtime alone is not freshness. Cached tracker Cursor values currently disagree with fresher browser values; do not combine them. Claude session dollar display is API-equivalent consumption, not subscription remaining allowance.

Default reserve:25% Codex and Claude. Prefer verified available Cursor/Antigravity/SuperGrok for routine work; spend reserved Claude on difficult bounded tasks. User authorizes using an expiring SuperGrok reset, but first verify the specific service/credit/expiry/need; never substitute Codex reset credits. Ordinary authorized account switching to user's other Cursor Google account may be used when appropriate through supported login; do not extract cookies/tokens, bypass limits or enable paid overages.

Sample locally every15minutes if safely supported; inspect provider quotas before expensive dispatch and after milestones. Let Sol perform a bounded operational check about every30–60minutes; notify Astra/user for meaningful milestones, blockers or anomalous burn. Avoid waking Astra on every log change. At >5 quota percentage points/15minutes or >2x sustainable pace until reset, checkpoint the suspected worker and inspect model, context growth, retries, subagent multiplication, cache counts and overlapping work. These thresholds are planning defaults, not provider rules.

Prefer compact handoffs and fresh purpose-specific sessions. Do not ask every model to review everything. Cheap deterministic local checks precede model reviews. A few high-quality independent reviews are more valuable than unbounded parallel agents. Runtime control boundaries and auth/tool availability are verified per provider before assigning production work.

## 12. Timing and next review

These are planning ranges, not measured delivery promises: M0/M1 roughly1–3 focused working days if native dependencies cooperate; M2 roughly3–10 further days; coverage/distribution across M3/M4 is likely multiple weeks; broad native compatibility and faithful frontend can take additional weeks or months. Re-estimate after the first gate/spacing cards and recovered long-form pack reveal actual defects. Parallel agents shorten independent tasks, not COM serialization, native QA or product decisions.

Immediate next review: accept or reject the gate-integrity patch; assign scoped layout correction; verify all worker tool receipts including Antigravity; finish prior-work inventory and long-form pack selection; publish the next5cards and dependencies on the board. This plan remains active until the full product requirements are demonstrated, not until a smoke report passes.

## Sources and evidence used for planning

- Existing `docs/architecture.md`, generated `docs/capability-matrix.md`, workspace/branch inventory and current source/hand-offs.
- Local `cursor-windpath-benchmark.txt`, `cursor-grok-controller-review.txt`, `cursor-gemini-cli-audit.txt`: advisory audits, not independent release certification.
- Native/first and second report evidence under `F:/RigorloomQA/` and `C:/Users/user/RigorloomQA/`.
- Claude context/cost guidance: https://code.claude.com/docs/en/costs and https://code.claude.com/docs/en/sub-agents . Use bounded contexts and account for subagent overhead.
- Cursor model/agent references: https://cursor.com/docs/agent/overview and https://prod.cursor.com/help/models-and-usage/available-models . Runtime account model listings remain authoritative for availability.
- Herdr automation: https://herdr.dev/docs/agent-automation/ . Native Windows Herdr is already installed; tmux is optional and not a prerequisite.
