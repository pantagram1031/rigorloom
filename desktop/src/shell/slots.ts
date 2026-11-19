/**
 * Slot registry: how every work package mounts into the shell (J1 §5).
 *
 * Nobody but the shell edits `App.tsx` or `main.tsx`. Each package ships
 * `desktop/src/<dir>/register.ts`, which calls `registerSlot(...)` at import
 * time; `shell/registrations.ts` loads every such file with
 * `import.meta.glob`. A slot nobody registered renders a quiet placeholder,
 * so a package that has not landed yet leaves the shell intact.
 *
 * Slots:
 * - `canvas`        the desk and paper (WP3)
 * - `rightPanel`    the 변경 · 에이전트 · 점검 panel (WP4)
 * - `pane:<id>`     a left pane; the shell owns the tab row. Ids it shows:
 *                   `files`, `outline`, `blanks`, `find`, `history`
 * - `stripStart`, `stripEnd`   the document strip's two ends
 * - `statusLeft`, `statusRight` status bar items (text only)
 * - `narrowSheet`   the bottom sheet under 600 px (WP9)
 * - `settings:<id>` a section in the 설정 dialog (e.g. `settings:agent`)
 *
 * Several packages may register into one slot; entries render in `order`.
 * Single-occupant slots (`canvas`, `rightPanel`, `narrowSheet`, `pane:*`) use
 * the entry with the lowest order.
 *
 * No React import beyond types, so node tests load this file.
 */
import type { ComponentType } from "react";

import type { UiLanguage } from "../types";

export type FixedSlotName =
  | "canvas"
  | "rightPanel"
  | "stripStart"
  | "stripEnd"
  | "statusLeft"
  | "statusRight"
  | "narrowSheet";

export type SlotName = FixedSlotName | `pane:${string}` | `settings:${string}`;

/** Every slot component receives the document it belongs to (null on the Start tab). */
export interface SlotProps {
  sessionId: string | null;
}

export interface SlotOptions {
  /** Lower renders first. Default 100. */
  order?: number;
  /** Section or pane title, for `settings:*`. Strings come from the caller's i18n/v2 table. */
  title?: (lang: UiLanguage) => string;
  /** Hide the entry when this returns false (read at render time). */
  when?: (sessionId: string | null) => boolean;
  /** Which package registered it; shown in the placeholder and in tests. */
  owner?: string;
}

export interface SlotEntry {
  name: SlotName;
  component: ComponentType<SlotProps>;
  order: number;
  title?: (lang: UiLanguage) => string;
  when?: (sessionId: string | null) => boolean;
  owner?: string;
  seq: number;
}

/** Slots that hold exactly one component. */
export function isSingleSlot(name: SlotName): boolean {
  return name === "canvas" || name === "rightPanel" || name === "narrowSheet" || name.startsWith("pane:");
}

const VALID_FIXED = new Set<string>([
  "canvas",
  "rightPanel",
  "stripStart",
  "stripEnd",
  "statusLeft",
  "statusRight",
  "narrowSheet",
]);

export function isSlotName(name: string): name is SlotName {
  return VALID_FIXED.has(name) || /^pane:[a-z][a-zA-Z0-9-]*$/.test(name) || /^settings:[a-z][a-zA-Z0-9-]*$/.test(name);
}

const registry = new Map<SlotName, SlotEntry[]>();
const listeners = new Set<() => void>();
let version = 0;
let seq = 0;

function changed() {
  version += 1;
  for (const l of listeners) l();
}

/**
 * Mount a component into a slot. Returns an unregister function (used by
 * tests and hot reload). Registering the same component twice in one slot is
 * a no-op, so module re-evaluation under HMR does not duplicate entries.
 */
export function registerSlot(
  name: SlotName,
  component: ComponentType<SlotProps>,
  options: SlotOptions = {},
): () => void {
  if (!isSlotName(name)) throw new Error(`slots: unknown slot "${name}"`);
  const list = registry.get(name) ?? [];
  const existing = list.find((e) => e.component === component);
  if (existing) return () => unregister(name, existing);
  const entry: SlotEntry = {
    name,
    component,
    order: options.order ?? 100,
    title: options.title,
    when: options.when,
    owner: options.owner,
    seq: (seq += 1),
  };
  registry.set(name, [...list, entry].sort((a, b) => a.order - b.order || a.seq - b.seq));
  changed();
  return () => unregister(name, entry);
}

function unregister(name: SlotName, entry: SlotEntry) {
  const list = registry.get(name);
  if (!list) return;
  const next = list.filter((e) => e !== entry);
  if (next.length === list.length) return;
  if (next.length === 0) registry.delete(name);
  else registry.set(name, next);
  changed();
}

/** Entries for a slot, in render order. Single slots return at most one. */
export function slotEntries(name: SlotName): SlotEntry[] {
  const list = registry.get(name) ?? [];
  return isSingleSlot(name) ? list.slice(0, 1) : list;
}

export function hasSlot(name: SlotName): boolean {
  return (registry.get(name)?.length ?? 0) > 0;
}

/** Every registered slot name starting with `prefix` (`pane:`, `settings:`). */
export function slotNames(prefix: "pane:" | "settings:"): SlotName[] {
  return [...registry.keys()].filter((n) => n.startsWith(prefix)).sort((a, b) => {
    const ao = registry.get(a)?.[0]?.order ?? 100;
    const bo = registry.get(b)?.[0]?.order ?? 100;
    return ao - bo || a.localeCompare(b);
  });
}

export function subscribeSlots(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function slotsVersion(): number {
  return version;
}

/** Test support. */
export function _resetSlotsForTest(): void {
  registry.clear();
  changed();
}
