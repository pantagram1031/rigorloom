# Studio Web Editor — Phase 1 architecture spike

Status: decision + vertical-slice PoC, 2026-07-19. This is not a production
editor and does not change the existing `studio/main.py` dashboard.

## Decision

Choose **(a) a structured editor with server-owned HWPX as the source of
truth**. The page preview remains a companion view and can later supply
click-to-locate hints, but it is not the editing representation.

The browser receives a typed projection of the document—paragraph, table,
figure, equation, and later field blocks—with stable ids, editability flags,
property references, and hazards. It sends typed operations with preconditions.
The server applies an operation through the document adapter, validates the
archive, appends an ordered operation record, and renders the resulting
revision. Unsupported structures fail closed.

This decision is narrower than “make every HWPX node editable.” In v1, a block
is editable only when the engine can prove that a bounded operation preserves
the rest of the file. Equations are opaque protected blocks. Mixed-style runs
remain protected until the engine has a span-level operation that preserves
their character properties.

### Comparison

| Design | Round-trip fidelity risk | Implementation cost | Assistant edit fit | Evidence and consequence |
|---|---|---|---|---|
| **(a) Structured blocks, HWPX source of truth** | **Low for explicitly supported operations; fail-closed elsewhere.** Paragraph and character property references stay in the HWPX. Equations and objects can remain opaque. | Medium-to-high: build a typed projection and one verified operation per structure. | **Best.** Stable block ids, expected hashes, and typed operations give the assistant a small reviewable diff. | The PoC changes one `hp:t` payload while 10 other ZIP members remain byte-identical. The current generic XML assembly adapter uses `ElementTree.tostring` for a dirty section, so interactive editing needs a narrower byte-local operation rather than a generic DOM save. |
| (b) Editable HTML round-trip | **High.** HTML has no native equivalent for HWPX `charPrIDRef`/`paraPrIDRef`, HwpEqn controls, field/control order, table cell spans, or Hancom layout records. Browser DOM normalization adds another lossy transform. | Highest: two converters, a reconciliation layer, property mapping, and a large fidelity corpus. | Superficially natural, but an HTML diff can be easy for an assistant to produce and impossible to map back without style/control drift. | The equation fixture contains text, a self-closing cursor `hp:t`, an equation control, and a following styled run. A first parser iteration incorrectly spanned that cursor; this was caught in the browser proof. A full HTML round-trip multiplies that class of ambiguity. |
| (c) Preview plus patch dialogs | Lowest write risk because all writes can be narrow server operations. | Low for dialogs, but reliable PDF-coordinate-to-HWPX block mapping is a separate medium/high-cost problem. | Adequate for isolated replacements; weak for outline reasoning, multi-block proposals, and table-aware edits. | It is a useful v1 interaction shell and fallback for protected blocks, but not a sufficient document model. The PoC uses a preview beside structured paragraphs without making pixels the source of truth. |

### Why the PoC has its own adapter

`pipeline/scripts/doc_backend.py` is a Stage-5 **assembly dispatcher**. Its HWPX
tier invokes the external `hwp-master` `fill_report.py --engine xml`; it has no
paragraph-operation API. The external generic XML backend reparses a dirty
section and serializes the entire section. That is appropriate for assembly,
but it cannot prove that an interactive text edit changed only one existing
run.

The spike therefore adds `studio/editor/doc_backend.py`, a prototype document
operation adapter, under the permitted isolated directory. FastAPI calls that
adapter rather than editing XML itself. The operation:

1. resolves a paragraph id against `Contents/section*.xml`;
2. requires exactly one non-equation, non-object text payload;
3. checks the expected old text;
4. XML-escapes and replaces only that payload byte range;
5. reparses the edited section;
6. rewrites the archive while retaining every other member payload;
7. reopens the result and rejects it unless the member set is identical and
   the target section equals the original bytes plus exactly the expected text
   replacement.

If this direction proceeds, that operation belongs in `hwp-master` as a public
`replace_text_run`/`replace_paragraph_text` contract. Studio should consume it
through the document-adapter interface. The spike does not claim that the
current Stage-5 dispatcher already supports interactive edits.

## Preview latency

### Environment and commands

All latency figures in this section were measured on the same environment:

- Windows host, Python 3.11.9;
- PyMuPDF 1.27.2.3;
- WSL renderer selected by `pipeline/scripts/render_probe.py`;
- LibreOffice 24.2.7.2 420(Build:2), H2Orestart detected;
- one-page, 23,164-byte sanitized HWPX;
- renderer command: the repo-probed `wsl -e bash -lc "exec soffice --headless
  ... --convert-to pdf:writer_pdf_Export ..."` argv, followed by PyMuPDF at
  1.5x for page 1.

Server benchmark command:

```powershell
python -m studio.editor.benchmark --iterations 5 --warmup 1 `
  --out studio/editor/results/preview-latency-2026-07-19.json
```

Raw environment, command, hashes, and per-run timings are in
[`studio/editor/results/preview-latency-2026-07-19.json`](../../studio/editor/results/preview-latency-2026-07-19.json).

Browser commands:

```powershell
python -m studio.editor.app --port 8010 --data-root scratch/studio-editor-runtime
npx --package @playwright/cli playwright-cli -s=studio-spike open http://127.0.0.1:8010
npx --package @playwright/cli playwright-cli -s=studio-spike snapshot
npx --package @playwright/cli playwright-cli -s=studio-spike fill <textarea-ref> "<new text>"
npx --package @playwright/cli playwright-cli -s=studio-spike click <apply-button-ref>
```

The exact browser refs, inputs, environment, and observed UI timings are in
[`studio/editor/results/browser-cycle-2026-07-19.json`](../../studio/editor/results/browser-cycle-2026-07-19.json).

### Results

The hot back-to-back benchmark produced:

| Phase | Median | Mean | Maximum / nearest-rank p95 |
|---|---:|---:|---:|
| Byte-local edit + fidelity + log | 33.851 ms | 33.447 ms | 36.739 ms |
| WSL LibreOffice conversion | 1,963.767 ms | 1,989.642 ms | 2,502.414 ms |
| PyMuPDF raster | 42.487 ms | 41.287 ms | 45.119 ms |
| Full server cycle | **2,036.572 ms** | 2,068.059 ms | **2,585.504 ms** |

All 5 measured hot cycles were below 3 seconds. The preceding warm-up cycle
was 24,770.378 ms. By the mean values, conversion consumed about 96.2% of the
cycle; the edit/fidelity step consumed about 1.6%, rasterization about 2.0%, and
the remaining process/accounting overhead about 0.2%.

The real Playwright flow, with normal time between page load and edits, was not
hot: the initial preview took 32,176.0 ms conversion plus 396.3 ms raster; the
two browser edit-to-refreshed-image cycles took 40,869.0 ms and 37,015.5 ms.
Their conversion phases alone took 40,703.6 ms and 36,854.8 ms; rasterization
took 54.9 ms and 61.5 ms. The operation log still recorded a successful
target-only fidelity check for both revisions.

### Is less than 3 seconds realistic?

**Not as a current user-facing per-edit guarantee.** It is realistic for a
small one-page document only in a hot, back-to-back burst: 5/5 hot runs passed.
At human interaction cadence, the current spawn-per-edit WSL/LibreOffice path
took 37–41 seconds in the browser proof. This spike did not isolate how much of
the cold variance belongs to WSL startup, LibreOffice startup/profile loading,
or the H2Orestart import filter; all of it is inside the measured conversion
phase. The conclusion does not depend on that split because the document edit
and PyMuPDF work are already two orders of magnitude smaller.

For v1, acknowledge the operation immediately after the bounded HWPX write,
mark the preview stale, debounce rendering to save/idle, and render
asynchronously. A persistent renderer worker or native Windows renderer can be
evaluated separately. Proposed SLOs are `<100 ms` for accepted plain-text
operation acknowledgement and best-effort `<3 s` for a hot preview, never a
hard preview promise until idle/cold p95 is measured.

Equation-bearing HWPX remains a separate renderer hazard. With the same
environment, sending the sanitized equation fixture through the repo-selected
soffice command returned exit 1 with `Unspecified Application Error`. The PoC
therefore inspects and locks that fixture but does not label LibreOffice output
as a valid equation preview.

## Document session model

One server process owns one `DocumentSession`. It serializes operations under a
lock; no CRDT, OT, or distributed synchronization is needed.

```json
{
  "sequence": 17,
  "op_id": "uuid",
  "kind": "edit",
  "actor": {"kind": "user", "id": "browser"},
  "base_revision": 8,
  "result_revision": 9,
  "paragraph_id": "s0-p5",
  "precondition": {
    "text_payload_sha256": "...",
    "document_revision": 8
  },
  "before_text": "old",
  "after_text": "new",
  "fidelity": {
    "ok": true,
    "changed_members": ["Contents/section0.xml"],
    "limited_to_text_payload": true
  },
  "render_receipt": {"revision": 9, "status": "ready|pending|failed"}
}
```

- The initial source is copied to immutable revision 0. Each accepted operation
  creates a new HWPX revision and appends one JSONL record.
- The client must supply `base_revision == current_revision` and the target
  payload hash/expected text. A mismatch returns a conflict; the server never
  merges silently.
- Only one operation is committed at a time. A pending assistant proposal does
  not reserve a revision.
- Undo is a **new inverse operation** that points to `undoes: <op_id>`; history
  is not deleted or rewritten. The PoC implements a linear undo stack.
- A render receipt binds preview state to a document revision. Rendering can
  fail without corrupting or rolling back a fidelity-checked document edit.
- Production storage can checkpoint periodic HWPX revisions and retain inverse
  operations between checkpoints. This spike keeps every revision for audit.

Simple conflict rule: first accepted operation wins. If the browser or
assistant sends a stale base revision, return `409 stale_revision` with the
current revision and the current target block. The client must reread and make
a new proposal. This is deterministic and sufficient for one user plus one
assistant sharing a local server.

## External assistant bridge

The editor process makes **no model calls**. It exposes a localhost WebSocket,
proposed as `ws://127.0.0.1:<port>/bridge/v1`, and the operator's existing
Claude Code/Codex process connects as a client. A random bridge token is passed
in the first message, not in the URL. The server accepts only localhost Host
headers and a protocol version it understands.

Every message uses this envelope:

```json
{
  "v": 1,
  "id": "message-uuid",
  "type": "document.read.request",
  "session_id": "session-uuid",
  "actor": {"kind": "assistant", "id": "claude-code-session"},
  "base_revision": 12,
  "payload": {}
}
```

### Connect and read

```json
{"v":1,"id":"1","type":"bridge.hello","session_id":"s1","actor":{"kind":"assistant","id":"claude-code"},"base_revision":null,"payload":{"token":"one-time-secret","capabilities":["read","propose"]}}
```

```json
{"v":1,"id":"2","type":"document.read.request","session_id":"s1","actor":{"kind":"assistant","id":"claude-code"},"base_revision":12,"payload":{"include":["outline","blocks"],"block_ids":["s0-p5"]}}
```

```json
{"v":1,"id":"2","type":"document.read.response","session_id":"s1","actor":{"kind":"editor","id":"server"},"base_revision":12,"payload":{"document_sha256":"...","blocks":[{"id":"s0-p5","type":"paragraph","text":"...","editable":true,"hazards":[],"text_payload_sha256":"..."}]}}
```

### Propose, decide, and apply

```json
{
  "v": 1,
  "id": "3",
  "type": "edit.propose",
  "session_id": "s1",
  "actor": {"kind": "assistant", "id": "claude-code"},
  "base_revision": 12,
  "payload": {
    "proposal_id": "proposal-uuid",
    "apply_policy": "review",
    "summary": "Tighten the conclusion without changing the claim.",
    "operations": [
      {
        "op_id": "candidate-1",
        "op": "replace_paragraph_text",
        "paragraph_id": "s0-p5",
        "expected_text_sha256": "...",
        "new_text": "...",
        "rationale": "Remove repetition."
      }
    ]
  }
}
```

The server validates syntax and preconditions but does not apply review-mode
proposals. It emits `edit.proposal.pending` to the browser. The browser returns:

```json
{"v":1,"id":"4","type":"edit.proposal.decision","session_id":"s1","actor":{"kind":"user","id":"browser"},"base_revision":12,"payload":{"proposal_id":"proposal-uuid","decision":"accept","accepted_op_ids":["candidate-1"],"note":null}}
```

After revalidating revision and hashes, the server appends the operation and
emits `edit.applied` with the new revision, fidelity receipt, and preview state.
Reject emits `edit.rejected` without changing the document. A stale accept
emits `edit.conflict` with the current revision and affected block ids.

### Auto-apply

Auto-apply is a **browser-granted, session-scoped lease**, never an assistant
default. The user enables a policy such as:

```json
{"enabled":true,"expires_at":"2026-07-19T11:00:00Z","allowed_ops":["replace_paragraph_text"],"allowed_hazards":[],"max_operations":20,"require_fidelity":true}
```

An assistant may send `apply_policy: "auto"`; the server applies it only when
the lease is live, the operation type is allowed, the target has no hazard, all
preconditions match, and the post-write fidelity check passes. Otherwise it is
demoted to pending review. Equations, table-structure changes, figures, fields,
pipeline gates, and external messages remain manual regardless of this v1
lease.

## Pipeline as an editor feature

Reuse the existing opt-in Studio action-mode boundary: actions hidden by
default, random per-run token, localhost Host check, fixed argv, no free-form
shell input, and exact command/result echo. Derive gate names from the
workspace's declared graph just as current Studio does.

### Appropriate editor actions

| Editor action | Existing command | Conditions |
|---|---|---|
| New report from topic | `python scripts/new_report.py --slug ... --subject ... --topic ... --form ... --mode supervised` | Structured fields; form chosen from an allowed local root; supervised default. |
| Show current stage / “your move” | `pipeline_ctl.py resume <WS>` plus `NEXT_TASK.md` and `.pipeline/handoff.json` | Read-only and always available. |
| Run the current script gate | `pipeline_ctl.py check <WS> <registered-gate>` | Gate comes from the current graph, never request-supplied free text. Build graph currently includes `layout`, `sane`, `content_audit`, `format_check`, `understand`, `final_panel`, and `submission_preflight`; edit graph includes `content_audit`, `edit_verify`, and `submission_preflight`. |
| Approve a human gate | append the explicit operator approval, then `pipeline_ctl.py gate <WS> <gate> --mode supervised` | Confirmation dialog; only graph-declared human gates (`topic_pick`, `design`, `draft`, `edit_spec`, `edit_accept`). Never manufacture autonomous approval. |
| Advance after a successful action | `pipeline_ctl.py advance <WS> <current-stage> --status done` | Server fills stage/status from state; show command and rejection reason. Do not expose arbitrary stage/status fields. |
| Build preview/deliverable | `pipeline/scripts/doc_backend.py <WS> --backend bundle|hwpx` | Existing action mode already exposes both. HWPX keeps its proof-grade label. |
| Workflow conformance | `pipeline/scripts/workflow_lint.py <WS> --json` | Read-only badge and details. |
| Existing-document edit workflow | `pipeline_ctl init ... --graph edit`, followed by graph-driven `resume/check/gate/advance` | v4 should wrap the edit graph rather than mutating a completed build workspace off-workflow. |

The current `run-content-audit` Studio button directly runs
`content_audit.py`. In the integrated editor it should prefer
`pipeline_ctl check <WS> content_audit` when that gate is current, because
`check` records checker argv, exit, stdout hash, and timestamp provenance.

### Keep CLI-only

- raw `pipeline_ctl init`, `advance`, and `gate` arguments; the UI may wrap
  fixed state-derived forms but must not expose arbitrary transitions;
- `invalidate`, because it resets a stage and all later stages and needs an
  operator who understands the cascade;
- `trouble`, shared knowledge/model-log writes, and free-form reason text;
- `heartbeat` and `compose`, which are worker/orchestrator mechanics;
- `autonomous`/`night` approval semantics and any attempt to create
  `auto_approved` records from a browser click;
- arbitrary checker paths, arbitrary backend argv, `--out-dir`, form/profile
  roots outside configured local roots, or free-form shell commands;
- low-level COM assembly/proof commands, skill synchronization, profile
  administration, publishing, releases, merges, and deployment;
- research/simulation/assistant worker execution. Those remain external
  processes that update artifacts and the kernel through recorded commands.

Interactive document revisions must be linked to pipeline state by HWPX hash.
Editing a built report should enter the edit graph, invalidate/recheck affected
artifacts, and reassemble. The editor must not turn a successful local patch
into an unrecorded gate bypass.

## PoC vertical slice

Code is isolated under [`studio/editor/`](../../studio/editor/). The existing
Studio and pipeline scripts are unchanged.

Run:

```powershell
python -m pip install -r studio/requirements.txt
python -m studio.editor.app --port 8010
```

Open `http://127.0.0.1:8010`. The process binds only to `127.0.0.1`, calls no
model or external service, and writes immutable runtime revisions plus
`operations.jsonl` under the system temp directory unless `--data-root` is
given.

Tests:

```powershell
python -m pytest studio/editor/tests -q
```

Environment: the Windows/Python/PyMuPDF environment recorded above. Result:
11 tests passed. The tests cover paragraph projection, XML escaping, exact
member preservation, equation rejection, nested text markup, stale text,
revision conflicts, ordered log + undo, renderer argv/rasterization,
token/Host protection, API edit, and preview retrieval.

Observed end-to-end result:

1. Browser listed the sanitized editable HWPX paragraphs.
2. Playwright changed paragraph `s0-p5` twice.
3. FastAPI applied each edit through the spike document backend.
4. Each operation log receipt reported `changed_members =
   ["Contents/section0.xml"]`, `limited_to_text_payload = true`, and 10
   unchanged member payloads.
5. WSL LibreOffice produced a revised PDF; PyMuPDF produced the page image;
   the browser refreshed to revisions 1 and 2.
6. The separate sanitized hazard HWPX exposed equation paragraph `s0-p9` as
   `editable=false`, with one protected equation run and a display placeholder
   `[equation]`. The backend rejects an edit before writing an output file.

Sanitized samples are under
[`studio/editor/sample_data/`](../../studio/editor/sample_data/). They are
derived from a generic blank form, contain synthetic text only, and have their
creator/last-save metadata, dates, title, and preview text replaced. The sample
factory scans text-bearing archive members for the removed metadata values
before publishing the copy. The source form itself is generic and contains no
student report content.

### PoC limitations

- A paragraph is editable only when it contains exactly one ordinary text
  payload and no equation/object. Mixed character runs, fields, tables,
  pictures, and equations are protected.
- Paragraph ids are section/ordinal ids for the spike. Structural editing will
  require persistent engine-generated ids or revision-scoped ids plus hashes.
- The preview shows page 1 and has no PDF-coordinate-to-block mapping.
- Rendering is synchronous in the PoC to make latency measurable; production
  should make it asynchronous.
- The assistant WebSocket is designed here but not implemented.
- The PoC session is one process and one document; restart/recovery,
  checkpoint compaction, and multiple open documents are future work.

## Phased roadmap

### v1 — structured text editing

- Promote byte-local text operations into the document engine.
- Add persistent/revision-scoped block ids, paragraph/run property projection,
  plain and styled-span edits, ordered session recovery, undo/redo, and
  revision-bound preview receipts.
- Keep fields, equations, tables, and objects opaque and fail closed.
- Move rendering to a debounced asynchronous worker; benchmark idle/cold p95
  before setting a preview SLO.
- Build a sanitized corpus covering multi-run text, self-closing cursor nodes,
  sections, fields, lists, and table-contained paragraphs.

### v2 — tables and figures

- Add typed table-cell text operations first, then row/column operations with
  span and width invariants.
- Add figure replace/caption/alt-text operations while preserving binary-item
  registration and anchoring.
- Keep equations opaque until a specialized equation editor plus Hancom/high-
  resolution proof path exists; never flatten an equation into text.

### v3 — assistant bridge

- Implement the versioned localhost WebSocket schema in this document.
- Add read scopes, pending proposal cards, partial accept/reject, stale-revision
  rebase, audit actors, and browser-granted auto-apply leases.
- Keep the model client outside Studio and make “no model calls in editor” a
  testable invariant.

### v4 — report-pipeline features in the UI

- Add “new report from topic,” current-stage guidance, graph-derived gate
  actions, provenance display, bundle/HWPX build, proof grade, edit-graph
  entry, and workflow lint.
- Use the existing opt-in action-mode authentication and fixed argv rules.
- Bind document revisions to pipeline artifact hashes and invalidate/recheck
  honestly; never hide or bypass kernel gates.

## Exit decision

Proceed to v1 only if the team accepts two constraints: structured operations
are deliberately incomplete/fail-closed, and preview is asynchronous until a
persistent renderer demonstrates an idle/cold latency distribution suitable
for interactive use. Do not invest in an editable-HTML round-trip first.
