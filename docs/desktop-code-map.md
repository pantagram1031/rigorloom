# Desktop code map

This is an implementation map for the Desktop frontend. The process and trust
boundary rationale in [desktop-architecture.md](desktop-architecture.md) is
historical design input; its original GAP statements are not a current feature
inventory. The wire contract remains [runtime-protocol-v0.md](runtime-protocol-v0.md).

## One Workspace, two layouts

`desktop/src/main.tsx` mounts React with StrictMode and an error boundary.
`App.tsx` owns startup, subscriptions, window shortcuts and the view switch.
The switch replaces the view subtree; it is not a URL router.

| Layout | Left | Centre | Right |
| --- | --- | --- | --- |
| DocumentView | StructureTree | TextView or PagePreview | ContextPanel: selection, ReviewQueue, History |
| AgentView | SessionList and TaskPacks | Conversation or Timeline, Composer | DocumentContext: document facts, ReviewQueue, History |

Both layouts use the same VerificationBar, Findings and ReceiptPanel components.
Settings is mounted outside the view switch. A review action is still a human
action through the shell regardless of which layout contains its button.

`store.ts` owns the module-level Workspace object and `useSyncExternalStore`
subscription. `setView` changes the layout and supersedes outstanding edit intent;
it does not create a new session, conversation, draft or approval.

| State lifetime | Examples |
| --- | --- |
| Workspace memory, survives view replacement | selection/navigation, draft/approval, turns, unsent composer draft, candidate/receipt state |
| Session-keyed cache in Workspace | inspects, texts, candidates, terminal apply outcomes |
| Active-session presentation | document events, findings, current geometry/render; session replacement explicitly invalidates selected fields |
| Component/DOM lifetime | focus, composition refs, transient editor values; these do not automatically survive remount |
| Persisted shell preferences | settings and recents sent through the existing prefs IPC; composer text is not persisted |

Returning a freshly allocated object from a `useWorkspace` selector is unsafe:
React compares snapshots by identity. Prefer primitives, stored objects, or stable
memoized results. `workspace/reviewSummary.ts` uses primitive session-scoped values.

`workspace/composerDraft.ts` owns the asynchronous submission rule: only the send
that still owns the cleared draft can restore it after refusal. New typing,
including typing followed by clearing, supersedes that restoration.

Apply completion records a session-keyed outcome. It consumes only the captured
queue and advances the visible head only while that queue still owns the current
document. Session changes restore only that document's apply presentation. A
timeout remains ambiguous; the same plan/approval cannot be retried while its
outcome is unknown or already confirmed applied. These caches are memory-only,
not durable Runtime idempotency or crash-recovery guarantees.

## Commands and transport

`actions.ts` orchestrates user actions against the store and `runtime.ts` wrappers.
The wrapper invokes Tauri commands; Rust `sidecar.rs` owns JSONL framing, request
correlation and batched delivery. `src-tauri/src/main.rs` registers commands.

The Python domain implementation is `runtime/scripts/rt_core.py`, shared by the
JSONL server, CLI and MCP. It delegates session, plan, apply and module work to
their own modules. Engine and renderer implementations stay below this boundary.

The agent's provider loop is a separate `agenthost/scripts/ah_host.py` process.
Its compile gate derives allowed calls from the Runtime's agent method roster.
The shell rereads a returned plan before placing it in the review queue. The
provider connection does not gain `approval/resolve` or `plan/apply` because the
Agent layout displays a human approval button.

`agent/planProjection.ts` accepts only cell-fill operations whose complete
semantics the editable queue can preserve. Unsupported operation kinds or
fields refuse the whole projection before replacing the draft. A candidate-based
plan reads its before-values from that exact parent run, not the source cache.

Do not equate the shell's visible turn list with a resumable provider conversation:
the host initializes its own history for each run. Nor should the shell invent a
displayable operation for an agent plan it cannot faithfully represent.

## Event lifetimes

Keep three records separate: shell protocol activity, session document history,
and provider/Agent Host events associated with a turn.

`runtimeSubscriptions.ts` manages asynchronous listener acquisition and disposal.
`documentEvents.ts` manages document subscription replacement and delivery
ownership. Event envelopes carry session and subscription IDs; sequence numbers
are only meaningful within the owning document log. A retired subscription's
late batch is not an event in the newly active document.

The pending replay buffer retains at most 1,000 deliveries per subscription ID;
this is not a global frontend cap across distinct IDs. App effect disposal also
disposes registrations that finish acquiring after their scope has closed.

## Terms that are different domains

- Desktop Workspace: one in-memory shell state and its open document sessions.
- Runtime session: one copied source document under a runtime root.
- Report workspace: a pipeline job with stages, gates and canonical artifacts.
- Distribution module: a registered payload under `modules/<name>/module.yaml`.
- Stage contract: a report pipeline composition unit, not a distribution module.

`studio/` is a separate local FastAPI/HTML report dashboard. Its registry-driven
`studio_panels` are not React Desktop views. Desktop task-pack catalogue data and
Runtime execution enablement have separate readers; keep disagreements visible.

## Focused verification

From `desktop/`, `npm ci --ignore-scripts` installs declared tools, `npm test`
runs the discovered Node tests, and `npm run build` checks TypeScript and builds
the frontend. `tests/test_desktop_workspace_tests.py` bridges these isolated tests
into pytest when Node and Desktop TypeScript are installed; absence is a skip,
not a pass. Existing draft/revision/run-range harnesses live under `tests/`.

These are frontend state and build checks. They do not establish native IME,
installed executable identity, renderer fidelity or Card4/Card5 GUI results.
The in-app `smoke.ts` has a separate built-app evidence contract; a file cleanup
must not quietly remove that production-accessible harness or alter its phases.
