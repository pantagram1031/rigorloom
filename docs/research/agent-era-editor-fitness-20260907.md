# Agent-Era Editor Fitness Audit — 2026-09-07

**Purpose:** Architecture + readiness audit for Hayul's beta-readiness question.
No product code changed. Read-only investigation of the PR tip stack (#340 →
#339 → #336/#333/#330) plus `main` docs.

**Auditor checkout base:** `main` at `a635289dd054341b882c8e8b3c262a7f538efa5f`
(last merged PR #149, 2026-08-13).
**Product tip examined:** PR #340 `claude/same-run-offset-range-text`
(`02d8ffeb9f36`) — the highest merged PR in the product desktop stack.
**Rematch freeze:** ON. This report does not recommend rematching research onto
product.

---

## 1. What the system actually is today

Three distinct layers share the repository, serving different purposes.

```
┌──────────────────────────────────────────────────────────┐
│  LAYER 1: Report Pipeline  (main — the committed product)│
│                                                          │
│  pipeline_ctl.py  ──►  stages.yaml  ──►  gates          │
│  doc_backend.py dispatch: bundle | docx | hwpx | hwp    │
│  engine/scripts/:  form_inspect, preedit, xml_backend,  │
│                    fill_report, com_backend, own_render  │
│  modules/:  gongmun | grant | hr | minwon | report|style│
│  studio/main.py:  read-only local viewer (FastAPI)       │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  LAYER 2: Desktop Shell  (unmerged — draft PR stack)     │
│                                                          │
│  Tauri 2 (src-tauri/) ◄──JSONL──► rigorloomd.py sidecar│
│  React/TS (src/):                                        │
│    store.ts  ──  actions.ts  ──  revision.ts             │
│    DocumentView | AgentView  ──  PageOverlay.tsx         │
│    SeatEditor (one <input> shared by tree + page)        │
│  agenthost/:  host.py ──► ah_compile gate ──► runtime   │
│  Windows only: COM render (Hancom), credstore, PyInstall │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  LAYER 3: Research Renderer  (unmerged — frozen per plan)│
│                                                          │
│  engine/scripts/own_render.py  (rigorloom-own renderer)  │
│  ~300 commits of PR research on claude/engine-e2-*       │
│  grade: own-uncertified  SSIM 0.746  text_iou 0.585      │
│  Rematch freeze ON: do not stack further.                │
└──────────────────────────────────────────────────────────┘
```

**Relationship between layers.** The pipeline (Layer 1) is the authoritative
public product: a stage-gated, provider-neutral document-automation workflow
that turns a research brief into a typeset HWPX/PDF report. The desktop shell
(Layer 2) is an agent-native Tauri app that treats the same `engine/` scripts
as backend workers, adds an approval-gated edit loop, and exposes a CLI agent
host. It has never been merged to `main`. The research renderer (Layer 3) is
lab instrumentation measuring how closely `own_render.py` can reproduce
Hancom's layout without COM; its scores are advisory and its PRs are parked by
the freeze.

**The "editor" in question** is Layer 2, not Layer 1. The pipeline assembles
documents into HWP forms; the desktop lets a human (or an agent, with human
approval) edit individual cells and runs in a live HWPX session.

---

## 2. Document-edit flow end-to-end (PR #340 tip)

The following traces one inline-cell edit from first click to saved receipt.
File references are `desktop/src/` unless marked `src-tauri/src/`.

### 2.1 Open

```
Ctrl+O / drop .hwpx on window
  └─► actions.ts:openPath()
        └─► runtime.ts:invoke("open_path", ...)   [Tauri command]
              └─► sidecar.rs:request(...)          [JSONL over stdio to rigorloomd.py]
                    └─► runtime sidecar: workspace/open
                          └─► engine/scripts/form_inspect.py  (Parser worker)
                    └─► store.ts:setState({ session: ... })
```

Store gets `session.sessionId`, `session.source`, `session.capabilities`.
**Unknown:** `rigorloomd.py` is a PyInstaller-frozen binary built by
`sidecar/build.ps1` on Windows; the live runtime scripts it wraps live in a
`runtime/` tree that is **not present** in this checkout. The protocol wire
contract is described in `docs/runtime-protocol-v0.md` (on branch) and
`docs/desktop-architecture.md`, but the actual serve-side implementation is
external.

### 2.2 Display

```
store.ts:centerMode = "text" | "page"
  "text":  DocumentView → TreeView (summary.sections, tables, paragraphs)
  "page":  actions.ts:renderCurrentPage()
             └─► runtime: document/render
                   └─► Renderer worker: own_render.py (offline) OR com_backend.py (Windows COM)
             └─► store.ts:{ render: RenderResult }
             └─► PageOverlay.tsx draws geometry seats over the raster
```

`document/pageGeometry` returns `GeometryResult` with seat rectangles from
Hancom's own stroked borders (`cell_borders` scan). PR #330 established that
73 seats are placed across ten corpus forms; 55 are on one form. 400 of 473
regions get no seat because underline-only forms have no box geometry.

### 2.3 Select / Edit

```
User clicks seat on PageOverlay
  └─► actions.ts:clickOverlaySeat(seat)
        └─► actions.ts:beginEdit(address)
              └─► revision.ts:prepareParagraphEdit(state, address)
                    - captures EditLease (sessionId, runId, documentSha256,
                      geometry ref, render ref, atPara)
                    - captures rangeText: the DISPLAYED run text
                    - captures rangeStart/rangeEnd (UTF-16 offsets)
                    - returns ParagraphEditEffect { kind:"caret", ... }
              └─► store.ts:setState({ inlineEdit: effect })
              └─► SeatEditor <input> mounts inside the seat rectangle
                    - value = fieldTextForRunEdit(rangeText, rangeStart, rangeEnd)
```

PR #340 fix: `rangeText` (the displayed string the offsets were measured
against) is now carried explicitly through `ParagraphEditEffect`. `before` (the
op's A→B baseline) may be an older revision's text when a `set_run` is already
queued. Offsets measured on the displayed text applied to `before` landed at a
stale position. Tests `desktop_same_run_range_text_harness.cjs` exercise five
cases (Latin, Hangul, surrogate pair); all five failed on the #339 tip and
pass on #340.

For inline span edits on `own_render` pages, `clickOverlaySpan()` →
`locateSpanInRuns()` in `run_map.ts` maps a geometric hit to a (run, UTF-16
offset) pair.

### 2.4 Queue / set_run

```
User types → commits
  └─► actions.ts:commitEdit(opId)
        └─► revision.ts:runTextAfterEdit(edit, trimmed)
              - splices into rangeText (not before, not queuedRun.text)
        └─► setQueue([...ops, next])
              └─► runtime: plan/setQueue
                    └─► runtime: plan/propose → plan/validate
                          └─► store.ts:{ draft: OperationPlan, planValidation }
              └─► ReviewQueue UI shows op with origin tag (user | agent)
```

`plan/validate` is a runtime gate: the plan is structurally checked before it
enters the queue. Every op carries `origin` (user-typed vs agent-proposed) —
a distinction the product treats as non-negotiable for the approving human.

### 2.5 Save / Export

```
User clicks Export
  └─► actions.ts:exportApplied()
        └─► saveFileDialog (Tauri plugin-dialog)
        └─► runtime: workspace/export  (AGENT-blocked — host only)
              └─► src-tauri/src/digest.rs: SHA-256 of candidate
              └─► dest-preserving backup pair (PR #336 fix)
                    - verify landed pair before dropping dest backups
              └─► Receipt: { sourceSha256, candidateSha256, planHash, approvalAt }
```

PR #336 added the dest-preserving export: original bytes are never overwritten
until the backup pair is verified. The Rust harness for the card-1 matrix
(`tests/desktop_export_safety_harness.rs`) is present but fails CI on Windows
due to a missing `windows_sys` crate dependency.

### 2.6 Reopen

```
Smoke (scripts/smoke.ps1) launches built .exe a second time
  └─► Tauri: persisted session ID found in prefs
  └─► runtime: workspace/reopen (sessionId)
  └─► smoke.ts:openReceipt() verifies receipt panel populates
  └─► UI zoom level and recents also persist
```

`smoke.ts` proves close/reopen is genuine: two separate processes, second
finds first's session. IME composition and the native file dialog are **not
exercised** (the smoke is in-app, not via WebDriver).

### 2.7 Flag: unknowns

| Unknown | Impact |
| --- | --- |
| `runtime/scripts/` tree not in repo | Cannot verify serve-side protocol conformance from this checkout |
| `plan/apply` not wired | Agent can propose but never execute without human approval click |
| COM renderer path (`com_backend.py`) | Windows-only; Linux CI runs `own_render` path only |
| IME composition | Not tested in any harness |
| `plan/apply` + approval round-trip | Smoke exercises up to `requestApproval`; `resolveApprovalDecision` is present but not proven against a live runtime in CI |

---

## 3. Honest readiness assessment

**Status: pre-alpha on the desktop/editor; private-preview on the report
pipeline.**

### 3.1 What works — with evidence

| Claim | Evidence |
| --- | --- |
| Report pipeline produces HWPX/PDF from a brief | Stage map in `pipeline-master-v0.6.md`; `bundle`, `docx`, `hwpx` backends run on any OS; CI on `main` passes |
| Parsing + geometry: 73 seats on corpus | Measured, not claimed: `PageOverlay.tsx` header quote; PR #330 description |
| Inline cell edit → review queue → plan | `smoke.ts` scripted path; 5 cjs harness cases pass on #340 tip |
| Dest-preserving export pair | PR #336 fix + `test_desktop_export_safety.py` (module exists; Rust compile blocked in CI) |
| Draft-fence (card 2) | PR #339 `bumpPlanGeneration` + `currentPlanGeneration` guard; test `test_desktop_revision_coherence.py` |
| Run-scoped edit (card 3) | PR #340 `rangeText` fix; harness passes 5/5 locally |
| Agent host CLI: mock + router + anthropic | `agenthost/README.md`; tests against fake server; no live-provider test |
| Deterministic compile gate | `ah_compile.py` derives allowed set from `AGENT_METHODS`; `plan/apply` refused before runtime sees it |

### 3.2 What is claimed but unproven

| Claim | Gap |
| --- | --- |
| "The page is an editor now" | True for box-cell seats (73); false for underline-rule seats (400); false for multi-run paragraphs (`CaretRefusal = "multi_run"`) |
| Export safety matrix | Rust harness exists but fails CI (`windows_sys` crate missing in GitHub Actions) |
| Korean mixed E2E (card 4) | Card 4 harness prep PR #341 states "NOT RUN" in its own title |
| `own_render` grade improvement | `own-uncertified`; grade is advisory and not an install-candidate |
| Live anthropic provider | `--live-smoke` noted as owed; keyless path tested; no real API call in any test |

### 3.3 What is broken or absent

| Item | State |
| --- | --- |
| CI on PR #340 tip | 4 of 5 checks FAIL: `test_cleanroom_evals` (render-check family missing eval task), `test_runtime_render` (KeyError, runtime stubs missing), `test_own_render` (font env not set), Rust compile (missing `windows_sys`) |
| Card 5 (install hash) | Absent. No outside-checkout hash of EXE/sidecar/installer exists. Checkpoint 24 self-reports the sidecar line as unowned |
| `runtime/` scripts | Not in this checkout; the sidecar is a frozen Windows binary |
| HWP COM path | Windows + Hancom Office required; never tested in CI |
| `plan/apply` | Intentionally refused; a fully autonomous headless loop is impossible without human approval |
| `multi_run` paragraph edits | Still refused (`CaretRefusal = "multi_run"`); only single-run seat edits work |

---

## 4. Agent-era fitness

### 4.1 CLI surface

```sh
# Runtime (agent authority)
python runtime/scripts/cli.py --root $R open --path /abs/form.hwpx

# Agent host
python agenthost/scripts/host.py --root $R --provider mock
python agenthost/scripts/host.py --root $R --provider anthropic
python agenthost/scripts/host.py --root $R --provider router --config r.json
python agenthost/scripts/host.py --capabilities --provider mock  # keyless
```

The agent host is a real CLI today. The nine `AGENT_METHODS` an agent may call
are derived from `rt_core.AGENT_METHODS`; the MCP server uses the same tuple.
An external agent can inspect, propose, and validate without a GUI. It cannot
approve or apply.

### 4.2 MCP / skill hooks

`runtime/scripts/mcp_server.py` (referenced in `ah_compile.py`) exposes the
same nine methods as MCP tools. `ah_compile.ALLOWED_TOOLS` is computed — not a
hardcoded list — so adding a method to `AGENT_METHODS` automatically extends
both the MCP server and the agent host; removing one closes both. The compile
gate refuses `approval/resolve` and `plan/apply` by identity before the
runtime is asked.

The report pipeline side has a skill installer (`scripts/sync_local.py`):
`adapters/claude-code/SKILL.report-pipeline.md` is the router skill entry
point. A Claude Code instance can drive the full pipeline via that skill.

### 4.3 Deterministic gates

| Gate | Owner | Mechanism |
| --- | --- | --- |
| `layout` | Script | `pipeline_ctl.py check <WS> layout` → `layout_plan_check.py` |
| `sane` | Script | sim result vs declared gates in `gate_result.json` |
| `content_audit` | Script | content verifier exits 0 before assembly |
| `plan/validate` | Runtime | structural check before any op enters the queue |
| `approval/resolve` | Human only | not callable by agent authority |
| Compile gate | `ah_compile.py` | tool request → ALLOWED_TOOLS check before Runtime is asked |
| Receipt binding | Runtime + `digest.rs` | SHA-256 of candidate + plan hash + approval timestamp |

Forged `--script-exit` passes are a hard error since v0.7 wave
(`docs/pipeline-master-v0.6.md §11`). A pending script gate blocks resume in
all modes including `autonomous`/`night`.

### 4.4 PASS ownership and evidence

Scripts own PASS. This is explicit and enforced:

- Pipeline: `pipeline_ctl.py check` invokes the registered checker, records
  provenance (argv, exit code, stdout sha256, checked-at) to
  `.pipeline/gate_checks.jsonl`. A non-zero exit rejects the gate. No agent
  path skips this.
- Desktop: `plan/validate` + receipt hash-bind the outcome. The smoke
  asserts structural guards, not visual aesthetics.
- Evals: `evals/cleanroom.py` + `evals/score.py` run tasks against the
  corpus; the first published eval pack record is PR #125 (`79c3574`).

Visual/aesthetic review is ADVISORY. `autonomous-orchestration.md §2.5` states
this: a text-only model filling a visual-QA rubric is "not grounded in
anything it actually looked at." PASS from a script gate is never overridden by
an aesthetic opinion.

### 4.5 External agent driving edits without GUI

**Today:** Yes, with human-approval bottleneck.

```
agenthost/scripts/host.py  ──(agent authority)──►  runtime sidecar
  ah_provider (mock | router | anthropic)
    turn loop: inspect → propose → validate → (STOP: human must approve)
  event log: JSONL (--events FILE)
  --redact: deterministic id scrub
```

The mock provider demonstrates the full loop: `propose-one`, `propose-invalid`,
`propose-then-wait`, and `escalate` (which the compile gate refuses). An agent
submits a plan and the plan sits in the review queue until a human resolves it
in the shell UI.

**Gaps vs a "perfect agent-native Hangul editor":**

| Gap | Severity | Notes |
| --- | --- | --- |
| `plan/apply` requires human approval | Architectural (by design) | Intentional safety gate; a fully autonomous apply path does not exist |
| Windows-only sidecar | Critical for CI/Linux agents | `rigorloomd.py` is PyInstaller-frozen for Windows; no cross-platform runtime entry point |
| `multi_run` paragraph edits refused | Medium | Caret only covers single-run seats; a paragraph with two formatting runs is uneditable via the overlay |
| No streaming of partial results | Medium | `resumableThread: no`; host resends full history each turn |
| OS credential store unimplemented | Low | `credential_source_unsupported` returned; env-var reference works |
| IME composition not tested | Medium | Native IME is outside the in-app smoke scope; real Korean input path is unverified |
| No live-provider round-trip in CI | Medium | `--live-smoke` owed; only fake server tested |
| Undo/redo not proven for agent-proposed ops | Low | `proposeUndoOf` exists in actions.ts; not in agent-authority smoke |

---

## 5. Visual / UX evaluation path vs script PASS

The PageOverlay rule is stated explicitly in `desktop/src/components/PageOverlay.tsx`:

> "The layout is the renderer's, never ours. Every rectangle here is a
> `[x0, y0, x1, y1]` fraction that came out of `document/pageGeometry`…
> A rectangle in the wrong place is worse than no rectangle."

**Principle alignment:**

| Concern | Who owns it | How enforced |
| --- | --- | --- |
| Seat placement correctness | Runtime (`document/pageGeometry`) | Derived from Hancom's stroked borders; not nudged |
| Ambiguity disclosure | UI | `address: null` → chooser, not auto-resolution |
| Edit route uniqueness | Architecture | One `SeatEditor` `<input>`, mounted by both tree and overlay |
| Visual QA verdict | ADVISORY | `own-uncertified` grade; not a PASS criterion |
| Aesthetic palette | ADVISORY | `autonomous-orchestration.md §4`: figure style pack enforced; "never let the model's default aesthetic through" |
| Script gate result | HARD PASS | Cannot be overridden by visual review |

An independent visual review catching a misplaced seat is evidence to **change
the measurement inputs** and rerun the gate — not to override the gate. The
`render-check-01` feature-by-feature comparison document
(`docs/research/render-check-01.md`) operationalizes this: per-feature IoU with
a 1-pixel dilation tolerance, page agreement flagged separately from crop IoU.

The holdout scoreboard (`docs/research/holdout-scoreboard-02.md`) shows that
`ssim_inked_min` is now positive (no page where ink is anti-correlated with
Hancom's), but the grade stays `own-uncertified`. A visual reviewer saying
"this looks fine" cannot promote that grade; only a ratified threshold and a
certified render path can.

---

## 6. Recommendations — W0–W1 (next 2 weeks, max 8 bullets)

**Rematch freeze is ON.** Do not merge or stack renderer research onto the
product desktop SHA.

1. **Fix the two CI failures that block all other cards.** Register the
   `render-check` corpus family in `evals/tasks/` so `test_cleanroom_evals`
   passes. Add `windows_sys` as a dev dependency (or feature-gate the Rust
   harness) so `test_desktop_export_safety.py` compiles on GitHub Actions
   Windows. Both are mechanical fixes with no architecture impact.

2. **Merge card 2 + card 3 onto the product SHA after CI is green.** PR #339
   (draft fence / `bumpPlanGeneration`) and PR #340 (`rangeText` splice fix)
   address the two diagnosed correctness bugs. Do not wait for another
   independent review; the bugs are instrumentally proved by the existing
   harnesses.

3. **Ship run-scoped `set_run` with full source-map (revision / run / UTF-16)
   — complete card 3.** The current tip still refuses `multi_run` paragraphs.
   The source-map contract in `docs/` (PR #332) is parked; implement it
   directly from the frozen desktop SHA using `run_map.ts` as the foundation.
   Do not implement `LayoutSnapshot` first.

4. **Write the export-safety install-candidate matrix for card 1.** Cases:
   mid-write crash, disk-full refuse, receipt hash mismatch, original path
   bytes unchanged, copied destination hashed. This is `hwpx_write.py` +
   `desktop/src-tauri/export_candidate` + `digest.rs`. The Rust harness shell
   exists; make it compile and run on CI.

5. **Hash a real Windows install outside the checkout — card 5.** Record
   source / EXE / sidecar / installer SHA-256 from a machine that is not the
   agent worktree. Checkpoint 24 self-reports the sidecar line as unowned;
   this is the minimum install-candidate evidence gate for all five cards.

6. **Run one Korean mixed E2E on that hashed install — card 4.** Mixed
   formatting (bold/plain span in one paragraph), a long paragraph, a table;
   edit → undo/redo → AI-review proposal → save → reopen. Record result in
   the `qa/` harness verifier. Do not accept cache SSIM or computed IoU as
   a substitute.

7. **Close or abandon PR #326+ (rematch conveyor) and #328+ (renderer
   research).** The conveyor produces 53,868 lines of `desktop/`-free diffs
   and zero install-candidate evidence. Closing these PRs reduces the 179-open-
   draft-PR sprawl and makes the real product line legible. Park the renderer
   research at SHA `eda8f60a7f94` (#323) as a frozen snapshot.

8. **Wire `approval/resolve` into the QA harness so card 4 can run
   unattended with a mock.** The `escalate` scenario already exercises the
   refusal path; a permissive mock for QA purposes (not shipped) would let
   the E2E loop run without a human click in an automated evidence run.
   Label such results as `mock_approved`, never `human_approved`.

---

## Appendix: Evidence sources

| Claim | Source |
| --- | --- |
| 179 open draft PRs | `gh pr list --state open` at time of audit |
| Last merge: #149 `a635289dd054` 2026-08-13 | `git log --oneline -1 main` |
| Desktop `src` frozen at `bf80c73c3383` | `git log origin/claude/desktop-on-renderer-323 -1 -- desktop/src` |
| 73 seats, 10 corpus forms | `PageOverlay.tsx` header comment; PR #330 description |
| CI failures on PR #340 | `gh run view 34047146124` — `test_cleanroom_evals`, `test_runtime_render`, `test_own_render`, Rust compile |
| `render-smoke` green | Same CI run; only check that passes |
| rangeText splice fix | PR #340 diff; harness `desktop_same_run_range_text_harness.cjs` 5/5 pass statement |
| Holdout SSIM 0.7457, text_iou 0.585 | `docs/research/holdout-scoreboard-02.md` (on PR #340 tip) |
| `plan/apply` refused by compile gate | `agenthost/scripts/ah_compile.py`; `FORBIDDEN_TOOLS` assertion |
| Card 5 absent | `docs/research/claude-research-vs-completion-cards-20260906.md` §4 verdict table |
| v0.7 hardening: forged `--script-exit` is hard error | `docs/pipeline-master-v0.6.md §11` |
| No runtime scripts in checkout | `docs/desktop-architecture.md §1.2` GAP note |
