/**
 * Where focus lands. Guarded so Node tests without a document are no-ops.
 */

function focusEl(el: HTMLElement | null | undefined): boolean {
  if (!el || typeof el.focus !== "function") return false;
  el.focus({ preventScroll: true });
  return true;
}

export function focusDocumentSurface(): boolean {
  if (typeof document === "undefined") return false;
  const el =
    document.querySelector<HTMLElement>('[data-testid="text-view"]') ??
    document.querySelector<HTMLElement>('[data-testid="paper"]') ??
    document.querySelector<HTMLElement>('[data-testid="page-preview"]');
  return focusEl(el);
}

export function focusHunkAt(index: number): boolean {
  if (typeof document === "undefined") return false;
  const cards = document.querySelectorAll<HTMLElement>(".hunk-card");
  return focusEl(cards[index] ?? null);
}

export function focusFirstHunk(): boolean {
  return focusHunkAt(0);
}
