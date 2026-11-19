/**
 * The one key registry (J1 §3 Keyboard, D1 §4).
 *
 * Bindings are data: `{id, chords, when, profile}` plus the `run` callback.
 * Every hint on screen reads from here through `useKeyHint(id)`, so a keycap
 * can never disagree with the key that actually fires.
 *
 * Rules the dispatcher enforces, not the callers:
 * - Letters, digits and punctuation match by physical key (`KeyboardEvent.code`),
 *   so 한/영 state never matters.
 * - Nothing fires while an IME is composing (`isComposing || keyCode === 229`).
 *   Korean composition must never trigger Y/N/E/U/J/K.
 * - Single keys (no Ctrl, Alt or Meta; F-keys and Esc excepted) never fire in an
 *   editable target unless the binding says `inEditable: true`.
 * - Modifier chords fire in editable targets unless the binding says
 *   `inEditable: false` (so Ctrl+Z inside an input stays the input's own undo).
 *
 * This file has no React or DOM imports beyond types, so node tests load it.
 */
import { useSyncExternalStore } from "react";

export type KeyProfile = "standard";

/**
 * A context name such as `review`, `sheet`, `pageEdit`, `composer`, or a
 * predicate read at dispatch time. Absent, `"global"` or `"always"` = global.
 */
export type KeyWhen = string | (() => boolean);

export interface KeyBinding {
  /** Stable action id, e.g. `shell.palette`, `review.accept`. One binding per id. */
  id: string;
  /**
   * Chord strings: `Ctrl+Shift+P`, `Alt+1`, `F3`, `Shift+F3`, `Y`, `Ctrl+=`.
   * Two strokes are separated by a space: `Ctrl+K Ctrl+S`.
   * The first chord is the one hints show.
   */
  chords: readonly string[];
  /** Chords that replace `chords` in a plain browser, where Ctrl+T/W/Tab belong to the browser. */
  browserChords?: readonly string[];
  when?: KeyWhen;
  profile?: KeyProfile;
  /** See the file comment. Default: true for modifier chords, false for single keys. */
  inEditable?: boolean;
  /** Return `false` to decline, letting the next match (or the browser) have the key. */
  run: (event: KeyEventLike) => boolean | void | Promise<unknown>;
}

/** The subset of `KeyboardEvent` the dispatcher reads. Tests pass plain objects. */
export interface KeyEventLike {
  code: string;
  key?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  isComposing?: boolean;
  keyCode?: number;
  repeat?: boolean;
  target?: unknown;
  preventDefault?: () => void;
  stopPropagation?: () => void;
}

export interface Stroke {
  ctrl: boolean;
  alt: boolean;
  shift: boolean;
  /** Canonical code, e.g. `KeyK`, `Digit1`, `Enter`, `F3`, `Equal`. */
  code: string;
}

// ---------------------------------------------------------------------------
// Chord parsing and display

const NAMED: Record<string, string> = {
  enter: "Enter",
  return: "Enter",
  esc: "Escape",
  escape: "Escape",
  tab: "Tab",
  space: "Space",
  backspace: "Backspace",
  delete: "Delete",
  del: "Delete",
  up: "ArrowUp",
  down: "ArrowDown",
  left: "ArrowLeft",
  right: "ArrowRight",
  arrowup: "ArrowUp",
  arrowdown: "ArrowDown",
  arrowleft: "ArrowLeft",
  arrowright: "ArrowRight",
  pageup: "PageUp",
  pgup: "PageUp",
  pagedown: "PageDown",
  pgdn: "PageDown",
  home: "Home",
  end: "End",
  "=": "Equal",
  "+": "Equal",
  "-": "Minus",
  ",": "Comma",
  ".": "Period",
  "/": "Slash",
  ";": "Semicolon",
  "'": "Quote",
  "[": "BracketLeft",
  "]": "BracketRight",
  "\\": "Backslash",
  "`": "Backquote",
};

/** Event codes that count as the same physical key for matching. */
const CODE_ALIASES: Record<string, string> = {
  NumpadEnter: "Enter",
  NumpadAdd: "Equal",
  NumpadSubtract: "Minus",
  NumpadDecimal: "Period",
  NumpadDivide: "Slash",
  Numpad0: "Digit0",
  Numpad1: "Digit1",
  Numpad2: "Digit2",
  Numpad3: "Digit3",
  Numpad4: "Digit4",
  Numpad5: "Digit5",
  Numpad6: "Digit6",
  Numpad7: "Digit7",
  Numpad8: "Digit8",
  Numpad9: "Digit9",
};

/** `KeyboardEvent.code` names accepted verbatim in chords (`Ctrl+Equal`). */
const KNOWN_CODES = new Set([
  "Equal", "Minus", "Comma", "Period", "Slash", "Semicolon", "Quote", "BracketLeft", "BracketRight",
  "Backslash", "Backquote", "Enter", "Escape", "Tab", "Space", "Backspace", "Delete", "ArrowUp",
  "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home", "End", "Insert",
]);

function keyToCode(raw: string): string {
  const k = raw.trim();
  if (k.length === 1 && /[a-z]/i.test(k)) return `Key${k.toUpperCase()}`;
  if (k.length === 1 && /[0-9]/.test(k)) return `Digit${k}`;
  if (/^f([1-9]|1[0-2])$/i.test(k)) return k.toUpperCase();
  const named = NAMED[k.toLowerCase()];
  if (named) return named;
  if (/^(Key[A-Z]|Digit[0-9]|Numpad[0-9])$/.test(k)) return CODE_ALIASES[k] ?? k;
  if (KNOWN_CODES.has(k)) return k;
  throw new Error(`keys: unknown key name "${raw}"`);
}

export function parseStroke(text: string): Stroke {
  // `Ctrl++` is not used; `+` inside a chord is always a separator except a trailing `=`/`-`.
  const parts = text.split("+").map((p) => p.trim());
  // Handle a trailing literal "+" (e.g. "Ctrl++") by re-joining an empty tail.
  if (parts.length >= 2 && parts[parts.length - 1] === "" && parts[parts.length - 2] === "") {
    parts.splice(parts.length - 2, 2, "+");
  }
  const stroke: Stroke = { ctrl: false, alt: false, shift: false, code: "" };
  for (const part of parts) {
    const lower = part.toLowerCase();
    if (lower === "ctrl" || lower === "control" || lower === "mod") stroke.ctrl = true;
    else if (lower === "alt" || lower === "option") stroke.alt = true;
    else if (lower === "shift") stroke.shift = true;
    else {
      if (stroke.code) throw new Error(`keys: two keys in one stroke "${text}"`);
      stroke.code = keyToCode(part);
    }
  }
  if (!stroke.code) throw new Error(`keys: no key in stroke "${text}"`);
  return stroke;
}

export function parseChord(text: string): Stroke[] {
  return text
    .trim()
    .split(/\s+/)
    .map(parseStroke);
}

export function strokeId(s: Stroke): string {
  return `${s.ctrl ? "C" : ""}${s.alt ? "A" : ""}${s.shift ? "S" : ""}:${s.code}`;
}

export function chordId(chord: string): string {
  return parseChord(chord).map(strokeId).join(" ");
}

const CODE_LABEL: Record<string, string> = {
  Escape: "Esc",
  ArrowUp: "↑",
  ArrowDown: "↓",
  ArrowLeft: "←",
  ArrowRight: "→",
  Equal: "=",
  Minus: "-",
  Comma: ",",
  Period: ".",
  Slash: "/",
  Semicolon: ";",
  Quote: "'",
  BracketLeft: "[",
  BracketRight: "]",
  Backslash: "\\",
  Backquote: "`",
  PageUp: "PgUp",
  PageDown: "PgDn",
};

function codeLabel(code: string): string {
  if (code.startsWith("Key")) return code.slice(3);
  if (code.startsWith("Digit")) return code.slice(5);
  return CODE_LABEL[code] ?? code;
}

/** Keycaps for one chord: `Ctrl+Shift+P` → `["Ctrl", "Shift", "P"]`. Two strokes join with `" "`. */
export function chordCaps(chord: string): string[] {
  const out: string[] = [];
  parseChord(chord).forEach((s, i) => {
    if (i > 0) out.push(" ");
    if (s.ctrl) out.push("Ctrl");
    if (s.alt) out.push("Alt");
    if (s.shift) out.push("Shift");
    out.push(codeLabel(s.code));
  });
  return out;
}

/** A single key: no Ctrl or Alt. F-keys and Esc are never "single keys" for the editable rule. */
export function isSingleKey(s: Stroke): boolean {
  if (s.ctrl || s.alt) return false;
  if (/^F([1-9]|1[0-2])$/.test(s.code)) return false;
  if (s.code === "Escape") return false;
  return true;
}

// ---------------------------------------------------------------------------
// Event helpers

/** The IME guard. Korean composition reports `isComposing` or keyCode 229. */
export function isComposingEvent(e: KeyEventLike): boolean {
  return Boolean(e.isComposing) || e.keyCode === 229;
}

/** Inputs, textareas, selects and contenteditable regions. */
export function isEditableTarget(target: unknown): boolean {
  if (!target || typeof target !== "object") return false;
  const el = target as {
    tagName?: string;
    isContentEditable?: boolean;
    type?: string;
    closest?: (sel: string) => unknown;
  };
  if (el.isContentEditable) return true;
  const tag = (el.tagName ?? "").toUpperCase();
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (el.type ?? "text").toLowerCase();
    return !["button", "checkbox", "radio", "submit", "reset", "range", "color", "file", "image"].includes(type);
  }
  if (typeof el.closest === "function") {
    try {
      return Boolean(el.closest("[contenteditable=''],[contenteditable='true'],[data-editable]"));
    } catch {
      return false;
    }
  }
  return false;
}

export function strokeFromEvent(e: KeyEventLike): Stroke {
  const code = CODE_ALIASES[e.code] ?? e.code;
  return {
    ctrl: Boolean(e.ctrlKey || e.metaKey),
    alt: Boolean(e.altKey),
    shift: Boolean(e.shiftKey),
    code,
  };
}

// ---------------------------------------------------------------------------
// Registry

interface Entry {
  binding: KeyBinding;
  strokes: Stroke[][];
  seq: number;
}

const entries = new Map<string, Entry>();
const contexts = new Map<string, () => boolean>();
let version = 0;
let seq = 0;
let browserMode = false;
const listeners = new Set<() => void>();
let pending: { strokes: Stroke[]; at: number } | null = null;
const CHORD_TIMEOUT_MS = 1500;

function changed() {
  version += 1;
  for (const l of listeners) l();
}

function activeChords(b: KeyBinding): readonly string[] {
  return browserMode && b.browserChords && b.browserChords.length > 0 ? b.browserChords : b.chords;
}

function compile(b: KeyBinding): Stroke[][] {
  const all = [...b.chords, ...(b.browserChords ?? [])];
  return all.map(parseChord);
}

/** Register a binding. Re-registering an id replaces it. Returns an unregister function. */
export function register(binding: KeyBinding): () => void {
  if (!binding.id) throw new Error("keys: binding needs an id");
  const entry: Entry = { binding, strokes: compile(binding), seq: (seq += 1) };
  entries.set(binding.id, entry);
  changed();
  return () => {
    if (entries.get(binding.id) === entry) {
      entries.delete(binding.id);
      changed();
    }
  };
}

/**
 * Declare a `when` context. The getter is read at dispatch time, so it can look
 * at live store state (`() => getState().screen === "review"`).
 */
export function defineContext(name: string, active: () => boolean): () => void {
  contexts.set(name, active);
  return () => {
    if (contexts.get(name) === active) contexts.delete(name);
  };
}

function isGlobal(when: KeyWhen | undefined): boolean {
  return !when || when === "global" || when === "always";
}

export function isContextActive(when: KeyWhen | undefined): boolean {
  if (isGlobal(when)) return true;
  if (typeof when === "function") {
    try {
      return Boolean(when());
    } catch {
      return false;
    }
  }
  const getter = contexts.get(when as string);
  if (!getter) return false;
  try {
    return Boolean(getter());
  } catch {
    return false;
  }
}

/** `rigorloom ui` in a browser uses `browserChords` where given. Tauri uses `chords`. */
export function setBrowserMode(on: boolean): void {
  if (browserMode !== on) {
    browserMode = on;
    changed();
  }
}

export function getBinding(id: string): KeyBinding | null {
  return entries.get(id)?.binding ?? null;
}

export function allBindings(): KeyBinding[] {
  return [...entries.values()].sort((a, b) => a.seq - b.seq).map((e) => e.binding);
}

/** Run a binding's action by id, as if its key were pressed. False when nothing is bound. */
export function runKeyAction(id: string): boolean {
  const b = entries.get(id)?.binding;
  if (!b) return false;
  return b.run({ code: "" }) !== false;
}

/** Keycaps for the binding's first active chord, or null when nothing is bound. */
export function keyHint(id: string): string[] | null {
  const b = entries.get(id)?.binding;
  if (!b) return null;
  const chord = activeChords(b)[0];
  return chord ? chordCaps(chord) : null;
}

/** The chord text for the binding's first active chord (`Ctrl+K`), or null. */
export function keyHintText(id: string): string | null {
  const caps = keyHint(id);
  return caps ? caps.join("+").replace(/\+ \+/g, " ") : null;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React hook: keycaps for an action id, kept in step with the registry. */
export function useKeyHint(id: string): string[] | null {
  useSyncExternalStore(
    subscribe,
    () => version,
    () => version,
  );
  return keyHint(id);
}

export interface ChordConflict {
  chord: string;
  when: string;
  profile: string;
  ids: string[];
}

/**
 * Two bindings conflict when, in the same `when` and profile, one's stroke
 * sequence equals the other's or is a prefix of it. A global binding also
 * conflicts with a scoped one on the same chord, because the scoped one would
 * silently shadow it whenever the scope is active.
 */
export function conflicts(list: KeyBinding[] = allBindings()): ChordConflict[] {
  const out: ChordConflict[] = [];
  const flat: Array<{ id: string; when: string; profile: string; key: string; chord: string }> = [];
  for (const b of list) {
    const when = isGlobal(b.when) ? "global" : typeof b.when === "function" ? `fn:${b.id}` : (b.when as string);
    const profile = b.profile ?? "standard";
    for (const chord of [...b.chords, ...(b.browserChords ?? [])]) {
      flat.push({ id: b.id, when, profile, key: chordId(chord), chord });
    }
  }
  const seen = new Set<string>();
  for (let i = 0; i < flat.length; i += 1) {
    for (let j = i + 1; j < flat.length; j += 1) {
      const a = flat[i];
      const b = flat[j];
      if (a.id === b.id || a.profile !== b.profile) continue;
      const sameScope = a.when === b.when || a.when === "global" || b.when === "global";
      if (!sameScope) continue;
      const clash = a.key === b.key || a.key.startsWith(`${b.key} `) || b.key.startsWith(`${a.key} `);
      if (!clash) continue;
      const tag = [a.id, b.id].sort().join("|") + a.key;
      if (seen.has(tag)) continue;
      seen.add(tag);
      out.push({ chord: a.chord, when: `${a.when}/${b.when}`, profile: a.profile, ids: [a.id, b.id] });
    }
  }
  return out;
}

/**
 * Chords that more than one binding would answer right now, given the
 * contexts and predicates as they stand. Predicate-scoped bindings (WP3's and
 * WP4's review keys) are separate scopes for `conflicts()`; this is the check
 * that their predicates really are exclusive in a given state.
 */
export function activeConflicts(): ChordConflict[] {
  const live = allBindings().filter((b) => isContextActive(b.when) && (b.profile ?? "standard") === "standard");
  const byChord = new Map<string, string[]>();
  for (const b of live) {
    for (const chord of activeChords(b)) {
      const key = chordId(chord);
      byChord.set(key, [...(byChord.get(key) ?? []), b.id]);
    }
  }
  return [...byChord.entries()]
    .filter(([, ids]) => new Set(ids).size > 1)
    .map(([chord, ids]) => ({ chord, when: "active", profile: "standard", ids: [...new Set(ids)] }));
}

function strokeEq(a: Stroke, b: Stroke): boolean {
  return a.ctrl === b.ctrl && a.alt === b.alt && a.shift === b.shift && a.code === b.code;
}

function seqStartsWith(chord: Stroke[], prefix: Stroke[]): boolean {
  if (prefix.length > chord.length) return false;
  return prefix.every((s, i) => strokeEq(s, chord[i]));
}

/**
 * Handle one keydown. Returns true when a binding ran (and the event was
 * prevented). Call it from the shell's single window listener only.
 */
export function dispatch(e: KeyEventLike, now: number = Date.now()): boolean {
  if (isComposingEvent(e)) return false;
  if (["Control", "Shift", "Alt", "Meta"].includes(e.key ?? "") || /^(Control|Shift|Alt|Meta|OS)(Left|Right)?$/.test(e.code)) {
    return false;
  }
  const stroke = strokeFromEvent(e);
  const editable = isEditableTarget(e.target);

  if (pending && now - pending.at > CHORD_TIMEOUT_MS) pending = null;
  const sequence = pending ? [...pending.strokes, stroke] : [stroke];

  const candidates = [...entries.values()]
    .filter((entry) => (entry.binding.profile ?? "standard") === "standard")
    .filter((entry) => isContextActive(entry.binding.when));

  // Scoped bindings win over global ones; among equals the latest registration wins.
  candidates.sort((a, b) => {
    const as = isGlobal(a.binding.when) ? 0 : 1;
    const bs = isGlobal(b.binding.when) ? 0 : 1;
    return bs - as || b.seq - a.seq;
  });

  let prefixMatch = false;
  for (const entry of candidates) {
    for (const chord of entry.strokes) {
      if (editable && !(entry.binding.inEditable ?? !isSingleKey(chord[0]))) continue;
      if (chord.length === sequence.length && seqStartsWith(chord, sequence)) {
        const result = entry.binding.run(e);
        if (result === false) continue;
        pending = null;
        e.preventDefault?.();
        return true;
      }
      if (chord.length > sequence.length && seqStartsWith(chord, sequence)) prefixMatch = true;
    }
  }

  if (prefixMatch) {
    pending = { strokes: sequence, at: now };
    e.preventDefault?.();
    return true;
  }
  pending = null;
  return false;
}

/** Test support: forget every binding and context. */
export function _resetForTest(): void {
  entries.clear();
  contexts.clear();
  pending = null;
  browserMode = false;
  changed();
}

export const keys = {
  register,
  activeConflicts,
  defineContext,
  dispatch,
  conflicts,
  keyHint,
  keyHintText,
  getBinding,
  allBindings,
  setBrowserMode,
};
