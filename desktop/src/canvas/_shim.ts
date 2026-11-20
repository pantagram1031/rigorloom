/**
 * Minimal local shim for WP2's shell contracts (`registerSlot`, `defineDocSlice`,
 * `useDoc`, `useActiveDoc`, `keys.register`, `useKeyHint`, `registerCommand`)
 * and structural WP4 `ChangeItem` compatibility while WP2/WP4 run in parallel.
 *
 * When WP2 merges `shell/slots.ts`, `shell/keys.ts`, and `store.ts` v2,
 * `canvas/register.ts` and `canvas/controller.ts` swap imports from `./_shim`
 * to WP2's shell modules with zero API changes.
 */
import { useSyncExternalStore, type ComponentType } from "react";

import type { CanvasChangeDecision, CanvasChangeRef, CanvasChangeSource } from "../model/page";
import { DECISION_KO_ALIAS_MAP, SOURCE_KO_ALIAS_MAP } from "../i18n/v2/wp3FormTokens";
import { activeSession, getState, useWorkspace, type WorkspaceState } from "../store";
import type { IndexedChange, RowGuardAudit } from "../workspace/guardHelper";

// --- Slot registry (WP2: shell/slots.ts) ------------------------------------

export type SlotName =
  | "canvas"
  | "rightPanel"
  | "pane:files"
  | "pane:outline"
  | "pane:blanks"
  | "pane:find"
  | "pane:history"
  | "stripStart"
  | "stripEnd"
  | "statusLeft"
  | "statusRight"
  | "narrowSheet"
  | `settings:${string}`;

const slotRegistry = new Map<string, ComponentType<Record<string, unknown>>>();
const slotListeners = new Set<() => void>();

export function registerSlot<P = Record<string, unknown>>(
  name: SlotName,
  component: ComponentType<P>,
): void {
  slotRegistry.set(name, component as ComponentType<Record<string, unknown>>);
  for (const fn of slotListeners) fn();
}

export function getRegisteredSlot(
  name: SlotName,
): ComponentType<Record<string, unknown>> | null {
  return slotRegistry.get(name) ?? null;
}

export function listRegisteredSlots(): SlotName[] {
  return [...slotRegistry.keys()] as SlotName[];
}

// --- Per-document slices (WP2: store.ts v2) ----------------------------------

const DEFAULT_DOC_KEY = "__default__";

export interface DocSliceHandle<T> {
  readonly key: string;
  readonly initial: T;
  get(sessionId?: string | null): T;
  set(patch: Partial<T> | ((prev: T) => T), sessionId?: string | null): void;
  use(sessionId?: string | null): T;
  reset(sessionId?: string | null): void;
}

const sliceStores = new Map<string, Map<string, unknown>>();
const sliceListeners = new Map<string, Set<() => void>>();

function notifySlice(key: string): void {
  const set = sliceListeners.get(key);
  if (!set) return;
  for (const fn of set) fn();
}

export function defineDocSlice<T extends object>(
  key: string,
  initial: T,
): DocSliceHandle<T> {
  if (!sliceStores.has(key)) {
    sliceStores.set(key, new Map());
    sliceListeners.set(key, new Set());
  }

  const resolveSid = (explicit?: string | null): string => {
    if (explicit !== undefined) return explicit || DEFAULT_DOC_KEY;
    try {
      return getState().activeSessionId || DEFAULT_DOC_KEY;
    } catch {
      return DEFAULT_DOC_KEY;
    }
  };

  const read = (sessionId?: string | null): T => {
    const sid = resolveSid(sessionId);
    const map = sliceStores.get(key)!;
    if (!map.has(sid)) {
      map.set(sid, { ...initial });
    }
    return map.get(sid) as T;
  };

  const write = (
    patch: Partial<T> | ((prev: T) => T),
    sessionId?: string | null,
  ): void => {
    const sid = resolveSid(sessionId);
    const map = sliceStores.get(key)!;
    const prev = read(sid);
    const next =
      typeof patch === "function"
        ? patch(prev)
        : { ...prev, ...patch };
    if (Object.is(prev, next)) return;
    map.set(sid, next);
    notifySlice(key);
  };

  const subscribe = (listener: () => void) => {
    const listeners = sliceListeners.get(key)!;
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  };

  return {
    key,
    initial,
    get: read,
    set: write,
    use: (sessionId?: string | null) =>
      useSyncExternalStore(
        subscribe,
        () => read(sessionId),
        () => initial,
      ),
    reset: (sessionId?: string | null) => {
      const sid = resolveSid(sessionId);
      sliceStores.get(key)!.set(sid, { ...initial });
      notifySlice(key);
    },
  };
}

export interface DocRef {
  sessionId: string;
  name: string;
  kind: string;
  sha256: string;
}

export function useDoc(sessionId: string | null): DocRef | null {
  return useWorkspace((s: WorkspaceState) => {
    if (!sessionId) return null;
    const sess = s.sessions.find((item) => item.sessionId === sessionId);
    if (!sess) return null;
    return {
      sessionId: sess.sessionId,
      name: sess.source.name,
      kind: sess.source.documentKind,
      sha256: sess.source.sha256,
    };
  });
}

export function useActiveDoc(): DocRef | null {
  const sess = useWorkspace(activeSession);
  if (!sess) return null;
  return {
    sessionId: sess.sessionId,
    name: sess.source.name,
    kind: sess.source.documentKind,
    sha256: sess.source.sha256,
  };
}

// --- Command & Keybinding registry (WP2: shell/keys.ts) ----------------------

export interface KeyBindingSpec {
  id: string;
  chords: readonly string[];
  when?: string | (() => boolean);
  hint?: string;
  run: (event?: KeyboardEventLike) => void | boolean | Promise<void | boolean>;
}

export interface KeyboardEventLike {
  code: string;
  key?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  isComposing?: boolean;
  keyCode?: number;
  target?: {
    tagName?: string;
    isContentEditable?: boolean;
    closest?: (selector: string) => unknown;
  } | null;
  preventDefault?: () => void;
  stopPropagation?: () => void;
}

export interface CommandSpec {
  id: string;
  title: string;
  category?: string;
  keybinding?: string;
  when?: () => boolean;
  run: () => void | Promise<void>;
}

const keyBindings = new Map<string, KeyBindingSpec>();
const keyListeners = new Set<() => void>();
const commands = new Map<string, CommandSpec>();

export const keys = {
  register(spec: KeyBindingSpec): () => void {
    keyBindings.set(spec.id, spec);
    for (const fn of keyListeners) fn();
    return () => {
      keyBindings.delete(spec.id);
      for (const fn of keyListeners) fn();
    };
  },
  list(): KeyBindingSpec[] {
    return [...keyBindings.values()];
  },
  getHint(id: string): string | null {
    const spec = keyBindings.get(id);
    if (!spec) return null;
    return spec.hint ?? spec.chords[0] ?? null;
  },
};

export function useKeyHint(id: string): string | null {
  return useSyncExternalStore(
    (cb) => {
      keyListeners.add(cb);
      return () => keyListeners.delete(cb);
    },
    () => keys.getHint(id),
    () => keys.getHint(id),
  );
}

export function registerCommand(spec: CommandSpec): () => void {
  commands.set(spec.id, spec);
  return () => {
    commands.delete(spec.id);
  };
}

export function listRegisteredCommands(): CommandSpec[] {
  return [...commands.values()];
}

const KEY_CODE_ALIASES: Record<string, string> = {
  "=": "Equal",
  "+": "Equal",
  "-": "Minus",
  "0": "Digit0",
  "ArrowUp": "ArrowUp",
  "ArrowDown": "ArrowDown",
  "Enter": "Enter",
  "Escape": "Escape",
  "PgUp": "PageUp",
  "PgDn": "PageDown",
  "PageUp": "PageUp",
  "PageDown": "PageDown",
  "F2": "F2",
  "F3": "F3",
  "F8": "F8",
};

function normalizeChordToken(token: string): string {
  if (token.length === 1 && /^[a-zA-Z]$/.test(token)) {
    return `Key${token.toUpperCase()}`;
  }
  return KEY_CODE_ALIASES[token] ?? token;
}

export function matchesChord(e: KeyboardEventLike, chord: string): boolean {
  const parts = chord.split("+").map((p) => p.trim()).filter(Boolean);
  let needCtrl = false;
  let needAlt = false;
  let needShift = false;
  let expectedCode = "";

  for (const part of parts) {
    if (part === "Ctrl" || part === "Mod") needCtrl = true;
    else if (part === "Alt") needAlt = true;
    else if (part === "Shift") needShift = true;
    else expectedCode = normalizeChordToken(part);
  }

  const hasCtrl = Boolean(e.ctrlKey || e.metaKey);
  const hasAlt = Boolean(e.altKey);
  const hasShift = Boolean(e.shiftKey);

  if (hasCtrl !== needCtrl) return false;
  if (hasAlt !== needAlt) return false;
  if (hasShift !== needShift) return false;
  return e.code === expectedCode;
}

export function isEditableTarget(target: KeyboardEventLike["target"]): boolean {
  if (!target) return false;
  const tag = (target.tagName ?? "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  if (typeof target.closest === "function" && target.closest('[contenteditable="true"]')) {
    return true;
  }
  return false;
}

/**
 * Physical-key dispatcher with strict Korean IME guard (`isComposing || keyCode === 229`)
 * and editable-target guard for single-key shortcuts.
 */
export function dispatchCanvasKeyEvent(e: KeyboardEventLike): string | null {
  if (e.isComposing || e.keyCode === 229) {
    return null;
  }

  const editable = isEditableTarget(e.target);
  const hasModifier = Boolean(e.ctrlKey || e.metaKey || e.altKey);

  for (const spec of keyBindings.values()) {
    const allowInInput = spec.when === "always" || hasModifier && Boolean(e.altKey);
    if (editable && !allowInInput) {
      continue;
    }
    if (typeof spec.when === "function" && !spec.when()) {
      continue;
    }
    if (spec.chords.some((chord) => matchesChord(e, chord))) {
      const handled = spec.run(e);
      if (handled !== false) {
        e.preventDefault?.();
        return spec.id;
      }
    }
  }
  return null;
}

// --- Left pane switcher shim (WP2 owns left pane host) ----------------------

export type Wp3PaneId = "outline" | "blanks" | "find";
let activeLeftPaneHook: ((pane: Wp3PaneId) => void) | null = null;
let findFocusModeHook: ((mode: "find" | "replace") => void) | null = null;

export function bindLeftPaneNavigator(fn: (pane: Wp3PaneId) => void): () => void {
  activeLeftPaneHook = fn;
  return () => {
    if (activeLeftPaneHook === fn) activeLeftPaneHook = null;
  };
}

export function requestLeftPane(pane: Wp3PaneId): void {
  activeLeftPaneHook?.(pane);
}

export function bindFindFocusHook(fn: (mode: "find" | "replace") => void): () => void {
  findFocusModeHook = fn;
  return () => {
    if (findFocusModeHook === fn) findFocusModeHook = null;
  };
}

export function requestFindFocus(mode: "find" | "replace"): void {
  requestLeftPane("find");
  findFocusModeHook?.(mode);
}

// --- Structural adapter from v1/WP0 IndexedChange to CanvasChangeRef ---------

export function normalizeChangeSource(
  rawSource: unknown,
  opOrigin?: "user" | "agent",
  opProposer?: string,
  reverses?: string | null,
): CanvasChangeSource {
  if (rawSource === "test" || rawSource === "mock") return "test";
  if (rawSource === "revert") return "revert";
  if (rawSource === "user") return "user";
  if (rawSource === "agent") return "agent";
  if (typeof rawSource === "string" && rawSource in SOURCE_KO_ALIAS_MAP) {
    return SOURCE_KO_ALIAS_MAP[rawSource];
  }
  if (reverses) return "revert";
  if (opProposer === "agenthost-mock" || opProposer === "rigorloom-mock-agent") return "test";
  if (opOrigin === "user") return "user";
  return "agent";
}

export function normalizeChangeDecision(
  rawDecision: unknown,
  source: CanvasChangeSource,
): CanvasChangeDecision {
  if (rawDecision === "accepted") return "accepted";
  if (rawDecision === "rejected") return "rejected";
  if (rawDecision === "pending") return "pending";
  if (typeof rawDecision === "string" && rawDecision in DECISION_KO_ALIAS_MAP) {
    return DECISION_KO_ALIAS_MAP[rawDecision];
  }
  return source === "user" ? "accepted" : "pending";
}

export function indexedChangesToCanvasRefs(
  changes: readonly IndexedChange[],
  rowAudits: Record<string, RowGuardAudit>,
  decisions: Readonly<Record<string, CanvasChangeDecision>>,
  options?: {
    isStale?: boolean;
    reverses?: string | null;
    planProvenance?: string | null;
  },
): CanvasChangeRef[] {
  return changes.map((ch) => {
    const audit = rowAudits[ch.opId];
    const op = ch.op as IndexedChange["op"] & {
      provenance?: string | null;
    };
    const source = normalizeChangeSource(
      op.provenance ?? options?.planProvenance,
      op.origin,
      op.proposer,
      options?.reverses,
    );
    const decision = normalizeChangeDecision(decisions[ch.opId], source);
    const isFactChanged = audit?.status === "changed";
    const guard: CanvasChangeRef["guard"] =
      audit?.status === "changed"
        ? "changed"
        : audit?.status === "needs_fixes"
          ? "needs_fixes"
          : audit?.status === "kept"
            ? "kept"
            : "none";

    const cellKey =
      op.kind === "fill_cell" || op.kind === "replace_at_cell"
        ? `c:${op.table}:${op.row}:${op.col}`
        : undefined;
    const at =
      op.kind === "fill_cell" || op.kind === "replace_at_cell"
        ? `t${op.table}/r${op.row}/c${op.col}`
        : op.kind === "set_run"
          ? `p${op.atPara}`
          : "place:guides";

    return {
      id: ch.opId,
      n: ch.ordinal,
      at,
      kind: ch.opKindText,
      opKind: op.kind,
      label: ch.fieldLabel,
      before: ch.beforeText,
      after: ch.afterText,
      page: 1,
      source,
      decision,
      guard,
      hard: ch.hasHardFailure,
      isFactChanged,
      isStale: Boolean(options?.isStale),
      cellKey,
      atPara: op.kind === "set_run" ? op.atPara : undefined,
      run:
        op.kind === "replace_at_cell" || op.kind === "set_run"
          ? op.run
          : undefined,
      hasFormText: ch.beforeText.trim().length > 0 && op.kind === "replace_at_cell",
      bodyStyleApplied:
        (op.kind === "fill_cell" || op.kind === "replace_at_cell") &&
        Boolean(op.charPr),
    };
  });
}
