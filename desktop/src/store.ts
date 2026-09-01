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
  Candidate,
  Capabilities,
  Finding,
  InspectResult,
  Recent,
  RegionText,
  RuntimeError,
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

  // --- checking ------------------------------------------------------------
  checkPhase: Phase;
  findings: Finding[];
  checkedAt: string | null;
  sheetOpen: boolean;

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

  // --- agent lane (read-only in this phase) --------------------------------
  activity: Activity[];
  /** Empty by construction: `plan/*` is never called in a read-only phase. */
  planQueue: never[];
  approvals: never[];
  verifications: never[];

  /** Set when the app was launched by the scripted smoke. */
  smokePhase: string | null;
}

const ACTIVITY_CAP = 500;

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

  checkPhase: "idle",
  findings: [],
  checkedAt: null,
  sheetOpen: false,

  uiZoom: 1,
  toast: null,
  recents: [],
  entranceDone: false,
  holdEntrance: false,
  dragOver: false,

  activity: [],
  planQueue: [],
  approvals: [],
  verifications: [],

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
  });
}
