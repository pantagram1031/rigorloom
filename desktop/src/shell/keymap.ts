/**
 * The one shipped keymap, as data (J1 §3 Keyboard; D1 §4 with J1's deltas).
 *
 * Every product key is listed here, whoever handles it, so the duplicate-chord
 * test covers the whole product and a hint can be shown before its package
 * lands. A package attaches behaviour with `bindKey(id, run)`; `keys.register`
 * stays available for keys that are not product-wide.
 *
 * Contexts (`when`), and who defines them with `keys.defineContext`:
 * - `docOpen`   a document tab is active (WP2)
 * - `palette`   the 명령창 is open (WP2)
 * - `review`    a document with changes is active, no sheet or popover open (WP4)
 * - `sheet`     the approval sheet is open (WP4)
 * - `pageEdit`  the in-place editor has focus (WP3; keys there have `inEditable`)
 * - `composer`  the agent composer has focus (WP4; keys there have `inEditable`)
 * Owners keep `review` and `sheet` mutually exclusive.
 */
import { chordCaps, type KeyBinding, register } from "./keys.ts";

export type KeymapEntry = Omit<KeyBinding, "run">;

export const SHELL_BINDINGS: KeymapEntry[] = [
  // global: shell (WP2)
  { id: "shell.palette", chords: ["Ctrl+K", "Ctrl+Shift+P"] },
  { id: "shell.openFile", chords: ["Ctrl+O", "Alt+O"] },
  { id: "shell.openFolder", chords: ["Ctrl+Shift+O"] },
  { id: "shell.newTab", chords: ["Ctrl+T"], browserChords: ["Alt+T"] },
  { id: "shell.closeTab", chords: ["Ctrl+W"], browserChords: ["Alt+W"] },
  { id: "shell.nextTab", chords: ["Ctrl+Tab"], browserChords: ["Alt+."] },
  { id: "shell.prevTab", chords: ["Ctrl+Shift+Tab"], browserChords: ["Alt+,"] },
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => ({ id: `shell.tab${n}`, chords: [`Ctrl+${n}`] })),
  { id: "shell.pane.files", chords: ["Alt+1"] },
  { id: "shell.pane.outline", chords: ["Alt+2"] },
  { id: "shell.pane.blanks", chords: ["Alt+3"] },
  { id: "shell.pane.find", chords: ["Alt+4"] },
  { id: "shell.pane.history", chords: ["Alt+5"] },
  { id: "shell.toggleLeft", chords: ["Ctrl+B"] },
  { id: "shell.toggleRight", chords: ["Ctrl+Alt+B"] },
  { id: "shell.settings", chords: ["Ctrl+,"] },
  { id: "shell.fullscreen", chords: ["F11"] },
  { id: "shell.save", chords: ["Ctrl+S", "Alt+S"] },
  { id: "shell.escape", chords: ["Escape"] },

  // global: canvas (WP3)
  { id: "canvas.zoomIn", chords: ["Ctrl+="] },
  { id: "canvas.zoomOut", chords: ["Ctrl+-"] },
  { id: "canvas.fitWidth", chords: ["Ctrl+0"] },
  { id: "canvas.fitPage", chords: ["Ctrl+Shift+0"] },
  { id: "canvas.nextPage", chords: ["Alt+PageDown"] },
  { id: "canvas.prevPage", chords: ["Alt+PageUp"] },
  { id: "canvas.find", chords: ["Ctrl+F"] },
  { id: "canvas.replace", chords: ["Ctrl+H"] },
  { id: "canvas.findNext", chords: ["F3"] },
  { id: "canvas.findPrev", chords: ["Shift+F3"] },
  { id: "canvas.goto", chords: ["Alt+G"] },
  { id: "canvas.charShape", chords: ["Alt+L"] },
  { id: "canvas.undo", chords: ["Ctrl+Z"], inEditable: false },
  { id: "canvas.redo", chords: ["Ctrl+Shift+Z", "Ctrl+Y"], inEditable: false },
  { id: "canvas.edit", chords: ["F2"], when: "docOpen" },

  // panel (WP4). Ids and chords are WP4's (panel/keys.ts PANEL_CHORDS);
  // WP4 registers them with its own `when` predicates, replacing these entries.
  { id: "panel.changes", chords: ["Alt+6"] },
  { id: "panel.agent", chords: ["Alt+7"] },
  { id: "panel.checks", chords: ["Alt+8", "Ctrl+Shift+M"] },
  { id: "composer.focus", chords: ["Ctrl+L"] },
  { id: "composer.send", chords: ["Enter"], when: "composer", inEditable: true },
  { id: "checks.style", chords: ["F8"] },
  { id: "change.next", chords: ["J", "ArrowDown", "Alt+ArrowDown"], when: "review" },
  { id: "change.prev", chords: ["K", "ArrowUp", "Alt+ArrowUp"], when: "review" },
  { id: "change.accept", chords: ["Y"], when: "review" },
  { id: "change.reject", chords: ["N"], when: "review" },
  { id: "change.edit", chords: ["E"], when: "review" },
  { id: "change.undo", chords: ["U"], when: "review" },
  { id: "change.open", chords: ["Enter"], when: "review" },
  { id: "change.acceptAll", chords: ["Ctrl+Shift+Y"], when: "review" },
  { id: "proposal.return", chords: ["R"], when: "review" },
  { id: "approval.open", chords: ["Ctrl+Shift+Enter"], when: "review" },
  { id: "canvas.cycleView", chords: ["V"], when: "review" },

  // approval sheet (WP4)
  { id: "sheet.confirm", chords: ["Enter"], when: "sheet" },
  { id: "sheet.tick", chords: ["Space"], when: "sheet" },

  // history (WP5)
  { id: "history.export", chords: ["Ctrl+E", "Alt+V"] },
  { id: "history.exportPdf", chords: ["Ctrl+P", "Alt+P"] },

  // palette (WP2)
  { id: "palette.down", chords: ["ArrowDown"], when: "palette", inEditable: true },
  { id: "palette.up", chords: ["ArrowUp"], when: "palette", inEditable: true },
  { id: "palette.run", chords: ["Enter"], when: "palette", inEditable: true },
];

/**
 * Reserved and unbound (D1 §4, J1): `Ctrl+N`, `Alt+T` (문단 모양; `Alt+T` is the
 * browser-mode new tab here instead), `F7`, `Ctrl+B/I/U` formatting. `Ctrl+B`
 * is taken by the left-pane toggle, as in every editor people know; formatting
 * waits for real formatting (D1 §9).
 */
export const RESERVED_CHORDS = ["Ctrl+N", "F7", "Ctrl+I", "Ctrl+U"] as const;

const byId = new Map(SHELL_BINDINGS.map((b) => [b.id, b]));

export function keymapEntry(id: string): KeymapEntry | null {
  return byId.get(id) ?? null;
}

export function keymapChord(id: string): string[] | undefined {
  const chord = byId.get(id)?.chords[0];
  return chord ? chordCaps(chord) : undefined;
}

/**
 * Attach behaviour to a keymap id. Throws for an id not in the keymap, so a
 * typo cannot silently register nothing. Returns the unregister function.
 */
export function bindKey(id: string, run: KeyBinding["run"], overrides: Partial<KeymapEntry> = {}): () => void {
  const entry = byId.get(id);
  if (!entry) throw new Error(`keymap: unknown id "${id}"`);
  return register({ ...entry, ...overrides, id, run });
}
