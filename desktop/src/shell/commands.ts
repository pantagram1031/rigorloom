/**
 * Command registry: the rows of the 명령창 and the app menu (J1 §5 `registerCommand`).
 *
 * A command names an action once. Its key hint comes from the key registry
 * through `keyId`, so the palette row and the binding can never disagree.
 */
import { useSyncExternalStore } from "react";

import type { UiLanguage } from "../types";

export type CommandGroup = "file" | "edit" | "view" | "document" | "review" | "help";

export interface Command {
  /** Stable id, e.g. `shell.openFile`. */
  id: string;
  /** Display name, from the caller's i18n/v2 table. A plain string is accepted too. */
  title: string | ((lang: UiLanguage) => string);
  group?: CommandGroup;
  /** Extra search words (both languages). */
  keywords?: (lang: UiLanguage) => string[];
  /** Key registry id whose first chord is shown as the hint. Defaults to `id`. */
  keyId?: string;
  /** Hide the row when false (read when the palette opens). */
  when?: () => boolean;
  /** Show the row but disabled when false. */
  enabled?: () => boolean;
  /** Whether the row appears in the app menu as well as the palette. */
  menu?: boolean;
  run: () => void | Promise<void>;
}

const commands = new Map<string, Command>();
const listeners = new Set<() => void>();
let version = 0;

function changed() {
  version += 1;
  for (const l of listeners) l();
}

export function commandTitle(c: Command, lang: UiLanguage): string {
  return typeof c.title === "function" ? c.title(lang) : c.title;
}

export function registerCommand(command: Command): () => void {
  commands.set(command.id, command);
  changed();
  return () => {
    if (commands.get(command.id) === command) {
      commands.delete(command.id);
      changed();
    }
  };
}

export function getCommand(id: string): Command | null {
  return commands.get(id) ?? null;
}

export function allCommands(): Command[] {
  return [...commands.values()];
}

/** Commands visible right now (their `when` holds). */
export function visibleCommands(): Command[] {
  return allCommands().filter((c) => {
    try {
      return !c.when || c.when();
    } catch {
      return false;
    }
  });
}

export function runCommand(id: string): boolean {
  const c = commands.get(id);
  if (!c) return false;
  if (c.when && !c.when()) return false;
  if (c.enabled && !c.enabled()) return false;
  void c.run();
  return true;
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function useCommandsVersion(): number {
  return useSyncExternalStore(subscribe, () => version, () => version);
}

/**
 * Score a command title against a query: 0 = no match. Prefix beats word start
 * beats substring; every query character must appear in order.
 */
export function matchScore(text: string, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 1;
  const t = text.toLowerCase();
  if (t.startsWith(q)) return 100 - Math.min(t.length - q.length, 50);
  const idx = t.indexOf(q);
  if (idx >= 0) return (/[\s·,(]/.test(t[idx - 1] ?? " ") ? 70 : 50) - Math.min(idx, 20);
  let ti = 0;
  for (const ch of q.replace(/\s+/g, "")) {
    ti = t.indexOf(ch, ti);
    if (ti < 0) return 0;
    ti += 1;
  }
  return 10;
}

/** Test support. */
export function _resetCommandsForTest(): void {
  commands.clear();
  changed();
}
