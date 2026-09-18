/** Keyboard helpers shared by Tabs, RadioGroup, ToggleGroup, and menus. */

export function isActivateKey(key: string): boolean {
  return key === "Enter" || key === " ";
}

export function isPrintableTypeahead(key: string, ev: { ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean }): boolean {
  if (key.length !== 1) return false;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return false;
  if (key === " ") return false;
  return true;
}

export function moveRoving(count: number, index: number, key: string): number {
  if (count <= 0) return 0;
  const i = Math.min(Math.max(index, 0), count - 1);
  if (key === "ArrowDown" || key === "ArrowRight") return (i + 1) % count;
  if (key === "ArrowUp" || key === "ArrowLeft") return (i - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return i;
}

/** First-letter (or buffer) typeahead. Searches forward from `from`. */
export function typeaheadIndex(labels: string[], from: number, query: string): number {
  const q = query.toLowerCase();
  if (!q || labels.length === 0) return Math.max(0, from);
  const n = labels.length;
  const start = Math.min(Math.max(from, 0), n - 1);
  for (let step = 0; step < n; step++) {
    const idx = (start + step) % n;
    if (labels[idx].trim().toLowerCase().startsWith(q)) return idx;
  }
  return start;
}

export const TABBABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function cycleTabIndex(count: number, index: number, shift: boolean): number {
  if (count <= 0) return 0;
  if (shift) return index <= 0 ? count - 1 : index - 1;
  return index >= count - 1 ? 0 : index + 1;
}

/** When Tab would leave the trap, return the index to focus; otherwise null (let the browser move). */
export function trapTabIndex(count: number, index: number, shift: boolean): number | null {
  if (count <= 0) return 0;
  if (shift && index <= 0) return count - 1;
  if (!shift && (index < 0 || index >= count - 1)) return 0;
  return null;
}
