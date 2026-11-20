/**
 * TEMPORARY stand-ins for WP2's C0 contracts (`shell/slots.ts`, the store API
 * and the key registry), under the names J1 §5 fixes. The panel imports them
 * from here only; when C0 lands, this file is deleted and the imports point
 * at `../shell/slots` and `../shell/keys`.
 *
 * Nothing here is shown to a person, and nothing here is global behaviour the
 * shell does not already promise: slots are a name → component map, a doc
 * slice is per-session state outside `store.ts`, and the key registry
 * dispatches bindings with the IME guard.
 */
import { useSyncExternalStore, type ComponentType } from "react";

import { getState, useWorkspace } from "../store";
import { bindingAllows, chordMatches, type KeyContext } from "./keys";

// --- slots ---------------------------------------------------------------------

export type SlotName =
  | "canvas"
  | "rightPanel"
  | "stripStart"
  | "stripEnd"
  | "statusLeft"
  | "statusRight"
  | "narrowSheet"
  | `pane:${string}`
  | `settings:${string}`;

const slots = new Map<string, ComponentType>();

export function registerSlot(name: SlotName, component: ComponentType): void {
  slots.set(name, component);
}

export function getSlot(name: SlotName): ComponentType | null {
  return slots.get(name) ?? null;
}

// --- per-document state --------------------------------------------------------

type Listener = () => void;

export interface DocSlice<T> {
  readonly key: string;
  get(doc: string | null): T;
  set(doc: string | null, patch: Partial<T> | ((prev: T) => Partial<T>)): void;
  use<R>(doc: string | null, select: (s: T) => R): R;
  reset(doc: string | null): void;
}

export function defineDocSlice<T extends object>(key: string, initial: T): DocSlice<T> {
  let byDoc: Record<string, T> = {};
  const listeners = new Set<Listener>();
  const NONE = "\u0000none";
  const id = (doc: string | null) => doc ?? NONE;
  const emit = () => {
    for (const l of listeners) l();
  };
  const subscribe = (l: Listener) => {
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  };
  const get = (doc: string | null): T => byDoc[id(doc)] ?? initial;
  return {
    key,
    get,
    set(doc, patch) {
      const prev = get(doc);
      const delta = typeof patch === "function" ? patch(prev) : patch;
      byDoc = { ...byDoc, [id(doc)]: { ...prev, ...delta } };
      emit();
    },
    use(doc, select) {
      return useSyncExternalStore(
        subscribe,
        () => select(get(doc)),
        () => select(initial),
      );
    },
    reset(doc) {
      const next = { ...byDoc };
      delete next[id(doc)];
      byDoc = next;
      emit();
    },
  };
}

/** The active document's session id. */
export function useActiveDoc(): string | null {
  return useWorkspace((s) => s.activeSessionId);
}

export function activeDoc(): string | null {
  return getState().activeSessionId;
}

// --- keys ----------------------------------------------------------------------

export interface KeyBindingSpec {
  id: string;
  /** `Y`, `Ctrl+Shift+Enter`, `Alt+8`. Letters match the physical key. */
  chords: string[];
  /** Single keys never fire in an editable target or while composing. */
  when?: (ctx: KeyContext) => boolean;
  run: (e: KeyboardEvent) => void;
}

const bindings = new Map<string, KeyBindingSpec>();
let listening = false;

function onKeyDown(e: KeyboardEvent): void {
  for (const binding of bindings.values()) {
    const chord = binding.chords.find((c) => chordMatches(c, e));
    if (!chord) continue;
    const ctx: KeyContext = { target: e.target, composing: e.isComposing || e.keyCode === 229 };
    if (!bindingAllows(chord, ctx)) continue;
    if (binding.when && !binding.when(ctx)) continue;
    e.preventDefault();
    binding.run(e);
    return;
  }
}

export const keys = {
  register(spec: KeyBindingSpec): () => void {
    bindings.set(spec.id, spec);
    if (!listening && typeof window !== "undefined") {
      window.addEventListener("keydown", onKeyDown);
      listening = true;
    }
    return () => {
      bindings.delete(spec.id);
    };
  },
  chordsOf(id: string): string[] {
    return bindings.get(id)?.chords ?? [];
  },
};

/** The first chord bound to `id`, split into keycaps: `["Ctrl", "Shift", "Enter"]`. */
export function useKeyHint(id: string): string[] {
  const chord = keys.chordsOf(id)[0];
  return chord ? chord.split("+") : [];
}

export interface CommandSpec {
  id: string;
  title: () => string;
  run: () => void;
  keyId?: string;
}

const commands = new Map<string, CommandSpec>();

export function registerCommand(spec: CommandSpec): void {
  commands.set(spec.id, spec);
}
