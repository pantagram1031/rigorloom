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
  InspectResult,
  RuntimeError,
  Session,
  SidecarStatus,
} from "./types";

export type View = "document" | "agent";

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
  /** Cached per session, so switching sessions does not re-run form_inspect. */
  inspects: Record<string, InspectResult>;
  inspectPhase: Phase;
  inspectError: RuntimeError | null;
  candidates: Record<string, Candidate[]>;

  // --- shared selection and navigation (survives every view switch) --------
  selection: Selection;
  expanded: string[];
  page: number;
  zoom: number;

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
  inspects: {},
  inspectPhase: "idle",
  inspectError: null,
  candidates: {},

  selection: null,
  expanded: [],
  page: 1,
  zoom: 1,

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

export const setSelection = (selection: Selection) => setState({ selection });

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

export function activeCandidates(s: WorkspaceState): Candidate[] {
  if (!s.activeSessionId) return NO_CANDIDATES;
  return s.candidates[s.activeSessionId] ?? NO_CANDIDATES;
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
    sessions: s.sessions.map((x) => x.sessionId),
    documentHash: activeInspect(s)?.documentHash ?? null,
    activity: s.activity.length,
    candidates: Object.keys(s.candidates).length,
  });
}
