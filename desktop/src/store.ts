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
  AgentHostStatus,
  AppliedCandidate,
  ApprovalRecord,
  Candidate,
  CandidateCompare,
  Capabilities,
  CredentialStatus,
  Finding,
  GeometryResult,
  HostEvent,
  InspectResult,
  ModuleCheckReport,
  OperationPlan,
  OverlayPick,
  PlanValidation,
  ProviderProfile,
  ProviderSettings,
  Receipt,
  Recent,
  RegionText,
  RenderResult,
  RuntimeError,
  RuntimeEvent,
  Session,
  SidecarStatus,
  TaskPackList,
  Turn,
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

/** 폭 맞춤 / 쪽 맞춤 / 직접. See `WorkspaceState.pageFit`. */
export type PageFit = "width" | "page" | "free";

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
interface QueuedOpBase {
  opId: string;
  text: string;
  /** Declared when the seat's preflight demands it (T30). */
  charPr?: string;
  before: string;
  origin: "user" | "agent";
  /** Who proposed it, when that is an agent. */
  proposer?: string;
}

/** A value going into an empty cell. `fill-cells`, via `plan/propose`. */
export interface QueuedFillOp extends QueuedOpBase {
  kind: "fill_cell";
  table: number;
  row: number;
  col: number;
  /**
   * Write into a cell that is not empty (`preedit --overwrite`).
   *
   * Off for an ordinary fill, and that default is a guard worth keeping: a
   * seat with something already in it is a seat somebody may have filled on
   * purpose, and preedit refuses rather than clobbering it. A 되돌리기 제안
   * sets it, because the cell it is restoring is occupied BY the edit being
   * reversed — the one case where overwriting is precisely the intent.
   */
  overwrite?: boolean;
}

/**
 * A paragraph line rewritten. `set-runs`, via the SAME `plan/propose`.
 *
 * There is no `replace_paragraph_text` operation and this shell did not invent
 * one: `set_run` replaces one run at `(atPara, run)` and preserves its
 * `charPrIDRef` (engine/scripts/preedit.py:2464). What that costs is the check
 * in `beginParagraphEdit` — a run is not a line, and the two coincide only
 * where a paragraph holds exactly one run. Where they do not, no caret is
 * placed at all.
 *
 * `run` is the index the run inventory returned, never a count this shell kept.
 */
export interface QueuedRunOp extends QueuedOpBase {
  kind: "set_run";
  atPara: number;
  run: number;
}

export type QueuedOp = QueuedFillOp | QueuedRunOp;

/** Where a queued op points, as one string. Cells and runs both have one. */
export function opTargetId(op: QueuedOp): string {
  return op.kind === "fill_cell"
    ? cellKey(op.table, op.row, op.col)
    : `p:${op.atPara}#${op.run}`;
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
  /**
   * The candidate this queue chains onto, or null for the source (§15.2).
   *
   * Set from the head of the chain whenever there is one, so a second edit
   * after an apply lands on TOP of the first rather than beside it. Before
   * this existed the second candidate quietly did not contain the first edit.
   */
  baseRunId: string | null;
  /**
   * The candidate this queue undoes, when it is a 되돌리기 제안.
   *
   * A queue carrying this is still an ordinary queue: same review, same
   * approval, same apply. The only difference is what the receipt will record
   * and what gets proven afterwards.
   */
  reverses: string | null;
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

interface InlineEditBase {
  /** The target's text before this edit, for the queue's before → after. */
  before: string;
  /** Present when the seat's preflight says a charPr must be declared. */
  charPr?: string;
  /** Whether this is replacing an op already in the queue. */
  opId: string | null;
}

/** The cell currently open for typing. A real `<input>` lives here. */
export interface InlineCellEdit extends InlineEditBase {
  kind: "cell";
  table: number;
  row: number;
  col: number;
}

/**
 * The paragraph line currently open for typing, with a caret in it.
 *
 * `caret` is a character offset the runtime's own `charX` resolved from where
 * the click landed. `null` means the line carried no per-character boxes and
 * the click SNAPPED to the start — a state the status bar has to say out loud,
 * which is the only reason this is a nullable number rather than a 0.
 *
 * `spanIndex` is carried so the overlay can mount the field in the rectangle
 * the runtime placed for that exact line, and `sizePt` so the field can be set
 * at the size the render drew it at rather than at the chrome's size.
 */
export interface InlineRunEdit extends InlineEditBase {
  kind: "run";
  atPara: number;
  run: number;
  caret: number | null;
  spanIndex: number;
  sizePt?: number;
}

export type InlineEdit = InlineCellEdit | InlineRunEdit;

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
  /**
   * How the page is fitted to the window, when it is fitted at all.
   *
   * `"free"` means `zoom` is exactly what the user asked for. `"width"` and
   * `"page"` mean the page view derives the scale from its own measured box
   * every time that box changes — so a resized window keeps fitting.
   *
   * GEOMETRY IS ZOOM-INDEPENDENT and this changes nothing about that: the
   * overlay rects are fractions of the page, so a fit change multiplies by a
   * different pixel size and asks the runtime nothing (§12.1).
   */
  pageFit: PageFit;
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

  // --- undo, in two tiers that are never blurred together (E1.4) -----------
  /**
   * Ops taken out of the QUEUE, newest last. The pre-approval undo's redo.
   *
   * This tier is exact and cheap because nothing has happened yet: an op in
   * the queue is not in any candidate, so removing it IS the undo and there is
   * no document to reconcile. It is labelled 대기열에서 제거 in the UI and
   * never 문서 되돌리기 — conflating the two would be telling a person their
   * document changed back when nothing ever changed.
   *
   * Cleared whenever the queue is bound to a different document or emptied
   * into a candidate: a redo that re-enqueued an op against other bytes would
   * be a different edit wearing the same label.
   */
  redoStack: QueuedOp[];
  /**
   * The candidate the shell treats as the document's current state.
   *
   * SHELL STATE, and it has to be: the runtime records parents but not a head
   * (§15.7), because a chain can fork. So this is a selection, made explicit
   * in the 기록 panel rather than drifting silently — and it is what a new
   * edit chains onto and what an export writes.
   */
  head: string | null;
  /** Which candidate the 기록 panel is showing, read-only. Never moves `head`. */
  historySelected: string | null;
  /**
   * Addresses each candidate's chain changed, as `c:t:r:c` / `p:N` keys (E1.2).
   *
   * Store state rather than a module memo, and that is not a style choice: the
   * page's echo is rendered through `useWorkspace`, so a cache the store cannot
   * see would fill in after the last re-render and the marks would never
   * appear. Keyed on the head run; absent means "not read yet", which the page
   * says out loud rather than drawing an unmarked page and looking clean.
   */
  changedByRun: Record<string, string[]>;
  /** Phase of a 되돌리기 제안 while it reads the chain and proposes. */
  undoPhase: Phase;
  undoError: RuntimeError | null;
  /**
   * `candidate/compare` for the reversal that was just applied.
   *
   * The runtime's answer, held verbatim. `regionsEqual` is the claim an undo
   * has to make good; `artifactEqual` is reported beside it and is normally
   * false, because restoring text is not restoring bytes.
   */
  inverseProof: {
    runId: string;
    reversedRunId: string;
    compare: CandidateCompare;
  } | null;

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

  // --- page geometry, and the overlay drawn from it (protocol §12) ----------
  /**
   * The geometry answer for the page on screen. Never derived, never patched:
   * if the runtime says `available: false` the overlay draws NOTHING, because
   * the alternative — a box interpolated from `summary.pageMetrics` — would be
   * this shell inventing a layout and calling it the renderer's.
   */
  geometry: GeometryResult | null;
  geometryPhase: Phase;
  geometryError: RuntimeError | null;
  /**
   * Answers held per `(session, page)`.
   *
   * The rects are fractions of the page, so they are the same at every zoom;
   * a zoom change multiplies by a different pixel size and re-asks nothing.
   * §12.1 is explicit that bundling geometry into `render` would re-extract
   * every glyph position on every zoom nudge, and a client that re-fetched on
   * zoom would have paid that cost anyway.
   */
  geometryCache: Record<string, GeometryResult>;
  /**
   * Evidence support only: how many times the METHOD was actually called.
   *
   * A cache is invisible from the outside, and "zoom does not re-fetch" is
   * exactly the sort of claim that quietly stops being true. The smoke reads
   * this across a zoom sweep; nothing in the UI does.
   */
  geometryFetches: number;
  /** What the last click on the page resolved to. Drives the status bar. */
  overlayPick: OverlayPick | null;

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

  // --- the Agent Host (Phase 5) --------------------------------------------
  /** Where `host.py` is, if it is anywhere. Absent = the composer says so. */
  agentHost: AgentHostStatus | null;
  /** What the settings pane holds. References only, never a secret. */
  provider: ProviderSettings;
  /** The last 연결 확인, verbatim. `unknown` stays `unknown` on screen. */
  providerProfile: ProviderProfile | null;
  probePhase: Phase;
  probeError: RuntimeError | null;
  /** Present / absent / how many bytes. Never the value. */
  credential: CredentialStatus | null;
  /** The conversation, newest last. One process per turn. */
  turns: Turn[];
  /** The turn in flight, if any. One at a time, enforced in Rust too. */
  activeTurn: string | null;
  settingsOpen: boolean;
  /**
   * Which of Agent view's two centre panes is showing.
   *
   * Navigation, so it lives in the store with `view`, `selection` and
   * `centerMode` rather than in the component — a view switch must not lose it,
   * and the property is structural rather than a discipline.
   */
  agentTab: "conversation" | "history";

  // --- 작업 팩 ---------------------------------------------------------------
  taskPacks: TaskPackList | null;
  /** Which pack's detail panel is open. */
  packOpen: string | null;
  /**
   * The last `module/check` this shell ran, and for which pack.
   *
   * One at a time, keyed by module name, because the panel shows one pack at a
   * time and a report from a pack the user has since navigated away from would
   * be a verdict attached to the wrong heading. Cleared when the module or the
   * session changes rather than left to go stale.
   */
  packRun: {
    module: string;
    sessionId: string;
    phase: "running" | "done" | "failed";
    report: ModuleCheckReport | null;
    error: RuntimeError | null;
  } | null;

  /** Mirrored from the window so the toolbar can label the control. */
  fullscreen: boolean;

  /** Set when the app was launched by the scripted smoke. */
  smokePhase: string | null;
}

/**
 * The settings a fresh install starts with.
 *
 * `anthropic.model` is left EMPTY rather than pre-filled with the adapter's
 * default. The adapter's default is `claude-opus-5` and it is the adapter's to
 * choose; copying it here would make the UI a second place that decides, and
 * the two would drift the first time the adapter moved. Empty means "whatever
 * the adapter says", and the settings pane shows what the adapter actually
 * answered under 연결 확인.
 */
export const DEFAULT_PROVIDER: ProviderSettings = {
  provider: "mock",
  scenario: "propose-one",
  router: { baseUrl: "", model: "", storeKey: "RIGORLOOM_ROUTER" },
  anthropic: { model: "", storeKey: "RIGORLOOM_ANTHROPIC" },
};

/** The store key the active provider uses, or null when it needs none. */
export function activeStoreKey(settings: ProviderSettings): string | null {
  if (settings.provider === "mock") return null;
  const key =
    settings.provider === "router" ? settings.router.storeKey : settings.anthropic.storeKey;
  return key.trim() === "" ? null : key.trim();
}

/** The config members the active provider contributes. Nothing secret-shaped. */
export function providerConfigFields(
  settings: ProviderSettings,
): Record<string, unknown> {
  if (settings.provider === "router") {
    return {
      providerId: "router",
      baseUrl: settings.router.baseUrl.trim(),
      model: settings.router.model.trim(),
    };
  }
  if (settings.provider === "anthropic") {
    return { model: settings.anthropic.model.trim() };
  }
  return {};
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
  baseRunId: null,
  reverses: null,
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
  pageFit: "free",
  centerMode: "text",
  locateNonce: 0,

  texts: {},
  textPhase: "idle",
  textError: null,

  inlineEdit: null,
  lastCommit: null,
  sawComposition: false,
  draft: EMPTY_DRAFT,
  redoStack: [],
  head: null,
  historySelected: null,
  changedByRun: {},
  undoPhase: "idle",
  undoError: null,
  inverseProof: null,
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

  geometry: null,
  geometryPhase: "idle",
  geometryError: null,
  geometryCache: {},
  geometryFetches: 0,
  overlayPick: null,

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

  agentHost: null,
  provider: DEFAULT_PROVIDER,
  providerProfile: null,
  probePhase: "idle",
  probeError: null,
  credential: null,
  turns: [],
  activeTurn: null,
  settingsOpen: false,
  agentTab: "conversation",

  taskPacks: null,
  packOpen: null,
  packRun: null,

  fullscreen: false,

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

/**
 * A zoom the user asked for by number. Leaves any fit mode, because a fit that
 * silently overrode the number the person just typed would be a control that
 * does not do what it says.
 */
export const setZoom = (zoom: number) =>
  setState({ zoom: Math.min(4, Math.max(0.5, zoom)), pageFit: "free" });

/** Enter (or leave) a fit mode. The scale itself is measured by the page view. */
export const setPageFit = (pageFit: PageFit) => setState({ pageFit });

/**
 * The scale a FIT arrived at. Keeps the mode, unlike `setZoom`.
 *
 * Separate function rather than a flag, because the two callers mean different
 * things: a person moving the zoom control has left the fit, and a window
 * resize has not.
 */
export const setFittedZoom = (zoom: number) =>
  setState({ zoom: Math.min(4, Math.max(0.5, zoom)) });

/**
 * The scale a fit mode wants, from the box it has to fit into.
 *
 * Kept here rather than in the component so the smoke can assert the arithmetic
 * without a layout, and so both call sites agree. `pagePx` is the page's size
 * at 100%; `boxPx` is the scroller's usable interior.
 */
export function fitScale(
  fit: PageFit,
  page: { width: number; height: number },
  box: { width: number; height: number },
  current: number,
): number {
  if (fit === "free" || page.width <= 0 || page.height <= 0) return current;
  if (box.width <= 0 || box.height <= 0) return current;
  const byWidth = box.width / page.width;
  const scale = fit === "width" ? byWidth : Math.min(byWidth, box.height / page.height);
  return Math.min(4, Math.max(0.5, Math.round(scale * 1000) / 1000));
}

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

// --- the conversation ---------------------------------------------------------

/**
 * Fold a batch of live Agent Host events into the turn they belong to.
 *
 * De-duplicated on `seq` for the same reason `pushEvents` is: the tail thread
 * reads a file by offset, and a re-read after a partial line would otherwise
 * make one provider request look like two. `seq` is the log's own index, so it
 * is authoritative here exactly as it is for the Runtime's.
 */
export function pushHostEvents(batch: Array<{ turnId: string; event: HostEvent }>) {
  if (batch.length === 0) return;
  const byTurn = new Map<string, HostEvent[]>();
  for (const row of batch) {
    const bucket = byTurn.get(row.turnId) ?? [];
    bucket.push(row.event);
    byTurn.set(row.turnId, bucket);
  }
  let changed = false;
  const turns = state.turns.map((turn) => {
    const incoming = byTurn.get(turn.id);
    if (!incoming) return turn;
    const bySeq = new Map<number, HostEvent>();
    for (const event of turn.events) bySeq.set(event.seq, event);
    let touched = false;
    for (const event of incoming) {
      if (bySeq.has(event.seq)) continue;
      bySeq.set(event.seq, event);
      touched = true;
    }
    if (!touched) return turn;
    changed = true;
    return { ...turn, events: [...bySeq.values()].sort((a, b) => a.seq - b.seq) };
  });
  if (!changed) return;
  setState({ turns });
}

export function patchTurn(id: string, patch: Partial<Turn>) {
  setState({
    turns: state.turns.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)),
  });
}

/**
 * Whether the composer may send.
 *
 * Four things must be true, and each one has its own sentence in the UI when it
 * is not: there is a document, the Agent Host is reachable, nothing is already
 * running, and the chosen provider has what it needs to make a call. The last
 * is the honest one — a provider that takes a credential and has none is not a
 * dead button, it is a button that says which key is missing.
 */
export function composerBlocker(s: WorkspaceState): string | null {
  if (!s.activeSessionId) return "no_document";
  if (!s.agentHost?.available) return "no_host";
  if (s.activeTurn) return "busy";
  if (s.provider.provider === "mock") return null;
  if (!activeStoreKey(s.provider)) return "no_credential_name";
  if (s.credential?.state !== "present") return "no_credential";
  if (s.provider.provider === "router" && s.provider.router.baseUrl.trim() === "") {
    return "no_base_url";
  }
  return null;
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

// --- the candidate chain, read side (E1.4) ------------------------------------

/**
 * The candidates of the active session in LINEAGE order, roots first.
 *
 * `candidate/list` already sorts by `createdUtc`, which is the order they were
 * published in. This walks the `base` links on top of that so a child never
 * precedes its parent even if two runs share a stamp, and so a fork is visible
 * as two children of one parent rather than being flattened into a line.
 *
 * A row whose base is not in the list is treated as a root and SAID to be one
 * by the panel, rather than being dropped: a candidate whose parent's receipt
 * has gone is still a candidate, and hiding it would hide the loss.
 */
export function lineage(rows: Candidate[]): Candidate[] {
  const byId = new Map<string, Candidate>();
  for (const row of rows) if (row.runId) byId.set(row.runId, row);
  const children = new Map<string | null, Candidate[]>();
  for (const row of rows) {
    const parent = row.base?.runId ?? null;
    const key = parent !== null && byId.has(parent) ? parent : null;
    const bucket = children.get(key) ?? [];
    bucket.push(row);
    children.set(key, bucket);
  }
  const out: Candidate[] = [];
  const walk = (key: string | null) => {
    for (const row of children.get(key) ?? []) {
      out.push(row);
      if (row.runId) walk(row.runId);
    }
  };
  walk(null);
  // Anything a cycle in the data would have stranded. Cannot happen with
  // runtime-written receipts; appended rather than silently lost if it does.
  for (const row of rows) if (!out.includes(row)) out.push(row);
  return out;
}

/** The candidate a reversal names, when this one is a reversal. */
export function reversedBy(rows: Candidate[], runId: string): Candidate | null {
  return rows.find((row) => row.reverses?.runId === runId) ?? null;
}

/**
 * Which candidate the shell is standing on: the explicit head, or the newest.
 *
 * The runtime has no head (§15.7) and this does not pretend otherwise — it is
 * a shell decision with a stated default, and the 기록 panel shows which row
 * carries it.
 */
export function headCandidate(s: WorkspaceState): Candidate | null {
  const rows = activeCandidates(s);
  if (rows.length === 0) return null;
  if (s.head) {
    const chosen = rows.find((row) => row.runId === s.head);
    if (chosen) return chosen;
  }
  const ordered = lineage(rows);
  return ordered[ordered.length - 1] ?? null;
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
): QueuedFillOp | null {
  return (
    s.draft.ops.find(
      (op): op is QueuedFillOp =>
        op.kind === "fill_cell" && op.table === table && op.row === row && op.col === col,
    ) ?? null
  );
}

/** The queued op sitting on a given paragraph run, if any. */
export function queuedRunOpAt(
  s: WorkspaceState,
  atPara: number,
  run: number,
): QueuedRunOp | null {
  return (
    s.draft.ops.find(
      (op): op is QueuedRunOp =>
        op.kind === "set_run" && op.atPara === atPara && op.run === run,
    ) ?? null
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
    pageFit: s.pageFit,
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
    draftOps: s.draft.ops.map((op) => `${opTargetId(op)}=${op.text}`),
    draftPlan: s.draft.plan?.opsHash ?? null,
    draftVerdict: s.draft.validation?.verdict ?? null,
    // A half-typed value survives Ctrl+2 and comes back — including the caret
    // offset, because a caret that came back at the front of the line would be
    // a different edit in all but name.
    inlineEdit: s.inlineEdit
      ? s.inlineEdit.kind === "cell"
        ? cellKey(s.inlineEdit.table, s.inlineEdit.row, s.inlineEdit.col)
        : `p:${s.inlineEdit.atPara}#${s.inlineEdit.run}@${s.inlineEdit.caret ?? "start"}`
      : null,
    approval: s.approval ? `${s.approval.approvalId}:${s.approval.state}` : null,
    applied: s.applied?.candidate.sha256 ?? null,
    // E1.4. Undo is Workspace state like every other kind: a 되돌리기 제안
    // half-reviewed in Document view must be the same proposal in Agent view,
    // and a redo stack that emptied on Ctrl+2 would be a second history.
    draftBase: s.draft.baseRunId,
    draftReverses: s.draft.reverses,
    redoStack: s.redoStack.map((op) => `${opTargetId(op)}=${op.text}`),
    head: s.head,
    historySelected: s.historySelected,
    inverseProof: s.inverseProof
      ? `${s.inverseProof.runId}:${s.inverseProof.compare.regionsEqual}`
      : null,
    verdict: s.candidateVerdict?.report.acceptance ?? null,
    receiptOpen: s.receiptOpen,
    events: s.events.length,
    // Phase 5. Product direction §4 names "one conversation state" in the same
    // breath as one selection and one plan queue, so the conversation belongs
    // in the signature the smoke asserts across a view switch — including
    // which turn is in flight, because a turn that lost its live events on
    // Ctrl+1 would be a second conversation in all but name.
    turns: s.turns.map((turn) => `${turn.id}:${turn.phase}:${turn.events.length}`),
    activeTurn: s.activeTurn,
    provider: s.provider.provider,
    agentTab: s.agentTab,
    packOpen: s.packOpen,
    // A pack's verdict is workspace state like any other: it survives Ctrl+1
    // and Ctrl+2, or it was never one Workspace to begin with.
    packRun: s.packRun
      ? `${s.packRun.module}:${s.packRun.phase}:${s.packRun.report?.counts.selected ?? 0}`
      : null,
  });
}
