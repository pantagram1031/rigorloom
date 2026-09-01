/**
 * Everything the app can do, as plain functions over the one store.
 *
 * Kept out of components so the scripted smoke drives the same code path a
 * click does — a smoke that exercised its own private path would prove nothing
 * about the app.
 */
import { open as openFileDialog } from "@tauri-apps/plugin-dialog";

import * as rt from "./runtime";
import { getState, setState, setSelection } from "./store";

/** Load a session's inspect once and cache it. */
export async function loadInspect(sessionId: string): Promise<boolean> {
  const cached = getState().inspects[sessionId];
  if (cached) {
    setState({ inspectPhase: "ready", inspectError: null });
    return true;
  }
  setState({ inspectPhase: "starting", inspectError: null });
  try {
    const result = await rt.inspect(sessionId);
    setState({
      inspects: { ...getState().inspects, [sessionId]: result },
      inspectPhase: "ready",
      inspectError: null,
    });
    return true;
  } catch (e) {
    setState({ inspectPhase: "failed", inspectError: rt.asRuntimeError(e) });
    return false;
  }
}

async function loadCandidates(sessionId: string) {
  try {
    const list = await rt.candidates(sessionId);
    setState({ candidates: { ...getState().candidates, [sessionId]: list } });
  } catch {
    // `candidate/list` is not load-bearing for a read-only phase. Absence is
    // not failure — the bar already renders "없음" for an empty set.
  }
}

/** Make a session active. Selection is cleared only when the document changes. */
export async function selectSession(sessionId: string) {
  const previous = getState().activeSessionId;
  setState({
    activeSessionId: sessionId,
    ...(previous !== sessionId ? { selection: null, page: 1 } : {}),
  });
  await rt.savePrefs({ lastSessionId: sessionId });
  await loadInspect(sessionId);
  await loadCandidates(sessionId);
}

export async function refreshSessions(): Promise<void> {
  try {
    setState({ sessions: await rt.sessions() });
  } catch (e) {
    setState({ fatal: rt.asRuntimeError(e) });
  }
}

/**
 * Open a document by absolute path. `workspace/openPath` is host-only, and it
 * validates, copies into the session and records the SHA-256 — the source
 * itself is never touched.
 */
export async function openPath(path: string): Promise<string | null> {
  try {
    const opened = await rt.openPath(path);
    await refreshSessions();
    await selectSession(opened.sessionId);
    return opened.sessionId;
  } catch (e) {
    setState({ inspectPhase: "failed", inspectError: rt.asRuntimeError(e) });
    return null;
  }
}

/** The native file dialog. No web upload, no drag target, no localhost. */
export async function openViaDialog(): Promise<string | null> {
  const chosen = await openFileDialog({
    multiple: false,
    directory: false,
    title: "한글 문서 열기",
    filters: [{ name: "한글 문서", extensions: ["hwpx", "hwp"] }],
  });
  if (typeof chosen !== "string") return null;
  return openPath(chosen);
}

/**
 * Start the runtime and restore what the last run was doing.
 *
 * Objective 5, close/reopen without a terminal: the Runtime already persists
 * sessions on disk under `--root`, so reattaching is remembering the root and
 * the session id and then calling `session/list`. Nothing is re-imported.
 */
export async function boot(): Promise<void> {
  setState({ phase: "starting", phaseNote: "런타임을 시작하는 중", fatal: null });
  try {
    const prefs = await rt.loadPrefs();
    const root = (prefs.root as string | undefined) ?? (await rt.defaultRoot());
    const { status } = await rt.start(root);
    setState({ status, root: status.root ?? root, phaseNote: "능력을 확인하는 중" });

    setState({ capabilities: await rt.capabilities() });
    setState({ phaseNote: "열린 문서를 찾는 중" });
    await refreshSessions();

    const remembered = prefs.lastSessionId as string | undefined;
    const sessions = getState().sessions;
    const target =
      (remembered && sessions.find((s) => s.sessionId === remembered)?.sessionId) ??
      sessions[0]?.sessionId;

    const view = prefs.lastView === "agent" ? "agent" : "document";
    setState({ view });

    if (target) {
      setState({ phaseNote: "문서를 다시 읽는 중" });
      await selectSession(target);
    }
    setState({ phase: "ready", phaseNote: "" });
  } catch (e) {
    setState({ phase: "failed", fatal: rt.asRuntimeError(e) });
  }
}

/** M12: a dead sidecar must be recoverable without losing document state. */
export async function restartRuntime(): Promise<void> {
  const keepSession = getState().activeSessionId;
  setState({ phase: "starting", phaseNote: "런타임을 다시 시작하는 중", fatal: null });
  try {
    const { status } = await rt.start(getState().root);
    setState({ status, capabilities: await rt.capabilities() });
    await refreshSessions();
    if (keepSession && getState().sessions.some((s) => s.sessionId === keepSession)) {
      setState({ activeSessionId: keepSession });
    }
    setState({ phase: "ready", phaseNote: "" });
  } catch (e) {
    setState({ phase: "failed", fatal: rt.asRuntimeError(e) });
  }
}

export { setSelection };
