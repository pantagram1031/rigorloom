/**
 * Tab side effects: what activating, opening and closing a tab does to the
 * workspace store and the runtime. Pure tab arithmetic is in `shellState.ts`.
 */
import { loadCorpusFiles, openPath, openUploadedFile, rememberRecent, selectSession } from "../actions";
import * as rt from "../runtime";
import { ensureDoc, getState, setState, subscribeWorkspace } from "../store";
import type { RuntimeError } from "../types";
import { findSessionByPath, pathBasename } from "../workspace/openHelpers";
import {
  activeTab,
  docLayout,
  docTabId,
  getShell,
  setShell,
  type Tab,
  withDocTab,
  withStartTab,
  withTabClosed,
  withTabPinned,
  withTabStep,
} from "./shellState";

let openingSeq = 0;
/** The opening tab a store-side `selectSession` should replace, if any. */
let pendingOpening: string | null = null;

function persistTabs() {
  const s = getShell();
  const sessions = s.tabs.flatMap((t) => (t.kind === "doc" ? [t.sessionId] : []));
  const active = activeTab(s);
  void rt
    .savePrefs({ shellTabs: sessions, shellActive: active?.kind === "doc" ? active.sessionId : null })
    .catch(() => {});
}

/** Mark the start of a tab switch for the budget measure (`tab-switch`). */
function markSwitch() {
  try {
    performance.clearMarks("tab-switch-start");
    performance.mark("tab-switch-start");
  } catch {
    // no performance API (node tests)
  }
}

export function activateTab(id: string): void {
  const s = getShell();
  const tab = s.tabs.find((t) => t.id === id);
  if (!tab) return;
  markSwitch();
  setShell({ activeTab: id, tabListOpen: false });
  if (tab.kind === "doc") {
    ensureDoc(tab.sessionId);
    if (getState().activeSessionId !== tab.sessionId) void selectSession(tab.sessionId).then(() => land(tab.sessionId));
    else land(tab.sessionId);
  } else if (getState().activeSessionId !== null) {
    // Start, opening and failed tabs show no document. Nothing about the
    // previous document leaks into them.
    setState({ activeSessionId: null });
  }
  persistTabs();
}

export function activateTabIndex(n: number): void {
  const tabs = getShell().tabs;
  // Ctrl+9 is the last tab, as in browsers and editors.
  const tab = n >= 9 ? tabs[tabs.length - 1] : tabs[n - 1];
  if (tab) activateTab(tab.id);
}

export function stepTab(delta: number): void {
  const next = withTabStep(getShell(), delta);
  if (next.activeTab !== getShell().activeTab) activateTab(next.activeTab);
}

export function openStartTab(): void {
  const next = withStartTab(getShell());
  setShell({ tabs: next.tabs });
  activateTab("start");
}

export function closeTab(id: string = getShell().activeTab): void {
  const before = getShell();
  const next = withTabClosed(before, id);
  setShell({ tabs: next.tabs });
  // Drafts are persisted per document; closing never asks to save (D1 §2).
  activateTab(next.activeTab);
}

export function pinTab(id: string): void {
  setShell({ tabs: withTabPinned(getShell(), id).tabs });
  persistTabs();
}

/** Show a document in a tab, opening one if needed. */
export function showDocument(sessionId: string, opts: { preview?: boolean } = {}): void {
  ensureDoc(sessionId);
  const replaceId = pendingOpening ?? undefined;
  pendingOpening = null;
  const next = withDocTab(getShell(), sessionId, { replaceId, preview: opts.preview });
  setShell({ tabs: next.tabs });
  activateTab(docTabId(sessionId));
}

/**
 * The landing rule (D1 flow a.6), once per document: with pending changes the
 * right panel shows 변경; otherwise 에이전트. The left pane shows 빈칸 when
 * the form has blanks, else 개요. The app never lands on an empty review.
 */
export function land(sessionId: string): void {
  const layout = docLayout.get(sessionId);
  if (layout.landed) return;
  const s = getState();
  if (s.activeSessionId !== sessionId) return;
  const inspect = s.inspects[sessionId];
  if (!inspect) return; // not read yet; called again when it is
  const pending =
    (s.draft.sessionId === sessionId && s.draft.ops.length > 0) ||
    (s.approval !== null && s.approval.state === "pending");
  const blanks = (inspect.graph?.tables ?? []).some((t) =>
    (t.cells ?? []).some((c) => c.classification === "fill_target"),
  );
  docLayout.set(sessionId, {
    leftPane: blanks ? "blanks" : "outline",
    rightTab: pending ? "changes" : "agent",
    landed: true,
  });
}

// ---------------------------------------------------------------------------
// Opening, with a tab that appears at once and keeps the file name on failure.

function beginOpening(name: string, path?: string): string {
  const id = `opening:${(openingSeq += 1)}`;
  const s = getShell();
  const tab: Tab = { kind: "opening", id, name, path };
  const startAt = s.tabs.findIndex((t) => t.kind === "start");
  const tabs =
    startAt >= 0 && s.activeTab === "start"
      ? [...s.tabs.slice(0, startAt), tab, ...s.tabs.slice(startAt + 1)]
      : [...s.tabs, tab];
  setShell({ tabs, activeTab: id });
  if (getState().activeSessionId !== null) setState({ activeSessionId: null });
  pendingOpening = id;
  return id;
}

function failOpening(id: string, error: RuntimeError | null) {
  if (pendingOpening === id) pendingOpening = null;
  const s = getShell();
  setShell({
    tabs: s.tabs.map((t) =>
      t.id === id && t.kind === "opening"
        ? { kind: "failed", id, name: t.name, path: t.path, error }
        : t,
    ),
  });
}

/** Open a file by path (Tauri, recents, samples, the 파일 pane). */
export async function openDocumentPath(path: string, opts: { name?: string; preview?: boolean } = {}): Promise<string | null> {
  const current = getState();
  const existing = findSessionByPath(current.sessions, current.openedPaths, path);
  if (existing) {
    showDocument(existing.sessionId, { preview: opts.preview });
    return existing.sessionId;
  }
  const id = beginOpening(opts.name ?? pathBasename(path), path);
  setState({ inspectError: null });
  const sid = await openPath(path);
  if (sid === null) {
    failOpening(id, getState().inspectError);
    return null;
  }
  // openPath → selectSession → the store sync replaced the opening tab.
  if (getShell().tabs.some((t) => t.id === id)) showDocumentReplacing(sid, id);
  // `selectSession` skips the recent when another open overtook it; an opened
  // file is a recent document whatever happened next.
  rememberRecent(sid);
  return sid;
}

function showDocumentReplacing(sessionId: string, openingId: string) {
  pendingOpening = openingId;
  showDocument(sessionId);
}

/** Browser mode: a file the person picked or dropped. */
export async function openDocumentUpload(file: File): Promise<string | null> {
  const id = beginOpening(file.name);
  setState({ inspectError: null });
  const sid = await openUploadedFile(file);
  if (sid === null) {
    // `openUploadedFile` refuses unsupported names with a toast and no error.
    const err = getState().inspectError ?? {
      code: "unsupported_file",
      message: file.name,
      detail: null,
    };
    failOpening(id, err as RuntimeError);
    return null;
  }
  if (getShell().tabs.some((t) => t.id === id)) showDocumentReplacing(sid, id);
  return sid;
}

/** Retry or replace a failed tab: closes it, then the caller opens something else. */
export function dismissFailedTab(id: string): void {
  closeTab(id);
}

// ---------------------------------------------------------------------------
// Keeping tabs and the workspace store in step.

let lastActive: string | null = null;
let installed = false;

/**
 * Any code path that selects a session (boot, legacy open helpers, an agent
 * attaching a plan) gets a tab for it. Called once by the shell.
 */
export function installTabSync(): () => void {
  if (installed) return () => {};
  installed = true;
  lastActive = getState().activeSessionId;
  const off = subscribeWorkspace(() => {
    const s = getState();
    const id = s.activeSessionId;
    if (id && id !== lastActive) {
      lastActive = id;
      const tab = activeTab(getShell());
      if (!(tab?.kind === "doc" && tab.sessionId === id)) showDocument(id);
    } else if (!id) {
      lastActive = null;
    }
    // Inspect results arrive after selection; finish the landing rule then.
    if (id) land(id);
  });
  return () => {
    installed = false;
    off();
  };
}

/** After boot: reopen the tabs the person had, in order. */
export async function restoreTabs(): Promise<void> {
  let prefs: Record<string, unknown> = {};
  try {
    prefs = await rt.loadPrefs();
  } catch {
    return;
  }
  const sessions = new Set(getState().sessions.map((s) => s.sessionId));
  const saved = Array.isArray(prefs.shellTabs) ? (prefs.shellTabs as unknown[]) : [];
  const ids = saved.filter((v): v is string => typeof v === "string" && sessions.has(v));
  let s = getShell();
  for (const id of ids) s = withDocTab({ ...s, activeTab: "" }, id);
  if (ids.length > 0) {
    const current = getState().activeSessionId;
    const activeId = current && ids.includes(current) ? current : ids[ids.length - 1];
    setShell({ tabs: s.tabs.filter((t) => t.kind !== "start" || ids.length === 0), activeTab: docTabId(activeId) });
    for (const id of ids) ensureDoc(id);
    if (getState().activeSessionId !== activeId) await selectSession(activeId);
    land(activeId);
  } else {
    const current = getState().activeSessionId;
    if (current) showDocument(current);
  }
  if (getState().corpusFiles.length === 0) void loadCorpusFiles();
}
