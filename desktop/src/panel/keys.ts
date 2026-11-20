/**
 * Key matching for the panel, pure so the IME rules can be unit-tested.
 *
 * - Letters and digits match the physical key (`e.code`), so 한/영 state never
 *   matters: `Y` is `KeyY` whether the keyboard is typing ㅛ or y.
 * - Nothing fires while a composition is in progress (`isComposing` or the
 *   229 keyCode some browsers send instead).
 * - A single key (no Ctrl, Alt or Meta) never fires in an editable target.
 */

export interface KeyContext {
  target: EventTarget | null;
  composing: boolean;
}

interface KeyLike {
  code: string;
  key: string;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  metaKey: boolean;
}

interface ParsedChord {
  ctrl: boolean;
  shift: boolean;
  alt: boolean;
  key: string;
}

export function parseChord(chord: string): ParsedChord {
  const parts = chord.split("+");
  const key = parts[parts.length - 1];
  const mods = new Set(parts.slice(0, -1).map((p) => p.toLowerCase()));
  return { ctrl: mods.has("ctrl"), shift: mods.has("shift"), alt: mods.has("alt"), key };
}

/** The `e.code` a chord's key stands for, or null when `e.key` decides. */
function codeFor(key: string): string | null {
  if (/^[A-Z]$/.test(key)) return `Key${key}`;
  if (/^[0-9]$/.test(key)) return `Digit${key}`;
  return null;
}

export function chordMatches(chord: string, e: KeyLike): boolean {
  const p = parseChord(chord);
  if (p.ctrl !== (e.ctrlKey || e.metaKey)) return false;
  if (p.alt !== e.altKey) return false;
  const code = codeFor(p.key);
  if (code) {
    // Letters ignore Shift unless the chord names it; Shift+Y is not Y.
    if (p.shift !== e.shiftKey) return false;
    return e.code === code;
  }
  if (p.shift !== e.shiftKey) return false;
  return e.key === p.key || e.code === p.key;
}

export function isSingleKey(chord: string): boolean {
  const p = parseChord(chord);
  return !p.ctrl && !p.alt;
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const el = target as { tagName?: string; isContentEditable?: boolean; type?: string };
  const tag = (el.tagName ?? "").toUpperCase();
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (el.type ?? "text").toLowerCase();
    return !["checkbox", "radio", "button", "submit", "reset"].includes(type);
  }
  return el.isContentEditable === true;
}

/** Whether a matched chord may fire in this context. */
export function bindingAllows(chord: string, ctx: KeyContext): boolean {
  if (ctx.composing) return false;
  if (isSingleKey(chord) && isEditableTarget(ctx.target)) return false;
  return true;
}

/** Whether a raw keyboard event is part of an IME composition. */
export function eventIsComposing(e: { isComposing?: boolean; keyCode?: number; nativeEvent?: { isComposing?: boolean } }): boolean {
  return Boolean(e.isComposing || e.nativeEvent?.isComposing || e.keyCode === 229);
}

/** The panel's bindings, as data (J1 §3 keyboard). */
export const PANEL_CHORDS = {
  "change.next": ["J", "ArrowDown", "Alt+ArrowDown"],
  "change.prev": ["K", "ArrowUp", "Alt+ArrowUp"],
  "change.accept": ["Y"],
  "change.reject": ["N"],
  "change.edit": ["E"],
  "change.undo": ["U"],
  "change.acceptAll": ["Ctrl+Shift+Y"],
  "proposal.return": ["R"],
  "approval.open": ["Ctrl+Shift+Enter"],
  "composer.focus": ["Ctrl+L"],
  "panel.changes": ["Alt+6"],
  "panel.agent": ["Alt+7"],
  "panel.checks": ["Alt+8", "Ctrl+Shift+M"],
  "checks.style": ["F8"],
} as const satisfies Record<string, readonly string[]>;

export type PanelKeyId = keyof typeof PANEL_CHORDS;

/** Find the panel action for an event, honouring every rule above. */
export function matchPanelKey(e: KeyLike & { target?: EventTarget | null; isComposing?: boolean; keyCode?: number }): PanelKeyId | null {
  const ctx: KeyContext = { target: e.target ?? null, composing: eventIsComposing(e) };
  for (const [id, chords] of Object.entries(PANEL_CHORDS) as [PanelKeyId, readonly string[]][]) {
    for (const chord of chords) {
      if (chordMatches(chord, e) && bindingAllows(chord, ctx)) return id;
    }
  }
  return null;
}
