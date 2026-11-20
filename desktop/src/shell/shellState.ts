/**
 * Shell state: tabs, docked panes, overlays (WP2).
 *
 * Global chrome (which tabs are open, whether a side is docked, the palette)
 * lives here. Per-document chrome (which left pane and right tab a document
 * shows) is a doc slice, so switching tabs restores each document's own layout.
 *
 * One tab is one session. A tab may also be the Start tab, a document still
 * opening, or a file that failed to open; the last two have no session yet and
 * keep the file name so the person can see what failed.
 */
import { useSyncExternalStore } from "react";

import { defineDocSlice } from "../store.ts";
import type { RuntimeError } from "../types";

export type LeftPaneId = "files" | "outline" | "blanks" | "find" | "history";
export const LEFT_PANES: LeftPaneId[] = ["files", "outline", "blanks", "find", "history"];

export type RightTabId = "changes" | "agent" | "checks";

export type Tab =
  | { kind: "start"; id: "start" }
  | { kind: "doc"; id: string; sessionId: string; preview?: boolean }
  | { kind: "opening"; id: string; name: string; path?: string }
  | { kind: "failed"; id: string; name: string; path?: string; error: RuntimeError | null };

export type Breakpoint = "wide" | "medium" | "overlay" | "narrow";

export interface ShellState {
  tabs: Tab[];
  activeTab: string;
  /** What the person asked for; the breakpoint may still hide a side. */
  leftOpen: boolean;
  rightOpen: boolean;
  /** Below 1360 only one side docks; this is the one that won. */
  lastOpened: "left" | "right";
  paletteOpen: boolean;
  paletteQuery: string;
  settingsOpen: boolean;
  settingsSection?: "general" | "settings:agent";
  appMenuOpen: boolean;
  tabListOpen: boolean;
  narrowDrawerOpen: boolean;
  /** Bumped by Ctrl+S; the status bar pulses `저장됨`. */
  savedPulse: number;
  /** The 문서 폴더 shown in 파일, when one was chosen. */
  docFolder: string | null;
  /** The current breakpoint, kept by the shell on resize. */
  breakpoint: Breakpoint;
}

/** Per-document chrome. Read by WP4 (`rightTab`) and WP3. */
export interface DocLayout {
  leftPane: LeftPaneId;
  rightTab: RightTabId;
  /** True once the landing rule ran for this document (D1 flow a.6). */
  landed: boolean;
}

export const docLayout = defineDocSlice<DocLayout>("shell.layout", () => ({
  leftPane: "outline",
  rightTab: "agent",
  landed: false,
}));

const START_TAB: Tab = { kind: "start", id: "start" };

let state: ShellState = {
  tabs: [START_TAB],
  activeTab: "start",
  leftOpen: true,
  rightOpen: true,
  lastOpened: "right",
  paletteOpen: false,
  paletteQuery: "",
  settingsOpen: false,
  appMenuOpen: false,
  tabListOpen: false,
  narrowDrawerOpen: false,
  savedPulse: 0,
  docFolder: null,
  breakpoint: "wide",
};

const listeners = new Set<() => void>();

export function getShell(): ShellState {
  return state;
}

export function setShell(patch: Partial<ShellState>): void {
  state = { ...state, ...patch };
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function useShell<T>(select: (s: ShellState) => T): T {
  return useSyncExternalStore(
    subscribe,
    () => select(state),
    () => select(state),
  );
}

export function activeTab(s: ShellState = state): Tab | null {
  return s.tabs.find((t) => t.id === s.activeTab) ?? null;
}

export function activeTabSessionId(s: ShellState = state): string | null {
  const tab = activeTab(s);
  return tab?.kind === "doc" ? tab.sessionId : null;
}

export function docTabId(sessionId: string): string {
  return `doc:${sessionId}`;
}

// ---------------------------------------------------------------------------
// Tab operations. Pure on the shell state; the side effects (selecting a
// session in the workspace store) live in `shell/tabs.ts`.

export function withDocTab(s: ShellState, sessionId: string, opts: { replaceId?: string; preview?: boolean } = {}): ShellState {
  const id = docTabId(sessionId);
  const existing = s.tabs.find((t) => t.id === id);
  let tabs = s.tabs;
  if (existing) {
    if (opts.replaceId && opts.replaceId !== id) tabs = tabs.filter((t) => t.id !== opts.replaceId);
    if (existing.kind === "doc" && existing.preview && opts.preview === false) {
      tabs = tabs.map((t) => (t.id === id ? { ...existing, preview: false } : t));
    }
    return { ...s, tabs, activeTab: id };
  }
  const tab: Tab = { kind: "doc", id, sessionId, preview: opts.preview || undefined };
  if (opts.replaceId) {
    const at = tabs.findIndex((t) => t.id === opts.replaceId);
    if (at >= 0) {
      tabs = [...tabs.slice(0, at), tab, ...tabs.slice(at + 1)];
      return { ...s, tabs, activeTab: id };
    }
  }
  if (opts.preview) {
    // A single click in 파일 reuses the one preview tab (J1 §3 IA).
    const at = tabs.findIndex((t) => t.kind === "doc" && t.preview);
    if (at >= 0) {
      tabs = [...tabs.slice(0, at), tab, ...tabs.slice(at + 1)];
      return { ...s, tabs, activeTab: id };
    }
  }
  // The Start tab gives way to the first document opened from it.
  const startAt = tabs.findIndex((t) => t.kind === "start");
  if (startAt >= 0 && s.activeTab === "start") {
    tabs = [...tabs.slice(0, startAt), tab, ...tabs.slice(startAt + 1)];
  } else {
    tabs = [...tabs, tab];
  }
  return { ...s, tabs, activeTab: id };
}

export function withTabClosed(s: ShellState, id: string): ShellState {
  const at = s.tabs.findIndex((t) => t.id === id);
  if (at < 0) return s;
  const tabs = s.tabs.filter((t) => t.id !== id);
  if (tabs.length === 0) return { ...s, tabs: [START_TAB], activeTab: "start" };
  if (s.activeTab !== id) return { ...s, tabs };
  const next = tabs[Math.min(at, tabs.length - 1)];
  return { ...s, tabs, activeTab: next.id };
}

export function withStartTab(s: ShellState): ShellState {
  if (s.tabs.some((t) => t.kind === "start")) return { ...s, activeTab: "start" };
  return { ...s, tabs: [...s.tabs, START_TAB], activeTab: "start" };
}

export function withTabStep(s: ShellState, delta: number): ShellState {
  if (s.tabs.length < 2) return s;
  const at = Math.max(0, s.tabs.findIndex((t) => t.id === s.activeTab));
  const next = s.tabs[(at + delta + s.tabs.length) % s.tabs.length];
  return { ...s, activeTab: next.id };
}

export function withTabPinned(s: ShellState, id: string): ShellState {
  return {
    ...s,
    tabs: s.tabs.map((t) => (t.id === id && t.kind === "doc" && t.preview ? { ...t, preview: false } : t)),
  };
}

// ---------------------------------------------------------------------------
// Breakpoints (J1 §3 IA, D1 §6)

export function breakpointFor(width: number): Breakpoint {
  if (width >= 1360) return "wide";
  if (width >= 900) return "medium";
  if (width >= 600) return "overlay";
  return "narrow";
}

/**
 * Which sides are docked. At 1360 and above both may be. Below that only one:
 * opening the left pane hides the right panel and the reverse. At 1280 the
 * default is the right panel (J1: "1280: left closed, right 340").
 */
export function dockedSides(
  bp: Breakpoint,
  s: Pick<ShellState, "leftOpen" | "rightOpen" | "lastOpened">,
  hasDoc: boolean,
): { left: boolean; right: boolean } {
  if (bp === "narrow") return { left: false, right: false };
  const right = hasDoc && s.rightOpen;
  if (bp === "wide") return { left: s.leftOpen, right };
  if (s.leftOpen && right) {
    return s.lastOpened === "left" ? { left: true, right: false } : { left: false, right: true };
  }
  return { left: s.leftOpen, right };
}

/** Pane widths in px per breakpoint (J1 §3 Widths). */
export function sideWidths(bp: Breakpoint): { left: number; right: number } {
  if (bp === "wide") return { left: 240, right: 360 };
  return { left: 240, right: 340 };
}

/** Test support. */
export function _resetShellForTest(): void {
  state = {
    ...state,
    tabs: [START_TAB],
    activeTab: "start",
    leftOpen: true,
    rightOpen: true,
    lastOpened: "right",
    paletteOpen: false,
    settingsOpen: false,
  };
}
