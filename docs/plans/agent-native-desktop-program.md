# Agent-native desktop program — living program document

Status: **living program record — Phase 0 in progress**  
Last updated: 2026-09-01

This is the running state of the agent-native desktop program: where it is,
what each phase must deliver, what depends on what, and what the repository
actually looks like today.

Three documents, three jobs:

| Document | Job |
|---|---|
| [`agent-native-desktop-goal.md`](agent-native-desktop-goal.md) | **Normative.** The durable specification: mission, invariants, phases, acceptance tasks, security and Git policy. Read it for what is required. |
| [`../product-direction.md`](../product-direction.md) | **Explanatory.** What the product is, for whom, with what boundaries. Read it to understand the product. |
| This document | **Operational.** Status, gates, dependencies, decisions, and observed repository truth. Read it to know where the program stands. |

This document holds milestones, dependencies, status, and acceptance gates. It
is not a minute-by-minute log, and it does not restate the specification.
Nothing here claims a capability exists; the capability authority is
[`../support-matrix.md`](../support-matrix.md).

---

## 1. Mission

> **An agent-native, local-first HWP/HWPX desktop editor and automation runtime
> with verifiable operations.**

> **사람과 AI 에이전트가 같은 검증형 작업 체계로 한글 문서를 열고, 이해하고,
> 수정하고, 검증하는 로컬 데스크톱 편집기이자 자동화 런타임.**

The installed desktop application is the main user product. The same Runtime
and operation model must also serve the CLI, external agent clients over MCP,
embedded provider adapters, and headless automation.

The program is complete when an **Agent-Native Desktop Developer Preview**
satisfies the completion target in the Goal specification §3: a packaged
Windows build running outside the checkout, two synchronized views over one
Workspace, one real edit through the shared `OperationPlan` path with a
byte-bound receipt, CLI/MCP/provider parity, and a reviewed product-quality
bar.

The report pipeline remains supported as one optional workflow module. It is
not the identity of the project.

---

## 2. Current status

| Field | Value |
|---|---|
| Current phase | **Phase 0 — Product truth and direction** |
| Phase 0 state | In progress |
| Phases 1–6 | Not started |
| Baseline commit (`main`) | `a635289` |
| Direction branch | `docs/product-direction-desktop` (PR #150, draft, docs-only, not merged) |
| Blocking user decisions | 2 open — see §6 (D2, D3) |

### Phase 0 deliverable checklist

| Deliverable | State |
|---|---|
| Repository and release truth audit | Done — recorded in §5 |
| Agent-native identity in `docs/product-direction.md` | Done |
| Dual-view UX stated as product definition | Done — `product-direction.md` §4 |
| Surface separation and authority model | Done — `product-direction.md` §5 |
| Living program document | Done — this file |
| Corrected docs index | Done — `docs/README.md` |
| `docs/desktop-architecture.md` | Not started |
| `docs/threat-model.md` | Not started |
| `docs/desktop-acceptance.md` | Not started |
| `docs/runtime-protocol-v0.md` | Not started (Phase 1 input; may be drafted in Phase 0) |

### Phase 0 exit gate

> An unfamiliar technical contributor can read `docs/product-direction.md` and
> this document and understand the product, the authority model, the initial
> developer-preview flow, and the current limitations — **without** reading
> report-pipeline history first.

Not met yet: the threat model, desktop architecture, and acceptance documents
are outstanding. The exit is judged by a fresh-context reviewer who did not
write these documents, not by their authors.

---

## 3. Phase ladder

One ladder, Phase 0–6, normative in Goal §18. The older M0–M5 milestone
numbering in `docs/product-direction.md` is **superseded**; the translation
table lives in `product-direction.md` §8.

Entry criteria below are this program's operational reading; exit criteria are
the specification's and are not negotiable here. A phase does not exit with
fake implementations, placeholder-only APIs, or TODOs standing in for its
acceptance criteria.

### Phase 0 — Product truth and direction

**Entry:** repository, tests, releases, and PR state inspected rather than
assumed.

**Deliver:** repository/release truth audit; agent-native identity; dual-view
UX; surface separation; this program document; desktop architecture; threat
model; acceptance document; corrected docs index. PR #150 stays docs-only.

**Exit:** an unfamiliar contributor understands product, authority, initial
flow, and current limits without reading report-pipeline history first.

### Phase 1 — Runtime Protocol v0 and headless vertical slice

**Entry:** Phase 0 exited; the surface boundary and authority split are agreed;
one existing engine edit has been chosen as the slice target and its tests
identified.

**Deliver:** schemas; JSONL protocol; strict initialization; host and agent
entrypoints; contained sessions; immutable import; real document summary and
graph; one existing engine edit; plan validation; host approval; a separate
candidate; source proof; applicable checks; honest unavailable checks; receipt;
export; focused tests.

**Exit:** the edit is reproducible headlessly.

**Non-negotiable inside this phase:** adapt existing tested operations. Do not
create a second editing engine to make Runtime look clean.

### Phase 2 — CLI and MCP parity

**Entry:** Phase 1 exited; Runtime Protocol v0 is stable enough that a second
client will not force a redesign.

**Deliver:** CLI with JSON output and stable exit semantics; MCP STDIO adapter;
allowed-root / attached-session policy; inspect-and-propose default; setup
examples; parity tests.

**Exit:** Runtime, CLI, and MCP produce compatible plans and verification for
the same task.

### Phase 3 — Read-only premium Desktop foundation

**Entry:** Phase 1 exited (Phase 2 may run in parallel); the shell/sidecar spike
has been run and its measurement recorded.

**Deliver:** measured shell spike; `desktop/`; packaged sidecar; lifecycle;
native import; recovery; shared store; both views; synchronized state; real
preview or an honest unavailable state; real structure; proof display;
deterministic mock agent; design system; keyboard and DPI checks; screenshots;
visual review.

**Exit:** a clean user can open, understand, switch views, and reopen without a
terminal.

### Phase 4 — Verified Desktop editing

**Entry:** Phase 3 exited; the Phase 1 edit is exposed through Runtime and
reachable from Desktop.

**Deliver:** bounded direct editing; plan review; before/after; invariants;
approval; candidate generation; verification; comparison; export;
receipt/evidence viewer; crash and cancel recovery.

**Exit:** one public supported task completes from packaged Desktop without XML
work or checkout access.

### Phase 5 — Agent-native operation

**Entry:** Phase 4 exited; Phase 2 exited (the external-agent flow needs MCP).

**Deliver:** contextual panel; full timeline; location navigation; mock provider
flow; external MCP flow; custom-router adapter with fake-server tests; one
official embedded provider path; secure settings; capability negotiation;
streaming; prompt-injection cases; disclosure of what may leave the device.

**Exit:** manual, embedded-agent, and external-agent work share the same plan
and verification path without authority collapse.

**Known allowed gap:** a live provider authentication smoke may be recorded as
`not run` when credentials are unavailable. Implementation, contract tests,
connection UI, failure handling, and credential boundaries must still be
complete, and a live login result is never fabricated.

### Phase 6 — Developer Preview hardening

**Entry:** Phase 5 exited.

**Deliver:** Windows preview package; clean-machine evidence; process cleanup;
installer/update/uninstall planning; dependencies and SBOM; performance; DPI;
accessibility; privacy; a clean-room task; independent architecture, security,
and visual reviews; coherent docs.

**Exit:** the Developer Preview completion target holds. **Nothing is published
publicly without explicit user authorization.**

### Acceptance tasks

The phase exits are validated against the six acceptance tasks in Goal §19:
A read-only inspection, B fixed-form edit, C embedded/mock agent proposal,
D external-agent proposal, E hostile document, F crash and cancellation. They
are specified in Goal §19 and will be made executable in
`docs/desktop-acceptance.md`.

---

## 4. PR dependency graph

Reviewable slices, not one giant PR and not dozens of trivial ones. Stacked
draft PRs are allowed with explicit dependencies. Direction documents and
implementation never mix in the same PR.

```
PR #150  docs-only: product direction + program document      [Phase 0, open, draft]
   |
   +--> PR: docs/desktop-architecture.md + docs/threat-model.md
   |         + docs/desktop-acceptance.md                     [Phase 0]
   |
   +--> PR: Runtime Protocol v0 schemas + JSONL transport     [Phase 1]
              |
              +--> PR: Runtime host/agent entrypoints,
              |         sessions, immutable import            [Phase 1]
              |         |
              |         +--> PR: one engine edit as a typed
              |                   operation -> plan -> approval
              |                   -> candidate -> receipt      [Phase 1, exit slice]
              |                      |
              |                      +--> PR: CLI over Runtime         [Phase 2]
              |                      |         |
              |                      |         +--> PR: MCP STDIO adapter
              |                      |                   + parity tests [Phase 2, exit slice]
              |                      |
              |                      +--> PR: shell/sidecar spike record [Phase 3]
              |                                |
              |                                +--> PR: desktop/ shell +
              |                                |         packaged sidecar   [Phase 3]
              |                                |         |
              |                                |         +--> PR: dual views +
              |                                |                   shared store   [Phase 3, exit slice]
              |                                |                      |
              |                                |                      +--> PR: bounded editing
              |                                |                      |         + approval UI  [Phase 4]
              |                                |                      |         |
              |                                |                      |         +--> PR: export +
              |                                |                      |                   receipt viewer
              |                                |                      |                   + recovery   [Phase 4, exit slice]
              |                                |                      |                      |
              |                                |                      |                      +--> PR: agent panel
              |                                |                      |                      |         + timeline   [Phase 5]
              |                                |                      |                      |
              |                                |                      |                      +--> PR: packaging,
              |                                |                      |                                SBOM, hardening [Phase 6]
              |                                |                      |
              |                                |                      +--> PR: mock provider +
              |                                |                                Agent Host boundary  [Phase 5]
              |                                |                                   |
              |                                |                                   +--> PR: custom router
              |                                |                                   |         (fake-server tests) [Phase 5]
              |                                |                                   +--> PR: one official
              |                                |                                             provider path       [Phase 5]
              |                                |
              |                                +--> (Phase 3 needs Phase 1 only; Phase 2 may run in parallel)
              |
              +--> PR: protocol conformance test suite                 [Phase 1]
```

| Slice | Depends on | Phase | Notes |
|---|---|---|---|
| PR #150 — direction + program docs | — | 0 | Docs-only. Do not merge without user authorization; do not add code. |
| Architecture / threat model / acceptance docs | #150 | 0 | Closes the remaining Phase 0 exit criteria. |
| Runtime Protocol v0 schemas + transport | Phase 0 exit | 1 | One authoritative schema source; TypeScript bindings generated or mechanically validated, never handwritten twice. |
| Runtime sessions + immutable import | schemas | 1 | Containment, path controls, recovery manifest. |
| First engine edit end-to-end | sessions | 1 | Phase 1 exit slice. Adapts an existing tested operation. |
| CLI over Runtime | Phase 1 exit | 2 | No separate editing semantics. |
| MCP STDIO adapter + parity tests | CLI | 2 | Phase 2 exit slice. Agent-safe subset only. |
| Shell/sidecar spike record | Phase 1 exit | 3 | A measurement, not a preference. |
| `desktop/` shell + packaged sidecar | spike | 3 | Desktop owns the sidecar lifecycle. |
| Dual views + shared store | shell | 3 | Phase 3 exit slice. |
| Bounded editing + approval UI | dual views | 4 | Same `OperationPlan` path as the agent. |
| Export + receipt viewer + recovery | editing | 4 | Phase 4 exit slice. |
| Agent panel + timeline | dual views, Phase 2 exit | 5 | |
| Mock provider + Agent Host boundary | agent panel | 5 | The only network-capable boundary. |
| Custom router adapter | Agent Host | 5 | Fake-server tests. |
| One official provider path | Agent Host | 5 | Live smoke may be `not run`. |
| Packaging, SBOM, hardening | Phase 5 exit | 6 | No public publication without user authorization. |

Every PR body states: user outcome, rationale, architecture boundary, changed
subsystems, security implications, tests and results, missing evidence,
limitations, dependencies, and the next slice.

---

## 5. Repository truth audit

Observed facts. All of the following were **verified by the orchestrator on
2026-09-01** against the real repository and GitHub state. Rows marked
"re-confirmed locally" were additionally checked in the Track A worktree on the
same date. This section records what is true; it does not authorize changing
any of it.

| # | Observation | How to re-check |
|---|---|---|
| O1 | `main` is at commit `a635289`. | `git log --oneline -1 main` — re-confirmed locally. |
| O2 | Test suite: **3895 passed, 0 failed** with distribution modules enabled. | Run the suite with modules enabled. Not re-run by Track A. |
| O3 | Tracked-content privacy scan: **HARD=0, WARN=42**. | `python pipeline/scripts/privacy_scan.py <tracked root>`. Not re-run repo-wide by Track A; `docs` alone is HARD=0 WARN=0. |
| O4 | Git tag `v0.17.0` exists and `pyproject.toml` declares `version = "0.17.0"`. | `git tag -l v0.17.0`; `pyproject.toml` — both re-confirmed locally. |
| O5 | The latest **published GitHub Release is v0.16.0**. No v0.17.0 Release has been published, despite O4 and the presence of `docs/release-v0.17.0.md`. | GitHub Releases page. Not independently checkable offline. |
| O6 | The **GitHub repository description** still reads "Verifiable report pipeline for HWPX (한글) documents…" — the pre-agent-native identity. | GitHub repository settings. Not independently checkable offline. |
| O7 | `docs/support-matrix.md` is **generated** by `scripts/support_matrix.py --write` from `pipeline/references/support-claims.yaml` and is the capability authority. It refuses a `supported` row whose evidence pointers do not resolve. | Header of `docs/support-matrix.md`; the generator script. Re-confirmed locally. |

Two further identity mismatches follow from the same audit and are recorded for
completeness:

- `pyproject.toml` `description` reads "Agent-neutral, resumable report
  workflow" — package metadata still describes the report pipeline.
- The root `README.md` already describes a general HWP/HWPX document engine, so
  README, package metadata, and the repository description currently give three
  different answers to "what is this project?"

### What the audit means for this program

O5 and O6 are the concrete form of the identity problem this program exists to
fix: the repository ships a general document engine, is tagged v0.17.0, and
presents itself publicly as a report pipeline at v0.16.0.

O2 and O3 are the reason the program can move: the engineering base is green
and the privacy gate is clean, so the work ahead is product and architecture
work, not remediation. O3's WARN=42 is a warning count, not a failure — the
gate's HARD count is the pass condition.

O7 is the reason no document in this program may restate capability in prose. A
capability claim belongs in `support-claims.yaml`, where it is checked, or
nowhere.

---

## 6. Phase 0 decisions

Decisions are recorded here, not applied silently. Anything outward-facing
waits for the user.

| ID | Decision | Status |
|---|---|---|
| D1 | Rename the "Application Service" surface to **Runtime**, matching the Goal specification. Older documents and branches referring to "Application Service" mean Runtime. | **Accepted.** Reversible, internal, recorded in `product-direction.md` §5.2. |
| D2 | Reconcile the release mismatch (O4/O5): either publish a v0.17.0 GitHub Release from the existing tag and `docs/release-v0.17.0.md`, or explicitly declare v0.17.0 a tag-only internal release and say so in the release record. | **Open — needs the user.** Publishing a GitHub Release is forbidden without explicit user authorization (Goal §21). The program does not choose for the user. |
| D3 | Update the GitHub repository description (O6) to the agent-native identity. | **Open — needs the user. Outward-facing.** This is public-facing text about the project's identity; it is not changed on an agent's judgment. Proposed replacement text should be reviewed by the user before anyone edits the setting. |
| D4 | Update `pyproject.toml` `description` to match the agent-native identity. | **Open — deferred.** Package metadata is shipped content; group it with D2/D3 rather than drifting a third identity into the tree. |
| D5 | One roadmap ladder. Phase 0–6 is canonical; M0–M5 is superseded and retained only as a translation table. | **Accepted.** Recorded in `product-direction.md` §8. |
| D6 | `docs/support-matrix.md` remains the single capability authority. Direction and program documents point at it and never restate capability. | **Accepted.** |

None of D2, D3, or D4 should be executed as a side effect of a documentation
PR. They are listed so that the mismatch is on the record and visible, which is
the Phase 0 obligation — recording observed truth before changing it.

---

## 7. Standing constraints

Carried from the Goal specification so a reader of this document alone does not
miss them.

**Forbidden without explicit user authorization:** merging to `main`;
force-pushing `main`; deleting protected or release branches; changing branch
protection; creating or moving public release tags; publishing GitHub Releases;
uploading public installers; publishing packages; signing or distributing an
updater; committing real credentials.

**Evidence discipline:** for every PR, report exact commands and classify each
result as passed, failed, skipped, not run, or unavailable. Old logs are not
current evidence. A prose claim is not evidence. Do not weaken a valid existing
test to make new architecture pass.

**Security work** uses synthetic or public documents only.

**Verification:** implementation owners run focused tests. At the end of a major
phase, a fresh-context reviewer who did not write the implementation inspects
code, tests, history, running artifacts, and the phase's exit criteria — and
may not reinterpret missing evidence as success.

---

## 8. Open risks

| Risk | Why it matters | Current handling |
|---|---|---|
| Identity drift between README, package metadata, repository description, and released version | A contributor or user gets a different answer depending on where they look; the agent-native direction stays invisible publicly | Recorded as O5/O6 and D2/D3/D4; blocked on user decisions |
| Runtime becoming a second editing engine | Duplicated document logic breaks the one-path invariant and doubles the verification surface | Phase 1 explicitly requires adapting existing tested operations |
| Desktop shell chosen by preference rather than measurement | An unmeasured shell choice is expensive to reverse after `desktop/` exists | Phase 3 entry requires a recorded spike measurement |
| Phase 0 exit judged by its own authors | The exit criterion is comprehension by an unfamiliar reader, which authors cannot self-assess | Exit requires a fresh-context reviewer |
| Provider credentials unavailable | Phase 5 could stall on something no amount of engineering resolves | Deterministic mock and fake-server paths carry the phase; the live smoke is recorded as `not run`, never fabricated |
| Documents accumulating capability claims prose | The support matrix stops being the authority and false capability leaks into docs | D6; capability claims live in `support-claims.yaml` or nowhere |
