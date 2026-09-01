/**
 * One Workspace. Two views are projections of it.
 *
 * Product direction §4 states this as product definition, not UI preference:
 * the two views "share one Workspace, one active document session, one
 * conversation state, one selection, one navigation state, one plan queue, one
 * approval state, one candidate set, and one verification history. Switching
 * views must never create a new conversation or duplicate document state."
 *
 * That is enforced structurally here rather than by discipline: `view` is one
 * field of the same object that holds `selection`, `expanded`, `page`, `zoom`
 * and everything else, and `setView` writes only `view`. There is no per-view
 * state anywhere in the tree, so a view switch cannot lose anything — the
 * components have no state of their own to lose.
 *
 * No state library: `useSyncExternalStore` is in React 18 and does the whole
 * job. One fewer dependency in an app whose point is that it has no ambient
 * network and a small supply chain.
 */
import { useSyncExternalStore } from "react";

import type {
  Activity,
  AppliedCandidate,
  ApprovalRecord,
  Candidate,
  Capabilities,
  Finding,
  InspectResult,
  OperationPlan,
  PlanValidation,
  Receipt,
  Recent,
  RegionText,
  RenderResult,
  RuntimeError,
  RuntimeEvent,
  Session,
  SidecarStatus,
} from "./types";

export type View = "document" | "agent";

/**
 * What the centre of Document view shows.
 *
 * `text` is the default and the only one reachable today: the document's own
 * text and table structure in reading order. `page` is wired for the render
 * method the runtime does not have yet and stays disabled until
 * `capabilities` advertises it.
 */
export type CenterMode = "text" | "page";

export type Selection =
  | { kind: "paragraph"; atPara: number }
  | { kind: "cell"; table: number; row: number; col: number }
  | { kind: "table"; table: number }
  | null;

/** A stable id for a selection, used for tree keys and equality in the smoke. */
export function selectionId(s: Selection): string {
  if (!s) return "none";
  if (s.kind === "paragraph") return `p:${s.atPara}`;
  if (s.kind === "table") return `t:${s.table}`;
  return `c:${s.table}:${s.row}:${s.col}`;
}

export type Phase = "idle" | "starting" | "ready" | "failed";

// --- the editing loop --------------------------------------------------------

/**
 * One queued edit, before it is a plan.
 *
 * `before` is captured at the moment the seat is opened for editing, from the
 * text the runtime returned — so the queue can show `before → after` without
 * asking the document again, and so a changed `before` is detectable.
 *
 * `origin` is not decoration. An op an agent proposed and an op the user typed
 * are approved by exactly the same gate, but the queue must say which is
 * which: that difference is the whole product claim, and hiding it would make
 * the claim unverifiable by the person doing the approving.
 */
export interface QueuedOp {
  opId: string;
  kind: "fill_cell";
  table: number;
  row: number;
  col: number;
  text: string;
  /** Declared when the seat's preflight demands it (T30). */
  charPr?: string;
  before: string;
  origin: "user" | "agent";
  /** Who proposed it, when that is an agent. */
  proposer?: string;
}

/**
 * The single pending plan. One draft, rebuilt from the queue on every change.
 *
 * Rebuilding rather than patching is deliberate: a plan binds the exact bytes
 * it was computed against (`boundSha256`) and hashes the whole op list, so
 * "add an op to the existing plan" is not a thing the protocol has. Proposing
 * is cheap; a stale plan is not.
 */
export interface Draft {
  ops: QueuedOp[];
  plan: OperationPlan | null;
  validation: PlanValidation | null;
  /** Which document's bytes the queue was built against. */
  sessionId: string | null;
  boundSha256: string | null;
  phase: Phase;
  error: RuntimeError | null;
  /** Set when the user edited or removed an agent's op: the plan is now ours. */
  rewrittenFromAgent: boolean;
}

/**
 * What the last committed edit received, for the IME harness.
 *
 * `composed` is the load-bearing field and the reason this exists. A test that
 * only compares the final string cannot tell composed Hangul from Unicode
 * characters injected straight into the field — both produce 안녕하세요. If no
 * `compositionend` fired, the IME was bypassed and the run proved nothing, so
 * the harness fails on it rather than reporting a pass it did not earn.
 */
export interface LastCommit {
  value: string;
  composed: boolean;
}

/** The cell currently open for typing. A real `<input>` lives here. */
export interface InlineEdit {
  table: number;
  row: number;
  col: number;
  /** The seat's text before this edit, for the queue's before → after. */
  before: string;
  /** Present when the seat's preflight says a charPr must be declared. */
  charPr?: string;
  /** Whether this is replacing an op already in the queue. */
  opId: string | null;
}

export type ApprovalPhase = "idle" | "requesting" | "pending" | "resolving" | "resolved";

/**
 * What to do after the sidecar died mid-mutation.
 *
 * `plan/apply` is the one call whose interruption is ambiguous from outside:
 * `rt_apply` removes the run directory on any failure, so a torn apply leaves
 * no candidate — but the shell cannot know whether the tear happened before or
 * after the receipt landed. So it records what was in flight and offers to look,
 * rather than guessing either way.
 */
export interface Recovery {
  planId: string;
  approvalId: string;
  atUtc: string;
  reason: string;
  /** Set once the shell has re-listed candidates and knows the answer. */
  outcome: "unknown" | "applied" | "not_applied";
  runId: string | null;
}

export interface WorkspaceState {
  // --- shell ---------------------------------------------------------------
  /** The ONLY field that differs between the two views. */
  view: View;
  phase: Phase;
  /** What the loading state says while `phase === "starting"`. ~1.5 s to first
   *  usable paint is the measured reality (spike M1/M2), so it is designed. */
  phaseNote: string;
  fatal: RuntimeError | null;
  status: SidecarStatus | null;
  panic: { location: string; message: string; logPath: string } | null;

  // --- workspace -----------------------------------------------------------
  root: string | null;
  capabilities: Capabilities | null;
  sessions: Session[];
  activeSessionId: string | null;
  /**
   * The on-disk path each session was opened from.
   *
   * The Runtime deliberately does not keep it: `workspace/openPath` copies the
   * bytes into the session and records only name, size and SHA-256, so the
   * source can never be touched again. Reopening from 최근 문서 needs the
   * original path, so the shell remembers it — and it is shell state, not a
   * runtime fact.
   */
  openedPaths: Record<string, string>;
  /** Cached per session, so switching sessions does not re-run form_inspect. */
  inspects: Record<string, InspectResult>;
  inspectPhase: Phase;
  inspectError: RuntimeError | null;
  candidates: Record<string, Candidate[]>;

  // --- shared selection and navigation (survives every view switch) --------
  selection: Selection;
  expanded: string[];
  page: number;
  /** Page-preview zoom. Independent of `uiZoom`, which scales the whole app. */
  zoom: number;
  centerMode: CenterMode;
  /** Bumped whenever something asks the centre to reveal the selection. */
  locateNonce: number;

  // --- document text (the centre's content) --------------------------------
  /** Full text and per-run colour facts, per session. From document/readRegion. */
  texts: Record<string, RegionText[]>;
  textPhase: Phase;
  textError: RuntimeError | null;

  // --- editing (Phase 4) ----------------------------------------------------
  /** The cell open for typing, or null. */
  inlineEdit: InlineEdit | null;
  /** Evidence support only: what the last commit received, and how. */
  lastCommit: LastCommit | null;
  /** Set by the editor when a real `compositionend` fires. */
  sawComposition: boolean;
  draft: Draft;
  approval: ApprovalRecord | null;
  approvalPhase: ApprovalPhase;
  approvalError: RuntimeError | null;
  applyPhase: Phase;
  applyError: RuntimeError | null;
  /** The candidate the last apply produced, and the one 검사 실행 reads. */
  applied: AppliedCandidate | null;
  recovery: Recovery | null;
  /** Receipts read back, keyed on runId. */
  receipts: Record<string, Receipt>;
  receiptOpen: string | null;
  receiptError: RuntimeError | null;
  exportPhase: Phase;
  exportResult: { path: string; sha256: string; bytes: number; receiptPath: string } | null;
  exportError: RuntimeError | null;
  /** A reopened export, proving the file that left the app still loads. */
  reopened: { path: string; sessionId: string; sha256: string } | null;

  // --- checking ------------------------------------------------------------
  checkPhase: Phase;
  findings: Finding[];
  checkedAt: string | null;
  sheetOpen: boolean;
  /**
   * The canonical verdict for a candidate, read from its receipt.
   *
   * NOT re-derived here: `receipt/read` re-hashes the artifact against its
   * binding before it returns, and the `checks` it carries are the offline
   * checkers' own output from the apply that produced it. `verify/*` is still
   * GAP, so a *re-run* is not available — and the UI says which of the two
   * it is showing rather than blurring them.
   */
  candidateVerdict: { runId: string; report: Receipt["checks"] } | null;

  // --- page rendering -------------------------------------------------------
  renderPhase: Phase;
  render: RenderResult | null;
  renderError: RuntimeError | null;
  preparePhase: Phase;
  prepareError: RuntimeError | null;
  prepareNote: string | null;

  // --- chrome --------------------------------------------------------------
  /** Webview zoom factor, 0.5-2.0, persisted. */
  uiZoom: number;
  toast: { text: string; at: number } | null;
  recents: Recent[];
  /** The entrance has played. A view switch must never reset this. */
  entranceDone: boolean;
  /** Screenshot support only: pin the entrance open so it can be captured. */
  holdEntrance: boolean;
  dragOver: boolean;

  // --- agent lane -----------------------------------------------------------
  /** This shell's own protocol traffic. Diagnostics, behind a disclosure. */
  activity: Activity[];
  /** The session's own `events.jsonl`, live over `event/subscribe`. */
  events: RuntimeEvent[];
  eventSubscription: string | null;
  eventPhase: Phase;
  eventError: RuntimeError | null;
  /** The dev-mode mock agent: is its script reachable from this build? */
  agentTool: { available: boolean; script: string | null; reason: string } | null;
  agentPhase: Phase;
  agentError: RuntimeError | null;
  /** What the last mock-agent run reported, verbatim. */
  agentRun: {
    ok: boolean;
    door: string;
    scenario: string;
    marker: string;
    planId: string;
    approvalId: string | null;
    approvalState: string;
    proposer: string;
    neverCalled: string[];
    exitCode: number;
  } | null;

  /** Set when the app was launched by the scripted smoke. */
  smokePhase: string | null;
}

const ACTIVITY_CAP = 500;
const EVENT_CAP = 1000;

export const EMPTY_DRAFT: Draft = {
  ops: [],
  plan: null,
  validation: null,
  sessionId: null,
  boundSha256: null,
  phase: "idle",
  error: null,
  rewrittenFromAgent: false,
};

const initial: WorkspaceState = {
  view: "document",
  phase: "idle",
  phaseNote: "",
  fatal: null,
  status: null,
  panic: null,

  root: null,
  capabilities: null,
  sessions: [],
  activeSessionId: null,
  openedPaths: {},
  inspects: {},
  inspectPhase: "idle",
  inspectError: null,
  candidates: {},

  selection: null,
  expanded: [],
  page: 1,
  zoom: 1,
  centerMode: "text",
  locateNonce: 0,

  texts: {},
  textPhase: "idle",
  textError: null,

  inlineEdit: null,
  lastCommit: null,
  sawComposition: false,
  draft: EMPTY_DRAFT,
  approval: null,
  approvalPhase: "idle",
  approvalError: null,
  applyPhase: "idle",
  applyError: null,
  applied: null,
  recovery: null,
  receipts: {},
  receiptOpen: null,
  receiptError: null,
  exportPhase: "idle",
  exportResult: null,
  exportError: null,
  reopened: null,

  checkPhase: "idle",
  findings: [],
  checkedAt: null,
  sheetOpen: false,
  candidateVerdict: null,

  renderPhase: "idle",
  render: null,
  renderError: null,
  preparePhase: "idle",
  prepareError: null,
  prepareNote: null,

  uiZoom: 1,
  toast: null,
  recents: [],
  entranceDone: false,
  holdEntrance: false,
  dragOver: false,

  activity: [],
  events: [],
  eventSubscription: null,
  eventPhase: "idle",
  eventError: null,
  agentTool: null,
  agentPhase: "idle",
  agentError: null,
  agentRun: null,

  smokePhase: null,
};

let state: WorkspaceState = initial;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function getState(): WorkspaceState {
  return state;
}

export function setState(patch: Partial<WorkspaceState>) {
  state = { ...state, ...patch };
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Both views call this. There is no second store to fall out of sync with. */
export function useWorkspace<T>(select: (s: WorkspaceState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => select(state),
    () => select(initial),
  );
}

// --- actions -----------------------------------------------------------------

export const setView = (view: View) => setState({ view });

export const setCenterMode = (centerMode: CenterMode) => setState({ centerMode });

export const setSelection = (selection: Selection) => setState({ selection });

/**
 * Select a node AND ask the centre to reveal it.
 *
 * Two calls rather than one flag on `setSelection`, because clicking *in* the
 * centre must not make the centre scroll itself out from under the pointer.
 * The tree calls this; the document calls `setSelection`.
 */
export function locateSelection(selection: Selection) {
  setState({ selection, locateNonce: state.locateNonce + 1 });
}

let toastTimer: number | undefined;

export function showToast(text: string, ms = 1100) {
  setState({ toast: { text, at: Date.now() } });
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => setState({ toast: null }), ms);
}

export function toggleExpanded(id: string) {
  const open = state.expanded.includes(id);
  setState({
    expanded: open
      ? state.expanded.filter((x) => x !== id)
      : [...state.expanded, id],
  });
}

export const setZoom = (zoom: number) =>
  setState({ zoom: Math.min(4, Math.max(0.5, zoom)) });

export const setPage = (page: number) => setState({ page: Math.max(1, page) });

export function pushActivity(batch: Activity[]) {
  if (batch.length === 0) return;
  const next = state.activity.concat(batch);
  setState({
    activity: next.length > ACTIVITY_CAP ? next.slice(next.length - ACTIVITY_CAP) : next,
  });
}

/**
 * Merge a batch of runtime events, keeping the log ordered and duplicate-free.
 *
 * `seq` is the line index in `events.jsonl`, so it is authoritative: a replay
 * after a reconnect re-delivers events this shell already has, and inserting
 * them twice would make the timeline lie about how many times something
 * happened. De-duplicating on `seq` is not defensive coding — it is the
 * property the protocol offers, used.
 */
export function pushEvents(batch: RuntimeEvent[]) {
  if (batch.length === 0) return;
  const bySeq = new Map<number, RuntimeEvent>();
  for (const event of state.events) bySeq.set(event.seq, event);
  let changed = false;
  for (const event of batch) {
    if (bySeq.has(event.seq)) continue;
    bySeq.set(event.seq, event);
    changed = true;
  }
  if (!changed) return;
  const next = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
  setState({ events: next.length > EVENT_CAP ? next.slice(next.length - EVENT_CAP) : next });
}

/** The inspect for the active session, or null. Both views read through this. */
export function activeInspect(s: WorkspaceState): InspectResult | null {
  if (!s.activeSessionId) return null;
  return s.inspects[s.activeSessionId] ?? null;
}

export function activeSession(s: WorkspaceState): Session | null {
  if (!s.activeSessionId) return null;
  return s.sessions.find((x) => x.sessionId === s.activeSessionId) ?? null;
}

/**
 * One shared empty array, never a fresh `[]`.
 *
 * `useSyncExternalStore` compares snapshots with `Object.is`. A selector that
 * returns a new literal on every call never compares equal, React treats the
 * store as perpetually changed, and the render loop it detects takes the whole
 * root down — the UI vanishes while the store looks perfectly healthy. That is
 * exactly what the first smoke run caught: every store assertion passed and
 * every DOM assertion failed.
 */
const NO_CANDIDATES: Candidate[] = [];
const NO_TEXT: RegionText[] = [];

export function activeCandidates(s: WorkspaceState): Candidate[] {
  if (!s.activeSessionId) return NO_CANDIDATES;
  return s.candidates[s.activeSessionId] ?? NO_CANDIDATES;
}

export function activeText(s: WorkspaceState): RegionText[] {
  if (!s.activeSessionId) return NO_TEXT;
  return s.texts[s.activeSessionId] ?? NO_TEXT;
}

/** Whether the runtime advertises a way to produce a page raster. */
export function canRenderPages(s: WorkspaceState): boolean {
  const methods = s.capabilities?.methods ?? [];
  return methods.some((m) => m.startsWith("document/render"));
}

/** Whether the host-only prepare step is on the wire at all. */
export function canPreparePages(s: WorkspaceState): boolean {
  return (s.capabilities?.methods ?? []).includes("document/renderPrepare");
}

// --- the editing loop, read side ---------------------------------------------

/**
 * Is the pending queue still bound to the document on screen?
 *
 * Two ways it can come loose, and the UI must distinguish them:
 *
 *  - the queue was built against ANOTHER SESSION (the user switched documents
 *    with edits pending) — shell-side, and the only one reachable today;
 *  - the source bytes under this session changed after the plan was proposed —
 *    the runtime's own `plan_stale`, reported by `plan/validate`.
 *
 * The second is structurally unreachable on this Runtime: `openPath` copies the
 * bytes into the session and nothing writes to that copy again, so
 * `current_source_sha256()` cannot move under a live plan. It is still handled,
 * because "cannot happen today" is a property of this build, not of the
 * protocol, and the refusal has a designed state either way.
 */
export type Staleness = null | {
  kind: "other_session" | "source_changed";
  boundSha256: string;
  currentSha256: string | null;
};

/**
 * The last computed staleness, returned by reference when nothing changed.
 *
 * THIS CACHE IS NOT AN OPTIMISATION. `useSyncExternalStore` compares snapshots
 * with `Object.is`, so a selector that builds a fresh object on every call
 * never compares equal, React concludes the store is changing forever, and its
 * infinite-loop detector takes the whole root down — which unmounts `App`,
 * runs its effect cleanup, and silently drops the event listeners with it.
 *
 * That is not a hypothetical. It is the exact failure `NO_CANDIDATES` above
 * was introduced for, and this selector walked straight back into it: the
 * smoke reported every store assertion passing, every DOM assertion failing,
 * and zero events delivered, all from React error #185 inside the review
 * queue. Returning a stable reference is what makes an object-valued selector
 * legal here at all.
 */
let stalenessCache: Staleness = null;

export function draftStaleness(s: WorkspaceState): Staleness {
  const next = computeStaleness(s);
  if (next === null) {
    stalenessCache = null;
    return null;
  }
  const cached = stalenessCache;
  if (
    cached !== null &&
    cached.kind === next.kind &&
    cached.boundSha256 === next.boundSha256 &&
    cached.currentSha256 === next.currentSha256
  ) {
    return cached;
  }
  stalenessCache = next;
  return next;
}

function computeStaleness(s: WorkspaceState): Staleness {
  const draft = s.draft;
  if (draft.ops.length === 0 || !draft.boundSha256) return null;
  if (draft.sessionId && s.activeSessionId && draft.sessionId !== s.activeSessionId) {
    return {
      kind: "other_session",
      boundSha256: draft.boundSha256,
      currentSha256: activeInspect(s)?.documentHash ?? null,
    };
  }
  if (draft.validation?.stale) {
    return {
      kind: "source_changed",
      boundSha256: draft.validation.boundSha256,
      currentSha256: draft.validation.currentSha256,
    };
  }
  return null;
}

/** The queue is approvable only when it validates and nothing has moved. */
export function canRequestApproval(s: WorkspaceState): boolean {
  return (
    s.draft.ops.length > 0 &&
    s.draft.plan !== null &&
    s.draft.validation?.ok === true &&
    draftStaleness(s) === null &&
    s.approvalPhase === "idle" &&
    s.applyPhase !== "starting"
  );
}

/** A stable key for a cell, shared by the queue, the tree and the centre. */
export function cellKey(table: number, row: number, col: number): string {
  return `c:${table}:${row}:${col}`;
}

/** The queued op sitting on a given cell, if any. */
export function queuedOpAt(
  s: WorkspaceState,
  table: number,
  row: number,
  col: number,
): QueuedOp | null {
  return (
    s.draft.ops.find((op) => op.table === table && op.row === row && op.col === col) ?? null
  );
}

/**
 * A compact signature of everything a view switch must preserve.
 *
 * The scripted smoke reads this before and after switching views and asserts
 * equality. Keeping it in the store — rather than in the test — means the
 * property is stated once, in the code that owns it.
 */
export function sharedStateSignature(s: WorkspaceState = state): string {
  return JSON.stringify({
    session: s.activeSessionId,
    selection: selectionId(s.selection),
    expanded: [...s.expanded].sort(),
    page: s.page,
    zoom: s.zoom,
    centerMode: s.centerMode,
    sessions: s.sessions.map((x) => x.sessionId),
    documentHash: activeInspect(s)?.documentHash ?? null,
    activity: s.activity.length,
    candidates: Object.keys(s.candidates).length,
    texts: Object.keys(s.texts).length,
    findings: s.findings.length,
    uiZoom: s.uiZoom,
    recents: s.recents.map((r) => r.sha256),
    entranceDone: s.entranceDone,
    // Phase 4. The plan queue, the approval and the candidate are exactly the
    // state product direction §4 names as shared, so they belong in the
    // signature the smoke asserts across a view switch. An edit in progress is
    // here too: a half-typed value must survive Ctrl+2 and come back.
    draftOps: s.draft.ops.map((op) => `${cellKey(op.table, op.row, op.col)}=${op.text}`),
    draftPlan: s.draft.plan?.opsHash ?? null,
    draftVerdict: s.draft.validation?.verdict ?? null,
    inlineEdit: s.inlineEdit
      ? cellKey(s.inlineEdit.table, s.inlineEdit.row, s.inlineEdit.col)
      : null,
    approval: s.approval ? `${s.approval.approvalId}:${s.approval.state}` : null,
    applied: s.applied?.candidate.sha256 ?? null,
    verdict: s.candidateVerdict?.report.acceptance ?? null,
    receiptOpen: s.receiptOpen,
    events: s.events.length,
  });
}
